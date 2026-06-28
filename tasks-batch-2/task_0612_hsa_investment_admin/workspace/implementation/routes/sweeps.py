"""InvestmentSweep: create (OCC-guarded), list, unwind (PRD §3.5, §2.8).

investable_cash_sweep calc:
  excess_cash = max(0, cash_balance_cents - invest_threshold_cents)
  cap = requested_amount_cents if provided else excess_cash
  sweepable_raw = min(excess_cash, cap)
  swept = floor(sweepable_raw / sweep_increment) * sweep_increment
  Boundary is strict: cash must be > threshold. If swept == 0 -> ERR_NOTHING_TO_SWEEP
  and NO row persists.
OCC: expected_account_version must equal account.version, else
ERR_STALE_ACCOUNT_VERSION (412). The OCC check is the LAST guard a sweep passes
(PRD §2.9). A successful create increments account.version by one.
"""
from flask import Blueprint

import serializers
from db import db, stamp_create, touch
from errors import err
from helpers import (get_json_body, paginate, qarg, require_int,
                     require_positive_int)
from lookups import get_account, get_sweep
from middleware import caller, require_role
from response import success

bp = Blueprint("sweeps", __name__)


@bp.route("/hsa/accounts/<account_id>/sweeps", methods=["POST"])
def create_sweep(account_id):
    _, role = caller()
    require_role(role, {"AccountAdmin", "Accountholder"})
    account = get_account(account_id)
    body = get_json_body()
    # expected_account_version is non-optional (PRD §2.8). Validated as int.
    expected_version = require_int(body, "expected_account_version", required=True)
    requested = require_positive_int(body, "requested_amount_cents", required=False)

    # Compute swept amount (business rule, evaluated before the OCC check).
    excess_cash = max(0, account["cash_balance_cents"] - account["invest_threshold_cents"])
    cap = requested if requested is not None else excess_cash
    sweepable_raw = min(excess_cash, cap)
    increment = account["sweep_increment_cents"]
    swept = (sweepable_raw // increment) * increment

    if swept == 0:
        raise err("ERR_NOTHING_TO_SWEEP", "Nothing to sweep")

    # OCC stale-version check is the LAST guard (PRD §2.9).
    if expected_version != account["version"]:
        raise err("ERR_STALE_ACCOUNT_VERSION", "expected_account_version is stale")

    o = {
        "account_id": account_id,
        "requested_amount_cents": requested,  # may be null
        "swept_amount_cents": swept,
        "status": "EXECUTED",
    }
    stamp_create(o)
    db.investment_sweeps[o["id"]] = o

    account["cash_balance_cents"] -= swept
    account["invested_balance_cents"] += swept
    touch(account)  # increments version by one
    return success(serializers.investment_sweep(o), status=201)


@bp.route("/hsa/accounts/<account_id>/sweeps", methods=["GET"])
def list_sweeps(account_id):
    _, role = caller()
    require_role(role, {"AccountAdmin", "Accountholder"})
    get_account(account_id)
    status_filter = qarg("status")
    items = [
        s for s in db.investment_sweeps.values()
        if s["account_id"] == account_id
        and (status_filter is None or s["status"] == status_filter)
    ]
    page, meta = paginate(items)
    return success([serializers.investment_sweep(s) for s in page], status=200, pagination=meta)


@bp.route("/hsa/accounts/<account_id>/sweeps/<sweep_id>/unwind", methods=["POST"])
def unwind_sweep(account_id, sweep_id):
    _, role = caller()
    require_role(role, {"AccountAdmin"})
    account = get_account(account_id)
    sweep = get_sweep(account_id, sweep_id)
    if sweep["status"] != "EXECUTED":
        raise err("ERR_INVALID_STATE", "Sweep is not EXECUTED")
    sweep["status"] = "UNWOUND"
    touch(sweep)
    account["invested_balance_cents"] -= sweep["swept_amount_cents"]
    account["cash_balance_cents"] += sweep["swept_amount_cents"]
    touch(account)
    return success(serializers.investment_sweep(sweep), status=200)
