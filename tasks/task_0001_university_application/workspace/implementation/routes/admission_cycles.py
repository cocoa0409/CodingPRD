"""Admission cycle and yield-management routes."""

from flask import Blueprint

import db
import errors
import response as resp
import util
from middleware import require_auth
from services import waitlist as waitlist_service
from services.serializers import serialize_admission_cycle


bp = Blueprint("admission_cycles", __name__)


# --------------------------------------------------------------------------- #
# GET /admission-cycles/{id}
# --------------------------------------------------------------------------- #

@bp.route("/admission-cycles/<cycle_id>", methods=["GET"])
@require_auth(["AdmissionsOfficer", "PlatformAdmin"])
def get_admission_cycle(cycle_id):
    row = db.admission_cycles.get(cycle_id)
    if row is None:
        errors.raise_error(errors.ERR_RESOURCE_NOT_FOUND,
                           "Admission cycle not found.")
    # Refresh the cycle's clock_iso view to match the current global clock
    row["clock_iso"] = util.server_clock_dt()
    return resp.success_object(serialize_admission_cycle(row))


# --------------------------------------------------------------------------- #
# POST /admission-cycles/{id}/run-yield  (AdmissionsOfficer, PlatformAdmin)
# --------------------------------------------------------------------------- #

@bp.route("/admission-cycles/<cycle_id>/run-yield", methods=["POST"])
@require_auth(["AdmissionsOfficer", "PlatformAdmin"])
def run_yield(cycle_id):
    cycle = db.admission_cycles.get(cycle_id)
    if cycle is None:
        errors.raise_error(errors.ERR_RESOURCE_NOT_FOUND,
                           "Admission cycle not found.")

    school = db.schools.get(cycle["school_id"])
    if school is None:
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Cycle's owning school not found.")

    # Priority 18: open seats and waitlist non-empty
    open_seats = max(
        0,
        school["target_class_size"] - school["confirmed_enrollment_count"],
    )
    if school["posture"] != "OPEN" or open_seats <= 0:
        errors.raise_error(errors.ERR_NO_OPEN_SEATS,
                           "School has no open seats for a yield run.")

    waitlisted = [
        a for a in db.applications.values()
        if a["school_id"] == school["id"] and a["status"] == "WAITLISTED"
    ]
    if len(waitlisted) == 0:
        errors.raise_error(errors.ERR_NO_OPEN_SEATS,
                           "School has no waitlisted applications.")

    # Priority 19: cooldown (inclusive lower bound at +cooldown_ms from last_yield_run_at)
    now = util.server_clock_dt()
    cooldown_ms = cycle.get("cooldown_ms", 86_400_000)
    last_run = cycle.get("last_yield_run_at")
    if last_run is not None:
        delta_ms = (now - last_run).total_seconds() * 1000
        if delta_ms < cooldown_ms:
            errors.raise_error(errors.ERR_YIELD_COOLDOWN_ACTIVE,
                               "Yield run cooldown is still active.")

    # Sort eligible by waitlist_rank ASC
    waitlisted.sort(key=lambda a: (a["waitlist_rank"]
                                   if a["waitlist_rank"] is not None
                                   else float("inf"),
                                   a["waitlist_added_at"], a["created_at"]))
    promote_count = min(open_seats, len(waitlisted))
    promoted_ids = []
    for app in waitlisted[:promote_count]:
        app["status"] = "ADMITTED"
        app["decision_at"] = now
        app["waitlist_rank"] = None
        util.stamp_update(app)
        promoted_ids.append(app["id"])

    # Recompute waitlist ranks for remaining waitlisted
    waitlist_service.recompute_waitlist_ranks(school["id"])

    cycle["yield_run_count"] += 1
    cycle["last_yield_run_at"] = now
    util.stamp_update(cycle)

    payload = {
        "admission_cycle_id": cycle["id"],
        "school_id": school["id"],
        "promoted_count": promote_count,
        "promoted_application_ids": promoted_ids,
        "open_seats_before": open_seats,
        "yield_run_count": cycle["yield_run_count"],
        "last_yield_run_at": util.format_iso(cycle["last_yield_run_at"]),
    }
    return resp.success_object(payload)
