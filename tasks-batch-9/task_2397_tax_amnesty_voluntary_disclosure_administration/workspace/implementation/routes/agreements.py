"""Voluntary disclosure agreements and the disclosure returns beneath them."""

from flask import Blueprint

import calc
import clock
import db
import middleware as mw
import response
import services
import validate
from errors import err
from middleware import (COMPLIANCE_AUDITOR, DISCLOSURE_OFFICER,
                        PROGRAM_ADMINISTRATOR, REPRESENTATIVE, TAXPAYER)

bp = Blueprint("agreements", __name__)

READERS = [PROGRAM_ADMINISTRATOR, DISCLOSURE_OFFICER, COMPLIANCE_AUDITOR, TAXPAYER,
           REPRESENTATIVE]
PLAN_READERS = [PROGRAM_ADMINISTRATOR, DISCLOSURE_OFFICER, COMPLIANCE_AUDITOR, TAXPAYER]
FILERS = [TAXPAYER, REPRESENTATIVE]


def _check_lookback(program, start_date, end_date):
    """Precedence rule 25."""
    earliest = calc.add_months(program["_open_dt"].date(), -program["lookback_months"])
    if start_date < earliest or end_date < start_date:
        raise err("ERR_LOOKBACK_EXCEEDS_PROGRAM_LIMIT")


# =============================================================================
# agreements
# =============================================================================
@bp.post("/amnesty/agreements")
def create_agreement():
    user_id, _ = mw.identity([DISCLOSURE_OFFICER])
    body = validate.get_body()
    program = mw.body_fk(body, "program_id", db.programs, "ERR_PROGRAM_NOT_FOUND")
    mw.body_fk(body, "taxpayer_id", db.taxpayers, "ERR_TAXPAYER_NOT_FOUND")
    pre_clearance = mw.body_fk(body, "pre_clearance_id", db.pre_clearances,
                               "ERR_PRE_CLEARANCE_NOT_FOUND")

    program_id = validate.vid(body, "program_id")
    taxpayer_id = validate.vid(body, "taxpayer_id")
    tax_types = validate.vtax_types(body, "tax_types")
    start_date = validate.vdate(body, "lookback_start_date")
    end_date = validate.vdate(body, "lookback_end_date")
    pre_clearance_id = validate.vid(body, "pre_clearance_id", required=False)
    compliance_months = validate.vint(body, "prospective_compliance_months", required=False)

    services.check_program_open(program)
    services.check_program_eligibility(taxpayer_id, tax_types)
    services.check_window_live(program)
    _check_lookback(program, start_date, end_date)

    if pre_clearance_id is not None:
        if pre_clearance["status"] != "ACCEPTED":
            raise err("ERR_PRECLEARANCE_NOT_ACCEPTED")
        if pre_clearance["disclosed_taxpayer_id"] != taxpayer_id:
            raise err("ERR_PRECLEARANCE_TAXPAYER_MISMATCH")

    for tax_type in tax_types:
        if not services.terms_for_tax_type(program_id, tax_type):
            raise err("ERR_TAX_TYPE_NOT_IN_PROGRAM")

    if compliance_months is None:
        compliance_months = program["prospective_compliance_months"]

    rec = db.insert(db.agreements, {
        "program_id": program_id,
        "taxpayer_id": taxpayer_id,
        "pre_clearance_id": pre_clearance_id,
        "amends_agreement_id": None,
        "tax_types": list(tax_types),
        "lookback_start_date": body["lookback_start_date"],
        "lookback_end_date": body["lookback_end_date"],
        "prospective_compliance_months": compliance_months,
        "liability_variant": "VDA_NEGOTIATED" if pre_clearance_id else "AMNESTY_STATUTORY",
        "status": "DRAFTED",
        "payment_status": "UNPAID",
        "gross_liability_cents": 0,
        "haircut_pct": 0,
        "effective_penalty_waiver_pct": None,
        "effective_interest_waiver_pct": None,
        "waived_amount_cents": 0,
        "reinstated_amount_cents": 0,
        "total_due_cents": 0,
        "paid_total_cents": 0,
        "unapplied_credit_cents": 0,
        "down_payment_applied_cents": 0,
        "drafted_by_user_id": user_id,
        "executed_by_user_id": None,
        "executed_at": None,
        "compliance_due_at": None,
        "breach_reason": None,
    })
    return response.created(services.agreement_out(rec))


@bp.get("/amnesty/agreements")
def list_agreements():
    mw.identity(PLAN_READERS)
    limit, offset = response.pagination()
    rows = db.ordered(list(db.agreements.values()))
    for field in ("program_id", "taxpayer_id", "pre_clearance_id", "amends_agreement_id",
                  "status", "payment_status"):
        rows = mw.filter_equals(rows, field)
    return response.paginate(rows, limit, offset, services.agreement_out)


@bp.get("/amnesty/agreements/<agreement_id>")
def read_agreement(agreement_id):
    user_id, role = mw.identity(READERS)
    agreement = mw.find(db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    mw.require_agreement_owner(agreement, user_id, role)
    return response.ok(services.agreement_out(agreement))


@bp.post("/amnesty/agreements/<agreement_id>/execute")
def execute_agreement(agreement_id):
    user_id, _ = mw.identity([DISCLOSURE_OFFICER])
    agreement = mw.find(db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    program = services.program_of(agreement)

    services.check_program_open(program)
    if agreement["status"] != "DRAFTED":
        raise err("ERR_AGREEMENT_NOT_DRAFTED")
    services.check_program_eligibility(agreement["taxpayer_id"], agreement["tax_types"])
    mw.require_segregation(agreement["drafted_by_user_id"], user_id)
    services.check_window_live(program)

    executed_at = clock.now()
    agreement["status"] = "EXECUTED"
    agreement["executed_by_user_id"] = user_id
    agreement["executed_at"] = clock.iso(executed_at)
    agreement["compliance_due_at"] = clock.iso(
        calc.add_months(executed_at, agreement["prospective_compliance_months"]))
    db.touch(agreement)
    return response.ok(services.agreement_out(agreement))


@bp.post("/amnesty/agreements/<agreement_id>/amend")
def amend_agreement(agreement_id):
    user_id, _ = mw.identity([DISCLOSURE_OFFICER])
    agreement = mw.find(db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    body = validate.get_body()

    expected_version = validate.vint(body, "expected_agreement_version")
    start_date = validate.vdate(body, "lookback_start_date")
    end_date = validate.vdate(body, "lookback_end_date")
    compliance_months = validate.vint(body, "prospective_compliance_months", required=False)

    if expected_version != agreement["version"]:
        raise err("ERR_STALE_AGREEMENT_VERSION")
    program = services.program_of(agreement)
    services.check_program_open(program)
    if agreement["status"] != "EXECUTED":
        raise err("ERR_AGREEMENT_NOT_EXECUTED")
    services.check_window_live(program)
    _check_lookback(program, start_date, end_date)

    if compliance_months is None:
        compliance_months = agreement["prospective_compliance_months"]

    fresh = db.insert(db.agreements, {
        "program_id": agreement["program_id"],
        "taxpayer_id": agreement["taxpayer_id"],
        "pre_clearance_id": agreement["pre_clearance_id"],
        "amends_agreement_id": agreement["id"],
        "tax_types": list(agreement["tax_types"]),
        "lookback_start_date": body["lookback_start_date"],
        "lookback_end_date": body["lookback_end_date"],
        "prospective_compliance_months": compliance_months,
        "liability_variant": agreement["liability_variant"],
        "status": "DRAFTED",
        "payment_status": "UNPAID",
        "gross_liability_cents": 0,
        "haircut_pct": 0,
        "effective_penalty_waiver_pct": None,
        "effective_interest_waiver_pct": None,
        "waived_amount_cents": 0,
        "reinstated_amount_cents": 0,
        "total_due_cents": 0,
        "paid_total_cents": 0,
        "unapplied_credit_cents": 0,
        "down_payment_applied_cents": 0,
        "drafted_by_user_id": user_id,
        "executed_by_user_id": None,
        "executed_at": None,
        "compliance_due_at": None,
        "breach_reason": None,
    })

    agreement["status"] = "SUPERSEDED"
    db.touch(agreement)
    # amendment brings a new agreement into existence, so the fresh draft is the
    # created resource this operation reports
    return response.created(services.agreement_out(fresh))


@bp.post("/amnesty/agreements/<agreement_id>/certify-compliance")
def certify_compliance(agreement_id):
    mw.identity([COMPLIANCE_AUDITOR])
    agreement = mw.find(db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    if agreement["status"] != "EXECUTED":
        raise err("ERR_AGREEMENT_NOT_EXECUTED")

    rows = services.agreement_returns(agreement_id)
    if not rows:
        raise err("ERR_NO_DISCLOSURE_RETURNS")
    for ret in rows:
        if ret["status"] != "VOIDED" and ret["status"] != "SETTLED":
            raise err("ERR_RETURNS_NOT_SETTLED")
    due_at = clock.parse_timestamp(agreement["compliance_due_at"])
    if due_at is None or clock.now() < due_at:
        raise err("ERR_COMPLIANCE_PERIOD_NOT_ELAPSED")

    agreement["status"] = "FULFILLED"
    db.touch(agreement)
    return response.ok(services.agreement_out(agreement))


@bp.post("/amnesty/agreements/<agreement_id>/declare-breach")
def declare_breach(agreement_id):
    mw.identity([COMPLIANCE_AUDITOR])
    agreement = mw.find(db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    body = validate.get_body()
    breach_reason = validate.vstr(body, "breach_reason")

    if agreement["status"] != "EXECUTED":
        raise err("ERR_AGREEMENT_NOT_EXECUTED")
    reinstatable = [r for r in services.agreement_returns(agreement_id)
                    if r["status"] in services.WAIVER_QUALIFYING]
    if agreement["waived_amount_cents"] <= 0 and not reinstatable:
        raise err("ERR_NOTHING_TO_REINSTATE")

    services.declare_breach_cascade(agreement, breach_reason)
    return response.ok(services.agreement_out(agreement))


@bp.post("/amnesty/agreements/<agreement_id>/rescind-breach")
def rescind_breach(agreement_id):
    mw.identity([COMPLIANCE_AUDITOR])
    agreement = mw.find(db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    body = validate.get_body()
    validate.vstr(body, "rescind_reason")

    if agreement["status"] != "BREACHED":
        raise err("ERR_AGREEMENT_NOT_BREACHED")
    program = services.program_of(agreement)
    if program["status"] not in ("OPEN", "CLOSED"):
        raise err("ERR_PROGRAM_NOT_OPEN")

    services.rescind_breach_cascade(agreement)
    return response.ok(services.agreement_out(agreement))


# =============================================================================
# disclosure returns
# =============================================================================
def _match_term(agreement, tax_type, start_date, end_date):
    """Rule 27: locate the term whose half-open window contains the period."""
    candidates = services.terms_for_tax_type(agreement["program_id"], tax_type)
    if not candidates:
        return None
    for term in candidates:
        term_start = clock.parse_date(term["eligible_period_start"])
        term_end = clock.parse_date(term["eligible_period_end"])
        if start_date >= term_start and end_date < term_end:
            return term
    raise err("ERR_PERIOD_OUTSIDE_ELIGIBLE_WINDOW")


@bp.post("/amnesty/agreements/<agreement_id>/returns")
def create_return(agreement_id):
    user_id, role = mw.identity(FILERS)
    agreement = mw.find(db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    mw.require_agreement_owner(agreement, user_id, role)
    body = validate.get_body()

    tax_type = validate.venum(body, "tax_type", validate.TAX_TYPES)
    start_date = validate.vdate(body, "period_start_date")
    end_date = validate.vdate(body, "period_end_date")
    validate.vdate(body, "original_due_date")
    reported_tax = validate.vint(body, "reported_tax_cents", minimum=1)
    is_nonfiler = validate.vbool(body, "is_nonfiler_period", required=False, default=False)

    if agreement["status"] not in ("DRAFTED", "EXECUTED"):
        raise err("ERR_AGREEMENT_NOT_EXECUTED")
    services.check_window_live(services.program_of(agreement))

    lookback_start = clock.parse_date(agreement["lookback_start_date"])
    lookback_end = clock.parse_date(agreement["lookback_end_date"])
    if start_date < lookback_start or end_date > lookback_end:
        raise err("ERR_PERIOD_OUTSIDE_LOOKBACK")

    term = _match_term(agreement, tax_type, start_date, end_date)

    for existing in services.agreement_returns(agreement_id):
        if existing["status"] == "VOIDED" or existing["tax_type"] != tax_type:
            continue
        other_start = clock.parse_date(existing["period_start_date"])
        other_end = clock.parse_date(existing["period_end_date"])
        if start_date <= other_end and other_start <= end_date:
            raise err("ERR_RETURN_PERIOD_OVERLAP")

    if tax_type not in agreement["tax_types"]:
        raise err("ERR_TAX_TYPE_NOT_IN_AGREEMENT")
    if term is not None:
        if term["requires_prior_nonfiler"] and not is_nonfiler:
            raise err("ERR_NONFILER_PERIOD_REQUIRED")
        if reported_tax < term["min_liability_cents"]:
            raise err("ERR_BELOW_MINIMUM_LIABILITY")

    rec = db.insert(db.returns, {
        "agreement_id": agreement_id,
        "tax_type": tax_type,
        "period_start_date": body["period_start_date"],
        "period_end_date": body["period_end_date"],
        "original_due_date": body["original_due_date"],
        "reported_tax_cents": reported_tax,
        "is_nonfiler_period": is_nonfiler,
        "accrual_end_date": None,
        "days_late": 0,
        "penalty_rate_applied": None,
        "gross_penalty_cents": 0,
        "gross_interest_cents": 0,
        "waived_penalty_cents": 0,
        "waived_interest_cents": 0,
        "payable_penalty_cents": 0,
        "payable_interest_cents": 0,
        "balance_due_cents": 0,
        "status": "DRAFT",
        "filed_at": None,
        "assessed_by_user_id": None,
        "_term_id": term["id"] if term is not None else None,
    })
    return response.created(services.return_out(rec))


@bp.get("/amnesty/agreements/<agreement_id>/returns")
def list_agreement_returns(agreement_id):
    user_id, role = mw.identity(READERS)
    agreement = mw.find(db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")
    mw.require_agreement_owner(agreement, user_id, role)
    limit, offset = response.pagination()
    rows = mw.filter_equals(services.agreement_returns(agreement_id), "status")
    rows = mw.filter_equals(rows, "tax_type")
    return response.paginate(rows, limit, offset, services.return_out)


@bp.get("/amnesty/returns/<return_id>")
def read_return(return_id):
    user_id, role = mw.identity(READERS)
    ret = mw.find(db.returns, return_id, "ERR_RETURN_NOT_FOUND")
    mw.require_agreement_owner(services.agreement_of_return(ret), user_id, role)
    return response.ok(services.return_out(ret))


@bp.post("/amnesty/returns/<return_id>/file")
def file_return(return_id):
    user_id, role = mw.identity(FILERS)
    ret = mw.find(db.returns, return_id, "ERR_RETURN_NOT_FOUND")
    agreement = services.agreement_of_return(ret)
    mw.require_agreement_owner(agreement, user_id, role)

    if agreement["status"] != "EXECUTED":
        raise err("ERR_AGREEMENT_NOT_EXECUTED")
    if ret["status"] != "DRAFT":
        raise err("ERR_RETURN_NOT_DRAFT")
    program = services.program_of(agreement)
    services.check_program_open(program)
    services.check_window_live(program)

    if agreement["liability_variant"] == "VDA_NEGOTIATED":
        accrual_end = clock.date_of(agreement["executed_at"])
    else:
        accrual_end = program["_close_dt"].date()

    days_late, rate, gross_penalty, gross_interest = calc.statutory_liability(
        ret["reported_tax_cents"],
        clock.parse_date(ret["original_due_date"]),
        accrual_end,
        ret["is_nonfiler_period"],
    )
    ret["accrual_end_date"] = accrual_end.isoformat()
    ret["days_late"] = days_late
    ret["penalty_rate_applied"] = calc.pct_out(rate)
    ret["gross_penalty_cents"] = gross_penalty
    ret["gross_interest_cents"] = gross_interest
    ret["status"] = "FILED"
    ret["filed_at"] = clock.now_iso()

    services.refresh_effective_waiver(agreement, ret)
    revised = services.waiver_rollup(agreement)
    if not any(row is ret for row in revised):
        revised.append(ret)
    for row in revised:
        db.touch(row)
    db.touch(agreement)
    return response.ok(services.return_out(ret))


@bp.post("/amnesty/returns/<return_id>/assess")
def assess_return(return_id):
    user_id, _ = mw.identity([DISCLOSURE_OFFICER])
    ret = mw.find(db.returns, return_id, "ERR_RETURN_NOT_FOUND")
    agreement = services.agreement_of_return(ret)
    if agreement["status"] != "EXECUTED":
        raise err("ERR_AGREEMENT_NOT_EXECUTED")
    if ret["status"] != "FILED":
        raise err("ERR_RETURN_NOT_FILED")
    ret["status"] = "ASSESSED"
    ret["assessed_by_user_id"] = user_id
    db.touch(ret)
    return response.ok(services.return_out(ret))
