"""Voucher routes (PRD §3.7 exchange via vouchers).

Validation ordering for POST /vouchers (PRD §2.10):
  auth -> role -> existence -> body well-formed -> OCC (ERR_STALE_VERSION).
"""
from datetime import timedelta

from flask import Blueprint, request

from db import db, parse_dt
from errors import err
from middleware import get_auth, require_roles, get_json_body
from response import object_response, array_response
from services import core


bp = Blueprint("vouchers", __name__)


@bp.route("/vouchers", methods=["POST"])
def issue_voucher():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    body = get_json_body()
    # Existence first (priority 3, PRD §2.10): body FKs left-to-right.
    core.resolve_body_fk(body, "from_location_id", db.locations)
    core.resolve_body_fk(body, "to_account_id", db.accounts)
    core.resolve_body_fk(body, "asset_type_id", db.asset_types)
    # Body well-formedness (priority 4).
    core.require_fields(body, ["from_location_id", "to_account_id", "asset_type_id",
                              "quantity", "expected_from_location_version"])
    from_location_id = core.require_str(body, "from_location_id")
    to_account_id = core.require_str(body, "to_account_id")
    asset_type_id = core.require_str(body, "asset_type_id")
    quantity = core.require_int(body, "quantity", minimum=1)
    expected_version = core.require_int(body, "expected_from_location_version")

    from_loc = db.locations[from_location_id]

    # OCC against from_location.version (PRD §2.9, priority 5) -> ERR_STALE_VERSION.
    if expected_version != from_loc["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_from_location_version does not match current location version")

    voucher = core.stamp_new({
        "from_location_id": from_location_id,
        "to_account_id": to_account_id,
        "asset_type_id": asset_type_id,
        "quantity": quantity,
        "issued_at": db.iso_clock(),
        "redeem_location_id": None,
        "expected_from_location_version": expected_version,
        "status": "OUTSTANDING",
    })
    db.vouchers[voucher["id"]] = voucher
    # from_location equity reduced by quantity; version +1; equity_status recompute.
    from_loc["equity_balance"] -= quantity
    core.touch(from_loc)
    core.recompute_equity_status(from_loc)
    return object_response(core.public(voucher), 201)


@bp.route("/vouchers/<voucher_id>", methods=["GET"])
def get_voucher(voucher_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    voucher = core.require(db.vouchers, voucher_id)
    return object_response(core.public(voucher), 200)


@bp.route("/vouchers", methods=["GET"])
def list_vouchers():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    items = list(db.vouchers.values())
    for field in ("from_location_id", "to_account_id", "asset_type_id",
                  "redeem_location_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [v for v in items if v[field] == val]
    data, limit, offset, total = core.paginate(items, request.args)
    return array_response(data, limit, offset, total, 200)


@bp.route("/vouchers/<voucher_id>/redeem", methods=["POST"])
def redeem_voucher(voucher_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    # Path id checked first (PRD §2.7), then body FKs.
    voucher = core.require(db.vouchers, voucher_id)
    body = get_json_body()
    # Existence first (priority 3, PRD §2.10) for the body FK.
    core.resolve_body_fk(body, "redeem_location_id", db.locations)
    # Body well-formedness (priority 4).
    core.require_fields(body, ["redeem_location_id"])
    redeem_location_id = core.require_str(body, "redeem_location_id")
    redeem_loc = db.locations[redeem_location_id]

    # OUTSTANDING -> REDEEMED (PRD §3.7) -> ERR_INVALID_STATE.
    if voucher["status"] != "OUTSTANDING":
        raise err("ERR_INVALID_STATE", "Voucher is not OUTSTANDING")

    # Preconditions in order (PRD §3.7):
    # 1. to_account must be ACTIVE -> ERR_ACCOUNT_NOT_ACTIVE.
    to_account = db.accounts[voucher["to_account_id"]]
    if to_account["status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_NOT_ACTIVE", "Redeeming account is not ACTIVE")
    # 2. redeem_location belongs to to_account_id and is OPEN.
    if redeem_loc["account_id"] != voucher["to_account_id"]:
        raise err("ERR_VOUCHER_REDEEM_LOCATION_INVALID",
                  "redeem_location_id does not belong to the voucher's to_account_id")
    if redeem_loc["status"] != "OPEN":
        raise err("ERR_LOCATION_CLOSED", "redeem location is not OPEN")
    # 3. Not past expiry: issued_at + voucher_expiry_days > current clock.
    policy = core.active_policy()
    voucher_expiry_days = policy["voucher_expiry_days"] if policy else 90
    issued = parse_dt(voucher["issued_at"])
    expiry = issued + timedelta(seconds=voucher_expiry_days * core.DAY_SECONDS)
    if not (expiry > db.clock):
        raise err("ERR_VOUCHER_EXPIRED", "Voucher is past expiry")

    # Commit (PRD §3.7).
    voucher["redeem_location_id"] = redeem_location_id
    voucher["status"] = "REDEEMED"
    core.touch(voucher)
    redeem_loc["equity_balance"] += voucher["quantity"]
    core.recompute_equity_status(redeem_loc)
    core.touch(redeem_loc)
    return object_response(core.public(voucher), 200)


@bp.route("/vouchers/<voucher_id>/cancel", methods=["POST"])
def cancel_voucher(voucher_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin"})
    voucher = core.require(db.vouchers, voucher_id)
    # OUTSTANDING -> CANCELLED (PRD §3.7) -> ERR_INVALID_STATE.
    if voucher["status"] != "OUTSTANDING":
        raise err("ERR_INVALID_STATE", "Only an OUTSTANDING voucher can be cancelled")
    # Obligation snaps back to issuer (PRD §3.7).
    from_loc = db.locations.get(voucher["from_location_id"])
    voucher["status"] = "CANCELLED"
    core.touch(voucher)
    if from_loc is not None:
        from_loc["equity_balance"] += voucher["quantity"]
        core.recompute_equity_status(from_loc)
        core.touch(from_loc)
    return object_response(core.public(voucher), 200)
