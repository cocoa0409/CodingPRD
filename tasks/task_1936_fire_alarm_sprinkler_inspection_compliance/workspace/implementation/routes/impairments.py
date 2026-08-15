"""Impairment endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from db import store
from middleware import (
    require_roles, ALL_ROLES,
    ROLE_CONTRACTOR_ADMIN, ROLE_FIRE_MARSHAL,
)
from response import success_object, list_response
from util import get_body, check_unknown_fields, req_enum, req_datetime
from errors import invalid_state, invalid_date_range, impairment_overlap
from services.core import (
    base_record, public, touch,
    get_system, get_impairment,
    contractor_of_system, property_of_system,
    require_contractor_active, require_property_active,
)
from services import calc

bp = Blueprint("impairments", __name__)

IMPAIRMENT_KINDS = {"PLANNED", "UNPLANNED"}


def create_impairment_record(sys, kind, planned_start, planned_end, internal=False):
    """Shared creation path for client-opened and permit-auto-created impairments."""
    now = store.now()
    if kind == "PLANNED":
        deadline = planned_start - timedelta(hours=calc.PLANNED_NOTIFY_BEFORE_HOURS)
    else:
        deadline = now + timedelta(hours=calc.UNPLANNED_NOTIFY_AFTER_HOURS)
    rec = base_record()
    rec.update({
        "system_id": sys["id"],
        "impairment_kind": kind,
        "planned_start": planned_start,
        "planned_end": planned_end,
        "notification_deadline": deadline,
        "authority_notified_at": None,
        "notification_late": False,
        "discovered_at": now,
        "restored_at": None,
        "status": "OPEN",
    })
    store.impairments[rec["id"]] = rec
    calc.derive_impairment_status(sys)
    return rec


@bp.route("/fire-compliance/systems/<sid>/impairments", methods=["POST"])
def create_impairment(sid):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    sys = get_system(sid)
    body = get_body()
    check_unknown_fields(body, {"impairment_kind", "planned_start", "planned_end"})
    planned_start = req_datetime(body, "planned_start")
    planned_end = req_datetime(body, "planned_end")
    prop = property_of_system(sys)
    con = contractor_of_system(sys)
    require_contractor_active(con)
    require_property_active(prop)
    if sys["status"] != "IN_SERVICE":
        raise invalid_state("ProtectedSystem is DECOMMISSIONED")
    # date range (10): end strictly after start
    if not planned_end > planned_start:
        raise invalid_date_range("planned_end must be strictly after planned_start")
    impairment_kind = req_enum(body, "impairment_kind", IMPAIRMENT_KINDS)

    # overlap + 4h re-certification buffer (11): only for new PLANNED rows,
    # against other non-CLOSED impairments on the same system
    if impairment_kind == "PLANNED":
        for other in store.impairments.values():
            if other["system_id"] != sys["id"] or other["status"] == "CLOSED":
                continue
            # half-open [start, end) overlap
            if planned_start < other["planned_end"] and other["planned_start"] < planned_end:
                raise impairment_overlap("Impairment window overlaps an existing impairment")
            # buffer: when the other ends at or before the new start, the new
            # start must be at least 4h after the other's end
            if other["planned_end"] <= planned_start and \
                    planned_start < other["planned_end"] + timedelta(hours=calc.IMPAIRMENT_BUFFER_HOURS):
                raise impairment_overlap("Impairment starts inside the 4-hour re-certification buffer")

    rec = create_impairment_record(sys, impairment_kind, planned_start, planned_end)
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(rec), status=201)


@bp.route("/fire-compliance/systems/<sid>/impairments", methods=["GET"])
def list_impairments(sid):
    require_roles(ALL_ROLES)
    sys = get_system(sid)
    status = request.args.get("status")
    rows = [i for i in store.impairments.values() if i["system_id"] == sys["id"]]
    if status is not None:
        rows = [i for i in rows if i["status"] == status]
    return list_response(rows, request.args, public)


@bp.route("/fire-compliance/impairments/<iid>", methods=["GET"])
def fetch_impairment(iid):
    require_roles(ALL_ROLES)
    return success_object(public(get_impairment(iid)))


def _impairment_gates(imp):
    sys = store.systems.get(imp["system_id"])
    prop = property_of_system(sys) if sys else None
    con = contractor_of_system(sys) if sys else None
    require_contractor_active(con)
    require_property_active(prop)
    return sys, con


@bp.route("/fire-compliance/impairments/<iid>/notify-authority", methods=["POST"])
def notify_authority(iid):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    imp = get_impairment(iid)
    if imp["status"] != "OPEN":
        raise invalid_state("Impairment is not OPEN")
    sys, con = _impairment_gates(imp)

    now = store.now()
    imp["authority_notified_at"] = now
    imp["notification_late"] = now > imp["notification_deadline"]
    imp["status"] = "NOTIFIED"
    touch(imp)
    calc.derive_impairment_status(sys)
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(imp))


@bp.route("/fire-compliance/impairments/<iid>/restore", methods=["POST"])
def restore_impairment(iid):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    imp = get_impairment(iid)
    if imp["status"] not in ("OPEN", "NOTIFIED"):
        raise invalid_state("Impairment is not OPEN or NOTIFIED")
    sys, con = _impairment_gates(imp)

    imp["restored_at"] = store.now()
    imp["status"] = "RESTORED"
    touch(imp)
    calc.derive_impairment_status(sys)
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(imp))


@bp.route("/fire-compliance/impairments/<iid>/close", methods=["POST"])
def close_impairment(iid):
    require_roles([ROLE_FIRE_MARSHAL])
    imp = get_impairment(iid)
    if imp["status"] != "RESTORED":
        raise invalid_state("Impairment is not RESTORED")
    imp["status"] = "CLOSED"
    touch(imp)
    sys = store.systems.get(imp["system_id"])
    if sys is not None:
        calc.derive_impairment_status(sys)
    con = contractor_of_system(sys) if sys else None
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(imp))
