"""DataQsChallenge endpoints (PRD 3.4): file, adjudicate, remand loop."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_VIOLATION_NOT_ACTIVE, ERR_INSPECTION_FINALIZED,
    ERR_CHALLENGE_NOT_SUBMITTED, ERR_CHALLENGE_NOT_UNDER_REVIEW,
    ERR_CHALLENGE_NOT_REMANDED, ERR_REMAND_LIMIT_REACHED,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services.core import (
    stamp_new, touch, recompute_inspection_total, recompute_driver_risk,
)
from validate import get_body, req_str, req_enum, require_path_resource, require_ref
from util import new_id, CLOCK, fmt_datetime

bp = Blueprint("challenges", __name__)

REASON_CODES = ["INCORRECT_DATA", "WRONG_CARRIER", "WRONG_DRIVER", "DUPLICATE_REPORT", "OTHER"]
OUTCOMES = ["UPHELD", "OVERTURNED", "REMANDED"]
REMAND_LIMIT = 2


@bp.post("/safety/dataqs-challenges")
def create_challenge():
    caller = authorized(["ComplianceAnalyst"])
    body = get_body()
    violation_id = req_str(body, "violation_id")
    reason_code = req_enum(body, "reason_code", REASON_CODES)
    evidence_note = req_str(body, "evidence_note")
    violation = require_ref("inspection_violations", violation_id, "violation_id")
    # Stage 5: violation ACTIVE, then parent inspection not FINALIZED
    if violation["status"] != "ACTIVE":
        raise_error(ERR_VIOLATION_NOT_ACTIVE, "challenge requires an ACTIVE violation")
    insp = db["roadside_inspections"].get(violation["inspection_id"])
    if insp is not None and insp["review_status"] == "FINALIZED":
        raise_error(ERR_INSPECTION_FINALIZED, "parent inspection is FINALIZED")
    challenge = stamp_new({
        "id": new_id(),
        "violation_id": violation_id,
        "reason_code": reason_code,
        "evidence_note": evidence_note,
        "filed_by_user_id": caller.user_id,
        "remand_count": 0,
        "decided_at": None,
        "status": "SUBMITTED",
    })
    db["dataqs_challenges"][challenge["id"]] = challenge
    violation["status"] = "CHALLENGED"
    touch(violation)
    return success_object(public(challenge), 201)


@bp.get("/safety/dataqs-challenges")
def list_challenges():
    return list_response("dataqs_challenges", filters={
        "violation_id": request.args.get("violation_id"),
        "status": request.args.get("status"),
    })


@bp.get("/safety/dataqs-challenges/<rid>")
def get_challenge(rid):
    return get_one("dataqs_challenges", rid)


@bp.post("/safety/dataqs-challenges/<rid>/start-review")
def start_review(rid):
    authorized(["SafetyAdmin"])
    challenge = require_path_resource("dataqs_challenges", rid)
    if challenge["status"] != "SUBMITTED":
        raise_error(ERR_CHALLENGE_NOT_SUBMITTED, "start-review requires SUBMITTED")
    challenge["status"] = "UNDER_REVIEW"
    touch(challenge)
    return success_object(public(challenge))


@bp.post("/safety/dataqs-challenges/<rid>/decide")
def decide(rid):
    authorized(["SafetyAdmin"])
    body = get_body()
    outcome = req_enum(body, "outcome", OUTCOMES)
    challenge = require_path_resource("dataqs_challenges", rid)
    if challenge["status"] != "UNDER_REVIEW":
        raise_error(ERR_CHALLENGE_NOT_UNDER_REVIEW, "decide requires UNDER_REVIEW")
    if outcome == "REMANDED":
        if challenge["remand_count"] >= REMAND_LIMIT:
            raise_error(ERR_REMAND_LIMIT_REACHED, "challenge has already been remanded twice")
        challenge["remand_count"] += 1
        challenge["decided_at"] = fmt_datetime(CLOCK.now())
        challenge["status"] = "REMANDED"
        touch(challenge)
        return success_object(public(challenge))
    # UPHELD or OVERTURNED — terminal for the challenge
    violation = db["inspection_violations"].get(challenge["violation_id"])
    if outcome == "UPHELD":
        if violation is not None and violation["status"] == "CHALLENGED":
            violation["status"] = "ACTIVE"
            touch(violation)
    else:  # OVERTURNED
        if violation is not None and violation["status"] == "CHALLENGED":
            violation["status"] = "REMOVED"
            touch(violation)
    if violation is not None:
        insp = db["roadside_inspections"].get(violation["inspection_id"])
        if insp is not None:
            recompute_inspection_total(insp)
        driver = db["drivers"].get(violation["driver_id"])
        if driver is not None:
            recompute_driver_risk(driver)
    challenge["decided_at"] = fmt_datetime(CLOCK.now())
    challenge["status"] = outcome
    touch(challenge)
    return success_object(public(challenge))


@bp.post("/safety/dataqs-challenges/<rid>/resubmit")
def resubmit(rid):
    authorized(["ComplianceAnalyst"])
    body = get_body()
    evidence_note = req_str(body, "evidence_note")
    challenge = require_path_resource("dataqs_challenges", rid)
    if challenge["status"] != "REMANDED":
        raise_error(ERR_CHALLENGE_NOT_REMANDED, "resubmit requires REMANDED")
    challenge["evidence_note"] = evidence_note
    challenge["status"] = "SUBMITTED"
    touch(challenge)
    return success_object(public(challenge))
