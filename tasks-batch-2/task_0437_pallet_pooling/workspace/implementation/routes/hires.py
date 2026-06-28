"""Hire routes (PRD §3.4 hiring/charge, §3.5 credit exposure).

Validation ordering for POST /hires (PRD §2.10 + §3.4):
  auth -> role -> existence -> body well-formed -> OCC (ERR_STALE_VERSION)
  -> [state] -> business preconditions (account ACTIVE, asset AVAILABLE,
  asset location, credit limit).
"""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_auth, require_roles, get_json_body
from response import object_response, array_response
from services import core

bp = Blueprint("hires", __name__)


@bp.route("/hires", methods=["POST"])
def open_hire():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    body = get_json_body()

    # Existence first (priority 3, PRD §2.10): resolve present body FKs
    # left-to-right before body well-formedness (priority 4).
    core.resolve_body_fk(body, "account_id", db.accounts)
    core.resolve_body_fk(body, "location_id", db.locations)
    core.resolve_body_fk(body, "asset_type_id", db.asset_types)
    core.resolve_body_fk_list(body, "asset_ids", db.assets)

    # Body well-formedness (priority 4, PRD §2.10).
    core.require_fields(body, ["account_id", "location_id", "asset_type_id",
                              "asset_ids", "expected_location_version"])
    account_id = core.require_str(body, "account_id")
    location_id = core.require_str(body, "location_id")
    asset_type_id = core.require_str(body, "asset_type_id")
    # asset_ids must be non-empty for hires (PRD §2.10).
    asset_ids = core.require_id_list(body, "asset_ids", allow_empty=False)
    expected_version = core.require_int(body, "expected_location_version")

    account = db.accounts[account_id]
    location = db.locations[location_id]
    asset_type = db.asset_types[asset_type_id]

    # OCC against Location.version (PRD §2.9, priority 5) -> ERR_STALE_VERSION.
    if expected_version != location["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_location_version does not match current location version")

    # Business referential: hiring account must be ACTIVE (PRD §3.4).
    if account["status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_NOT_ACTIVE", "Hiring account is not ACTIVE")

    # Asset eligibility: every asset AVAILABLE and physically at location (PRD §3.4).
    for aid in asset_ids:
        a = db.assets[aid]
        if a["condition"] != "AVAILABLE":
            raise err("ERR_ASSET_NOT_AVAILABLE", "Asset %s is not AVAILABLE" % aid)
        if a["current_location_id"] != location_id:
            raise err("ERR_ASSET_WRONG_LOCATION",
                      "Asset %s is not at the hire location" % aid)

    # Credit-limit gate (PRD §3.5): exposure = outstanding (pre-open) + day-1
    # reservation = 1 * len(asset_ids) * tiered_daily_rate(len(asset_ids), base).
    # Rejected only when exposure > credit_limit_cents; equality is allowed.
    core.recompute_account_outstanding(account)
    n = len(asset_ids)
    day1_rate = core.tiered_daily_rate(n, asset_type["base_daily_rate_cents"])
    day1_reservation = 1 * n * day1_rate
    exposure = account["outstanding_charge_cents"] + day1_reservation
    if exposure > account["credit_limit_cents"]:
        raise err("ERR_CREDIT_LIMIT_EXCEEDED",
                  "Opening the hire would exceed the account credit limit")

    # Commit (PRD §3.4).
    hire = core.stamp_new({
        "account_id": account_id,
        "location_id": location_id,
        "asset_type_id": asset_type_id,
        "asset_ids": list(asset_ids),
        "on_hire_at": db.iso_clock(),
        "off_hire_at": None,
        "expected_location_version": expected_version,
        "accrued_charge_cents": 0,
        "final_charge_cents": None,
        "lifecycle_status": "OPEN",
        "settlement_status": "UNBILLED",
        "_damage_at": {},
    })
    db.hires[hire["id"]] = hire
    # Assets AVAILABLE -> ON_HIRE, current_hire_id set (PRD §3.4).
    for aid in asset_ids:
        a = db.assets[aid]
        a["condition"] = "ON_HIRE"
        a["current_hire_id"] = hire["id"]
        core.touch(a)
    # Location.version incremented by one (PRD §3.4).
    core.touch(location)
    # accrued_charge_cents + account outstanding recomputed (PRD §3.4).
    core.recompute_hire_accrued(hire)
    core.recompute_account_outstanding(account)
    return object_response(core.public(hire), 201)


@bp.route("/hires/<hire_id>", methods=["GET"])
def get_hire(hire_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    hire = core.require(db.hires, hire_id)
    # accrued_charge_cents recomputed on read while OPEN (PRD §3.4).
    core.recompute_hire_accrued(hire)
    return object_response(core.public(hire), 200)


@bp.route("/hires", methods=["GET"])
def list_hires():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    items = list(db.hires.values())
    for field in ("account_id", "location_id", "asset_type_id",
                  "lifecycle_status", "settlement_status"):
        val = request.args.get(field)
        if val is not None:
            items = [h for h in items if h[field] == val]
    for h in items:
        core.recompute_hire_accrued(h)
    data, limit, offset, total = core.paginate(items, request.args)
    return array_response(data, limit, offset, total, 200)


@bp.route("/hires/<hire_id>/close", methods=["POST"])
def close_hire(hire_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    hire = core.require(db.hires, hire_id)
    # Permitted only from OPEN (PRD §3.4) -> ERR_INVALID_STATE.
    if hire["lifecycle_status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Hire is not OPEN")
    # off_hire_at stamped, final_charge_cents pinned via chronological replay.
    hire["off_hire_at"] = db.iso_clock()
    hire["final_charge_cents"] = core.hire_final_charge(hire)
    # Each asset still ON_HIRE -> AVAILABLE, current_hire_id cleared (PRD §3.4).
    for aid in hire["asset_ids"]:
        a = db.assets.get(aid)
        if a is not None and a["condition"] == "ON_HIRE" and a["current_hire_id"] == hire_id:
            a["condition"] = "AVAILABLE"
            a["current_hire_id"] = None
            core.touch(a)
    hire["lifecycle_status"] = "CLOSED"
    core.touch(hire)
    # Recompute account outstanding (PRD §3.4/§3.5).
    acc = db.accounts.get(hire["account_id"])
    if acc is not None:
        core.recompute_account_outstanding(acc)
    return object_response(core.public(hire), 200)


@bp.route("/hires/<hire_id>/void", methods=["POST"])
def void_hire(hire_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin"})
    hire = core.require(db.hires, hire_id)
    # Only while OPEN (state) and settlement UNBILLED (PRD §3.4).
    if hire["lifecycle_status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Hire is not OPEN")
    if hire["settlement_status"] != "UNBILLED":
        raise err("ERR_HIRE_ALREADY_INVOICED",
                  "Hire settlement_status is not UNBILLED")
    # Each ON_HIRE asset -> AVAILABLE, current_hire_id cleared (PRD §3.4).
    for aid in hire["asset_ids"]:
        a = db.assets.get(aid)
        if a is not None and a["condition"] == "ON_HIRE" and a["current_hire_id"] == hire_id:
            a["condition"] = "AVAILABLE"
            a["current_hire_id"] = None
            core.touch(a)
    # Compensating reversal: zero charges (PRD §3.4).
    hire["accrued_charge_cents"] = 0
    hire["final_charge_cents"] = 0
    hire["lifecycle_status"] = "VOIDED"
    core.touch(hire)
    acc = db.accounts.get(hire["account_id"])
    if acc is not None:
        core.recompute_account_outstanding(acc)
    return object_response(core.public(hire), 200)
