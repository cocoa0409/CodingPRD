"""Temporary storage assignment endpoints (PRD 3.5)."""
from flask import Blueprint

import calc
import lookup
import recompute
from db import new_row, store, touch
from errors import ApiError
from middleware import authenticate, body, get_dt, get_int
from response import created, ok

bp = Blueprint("assignments", __name__)


@bp.post("/storage-assignments")
def commit_storage():
    authenticate("Underwriter", "RiskEngineer")
    payload = body()
    policy = lookup.fk_policy(payload)
    facility = lookup.fk_facility(payload)
    stored_value_cents = get_int(payload, "stored_value_cents", minimum=1)
    window_start = get_dt(payload, "window_start")
    window_end = get_dt(payload, "window_end")
    if window_end <= window_start:
        raise ApiError("ERR_DATE_RANGE_INVALID", "window_end must be later than window_start.")
    if policy["status"] not in ("BOUND", "IN_FORCE"):
        raise ApiError(
            "ERR_INVALID_POLICY_STATE",
            "Storage may only be committed under a BOUND or IN_FORCE policy.",
        )
    if facility["status"] != "ACTIVE":
        raise ApiError("ERR_FACILITY_SUSPENDED", "A SUSPENDED facility accepts no new storage.")
    if window_start < policy["term_start_date"] \
            or window_end > policy["adjusted_completion_date"]:
        raise ApiError(
            "ERR_WINDOW_OUTSIDE_POLICY_TERM",
            "The occupancy window must sit inside the policy's covered period.",
        )
    if facility["distance_from_site_miles"] > calc.MAX_STORAGE_DISTANCE_MILES:
        raise ApiError(
            "ERR_FACILITY_TOO_DISTANT", "The facility is beyond 100 road miles of the site."
        )
    peak = calc.facility_peak_exposure(
        facility["id"], stored_value_cents, window_start, window_end
    )
    if peak > facility["aggregate_capacity_cents"]:
        raise ApiError(
            "ERR_FACILITY_CAPACITY_EXCEEDED",
            "Peak overlapping exposure would exceed the facility's aggregate capacity.",
        )
    row = new_row()
    row.update({
        "policy_id": policy["id"],
        "facility_id": facility["id"],
        "stored_value_cents": stored_value_cents,
        "window_start": window_start,
        "window_end": window_end,
        "status": "APPROVED",
        "released_at": None,
        "release_reason": None,
    })
    store.assignments[row["id"]] = row
    recompute.recompute_committed_value(facility)
    return created(row)


@bp.post("/storage-assignments/<assignment_id>/release")
def release_storage(assignment_id):
    authenticate("Underwriter", "RiskEngineer")
    assignment = lookup.assignment(assignment_id)
    if assignment["status"] != "APPROVED":
        raise ApiError(
            "ERR_INVALID_ASSIGNMENT_STATE", "Only an APPROVED assignment may be released."
        )
    assignment["status"] = "RELEASED"
    assignment["released_at"] = store.now()
    assignment["release_reason"] = "MANUAL"
    touch(assignment)
    facility = store.facilities.get(assignment["facility_id"])
    if facility is not None:
        recompute.recompute_committed_value(facility)
    return ok(assignment)


@bp.get("/storage-assignments/<assignment_id>")
def read_assignment(assignment_id):
    authenticate("Underwriter", "UnderwritingManager", "RiskEngineer")
    return ok(lookup.assignment(assignment_id))
