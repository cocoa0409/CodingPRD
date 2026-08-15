"""Order routes: place, get, list, confirm, cancel, schedule loads."""

from decimal import Decimal

from flask import Blueprint

import clock
import errors
import middleware as mw
import response
from db import stores
from routes.catalog import get_or_404, request_args
from services import calc

bp = Blueprint("orders", __name__)

CUSTOMER = ["Customer"]
DISPATCHER = ["Dispatcher"]
CANCEL_ROLES = ["Customer", "Dispatcher"]


@bp.post("/v1/orders")
def create_order():
    user_id, _ = mw.require_auth(CUSTOMER)
    body = mw.get_json_body()
    plant_id = mw.require_string(body, "plant_id")
    get_or_404("plants", plant_id)
    mix_design_id = mw.require_string(body, "mix_design_id")
    mix = get_or_404("mix_designs", mix_design_id)
    qty_yd3 = mw.require_number(body, "qty_yd3")
    pour_date = mw.require_date(body, "pour_date")
    pour_window_start = mw.require_hhmm(body, "pour_window_start")
    pour_window_end = mw.require_hhmm(body, "pour_window_end")
    slump_in = mw.require_number(body, "slump_in")
    # Slump tolerance (+/-1.0 in, inclusive) — referential check.
    if abs(mw.dec(slump_in) - mw.dec(mix["slump_in"])) > Decimal("1.0"):
        raise errors.err_slump()
    # Pour window ordering — temporal check.
    if not pour_window_end > pour_window_start:
        raise errors.err_window()
    # Pour date not before the current logical-clock date.
    if pour_date < clock.now().strftime("%Y-%m-%d"):
        raise errors.err_pour_date_past()
    rec = mw.new_record()
    rec["customer_id"] = user_id
    rec["plant_id"] = plant_id
    rec["mix_design_id"] = mix_design_id
    rec["price_list_id"] = None
    rec["qty_yd3"] = qty_yd3
    rec["pour_date"] = pour_date
    rec["pour_window_start"] = pour_window_start
    rec["pour_window_end"] = pour_window_end
    rec["slump_in"] = slump_in
    rec["delivery_status"] = "PLACED"
    rec["billing_status"] = "UNPRICED"
    rec["delivered_qty_yd3"] = 0
    rec["escalated_base_cents"] = None
    rec["provisional_total_cents"] = None
    stores["orders"][rec["id"]] = rec
    return response.success_object(rec, 201)


@bp.get("/v1/orders/<rid>")
def get_order(rid):
    user_id, role = mw.require_auth(mw.ALL_ROLES)
    rec = get_or_404("orders", rid)
    if role == "Customer" and rec["customer_id"] != user_id:
        raise errors.err_ownership()
    return response.success_object(rec)


@bp.get("/v1/orders")
def list_orders():
    mw.require_auth(mw.ALL_ROLES)
    limit, offset = mw.parse_pagination()
    items = list(stores["orders"].values())
    args = request_args()
    for field in ("customer_id", "plant_id", "mix_design_id", "price_list_id",
                  "delivery_status", "billing_status"):
        v = mw.optional_string(args, field)
        if v is not None:
            items = [o for o in items if o.get(field) == v]
    page, total = mw.sort_and_page(items, limit, offset)
    return response.success_array(page, limit, offset, total)


@bp.post("/v1/orders/<rid>/confirm")
def confirm_order(rid):
    mw.require_auth(DISPATCHER)
    rec = get_or_404("orders", rid)
    if rec["delivery_status"] in ("DELIVERED", "CANCELLED"):
        raise errors.err_already_terminal()
    if rec["delivery_status"] != "PLACED":
        raise errors.err_invalid_state()
    customer = stores["customers"].get(rec["customer_id"])
    if customer is None:
        raise errors.err_not_found("Customer does not exist")
    if customer["credit_status"] == "HOLD":
        raise errors.err_credit_hold()
    mix = get_or_404("mix_designs", rec["mix_design_id"])
    if mix["status"] != "ACTIVE":
        raise errors.err_mix_not_active()
    active_lists = [p for p in stores["price_lists"].values()
                    if p["plant_id"] == rec["plant_id"]
                    and p["mix_design_id"] == rec["mix_design_id"]
                    and p["status"] == "ACTIVE"]
    if len(active_lists) != 1:
        raise errors.err_price_list_missing()
    if rec["pour_date"] < clock.now().strftime("%Y-%m-%d"):
        raise errors.err_pour_date_past()
    price_list = active_lists[0]
    rec["price_list_id"] = price_list["id"]
    rec["delivery_status"] = "CONFIRMED"
    rec["billing_status"] = "PRICED"
    base, total = calc.compute_provisional_quote(rec, price_list)
    rec["escalated_base_cents"] = base
    rec["provisional_total_cents"] = total
    mw.touch(rec)
    if calc.recompute_credit_exposure(customer):
        mw.touch(customer)
    return response.success_object(rec)


@bp.post("/v1/orders/<rid>/cancel")
def cancel_order(rid):
    user_id, role = mw.require_auth(CANCEL_ROLES)
    rec = get_or_404("orders", rid)
    if role == "Customer" and rec["customer_id"] != user_id:
        raise errors.err_ownership()
    if rec["delivery_status"] in ("DELIVERED", "CANCELLED"):
        raise errors.err_already_terminal()
    if rec["delivery_status"] in ("CONFIRMED", "SCHEDULED", "IN_PROGRESS"):
        active = [l for l in stores["loads"].values()
                  if l["order_id"] == rec["id"]
                  and l["status"] in ("SCHEDULED", "BATCHED", "EN_ROUTE", "ON_SITE", "POURING")]
        if active:
            raise errors.err_order_has_active_loads()
    rec["delivery_status"] = "CANCELLED"
    rec["billing_status"] = "VOID"
    mw.touch(rec)
    # Invoice still DRAFT -> VOID automatically.
    for inv in stores["invoices"].values():
        if inv["order_id"] == rec["id"] and inv["status"] == "DRAFT":
            inv["status"] = "VOID"
            mw.touch(inv)
    customer = stores["customers"].get(rec["customer_id"])
    if customer is not None and calc.recompute_credit_exposure(customer):
        mw.touch(customer)
    return response.success_object(rec)


# -------------------------------------------------------------- scheduling

@bp.post("/v1/orders/<rid>/loads")
def schedule_load(rid):
    mw.require_auth(DISPATCHER)
    order = get_or_404("orders", rid)
    body = mw.get_json_body()
    qty_yd3 = mw.require_number(body, "qty_yd3")
    expected_order_version = mw.require_int(body, "expected_order_version")
    truck_id = mw.optional_string(body, "truck_id")
    truck = None
    if truck_id is not None:
        truck = get_or_404("trucks", truck_id)
    if order["delivery_status"] in ("DELIVERED", "CANCELLED"):
        raise errors.err_already_terminal()
    if order["delivery_status"] not in ("CONFIRMED", "SCHEDULED", "IN_PROGRESS"):
        raise errors.err_invalid_state()
    if expected_order_version != order["version"]:
        raise errors.err_stale_version()
    price_list = stores["price_lists"].get(order["price_list_id"])
    if price_list is None:
        raise errors.err_not_found("Price list does not exist")
    customer = stores["customers"].get(order["customer_id"])
    if truck is not None:
        if truck["status"] != "AVAILABLE":
            raise errors.err_truck_not_available()
        if mw.dec(qty_yd3) > mw.dec(truck["capacity_yd3"]):
            raise errors.err_truck_capacity()
    else:
        candidates = [t for t in stores["trucks"].values()
                      if t["plant_id"] == order["plant_id"]
                      and t["status"] == "AVAILABLE"
                      and mw.dec(t["capacity_yd3"]) >= mw.dec(qty_yd3)]
        if not candidates:
            raise errors.err_no_truck_available()
        candidates.sort(key=lambda t: (t["last_available_at"], t["created_at"], t["id"]))
        truck = candidates[0]
    if mw.dec(qty_yd3) < mw.dec(price_list["min_load_yd3"]) \
            and customer is not None and not customer["short_load_allowed"]:
        raise errors.err_short_load_forbidden()
    rec = mw.new_record()
    rec["order_id"] = order["id"]
    rec["truck_id"] = truck["id"]
    rec["plant_id"] = order["plant_id"]
    rec["qty_yd3"] = qty_yd3
    rec["status"] = "SCHEDULED"
    rec["batch_time"] = None
    rec["arrival_time"] = None
    rec["complete_time"] = None
    rec["on_site_minutes"] = None
    rec["discharged_qty_yd3"] = 0
    rec["returned_qty_yd3"] = 0
    rec["actual_wc_ratio"] = None
    rec["over_watered"] = False
    rec["strength_liability"] = "NONE"
    rec["concrete_cents"] = None
    rec["short_load_fee_cents"] = None
    rec["wait_fee_cents"] = None
    rec["saturday_fee_cents"] = None
    rec["final_charge_cents"] = None
    stores["loads"][rec["id"]] = rec
    # Each schedule bumps the order version; first load CONFIRMED -> SCHEDULED.
    if order["delivery_status"] == "CONFIRMED":
        order["delivery_status"] = "SCHEDULED"
    mw.touch(order)
    return response.success_object(rec, 201)
