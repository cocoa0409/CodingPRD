"""Clock, PoolPolicy, AssetType, Account, Location routes.

Covers PRD §2.4 (clock), §3.1 (policy/asset-type/account/location).
"""
from flask import Blueprint, request

from db import db, parse_dt, iso
from errors import err
from middleware import get_auth, require_roles, get_json_body
from response import object_response, array_response
from services import core

bp = Blueprint("setup", __name__)


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin"})
    body = get_json_body()
    core.require_fields(body, ["to_iso8601"])
    dt = parse_dt(body.get("to_iso8601"))
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 datetime")
    db.clock = dt
    return object_response({}, 200)


# ---------------------------------------------------------------------------
# PoolPolicy (PRD §3.1)
# ---------------------------------------------------------------------------
@bp.route("/pool-policies", methods=["POST"])
def create_pool_policy():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin"})
    body = get_json_body()
    core.require_fields(body, ["name"])
    name = core.require_str(body, "name")
    currency = body.get("currency", "USD")
    if currency is None:
        currency = "USD"
    if not isinstance(currency, str) or not currency.strip():
        raise err("ERR_INVALID_REQUEST", "currency must be a string")
    equity_warn = core.optional_int(body, "equity_warn_threshold", 200)
    voucher_expiry = core.optional_int(body, "voucher_expiry_days", 90)
    audit_min = core.optional_int(body, "audit_min_interval_days", 28)

    # Only one ACTIVE PoolPolicy may exist (PRD §3.1) -> ERR_DUPLICATE_RESOURCE.
    if core.active_policy() is not None:
        raise err("ERR_DUPLICATE_RESOURCE", "An ACTIVE pool policy already exists")

    policy = core.stamp_new({
        "name": name,
        "currency": currency,
        "equity_warn_threshold": equity_warn,
        "voucher_expiry_days": voucher_expiry,
        "audit_min_interval_days": audit_min,
        "status": "ACTIVE",
    })
    db.pool_policies[policy["id"]] = policy
    return object_response(core.public(policy), 201)


@bp.route("/pool-policies/<pool_policy_id>", methods=["GET"])
def get_pool_policy(pool_policy_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    policy = core.require(db.pool_policies, pool_policy_id)
    return object_response(core.public(policy), 200)


# ---------------------------------------------------------------------------
# AssetType (PRD §3.1)
# ---------------------------------------------------------------------------
@bp.route("/asset-types", methods=["POST"])
def create_asset_type():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin"})
    body = get_json_body()
    core.require_fields(body, ["code", "name", "base_daily_rate_cents", "replacement_cost_cents"])
    code = core.require_str(body, "code")
    name = core.require_str(body, "name")
    base_rate = core.require_int(body, "base_daily_rate_cents", minimum=0)
    repl_cost = core.require_int(body, "replacement_cost_cents", minimum=0)
    useful_life = core.optional_int(body, "useful_life_days", 1825, minimum=1)

    # code unique across all asset types regardless of status (PRD §3.1).
    for at in db.asset_types.values():
        if at["code"] == code:
            raise err("ERR_DUPLICATE_RESOURCE", "AssetType code already exists")

    at = core.stamp_new({
        "code": code,
        "name": name,
        "base_daily_rate_cents": base_rate,
        "replacement_cost_cents": repl_cost,
        "useful_life_days": useful_life,
        "status": "ACTIVE",
    })
    db.asset_types[at["id"]] = at
    return object_response(core.public(at), 201)


@bp.route("/asset-types/<asset_type_id>", methods=["GET"])
def get_asset_type(asset_type_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    at = core.require(db.asset_types, asset_type_id)
    return object_response(core.public(at), 200)


@bp.route("/asset-types/<asset_type_id>/discontinue", methods=["POST"])
def discontinue_asset_type(asset_type_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin"})
    at = core.require(db.asset_types, asset_type_id)
    at["status"] = "DISCONTINUED"
    core.touch(at)
    return object_response(core.public(at), 200)


# ---------------------------------------------------------------------------
# Account (PRD §3.1, lifecycle §3.1)
# ---------------------------------------------------------------------------
@bp.route("/accounts", methods=["POST"])
def create_account():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin"})
    body = get_json_body()
    core.require_fields(body, ["legal_name", "role_type", "credit_limit_cents"])
    legal_name = core.require_str(body, "legal_name")
    role_type = core.require_enum(body, "role_type",
                                  {"MANUFACTURER", "DISTRIBUTOR", "RETAILER"})
    credit_limit = core.require_int(body, "credit_limit_cents", minimum=0)

    acc = core.stamp_new({
        "legal_name": legal_name,
        "role_type": role_type,
        "credit_limit_cents": credit_limit,
        "outstanding_charge_cents": 0,
        "status": "ACTIVE",
    })
    db.accounts[acc["id"]] = acc
    return object_response(core.public(acc), 201)


@bp.route("/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    acc = core.require(db.accounts, account_id)
    # outstanding_charge_cents recomputed on read (PRD §3.5).
    core.recompute_account_outstanding(acc)
    return object_response(core.public(acc), 200)


@bp.route("/accounts/<account_id>/suspend", methods=["POST"])
def suspend_account(account_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin"})
    acc = core.require(db.accounts, account_id)
    # ACTIVE -> SUSPENDED (PRD §3.1).
    if acc["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE account can be suspended")
    acc["status"] = "SUSPENDED"
    core.touch(acc)
    return object_response(core.public(acc), 200)


@bp.route("/accounts/<account_id>/reactivate", methods=["POST"])
def reactivate_account(account_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin"})
    acc = core.require(db.accounts, account_id)
    # SUSPENDED -> ACTIVE (PRD §3.1).
    if acc["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Only a SUSPENDED account can be reactivated")
    acc["status"] = "ACTIVE"
    core.touch(acc)
    return object_response(core.public(acc), 200)


@bp.route("/accounts/<account_id>/close", methods=["POST"])
def close_account(account_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin"})
    acc = core.require(db.accounts, account_id)
    # ACTIVE -> CLOSED (PRD §3.1).
    if acc["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE account can be closed")
    # No OPEN hire (PRD §3.1) -> ERR_ACCOUNT_HAS_OPEN_HIRE.
    for h in db.hires.values():
        if h["account_id"] == account_id and h["lifecycle_status"] == "OPEN":
            raise err("ERR_ACCOUNT_HAS_OPEN_HIRE",
                      "Account has a hire in lifecycle_status OPEN")
    # outstanding_charge_cents == 0 (PRD §3.1) -> ERR_ACCOUNT_NOT_SETTLED.
    core.recompute_account_outstanding(acc)
    if acc["outstanding_charge_cents"] != 0:
        raise err("ERR_ACCOUNT_NOT_SETTLED",
                  "Account outstanding_charge_cents is not zero")
    acc["status"] = "CLOSED"
    core.touch(acc)
    return object_response(core.public(acc), 200)


# ---------------------------------------------------------------------------
# Location (PRD §3.1)
# ---------------------------------------------------------------------------
@bp.route("/locations", methods=["POST"])
def create_location():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator"})
    body = get_json_body()
    # Existence first (priority 3, PRD §2.10).
    core.resolve_body_fk(body, "account_id", db.accounts)
    # Body well-formedness (priority 4).
    core.require_fields(body, ["account_id", "name"])
    account_id = core.require_str(body, "account_id")
    name = core.require_str(body, "name")

    loc = core.stamp_new({
        "account_id": account_id,
        "name": name,
        "physical_balance": 0,
        "equity_balance": 0,
        "equity_status": "BALANCED",
        "status": "OPEN",
    })
    db.locations[loc["id"]] = loc
    return object_response(core.public(loc), 201)


@bp.route("/locations/<location_id>", methods=["GET"])
def get_location(location_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    loc = core.require(db.locations, location_id)
    # Recompute physical_balance and equity_status on read (PRD §3.1).
    core.recompute_location_derived(loc)
    return object_response(core.public(loc), 200)


@bp.route("/locations", methods=["GET"])
def list_locations():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    account_id = request.args.get("account_id")
    items = list(db.locations.values())
    if account_id is not None:
        items = [l for l in items if l["account_id"] == account_id]
    # Recompute derived fields so list responses reflect current state.
    for l in items:
        core.recompute_location_derived(l)
    data, limit, offset, total = core.paginate(items, request.args)
    return array_response(data, limit, offset, total, 200)


@bp.route("/locations/<location_id>/close", methods=["POST"])
def close_location(location_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator"})
    loc = core.require(db.locations, location_id)
    if loc["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Location is not OPEN")
    # Requires zero balances (PRD §3.1) -> ERR_INVALID_STATE.
    core.recompute_physical_balance(loc)
    if loc["physical_balance"] != 0 or loc["equity_balance"] != 0:
        raise err("ERR_INVALID_STATE",
                  "Location must have zero physical_balance and equity_balance to close")
    loc["status"] = "CLOSED"
    core.recompute_equity_status(loc)
    core.touch(loc)
    return object_response(core.public(loc), 200)
