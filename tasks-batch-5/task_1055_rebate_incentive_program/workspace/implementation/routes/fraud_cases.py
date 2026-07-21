"""Fraud case endpoints (4) - PRD §3.7."""
from flask import Blueprint, request

import db
import middleware as mw
import response as resp
import serializers as ser
from errors import err
from services import fraud

bp = Blueprint("fraud_cases", __name__)

CASE_STATUSES = {"UNDER_INVESTIGATION", "PENDING_INFO", "SUBSTANTIATED", "CLEARED"}

ALLOWED_TRANSITIONS = {
    ("OPEN", "UNDER_INVESTIGATION"),
    ("PENDING_INFO", "UNDER_INVESTIGATION"),
    ("UNDER_INVESTIGATION", "PENDING_INFO"),
    ("UNDER_INVESTIGATION", "SUBSTANTIATED"),
    ("UNDER_INVESTIGATION", "CLEARED"),
}


@bp.post("/api/fraud-cases")
@mw.require("FraudAnalyst")
def create_case():
    data = mw.body()
    claimant_id = data.get("claimant_id")
    if not isinstance(claimant_id, str) or not claimant_id:
        raise err("ERR_VALIDATION", "Field 'claimant_id' is required.")
    claimant = db.get_claimant(claimant_id)

    claim = None
    claim_id = data.get("claim_id")
    if claim_id is not None:
        if not isinstance(claim_id, str) or not claim_id:
            raise err("ERR_VALIDATION", "Field 'claim_id' must be a string.")
        claim = db.get_claim(claim_id)

    opened_reason = mw.as_string(data, "opened_reason")

    score = fraud.heuristic_score(claimant, subject_claim=claim)
    case = fraud.open_case(claimant, claim["id"] if claim else None, "ANALYST", opened_reason, score)
    return resp.created(ser.fraud_case(case))


@bp.get("/api/fraud-cases/<fid>")
@mw.require("ProgramAdmin", "FraudAnalyst")
def read_case(fid):
    return resp.ok(ser.fraud_case(db.get_fraud_case(fid)))


@bp.get("/api/fraud-cases")
@mw.require("ProgramAdmin", "FraudAnalyst", "ClaimsProcessor")
def list_cases():
    items = db.by_created(list(db.fraud_cases.values()))
    for field in ("claimant_id", "claim_id", "status"):
        value = request.args.get(field)
        if value:
            items = [f for f in items if f[field] == value]
    return resp.paginated(items, ser.fraud_case)


@bp.post("/api/fraud-cases/<fid>/transition")
@mw.require("FraudAnalyst")
def transition_case(fid):
    case = db.get_fraud_case(fid)
    data = mw.body()
    to_status = mw.as_enum(data, "to_status", CASE_STATUSES)
    mw.as_string(data, "note", required=False, allow_empty=True)

    if (case["status"], to_status) not in ALLOWED_TRANSITIONS:
        raise err("ERR_INVALID_TRANSITION")

    claimant = db.get_claimant(case["claimant_id"])
    case["status"] = to_status

    if to_status == "PENDING_INFO":
        case["info_request_count"] += 1
        db.touch(case)
    elif to_status == "SUBSTANTIATED":
        case["final_score"] = fraud.substantiated_score(case)
        db.touch(case)
        claimant["fraud_score"] = case["final_score"]
        db.touch(claimant)
        fraud.block_claimant_cascade(claimant)
        claimant["fraud_score"] = case["final_score"]
    elif to_status == "CLEARED":
        case["final_score"] = fraud.cleared_score(case)
        db.touch(case)
        claimant["fraud_score"] = case["final_score"]
        db.touch(claimant)
        if case["claim_id"]:
            claim = db.claims.get(case["claim_id"])
            if claim is not None and claim["adjudication_status"] == "HELD":
                claim["adjudication_status"] = "UNDER_REVIEW"
                db.touch(claim)
    else:
        db.touch(case)

    return resp.ok(ser.fraud_case(case))
