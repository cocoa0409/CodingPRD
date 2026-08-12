"""RidershipReport endpoints (append-only)."""
from flask import Blueprint, request

import db
from envelope import success_list, success_object
from errors import (
    ERR_DUPLICATE_RIDERSHIP_REPORT,
    ERR_INVALID_STATE,
    raise_err,
)
from middleware import authenticate, driver_ownership, get_or_404, require_roles
from services.pricing import ON_TIME_GRACE_MINUTES
from validation import (
    get_body,
    paginate,
    pagination_params,
    req_int,
    req_minute,
    req_str,
)

bp = Blueprint("ridership_reports", __name__)

ROLES = {"SystemAdmin", "DistrictAdmin", "ContractorOps", "Driver"}


@bp.route("/busops/ridership-reports", methods=["POST"])
def create_ridership_report():
    body = get_body()
    assignment_id = req_str(body, "assignment_id")
    service_day_id = req_str(body, "service_day_id")
    boardings = req_int(body, "boardings", minimum=0)
    alightings = req_int(body, "alightings", minimum=0)
    first_pickup = req_minute(body, "first_pickup_actual_minute")
    last_dropoff = req_minute(body, "last_dropoff_actual_minute")
    actor = authenticate()
    require_roles(actor, {"Driver", "ContractorOps"})
    assignment = get_or_404("assignments", assignment_id, "Assignment")
    get_or_404("service_days", service_day_id, "ServiceDay")
    if actor["role"] == "Driver":
        driver_ownership(actor, assignment.get("driver_id"))
    if assignment["status"] != "COMPLETED":
        raise_err(
            ERR_INVALID_STATE,
            "Ridership reports are accepted only for COMPLETED assignments",
        )
    for r in db.all_of("ridership_reports"):
        if r["assignment_id"] == assignment_id:
            raise_err(
                ERR_DUPLICATE_RIDERSHIP_REPORT,
                "A ridership report already exists for this assignment",
            )

    minutes_late = max(
        0, first_pickup - assignment["planned_start_minute"] - ON_TIME_GRACE_MINUTES
    )
    rec = {
        "id": db.new_id(),
        "assignment_id": assignment_id,
        "service_day_id": service_day_id,
        "boardings": boardings,
        "alightings": alightings,
        "first_pickup_actual_minute": first_pickup,
        "last_dropoff_actual_minute": last_dropoff,
        "minutes_late": minutes_late,
        "on_time": minutes_late == 0,
        "student_minutes_late": minutes_late * boardings,
    }
    db.stamp_append_only(rec)
    db.STORES["ridership_reports"][rec["id"]] = rec
    return success_object(db.public(rec), status=201)


@bp.route("/busops/ridership-reports", methods=["GET"])
def list_ridership_reports():
    limit, offset = pagination_params()
    actor = authenticate()
    require_roles(actor, ROLES)
    items = list(db.all_of("ridership_reports"))
    assignment_id = request.args.get("assignment_id")
    service_day_id = request.args.get("service_day_id")
    if assignment_id is not None:
        items = [r for r in items if r["assignment_id"] == assignment_id]
    if service_day_id is not None:
        items = [r for r in items if r["service_day_id"] == service_day_id]
    page, info = paginate(items, limit, offset)
    return success_list(page, info)


@bp.route("/busops/ridership-reports/<rid>", methods=["GET"])
def get_ridership_report(rid):
    actor = authenticate()
    require_roles(actor, ROLES)
    rec = get_or_404("ridership_reports", rid, "RidershipReport")
    return success_object(db.public(rec))
