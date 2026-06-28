"""ExcessCorrection: request (OCC-guarded), list, execute, reject (PRD §3.9, §2.8).

Execute cascade (excess_correction_sweep): order POSTED contributions by
posted_at DESC, tie-break created_at DESC (latest first), reverse in full until
reversed_sum >= corrected_amount. Each reversal lowers cash_balance and
contributions_ytd. Then excess recomputed -> 0; posture -> OPEN.
"""
from flask import Blueprint

import serializers
from db import db, stamp_create, touch
from errors import err
from helpers import get_json_body, paginate, qarg, require_int
from lookups import get_account, get_correction
from middleware import caller, require_role
from response import success
from services.account_calc import recompute_derived

bp = Blueprint("corrections", __name__)


@bp.route("/hsa/accounts/<account_id>/corrections", methods=["POST"])
def request_correction(account_id):
    _, role = caller()
    require_role(role, {"AccountAdmin", "Accountholder"})
    account = get_account(account_id)
    body = get_json_body()
    # Both fields non-optional. requested_amount_cents must be a positive int
    # equal to the current excess (mismatch surfaces at execute per PRD §3.9;
    # the create only requires presence/typing and the OCC version match).
    requested = require_int(body, "requested_amount_cents", required=True)
    expected_version = require_int(body, "expected_account_version", required=True)
    if requested <= 0:
        raise err("ERR_INVALID_REQUEST", "requested_amount_cents must be a positive integer")

    # OCC stale-version check is the last guard (PRD §2.9).
    if expected_version != account["version"]:
        raise err("ERR_STALE_ACCOUNT_VERSION", "expected_account_version is stale")

    o = {
        "account_id": account_id,
        "requested_amount_cents": requested,
        "corrected_amount_cents": None,
        "status": "REQUESTED",
    }
    stamp_create(o)
    db.excess_corrections[o["id"]] = o
    # Creating a correction increments the account version by one.
    touch(account)
    return success(serializers.excess_correction(o), status=201)


@bp.route("/hsa/accounts/<account_id>/corrections", methods=["GET"])
def list_corrections(account_id):
    _, role = caller()
    require_role(role, {"AccountAdmin", "Accountholder"})
    get_account(account_id)
    status_filter = qarg("status")
    items = [
        c for c in db.excess_corrections.values()
        if c["account_id"] == account_id
        and (status_filter is None or c["status"] == status_filter)
    ]
    page, meta = paginate(items)
    return success([serializers.excess_correction(c) for c in page], status=200, pagination=meta)


@bp.route("/hsa/accounts/<account_id>/corrections/<correction_id>/execute", methods=["POST"])
def execute_correction(account_id, correction_id):
    _, role = caller()
    require_role(role, {"AccountAdmin"})
    account = get_account(account_id)
    correction = get_correction(account_id, correction_id)

    # State: only from REQUESTED.
    if correction["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Correction is not REQUESTED")
    # lifecycle must be ACTIVE.
    if account["lifecycle_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Account is not ACTIVE")
    # excess must be > 0.
    if account["excess_contribution_cents"] <= 0:
        raise err("ERR_NO_EXCESS", "No excess to correct")
    # requested must equal current excess.
    if correction["requested_amount_cents"] != account["excess_contribution_cents"]:
        raise err("ERR_CORRECTION_AMOUNT_MISMATCH", "requested_amount_cents != current excess")

    target = account["excess_contribution_cents"]
    correction["status"] = "COMPLETED"
    correction["corrected_amount_cents"] = target

    # Cascade: reverse latest-posted-first until reversed_sum >= target.
    posted = [
        c for c in db.contributions.values()
        if c["account_id"] == account_id and c["status"] == "POSTED"
    ]
    # posted_at DESC, tie-break created_at DESC (latest first).
    posted.sort(key=lambda c: (c["posted_at"] or "", c["created_at"], c["id"]), reverse=True)

    reversed_sum = 0
    for c in posted:
        if reversed_sum >= target:
            break
        c["status"] = "REVERSED"
        touch(c)
        account["cash_balance_cents"] -= c["amount_cents"]
        reversed_sum += c["amount_cents"]

    recompute_derived(account)  # ytd downward; excess -> 0; posture -> OPEN; bump
    touch(correction)
    return success(serializers.excess_correction(correction), status=200)


@bp.route("/hsa/accounts/<account_id>/corrections/<correction_id>/reject", methods=["POST"])
def reject_correction(account_id, correction_id):
    _, role = caller()
    require_role(role, {"AccountAdmin"})
    get_account(account_id)
    correction = get_correction(account_id, correction_id)
    if correction["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Correction is not REQUESTED")
    correction["status"] = "REJECTED"
    touch(correction)
    return success(serializers.excess_correction(correction), status=200)
