"""Placement outcomes and the positive-outcome rate report (PRD 3.10)."""

from flask import Blueprint

import calc
import derive
from db import by_created, days_between, db, new_record, today_str, touch
from auth import require
from errors import fail
from response import created, listing, ok
from validation import f_enum, f_str, get_body, pagination, paginate, q_date

bp = Blueprint("outcomes", __name__)

OUTCOME_TYPES = ("EMPLOYED_FULL_TIME", "EMPLOYED_PART_TIME", "POSTSECONDARY_ENROLLED",
                 "APPRENTICESHIP", "MILITARY", "NOT_ENGAGED", "UNKNOWN")
VERIFICATION_SOURCES = ("EMPLOYER_LETTER", "ENROLLMENT_RECORD", "STUDENT_ATTESTATION")
DOCUMENTARY_SOURCES = ("EMPLOYER_LETTER", "ENROLLMENT_RECORD")
EMPLOYER_NAME_REQUIRED = ("EMPLOYED_FULL_TIME", "EMPLOYED_PART_TIME", "APPRENTICESHIP")
OUTCOME_WINDOW_DAYS = 180


@bp.post("/placement-outcomes")
def record_outcome():
    require("WblCoordinator")
    body = get_body()
    placement = derive.get_placement(f_str(body, "placement_id"))
    outcome_type = f_enum(body, "outcome_type", OUTCOME_TYPES)
    employer_name = f_str(body, "employer_name", required=False)
    institution_name = f_str(body, "institution_name", required=False)
    verification_source = f_enum(body, "verification_source", VERIFICATION_SOURCES)

    if outcome_type in EMPLOYER_NAME_REQUIRED and employer_name is None:
        fail("ERR_INVALID_REQUEST",
             "Field 'employer_name' is required for this outcome type.")
    if outcome_type == "POSTSECONDARY_ENROLLED" and institution_name is None:
        fail("ERR_INVALID_REQUEST",
             "Field 'institution_name' is required for this outcome type.")

    if placement["lifecycle_status"] != "COMPLETED":
        fail("ERR_PLACEMENT_NOT_COMPLETED", "The placement is not completed.")

    recorded_on = today_str()
    days_since = days_between(placement["completed_on"], recorded_on)
    if days_since > OUTCOME_WINDOW_DAYS:
        fail("ERR_OUTCOME_WINDOW_CLOSED",
             "The 180-day outcome reporting window has closed.")

    outcome = new_record()
    outcome.update({
        "placement_id": placement["id"],
        "outcome_type": outcome_type,
        "employer_name": employer_name,
        "institution_name": institution_name,
        "recorded_on": recorded_on,
        "verification_source": verification_source,
        "status": "RECORDED",
        "verified_on": None,
        "days_since_completion": days_since,
        "counts_positive": False,
    })
    db.placement_outcomes[outcome["id"]] = outcome
    return created(outcome)


@bp.post("/placement-outcomes/<outcomeId>/verify")
def verify_outcome(outcomeId):
    require("WblCoordinator")
    outcome = derive.get_outcome(outcomeId)

    if outcome["status"] != "RECORDED":
        fail("ERR_OUTCOME_INVALID_STATE", "Only a recorded outcome may be verified.")
    if outcome["verification_source"] not in DOCUMENTARY_SOURCES:
        fail("ERR_OUTCOME_INVALID_STATE",
             "A student attestation is not documentary evidence for verification.")

    outcome["status"] = "VERIFIED"
    outcome["verified_on"] = today_str()
    outcome["counts_positive"] = outcome["outcome_type"] in calc.POSITIVE_OUTCOME_TYPES
    touch(outcome)
    return ok(outcome)


@bp.get("/placements/<id>/outcomes")
def list_placement_outcomes(id):
    require("WblCoordinator", "ComplianceOfficer")
    placement = derive.get_placement(id)
    limit, offset = pagination()
    rows = by_created([o for o in db.placement_outcomes.values()
                       if o["placement_id"] == placement["id"]])
    page, total = paginate(rows, limit, offset)
    return listing(page, total, limit, offset)


@bp.get("/reports/outcome-rate")
def outcome_rate_report():
    require("WblCoordinator", "ComplianceOfficer")
    from_date = q_date("from_date", required=True)
    to_date = q_date("to_date", required=True)
    if to_date < from_date:
        fail("ERR_INVALID_REQUEST", "Query parameter 'to_date' must not precede 'from_date'.")
    return ok(calc.outcome_rate(from_date, to_date))
