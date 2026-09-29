"""Store endpoints."""
from flask import Blueprint

import calc
import serial
import services
from core import (bad_request, db, ensure_object, fail, filter_str, get_body,
                  ok, ok_list, opt_bool, opt_int, opt_str, ordered, paginate,
                  mark, req_enum, req_int, req_str, require_auth,
                  resolve_body_ref, resolve_path, stamp_new)
from guards import ADMIN_OWNER, ALL_READ, check_state_code

bp = Blueprint("stores", __name__)

STORE_TYPES = ("SUPERMARKET", "GROCERY", "CONVENIENCE", "SPECIALTY",
               "FARMERS_MARKET", "MEAL_SERVICE")
STORE_READ_ROLES = ("FnsAdmin", "FnsAnalyst", "AdminReviewOfficer",
                    "RetailerOwner", "StoreClerk", "Inspector")


def _derive_sales(store):
    bps, passes = calc.criterion_b(store["annual_staple_sales_cents"],
                                   store["annual_gross_sales_cents"])
    store["staple_sales_bps"] = bps
    store["criterion_b_pass"] = passes


@bp.post("/stores")
def create_store():
    require_auth(ADMIN_OWNER)
    body = get_body()
    ensure_object(body)
    owner = resolve_body_ref(body, "owner_id", db.owners, "ERR_OWNER_NOT_FOUND")
    predecessor = resolve_body_ref(body, "predecessor_store_id", db.stores,
                                  "ERR_STORE_NOT_FOUND", optional=True)
    owner_id = req_str(body, "owner_id")
    store_name = req_str(body, "store_name")
    state_code = check_state_code(req_str(body, "state_code"))
    store_type = req_enum(body, "store_type", STORE_TYPES)
    lanes = req_int(body, "checkout_lane_count", minimum=0)
    shelf = req_int(body, "staple_shelf_linear_feet", minimum=0)
    gross = req_int(body, "annual_gross_sales_cents", minimum=1)
    staple = req_int(body, "annual_staple_sales_cents", minimum=0)
    if staple > gross:
        bad_request("Field 'annual_staple_sales_cents' must be <= "
                    "annual_gross_sales_cents.")
    slots = req_int(body, "max_terminal_slots", minimum=1)
    tax_rate_bps = opt_int(body, "tax_rate_bps", default=0, minimum=0,
                           maximum=2000)
    hardship = opt_bool(body, "hardship_designated", default=False)
    row = stamp_new({
        "owner_id": owner_id if owner is None else owner["id"],
        "predecessor_store_id": None if predecessor is None else predecessor["id"],
        "store_name": store_name,
        "state_code": state_code,
        "store_type": store_type,
        "checkout_lane_count": lanes,
        "staple_shelf_linear_feet": shelf,
        "annual_gross_sales_cents": gross,
        "annual_staple_sales_cents": staple,
        "max_terminal_slots": slots,
        "tax_rate_bps": tax_rate_bps,
        "hardship_designated": hardship,
        "fns_number": None,
        "authorization_status": "NOT_AUTHORIZED",
        "sanction_status": "NONE",
        "authorized_at": None,
        "disqualified_until": None,
        "permanently_disqualified": False,
        "redemption_flag_level": "FLAG_L0",
        "active_terminal_count": 0,
    })
    _derive_sales(row)
    db.stores[row["id"]] = row
    return ok(serial.store(row), 201)


@bp.get("/stores/<store_id>")
def get_store(store_id):
    require_auth(STORE_READ_ROLES)
    row = resolve_path(db.stores, store_id, "ERR_STORE_NOT_FOUND")
    return ok(serial.store(row))


@bp.get("/stores")
def list_stores():
    require_auth(ALL_READ)
    rows = ordered(list(db.stores.values()))
    for name in ("owner_id", "predecessor_store_id", "authorization_status",
                 "sanction_status", "state_code", "store_type",
                 "redemption_flag_level"):
        value = filter_str(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    data, pagination = paginate(rows, serial.store)
    return ok_list(data, pagination)


@bp.patch("/stores/<store_id>")
def patch_store(store_id):
    require_auth(ADMIN_OWNER)
    store = resolve_path(db.stores, store_id, "ERR_STORE_NOT_FOUND")
    body = get_body()
    ensure_object(body)
    expected = req_int(body, "expected_store_version")
    store_name = opt_str(body, "store_name", default=None, allow_empty=False)
    lanes = opt_int(body, "checkout_lane_count", minimum=0)
    shelf = opt_int(body, "staple_shelf_linear_feet", minimum=0)
    gross = opt_int(body, "annual_gross_sales_cents", minimum=1)
    staple = opt_int(body, "annual_staple_sales_cents", minimum=0)
    slots = opt_int(body, "max_terminal_slots", minimum=1)
    tax_rate_bps = opt_int(body, "tax_rate_bps", minimum=0, maximum=2000)
    hardship = opt_bool(body, "hardship_designated")
    new_gross = gross if gross is not None else store["annual_gross_sales_cents"]
    new_staple = (staple if staple is not None
                  else store["annual_staple_sales_cents"])
    if new_staple > new_gross:
        bad_request("Field 'annual_staple_sales_cents' must be <= "
                    "annual_gross_sales_cents.")
    if expected != store["version"]:
        fail("ERR_STALE_STORE_VERSION")
    if store_name is not None:
        store["store_name"] = store_name
    if lanes is not None:
        store["checkout_lane_count"] = lanes
    if shelf is not None:
        store["staple_shelf_linear_feet"] = shelf
    store["annual_gross_sales_cents"] = new_gross
    store["annual_staple_sales_cents"] = new_staple
    if slots is not None:
        store["max_terminal_slots"] = slots
    if tax_rate_bps is not None:
        store["tax_rate_bps"] = tax_rate_bps
    if hardship is not None:
        store["hardship_designated"] = hardship
    _derive_sales(store)
    mark(store)
    services.commit()
    return ok(serial.store(store))


@bp.post("/stores/<store_id>/withdraw")
def withdraw_store(store_id):
    require_auth(ADMIN_OWNER)
    store = resolve_path(db.stores, store_id, "ERR_STORE_NOT_FOUND")
    if store["authorization_status"] != "AUTHORIZED":
        fail("ERR_INVALID_STATE")
    if store["sanction_status"] in ("CHARGED", "UNDER_ADMIN_REVIEW",
                                   "SANCTION_FINAL"):
        fail("ERR_INVALID_STATE")
    store["authorization_status"] = "WITHDRAWN"
    mark(store)
    services.release_open_deployments_for_withdrawal(store)
    services.commit()
    return ok(serial.store(store))
