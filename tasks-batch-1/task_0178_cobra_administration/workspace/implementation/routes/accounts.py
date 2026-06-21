"""Premium-account endpoints: get/list, invoice creation, payment posting,
refund (OCC-guarded). Plus invoice/payment get+list."""
from flask import Blueprint, request, g

from db import store
from errors import ApiError
from middleware import require_role
from models import (
    _common, serialize, touch, ACCOUNT_FIELDS, INVOICE_FIELDS, PAYMENT_FIELDS,
)
from response import object_response, array_response
from timeutil import parse_year_month, year_month_index
from services import lifecycle
from services.ledger import (
    gross_premium_cents, amount_due_cents, coverage_month_index,
    recompute_invoice_subsidy, recompute_account, invoice_for_month,
    month_satisfied, posted_paid_for_month, shortfall_allowance,
)
from services.lookup import (
    get_or_404, require_body, require_enum, require_positive_int,
    require_coverage_month, require_int, paginate, sorted_by_creation,
)

bp = Blueprint("accounts", __name__)


# ---------------------------------------------------------------------------
# Account get/list
# ---------------------------------------------------------------------------
@bp.get("/accounts/<aid>")
@require_role({"PlanAdministrator", "BillingAgent", "QualifiedBeneficiary"})
def get_account(aid):
    acc = get_or_404(store.accounts, aid)
    return object_response(serialize(acc, ACCOUNT_FIELDS))


@bp.get("/accounts")
@require_role({"PlanAdministrator", "BillingAgent"})
def list_accounts():
    enrollment_id = request.args.get("enrollment_id")
    beneficiary_id = request.args.get("beneficiary_id")
    items = list(store.accounts.values())
    if enrollment_id is not None:
        items = [a for a in items if a["enrollment_id"] == enrollment_id]
    if beneficiary_id is not None:
        items = [a for a in items if a["beneficiary_id"] == beneficiary_id]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(request.args, items)
    return array_response([serialize(a, ACCOUNT_FIELDS) for a in page],
                          limit, offset, total)


def _enrollment_for_account(account):
    return store.enrollments.get(account["enrollment_id"])


def _plan_for_account(account):
    enr = _enrollment_for_account(account)
    if enr is None:
        return None
    ben = store.beneficiaries.get(enr["beneficiary_id"])
    if ben is None:
        return None
    return store.plans.get(ben["plan_id"])


# ---------------------------------------------------------------------------
# Invoice creation (PRD §3.5)
# ---------------------------------------------------------------------------
@bp.post("/accounts/<aid>/invoices")
@require_role({"BillingAgent", "PlanAdministrator"})
def create_invoice(aid):
    account = get_or_404(store.accounts, aid)
    body = require_body()
    coverage_month = require_coverage_month(body, "coverage_month")
    proration_mode = require_enum(body, "proration_mode",
                                  {"FULL_MONTH", "DAILY_PRORATED"},
                                  required=False)
    if proration_mode is None:
        proration_mode = "FULL_MONTH"

    enrollment = _enrollment_for_account(account)
    plan = _plan_for_account(account)

    y, m = parse_year_month(coverage_month)
    idx = coverage_month_index(enrollment, y, m)

    # Coverage interval check (priority 12): [coverage_start month, scheduled_end
    # month]. Daily proration only allowed for month 1.
    cs = enrollment["coverage_start_date"]
    se = enrollment["scheduled_end_date"]
    lo = year_month_index(cs.year, cs.month)
    hi = year_month_index(se.year, se.month)
    if not (lo <= year_month_index(y, m) <= hi):
        raise ApiError("ERR_INVALID_COVERAGE_MONTH",
                       "coverage_month outside the enrollment coverage interval")
    if proration_mode == "DAILY_PRORATED" and idx != 1:
        raise ApiError("ERR_INVALID_COVERAGE_MONTH",
                       "Only the first coverage month may be DAILY_PRORATED")

    # Duplicate invoice (priority 13): an account holds only one non-VOID? The
    # PRD says "only one invoice per coverage month". Treat any existing
    # non-VOID invoice for the month as a duplicate.
    for inv in store.invoices.values():
        if inv["account_id"] == account["id"] \
                and inv["coverage_month"] == coverage_month \
                and inv["status"] != "VOID":
            raise ApiError("ERR_DUPLICATE_INVOICE",
                           "An invoice already exists for this coverage_month")

    gross = gross_premium_cents(plan, enrollment, idx)
    due = amount_due_cents(gross, proration_mode, cs)

    invoice = {
        "account_id": account["id"],
        "coverage_month": coverage_month,
        "coverage_month_index": idx,
        "gross_premium_cents": gross,
        "proration_mode": proration_mode,
        "amount_due_cents": due,
        "subsidy_applied_cents": 0,
        "beneficiary_owed_cents": due,
        "status": "OPEN",
    }
    _common(invoice)
    store.invoices[invoice["id"]] = invoice

    # Apply subsidy (chronological first-match) then recompute account.
    recompute_invoice_subsidy(enrollment, invoice)
    recompute_account(account, enrollment)
    return object_response(serialize(invoice, INVOICE_FIELDS), status=201)


@bp.get("/invoices/<iid>")
@require_role({"PlanAdministrator", "BillingAgent", "QualifiedBeneficiary"})
def get_invoice(iid):
    inv = get_or_404(store.invoices, iid)
    return object_response(serialize(inv, INVOICE_FIELDS))


@bp.get("/invoices")
@require_role({"PlanAdministrator", "BillingAgent", "QualifiedBeneficiary"})
def list_invoices():
    account_id = request.args.get("account_id")
    items = list(store.invoices.values())
    if account_id is not None:
        items = [i for i in items if i["account_id"] == account_id]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(request.args, items)
    return array_response([serialize(i, INVOICE_FIELDS) for i in page],
                          limit, offset, total)


# ---------------------------------------------------------------------------
# Payment posting (PRD §3.6)
# ---------------------------------------------------------------------------
@bp.post("/accounts/<aid>/payments")
@require_role({"BillingAgent", "QualifiedBeneficiary"})
def post_payment(aid):
    account = get_or_404(store.accounts, aid)
    # Ownership (priority 4): QB may pay only on its own account.
    if g.role == "QualifiedBeneficiary" and account["beneficiary_id"] != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Caller does not own the targeted account")

    body = require_body()
    amount = require_positive_int(body, "amount_cents")
    target_month = require_coverage_month(body, "target_coverage_month")

    enrollment = _enrollment_for_account(account)
    plan = _plan_for_account(account)

    # State (priority 6): enrollment must be PENDING_INITIAL_PREMIUM or ACTIVE.
    if enrollment["status"] not in ("PENDING_INITIAL_PREMIUM", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE",
                       "Enrollment does not accept payments in its current state")

    # OPEN invoice for the target month must exist (priority 14).
    inv = invoice_for_month(account["id"], target_month)
    if inv is None or inv["status"] != "OPEN":
        raise ApiError("ERR_NO_OPEN_INVOICE",
                       "No OPEN invoice for the target coverage month")

    now = store.now()
    # deemed_full_payment: shortfall after THIS payment's already-paid total
    # (including this payment) <= allowance. PRD §3.6: sum POSTED payments for
    # the month, take shortfall = beneficiary_owed - already_paid.
    payment = {
        "account_id": account["id"],
        "amount_cents": amount,
        "received_date": now,
        "target_coverage_month": target_month,
        "deemed_full_payment": False,
        "status": "POSTED",
    }
    _common(payment)
    store.payments[payment["id"]] = payment

    # Now compute deemed_full_payment over all POSTED payments for the month
    # (this payment is now included). Per SCAFFOLD deemed_full_payment formula:
    # shortfall = beneficiary_owed - sum(POSTED payment amounts); subsidy is
    # already netted out of beneficiary_owed, so it is NOT subtracted again.
    already_paid = posted_paid_for_month(account["id"], target_month)
    allowance = shortfall_allowance(plan, inv["beneficiary_owed_cents"])
    shortfall = inv["beneficiary_owed_cents"] - already_paid
    if shortfall <= allowance:
        payment["deemed_full_payment"] = True
        # Note: created above; no version bump needed (still v1).

    # If invoice now fully satisfied or deemed full: mark PAID.
    if month_satisfied(account["id"], inv):
        if inv["status"] == "OPEN":
            inv["status"] = "PAID"
            touch(inv)

    # Recompute ledger (amount_paid, credit_balance, paid_through_date).
    recompute_account(account, enrollment)

    # Vesting: PENDING_INITIAL_PREMIUM month-1 satisfied within grace -> ACTIVE.
    lifecycle.maybe_vest_enrollment(enrollment, account)

    return object_response(serialize(payment, PAYMENT_FIELDS), status=201)


@bp.get("/payments/<pid>")
@require_role({"PlanAdministrator", "BillingAgent", "QualifiedBeneficiary"})
def get_payment(pid):
    p = get_or_404(store.payments, pid)
    return object_response(serialize(p, PAYMENT_FIELDS))


@bp.get("/payments")
@require_role({"PlanAdministrator", "BillingAgent", "QualifiedBeneficiary"})
def list_payments():
    account_id = request.args.get("account_id")
    items = list(store.payments.values())
    if account_id is not None:
        items = [p for p in items if p["account_id"] == account_id]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(request.args, items)
    return array_response([serialize(p, PAYMENT_FIELDS) for p in page],
                          limit, offset, total)


# ---------------------------------------------------------------------------
# Refund (PRD §3.11 + §2.8 OCC)
# ---------------------------------------------------------------------------
@bp.post("/accounts/<aid>/refund")
@require_role({"BillingAgent"})
def refund(aid):
    account = get_or_404(store.accounts, aid)
    body = require_body()
    refund_amount = require_positive_int(body, "refund_amount_cents")
    expected_version = require_int(body, "expected_account_version")

    # Validation order: PRD §3.11 prose lists the positive-balance gate first,
    # then the exceeds check; the state-machine preconditions agree (no-credit
    # before exceeds). PRD prose is authoritative, so we check NO_CREDIT_BALANCE
    # first, then REFUND_EXCEEDS_CREDIT, then the OCC stale-version gate (last).
    if account["credit_balance_cents"] <= 0:
        raise ApiError("ERR_NO_CREDIT_BALANCE",
                       "Refund requires a positive credit balance")
    if refund_amount > account["credit_balance_cents"]:
        raise ApiError("ERR_REFUND_EXCEEDS_CREDIT",
                       "Refund amount exceeds the account credit balance")
    if expected_version != account["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_account_version does not match the current version")

    account["amount_refunded_cents"] = account.get("amount_refunded_cents", 0) + refund_amount
    enrollment = _enrollment_for_account(account)
    # Recompute credit balance from conservation identity, then bump version.
    recompute_account(account, enrollment, bump=False)
    touch(account)
    return object_response(serialize(account, ACCOUNT_FIELDS))
