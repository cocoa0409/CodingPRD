"""Withdrawal endpoints: create, disburse, reject, expenses, classify, get, list."""

from flask import Blueprint, g, request
from core.auth import require_roles
from core.envelope import success_object, success_array
from core.errors import raise_error
from core.store import STORE, lock
from core.clock import CLOCK
from core.validation import (
    require_body, require_field, require_enum, require_full_name, parse_pagination,
)
from core.models import (
    withdrawal_create, withdrawal_view, expense_create, expense_view, touch,
)
from services.calculations import (
    withdrawal_basis_earnings_split, k12_cap_application, non_qualified_penalty,
    K12_ANNUAL_CAP_CENTS,
)
from services.calendar import ensure_beneficiary_year, year_from_iso


bp = Blueprint("withdrawals", __name__)


EXPENSE_CATEGORIES = {
    "POST_SECONDARY_TUITION", "ROOM_AND_BOARD", "BOOKS_SUPPLIES",
    "K_12", "NON_QUALIFIED",
}
REJECTED_REASONS = {
    "INSUFFICIENT_BALANCE", "ACCOUNT_RESTRICTED", "K12_CAP_WOULD_EXCEED",
    "EXPENSE_RECEIPT_MISSING",
}


def _check_donor_owns_account(account):
    if g.user_role == "Donor" and account["primary_donor_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "Donor does not own this account")


def _check_donor_can_read_account(account):
    if g.user_role == "Donor" and account["primary_donor_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "Donor does not own this account")
    if g.user_role == "Beneficiary" and account["beneficiary_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "Beneficiary may only read accounts they benefit from")


def _tax_year_locked_for(account_id: str, year: int) -> bool:
    for tr in STORE.tax_reports.values():
        if tr["account_id"] == account_id and tr["tax_year"] == year and tr["locked"]:
            return True
    return False


@bp.post("/accounts/<aid>/withdrawals")
@require_roles("Donor")
def create_withdrawal(aid):
    body = require_body(request)
    requested = require_field(body, "requested_amount_cents", kind="positive_int")
    category = require_enum(body, "expense_category", EXPENSE_CATEGORIES)

    with lock():
        a = STORE.accounts.get(aid)
        if not a:
            raise_error("ERR_NOT_FOUND", f"Account {aid} not found")
        _check_donor_owns_account(a)
        # Priority 6 — Account state.
        if a["status"] != "OPEN":
            raise_error("ERR_ACCOUNT_RESTRICTED",
                        f"Account is {a['status']}; cannot create withdrawal")
        # Priority 8 — locked tax report for the CURRENT calendar year.
        current_year = year_from_iso(CLOCK.now_iso())
        if _tax_year_locked_for(aid, current_year):
            raise_error("ERR_TAX_REPORT_LOCKED",
                        f"TaxReport for {aid} year {current_year} is locked")
        # Priority 16 — K-12 cap pre-check. Per PRD §3.5: "rejected with
        # ERR_K12_CAP_EXCEEDED if the beneficiary has zero cap room
        # remaining for the current calendar year AND the request would
        # push them into negative cap room. A request that lands exactly
        # on the remaining cap room (so cap room equals requested) is
        # allowed." So we reject ONLY when cap_room == 0 AND requested > 0.
        # When cap_room > 0 but requested > cap_room, the withdrawal is
        # allowed; at classify time the qualified amount is capped at
        # cap_room and the surplus becomes non_qualified.
        if category == "K_12":
            ben = STORE.beneficiaries.get(a["beneficiary_id"])
            if ben:
                ensure_beneficiary_year(ben, current_year)
                cap_room = K12_ANNUAL_CAP_CENTS - ben["k12_ytd_qualified_cents"]
                if cap_room < 0:
                    cap_room = 0
                if cap_room == 0 and requested > 0:
                    raise_error("ERR_K12_CAP_EXCEEDED",
                                "K-12 cap is zero; request would push into negative cap room")
        # Priority 17 — Insufficient balance.
        if requested > a["total_balance_cents"]:
            raise_error("ERR_INSUFFICIENT_BALANCE",
                        "Requested amount exceeds account balance")
        w = withdrawal_create(aid, requested, category)
    return success_object(withdrawal_view(w), 201)


@bp.post("/withdrawals/<wid>/disburse")
@require_roles("Donor")
def disburse_withdrawal(wid):
    with lock():
        w = STORE.withdrawals.get(wid)
        if not w:
            raise_error("ERR_NOT_FOUND", f"Withdrawal {wid} not found")
        a = STORE.accounts.get(w["account_id"])
        if not a:
            raise_error("ERR_NOT_FOUND", "Account missing for this withdrawal")
        _check_donor_owns_account(a)
        # Priority 6 — account state.
        if a["status"] != "OPEN":
            raise_error("ERR_ACCOUNT_RESTRICTED",
                        f"Account is {a['status']}; cannot disburse")
        # Priority 7 — invalid state.
        if w["status"] != "REQUESTED":
            raise_error("ERR_INVALID_STATE",
                        f"Withdrawal is {w['status']}; only REQUESTED may disburse")
        # Priority 8 — locked tax report for the current year.
        now_iso = CLOCK.now_iso()
        current_year = year_from_iso(now_iso)
        if _tax_year_locked_for(a["id"], current_year):
            raise_error("ERR_TAX_REPORT_LOCKED",
                        f"TaxReport for {a['id']} year {current_year} is locked")
        # Priority 17 — insufficient balance, re-checked at disburse.
        if w["requested_amount_cents"] > a["total_balance_cents"]:
            raise_error("ERR_INSUFFICIENT_BALANCE",
                        "Requested amount exceeds account balance at disburse")

        basis_p, earn_p = withdrawal_basis_earnings_split(
            a["total_balance_cents"], a["earnings_balance_cents"],
            w["requested_amount_cents"],
        )
        w["basis_portion_cents"] = basis_p
        w["earnings_portion_cents"] = earn_p

        a["basis_balance_cents"] -= basis_p
        a["earnings_balance_cents"] -= earn_p
        a["total_balance_cents"] -= w["requested_amount_cents"]
        touch(a)

        w["status"] = "DISBURSED"
        w["_disbursed_at"] = now_iso
        touch(w)
    return success_object(withdrawal_view(w))


@bp.post("/withdrawals/<wid>/reject")
@require_roles("PlanAdministrator")
def reject_withdrawal(wid):
    body = require_body(request)
    reason = require_enum(body, "rejected_reason", REJECTED_REASONS)
    with lock():
        w = STORE.withdrawals.get(wid)
        if not w:
            raise_error("ERR_NOT_FOUND", f"Withdrawal {wid} not found")
        if w["status"] != "REQUESTED":
            raise_error("ERR_INVALID_STATE",
                        f"Withdrawal is {w['status']}; only REQUESTED may be rejected")
        w["status"] = "REJECTED"
        w["rejected_reason"] = reason
        touch(w)
    return success_object(withdrawal_view(w))


@bp.post("/withdrawals/<wid>/expenses")
@require_roles("Donor")
def attach_expense(wid):
    body = require_body(request)
    institution_name = require_full_name(body, "institution_name")
    category = require_enum(body, "category", EXPENSE_CATEGORIES)
    amount_cents = require_field(body, "amount_cents", kind="positive_int")
    incurred_on = require_field(body, "incurred_on", kind="string")

    with lock():
        w = STORE.withdrawals.get(wid)
        if not w:
            raise_error("ERR_NOT_FOUND", f"Withdrawal {wid} not found")
        a = STORE.accounts.get(w["account_id"])
        if not a:
            raise_error("ERR_NOT_FOUND", "Account missing for this withdrawal")
        _check_donor_owns_account(a)
        # Expenses are attachable only after DISBURSED.
        if w["status"] != "DISBURSED":
            raise_error("ERR_INVALID_STATE",
                        f"Withdrawal is {w['status']}; expenses attachable only on DISBURSED")
        # Priority 10 — temporal: incurred_on must be in same calendar year as disbursement.
        d_year = year_from_iso(w["_disbursed_at"]) if w.get("_disbursed_at") else None
        if d_year is not None:
            try:
                exp_year = int(incurred_on[:4])
            except (ValueError, TypeError):
                raise_error("ERR_VALIDATION_FAILED", "incurred_on must be a valid ISO date")
            if exp_year != d_year:
                raise_error("ERR_EXPENSE_OUT_OF_YEAR",
                            f"incurred_on year {exp_year} != disbursement year {d_year}")
        exp = expense_create(wid, institution_name, category, amount_cents, incurred_on)
    return success_object(expense_view(exp), 201)


@bp.post("/withdrawals/<wid>/classify")
@require_roles("Donor")
def classify_withdrawal(wid):
    with lock():
        w = STORE.withdrawals.get(wid)
        if not w:
            raise_error("ERR_NOT_FOUND", f"Withdrawal {wid} not found")
        a = STORE.accounts.get(w["account_id"])
        if not a:
            raise_error("ERR_NOT_FOUND", "Account missing for this withdrawal")
        _check_donor_owns_account(a)
        # Priority 7 — invalid state precedes other business checks.
        if w["status"] != "DISBURSED":
            raise_error("ERR_INVALID_STATE",
                        f"Withdrawal is {w['status']}; only DISBURSED may classify")
        # Priority 8 — locked tax report for the disbursement year blocks classify.
        d_year = year_from_iso(w["_disbursed_at"])
        if _tax_year_locked_for(a["id"], d_year):
            raise_error("ERR_TAX_REPORT_LOCKED",
                        f"TaxReport for {a['id']} year {d_year} is locked")
        # Priority 9 — category mismatch on any receipt is rejected before any cap math.
        receipts = [
            e for e in STORE.education_expenses.values() if e["withdrawal_id"] == wid
        ]
        for e in receipts:
            if e["category"] != w["expense_category"]:
                raise_error("ERR_EXPENSE_CATEGORY_MISMATCH",
                            "Receipt category does not match withdrawal expense_category")
        receipts_total = sum(
            e["amount_cents"] for e in receipts if e["category"] == w["expense_category"]
        )
        # PRD §3.5: when expense_category != NON_QUALIFIED, receipts_total > 0 else missing
        # substantiation -> ERR_INVALID_STATE.
        if w["expense_category"] != "NON_QUALIFIED" and receipts_total <= 0:
            raise_error("ERR_INVALID_STATE",
                        "Missing substantiating expense receipts for classification")

        # Beneficiary YTD bookkeeping is tied to the DISBURSEMENT year.
        ben = STORE.beneficiaries.get(a["beneficiary_id"])
        if not ben:
            raise_error("ERR_NOT_FOUND", "Beneficiary missing for this account")
        ensure_beneficiary_year(ben, d_year)

        qualified, non_qualified = k12_cap_application(
            w, receipts_total, ben["k12_ytd_qualified_cents"]
        )
        w["qualified_amount_cents"] = qualified
        w["non_qualified_amount_cents"] = non_qualified

        penalty = non_qualified_penalty(
            w["earnings_portion_cents"], non_qualified, w["requested_amount_cents"]
        )
        w["penalty_cents"] = penalty

        # Beneficiary k12_ytd_qualified_cents increases by qualified amount when K_12.
        if w["expense_category"] == "K_12":
            ben["k12_ytd_qualified_cents"] += qualified
            touch(ben)

        w["status"] = "CLASSIFIED"
        touch(w)
    return success_object(withdrawal_view(w))


@bp.get("/withdrawals/<wid>")
@require_roles("PlanAdministrator", "Donor", "Beneficiary")
def get_withdrawal(wid):
    w = STORE.withdrawals.get(wid)
    if not w:
        raise_error("ERR_NOT_FOUND", f"Withdrawal {wid} not found")
    if g.user_role == "Donor":
        a = STORE.accounts.get(w["account_id"])
        if not a or a["primary_donor_id"] != g.user_id:
            raise_error("ERR_FORBIDDEN", "Donor may only read withdrawals on their accounts")
    elif g.user_role == "Beneficiary":
        a = STORE.accounts.get(w["account_id"])
        if not a or a["beneficiary_id"] != g.user_id:
            raise_error("ERR_FORBIDDEN", "Beneficiary may only read withdrawals on accounts they benefit from")
    return success_object(withdrawal_view(w))


@bp.get("/accounts/<aid>/withdrawals")
@require_roles("PlanAdministrator", "Donor", "Beneficiary")
def list_withdrawals(aid):
    a = STORE.accounts.get(aid)
    if not a:
        raise_error("ERR_NOT_FOUND", f"Account {aid} not found")
    _check_donor_can_read_account(a)
    limit, offset = parse_pagination(request)
    status = request.args.get("status")
    category = request.args.get("expense_category")
    rows = [w for w in STORE.withdrawals.values() if w["account_id"] == aid]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if category is not None:
        rows = [r for r in rows if r["expense_category"] == category]
    rows.sort(key=lambda r: (r["_created_seq"], r["id"]))
    total = len(rows)
    page = [withdrawal_view(r) for r in rows[offset:offset + limit]]
    return success_array(page, limit, offset, total)
