"""Config & setup routes: state-schedules, shops, storage-bins, clock (PRD §3.1, §3.11)."""
from flask import Blueprint, request

from db import store, iso, parse_iso
from errors import err
from middleware import require_auth
from models import base_record
from helpers import (
    get_body,
    as_int,
    as_int_nonneg,
    as_str,
    as_bool,
    as_enum,
    parse_pagination,
    paginate,
    sort_by_creation,
    serialize,
)
from response import success_object, success_array
from services.domain import rederive_grace

bp = Blueprint("config", __name__)

STATE_CODES = {"FL", "TX", "CA"}


# ---------------------------------------------------------------------------
# State rate schedules (PRD §3.1)
# ---------------------------------------------------------------------------
@bp.route("/pawn/state-schedules", methods=["POST"])
def create_state_schedule():
    require_auth(["ShopManager"])
    body = get_body()

    state_code = as_enum(body, "state_code", STATE_CODES)
    monthly_interest_bps = as_int_nonneg(body, "monthly_interest_bps")
    monthly_storage_fee_cents = as_int_nonneg(body, "monthly_storage_fee_cents")
    setup_fee_cents = as_int_nonneg(body, "setup_fee_cents")
    term_days = as_int(body, "term_days")
    grace_days = as_int_nonneg(body, "grace_days")
    max_principal_cents = as_int(body, "max_principal_cents")
    max_periods_total = as_int(body, "max_periods_total")
    loan_to_value_bps = as_int(body, "loan_to_value_bps")
    layaway_buffer_days = as_int_nonneg(body, "layaway_buffer_days")

    # Constraint well-formedness (priority 4 ERR_INVALID_REQUEST).
    if term_days <= 0:
        raise err("ERR_INVALID_REQUEST", "term_days must be > 0.")
    if max_principal_cents <= 0:
        raise err("ERR_INVALID_REQUEST", "max_principal_cents must be > 0.")
    if max_periods_total < 1:
        raise err("ERR_INVALID_REQUEST", "max_periods_total must be >= 1.")
    if loan_to_value_bps <= 0 or loan_to_value_bps > 10000:
        raise err("ERR_INVALID_REQUEST", "loan_to_value_bps must be in (0, 10000].")

    # Uniqueness of state_code (PRD §3.1 ERR_DUPLICATE_SCHEDULE).
    for s in store.state_schedules.values():
        if s["state_code"] == state_code:
            raise err("ERR_DUPLICATE_SCHEDULE", "A schedule already exists for this state.")

    rec = base_record({
        "state_code": state_code,
        "monthly_interest_bps": monthly_interest_bps,
        "monthly_storage_fee_cents": monthly_storage_fee_cents,
        "setup_fee_cents": setup_fee_cents,
        "term_days": term_days,
        "grace_days": grace_days,
        "max_principal_cents": max_principal_cents,
        "max_periods_total": max_periods_total,
        "loan_to_value_bps": loan_to_value_bps,
        "layaway_buffer_days": layaway_buffer_days,
    })
    store.state_schedules[rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.route("/pawn/state-schedules", methods=["GET"])
def list_state_schedules():
    require_auth(["ShopManager", "LoanOfficer", "Appraiser"])
    limit, offset = parse_pagination()
    state_code = request.args.get("state_code")
    items = list(store.state_schedules.values())
    if state_code is not None:
        items = [s for s in items if s["state_code"] == state_code]
    items = sort_by_creation(items)
    window, total = paginate(items, limit, offset)
    return success_array([serialize(s) for s in window], limit, offset, total)


# ---------------------------------------------------------------------------
# Shops (PRD §3.1, §2.8)
# ---------------------------------------------------------------------------
@bp.route("/pawn/shops", methods=["POST"])
def create_shop():
    require_auth(["ShopManager"])
    body = get_body()

    name = as_str(body, "name")
    state_code = as_enum(body, "state_code", STATE_CODES)
    police_reporting_enabled = as_bool(body, "police_reporting_enabled", True)

    shop = base_record({
        "name": name,
        "state_code": state_code,
        "police_reporting_enabled": police_reporting_enabled,
        "cash_drawer_id": None,
    })
    # Mint the 1:1 CashDrawer at balance 0 (PRD §2.8 / §3.1).
    drawer = base_record({
        "shop_id": shop["id"],
        "balance_cents": 0,
    })
    store.cash_drawers[drawer["id"]] = drawer
    shop["cash_drawer_id"] = drawer["id"]

    store.shops[shop["id"]] = shop
    return success_object(serialize(shop), 201)


@bp.route("/pawn/shops/<shop_id>", methods=["GET"])
def get_shop(shop_id):
    require_auth(["ShopManager", "LoanOfficer", "Appraiser"])
    shop = store.shops.get(shop_id)
    if shop is None:
        raise err("ERR_NOT_FOUND", "Shop not found.")
    return success_object(serialize(shop))


@bp.route("/pawn/shops/<shop_id>/drawer", methods=["GET"])
def get_shop_drawer(shop_id):
    require_auth(["ShopManager", "LoanOfficer"])
    shop = store.shops.get(shop_id)
    if shop is None:
        raise err("ERR_NOT_FOUND", "Shop not found.")
    limit, offset = parse_pagination()
    items = [d for d in store.cash_drawers.values() if d["shop_id"] == shop_id]
    items = sort_by_creation(items)
    window, total = paginate(items, limit, offset)
    return success_array([serialize(d) for d in window], limit, offset, total)


@bp.route("/pawn/shops/<shop_id>/loans", methods=["GET"])
def get_shop_loans(shop_id):
    require_auth(["ShopManager", "LoanOfficer", "Appraiser"])
    shop = store.shops.get(shop_id)
    if shop is None:
        raise err("ERR_NOT_FOUND", "Shop not found.")
    limit, offset = parse_pagination()
    items = [l for l in store.loans.values() if l["shop_id"] == shop_id]
    for l in items:
        rederive_grace(l)
    items = sort_by_creation(items)
    window, total = paginate(items, limit, offset)
    return success_array([serialize(l) for l in window], limit, offset, total)


@bp.route("/pawn/shops/<shop_id>/inventory", methods=["GET"])
def get_shop_inventory(shop_id):
    require_auth(["ShopManager", "LoanOfficer"])
    shop = store.shops.get(shop_id)
    if shop is None:
        raise err("ERR_NOT_FOUND", "Shop not found.")
    limit, offset = parse_pagination()
    items = [i for i in store.inventory_items.values() if i["shop_id"] == shop_id]
    items = sort_by_creation(items)
    window, total = paginate(items, limit, offset)
    return success_array([serialize(i) for i in window], limit, offset, total)


# ---------------------------------------------------------------------------
# Storage bins (PRD §3.1)
# ---------------------------------------------------------------------------
@bp.route("/pawn/storage-bins", methods=["POST"])
def create_storage_bin():
    require_auth(["ShopManager"])
    body = get_body()

    shop_id = as_str(body, "shop_id")
    label = as_str(body, "label")
    capacity = as_int(body, "capacity")
    if capacity < 1:
        raise err("ERR_INVALID_REQUEST", "capacity must be >= 1.")

    # FK existence (priority 3 ERR_NOT_FOUND).
    if shop_id not in store.shops:
        raise err("ERR_NOT_FOUND", "Shop not found.")

    rec = base_record({
        "shop_id": shop_id,
        "label": label,
        "capacity": capacity,
    })
    store.storage_bins[rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.route("/pawn/storage-bins/<bin_id>", methods=["GET"])
def get_storage_bin(bin_id):
    require_auth(["ShopManager", "LoanOfficer"])
    rec = store.storage_bins.get(bin_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Storage bin not found.")
    return success_object(serialize(rec))


@bp.route("/pawn/storage-bins", methods=["GET"])
def list_storage_bins():
    require_auth(["ShopManager", "LoanOfficer"])
    limit, offset = parse_pagination()
    shop_id = request.args.get("shop_id")
    items = list(store.storage_bins.values())
    if shop_id is not None:
        items = [b for b in items if b["shop_id"] == shop_id]
    items = sort_by_creation(items)
    window, total = paginate(items, limit, offset)
    return success_array([serialize(b) for b in window], limit, offset, total)


@bp.route("/pawn/storage-bins/<bin_id>/loans", methods=["GET"])
def get_bin_loans(bin_id):
    require_auth(["ShopManager", "LoanOfficer"])
    rec = store.storage_bins.get(bin_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Storage bin not found.")
    limit, offset = parse_pagination()
    items = [l for l in store.loans.values() if l["storage_bin_id"] == bin_id]
    for l in items:
        rederive_grace(l)
    items = sort_by_creation(items)
    window, total = paginate(items, limit, offset)
    return success_array([serialize(l) for l in window], limit, offset, total)


# ---------------------------------------------------------------------------
# Simulated clock (PRD §3.11)
# ---------------------------------------------------------------------------
@bp.route("/pawn/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth(["ShopManager"])
    body = get_body()
    to_iso8601 = as_str(body, "to_iso8601")
    dt = parse_iso(to_iso8601)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 timestamp.")
    store.set_clock(dt)
    return success_object({"current_utc": iso(store.now())})


@bp.route("/pawn/_clock", methods=["GET"])
def get_clock():
    require_auth(["ShopManager", "LoanOfficer"])
    return success_object({"current_utc": iso(store.now())})
