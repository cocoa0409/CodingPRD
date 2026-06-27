"""Provider endpoints and provider-scoped lists (PRD §3.1, §3.5)."""
from flask import Blueprint, request

import db
import errors
import response
import serialize
import validate
from middleware import authenticate, require_roles
from routes.helpers import get_or_404
from services import domain
from timeutil import parse_iso

bp = Blueprint("providers", __name__)


@bp.route("/providers", methods=["POST"])
def create_provider():
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin"})
    data = validate.body()

    practice_id = validate.require(data, "practice_id", str)
    full_name = validate.require(data, "full_name", str)
    npi = validate.require(data, "npi", str)
    panel_capacity = validate.optional(data, "panel_capacity", int, None)
    accepting = validate.optional(data, "accepting_new_members", bool, True)

    # Existence (priority 3) before business validation.
    get_or_404("practice", practice_id)

    if panel_capacity is not None and panel_capacity <= 0:
        raise errors.validation("panel_capacity must be null or > 0.")

    # npi unique within the practice (PRD §3.1).
    for p in db.providers.values():
        if p["practice_id"] == practice_id and p["npi"] == npi:
            raise errors.validation("npi must be unique within the practice.")

    e = dict(db.common_fields())
    e["id"] = db.new_id()
    e["_seq"] = db.next_seq()
    e["practice_id"] = practice_id
    e["full_name"] = full_name
    e["npi"] = npi
    e["panel_capacity"] = panel_capacity
    e["accepting_new_members"] = accepting
    e["active_panel_count"] = 0
    e["panel_load_bucket"] = "UNDER_TARGET"
    db.providers[e["id"]] = e
    return response.object_response(serialize.provider(e), 201)


@bp.route("/providers/<pid>", methods=["GET"])
def get_provider(pid):
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Provider", "Member"})
    e = get_or_404("provider", pid)
    return response.object_response(serialize.provider(e), 200)


@bp.route("/providers", methods=["GET"])
def list_providers():
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Provider", "Member"})
    limit, offset = validate.pagination()

    practice_id = request.args.get("practice_id")
    accepting_raw = request.args.get("accepting_new_members")

    rows = list(db.providers.values())
    if practice_id is not None:
        rows = [r for r in rows if r["practice_id"] == practice_id]
    if accepting_raw is not None:
        want = accepting_raw.lower() == "true"
        rows = [r for r in rows if r["accepting_new_members"] == want]

    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(
        [serialize.provider(r) for r in page], limit, offset, total, 200
    )


@bp.route("/providers/<pid>/members", methods=["GET"])
def list_provider_members(pid):
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Provider"})
    get_or_404("provider", pid)
    limit, offset = validate.pagination()

    rows = [m for m in db.members.values() if m.get("assigned_provider_id") == pid]
    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(
        [serialize.member(r) for r in page], limit, offset, total, 200
    )


@bp.route("/providers/<pid>/visit-slots", methods=["GET"])
def list_provider_slots(pid):
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Provider", "Member"})
    get_or_404("provider", pid)
    limit, offset = validate.pagination()

    rows = [s for s in db.visit_slots.values() if s["provider_id"] == pid]
    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(
        [serialize.visit_slot(r) for r in page], limit, offset, total, 200
    )


@bp.route("/providers/<pid>/visit-slots", methods=["POST"])
def create_visit_slot(pid):
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Provider"})
    provider = get_or_404("provider", pid)
    # Provider ownership: a provider may only publish on its own id.
    if caller.role == "Provider" and caller.user_id != pid:
        raise errors.forbidden("Provider does not own this provider resource.")

    data = validate.body()
    slot_type = validate.require(data, "slot_type", str)
    validate.enum(slot_type, {"IN_PERSON", "VIRTUAL"}, "slot_type")
    starts_raw = validate.require(data, "starts_at", str)
    ends_raw = validate.require(data, "ends_at", str)
    virtual_capacity = validate.optional(data, "virtual_capacity", int, 1)

    try:
        starts_at = parse_iso(starts_raw)
        ends_at = parse_iso(ends_raw)
    except ValueError:
        raise errors.invalid_request("starts_at/ends_at must be ISO 8601 timestamps.")

    if virtual_capacity < 1:
        raise errors.validation("virtual_capacity must be >= 1.")
    # ends_at strictly after starts_at (PRD §3.5).
    if ends_at <= starts_at:
        raise errors.validation("ends_at must be strictly after starts_at.")

    e = dict(db.common_fields())
    e["id"] = db.new_id()
    e["_seq"] = db.next_seq()
    e["provider_id"] = pid
    e["slot_type"] = slot_type
    e["starts_at"] = starts_at
    e["ends_at"] = ends_at
    e["virtual_capacity"] = virtual_capacity
    e["booked_count"] = 0
    e["slot_state"] = "OPEN"
    db.visit_slots[e["id"]] = e
    return response.object_response(serialize.visit_slot(e), 201)


@bp.route("/visit-slots/<sid>", methods=["GET"])
def get_visit_slot(sid):
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Provider", "Member"})
    e = get_or_404("visit_slot", sid)
    return response.object_response(serialize.visit_slot(e), 200)
