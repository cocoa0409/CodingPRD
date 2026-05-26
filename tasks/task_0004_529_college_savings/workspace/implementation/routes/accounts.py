"""Account routes: CRUD + restrict/release/close lifecycle."""
from __future__ import annotations

from flask import Flask, request

from db import store, stamp_create, stamp_update
from errors import err, ERR_INVALID_STATE, ERR_FORBIDDEN
from middleware import require_roles, current_user_id
from response import success_object, success_array, parse_pagination, paginate
from validators import must_exist, require_dict, require_str


_VIEW_KEYS = (
    "id", "created_at", "updated_at", "version",
    "donor_id", "beneficiary_id",
    "status",
    "total_basis_cents", "total_earnings_cents", "account_balance_cents",
    "ytd_qualified_k12_cents", "tax_year",
)


def _account_view(a: dict) -> dict:
    return {k: a[k] for k in _VIEW_KEYS}


def _ensure_owner(account: dict) -> None:
    """Enforce AccountOwner ownership: X-User-ID must equal account.donor_id."""
    if request.headers.get("X-User-Role") == "AccountOwner":
        if current_user_id() != account["donor_id"]:
            raise err(ERR_FORBIDDEN, "AccountOwner does not own this account")


def register(app: Flask) -> None:

    @app.post("/accounts")
    @require_roles("CustodianAgent")
    def create_account():
        body = require_dict(request.get_json(silent=True))
        donor_id = require_str(body, "donor_id")
        beneficiary_id = require_str(body, "beneficiary_id")
        must_exist(store.donors, donor_id, path=False)
        must_exist(store.beneficiaries, beneficiary_id, path=False)
        account = stamp_create({
            "donor_id": donor_id,
            "beneficiary_id": beneficiary_id,
            "status": "OPEN",
            "total_basis_cents": 0,
            "total_earnings_cents": 0,
            "account_balance_cents": 0,
            "ytd_qualified_k12_cents": 0,
            "tax_year": store.clock_utc.year,
            "_market_credit_cents": 0,  # private; not exposed in view.
        }, store.clock_utc)
        store.accounts[account["id"]] = account
        return success_object(_account_view(account), status=201)

    @app.get("/accounts/<account_id>")
    @require_roles("CustodianAgent", "AccountOwner", "ComplianceOfficer")
    def get_account(account_id: str):
        account = must_exist(store.accounts, account_id, path=True)
        _ensure_owner(account)
        return success_object(_account_view(account))

    @app.get("/accounts")
    @require_roles("CustodianAgent", "ComplianceOfficer")
    def list_accounts():
        limit, offset = parse_pagination(request.args)
        donor_filter = request.args.get("donor_id")
        ben_filter = request.args.get("beneficiary_id")
        rows = list(store.accounts.values())
        if donor_filter:
            rows = [a for a in rows if a["donor_id"] == donor_filter]
        if ben_filter:
            rows = [a for a in rows if a["beneficiary_id"] == ben_filter]
        rows.sort(key=lambda a: a["created_at"])
        page, total = paginate(rows, limit, offset)
        return success_array(
            [_account_view(a) for a in page],
            limit=limit, offset=offset, total_count=total,
        )

    @app.post("/accounts/<account_id>/restrict")
    @require_roles("ComplianceOfficer")
    def restrict_account(account_id: str):
        account = must_exist(store.accounts, account_id, path=True)
        if account["status"] != "OPEN":
            raise err(ERR_INVALID_STATE, "account must be OPEN to restrict")
        account["status"] = "RESTRICTED"
        stamp_update(account, store.clock_utc)
        return success_object(_account_view(account))

    @app.post("/accounts/<account_id>/release")
    @require_roles("ComplianceOfficer")
    def release_account(account_id: str):
        account = must_exist(store.accounts, account_id, path=True)
        if account["status"] != "RESTRICTED":
            raise err(ERR_INVALID_STATE, "account must be RESTRICTED to release")
        account["status"] = "OPEN"
        stamp_update(account, store.clock_utc)
        return success_object(_account_view(account))

    @app.post("/accounts/<account_id>/close")
    @require_roles("AccountOwner")
    def close_account(account_id: str):
        account = must_exist(store.accounts, account_id, path=True)
        _ensure_owner(account)
        # State precondition (priority 6) before business checks.
        if account["status"] != "OPEN":
            raise err(ERR_INVALID_STATE, "account must be OPEN to close")
        if account["account_balance_cents"] != 0:
            raise err(ERR_INVALID_STATE, "account_balance_cents must be 0 to close")
        has_active_schedule = any(
            s["account_id"] == account_id and s["status"] == "ACTIVE"
            for s in store.scheduled_contributions.values()
        )
        if has_active_schedule:
            raise err(ERR_INVALID_STATE, "active scheduled contributions present")
        has_inflight_withdrawal = any(
            w["account_id"] == account_id and w["status"] in {"SUBMITTED", "APPROVED"}
            for w in store.withdrawals.values()
        )
        if has_inflight_withdrawal:
            raise err(ERR_INVALID_STATE, "in-flight withdrawal present")
        has_pending_change = any(
            c["account_id"] == account_id and c["status"] == "PENDING"
            for c in store.beneficiary_changes.values()
        )
        if has_pending_change:
            raise err(ERR_INVALID_STATE, "pending beneficiary change present")
        account["status"] = "CLOSED"
        stamp_update(account, store.clock_utc)
        return success_object(_account_view(account))
