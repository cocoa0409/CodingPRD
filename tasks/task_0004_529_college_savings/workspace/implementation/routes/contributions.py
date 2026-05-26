"""Contribution routes: create, post, reverse, get, list."""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from flask import Flask, request

from db import store, stamp_create, stamp_update, iso_ms
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_REVERSE_WINDOW_CLOSED,
    ERR_INVALID_REQUEST,
    ERR_FORBIDDEN,
)
from middleware import require_roles, current_user_id
from response import success_object, success_array, parse_pagination, paginate
from services import (
    advance_by_cadence,
    recompute_account_ledger,
    recompute_state_tax_incentives,
)
from validators import (
    must_exist,
    parse_iso,
    require_dict,
    require_enum,
    require_positive_int,
    require_str,
)


_KINDS = {"LUMP_SUM", "RECURRING"}
_VIEW_KEYS = (
    "id", "created_at", "updated_at", "version",
    "account_id", "amount_cents", "contribution_kind",
    "scheduled_contribution_id", "status",
    "posted_at_utc", "tax_year",
)


def _view(c: dict) -> dict:
    return {k: c.get(k) for k in _VIEW_KEYS}


def post_contribution_logic(contribution: dict) -> None:
    """Drive a DRAFT contribution to POSTED (shared by /post endpoint and
    /_scheduler/tick admin endpoint). Caller is responsible for validating the
    contribution is currently DRAFT and the account passes state-precondition
    checks; this fn performs the state mutation and all cascades.
    """
    account = store.accounts[contribution["account_id"]]
    now = store.clock_utc
    contribution["status"] = "POSTED"
    contribution["posted_at_utc"] = iso_ms(now)
    contribution["tax_year"] = now.year
    stamp_update(contribution, now)
    recompute_account_ledger(account, bump_version=True, now=now)
    if contribution.get("scheduled_contribution_id"):
        sched = store.scheduled_contributions.get(contribution["scheduled_contribution_id"])
        if sched is not None:
            sched["posted_runs"] = sched.get("posted_runs", 0) + 1
            sched["next_run_utc"] = iso_ms(advance_by_cadence(now, sched["cadence"]))
            stamp_update(sched, now)
    recompute_state_tax_incentives(account["donor_id"], contribution["tax_year"])


def register(app: Flask) -> None:

    @app.post("/contributions")
    @require_roles("CustodianAgent")
    def create_contribution():
        body = require_dict(request.get_json(silent=True))
        account_id = require_str(body, "account_id")
        must_exist(store.accounts, account_id, path=False)
        amount = require_positive_int(body, "amount_cents", max_value=5_000_000)
        kind = require_enum(body, "contribution_kind", _KINDS)
        sched_id: Optional[str] = None
        if kind == "RECURRING":
            if "scheduled_contribution_id" not in body:
                raise err(ERR_INVALID_REQUEST, "scheduled_contribution_id required for RECURRING")
            sched_id = require_str(body, "scheduled_contribution_id")
            must_exist(store.scheduled_contributions, sched_id, path=False)
        else:
            # LUMP_SUM must not carry a schedule reference.
            if body.get("scheduled_contribution_id"):
                raise err(ERR_INVALID_REQUEST, "scheduled_contribution_id must be null for LUMP_SUM")
        contribution = stamp_create({
            "account_id": account_id,
            "amount_cents": amount,
            "contribution_kind": kind,
            "scheduled_contribution_id": sched_id,
            "status": "DRAFT",
            "posted_at_utc": None,
            "tax_year": None,
        }, store.clock_utc)
        store.contributions[contribution["id"]] = contribution
        return success_object(_view(contribution), status=201)

    @app.post("/contributions/<cid>/post")
    @require_roles("CustodianAgent")
    def post_contribution(cid: str):
        contribution = must_exist(store.contributions, cid, path=True)
        if contribution["status"] != "DRAFT":
            raise err(ERR_INVALID_STATE, "contribution must be DRAFT to post")
        account = store.accounts.get(contribution["account_id"])
        if account is None or account["status"] not in {"OPEN", "RESTRICTED"}:
            raise err(ERR_INVALID_STATE, "account must be OPEN or RESTRICTED")
        if contribution["contribution_kind"] == "RECURRING":
            sched = store.scheduled_contributions.get(contribution.get("scheduled_contribution_id") or "")
            if not sched or sched["status"] != "ACTIVE":
                raise err(ERR_INVALID_STATE, "scheduled contribution must be ACTIVE")
        post_contribution_logic(contribution)
        return success_object(_view(contribution))

    @app.post("/contributions/<cid>/reverse")
    @require_roles("CustodianAgent")
    def reverse_contribution(cid: str):
        contribution = must_exist(store.contributions, cid, path=True)
        if contribution["status"] != "POSTED":
            raise err(ERR_INVALID_STATE, "contribution must be POSTED to reverse")
        account = store.accounts[contribution["account_id"]]
        if account["status"] not in {"OPEN", "RESTRICTED"}:
            raise err(ERR_INVALID_STATE, "account must be OPEN or RESTRICTED")
        # 72h window — strictly less than 72 hours from posted_at_utc.
        posted_at = parse_iso(contribution["posted_at_utc"])
        if (store.clock_utc - posted_at) >= timedelta(hours=72):
            raise err(ERR_REVERSE_WINDOW_CLOSED, "reverse window has elapsed")
        # Ledger-safety: after the reverse, balance must still cover
        # APPROVED-but-not-DISBURSED withdrawals on this account.
        approved_owed = sum(
            w["amount_cents"]
            for w in store.withdrawals.values()
            if w["account_id"] == account["id"] and w["status"] == "APPROVED"
        )
        projected_balance = account["account_balance_cents"] - contribution["amount_cents"]
        if projected_balance < approved_owed:
            raise err(ERR_INVALID_STATE, "reverse would underflow against approved withdrawals")
        contribution["status"] = "REVERSED"
        now = store.clock_utc
        stamp_update(contribution, now)
        recompute_account_ledger(account, bump_version=True, now=now)
        recompute_state_tax_incentives(account["donor_id"], contribution["tax_year"])
        return success_object(_view(contribution))

    @app.get("/contributions/<cid>")
    @require_roles("CustodianAgent", "AccountOwner", "ComplianceOfficer")
    def get_contribution(cid: str):
        c = must_exist(store.contributions, cid, path=True)
        if request.headers.get("X-User-Role") == "AccountOwner":
            account = store.accounts.get(c["account_id"])
            if not account or current_user_id() != account["donor_id"]:
                raise err(ERR_FORBIDDEN, "AccountOwner does not own this contribution")
        return success_object(_view(c))

    @app.get("/contributions")
    @require_roles("CustodianAgent", "AccountOwner", "ComplianceOfficer")
    def list_contributions():
        limit, offset = parse_pagination(request.args)
        account_filter = request.args.get("account_id")
        sched_filter = request.args.get("scheduled_contribution_id")
        rows = list(store.contributions.values())
        if account_filter:
            rows = [c for c in rows if c["account_id"] == account_filter]
        if sched_filter:
            rows = [c for c in rows if c.get("scheduled_contribution_id") == sched_filter]
        if request.headers.get("X-User-Role") == "AccountOwner":
            owned = {a["id"] for a in store.accounts.values()
                     if a["donor_id"] == current_user_id()}
            rows = [c for c in rows if c["account_id"] in owned]
        rows.sort(key=lambda c: c["created_at"])
        page, total = paginate(rows, limit, offset)
        return success_array(
            [_view(c) for c in page],
            limit=limit, offset=offset, total_count=total,
        )
