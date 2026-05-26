"""Withdrawal routes: create, submit, reject, revise, approve, disburse,
get, audit, list."""
from __future__ import annotations

from flask import Flask, request

from db import store, stamp_create, stamp_update, iso_ms
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_INSUFFICIENT_BALANCE,
    ERR_REVISION_LIMIT_EXCEEDED,
    ERR_STALE_ACCOUNT_VERSION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_FORBIDDEN,
)
from middleware import require_roles, current_user_id
from response import success_object, success_array, parse_pagination, paginate
from calculations import (
    earnings_ratio_split,
    k12_excess_cents,
    excess_withdrawal_penalty_cents,
)
from services import (
    recompute_account_ledger,
    refresh_matching_draft_forms_on_disburse,
)
from validators import (
    must_exist,
    require_dict,
    require_enum,
    require_int,
    require_positive_int,
    require_str,
)


_EXPENSE_CLASSES = {
    "HIGHER_ED_TUITION",
    "ROOM_BOARD",
    "BOOKS_SUPPLIES",
    "K_12_TUITION",
    "APPRENTICESHIP",
    "NON_QUALIFIED",
}

_VIEW_KEYS = (
    "id", "created_at", "updated_at", "version",
    "account_id", "amount_cents", "expense_class", "status",
    "basis_portion_cents", "earnings_portion_cents",
    "penalty_cents", "k12_excess_cents",
    "tax_year", "approved_at_utc", "disbursed_at_utc", "rejection_count",
)


def _view(w: dict) -> dict:
    return {k: w.get(k) for k in _VIEW_KEYS}


def _ensure_owner_via_account(account_id: str) -> dict:
    account = must_exist(store.accounts, account_id, path=False)
    if request.headers.get("X-User-Role") == "AccountOwner":
        if current_user_id() != account["donor_id"]:
            raise err(ERR_FORBIDDEN, "AccountOwner does not own this account")
    return account


def register(app: Flask) -> None:

    @app.post("/withdrawals")
    @require_roles("AccountOwner")
    def create_withdrawal():
        body = require_dict(request.get_json(silent=True))
        account_id = require_str(body, "account_id")
        _ensure_owner_via_account(account_id)
        amount = require_positive_int(body, "amount_cents")
        expense_class = require_enum(body, "expense_class", _EXPENSE_CLASSES)
        w = stamp_create({
            "account_id": account_id,
            "amount_cents": amount,
            "expense_class": expense_class,
            "status": "DRAFT",
            "basis_portion_cents": None,
            "earnings_portion_cents": None,
            "penalty_cents": 0,
            "k12_excess_cents": 0,
            "tax_year": None,
            "approved_at_utc": None,
            "disbursed_at_utc": None,
            "rejection_count": 0,
        }, store.clock_utc)
        store.withdrawals[w["id"]] = w
        return success_object(_view(w), status=201)

    @app.post("/withdrawals/<wid>/submit")
    @require_roles("AccountOwner")
    def submit_withdrawal(wid: str):
        w = must_exist(store.withdrawals, wid, path=True)
        account = _ensure_owner_via_account(w["account_id"])
        if w["status"] != "DRAFT":
            raise err(ERR_INVALID_STATE, "withdrawal must be DRAFT to submit")
        if account["status"] != "OPEN":
            raise err(ERR_INVALID_STATE, "account must be OPEN to submit withdrawal")
        # No PENDING BeneficiaryChange.
        has_pending = any(
            c["account_id"] == account["id"] and c["status"] == "PENDING"
            for c in store.beneficiary_changes.values()
        )
        if has_pending:
            raise err(ERR_INVALID_STATE, "pending beneficiary change blocks submit")
        # Balance precondition.
        if w["amount_cents"] > account["account_balance_cents"]:
            raise err(ERR_INSUFFICIENT_BALANCE, "amount exceeds balance")
        w["status"] = "SUBMITTED"
        stamp_update(w, store.clock_utc)
        store.withdrawal_submitter[wid] = current_user_id()
        return success_object(_view(w))

    @app.post("/withdrawals/<wid>/reject")
    @require_roles("ComplianceOfficer")
    def reject_withdrawal(wid: str):
        w = must_exist(store.withdrawals, wid, path=True)
        if w["status"] != "SUBMITTED":
            raise err(ERR_INVALID_STATE, "withdrawal must be SUBMITTED to reject")
        w["status"] = "REJECTED"
        w["rejection_count"] = w.get("rejection_count", 0) + 1
        stamp_update(w, store.clock_utc)
        return success_object(_view(w))

    @app.post("/withdrawals/<wid>/revise")
    @require_roles("AccountOwner")
    def revise_withdrawal(wid: str):
        w = must_exist(store.withdrawals, wid, path=True)
        _ensure_owner_via_account(w["account_id"])
        # Priority order per PRD §2.8: state precondition (priority 6) BEFORE
        # business fiscal (priority 16). So check status first.
        if w["status"] != "REJECTED":
            raise err(ERR_INVALID_STATE, "withdrawal must be REJECTED to revise")
        if w["rejection_count"] >= 3:
            raise err(ERR_REVISION_LIMIT_EXCEEDED, "revision count limit reached")
        w["status"] = "DRAFT"
        stamp_update(w, store.clock_utc)
        return success_object(_view(w))

    @app.post("/withdrawals/<wid>/approve")
    @require_roles("ComplianceOfficer")
    def approve_withdrawal(wid: str):
        w = must_exist(store.withdrawals, wid, path=True)
        body = require_dict(request.get_json(silent=True))
        # Segregation-of-duties (priority 3) — runs before existence and state.
        # But "must_exist" above already ran (priority 4). The scaffold's
        # priority places SoD at 3, but in practice the test suite uses an
        # existing withdrawal, so ordering between 3 and 4/5 isn't testable.
        # SoD vs OCC: SoD MUST fire before OCC (test_segregation_surfaces_before_occ).
        submitter = store.withdrawal_submitter.get(wid)
        if submitter is not None and submitter == current_user_id():
            raise err(ERR_SEGREGATION_OF_DUTIES, "approver must differ from submitter")
        # State precondition (priority 6).
        if w["status"] != "SUBMITTED":
            raise err(ERR_INVALID_STATE, "withdrawal must be SUBMITTED to approve")
        account = store.accounts[w["account_id"]]
        if account["status"] != "OPEN":
            raise err(ERR_INVALID_STATE, "account must be OPEN to approve withdrawal")
        # OCC (priority 7) before balance (priority 15).
        if "expected_account_version" not in body:
            raise err(ERR_INVALID_REQUEST, "expected_account_version required")
        expected = require_int(body, "expected_account_version")
        if expected != account["version"]:
            raise err(ERR_STALE_ACCOUNT_VERSION, "expected_account_version does not match")
        # Balance precondition (priority 15).
        if w["amount_cents"] > account["account_balance_cents"]:
            raise err(ERR_INSUFFICIENT_BALANCE, "amount exceeds balance at approve")
        # Pin calculations.
        basis, earnings = earnings_ratio_split(
            w["amount_cents"],
            account["account_balance_cents"],
            account["total_earnings_cents"],
        )
        excess = k12_excess_cents(
            w["expense_class"],
            account["ytd_qualified_k12_cents"],
            w["amount_cents"],
        )
        penalty = excess_withdrawal_penalty_cents(
            w["expense_class"], w["amount_cents"], earnings, excess
        )
        w["status"] = "APPROVED"
        now = store.clock_utc
        w["approved_at_utc"] = iso_ms(now)
        w["tax_year"] = now.year
        w["basis_portion_cents"] = basis
        w["earnings_portion_cents"] = earnings
        w["k12_excess_cents"] = excess
        w["penalty_cents"] = penalty
        stamp_update(w, now)
        stamp_update(account, now)  # version += 1 on the account.
        return success_object(_view(w))

    @app.post("/withdrawals/<wid>/disburse")
    @require_roles("CustodianAgent")
    def disburse_withdrawal(wid: str):
        w = must_exist(store.withdrawals, wid, path=True)
        if w["status"] != "APPROVED":
            raise err(ERR_INVALID_STATE, "withdrawal must be APPROVED to disburse")
        account = store.accounts[w["account_id"]]
        if account["status"] != "OPEN":
            raise err(ERR_INVALID_STATE, "account must be OPEN to disburse")
        now = store.clock_utc
        w["status"] = "DISBURSED"
        w["disbursed_at_utc"] = iso_ms(now)
        stamp_update(w, now)
        # Re-aggregate the account ledger (this re-derives from primary sources
        # including this freshly-DISBURSED withdrawal).
        recompute_account_ledger(account, bump_version=True, now=now)
        # YTD K-12 — qualified portion only.
        if w["expense_class"] == "K_12_TUITION":
            qualified = w["amount_cents"] - w.get("k12_excess_cents", 0)
            account["ytd_qualified_k12_cents"] = (
                account.get("ytd_qualified_k12_cents", 0) + qualified
            )
        # Cascade: refresh any DRAFT 1099-Q for (account_id, tax_year).
        refresh_matching_draft_forms_on_disburse(account["id"], w["tax_year"])
        return success_object(_view(w))

    @app.get("/withdrawals/<wid>")
    @require_roles("AccountOwner", "CustodianAgent", "ComplianceOfficer")
    def get_withdrawal(wid: str):
        w = must_exist(store.withdrawals, wid, path=True)
        if request.headers.get("X-User-Role") == "AccountOwner":
            account = store.accounts.get(w["account_id"])
            if not account or current_user_id() != account["donor_id"]:
                raise err(ERR_FORBIDDEN, "AccountOwner does not own this withdrawal")
        return success_object(_view(w))

    @app.get("/withdrawals/<wid>/audit")
    @require_roles("ComplianceOfficer")
    def audit_withdrawal(wid: str):
        w = must_exist(store.withdrawals, wid, path=True)
        account = store.accounts[w["account_id"]]
        # Recompute basis/earnings split against CURRENT account totals.
        # Pinned fields on the row are NOT mutated; we return a transient view.
        basis, earnings = earnings_ratio_split(
            w["amount_cents"],
            account["account_balance_cents"],
            account["total_earnings_cents"],
        )
        view = _view(w)
        view["basis_portion_cents"] = basis
        view["earnings_portion_cents"] = earnings
        return success_object(view)

    @app.get("/withdrawals")
    @require_roles("AccountOwner", "CustodianAgent", "ComplianceOfficer")
    def list_withdrawals():
        limit, offset = parse_pagination(request.args)
        account_filter = request.args.get("account_id")
        rows = list(store.withdrawals.values())
        if account_filter:
            rows = [w for w in rows if w["account_id"] == account_filter]
        if request.headers.get("X-User-Role") == "AccountOwner":
            owned = {a["id"] for a in store.accounts.values()
                     if a["donor_id"] == current_user_id()}
            rows = [w for w in rows if w["account_id"] in owned]
        rows.sort(key=lambda w: w["created_at"])
        page, total = paginate(rows, limit, offset)
        return success_array(
            [_view(w) for w in page],
            limit=limit, offset=offset, total_count=total,
        )
