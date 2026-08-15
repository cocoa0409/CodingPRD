"""DepositAccount endpoints."""

from flask import Blueprint, request
from middleware import require_role, ALL_ROLES
from response import success_object, success_list
from errors import *
from db import store
from services.helpers import (
    require_fields, require_str, require_int,
    make_entity, touch, get_production, get_location, get_scoped,
    list_filtered, paginate, get_pagination_params, parse_date,
)
from services.calculations import deposit_required, calendar_days_in_window, deposit_waterfall

bp = Blueprint("deposits", __name__)


def _find_executed_agreement(production_id, location_id):
    for oa in store.owner_agreements.values():
        if (oa.get("production_id") == production_id
                and oa.get("location_id") == location_id
                and oa["status"] == "EXECUTED"):
            return oa
    return None


def _compute_required(production_id, location_id):
    """Compute required_amount_cents: uses agreement if EXECUTED, else deposit_floor_cents."""
    loc = get_location(location_id)
    oa = _find_executed_agreement(production_id, location_id)
    if oa:
        shoot_days = calendar_days_in_window(
            parse_date(oa["shoot_start_date"]),
            parse_date(oa["shoot_end_date"])
        )
        return deposit_required(loc["deposit_floor_cents"], oa["agreed_day_rate_cents"], shoot_days)
    return loc["deposit_floor_cents"]


@bp.route("/productions/<pid>/deposit-accounts", methods=["POST"])
def create_deposit_account(pid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["location_id"])
    loc_id = require_str(payload, "location_id")
    get_location(loc_id)
    # Unique per (production, location)
    for da in store.deposit_accounts.values():
        if da.get("production_id") == pid and da.get("location_id") == loc_id:
            raise ApiError(ERR_INVALID_REQUEST, "Deposit account already exists for this location", 400)
    required = _compute_required(pid, loc_id)
    entity = make_entity({
        "production_id": pid,
        "location_id": loc_id,
        "required_amount_cents": required,
        "held_amount_cents": 0,
        "claimed_amount_cents": 0,
        "released_amount_cents": 0,
        "status": "OPEN",
    })
    store.deposit_accounts[entity["id"]] = entity
    return success_object(entity, 201)


@bp.route("/productions/<pid>/deposit-accounts", methods=["GET"])
def list_deposit_accounts(pid):
    user_id, role = require_role(*ALL_ROLES)
    p = get_production(pid)
    limit, offset = get_pagination_params(request.args)
    filters = {}
    for f in ("location_id", "status"):
        v = request.args.get(f)
        if v:
            filters[f] = v
    items = list_filtered(store.deposit_accounts, filters, production_id=pid)
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/productions/<pid>/deposit-accounts/<rid>", methods=["GET"])
def get_deposit_account(pid, rid):
    user_id, role = require_role(*ALL_ROLES)
    p = get_production(pid)
    da = get_scoped(store.deposit_accounts, rid, pid, "DepositAccount")
    return success_object(da)


@bp.route("/productions/<pid>/deposit-accounts/<rid>/deposit", methods=["POST"])
def deposit_funds(pid, rid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    da = get_scoped(store.deposit_accounts, rid, pid, "DepositAccount")
    if da["status"] not in ("OPEN", "FUNDED"):
        raise ApiError(ERR_INVALID_STATE, "Cannot deposit to account in current state", 409)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["amount_cents"])
    amount = require_int(payload, "amount_cents")
    da["held_amount_cents"] = da.get("held_amount_cents", 0) + amount
    if da["held_amount_cents"] >= da["required_amount_cents"] and da["status"] == "OPEN":
        da["status"] = "FUNDED"
    touch(da)
    return success_object(da)


@bp.route("/productions/<pid>/deposit-accounts/<rid>/settle", methods=["POST"])
def settle_deposit_account(pid, rid):
    user_id, role = require_role("FilmOffice")
    p = get_production(pid)
    da = get_scoped(store.deposit_accounts, rid, pid, "DepositAccount")
    if da["status"] != "SETTLING":
        raise ApiError(ERR_INVALID_STATE, "Deposit account is not SETTLING", 409)
    # Check POST walkthrough not DISPUTED
    for wt in store.walkthrough_reports.values():
        if (wt.get("production_id") == pid
                and wt.get("location_id") == da["location_id"]
                and wt.get("kind") == "POST"
                and wt["status"] == "DISPUTED"):
            raise ApiError(ERR_WALKTHROUGH_DISPUTED, "POST walkthrough is DISPUTED", 422)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["awarded_claim_cents"])
    awarded = require_int(payload, "awarded_claim_cents")
    unreleased = da["held_amount_cents"] - da["released_amount_cents"]
    if awarded > unreleased:
        raise ApiError(ERR_CLAIM_EXCEEDS_DEPOSIT, "Award exceeds unreleased balance", 422)
    claimed_delta, released_delta = deposit_waterfall(
        da["held_amount_cents"], da["released_amount_cents"], awarded
    )
    da["claimed_amount_cents"] += claimed_delta
    da["released_amount_cents"] += released_delta
    da["status"] = "CLOSED"
    touch(da)
    # POST walkthrough -> FINAL
    for wt in store.walkthrough_reports.values():
        if (wt.get("production_id") == pid
                and wt.get("location_id") == da["location_id"]
                and wt.get("kind") == "POST"
                and wt["status"] in ("SIGNED", "DISPUTED")):
            wt["status"] = "FINAL"
            touch(wt)
    return success_object(da)
