"""ScheduledContribution routes."""
from __future__ import annotations

from flask import Flask, request

from db import store, stamp_create, stamp_update, iso_ms
from errors import err, ERR_INVALID_STATE, ERR_FORBIDDEN
from middleware import require_roles, current_user_id
from response import success_object, success_array, parse_pagination, paginate
from services import advance_by_cadence
from validators import must_exist, require_dict, require_enum, require_positive_int, require_str


_CADENCES = {"WEEKLY", "MONTHLY", "QUARTERLY"}
_VIEW_KEYS = (
    "id", "created_at", "updated_at", "version",
    "account_id", "amount_cents", "cadence",
    "next_run_utc", "status", "posted_runs",
)


def _view(s: dict) -> dict:
    return {k: s[k] for k in _VIEW_KEYS}


def _check_owner_via_account(account_id: str) -> dict:
    account = must_exist(store.accounts, account_id, path=False)
    if request.headers.get("X-User-Role") == "AccountOwner":
        if current_user_id() != account["donor_id"]:
            raise err(ERR_FORBIDDEN, "AccountOwner does not own this account")
    return account


def register(app: Flask) -> None:

    @app.post("/scheduled-contributions")
    @require_roles("AccountOwner")
    def create_schedule():
        body = require_dict(request.get_json(silent=True))
        account_id = require_str(body, "account_id")
        account = _check_owner_via_account(account_id)
        amount = require_positive_int(body, "amount_cents", max_value=5_000_000)
        cadence = require_enum(body, "cadence", _CADENCES)
        # PRD §3.3: requires account in OPEN to create new schedule.
        if account["status"] != "OPEN":
            raise err(ERR_INVALID_STATE, "account must be OPEN to create schedule")
        next_run = advance_by_cadence(store.clock_utc, cadence)
        sched = stamp_create({
            "account_id": account_id,
            "amount_cents": amount,
            "cadence": cadence,
            "next_run_utc": iso_ms(next_run),
            "status": "ACTIVE",
            "posted_runs": 0,
        }, store.clock_utc)
        store.scheduled_contributions[sched["id"]] = sched
        return success_object(_view(sched), status=201)

    @app.get("/scheduled-contributions/<sid>")
    @require_roles("AccountOwner", "CustodianAgent", "ComplianceOfficer")
    def get_schedule(sid: str):
        sched = must_exist(store.scheduled_contributions, sid, path=True)
        # AccountOwner ownership: enforced via owning account.
        if request.headers.get("X-User-Role") == "AccountOwner":
            account = store.accounts.get(sched["account_id"])
            if not account or current_user_id() != account["donor_id"]:
                raise err(ERR_FORBIDDEN, "AccountOwner does not own this schedule")
        return success_object(_view(sched))

    @app.get("/scheduled-contributions")
    @require_roles("AccountOwner", "CustodianAgent", "ComplianceOfficer")
    def list_schedules():
        limit, offset = parse_pagination(request.args)
        account_filter = request.args.get("account_id")
        rows = list(store.scheduled_contributions.values())
        if account_filter:
            rows = [s for s in rows if s["account_id"] == account_filter]
        if request.headers.get("X-User-Role") == "AccountOwner":
            owned = {a["id"] for a in store.accounts.values()
                     if a["donor_id"] == current_user_id()}
            rows = [s for s in rows if s["account_id"] in owned]
        rows.sort(key=lambda s: s["created_at"])
        page, total = paginate(rows, limit, offset)
        return success_array(
            [_view(s) for s in page],
            limit=limit, offset=offset, total_count=total,
        )

    @app.post("/scheduled-contributions/<sid>/pause")
    @require_roles("AccountOwner")
    def pause_schedule(sid: str):
        sched = must_exist(store.scheduled_contributions, sid, path=True)
        account = _check_owner_via_account(sched["account_id"])
        if sched["status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "schedule must be ACTIVE to pause")
        if account["status"] not in {"OPEN", "RESTRICTED"}:
            raise err(ERR_INVALID_STATE, "account must be OPEN or RESTRICTED to pause schedule")
        sched["status"] = "PAUSED"
        stamp_update(sched, store.clock_utc)
        return success_object(_view(sched))

    @app.post("/scheduled-contributions/<sid>/resume")
    @require_roles("AccountOwner")
    def resume_schedule(sid: str):
        sched = must_exist(store.scheduled_contributions, sid, path=True)
        account = _check_owner_via_account(sched["account_id"])
        if sched["status"] != "PAUSED":
            raise err(ERR_INVALID_STATE, "schedule must be PAUSED to resume")
        if account["status"] != "OPEN":
            raise err(ERR_INVALID_STATE, "account must be OPEN to resume schedule")
        sched["status"] = "ACTIVE"
        sched["next_run_utc"] = iso_ms(advance_by_cadence(store.clock_utc, sched["cadence"]))
        stamp_update(sched, store.clock_utc)
        return success_object(_view(sched))

    @app.post("/scheduled-contributions/<sid>/cancel")
    @require_roles("AccountOwner")
    def cancel_schedule(sid: str):
        sched = must_exist(store.scheduled_contributions, sid, path=True)
        _check_owner_via_account(sched["account_id"])
        if sched["status"] not in {"ACTIVE", "PAUSED"}:
            raise err(ERR_INVALID_STATE, "schedule must be ACTIVE or PAUSED to cancel")
        sched["status"] = "CANCELLED"
        stamp_update(sched, store.clock_utc)
        return success_object(_view(sched))
