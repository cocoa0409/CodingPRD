"""Remediation programs, termination, appeals, forecasting and the logical clock."""
from flask import Blueprint

from db import by_seq, db, new_row, serialize, serialize_all
from errors import fail
from middleware import (
    authenticate,
    body,
    filter_enum,
    find_appeal,
    find_forecast,
    find_merchant,
    find_program,
    find_termination,
    opt_bool,
    opt_int,
    own_merchant,
    pagination,
    req_date,
    req_datetime,
    req_enum,
    req_id,
    req_int,
    req_str,
    req_str_list,
    touch,
)
from response import object_response, paged_response
from services.calc import (
    FAIL_RATIO_BPS,
    MAX_GRACE_MONTHS,
    evaluate_month,
    portfolio_forecast,
)
from services.cascades import (
    appeal_grant,
    remediation_fail,
    remediation_pass,
    termination_exec,
)
from services.metrics import (
    active_book,
    appeals_of_merchant,
    programs_of,
    recompute_trailing_metrics,
    terminations_of,
)
from util import date_plus

bp = Blueprint("enforcement", __name__)

PROGRAM_STATES = ("DRAFT", "ACTIVE", "PASSED", "FAILED", "NETWORK_ESCALATED")
TERMINATION_STATES = ("PROPOSED", "APPROVED", "REJECTED", "EXECUTED", "REVERSED")
TERMINATION_REASONS = ("EXCESSIVE_CHARGEBACKS", "SUSPECTED_LAUNDERING",
                       "PROHIBITED_ACTIVITY", "REMEDIATION_FAILURE")
APPEAL_STATES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "GRANTED", "UPHELD")
FORECAST_METHODS = ("EXPECTED_LOSS", "STRESSED")
ALL_STAFF = ("MerchantUser", "RiskAnalyst", "RiskCommitteeApprover", "PortfolioController")


# --------------------------------------------------------------------------
# remediation programs
# --------------------------------------------------------------------------
@bp.post("/remediation-programs")
def create_program():
    user_id, _ = authenticate(["RiskAnalyst"])
    payload = body()
    merchant_id = req_id(payload, "merchant_id")
    window_start_date = req_date(payload, "window_start_date")
    window_end_date = req_date(payload, "window_end_date")
    target_ratio_bps = req_int(payload, "target_ratio_bps", lo=1, hi=10000)
    monitoring_month_count = req_int(payload, "monitoring_month_count", lo=1, hi=6)

    merchant = find_merchant(merchant_id)
    if merchant["account_state"] == "TERMINATED":
        fail("ERR_MERCHANT_ACCOUNT_STATE_INVALID",
             "The merchant account_state is TERMINATED.")
    if not merchant["remediation_required"]:
        fail("ERR_REMEDIATION_NOT_REQUIRED",
             "The merchant is not flagged remediation_required.")
    for other in programs_of(merchant_id):
        if other["state"] not in ("DRAFT", "ACTIVE"):
            continue
        if (window_start_date < other["window_end_date"]
                and other["window_start_date"] < window_end_date):
            fail("ERR_REMEDIATION_WINDOW_OVERLAP",
                 "The window overlaps remediation program '%s'." % other["id"])

    program = new_row()
    program.update({
        "merchant_id": merchant_id,
        "target_ratio_bps": target_ratio_bps,
        "monitoring_month_count": monitoring_month_count,
        "window_start_date": window_start_date,
        "window_end_date": window_end_date,
        "state": "DRAFT",
        "months_elapsed": 0,
        "consecutive_compliant_months": 0,
        "last_observed_ratio_bps": None,
        "network_program_tier": "STANDARD",
        "opened_by_user_id": user_id,
        "activated_by_user_id": None,
    })
    db.programs[program["id"]] = program
    return object_response(serialize(program), 201)


@bp.post("/remediation-programs/<program_id>/activate")
def activate_program(program_id):
    user_id, _ = authenticate(["RiskCommitteeApprover"])
    program = find_program(program_id)
    merchant = db.merchants.get(program["merchant_id"])
    if merchant is None or merchant["account_state"] != "RESTRICTED":
        fail("ERR_MERCHANT_ACCOUNT_STATE_INVALID",
             "The merchant account_state must be RESTRICTED to activate a program.")
    if program["state"] != "DRAFT":
        fail("ERR_PROGRAM_STATE_INVALID",
             "Program state '%s' cannot be activated." % program["state"])
    if user_id == program["opened_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The activating user must differ from the user that opened the program.")

    program["state"] = "ACTIVE"
    program["activated_by_user_id"] = user_id
    touch(program)
    return object_response(serialize(program))


@bp.post("/remediation-programs/<program_id>/evaluate-month")
def evaluate_program_month(program_id):
    authenticate(["RiskAnalyst"])
    payload = body()
    month_index = req_int(payload, "month_index", lo=1)

    program = find_program(program_id)
    if program["state"] != "ACTIVE":
        fail("ERR_PROGRAM_STATE_INVALID",
             "Program state '%s' cannot be evaluated." % program["state"])
    if month_index != program["months_elapsed"] + 1:
        fail("ERR_MONTH_INDEX_OUT_OF_SEQUENCE",
             "month_index must equal months_elapsed + 1 (%s)."
             % (program["months_elapsed"] + 1))

    result = evaluate_month(program, month_index)
    program["months_elapsed"] += 1
    program["last_observed_ratio_bps"] = result["observed_ratio_bps"]
    if result["compliant"]:
        program["consecutive_compliant_months"] += 1
    else:
        program["consecutive_compliant_months"] = 0
    touch(program)

    merchant = db.merchants.get(program["merchant_id"])
    failed = (
        result["observed_ratio_bps"] >= FAIL_RATIO_BPS
        or (not result["compliant"]
            and program["months_elapsed"] >= program["monitoring_month_count"] + MAX_GRACE_MONTHS)
    )
    if failed:
        program["state"] = "FAILED"
        touch(program)
        if merchant is not None:
            remediation_fail(program, merchant, result["month_chargeback_count"])
    elif program["consecutive_compliant_months"] >= program["monitoring_month_count"]:
        program["state"] = "PASSED"
        touch(program)
        if merchant is not None:
            remediation_pass(merchant)

    return object_response(serialize(program))


@bp.get("/remediation-programs/<program_id>")
def get_program(program_id):
    authenticate(list(ALL_STAFF))
    program = find_program(program_id)
    own_merchant(program["merchant_id"])
    return object_response(serialize(program))


@bp.get("/merchants/<merchant_id>/remediation-programs")
def list_programs(merchant_id):
    authenticate(list(ALL_STAFF))
    state = filter_enum("state", PROGRAM_STATES)
    limit, offset = pagination()
    find_merchant(merchant_id)
    own_merchant(merchant_id)
    rows = sorted(programs_of(merchant_id), key=lambda p: (p["window_start_date"], p["_seq"]))
    if state:
        rows = [r for r in rows if r["state"] == state]
    return paged_response(serialize_all(rows), limit, offset)


# --------------------------------------------------------------------------
# termination
# --------------------------------------------------------------------------
@bp.post("/termination-decisions")
def propose_termination():
    user_id, _ = authenticate(["RiskAnalyst"])
    payload = body()
    merchant_id = req_id(payload, "merchant_id")
    reason_code = req_enum(payload, "reason_code", TERMINATION_REASONS)
    match_listing_flag = opt_bool(payload, "match_listing_flag", default=False)

    merchant = find_merchant(merchant_id)
    if merchant["account_state"] == "TERMINATED":
        fail("ERR_MERCHANT_ACCOUNT_STATE_INVALID",
             "The merchant account_state is already TERMINATED.")

    decision = new_row()
    decision.update({
        "merchant_id": merchant_id,
        "reason_code": reason_code,
        "match_listing_flag": match_listing_flag,
        "state": "PROPOSED",
        "proposed_by_user_id": user_id,
        "approved_by_user_id": None,
        "rejection_note": None,
        "executed_at": None,
        "reversed_at": None,
    })
    db.terminations[decision["id"]] = decision
    return object_response(serialize(decision), 201)


@bp.post("/termination-decisions/<decision_id>/approve")
def approve_termination(decision_id):
    user_id, _ = authenticate(["RiskCommitteeApprover"])
    decision = find_termination(decision_id)
    merchant = db.merchants.get(decision["merchant_id"])
    if merchant is not None and merchant["account_state"] == "TERMINATED":
        fail("ERR_MERCHANT_ACCOUNT_STATE_INVALID",
             "The merchant account_state is already TERMINATED.")
    if decision["state"] != "PROPOSED":
        fail("ERR_TERMINATION_STATE_INVALID",
             "Decision state '%s' cannot be approved." % decision["state"])
    if user_id == decision["proposed_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The approving user must differ from the proposing user.")

    decision["state"] = "APPROVED"
    decision["approved_by_user_id"] = user_id
    touch(decision)
    return object_response(serialize(decision))


@bp.post("/termination-decisions/<decision_id>/reject")
def reject_termination(decision_id):
    user_id, _ = authenticate(["RiskCommitteeApprover"])
    payload = body()
    rejection_note = req_str(payload, "rejection_note", max_len=2000)

    decision = find_termination(decision_id)
    if decision["state"] != "PROPOSED":
        fail("ERR_TERMINATION_STATE_INVALID",
             "Decision state '%s' cannot be rejected." % decision["state"])
    if user_id == decision["proposed_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The rejecting user must differ from the proposing user.")

    decision["state"] = "REJECTED"
    decision["rejection_note"] = rejection_note
    decision["approved_by_user_id"] = user_id
    touch(decision)
    return object_response(serialize(decision))


@bp.post("/termination-decisions/<decision_id>/execute")
def execute_termination(decision_id):
    authenticate(["PortfolioController"])
    decision = find_termination(decision_id)
    merchant = db.merchants.get(decision["merchant_id"])
    if merchant is None or merchant["account_state"] not in ("ACTIVE", "RESTRICTED"):
        fail("ERR_MERCHANT_ACCOUNT_STATE_INVALID",
             "The merchant account_state must be ACTIVE or RESTRICTED to execute a termination.")
    if any(p["state"] in ("DRAFT", "ACTIVE") for p in programs_of(merchant["id"])):
        fail("ERR_PROGRAM_STATE_INVALID",
             "An open remediation program must be resolved before termination.")
    if decision["state"] != "APPROVED":
        fail("ERR_TERMINATION_STATE_INVALID",
             "Decision state '%s' cannot be executed." % decision["state"])

    clock_iso = db.clock_iso()
    decision["state"] = "EXECUTED"
    decision["executed_at"] = clock_iso
    touch(decision)
    termination_exec(merchant, clock_iso)
    return object_response(serialize(decision))


@bp.get("/termination-decisions/<decision_id>")
def get_termination(decision_id):
    authenticate(list(ALL_STAFF))
    decision = find_termination(decision_id)
    own_merchant(decision["merchant_id"])
    return object_response(serialize(decision))


@bp.get("/merchants/<merchant_id>/termination-decisions")
def list_terminations(merchant_id):
    authenticate(list(ALL_STAFF))
    state = filter_enum("state", TERMINATION_STATES)
    limit, offset = pagination()
    find_merchant(merchant_id)
    own_merchant(merchant_id)
    rows = terminations_of(merchant_id)
    if state:
        rows = [r for r in rows if r["state"] == state]
    return paged_response(serialize_all(rows), limit, offset)


# --------------------------------------------------------------------------
# appeals
# --------------------------------------------------------------------------
@bp.post("/appeals")
def file_appeal():
    authenticate(["MerchantUser"])
    payload = body()
    merchant_id = req_id(payload, "merchant_id")
    termination_decision_id = req_id(payload, "termination_decision_id")
    evidence_summary = req_str(payload, "evidence_summary", max_len=2000)

    find_merchant(merchant_id)
    decision = find_termination(termination_decision_id)
    own_merchant(merchant_id)

    if decision["state"] != "EXECUTED" or decision["merchant_id"] != merchant_id:
        fail("ERR_APPEAL_DECISION_NOT_EXECUTED",
             "The appealed decision must be EXECUTED and belong to this merchant.")

    clock_date = db.clock_date()
    executed_date = (decision["executed_at"] or "")[:10]
    if executed_date and clock_date > date_plus(executed_date, 30):
        fail("ERR_APPEAL_WINDOW_EXPIRED",
             "The 30-day appeal window closed on '%s'." % date_plus(executed_date, 30))

    for other in db.appeals.values():
        if (other["termination_decision_id"] == termination_decision_id
                and other["state"] in ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED")):
            fail("ERR_DUPLICATE_APPEAL",
                 "An open appeal already contests this termination decision.")

    appeal = new_row()
    appeal.update({
        "merchant_id": merchant_id,
        "termination_decision_id": termination_decision_id,
        "evidence_summary": evidence_summary,
        "state": "SUBMITTED",
        "filed_on_date": clock_date,
        "outstanding_info_items": [],
        "response_round_count": 0,
        "reviewer_user_id": None,
        "reinstatement_reserve_pct_bps": None,
        "decided_at": None,
    })
    db.appeals[appeal["id"]] = appeal
    return object_response(serialize(appeal), 201)


@bp.post("/appeals/<appeal_id>/review")
def review_appeal(appeal_id):
    user_id, _ = authenticate(["RiskCommitteeApprover"])
    appeal = find_appeal(appeal_id)
    if appeal["state"] != "SUBMITTED":
        fail("ERR_APPEAL_STATE_INVALID",
             "Appeal state '%s' cannot be taken up for review." % appeal["state"])
    appeal["state"] = "UNDER_REVIEW"
    appeal["reviewer_user_id"] = user_id
    touch(appeal)
    return object_response(serialize(appeal))


@bp.post("/appeals/<appeal_id>/request-info")
def request_appeal_info(appeal_id):
    authenticate(["RiskCommitteeApprover"])
    payload = body()
    items = req_str_list(payload, "outstanding_info_items")
    appeal = find_appeal(appeal_id)
    if appeal["state"] != "UNDER_REVIEW":
        fail("ERR_APPEAL_STATE_INVALID",
             "Appeal state '%s' does not permit an information request." % appeal["state"])
    appeal["state"] = "INFO_REQUESTED"
    appeal["outstanding_info_items"] = items
    touch(appeal)
    return object_response(serialize(appeal))


@bp.post("/appeals/<appeal_id>/respond")
def respond_to_appeal(appeal_id):
    authenticate(["MerchantUser"])
    payload = body()
    req_str(payload, "response_text", max_len=4000)
    appeal = find_appeal(appeal_id)
    own_merchant(appeal["merchant_id"])
    if appeal["state"] != "INFO_REQUESTED":
        fail("ERR_APPEAL_STATE_INVALID",
             "Appeal state '%s' does not permit a response." % appeal["state"])
    appeal["state"] = "UNDER_REVIEW"
    appeal["outstanding_info_items"] = []
    appeal["response_round_count"] += 1
    touch(appeal)
    return object_response(serialize(appeal))


@bp.post("/appeals/<appeal_id>/decide")
def decide_appeal(appeal_id):
    user_id, _ = authenticate(["RiskCommitteeApprover"])
    payload = body()
    outcome = req_enum(payload, "outcome", ("GRANT", "UPHOLD"))
    reinstatement_pct = opt_int(payload, "reinstatement_reserve_pct_bps", lo=0, hi=10000)

    appeal = find_appeal(appeal_id)
    decision = db.terminations.get(appeal["termination_decision_id"])
    if outcome == "GRANT" and (decision is None or decision["state"] != "EXECUTED"):
        fail("ERR_TERMINATION_STATE_INVALID",
             "The appealed decision must be EXECUTED to grant an appeal.")
    if appeal["state"] != "UNDER_REVIEW":
        fail("ERR_APPEAL_STATE_INVALID",
             "Appeal state '%s' cannot be decided." % appeal["state"])
    if decision is not None and user_id in (decision["proposed_by_user_id"],
                                            decision["approved_by_user_id"]):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The deciding user may be neither the proposer nor the approver.")

    clock_iso = db.clock_iso()
    appeal["decided_at"] = clock_iso
    if outcome == "UPHOLD":
        appeal["state"] = "UPHELD"
        touch(appeal)
        return object_response(serialize(appeal))

    appeal["state"] = "GRANTED"
    if reinstatement_pct is not None:
        appeal["reinstatement_reserve_pct_bps"] = reinstatement_pct
    touch(appeal)

    merchant = db.merchants.get(appeal["merchant_id"])
    if merchant is not None:
        appeal_grant(appeal, decision, merchant, clock_iso, db.clock_date(), user_id)
    return object_response(serialize(appeal))


@bp.get("/appeals/<appeal_id>")
def get_appeal(appeal_id):
    authenticate(list(ALL_STAFF))
    appeal = find_appeal(appeal_id)
    own_merchant(appeal["merchant_id"])
    return object_response(serialize(appeal))


@bp.get("/merchants/<merchant_id>/appeals")
def list_merchant_appeals(merchant_id):
    authenticate(list(ALL_STAFF))
    state = filter_enum("state", APPEAL_STATES)
    limit, offset = pagination()
    find_merchant(merchant_id)
    own_merchant(merchant_id)
    rows = appeals_of_merchant(merchant_id)
    if state:
        rows = [r for r in rows if r["state"] == state]
    return paged_response(serialize_all(rows), limit, offset)


@bp.get("/termination-decisions/<decision_id>/appeals")
def list_decision_appeals(decision_id):
    authenticate(list(ALL_STAFF))
    state = filter_enum("state", APPEAL_STATES)
    limit, offset = pagination()
    decision = find_termination(decision_id)
    own_merchant(decision["merchant_id"])
    rows = by_seq([a for a in db.appeals.values()
                   if a["termination_decision_id"] == decision_id])
    if state:
        rows = [r for r in rows if r["state"] == state]
    return paged_response(serialize_all(rows), limit, offset)


# --------------------------------------------------------------------------
# portfolio forecasting
# --------------------------------------------------------------------------
@bp.post("/portfolio-forecasts")
def create_forecast():
    user_id, _ = authenticate(["PortfolioController"])
    payload = body()
    as_of_date = req_date(payload, "as_of_date")
    method = req_enum(payload, "method", FORECAST_METHODS)
    stress_multiplier_bps = opt_int(payload, "stress_multiplier_bps",
                                    default=25000, lo=10000, hi=100000)

    merchants = active_book()
    for merchant in merchants:
        recompute_trailing_metrics(merchant, as_of_date)

    computed = portfolio_forecast(merchants, method, stress_multiplier_bps)
    forecast = new_row()
    forecast.update({
        "as_of_date": as_of_date,
        "method": method,
        "stress_multiplier_bps": stress_multiplier_bps,
        "generated_by_user_id": user_id,
    })
    forecast.update(computed)
    db.forecasts[forecast["id"]] = forecast
    return object_response(serialize(forecast), 201)


@bp.get("/portfolio-forecasts/<forecast_id>")
def get_forecast(forecast_id):
    authenticate(["RiskAnalyst", "PortfolioController"])
    forecast = find_forecast(forecast_id)
    return object_response(serialize(forecast))


@bp.get("/portfolio-forecasts")
def list_forecasts():
    authenticate(["RiskAnalyst", "PortfolioController"])
    method = filter_enum("method", FORECAST_METHODS)
    limit, offset = pagination()
    rows = by_seq(list(db.forecasts.values()))
    if method:
        rows = [r for r in rows if r["method"] == method]
    return paged_response(serialize_all(rows), limit, offset)


# --------------------------------------------------------------------------
# the logical clock
# --------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(list(("Applicant", "MerchantUser", "UnderwritingOfficer", "RiskAnalyst",
                       "RiskCommitteeApprover", "PortfolioController")))
    payload = body()
    moment = req_datetime(payload, "now_utc")
    db.clock = moment
    return object_response(None)
