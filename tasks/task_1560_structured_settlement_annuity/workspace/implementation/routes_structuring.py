"""Routes: settlement agreements, qualified assignments, annuity policies,
payment schedules, scheduled payments."""

from flask import Blueprint, request

from db import DB, CLOCK, base_entity, touch, parse_date, clock_date_iso
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_STATE_PROFILE_NOT_FOUND,
    ERR_DUPLICATE_CASE_NUMBER,
    ERR_AGREEMENT_INVALID_STATE,
    ERR_ASSIGNMENT_INVALID_STATE,
    ERR_POLICY_INVALID_STATE,
    ERR_SCHEDULE_INVALID_STATE,
    ERR_SCHEDULE_HAS_PAYMENTS,
    ERR_STALE_AGREEMENT_VERSION,
    ERR_INVALID_REQUEST,
)
from middleware import (
    get_caller, require_roles, get_json_body, check_unknown_fields,
    require_field, opt_field, as_string, as_int, as_positive_int,
    as_nonnegative_int, as_date, as_enum, parse_pagination,
)
from response import success_object, success_list
from services import (
    pub, list_view, find_profile_by_state, active_schedule_for,
    recompute_agreement_totals, escalated_amounts, escalation_exponent,
    compute_is_minor, active_guardianship,
)

bp = Blueprint("structuring", __name__)


# ---------------------------------------------------------------------------
# SettlementAgreement
# ---------------------------------------------------------------------------

AGREEMENT_FIELDS = {
    "case_number", "court_state_code", "obligor_name", "injury_type",
    "primary_payee_id", "agreement_date",
}


def agreement_view(a):
    return pub(a)


@bp.route("/annuity/settlement-agreements", methods=["POST"])
def create_agreement():
    caller = get_caller()
    require_roles(caller, {"CaseManager"})
    body = get_json_body()
    # existence: primary_payee_id, court_state_code
    ppid = body.get("primary_payee_id")
    if ppid is not None and isinstance(ppid, str) and ppid not in DB.payees:
        raise ApiError(ERR_NOT_FOUND, "Payee not found", 404)
    csc = body.get("court_state_code")
    if csc is not None and isinstance(csc, str) and find_profile_by_state(csc) is None:
        raise ApiError(ERR_STATE_PROFILE_NOT_FOUND, "No StateStatuteProfile for court_state_code", 404)
    # business: unique case_number
    cn = body.get("case_number")
    if cn is not None and isinstance(cn, str):
        for a in DB.settlement_agreements.values():
            if a["case_number"] == cn:
                raise ApiError(ERR_DUPLICATE_CASE_NUMBER, "Settlement agreement case_number already exists", 409)
    check_unknown_fields(body, AGREEMENT_FIELDS)
    cn = as_string(require_field(body, "case_number"), "case_number")
    csc = as_string(require_field(body, "court_state_code"), "court_state_code")
    if find_profile_by_state(csc) is None:
        raise ApiError(ERR_STATE_PROFILE_NOT_FOUND, "No StateStatuteProfile for court_state_code", 404)
    obligor = as_string(require_field(body, "obligor_name"), "obligor_name")
    injury = as_enum(require_field(body, "injury_type"), "injury_type", {"PHYSICAL", "NON_PHYSICAL"})
    ppid = as_string(require_field(body, "primary_payee_id"), "primary_payee_id")
    if ppid not in DB.payees:
        raise ApiError(ERR_NOT_FOUND, "Payee not found", 404)
    adate = as_date(require_field(body, "agreement_date"), "agreement_date")

    e = base_entity()
    e.update({
        "case_number": cn,
        "court_state_code": csc,
        "obligor_name": obligor,
        "injury_type": injury,
        "primary_payee_id": ppid,
        "agreement_date": adate.isoformat(),
        "status": "DRAFT",
        "total_scheduled_cents": 0,
        "outstanding_liability_cents": 0,
        "paid_total_cents": 0,
        "escheated_total_cents": 0,
        "transferred_total_cents": 0,
        "commuted_nominal_total_cents": 0,
    })
    DB.settlement_agreements[e["id"]] = e
    return success_object(agreement_view(e), status=201)


@bp.route("/annuity/settlement-agreements", methods=["GET"])
def list_agreements():
    caller = get_caller()
    require_roles(caller, {"Any"})
    limit, offset = parse_pagination(request.args)
    items = list(DB.settlement_agreements.values())
    st = request.args.get("status")
    if st is not None:
        items = [a for a in items if a["status"] == st]
    csc = request.args.get("court_state_code")
    if csc is not None:
        items = [a for a in items if a["court_state_code"] == csc]
    ppid = request.args.get("primary_payee_id")
    if ppid is not None:
        items = [a for a in items if a["primary_payee_id"] == ppid]
    page, total = list_view(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/annuity/settlement-agreements/<agreementId>", methods=["GET"])
def get_agreement(agreementId):
    caller = get_caller()
    require_roles(caller, {"Any"})
    a = DB.settlement_agreements.get(agreementId)
    if a is None:
        raise ApiError(ERR_NOT_FOUND, "SettlementAgreement not found", 404)
    return success_object(agreement_view(a))


@bp.route("/annuity/settlement-agreements/<agreementId>/execute", methods=["POST"])
def execute_agreement(agreementId):
    caller = get_caller()
    require_roles(caller, {"CaseManager"})
    a = DB.settlement_agreements.get(agreementId)
    if a is None:
        raise ApiError(ERR_NOT_FOUND, "SettlementAgreement not found", 404)
    if a["status"] != "DRAFT":
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, "Agreement not DRAFT", 409)
    get_json_body()
    a["status"] = "EXECUTED"
    touch(a)
    return success_object(agreement_view(a))


# ---------------------------------------------------------------------------
# QualifiedAssignment
# ---------------------------------------------------------------------------

ASSIGNMENT_FIELDS = {"settlement_agreement_id", "assignment_company_name", "executed_date"}


def assignment_view(a):
    return pub(a)


@bp.route("/annuity/qualified-assignments", methods=["POST"])
def create_assignment():
    caller = get_caller()
    require_roles(caller, {"CaseManager"})
    body = get_json_body()
    said = body.get("settlement_agreement_id")
    agreement = None
    if said is not None and isinstance(said, str):
        agreement = DB.settlement_agreements.get(said)
        if agreement is None:
            raise ApiError(ERR_NOT_FOUND, "SettlementAgreement not found", 404)
    # cross-entity state (priority 18): agreement must be EXECUTED
    if agreement is not None and agreement["status"] != "EXECUTED":
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, "Agreement not EXECUTED", 409)
    check_unknown_fields(body, ASSIGNMENT_FIELDS)
    said = as_string(require_field(body, "settlement_agreement_id"), "settlement_agreement_id")
    agreement = DB.settlement_agreements.get(said)
    if agreement is None:
        raise ApiError(ERR_NOT_FOUND, "SettlementAgreement not found", 404)
    if agreement["status"] != "EXECUTED":
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, "Agreement not EXECUTED", 409)
    qac = as_string(require_field(body, "assignment_company_name"), "assignment_company_name")
    exd = as_date(require_field(body, "executed_date"), "executed_date")

    e = base_entity()
    e.update({
        "settlement_agreement_id": said,
        "assignment_company_name": qac,
        "executed_date": exd.isoformat(),
        "status": "EXECUTED",
    })
    DB.qualified_assignments[e["id"]] = e
    # cascade: agreement EXECUTED -> ASSIGNED
    agreement["status"] = "ASSIGNED"
    touch(agreement)
    return success_object(assignment_view(e), status=201)


@bp.route("/annuity/qualified-assignments", methods=["GET"])
def list_assignments():
    caller = get_caller()
    require_roles(caller, {"Any"})
    limit, offset = parse_pagination(request.args)
    items = list(DB.qualified_assignments.values())
    said = request.args.get("settlement_agreement_id")
    if said is not None:
        items = [a for a in items if a["settlement_agreement_id"] == said]
    st = request.args.get("status")
    if st is not None:
        items = [a for a in items if a["status"] == st]
    page, total = list_view(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/annuity/qualified-assignments/<assignmentId>", methods=["GET"])
def get_assignment(assignmentId):
    caller = get_caller()
    require_roles(caller, {"Any"})
    a = DB.qualified_assignments.get(assignmentId)
    if a is None:
        raise ApiError(ERR_NOT_FOUND, "QualifiedAssignment not found", 404)
    return success_object(assignment_view(a))


@bp.route("/annuity/qualified-assignments/<assignmentId>/release", methods=["POST"])
def release_assignment(assignmentId):
    caller = get_caller()
    require_roles(caller, {"ComplianceOfficer"})
    a = DB.qualified_assignments.get(assignmentId)
    if a is None:
        raise ApiError(ERR_NOT_FOUND, "QualifiedAssignment not found", 404)
    if a["status"] != "EXECUTED":
        raise ApiError(ERR_ASSIGNMENT_INVALID_STATE, "Assignment not EXECUTED", 409)
    # requires a linked policy IN_FORCE | PARTIALLY_COMMUTED
    ok = False
    for pol in DB.annuity_policies.values():
        if pol["qualified_assignment_id"] == a["id"] and pol["status"] in ("IN_FORCE", "PARTIALLY_COMMUTED"):
            ok = True
            break
    if not ok:
        raise ApiError(ERR_POLICY_INVALID_STATE, "No linked policy IN_FORCE or PARTIALLY_COMMUTED", 409)
    get_json_body()
    a["status"] = "RELEASED"
    touch(a)
    return success_object(assignment_view(a))


# ---------------------------------------------------------------------------
# AnnuityPolicy
# ---------------------------------------------------------------------------

POLICY_FIELDS = {
    "settlement_agreement_id", "qualified_assignment_id", "policy_number",
    "insurer_name", "premium_cents", "contract_discount_rate_bps",
    "commutation_rider", "certain_period_end_date",
}


def policy_view(p):
    return pub(p)


@bp.route("/annuity/annuity-policies", methods=["POST"])
def create_policy():
    caller = get_caller()
    require_roles(caller, {"CaseManager"})
    body = get_json_body()
    said = body.get("settlement_agreement_id")
    agreement = None
    if said is not None and isinstance(said, str):
        agreement = DB.settlement_agreements.get(said)
        if agreement is None:
            raise ApiError(ERR_NOT_FOUND, "SettlementAgreement not found", 404)
    qaid = body.get("qualified_assignment_id")
    assignment = None
    if qaid is not None and isinstance(qaid, str):
        assignment = DB.qualified_assignments.get(qaid)
        if assignment is None:
            raise ApiError(ERR_NOT_FOUND, "QualifiedAssignment not found", 404)
    # cross-entity state (priority 18)
    if agreement is not None and agreement["status"] != "ASSIGNED":
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, "Agreement not ASSIGNED", 409)
    if assignment is not None and assignment["status"] != "EXECUTED":
        raise ApiError(ERR_ASSIGNMENT_INVALID_STATE, "Assignment not EXECUTED", 409)
    check_unknown_fields(body, POLICY_FIELDS)
    said = as_string(require_field(body, "settlement_agreement_id"), "settlement_agreement_id")
    agreement = DB.settlement_agreements.get(said)
    if agreement is None:
        raise ApiError(ERR_NOT_FOUND, "SettlementAgreement not found", 404)
    qaid = as_string(require_field(body, "qualified_assignment_id"), "qualified_assignment_id")
    assignment = DB.qualified_assignments.get(qaid)
    if assignment is None:
        raise ApiError(ERR_NOT_FOUND, "QualifiedAssignment not found", 404)
    if agreement["status"] != "ASSIGNED":
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, "Agreement not ASSIGNED", 409)
    if assignment["status"] != "EXECUTED":
        raise ApiError(ERR_ASSIGNMENT_INVALID_STATE, "Assignment not EXECUTED", 409)
    pnum = as_string(require_field(body, "policy_number"), "policy_number")
    insurer = as_string(require_field(body, "insurer_name"), "insurer_name")
    premium = as_positive_int(require_field(body, "premium_cents"), "premium_cents")
    cdr = as_positive_int(require_field(body, "contract_discount_rate_bps"), "contract_discount_rate_bps")
    rider = as_enum(require_field(body, "commutation_rider"), "commutation_rider",
                    {"NONE", "DEATH_ONLY", "DEATH_AND_HARDSHIP"})
    cpe = opt_field(body, "certain_period_end_date")
    cpe_iso = None
    if cpe is not None:
        cpe_iso = as_date(cpe, "certain_period_end_date").isoformat()

    e = base_entity()
    e.update({
        "settlement_agreement_id": said,
        "qualified_assignment_id": qaid,
        "policy_number": pnum,
        "insurer_name": insurer,
        "premium_cents": premium,
        "contract_discount_rate_bps": cdr,
        "commutation_rider": rider,
        "certain_period_end_date": cpe_iso,
        "in_force_date": None,
        "status": "PENDING_ISSUE",
    })
    DB.annuity_policies[e["id"]] = e
    return success_object(policy_view(e), status=201)


@bp.route("/annuity/annuity-policies", methods=["GET"])
def list_policies():
    caller = get_caller()
    require_roles(caller, {"Any"})
    limit, offset = parse_pagination(request.args)
    items = list(DB.annuity_policies.values())
    said = request.args.get("settlement_agreement_id")
    if said is not None:
        items = [p for p in items if p["settlement_agreement_id"] == said]
    qaid = request.args.get("qualified_assignment_id")
    if qaid is not None:
        items = [p for p in items if p["qualified_assignment_id"] == qaid]
    st = request.args.get("status")
    if st is not None:
        items = [p for p in items if p["status"] == st]
    page, total = list_view(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/annuity/annuity-policies/<policyId>", methods=["GET"])
def get_policy(policyId):
    caller = get_caller()
    require_roles(caller, {"Any"})
    p = DB.annuity_policies.get(policyId)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, "AnnuityPolicy not found", 404)
    return success_object(policy_view(p))


@bp.route("/annuity/annuity-policies/<policyId>/mark-in-force", methods=["POST"])
def mark_in_force(policyId):
    caller = get_caller()
    require_roles(caller, {"CaseManager"})
    p = DB.annuity_policies.get(policyId)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, "AnnuityPolicy not found", 404)
    if p["status"] != "PENDING_ISSUE":
        raise ApiError(ERR_POLICY_INVALID_STATE, "Policy not PENDING_ISSUE", 409)
    agreement = DB.settlement_agreements.get(p["settlement_agreement_id"])
    if agreement is None:
        raise ApiError(ERR_NOT_FOUND, "SettlementAgreement not found", 404)
    if agreement["status"] != "ASSIGNED":
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, "Agreement not ASSIGNED", 409)
    body = get_json_body()
    check_unknown_fields(body, {"in_force_date"})
    ifd = as_date(require_field(body, "in_force_date"), "in_force_date")
    p["status"] = "IN_FORCE"
    p["in_force_date"] = ifd.isoformat()
    touch(p)
    # cascade: agreement ASSIGNED -> FUNDED
    agreement["status"] = "FUNDED"
    touch(agreement)
    return success_object(policy_view(p))


# ---------------------------------------------------------------------------
# PaymentSchedule
# ---------------------------------------------------------------------------

SCHEDULE_FIELDS = {"settlement_agreement_id", "effective_from_date", "escalation_anchor_date"}


def schedule_view(s):
    return pub(s)


@bp.route("/annuity/payment-schedules", methods=["POST"])
def create_schedule():
    caller = get_caller()
    require_roles(caller, {"CaseManager"})
    body = get_json_body()
    said = body.get("settlement_agreement_id")
    agreement = None
    if said is not None and isinstance(said, str):
        agreement = DB.settlement_agreements.get(said)
        if agreement is None:
            raise ApiError(ERR_NOT_FOUND, "SettlementAgreement not found", 404)
    # cross-entity state: agreement not in {DRAFT, CLOSED, COMMUTED}
    if agreement is not None and agreement["status"] in ("DRAFT", "CLOSED", "COMMUTED"):
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, "Agreement state does not allow schedule creation", 409)
    check_unknown_fields(body, SCHEDULE_FIELDS)
    said = as_string(require_field(body, "settlement_agreement_id"), "settlement_agreement_id")
    agreement = DB.settlement_agreements.get(said)
    if agreement is None:
        raise ApiError(ERR_NOT_FOUND, "SettlementAgreement not found", 404)
    if agreement["status"] in ("DRAFT", "CLOSED", "COMMUTED"):
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, "Agreement state does not allow schedule creation", 409)
    eff = as_date(require_field(body, "effective_from_date"), "effective_from_date")
    anchor = as_date(require_field(body, "escalation_anchor_date"), "escalation_anchor_date")

    e = base_entity()
    e.update({
        "settlement_agreement_id": said,
        "effective_from_date": eff.isoformat(),
        "escalation_anchor_date": anchor.isoformat(),
        "supersedes_schedule_id": None,
        "status": "DRAFT",
    })
    DB.payment_schedules[e["id"]] = e
    return success_object(schedule_view(e), status=201)


@bp.route("/annuity/payment-schedules", methods=["GET"])
def list_schedules():
    caller = get_caller()
    require_roles(caller, {"Any"})
    limit, offset = parse_pagination(request.args)
    items = list(DB.payment_schedules.values())
    said = request.args.get("settlement_agreement_id")
    if said is not None:
        items = [s for s in items if s["settlement_agreement_id"] == said]
    st = request.args.get("status")
    if st is not None:
        items = [s for s in items if s["status"] == st]
    sup = request.args.get("supersedes_schedule_id")
    if sup is not None:
        items = [s for s in items if s.get("supersedes_schedule_id") == sup]
    page, total = list_view(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/annuity/payment-schedules/<scheduleId>", methods=["GET"])
def get_schedule(scheduleId):
    caller = get_caller()
    require_roles(caller, {"Any"})
    s = DB.payment_schedules.get(scheduleId)
    if s is None:
        raise ApiError(ERR_NOT_FOUND, "PaymentSchedule not found", 404)
    return success_object(schedule_view(s))


@bp.route("/annuity/payment-schedules/<scheduleId>/activate", methods=["POST"])
def activate_schedule(scheduleId):
    caller = get_caller()
    require_roles(caller, {"CaseManager"})
    s = DB.payment_schedules.get(scheduleId)
    if s is None:
        raise ApiError(ERR_NOT_FOUND, "PaymentSchedule not found", 404)
    agreement = DB.settlement_agreements.get(s["settlement_agreement_id"])
    if agreement is None:
        raise ApiError(ERR_NOT_FOUND, "SettlementAgreement not found", 404)
    body = get_json_body()
    # OCC (priority 3.5) — after existence, before state/business
    expected = body.get("expected_settlement_agreement_version")
    if expected is not None and isinstance(expected, int) and not isinstance(expected, bool):
        if expected != agreement["version"]:
            raise ApiError(ERR_STALE_AGREEMENT_VERSION, "expected_settlement_agreement_version != agreement.version", 412)
    # state guards (priority 4)
    if s["status"] != "DRAFT":
        raise ApiError(ERR_SCHEDULE_INVALID_STATE, "Schedule not DRAFT", 409)
    has_payments = any(p["payment_schedule_id"] == s["id"] for p in DB.scheduled_payments.values())
    if not has_payments:
        raise ApiError(ERR_SCHEDULE_HAS_PAYMENTS, "Schedule has no payment rows", 409)
    if agreement["status"] not in ("FUNDED", "ACTIVE"):
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, "Agreement not FUNDED or ACTIVE", 409)
    # shape
    check_unknown_fields(body, {"expected_settlement_agreement_version"})
    expected = require_field(body, "expected_settlement_agreement_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(ERR_INVALID_REQUEST, "expected_settlement_agreement_version must be an integer", 400)
    if expected != agreement["version"]:
        raise ApiError(ERR_STALE_AGREEMENT_VERSION, "expected_settlement_agreement_version != agreement.version", 412)

    # supersede previously ACTIVE schedule
    prev = active_schedule_for(agreement["id"])
    if prev is not None:
        prev["status"] = "SUPERSEDED"
        touch(prev)
        s["supersedes_schedule_id"] = prev["id"]
        # cancel its {SCHEDULED, PAYABLE} payments
        for p in DB.scheduled_payments.values():
            if p["payment_schedule_id"] == prev["id"] and p["status"] in ("SCHEDULED", "PAYABLE"):
                p["status"] = "CANCELLED"
                p["cancel_reason"] = "SUPERSEDED"
                touch(p)
    s["status"] = "ACTIVE"
    touch(s)
    recompute_agreement_totals(agreement)  # bumps agreement version
    return success_object(schedule_view(s))


# ---------------------------------------------------------------------------
# ScheduledPayment
# ---------------------------------------------------------------------------

PAYMENT_FIELDS = {
    "payment_schedule_id", "payee_id", "payment_seq_no", "due_date",
    "base_amount_cents", "escalation_rate_bps", "payment_type",
}


def payment_view(p):
    return pub(p)


@bp.route("/annuity/scheduled-payments", methods=["POST"])
def create_payment():
    caller = get_caller()
    require_roles(caller, {"CaseManager"})
    body = get_json_body()
    psid = body.get("payment_schedule_id")
    sched = None
    if psid is not None and isinstance(psid, str):
        sched = DB.payment_schedules.get(psid)
        if sched is None:
            raise ApiError(ERR_NOT_FOUND, "PaymentSchedule not found", 404)
    pid = body.get("payee_id")
    if pid is not None and isinstance(pid, str) and pid not in DB.payees:
        raise ApiError(ERR_NOT_FOUND, "Payee not found", 404)
    # state: schedule must be DRAFT
    if sched is not None and sched["status"] != "DRAFT":
        raise ApiError(ERR_SCHEDULE_INVALID_STATE, "Schedule not DRAFT", 409)
    check_unknown_fields(body, PAYMENT_FIELDS)
    psid = as_string(require_field(body, "payment_schedule_id"), "payment_schedule_id")
    sched = DB.payment_schedules.get(psid)
    if sched is None:
        raise ApiError(ERR_NOT_FOUND, "PaymentSchedule not found", 404)
    if sched["status"] != "DRAFT":
        raise ApiError(ERR_SCHEDULE_INVALID_STATE, "Schedule not DRAFT", 409)
    pid = as_string(require_field(body, "payee_id"), "payee_id")
    if pid not in DB.payees:
        raise ApiError(ERR_NOT_FOUND, "Payee not found", 404)
    seq = as_int(require_field(body, "payment_seq_no"), "payment_seq_no")
    if seq < 1:
        raise ApiError(ERR_INVALID_REQUEST, "payment_seq_no must be >= 1", 400)
    due = as_date(require_field(body, "due_date"), "due_date")
    eff = parse_date(sched["effective_from_date"])
    if due < eff:
        raise ApiError(ERR_INVALID_REQUEST, "due_date must be >= schedule effective_from_date", 400)
    base_amt = as_positive_int(require_field(body, "base_amount_cents"), "base_amount_cents")
    esc = opt_field(body, "escalation_rate_bps", 0)
    esc = as_nonnegative_int(esc, "escalation_rate_bps")
    ptype = as_enum(opt_field(body, "payment_type", "PERIODIC"), "payment_type", {"PERIODIC", "LUMP_SUM"})

    n = escalation_exponent(sched["escalation_anchor_date"], due.isoformat())
    amount, disclosure = escalated_amounts(base_amt, esc, n)

    e = base_entity()
    e.update({
        "payment_schedule_id": psid,
        "payee_id": pid,
        "payment_seq_no": seq,
        "due_date": due.isoformat(),
        "base_amount_cents": base_amt,
        "escalation_rate_bps": esc,
        "payment_type": ptype,
        "amount_cents": amount,
        "disclosure_amount_cents": disclosure,
        "status": "SCHEDULED",
        "issue_count": 0,
        "last_issue_method": None,
        "last_issued_at": None,
        "payee_name_on_check": None,
        "return_reason": None,
        "escheated_in_batch_id": None,
        "transferred_by_petition_id": None,
        "commuted_by_request_id": None,
        "cancel_reason": None,
    })
    DB.scheduled_payments[e["id"]] = e
    return success_object(payment_view(e), status=201)


@bp.route("/annuity/scheduled-payments", methods=["GET"])
def list_payments():
    caller = get_caller()
    require_roles(caller, {"Any"})
    limit, offset = parse_pagination(request.args)
    items = list(DB.scheduled_payments.values())
    f = request.args.get("payment_schedule_id")
    if f is not None:
        items = [p for p in items if p["payment_schedule_id"] == f]
    f = request.args.get("payee_id")
    if f is not None:
        items = [p for p in items if p["payee_id"] == f]
    f = request.args.get("status")
    if f is not None:
        items = [p for p in items if p["status"] == f]
    f = request.args.get("escheated_in_batch_id")
    if f is not None:
        items = [p for p in items if p.get("escheated_in_batch_id") == f]
    f = request.args.get("transferred_by_petition_id")
    if f is not None:
        items = [p for p in items if p.get("transferred_by_petition_id") == f]
    f = request.args.get("commuted_by_request_id")
    if f is not None:
        items = [p for p in items if p.get("commuted_by_request_id") == f]
    page, total = list_view(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/annuity/scheduled-payments/<paymentId>", methods=["GET"])
def get_payment(paymentId):
    caller = get_caller()
    require_roles(caller, {"Any"})
    p = DB.scheduled_payments.get(paymentId)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, "ScheduledPayment not found", 404)
    return success_object(payment_view(p))
