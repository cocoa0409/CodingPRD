"""Minor-servicing exceptions: request, segregated determination, revoke (PRD 3.9)."""

from flask import Blueprint, request

import db
from clock import parse_iso, fmt
from errors import ApiError
from middleware import auth, paginate, ALL_ROLES
from response import ok, ok_list
from services import core

bp = Blueprint("minor_servicing_exceptions", __name__)


@bp.route("/minor-servicing-exceptions", methods=["POST"])
def create_exception():
    user_id, _ = auth(["AuthorizedEmployee"])
    body = core.body_json()
    machine_id = core.req_str(body, "machine_id")
    task_description = core.req_str(body, "task_description")
    routine_repetitive = core.req_bool(body, "routine_repetitive")
    integral_to_production = core.req_bool(body, "integral_to_production")
    alternative_measures_effective = core.req_bool(body, "alternative_measures_effective")
    estimated_duration_min = core.req_int(body, "estimated_duration_min", min_v=1)
    valid_from = core.req_dt(body, "valid_from")
    valid_until = core.req_dt(body, "valid_until")
    if not valid_from < valid_until:
        raise ApiError("ERR_VALIDATION", 400,
                       "valid_from must be strictly before valid_until")
    m = core.get_or_404("machines", machine_id, "Machine")
    e = core.stamp_new({
        "id": core.new_id(),
        "machine_id": m["id"],
        "requested_by_employee_id": user_id,
        "task_description": task_description,
        "routine_repetitive": routine_repetitive,
        "integral_to_production": integral_to_production,
        "alternative_measures_effective": alternative_measures_effective,
        "estimated_duration_min": estimated_duration_min,
        "valid_from": fmt(valid_from),
        "valid_until": fmt(valid_until),
        "determination": None,
        "determined_by_employee_id": None,
        "status": "PENDING",
    })
    db.DB["minor_servicing_exceptions"][e["id"]] = e
    return ok(core.exception_view(e), 201)


@bp.route("/minor-servicing-exceptions", methods=["GET"])
def list_exceptions():
    auth(ALL_ROLES)
    machine_id = request.args.get("machine_id")
    requested_by = request.args.get("requested_by_employee_id")
    determined_by = request.args.get("determined_by_employee_id")
    status = request.args.get("status")
    items = list(db.DB["minor_servicing_exceptions"].values())
    if machine_id is not None:
        items = [e for e in items if e["machine_id"] == machine_id]
    if requested_by is not None:
        items = [e for e in items if e["requested_by_employee_id"] == requested_by]
    if determined_by is not None:
        items = [e for e in items if e["determined_by_employee_id"] == determined_by]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.exception_view(e) for e in page], total, limit, offset)


@bp.route("/minor-servicing-exceptions/<eid>", methods=["GET"])
def get_exception(eid):
    auth(ALL_ROLES)
    e = core.get_or_404("minor_servicing_exceptions", eid, "MinorServicingException")
    return ok(core.exception_view(e))


@bp.route("/minor-servicing-exceptions/<eid>/determine", methods=["POST"])
def determine_exception(eid):
    user_id, _ = auth(["EHSManager"])
    e = core.get_or_404("minor_servicing_exceptions", eid, "MinorServicingException")
    if e["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a PENDING exception can be determined")
    # Segregation of duties (stage 8): the determiner must not be the requester.
    if e["requested_by_employee_id"] == user_id:
        raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN", 409,
                       "The requester may not determine their own exception")
    # calculations.minor_servicing_eligibility: the machine's risk tier is read
    # once, at determination time; the duration boundary is inclusive.
    m = db.DB["machines"][e["machine_id"]]
    cap = core.DURATION_CAP[core.risk_tier(m)]
    if not (e["routine_repetitive"] and e["integral_to_production"]
            and e["alternative_measures_effective"]):
        determination = "NOT_ELIGIBLE"
    elif e["estimated_duration_min"] > cap:
        determination = "NOT_ELIGIBLE"
    else:
        determination = "ELIGIBLE"
    if determination == "ELIGIBLE":
        # Window exclusivity: no other DETERMINED + ELIGIBLE exception on the
        # machine with a closed-interval-overlapping window (touching conflicts).
        new_from = parse_iso(e["valid_from"])
        new_until = parse_iso(e["valid_until"])
        for other in db.DB["minor_servicing_exceptions"].values():
            if (other["id"] == e["id"] or other["machine_id"] != e["machine_id"]
                    or other["status"] != "DETERMINED"
                    or other["determination"] != "ELIGIBLE"):
                continue
            if (new_from <= parse_iso(other["valid_until"])
                    and parse_iso(other["valid_from"]) <= new_until):
                raise ApiError("ERR_EXCEPTION_WINDOW_CONFLICT", 409,
                               "Another ELIGIBLE exception overlaps this validity window")
    e["determination"] = determination
    e["determined_by_employee_id"] = user_id
    e["status"] = "DETERMINED"
    core.touch(e)
    return ok(core.exception_view(e))


@bp.route("/minor-servicing-exceptions/<eid>/revoke", methods=["POST"])
def revoke_exception(eid):
    auth(["EHSManager"])
    e = core.get_or_404("minor_servicing_exceptions", eid, "MinorServicingException")
    if e["status"] != "DETERMINED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a DETERMINED exception can be revoked")
    e["status"] = "REVOKED"
    core.touch(e)
    return ok(core.exception_view(e))
