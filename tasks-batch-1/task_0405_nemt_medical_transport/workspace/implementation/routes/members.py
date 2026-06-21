"""Member, EligibilitySpan, and member-scoped list endpoints."""
from flask import Blueprint

from db import db, new_common, new_immutable_common, touch
from errors import err
from helpers import (get_json_body, paginate, parse_pagination, require_enum,
                     require_string)
from middleware import require_roles
from response import ok_list, ok_object
from serializers import serialize, serialize_list
from services.cascades import eligibility_lapse_cascade
from services.eligibility import has_coverage_now

bp = Blueprint("members", __name__)

MOBILITY = {"AMBULATORY", "WHEELCHAIR", "STRETCHER"}
LOS = {"ROUTINE", "URGENT", "BARIATRIC"}


def get_member_or_404(member_id):
    m = db.members.get(member_id)
    if m is None:
        raise err("ERR_NOT_FOUND", "Member not found")
    return m


@bp.route("/members", methods=["POST"])
def create_member():
    require_roles("Coordinator")
    body = get_json_body()
    medicaid_id = require_string(body, "medicaid_id")
    full_name = require_string(body, "full_name")
    mobility_level = require_enum(body, "mobility_level", MOBILITY)
    home_county = require_string(body, "home_county")

    member = new_common()
    member.update({
        "medicaid_id": medicaid_id,
        "full_name": full_name,
        "mobility_level": mobility_level,
        "home_county": home_county,
        "eligibility_status": "ELIGIBLE",
        "noshow_strike_count": 0,
        "standing_orders_paused": False,
    })
    db.members[member["id"]] = member
    return ok_object(serialize(member), status=201)


@bp.route("/members/<member_id>", methods=["GET"])
def get_member(member_id):
    require_roles("Coordinator", "Broker", "Auditor", "Driver")
    return ok_object(serialize(get_member_or_404(member_id)))


@bp.route("/members/<member_id>/eligibility/recompute", methods=["POST"])
def recompute_eligibility(member_id):
    require_roles("Coordinator")
    member = get_member_or_404(member_id)
    if member["eligibility_status"] == "TERMINATED":
        # Terminal posture: recompute is a no-op (no defined transition).
        return ok_object(serialize(member))

    covered = has_coverage_now(member_id)
    status = member["eligibility_status"]
    if status == "ELIGIBLE" and not covered:
        member["eligibility_status"] = "SUSPENDED"
        eligibility_lapse_cascade(member)
        touch(member)
    elif status == "SUSPENDED" and covered:
        member["eligibility_status"] = "ELIGIBLE"
        member["standing_orders_paused"] = False  # no auto-resume of paused orders
        touch(member)
    return ok_object(serialize(member))


@bp.route("/members/<member_id>/terminate", methods=["POST"])
def terminate_member(member_id):
    require_roles("Coordinator")
    member = get_member_or_404(member_id)
    if member["eligibility_status"] == "TERMINATED":
        raise err("ERR_INVALID_STATE", "Member already terminated")
    # In-flight work blocks termination (PRD 3.1).
    for trip in db.trips.values():
        if trip["member_id"] == member_id and trip["trip_status"] in ("ASSIGNED", "IN_PROGRESS"):
            raise err("ERR_DEPENDENCY_EXISTS", "Member has in-flight ASSIGNED/IN_PROGRESS trips")
    member["eligibility_status"] = "TERMINATED"
    for so in db.standing_orders.values():
        if so["member_id"] == member_id and so["status"] in ("ACTIVE", "PAUSED"):
            so["status"] = "CANCELLED"
            touch(so)
    touch(member)
    return ok_object(serialize(member))


@bp.route("/members/<member_id>/eligibility-spans", methods=["GET"])
def list_member_spans(member_id):
    require_roles("Coordinator", "Auditor")
    get_member_or_404(member_id)
    limit, offset = parse_pagination()
    items = [s for s in db.eligibility_spans.values() if s["member_id"] == member_id]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    page, total = paginate(items, limit, offset)
    return ok_list(serialize_list(page), limit, offset, total)


@bp.route("/members/<member_id>/trips", methods=["GET"])
def list_member_trips(member_id):
    require_roles("Coordinator", "Broker", "Auditor")
    get_member_or_404(member_id)
    limit, offset = parse_pagination()
    items = [t for t in db.trips.values() if t["member_id"] == member_id]
    items.sort(key=lambda t: (t["created_at"], t["_seq"]))
    page, total = paginate(items, limit, offset)
    return ok_list(serialize_list(page), limit, offset, total)


@bp.route("/members/<member_id>/standing-orders", methods=["GET"])
def list_member_standing_orders(member_id):
    require_roles("Coordinator")
    get_member_or_404(member_id)
    limit, offset = parse_pagination()
    items = [s for s in db.standing_orders.values() if s["member_id"] == member_id]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    page, total = paginate(items, limit, offset)
    return ok_list(serialize_list(page), limit, offset, total)


# ---- EligibilitySpan ----

@bp.route("/eligibility-spans", methods=["POST"])
def create_span():
    require_roles("Coordinator")
    body = get_json_body()
    # FK existence (priority 4) is checked after field validation here only after
    # required-field presence; but invalid enum is priority 16 (last). We validate
    # presence/format, then FK, mirroring the global ordering where FK_NOT_FOUND
    # (422) precedes INVALID_REQUEST (400) only when both could fire — required
    # fields must exist to evaluate FK.
    if "member_id" not in body or body["member_id"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: member_id")
    member_id = body["member_id"]
    if member_id not in db.members:
        raise err("ERR_FK_NOT_FOUND", "member_id does not reference an existing Member")
    level_of_service = require_enum(body, "level_of_service", LOS)
    from helpers import parse_dt
    if "coverage_start" not in body or body["coverage_start"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: coverage_start")
    if "coverage_end" not in body or body["coverage_end"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: coverage_end")
    parse_dt(body["coverage_start"])
    parse_dt(body["coverage_end"])

    span = new_immutable_common()
    span.update({
        "member_id": member_id,
        "level_of_service": level_of_service,
        "coverage_start": body["coverage_start"],
        "coverage_end": body["coverage_end"],
        "voided": False,
    })
    db.eligibility_spans[span["id"]] = span
    return ok_object(serialize(span), status=201)


@bp.route("/eligibility-spans/<span_id>/void", methods=["POST"])
def void_span(span_id):
    require_roles("Coordinator")
    span = db.eligibility_spans.get(span_id)
    if span is None:
        raise err("ERR_NOT_FOUND", "EligibilitySpan not found")
    span["voided"] = True  # immutable record; only the voided flag may flip
    return ok_object(serialize(span))
