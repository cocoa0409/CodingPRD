"""Appeal endpoints: file, get, list, assign, dismiss, remand, withdraw, decide.

Includes the reversal cascade onto a DENIED MONETARY determination's claim.
"""
from datetime import date

from flask import Blueprint

import db
from errors import err
from middleware import authenticate, require_role
from response import object_response, array_response
from validate import (
    as_enum, as_string, check_occ, get_json_body, paginate, serialize,
    validate_iso_date,
)
from services import claim_logic

bp = Blueprint("appeals", __name__)

MAX_REMANDS = 2

SUBMITTED = "SUBMITTED"
UNDER_REVIEW = "UNDER_REVIEW"
REMANDED = "REMANDED"
DECIDED_AFFIRMED = "DECIDED_AFFIRMED"
DECIDED_REVERSED = "DECIDED_REVERSED"
WITHDRAWN = "WITHDRAWN"
DISMISSED = "DISMISSED"

MONETARILY_ELIGIBLE = "MONETARILY_ELIGIBLE"
MONETARILY_INELIGIBLE = "MONETARILY_INELIGIBLE"


@bp.route("/ui/appeals", methods=["POST"])
def file_appeal():
    p = authenticate()
    require_role(p, {"Claimant", "Employer", "ProgramAdmin"})
    body = get_json_body()
    determination_id = as_string(body, "determination_id")
    det = db.determinations.get(determination_id)
    if det is None:
        raise err("ERR_NOT_FOUND", "determination_id not found.")
    filed_by = as_enum(body, "filed_by", {"CLAIMANT", "EMPLOYER"})
    filed_date_str = as_string(body, "filed_date")
    filed_date = validate_iso_date(filed_date_str, "filed_date")

    # Temporal (priority 8): timely only when filed_date <= appeal_deadline_date
    deadline = date.fromisoformat(det["appeal_deadline_date"])
    if filed_date > deadline:
        raise err("ERR_UNTIMELY", "Appeal filed after the appeal deadline.")

    rec = {
        "determination_id": determination_id,
        "filed_by": filed_by,
        "filed_date": filed_date_str,
        "status": SUBMITTED,
        "assigned_referee_id": None,
        "remand_count": 0,
    }
    db.stamp_create(rec)
    db.appeals[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/ui/appeals/<aid>", methods=["GET"])
def get_appeal(aid):
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Adjudicator", "Referee", "AppealsClerk",
                     "Claimant", "Employer"})
    rec = db.appeals.get(aid)
    if not rec:
        raise err("ERR_NOT_FOUND", "Appeal not found.")
    return object_response(serialize(rec))


@bp.route("/ui/determinations/<did>/appeals", methods=["GET"])
def list_determination_appeals(did):
    p = authenticate()
    require_role(p, {"ProgramAdmin", "Adjudicator", "Referee", "AppealsClerk"})
    if did not in db.determinations:
        raise err("ERR_NOT_FOUND", "Determination not found.")
    items = [a for a in db.appeals.values() if a["determination_id"] == did]
    page, limit, offset, total = paginate(items)
    return array_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/ui/appeals/<aid>/assign", methods=["POST"])
def assign_appeal(aid):
    p = authenticate()
    require_role(p, {"AppealsClerk"})
    appeal = db.appeals.get(aid)
    if not appeal:
        raise err("ERR_NOT_FOUND", "Appeal not found.")
    body = get_json_body()
    referee_id = as_string(body, "assigned_referee_id")
    # state check (priority 7): assign defined from SUBMITTED or REMANDED
    if appeal["status"] not in (SUBMITTED, REMANDED):
        raise err("ERR_INVALID_STATE", "Appeal is not SUBMITTED or REMANDED.")
    # segregation of duties (priority 9)
    det = db.determinations[appeal["determination_id"]]
    if referee_id == det["issuing_adjudicator_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "Referee must differ from the issuing adjudicator.")
    check_occ(body, "expected_appeal_version", appeal, "ERR_STALE_VERSION")
    appeal["assigned_referee_id"] = referee_id
    appeal["status"] = UNDER_REVIEW
    db.touch(appeal)
    return object_response(serialize(appeal))


@bp.route("/ui/appeals/<aid>/dismiss", methods=["POST"])
def dismiss_appeal(aid):
    p = authenticate()
    require_role(p, {"AppealsClerk"})
    appeal = db.appeals.get(aid)
    if not appeal:
        raise err("ERR_NOT_FOUND", "Appeal not found.")
    body = get_json_body()
    # state check: dismiss defined from SUBMITTED
    if appeal["status"] != SUBMITTED:
        raise err("ERR_INVALID_STATE", "Appeal is not SUBMITTED.")
    check_occ(body, "expected_appeal_version", appeal, "ERR_STALE_VERSION")
    appeal["status"] = DISMISSED
    db.touch(appeal)
    return object_response(serialize(appeal))


@bp.route("/ui/appeals/<aid>/remand", methods=["POST"])
def remand_appeal(aid):
    p = authenticate()
    require_role(p, {"Referee"})
    appeal = db.appeals.get(aid)
    if not appeal:
        raise err("ERR_NOT_FOUND", "Appeal not found.")
    body = get_json_body()
    # state check: remand defined from UNDER_REVIEW
    if appeal["status"] != UNDER_REVIEW:
        raise err("ERR_INVALID_STATE", "Appeal is not UNDER_REVIEW.")
    # remand cap (priority 15)
    if appeal["remand_count"] >= MAX_REMANDS:
        raise err("ERR_REMAND_LIMIT", "Appeal has reached the remand limit.")
    check_occ(body, "expected_appeal_version", appeal, "ERR_STALE_VERSION")
    appeal["remand_count"] += 1
    appeal["status"] = REMANDED
    db.touch(appeal)
    return object_response(serialize(appeal))


@bp.route("/ui/appeals/<aid>/withdraw", methods=["POST"])
def withdraw_appeal(aid):
    p = authenticate()
    require_role(p, {"Referee", "Claimant", "Employer"})
    appeal = db.appeals.get(aid)
    if not appeal:
        raise err("ERR_NOT_FOUND", "Appeal not found.")
    body = get_json_body()
    if appeal["status"] not in (SUBMITTED, UNDER_REVIEW):
        raise err("ERR_INVALID_STATE", "Appeal is not SUBMITTED or UNDER_REVIEW.")
    check_occ(body, "expected_appeal_version", appeal, "ERR_STALE_VERSION")
    appeal["status"] = WITHDRAWN
    db.touch(appeal)
    return object_response(serialize(appeal))


@bp.route("/ui/appeals/<aid>/decide", methods=["POST"])
def decide_appeal(aid):
    p = authenticate()
    require_role(p, {"Referee"})
    appeal = db.appeals.get(aid)
    if not appeal:
        raise err("ERR_NOT_FOUND", "Appeal not found.")
    body = get_json_body()
    ruling = as_enum(body, "ruling", {"AFFIRM", "REVERSE"})
    if appeal["status"] != UNDER_REVIEW:
        raise err("ERR_INVALID_STATE", "Appeal is not UNDER_REVIEW.")
    check_occ(body, "expected_appeal_version", appeal, "ERR_STALE_VERSION")

    det = db.determinations[appeal["determination_id"]]
    if ruling == "AFFIRM":
        appeal["status"] = DECIDED_AFFIRMED
        db.touch(appeal)
        return object_response(serialize(appeal))

    # REVERSE
    appeal["status"] = DECIDED_REVERSED
    # Reversal cascade
    if det["determination_type"] == "MONETARY" and det["outcome"] == "DENIED":
        claim = db.claims[det["claim_id"]]
        if claim["status"] == MONETARILY_INELIGIBLE:
            results = claim_logic.run_monetary(claim)
            if results["method"] != "NONE":
                claim["base_period_method"] = results["method"]
                claim["weekly_benefit_amount_cents"] = results["wba"]
                claim["maximum_benefit_amount_cents"] = results["base_mba"]
                claim["remaining_balance_cents"] = results["base_mba"]
            claim["status"] = MONETARILY_ELIGIBLE
            db.touch(claim)
    # Mark determination reversed and no longer appealable (both MONETARY and
    # NONMONETARY).
    det["outcome"] = "REVERSED"
    det["is_appealable"] = False
    db.touch(det)
    db.touch(appeal)
    return object_response(serialize(appeal))
