"""Load routes: lifecycle, batch, delivery events, complete/return/washout,
water additions, batch ticket, cylinder sets."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import clock
import errors
import middleware as mw
import response
from db import stores
from routes.catalog import get_or_404, request_args
from services import calc

bp = Blueprint("loads", __name__)

BATCH_OP = ["BatchOperator"]
DRIVER = ["Driver"]
QCTECH = ["QCTech"]
DISPATCHER = ["Dispatcher"]

RETURNABLE_STATES = ("BATCHED", "EN_ROUTE", "ON_SITE", "POURING")
COMPLETABLE_STATES = ("ON_SITE", "POURING")
CASTABLE_STATES = ("ON_SITE", "POURING", "COMPLETED")
TERMINAL_STATES = ("COMPLETED", "WASHED_OUT", "CANCELLED")


@bp.get("/v1/loads/<rid>")
def get_load(rid):
    mw.require_auth(mw.ALL_ROLES)
    return response.success_object(get_or_404("loads", rid))


@bp.get("/v1/loads")
def list_loads():
    mw.require_auth(mw.ALL_ROLES)
    limit, offset = mw.parse_pagination()
    items = list(stores["loads"].values())
    args = request_args()
    for field in ("order_id", "truck_id", "plant_id", "status"):
        v = mw.optional_string(args, field)
        if v is not None:
            items = [l for l in items if l.get(field) == v]
    page, total = mw.sort_and_page(items, limit, offset)
    return response.success_array(page, limit, offset, total)


# ------------------------------------------------------------------ batch

@bp.post("/v1/loads/<rid>/batch")
def batch_load(rid):
    mw.require_auth(BATCH_OP)
    load = get_or_404("loads", rid)
    body = mw.get_json_body()
    if load["status"] in TERMINAL_STATES:
        raise errors.err_already_terminal()
    if load["status"] != "SCHEDULED":
        raise errors.err_invalid_state()
    order = get_or_404("orders", load["order_id"])
    if order["delivery_status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise errors.err_invalid_state()
    mix = get_or_404("mix_designs", order["mix_design_id"])
    if mix["status"] != "ACTIVE":
        raise errors.err_mix_not_active()
    truck = get_or_404("trucks", load["truck_id"])
    if truck["status"] != "AVAILABLE":
        raise errors.err_truck_not_available()
    plant = get_or_404("plants", load["plant_id"])
    if "batch_time" in body and body["batch_time"] is not None:
        if not isinstance(body["batch_time"], str):
            raise errors.err_validation("batch_time must be an ISO 8601 timestamp")
        try:
            batch_time = clock.parse_iso(body["batch_time"])
        except (ValueError, TypeError):
            raise errors.err_validation("batch_time must be an ISO 8601 timestamp")
    else:
        batch_time = clock.now()
    extra_batch_water_gal = mw.optional_number(body, "extra_batch_water_gal", 0)

    # Batch weights (pinned order) and the w/c safety ceiling.
    ticket_calc = calc.compute_batch_ticket(mix, load["qty_yd3"], extra_batch_water_gal)
    cement_lb = Decimal(str(ticket_calc["cement_lb"]))
    wc = calc.d(ticket_calc["batch_water_lb"]) / cement_lb
    if wc > calc.d(mix["max_wc_ratio"]):
        raise errors.err_wc_ratio()

    # Plant batch interval: half-open [batch_time, batch_time + cycle).
    interval_end = batch_time + timedelta(minutes=int(plant["batch_cycle_minutes"]))
    for other in stores["loads"].values():
        if other["id"] == load["id"] or other["plant_id"] != plant["id"]:
            continue
        if other["status"] not in ("BATCHED", "EN_ROUTE", "ON_SITE", "POURING"):
            continue
        if other.get("batch_time") is None:
            continue
        o_start = clock.parse_iso(other["batch_time"])
        o_end = o_start + timedelta(minutes=int(plant["batch_cycle_minutes"]))
        if batch_time < o_end and o_start < interval_end:
            raise errors.err_plant_batch_conflict()

    # Truck turnaround: batch_time >= latest prior batch_time + 90 min (closed).
    prior = [l for l in stores["loads"].values()
             if l["truck_id"] == truck["id"] and l["id"] != load["id"]
             and l["status"] != "CANCELLED" and l.get("batch_time") is not None]
    if prior:
        latest = max(clock.parse_iso(l["batch_time"]) for l in prior)
        if batch_time < latest + timedelta(minutes=90):
            raise errors.err_truck_overlap()

    load["status"] = "BATCHED"
    load["batch_time"] = clock.iso(batch_time)
    ticket = mw.new_record(common=False)
    ticket["load_id"] = load["id"]
    existing = [t for t in stores["batch_tickets"].values()
                if stores["loads"].get(t["load_id"], {}).get("plant_id") == plant["id"]]
    ticket["ticket_number"] = len(existing) + 1
    ticket["cement_lb"] = ticket_calc["cement_lb"]
    ticket["batch_water_lb"] = ticket_calc["batch_water_lb"]
    ticket["extra_batch_water_gal"] = ticket_calc["extra_batch_water_gal"]
    ticket["admixture_doses"] = ticket_calc["admixture_doses"]
    ticket["total_admixture_oz"] = ticket_calc["total_admixture_oz"]
    stores["batch_tickets"][ticket["id"]] = ticket

    load["actual_wc_ratio"] = calc.compute_actual_wc(ticket, load["id"])
    load["over_watered"] = calc.d(load["actual_wc_ratio"]) > calc.d(mix["max_wc_ratio"])
    if load["over_watered"] and load["strength_liability"] == "NONE":
        calc.apply_water_liability(load)
    mw.touch(load)

    truck["status"] = "ON_DELIVERY"
    mw.touch(truck)

    first_batched = not any(
        l["order_id"] == order["id"] and l["id"] != load["id"]
        and l["status"] in ("BATCHED", "EN_ROUTE", "ON_SITE", "POURING", "COMPLETED",
                            "RETURNED", "WASHED_OUT")
        for l in stores["loads"].values()
    )
    if first_batched and order["delivery_status"] == "SCHEDULED":
        order["delivery_status"] = "IN_PROGRESS"
        mw.touch(order)
    return response.success_object(load)


# ----------------------------------------------------------- delivery events

def _simple_transition(rid, from_states, to_state, mutate=None):
    load = get_or_404("loads", rid)
    if load["status"] in TERMINAL_STATES:
        raise errors.err_already_terminal()
    if load["status"] not in from_states:
        raise errors.err_invalid_state()
    load["status"] = to_state
    if mutate:
        mutate(load)
    mw.touch(load)
    return response.success_object(load)


@bp.post("/v1/loads/<rid>/depart")
def depart(rid):
    mw.require_auth(DRIVER)
    return _simple_transition(rid, ("BATCHED",), "EN_ROUTE")


@bp.post("/v1/loads/<rid>/arrive")
def arrive(rid):
    mw.require_auth(DRIVER)
    def _stamp(load):
        load["arrival_time"] = clock.iso(clock.now())
    return _simple_transition(rid, ("EN_ROUTE",), "ON_SITE", _stamp)


@bp.post("/v1/loads/<rid>/start-pour")
def start_pour(rid):
    mw.require_auth(DRIVER)
    return _simple_transition(rid, ("ON_SITE",), "POURING")


# --------------------------------------------------------------- complete

@bp.post("/v1/loads/<rid>/complete")
def complete(rid):
    mw.require_auth(DRIVER)
    load = get_or_404("loads", rid)
    body = mw.get_json_body()
    discharged = mw.require_number(body, "discharged_qty_yd3")
    if load["status"] in TERMINAL_STATES:
        raise errors.err_already_terminal()
    if load["status"] not in COMPLETABLE_STATES:
        raise errors.err_invalid_state()
    if mw.dec(discharged) != mw.dec(load["qty_yd3"]):
        raise errors.err_volume()
    order = get_or_404("orders", load["order_id"])
    price_list = get_or_404("price_lists", order["price_list_id"])
    customer = get_or_404("customers", order["customer_id"])
    truck = get_or_404("trucks", load["truck_id"])

    load["discharged_qty_yd3"] = discharged
    load["complete_time"] = clock.iso(clock.now())
    arrival = clock.parse_iso(load["arrival_time"])
    complete_time = clock.now()
    load["on_site_minutes"] = int((complete_time - arrival).total_seconds() // 60)
    charges = calc.compute_final_charge(load, order, price_list)
    load["concrete_cents"] = charges["concrete_cents"]
    load["short_load_fee_cents"] = charges["short_load_fee_cents"]
    load["wait_fee_cents"] = charges["wait_fee_cents"]
    load["saturday_fee_cents"] = charges["saturday_fee_cents"]
    load["final_charge_cents"] = charges["final_charge_cents"]
    load["status"] = "COMPLETED"
    mw.touch(load)

    truck["status"] = "AVAILABLE"
    truck["last_available_at"] = clock.iso(clock.now())
    mw.touch(truck)

    calc.recompute_delivered_qty(order)
    if calc.d(order["delivered_qty_yd3"]) >= calc.d(order["qty_yd3"]) \
            and order["delivery_status"] in ("SCHEDULED", "IN_PROGRESS"):
        order["delivery_status"] = "DELIVERED"
        invoice = mw.new_record()
        invoice["order_id"] = order["id"]
        invoice["customer_id"] = order["customer_id"]
        line_items = []
        for l in stores["loads"].values():
            if l["order_id"] == order["id"] and l["status"] == "COMPLETED":
                line_items.append({
                    "kind": "LOAD",
                    "description": f"Load {l['id']}",
                    "amount_cents": l["final_charge_cents"],
                })
        line_items.sort(key=lambda li: stores["loads"].get(
            next(k for k, v in stores["loads"].items() if v["id"] == li["description"].split(" ", 1)[1]), {}
        ).get("created_at", ""))
        invoice["line_items"] = line_items
        invoice["total_cents"] = sum(li["amount_cents"] for li in line_items)
        invoice["status"] = "DRAFT"
        invoice["issued_at"] = None
        stores["invoices"][invoice["id"]] = invoice
    mw.touch(order)
    if calc.recompute_credit_exposure(customer):
        mw.touch(customer)
    return response.success_object(load)


# ----------------------------------------------------------------- cancel

@bp.post("/v1/loads/<rid>/cancel")
def cancel_load(rid):
    mw.require_auth(DISPATCHER)
    load = get_or_404("loads", rid)
    if load["status"] in TERMINAL_STATES:
        raise errors.err_already_terminal()
    if load["status"] != "SCHEDULED":
        raise errors.err_invalid_state()
    load["status"] = "CANCELLED"
    mw.touch(load)
    return response.success_object(load)


# ----------------------------------------------------------------- return

@bp.post("/v1/loads/<rid>/return")
def return_load(rid):
    mw.require_auth(DRIVER)
    load = get_or_404("loads", rid)
    body = mw.get_json_body()
    discharged = mw.require_number(body, "discharged_qty_yd3")
    returned = mw.require_number(body, "returned_qty_yd3")
    disposition = mw.require_string(body, "disposition")
    if disposition not in ("DUMPED", "RECYCLED", "FILL"):
        raise errors.err_validation("disposition must be DUMPED, RECYCLED, or FILL")
    if load["status"] in TERMINAL_STATES:
        raise errors.err_already_terminal()
    if load["status"] not in RETURNABLE_STATES:
        raise errors.err_invalid_state()
    if mw.dec(returned) <= 0:
        raise errors.err_validation("returned_qty_yd3 must be > 0")
    if mw.dec(discharged) + mw.dec(returned) != mw.dec(load["qty_yd3"]):
        raise errors.err_volume()
    truck = get_or_404("trucks", load["truck_id"])

    load["discharged_qty_yd3"] = discharged
    load["returned_qty_yd3"] = returned
    load["status"] = "RETURNED"
    mw.touch(load)

    rec = mw.new_record()
    rec["load_id"] = load["id"]
    rec["returned_qty_yd3"] = returned
    rec["disposition"] = disposition
    rec["washout_water_gal"] = None
    stores["return_records"][rec["id"]] = rec

    truck["status"] = "IN_WASHOUT"
    mw.touch(truck)
    return response.success_object(load)


# ---------------------------------------------------------------- washout

@bp.post("/v1/loads/<rid>/washout")
def washout(rid):
    mw.require_auth(BATCH_OP)
    load = get_or_404("loads", rid)
    body = mw.get_json_body()
    washout_water_gal = mw.require_number(body, "washout_water_gal")
    if load["status"] in TERMINAL_STATES:
        raise errors.err_already_terminal()
    if load["status"] != "RETURNED":
        raise errors.err_invalid_state()
    truck = get_or_404("trucks", load["truck_id"])
    for rec in stores["return_records"].values():
        if rec["load_id"] == load["id"]:
            rec["washout_water_gal"] = washout_water_gal
            mw.touch(rec)
            break
    load["status"] = "WASHED_OUT"
    mw.touch(load)
    truck["status"] = "AVAILABLE"
    truck["last_available_at"] = clock.iso(clock.now())
    mw.touch(truck)
    return response.success_object(load)


# ---------------------------------------------------------- water additions

@bp.post("/v1/loads/<rid>/water-additions")
def add_water(rid):
    user_id, _ = mw.require_auth(DRIVER)
    load = get_or_404("loads", rid)
    body = mw.get_json_body()
    gallons = mw.require_number(body, "gallons")
    customer_authorized = mw.require_bool(body, "customer_authorized")
    if load["status"] in TERMINAL_STATES:
        raise errors.err_already_terminal()
    if load["status"] not in ("ON_SITE", "POURING"):
        raise errors.err_invalid_state()
    ticket = next((t for t in stores["batch_tickets"].values() if t["load_id"] == load["id"]), None)
    if ticket is None:
        raise errors.err_not_found("Batch ticket does not exist")
    rec = mw.new_record(common=False)
    rec["load_id"] = load["id"]
    rec["gallons"] = gallons
    rec["customer_authorized"] = customer_authorized
    rec["added_by_user_id"] = user_id
    rec["added_at"] = clock.iso(clock.now())
    rec.pop("updated_at", None)
    stores["water_additions"][rec["id"]] = rec

    order = get_or_404("orders", load["order_id"])
    mix = get_or_404("mix_designs", order["mix_design_id"])
    load["actual_wc_ratio"] = calc.compute_actual_wc(ticket, load["id"])
    if calc.d(load["actual_wc_ratio"]) > calc.d(mix["max_wc_ratio"]) and not load["over_watered"]:
        load["over_watered"] = True
        calc.apply_water_liability(load)
    elif load["over_watered"]:
        calc.apply_water_liability(load)
    mw.touch(load)
    return response.success_object(rec, 201)


@bp.get("/v1/loads/<rid>/water-additions")
def list_water_additions(rid):
    mw.require_auth(mw.ALL_ROLES)
    get_or_404("loads", rid)
    limit, offset = mw.parse_pagination()
    items = [w for w in stores["water_additions"].values() if w["load_id"] == rid]
    page, total = mw.sort_and_page(items, limit, offset)
    return response.success_array(page, limit, offset, total)


# ------------------------------------------------------------- batch ticket

@bp.get("/v1/loads/<rid>/batch-ticket")
def get_batch_ticket(rid):
    mw.require_auth(mw.ALL_ROLES)
    get_or_404("loads", rid)
    items = [t for t in stores["batch_tickets"].values() if t["load_id"] == rid]
    return response.success_array(items, 10, 0, len(items))


# ------------------------------------------------------------ return record

@bp.get("/v1/loads/<rid>/return-record")
def get_return_record(rid):
    mw.require_auth(mw.ALL_ROLES)
    get_or_404("loads", rid)
    items = [r for r in stores["return_records"].values() if r["load_id"] == rid]
    return response.success_array(items, 10, 0, len(items))


# ------------------------------------------------------------ cylinder sets

@bp.post("/v1/loads/<rid>/cylinder-sets")
def cast_cylinder_set(rid):
    user_id, _ = mw.require_auth(QCTECH)
    load = get_or_404("loads", rid)
    body = mw.get_json_body()
    num_cylinders = mw.require_int(body, "num_cylinders")
    if load["status"] in TERMINAL_STATES and load["status"] != "COMPLETED":
        raise errors.err_already_terminal()
    if load["status"] not in CASTABLE_STATES:
        raise errors.err_invalid_state()
    order = get_or_404("orders", load["order_id"])
    mix = get_or_404("mix_designs", order["mix_design_id"])
    rec = mw.new_record()
    rec["load_id"] = load["id"]
    rec["num_cylinders"] = num_cylinders
    rec["cast_by_user_id"] = user_id
    rec["cast_at"] = clock.iso(clock.now())
    rec["status"] = "CURING"
    rec["seven_day_strength_psi"] = None
    rec["seven_day_recorded_by"] = None
    rec["final_strength_psi"] = None
    rec["final_recorded_by"] = None
    rec["acceptance_basis"] = "AS_PLACED" if load["over_watered"] else "DESIGN_BASIS"
    rec["required_strength_psi"] = mix["design_strength_psi"]
    rec["acceptance_passed"] = None
    rec["certified_by_user_id"] = None
    stores["cylinder_sets"][rec["id"]] = rec
    return response.success_object(rec, 201)


@bp.get("/v1/loads/<rid>/cylinder-sets")
def list_cylinder_sets(rid):
    mw.require_auth(mw.ALL_ROLES)
    get_or_404("loads", rid)
    limit, offset = mw.parse_pagination()
    items = [c for c in stores["cylinder_sets"].values() if c["load_id"] == rid]
    page, total = mw.sort_and_page(items, limit, offset)
    return response.success_array(page, limit, offset, total)
