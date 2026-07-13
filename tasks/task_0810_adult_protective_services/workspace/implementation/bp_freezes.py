"""Financial-exploitation freezes (PRD 3.5)."""
from datetime import timedelta

from flask import Blueprint, request

from store import store
from errors import ApiError
from envelope import success
from helpers import (authenticate, authorize, get_body, require_str, require_int,
                     resolve, resolve_body_id, parse_dt, base_fields, touch,
                     paginate, sort_key, serialize)
from recompute import recompute_case_financials

bp = Blueprint("freezes", __name__)

COOLDOWN_HOURS = 24


@bp.post("/freezes")
def create_freeze():
    uid, role = authenticate()
    authorize(role, {"Caseworker", "Supervisor"})
    body = get_body()
    resolve_body_id(body, "case_id", "case")
    resolve_body_id(body, "account_id", "account")
    case_id = require_str(body, "case_id")
    account_id = require_str(body, "account_id")
    flagged = require_int(body, "flagged_amount_cents")
    start_raw = require_str(body, "freeze_start")
    end_raw = require_str(body, "freeze_end")
    case = resolve("case", case_id)
    account = resolve("account", account_id)

    freeze_start = parse_dt(start_raw, "freeze_start")
    freeze_end = parse_dt(end_raw, "freeze_end")
    if not (freeze_end > freeze_start):
        raise ApiError("ERR_INVALID_DATE_RANGE", "freeze_end must be strictly after freeze_start", 422)

    if "FINANCIAL_EXPLOITATION" not in case["allegation_types"] or case["status"] != "UNDER_INVESTIGATION":
        raise ApiError("ERR_NOT_FINANCIAL_EXPLOITATION",
                       "Case does not admit a financial freeze", 422)
    if account["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_ALREADY_FROZEN", "Account is already frozen", 409)

    # cool-down against the most recent prior freeze on this account
    prior = [f for f in store.freezes.values() if f["account_id"] == account_id]
    if prior:
        latest = max(prior, key=lambda f: (f["created_at"], f["_seq"]))
        if freeze_start < latest["freeze_end"] + timedelta(hours=COOLDOWN_HOURS):
            raise ApiError("ERR_FREEZE_WINDOW_OVERLAP",
                           "Freeze window violates the mandatory cool-down", 409)

    freeze = base_fields()
    freeze.update({
        "case_id": case_id,
        "account_id": account_id,
        "flagged_amount_cents": flagged,
        "freeze_start": freeze_start,
        "freeze_end": freeze_end,
        "status": "ACTIVE",
        "lifted_at": None,
    })
    store.freezes[freeze["id"]] = freeze

    account["frozen_amount_cents"] = account["total_balance_cents"]
    account["available_balance_cents"] = 0
    account["flagged_amount_cents"] = flagged
    account["status"] = "FROZEN"
    touch(account)

    recompute_case_financials(case)
    touch(case)
    return success(serialize(freeze, "freeze")), 201


@bp.get("/freezes/<fid>")
def get_freeze(fid):
    uid, role = authenticate()
    authorize(role, {"Caseworker", "Supervisor"})
    freeze = resolve("freeze", fid)
    return success(serialize(freeze, "freeze")), 200


@bp.get("/freezes")
def list_freezes():
    uid, role = authenticate()
    authorize(role, {"Caseworker", "Supervisor"})
    items = list(store.freezes.values())
    for key in ("case_id", "account_id"):
        val = request.args.get(key)
        if val is not None:
            items = [f for f in items if f[key] == val]
    items.sort(key=sort_key)
    page, pag = paginate(items)
    return success([serialize(f, "freeze") for f in page], "array", pag), 200


@bp.post("/freezes/<fid>/lift")
def lift_freeze(fid):
    uid, role = authenticate()
    authorize(role, {"Supervisor"})
    freeze = resolve("freeze", fid)
    if freeze["status"] != "ACTIVE":
        raise ApiError("ERR_FREEZE_INVALID_STATE", "Freeze is not ACTIVE", 409)
    freeze["status"] = "LIFTED"
    freeze["lifted_at"] = store.clock
    touch(freeze)

    account = store.accounts[freeze["account_id"]]
    account["frozen_amount_cents"] = 0
    account["available_balance_cents"] = account["total_balance_cents"]
    account["flagged_amount_cents"] = 0
    account["status"] = "ACTIVE"
    touch(account)

    case = store.cases[freeze["case_id"]]
    recompute_case_financials(case)
    touch(case)
    return success(serialize(freeze, "freeze")), 200
