"""Admin / test-driving endpoints: clock, market credit, scheduler tick."""
from __future__ import annotations

from flask import Flask, request

from db import store, stamp_update, iso_ms, new_id, stamp_create
from errors import err, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success_object, success_array
from services import recompute_account_ledger
from validators import must_exist, parse_iso, require_dict, require_positive_int, require_str
from routes.contributions import post_contribution_logic


def _scheduled_view(s: dict) -> dict:
    keys = ("id", "created_at", "updated_at", "version",
            "account_id", "amount_cents", "cadence",
            "next_run_utc", "status", "posted_runs")
    return {k: s[k] for k in keys}


def _account_view(a: dict) -> dict:
    keys = ("id", "created_at", "updated_at", "version",
            "donor_id", "beneficiary_id", "status",
            "total_basis_cents", "total_earnings_cents", "account_balance_cents",
            "ytd_qualified_k12_cents", "tax_year")
    return {k: a[k] for k in keys}


def register(app: Flask) -> None:

    @app.post("/_clock/set_current_utc")
    @require_roles("CustodianAgent", "SystemTaxAuthority", "ComplianceOfficer")
    def set_clock():
        body = require_dict(request.get_json(silent=True))
        iso = require_str(body, "to_iso8601")
        new_clock = parse_iso(iso)
        old_year = store.clock_utc.year
        store.clock_utc = new_clock
        # If the year rolled, recompute every account's tax_year. PRD §3.10:
        # ytd_qualified_k12_cents is NOT auto-reset.
        if new_clock.year != old_year:
            for a in store.accounts.values():
                a["tax_year"] = new_clock.year
        return success_object({"current_utc": iso_ms(new_clock)})

    @app.get("/_clock")
    @require_roles("CustodianAgent", "SystemTaxAuthority", "ComplianceOfficer", "AccountOwner")
    def get_clock():
        return success_object({"current_utc": iso_ms(store.clock_utc)})

    @app.post("/_market/credit_earnings")
    @require_roles("CustodianAgent")
    def credit_earnings():
        body = require_dict(request.get_json(silent=True))
        account_id = require_str(body, "account_id")
        account = must_exist(store.accounts, account_id, path=False)
        delta = require_positive_int(body, "delta_cents")
        account["_market_credit_cents"] = account.get("_market_credit_cents", 0) + delta
        # Recompute ledger (balance increases, basis unchanged, earnings = balance - basis).
        recompute_account_ledger(account, bump_version=True, now=store.clock_utc)
        return success_object(_account_view(account))

    @app.post("/_scheduler/tick")
    @require_roles("CustodianAgent")
    def scheduler_tick():
        """For every ACTIVE schedule whose next_run_utc <= clock, materialise a
        fresh RECURRING Contribution and post it immediately."""
        triggered = []
        now = store.clock_utc
        for sched in list(store.scheduled_contributions.values()):
            if sched["status"] != "ACTIVE":
                continue
            try:
                due = parse_iso(sched["next_run_utc"])
            except Exception:
                continue
            if due > now:
                continue
            account = store.accounts.get(sched["account_id"])
            if account is None or account["status"] not in {"OPEN", "RESTRICTED"}:
                continue
            # Create a fresh DRAFT contribution and post it via shared logic.
            contribution = stamp_create({
                "account_id": sched["account_id"],
                "amount_cents": sched["amount_cents"],
                "contribution_kind": "RECURRING",
                "scheduled_contribution_id": sched["id"],
                "status": "DRAFT",
                "posted_at_utc": None,
                "tax_year": None,
            }, now)
            store.contributions[contribution["id"]] = contribution
            post_contribution_logic(contribution)
            triggered.append(sched)
        # Return list of advanced schedules.
        rows = [_scheduled_view(s) for s in triggered]
        return success_array(rows, limit=len(rows), offset=0, total_count=len(rows))
