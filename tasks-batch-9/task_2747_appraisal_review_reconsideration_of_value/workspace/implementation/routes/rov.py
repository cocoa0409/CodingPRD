"""Reconsideration of value intake, evidence, routing and disposition."""

from flask import Blueprint, request

import db
import response
import validate as V
from errors import fail
from middleware import (ROLE_AMC_COORDINATOR, ROLE_APPRAISER, ROLE_BORROWER,
                        ROLE_CHIEF_APPRAISER, ROLE_COMPLIANCE, ROLE_DESK_REVIEWER,
                        ROLE_LOAN_OFFICER, require_owner, require_roles)
from routes.common import (PREFIX, body_fk, filter_equals, find_loan, find_rov)
from services import constants as C
from services import evidence as evidence_svc
from services import loans as loan_svc
from services import panel as panel_svc
from services import revision as revision_svc

bp = Blueprint("rov", __name__)

ROV_ELIGIBLE_UNDERWRITING = ("SUBMITTED", "CONDITIONALLY_APPROVED", "SUSPENDED")
ROV_CONTESTABLE_REVIEW_STATUSES = ("RULES_CLEARED", "VALUE_ACCEPTED", "VALUE_REVISED")


def _refresh_admissible_count(rov):
    rov["admissible_evidence_count"] = sum(
        1 for item in db.rov_evidence.values()
        if item["rov_request_id"] == rov["id"]
        and item["round_number"] == rov["round_number"]
        and item["admissible"])
    db.touch(rov)


@bp.post(PREFIX + "/rov-requests")
def open_rov():
    user_id, role = require_roles(ROLE_BORROWER, ROLE_DESK_REVIEWER)
    data = V.body()

    claimed_loan = data.get("loan_file_id")
    if role == ROLE_BORROWER and isinstance(claimed_loan, str) and claimed_loan != "":
        require_owner(claimed_loan, user_id)

    loan = body_fk(data, "loan_file_id", db.loan_files, "ERR_LOAN_FILE_NOT_FOUND")
    appraisal = body_fk(data, "appraisal_id", db.appraisals, "ERR_APPRAISAL_NOT_FOUND")
    V.req_str(data, "loan_file_id")
    V.req_str(data, "appraisal_id")
    borrower_statement = V.req_str(data, "borrower_statement")
    requested_value = V.req_int(data, "requested_value_cents", positive=True)

    if loan["underwriting_status"] not in ROV_ELIGIBLE_UNDERWRITING:
        fail("ERR_LOAN_NOT_ROV_ELIGIBLE")
    if appraisal["loan_file_id"] != loan["id"]:
        fail("ERR_LOAN_NOT_ROV_ELIGIBLE")

    record = db.make_record({
        "loan_file_id": loan["id"],
        "appraisal_id": appraisal["id"],
        "borrower_statement": borrower_statement,
        "requested_value_cents": requested_value,
        "round_number": 1,
        "status": "INTAKE",
        "admissible_evidence_count": 0,
        "response_deadline_at": None,
        "appraiser_responded_at": None,
        "responded_late": False,
        "outcome": None,
        "revised_value_cents": None,
        "intake_note": None,
        "response_note": None,
        "next_round_reason": None,
        "closure_note": None,
    })
    db.rov_requests[record["id"]] = record
    loan_svc.refresh_rov_count(loan)
    return response.created(record)


@bp.get(PREFIX + "/rov-requests/<rov_id>")
def get_rov(rov_id):
    require_roles(ROLE_BORROWER, ROLE_DESK_REVIEWER, ROLE_CHIEF_APPRAISER,
                  ROLE_COMPLIANCE, ROLE_APPRAISER, ROLE_AMC_COORDINATOR)
    return response.ok(find_rov(rov_id))


@bp.get(PREFIX + "/rov-requests")
def list_rovs():
    require_roles(ROLE_DESK_REVIEWER, ROLE_CHIEF_APPRAISER, ROLE_COMPLIANCE,
                  ROLE_LOAN_OFFICER)
    rows = db.ordered(db.rov_requests)
    rows = filter_equals(rows, "loan_file_id")
    rows = filter_equals(rows, "appraisal_id")
    rows = filter_equals(rows, "status")
    return response.page(rows)


@bp.post(PREFIX + "/rov-requests/<rov_id>/evidence")
def file_evidence(rov_id):
    user_id, role = require_roles(ROLE_BORROWER, ROLE_DESK_REVIEWER)
    rov = find_rov(rov_id)
    if role == ROLE_BORROWER:
        require_owner(rov["loan_file_id"], user_id)
    data = V.body()
    evidence_type = V.req_enum(data, "evidence_type", C.EVIDENCE_TYPES)
    street_address = V.req_str(data, "street_address")
    sale_price = V.opt_int(data, "sale_price_cents", positive=True)
    sale_date = V.opt_dt(data, "sale_date")
    distance = V.opt_decimal_2dp(data, "distance_miles", minimum="0")
    citation_note = V.opt_str(data, "citation_note")

    appraisal = db.appraisals.get(rov["appraisal_id"])
    loan = find_loan(rov["loan_file_id"])
    admissible, reason = evidence_svc.judge(evidence_type, street_address, sale_price,
                                            sale_date, distance, citation_note,
                                            appraisal, loan)

    record = db.make_record({
        "rov_request_id": rov["id"],
        "evidence_type": evidence_type,
        "street_address": street_address,
        "sale_price_cents": sale_price,
        "sale_date": sale_date,
        "distance_miles": distance,
        "citation_note": citation_note,
        "admissible": admissible,
        "inadmissible_reason": reason,
        "round_number": rov["round_number"],
    })
    db.rov_evidence[record["id"]] = record
    _refresh_admissible_count(rov)
    return response.created(record)


@bp.get(PREFIX + "/rov-requests/<rov_id>/evidence")
def list_evidence(rov_id):
    require_roles(ROLE_BORROWER, ROLE_DESK_REVIEWER, ROLE_CHIEF_APPRAISER,
                  ROLE_COMPLIANCE, ROLE_APPRAISER)
    rov = find_rov(rov_id)
    rows = db.ordered(db.rov_evidence, lambda r: r["rov_request_id"] == rov["id"])
    if request.args.get("admissible") is not None:
        wanted = V.query_bool("admissible")
        rows = [r for r in rows if r["admissible"] is wanted]
    if request.args.get("round_number") is not None:
        wanted_round = V.query_int("round_number")
        rows = [r for r in rows if r["round_number"] == wanted_round]
    return response.page(rows)


@bp.post(PREFIX + "/rov-requests/<rov_id>/submit")
def route_rov(rov_id):
    require_roles(ROLE_DESK_REVIEWER)
    rov = find_rov(rov_id)
    data = V.body()
    intake_note = V.opt_str(data, "intake_note")

    appraisal = db.appraisals.get(rov["appraisal_id"])
    loan = find_loan(rov["loan_file_id"])

    if rov["status"] != "INTAKE":
        fail("ERR_INVALID_STATE")
    quarantined = loan_svc.appraisal_quarantined(appraisal)
    if not quarantined and appraisal["review_status"] not in ROV_CONTESTABLE_REVIEW_STATUSES:
        fail("ERR_INVALID_STATE")
    if quarantined:
        fail("ERR_BIAS_QUARANTINE_ACTIVE")
    if loan["underwriting_status"] not in ROV_ELIGIBLE_UNDERWRITING:
        fail("ERR_LOAN_NOT_ROV_ELIGIBLE")
    if appraisal["loan_file_id"] != loan["id"]:
        fail("ERR_LOAN_NOT_ROV_ELIGIBLE")
    if rov["admissible_evidence_count"] < C.MIN_ADMISSIBLE_EVIDENCE:
        fail("ERR_INSUFFICIENT_ADMISSIBLE_EVIDENCE")

    rov["status"] = "AWAITING_APPRAISER"
    rov["intake_note"] = intake_note
    rov["response_deadline_at"] = db.hours_after(db.now(), C.ROV_APPRAISER_RESPONSE_HOURS)
    db.bump(rov)

    appraisal["review_status"] = "VALUE_CONTESTED"
    db.bump(appraisal)
    if loan["collateral_status"] in ("VALUE_ACCEPTED", "VALUE_REVISED"):
        loan["collateral_status"] = "VALUE_CONTESTED"
        db.bump(loan)
    return response.ok(rov)


@bp.post(PREFIX + "/rov-requests/<rov_id>/appraiser-response")
def respond_rov(rov_id):
    user_id, _ = require_roles(ROLE_APPRAISER)
    rov = find_rov(rov_id)
    appraisal = db.appraisals.get(rov["appraisal_id"])
    require_owner(appraisal["appraiser_id"] if appraisal else None, user_id)
    data = V.body()
    outcome = V.req_enum(data, "outcome", C.ROV_OUTCOMES)
    response_note = V.req_str(data, "response_note")
    revised_value = V.opt_int(data, "revised_value_cents", positive=True)
    if outcome == "VALUE_REVISED" and revised_value is None:
        fail("ERR_INVALID_REQUEST", "revised_value_cents is required when revising.")

    if rov["status"] != "AWAITING_APPRAISER":
        fail("ERR_ROV_NOT_AWAITING_RESPONSE")

    if outcome == "VALUE_REVISED" and revision_svc.exceeds_cap(appraisal, revised_value):
        fail("ERR_REVISION_EXCEEDS_CAP")

    loan = find_loan(rov["loan_file_id"])
    instant = db.now()
    rov["status"] = "RESPONDED"
    rov["outcome"] = outcome
    rov["response_note"] = response_note
    rov["appraiser_responded_at"] = instant
    deadline = rov["response_deadline_at"]
    rov["responded_late"] = bool(deadline is not None and instant > deadline)
    if outcome == "VALUE_REVISED":
        rov["revised_value_cents"] = revised_value
    db.bump(rov)

    if outcome == "VALUE_AFFIRMED":
        appraisal["review_status"] = "VALUE_ACCEPTED"
        db.bump(appraisal)
        if loan["value_of_record_appraisal_id"] is None:
            loan["value_of_record_appraisal_id"] = appraisal["id"]
        loan["collateral_status"] = "VALUE_ACCEPTED"
        db.bump(loan)
        loan_svc.recompute_loan_values(loan)
    else:
        appraisal["review_status"] = "VALUE_REVISED"
        db.bump(appraisal)
        if loan["value_of_record_appraisal_id"] is None:
            loan["value_of_record_appraisal_id"] = appraisal["id"]
        loan["collateral_status"] = "VALUE_REVISED"
        db.bump(loan)
        revision_svc.write_revision(appraisal, loan, "ROV", rov["id"],
                                    revised_value, response_note)
        author = db.appraisers.get(appraisal["appraiser_id"])
        if author is not None:
            panel_svc.recompute_performance(author)
    return response.ok(rov)


@bp.post(PREFIX + "/rov-requests/<rov_id>/next-round")
def next_round(rov_id):
    require_roles(ROLE_DESK_REVIEWER)
    rov = find_rov(rov_id)
    data = V.body()
    reason = V.req_str(data, "next_round_reason")

    if rov["status"] != "RESPONDED":
        fail("ERR_INVALID_STATE")
    if rov["round_number"] >= C.MAX_ROV_ROUNDS:
        fail("ERR_ROV_ROUND_LIMIT")

    rov["status"] = "INTAKE"
    rov["round_number"] += 1
    rov["next_round_reason"] = reason
    rov["response_deadline_at"] = None
    rov["appraiser_responded_at"] = None
    rov["responded_late"] = False
    rov["outcome"] = None
    rov["revised_value_cents"] = None
    db.bump(rov)
    _refresh_admissible_count(rov)
    return response.ok(rov)


@bp.post(PREFIX + "/rov-requests/<rov_id>/finalize")
def finalize_rov(rov_id):
    require_roles(ROLE_DESK_REVIEWER)
    rov = find_rov(rov_id)
    data = V.body()
    closure_note = V.req_str(data, "closure_note")

    if rov["status"] != "RESPONDED":
        fail("ERR_INVALID_STATE")

    rov["status"] = ("CLOSED_AFFIRMED" if rov["outcome"] == "VALUE_AFFIRMED"
                    else "CLOSED_REVISED")
    rov["closure_note"] = closure_note
    db.bump(rov)
    return response.ok(rov)
