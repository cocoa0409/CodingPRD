"""Routes: payment lifecycle actions (issue / mark-cleared / report-returned /
reclaim-escheat) and returned-payment cases."""

from flask import Blueprint, request

from db import DB, CLOCK, base_entity, touch, clock_date_iso, parse_date, add_years
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_PAYMENT_NOT_PAYABLE,
    ERR_PAYMENT_NOT_ISSUED,
    ERR_PAYMENT_NOT_RETURNED,
    ERR_PAYMENT_NOT_ESCHEATED,
    ERR_CASE_INVALID_STATE,
    ERR_GUARDIANSHIP_REQUIRED,
    ERR_SOD_VIOLATION,
    ERR_DORMANCY_NOT_MET,
    ERR_NO_OPEN_ESCHEAT_BATCH,
    ERR_AGREEMENT_INVALID_STATE,
    ERR_INVALID_REQUEST,
)
from middleware import (
    get_caller, require_roles, get_json_body, check_unknown_fields,
    require_field, as_enum, parse_pagination,
)
from response import success_object, success_list
from services import (
    pub, list_view, compute_is_minor, active_guardianship,
    recompute_agreement_totals, exhaustion_check, find_profile_by_state,
)

bp = Blueprint("payments", __name__)


def payment_view(p):
    return pub(p)


def case_view(c):
    return pub(c)


def _agreement_for_payment(payment):
    sched = DB.payment_schedules.get(payment["payment_schedule_id"])
    if sched is None:
        return None
    return DB.settlement_agreements.get(sched["settlement_agreement_id"])


# ---------------------------------------------------------------------------
# Issue
# ---------------------------------------------------------------------------

@bp.route("/annuity/scheduled-payments/<paymentId>/issue", methods=["POST"])
def issue_payment(paymentId):
    caller = get_caller()
    require_roles(caller, {"OperationsSpecialist"})
    p = DB.scheduled_payments.get(paymentId)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, "ScheduledPayment not found", 404)
    if p["status"] != "PAYABLE":
        raise ApiError(ERR_PAYMENT_NOT_PAYABLE, "Payment not PAYABLE", 409)
    # guardianship gate for minors (priority 5)
    payee = DB.payees.get(p["payee_id"])
    if payee is None:
        raise ApiError(ERR_NOT_FOUND, "Payee not found", 404)
    is_minor = compute_is_minor(payee)
    guard = active_guardianship(payee["id"])
    if is_minor and guard is None:
        raise ApiError(ERR_GUARDIANSHIP_REQUIRED, "Minor payee requires an ACTIVE GuardianshipCase", 403)
    body = get_json_body()
    check_unknown_fields(body, {"method"})
    method = as_enum(require_field(body, "method"), "method", {"CHECK", "EFT"})

    p["status"] = "ISSUED"
    p["issue_count"] += 1
    p["last_issue_method"] = method
    p["last_issued_at"] = clock_date_iso()
    p["payee_name_on_check"] = guard["guardian_full_name"] if (is_minor and guard) else payee["full_name"]
    p["return_reason"] = None
    touch(p)
    return success_object(payment_view(p))


# ---------------------------------------------------------------------------
# Mark cleared
# ---------------------------------------------------------------------------

@bp.route("/annuity/scheduled-payments/<paymentId>/mark-cleared", methods=["POST"])
def mark_cleared(paymentId):
    caller = get_caller()
    require_roles(caller, {"OperationsSpecialist"})
    p = DB.scheduled_payments.get(paymentId)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, "ScheduledPayment not found", 404)
    if p["status"] != "ISSUED":
        raise ApiError(ERR_PAYMENT_NOT_ISSUED, "Payment not ISSUED", 409)
    get_json_body()
    p["status"] = "CLEARED"
    touch(p)
    agreement = _agreement_for_payment(p)
    if agreement is not None:
        agreement["paid_total_cents"] += p["amount_cents"]
        recompute_agreement_totals(agreement)  # bumps version
        exhaustion_check(agreement)
    return success_object(payment_view(p))


# ---------------------------------------------------------------------------
# Report returned
# ---------------------------------------------------------------------------

@bp.route("/annuity/scheduled-payments/<paymentId>/report-returned", methods=["POST"])
def report_returned(paymentId):
    caller = get_caller()
    require_roles(caller, {"OperationsSpecialist"})
    p = DB.scheduled_payments.get(paymentId)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, "ScheduledPayment not found", 404)
    if p["status"] != "ISSUED":
        raise ApiError(ERR_PAYMENT_NOT_ISSUED, "Payment not ISSUED", 409)
    body = get_json_body()
    check_unknown_fields(body, {"return_reason"})
    reason = as_enum(require_field(body, "return_reason"), "return_reason",
                     {"BAD_ADDRESS", "EFT_REJECTED", "UNCASHED_STALE"})
    p["status"] = "RETURNED"
    p["return_reason"] = reason
    touch(p)
    agreement = _agreement_for_payment(p)
    if agreement is not None:
        recompute_agreement_totals(agreement)
    # auto-open a ReturnedPaymentCase
    c = base_entity()
    c.update({
        "scheduled_payment_id": p["id"],
        "return_reason": reason,
        "opened_by_user_id": caller.user_id,
        "status": "OPEN",
        "resolution_note": None,
    })
    DB.returned_payment_cases[c["id"]] = c
    return success_object(payment_view(p))


# ---------------------------------------------------------------------------
# Reclaim escheat
# ---------------------------------------------------------------------------

@bp.route("/annuity/scheduled-payments/<paymentId>/reclaim-escheat", methods=["POST"])
def reclaim_escheat(paymentId):
    caller = get_caller()
    require_roles(caller, {"OperationsSpecialist"})
    p = DB.scheduled_payments.get(paymentId)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, "ScheduledPayment not found", 404)
    if p["status"] != "ESCHEATED":
        raise ApiError(ERR_PAYMENT_NOT_ESCHEATED, "Payment not ESCHEATED", 409)
    payee = DB.payees.get(p["payee_id"])
    if payee is None:
        raise ApiError(ERR_NOT_FOUND, "Payee not found", 404)
    # business: OPEN batch for payee's state
    open_batch = None
    for b in DB.escheatment_batches.values():
        if b["state_code"] == payee["address_state_code"] and b["status"] == "OPEN":
            open_batch = b
            break
    agreement = _agreement_for_payment(p)
    # priority 17 (open batch) before priority 18 (cross-entity state)
    if open_batch is None:
        raise ApiError(ERR_NO_OPEN_ESCHEAT_BATCH, "No OPEN escheatment batch for the payee's state", 409)
    if agreement is not None and agreement["status"] in ("CLOSED", "COMMUTED"):
        raise ApiError(ERR_AGREEMENT_INVALID_STATE, "Agreement is CLOSED or COMMUTED", 409)
    get_json_body()

    p["status"] = "PAYABLE"
    p["escheated_in_batch_id"] = None
    p["return_reason"] = None
    touch(p)
    if agreement is not None:
        agreement["escheated_total_cents"] -= p["amount_cents"]
        recompute_agreement_totals(agreement)
    open_batch["reclaimed_count"] += 1
    open_batch["reclaimed_amount_cents"] += p["amount_cents"]
    touch(open_batch)
    return success_object(payment_view(p))


# ---------------------------------------------------------------------------
# ReturnedPaymentCase
# ---------------------------------------------------------------------------

@bp.route("/annuity/returned-payment-cases", methods=["GET"])
def list_cases():
    caller = get_caller()
    require_roles(caller, {"Any"})
    limit, offset = parse_pagination(request.args)
    items = list(DB.returned_payment_cases.values())
    spid = request.args.get("scheduled_payment_id")
    if spid is not None:
        items = [c for c in items if c["scheduled_payment_id"] == spid]
    st = request.args.get("status")
    if st is not None:
        items = [c for c in items if c["status"] == st]
    page, total = list_view(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/annuity/returned-payment-cases/<caseId>", methods=["GET"])
def get_case(caseId):
    caller = get_caller()
    require_roles(caller, {"Any"})
    c = DB.returned_payment_cases.get(caseId)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "ReturnedPaymentCase not found", 404)
    return success_object(case_view(c))


@bp.route("/annuity/returned-payment-cases/<caseId>/authorize-reissue", methods=["POST"])
def authorize_reissue(caseId):
    caller = get_caller()
    require_roles(caller, {"OperationsSpecialist"})
    c = DB.returned_payment_cases.get(caseId)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "ReturnedPaymentCase not found", 404)
    if c["status"] != "OPEN":
        raise ApiError(ERR_CASE_INVALID_STATE, "Case not OPEN", 409)
    p = DB.scheduled_payments.get(c["scheduled_payment_id"])
    if p is None:
        raise ApiError(ERR_NOT_FOUND, "ScheduledPayment not found", 404)
    if p["status"] != "RETURNED":
        raise ApiError(ERR_PAYMENT_NOT_RETURNED, "Payment not RETURNED", 409)
    if caller.user_id == c["opened_by_user_id"]:
        raise ApiError(ERR_SOD_VIOLATION, "Reissue authorizer must differ from case opener", 403)
    get_json_body()
    c["status"] = "RESOLVED_REISSUE"
    c["resolution_note"] = "REISSUE_AUTHORIZED"
    touch(c)
    p["status"] = "PAYABLE"
    touch(p)
    agreement = _agreement_for_payment(p)
    if agreement is not None:
        recompute_agreement_totals(agreement)
    return success_object(case_view(c))


@bp.route("/annuity/returned-payment-cases/<caseId>/escalate-escheat", methods=["POST"])
def escalate_escheat(caseId):
    caller = get_caller()
    require_roles(caller, {"ComplianceOfficer"})
    c = DB.returned_payment_cases.get(caseId)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, "ReturnedPaymentCase not found", 404)
    if c["status"] != "OPEN":
        raise ApiError(ERR_CASE_INVALID_STATE, "Case not OPEN", 409)
    p = DB.scheduled_payments.get(c["scheduled_payment_id"])
    if p is None:
        raise ApiError(ERR_NOT_FOUND, "ScheduledPayment not found", 404)
    # dormancy must already be met
    payee = DB.payees.get(p["payee_id"])
    if payee is None:
        raise ApiError(ERR_NOT_FOUND, "Payee not found", 404)
    profile = find_profile_by_state(payee["address_state_code"])
    if profile is None:
        raise ApiError(ERR_NOT_FOUND, "StateStatuteProfile not found", 404)
    dormancy_anniversary = add_years(parse_date(p["due_date"]), profile["dormancy_years"])
    if CLOCK.today() <= dormancy_anniversary:
        raise ApiError(ERR_DORMANCY_NOT_MET, "Dormancy period not yet met", 409)
    get_json_body()
    c["status"] = "ESCHEAT_PENDING"
    touch(c)
    if p["status"] in ("ISSUED", "STALE_DATED", "RETURNED"):
        p["status"] = "ESCHEATABLE"
        touch(p)
        agreement = _agreement_for_payment(p)
        if agreement is not None:
            recompute_agreement_totals(agreement)
    return success_object(case_view(c))
