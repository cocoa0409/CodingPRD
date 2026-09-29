"""Audit selection, casework, assessment and collection (PRD 3.9)."""

from flask import Blueprint

import db
import helpers
import middleware
import response
import shape
from errors import ApiError
from middleware import (AUDIT_MANAGER, LICENSEE_AGENT, RETURNS_EXAMINER,
                        TAX_SUPERVISOR)
from services import calc, cascade, derive

bp = Blueprint("audits", __name__, url_prefix="/mft")

READ_ROLES = (AUDIT_MANAGER, TAX_SUPERVISOR, RETURNS_EXAMINER, LICENSEE_AGENT)

# The case dimension: current status -> the statuses it may move to.
CASE_EDGES = {
    "OPEN": ("FIELDWORK",),
    "FIELDWORK": ("PRELIM_FINDINGS",),
    "PRELIM_FINDINGS": ("TAXPAYER_RESPONSE", "CLOSED"),
    "TAXPAYER_RESPONSE": ("FIELDWORK",),
}


def _owner(row):
    return row["subject_licensee_id"]


@bp.post("/audit-cases")
def open_case():
    user_id, role = middleware.require(AUDIT_MANAGER)
    body = shape.body()
    subject_id = shape.req_id(body, "subject_licensee_id")
    selection_method = shape.req_enum(body, "selection_method",
                                      calc.SELECTION_METHODS)
    period_start = shape.req_month(body, "period_start_month")
    period_end = shape.req_month(body, "period_end_month")
    variant = shape.opt_enum(body, "risk_score_variant",
                             calc.RISK_SCORE_VARIANTS,
                             default="VARIANCE_WEIGHTED")
    source_id = shape.opt_id(body, "source_discrepancy_id")

    helpers.body_licensee(subject_id)
    source = (helpers.body_ref("discrepancy", source_id) if source_id else None)

    # Band 11: escalation-source consistency, all three conditions together.
    if source is not None:
        if (selection_method != "CROSS_MATCH_ESCALATION"
                or cascade.escalation_subject_id(source) != subject_id
                or source["status"] not in calc.OPEN_DISCREPANCY_STATUSES):
            raise ApiError("ERR_DISCREPANCY_SOURCE_MISMATCH")

    # Band 12: date ordering, then the buffered overlap rule.
    if db.month_index(period_end) < db.month_index(period_start):
        raise ApiError("ERR_DATE_RANGE_INVALID")
    if cascade.overlapping_open_case(subject_id, period_start,
                                    period_end) is not None:
        raise ApiError("ERR_AUDIT_PERIOD_OVERLAP")

    # Band 13: risk-score gating, consulted only under RISK_SCORE.
    selection_score = 0
    if selection_method == "RISK_SCORE":
        variance_weighted, frequency_weighted = derive.risk_scores(subject_id)
        selected = (variance_weighted if variant == "VARIANCE_WEIGHTED"
                    else frequency_weighted)
        if selected < calc.AUDIT_SELECTION_THRESHOLD:
            raise ApiError("ERR_RISK_SCORE_BELOW_THRESHOLD")
        selection_score = selected

    row = cascade.create_audit_case(subject_id, selection_method, variant,
                                    selection_score, period_start, period_end,
                                    user_id, source_discrepancy_id=source_id)
    return response.object_response(derive.audit_case_json(row), 201)


@bp.get("/audit-cases/<case_id>")
def read_case(case_id):
    user_id, role = middleware.require(*READ_ROLES)
    row = helpers.ensure("audit_case", helpers.peek(
        "audit_case", case_id, user_id, role, _owner))
    return response.object_response(derive.audit_case_json(row))


@bp.get("/audit-cases")
def list_cases():
    user_id, role = middleware.require(*READ_ROLES)
    rows = db.ordered(db.audit_cases)
    rows = helpers.agent_narrow(rows, _owner, user_id, role)
    rows = helpers.filter_by(rows, {
        "subject_licensee_id": "subject_licensee_id",
        "case_status": "case_status",
        "assessment_status": "assessment_status",
        "source_discrepancy_id": "source_discrepancy_id",
        "selection_method": "selection_method",
    })
    return response.list_response(rows, derive.audit_case_json)


@bp.post("/audit-cases/<case_id>/advance")
def advance_case(case_id):
    user_id, role = middleware.require(AUDIT_MANAGER)
    body = shape.body()
    to_status = shape.req_enum(body, "to_status", calc.CASE_STATUSES)
    row = helpers.find("audit_case", case_id)

    # Once case_status is CLOSED no action against the case is accepted.
    if to_status not in CASE_EDGES.get(row["case_status"], ()):
        raise ApiError("ERR_AUDIT_CASE_STATE_INVALID")

    if row["case_status"] == "TAXPAYER_RESPONSE" and to_status == "FIELDWORK":
        if row["response_rounds"] >= calc.MAX_AUDIT_RESPONSE_ROUNDS:
            raise ApiError("ERR_AUDIT_ROUND_LIMIT")

    if to_status == "CLOSED":
        if row["assessment_status"] not in ("NONE", "FINAL", "ABATED"):
            raise ApiError("ERR_ASSESSMENT_PENDING_DISPOSITION")

    if row["case_status"] == "TAXPAYER_RESPONSE" and to_status == "FIELDWORK":
        row["response_rounds"] += 1
    row["case_status"] = to_status
    db.touch(row)

    if to_status == "CLOSED":
        # Closure decrements open_audit_count; at zero the audit holds lift.
        if derive.open_audit_count(row["subject_licensee_id"]) == 0:
            cascade.release_holds(row["subject_licensee_id"], "OPEN_AUDIT")

    return response.object_response(derive.audit_case_json(row))


@bp.post("/audit-cases/<case_id>/assessments")
def issue_assessment(case_id):
    user_id, role = middleware.require(TAX_SUPERVISOR)
    body = shape.body()
    additional_tax_cents = shape.req_int(body, "additional_tax_cents", minimum=0)
    evasion_indicator = shape.req_bool(body, "evasion_indicator")
    row = helpers.find("audit_case", case_id)

    if row["case_status"] == "CLOSED":
        raise ApiError("ERR_AUDIT_CASE_STATE_INVALID")
    if row["assessment_status"] != "NONE":
        raise ApiError("ERR_ASSESSMENT_ALREADY_ISSUED")
    if row["case_status"] not in ("PRELIM_FINDINGS", "TAXPAYER_RESPONSE"):
        raise ApiError("ERR_AUDIT_CASE_STATE_INVALID")
    if (row["opened_by_user_id"] is not None
            and user_id == row["opened_by_user_id"]):
        raise ApiError("ERR_ASSESSMENT_SEGREGATION_VIOLATION")

    penalty, interest, total, _days = calc.assessment_amounts(
        additional_tax_cents, evasion_indicator, db.now(),
        db.period_due_at(row["period_end_month"]))

    row["additional_tax_cents"] = additional_tax_cents
    row["evasion_indicator"] = evasion_indicator
    row["assessment_penalty_cents"] = penalty
    row["assessment_interest_cents"] = interest
    row["assessed_total_cents"] = total
    row["assessment_status"] = "ISSUED"
    row["assessed_by_user_id"] = user_id
    db.touch(row)
    cascade.post_ledger(row["subject_licensee_id"], "ASSESSMENT", total,
                        "AuditCase", row["id"],
                        "Deficiency assessment for %s through %s"
                        % (row["period_start_month"], row["period_end_month"]))
    return response.object_response(derive.audit_case_json(row))


@bp.post("/audit-cases/<case_id>/abate")
def abate_assessment(case_id):
    user_id, role = middleware.require(TAX_SUPERVISOR)
    body = shape.body()
    abatement_reason = shape.req_str(body, "abatement_reason")
    row = helpers.find("audit_case", case_id)

    if row["case_status"] == "CLOSED":
        raise ApiError("ERR_AUDIT_CASE_STATE_INVALID")
    if row["assessment_status"] not in ("ISSUED", "PROTESTED"):
        raise ApiError("ERR_AUDIT_CASE_STATE_INVALID")
    if (row["assessed_by_user_id"] is not None
            and user_id == row["assessed_by_user_id"]):
        raise ApiError("ERR_ASSESSMENT_SEGREGATION_VIOLATION")
    # Abatement is always in full, so it may not mint a credit the state
    # does not owe.
    if derive.balance_cents(row["subject_licensee_id"]) < row["assessed_total_cents"]:
        raise ApiError("ERR_ABATEMENT_AMOUNT_INVALID")

    row["assessment_status"] = "ABATED"
    row["abatement_reason"] = abatement_reason
    db.touch(row)
    cascade.post_ledger(row["subject_licensee_id"], "ABATEMENT",
                        -row["assessed_total_cents"], "AuditCase", row["id"],
                        "Abatement in full: %s" % abatement_reason)
    return response.object_response(derive.audit_case_json(row))


@bp.post("/audit-cases/<case_id>/protest")
def protest_assessment(case_id):
    user_id, role = middleware.require(LICENSEE_AGENT)
    peeked = helpers.peek("audit_case", case_id, user_id, role, _owner)
    body = shape.body()
    protest_grounds = shape.req_str(body, "protest_grounds")
    row = helpers.ensure("audit_case", peeked)

    if row["case_status"] == "CLOSED":
        raise ApiError("ERR_AUDIT_CASE_STATE_INVALID")
    if row["assessment_status"] != "ISSUED":
        raise ApiError("ERR_AUDIT_CASE_STATE_INVALID")

    # A protest suspends collection but does not extinguish the liability,
    # so the ledger is deliberately left untouched.
    row["assessment_status"] = "PROTESTED"
    row["protest_grounds"] = protest_grounds
    db.touch(row)
    return response.object_response(derive.audit_case_json(row))


@bp.post("/audit-cases/<case_id>/finalize")
def finalize_assessment(case_id):
    middleware.require(TAX_SUPERVISOR)
    shape.body()
    row = helpers.find("audit_case", case_id)

    if row["case_status"] == "CLOSED":
        raise ApiError("ERR_AUDIT_CASE_STATE_INVALID")
    if row["assessment_status"] not in ("ISSUED", "PROTESTED"):
        raise ApiError("ERR_AUDIT_CASE_STATE_INVALID")

    row["assessment_status"] = "FINAL"
    db.touch(row)
    return response.object_response(derive.audit_case_json(row))
