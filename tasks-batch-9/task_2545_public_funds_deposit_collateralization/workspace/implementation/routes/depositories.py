"""Depository registration and the qualification review conversation (PRD 3.1)."""

from flask import Blueprint

import db
import middleware as mw
from constants import (
    CHARTER_TYPES,
    COLLATERAL_POSTURES,
    DECISIONS,
    DEFAULT_CAPITAL_RATIO_BPS,
    DEFAULT_INSURANCE_DETERMINATION_BASIS,
    DEPOSITORY_APPROVAL_STATUSES,
    INSURANCE_ELECTIONS,
    MAX_CAPITAL_RATIO_BPS,
    MIN_CAPITAL_RATIO_BPS,
    PLEDGE_CAPACITY_STATUTORY_CEILING_CENTS,
    REVIEW_ROUND_LIMIT,
    REVIEW_STATUSES,
    RISK_GRADES,
    ROLE_BANK_COLLATERAL_OFFICER,
    ROLE_BANK_COMPLIANCE_OFFICER,
    ROLE_CUSTODIAN,
    ROLE_PUBLIC_UNIT_TREASURER,
    ROLE_STATE_REGULATOR,
    ROLE_SYSTEM_OPERATOR,
)
from errors import fail
from response import list_response, record_response
from services import calc, state

bp = Blueprint("depositories", __name__)

READ_ROLES = (
    ROLE_STATE_REGULATOR,
    ROLE_BANK_COLLATERAL_OFFICER,
    ROLE_BANK_COMPLIANCE_OFFICER,
    ROLE_PUBLIC_UNIT_TREASURER,
    ROLE_CUSTODIAN,
    ROLE_SYSTEM_OPERATOR,
)


@bp.post("/depositories")
def create_depository():
    mw.authorize(ROLE_BANK_COLLATERAL_OFFICER)
    body = mw.body_json()
    program = mw.resolve_fk("pooled_programs", body.get("pooled_program_id"))
    name = mw.req_text(body, "name")
    charter_type = mw.req_enum(body, "charter_type", CHARTER_TYPES)
    home_state = mw.req_text(body, "home_state")
    capital_ratio_bps = mw.opt_int(
        body,
        "capital_ratio_bps",
        default=DEFAULT_CAPITAL_RATIO_BPS,
        allow_zero=True,
        minimum=MIN_CAPITAL_RATIO_BPS,
        maximum=MAX_CAPITAL_RATIO_BPS,
    )
    basis = mw.opt_enum(
        body,
        "insurance_determination_basis",
        INSURANCE_ELECTIONS,
        DEFAULT_INSURANCE_DETERMINATION_BASIS,
    )
    if mw.present(body, "pooled_program_id"):
        mw.req_id(body, "pooled_program_id")
    record = db.new_record(
        {
            "name": name,
            "charter_type": charter_type,
            "home_state": home_state,
            "capital_ratio_bps": capital_ratio_bps,
            "capital_tier": calc.capital_tier(capital_ratio_bps),
            "insurance_determination_basis": basis,
            "pooled_program_id": program["id"] if program else None,
            "approval_status": "DRAFT",
            "approved_at": None,
            "approved_pledge_capacity_cents": 0,
            "consecutive_deficiency_runs": 0,
            "open_margin_call_count": 0,
            "collateral_posture": "COMPLIANT",
            "total_required_collateral_cents": 0,
            "total_pledged_collateral_value_cents": 0,
            "total_pledged_par_cents": 0,
            "risk_score_bps": 0,
            "risk_grade": "A",
            "mtm_run_index": 0,
            "last_mtm_window_end": None,
        }
    )
    db.insert("depositories", record)
    state.recompute_all()
    return record_response(record, 201)


@bp.get("/depositories/<depository_id>")
def read_depository(depository_id):
    mw.authorize(*READ_ROLES)
    return record_response(mw.resolve("depositories", depository_id))


@bp.get("/depositories")
def list_depositories():
    mw.authorize(
        ROLE_STATE_REGULATOR,
        ROLE_BANK_COLLATERAL_OFFICER,
        ROLE_BANK_COMPLIANCE_OFFICER,
        ROLE_PUBLIC_UNIT_TREASURER,
        ROLE_SYSTEM_OPERATOR,
    )
    limit, offset = mw.page_params()
    approval_status = mw.query_filter("approval_status", DEPOSITORY_APPROVAL_STATUSES)
    pooled_program_id = mw.query_filter("pooled_program_id")
    posture = mw.query_filter("collateral_posture", COLLATERAL_POSTURES)
    risk_grade = mw.query_filter("risk_grade", RISK_GRADES)
    records = db.rows("depositories")
    if approval_status is not None:
        records = [r for r in records if r["approval_status"] == approval_status]
    if pooled_program_id is not None:
        records = [r for r in records if r["pooled_program_id"] == pooled_program_id]
    if posture is not None:
        records = [r for r in records if r["collateral_posture"] == posture]
    if risk_grade is not None:
        records = [r for r in records if r["risk_grade"] == risk_grade]
    return list_response(mw.paginate(records, limit, offset), limit, offset, len(records))


@bp.post("/depositories/<depository_id>/suspend")
def suspend_depository(depository_id):
    mw.authorize(ROLE_STATE_REGULATOR)
    depository = mw.resolve("depositories", depository_id)
    if depository["approval_status"] != "APPROVED":
        fail("ERR_INVALID_STATE")
    state.suspend_depository_cascade(depository)
    state.recompute_all()
    return record_response(depository)


# ------------------------------------------------------- qualification reviews
@bp.post("/depositories/<depository_id>/qualification-reviews")
def file_qualification_review(depository_id):
    user_id, _ = mw.authorize(ROLE_BANK_COLLATERAL_OFFICER)
    depository = mw.resolve("depositories", depository_id)
    body = mw.body_json()
    requested = mw.req_int(body, "requested_pledge_capacity_cents")
    if depository["approval_status"] in ("DENIED", "SUSPENDED"):
        fail("ERR_INVALID_STATE")
    if requested > PLEDGE_CAPACITY_STATUTORY_CEILING_CENTS:
        fail("ERR_CAPACITY_ABOVE_STATUTORY_CEILING")
    record = db.new_record(
        {
            "depository_id": depository["id"],
            "submitted_by_user_id": user_id,
            "attested_by_user_id": None,
            "requested_pledge_capacity_cents": requested,
            "attestation_note": None,
            "status": "SUBMITTED",
            "round_count": 1,
            "info_request_note": None,
            "decision_note": None,
            "decided_at": None,
        }
    )
    db.insert("qualification_reviews", record)
    state.recompute_all()
    return record_response(record, 201)


@bp.get("/depositories/<depository_id>/qualification-reviews")
def list_qualification_reviews(depository_id):
    mw.authorize(
        ROLE_STATE_REGULATOR, ROLE_BANK_COLLATERAL_OFFICER, ROLE_BANK_COMPLIANCE_OFFICER
    )
    depository = mw.resolve("depositories", depository_id)
    limit, offset = mw.page_params()
    status_filter = mw.query_filter("status", REVIEW_STATUSES)
    records = [
        r
        for r in db.rows("qualification_reviews")
        if r["depository_id"] == depository["id"]
    ]
    if status_filter is not None:
        records = [r for r in records if r["status"] == status_filter]
    return list_response(mw.paginate(records, limit, offset), limit, offset, len(records))


@bp.post("/qualification-reviews/<review_id>/attest")
def attest_review(review_id):
    user_id, _ = mw.authorize(ROLE_BANK_COMPLIANCE_OFFICER)
    review = mw.resolve("qualification_reviews", review_id)
    body = mw.body_json()
    note = mw.req_text(body, "attestation_note")
    depository = db.get("depositories", review["depository_id"])
    if review["status"] not in ("SUBMITTED", "RETURNED_FOR_INFO"):
        fail("ERR_INVALID_STATE")
    if depository is not None and depository["approval_status"] == "DENIED":
        fail("ERR_INVALID_STATE")
    if user_id == review["submitted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    reattest = review["status"] == "RETURNED_FOR_INFO"
    if reattest and review["round_count"] + 1 > REVIEW_ROUND_LIMIT:
        fail("ERR_ROUND_LIMIT_REACHED")
    review["attestation_note"] = note
    review["attested_by_user_id"] = user_id
    review["status"] = "ATTESTED"
    if reattest:
        review["round_count"] = review["round_count"] + 1
    db.touch(review)
    state.recompute_all()
    return record_response(review)


@bp.post("/qualification-reviews/<review_id>/begin-review")
def begin_review(review_id):
    mw.authorize(ROLE_STATE_REGULATOR)
    review = mw.resolve("qualification_reviews", review_id)
    depository = db.get("depositories", review["depository_id"])
    if review["status"] != "ATTESTED":
        fail("ERR_INVALID_STATE")
    if depository is None or depository["approval_status"] not in ("DRAFT", "UNDER_REVIEW"):
        fail("ERR_INVALID_STATE")
    review["status"] = "UNDER_REVIEW"
    db.touch(review)
    depository["approval_status"] = "UNDER_REVIEW"
    db.touch(depository)
    state.recompute_all()
    return record_response(review)


@bp.post("/qualification-reviews/<review_id>/return-for-info")
def return_for_info(review_id):
    mw.authorize(ROLE_STATE_REGULATOR)
    review = mw.resolve("qualification_reviews", review_id)
    body = mw.body_json()
    note = mw.req_text(body, "info_request_note")
    if review["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE")
    review["info_request_note"] = note
    review["attested_by_user_id"] = None
    review["status"] = "RETURNED_FOR_INFO"
    db.touch(review)
    state.recompute_all()
    return record_response(review)


@bp.post("/qualification-reviews/<review_id>/decide")
def decide_review(review_id):
    mw.authorize(ROLE_STATE_REGULATOR)
    review = mw.resolve("qualification_reviews", review_id)
    body = mw.body_json()
    decision = mw.req_enum(body, "decision", DECISIONS)
    note = mw.opt_text(body, "decision_note")
    depository = db.get("depositories", review["depository_id"])
    if review["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE")
    if decision == "APPROVE" and review["attested_by_user_id"] is None:
        fail("ERR_INVALID_STATE")
    if review["requested_pledge_capacity_cents"] > PLEDGE_CAPACITY_STATUTORY_CEILING_CENTS:
        fail("ERR_CAPACITY_ABOVE_STATUTORY_CEILING")
    review["decision_note"] = note
    review["decided_at"] = db.now_ts()
    if decision == "APPROVE":
        review["status"] = "APPROVED"
        db.touch(review)
        if depository is not None:
            depository["approval_status"] = "APPROVED"
            depository["approved_at"] = db.now_ts()
            depository["approved_pledge_capacity_cents"] = review[
                "requested_pledge_capacity_cents"
            ]
            db.touch(depository)
    else:
        review["status"] = "DENIED"
        db.touch(review)
        if depository is not None:
            depository["approval_status"] = "DENIED"
            depository["approved_pledge_capacity_cents"] = 0
            db.touch(depository)
    state.recompute_all()
    return record_response(review)
