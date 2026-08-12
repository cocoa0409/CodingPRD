from decimal import Decimal

from flask import Blueprint, g, request

from auth import auth, check_own
from envelope import created, list_response, success
from errors import err
from services import (assign_item, compute_din, items_of, occupancy_conflict,
                      planned_days_of, recompute_quote, recompute_standing,
                      release_item, rhu, rental_discount, unit_eligible)
from store import db, is_date_str, new_entity, now, parse_date, pub, touch
from validate import (GEAR_TYPES, PICKUP_METHODS, TIERS, body, get_or_404,
                      req_date, req_enum, req_int, req_str)

bp = Blueprint("reservations", __name__)


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------

@bp.post("/shop/reservations")
def create_reservation():
    auth("Customer", "FrontDesk", "Manager")
    b = body()
    cust_id = b.get("customer_id")
    # ownership (priority 3) before existence (priority 4)
    if g.user_role == "Customer" and cust_id is not None and cust_id != g.user_id:
        raise err("ERR_FORBIDDEN_OWNERSHIP",
                  "Customers may only create reservations for themselves")
    if cust_id is not None:
        get_or_404(db.customers, cust_id, "Customer")
    # date-window check (priority 7) ahead of generic field-shape checks (10)
    sd, ed = b.get("start_date"), b.get("end_date")
    if is_date_str(sd) and is_date_str(ed) and parse_date(ed) < parse_date(sd):
        raise err("ERR_DATE_RANGE_INVALID", "end_date must be >= start_date")
    cust_id = req_str(b, "customer_id")
    start_date = req_date(b, "start_date")
    end_date = req_date(b, "end_date")
    pickup_method = req_enum(b, "pickup_method", PICKUP_METHODS)
    res = new_entity({
        "customer_id": cust_id,
        "start_date": start_date,
        "end_date": end_date,
        "pickup_method": pickup_method,
        "fulfillment_status": "DRAFT",
        "payment_status": "UNPAID",
        "quoted_total_cents": 0,
        "deposit_minimum_cents": 0,
        "final_total_cents": None,
        "deposit_authorized_cents": 0,
        "deposit_captured_cents": 0,
        "deposit_released_cents": 0,
    })
    db.reservations[res["id"]] = res
    return created(pub(res))


@bp.get("/shop/reservations/<rid>")
def get_reservation(rid):
    auth("Customer", "FrontDesk", "Technician", "Manager")
    res = get_or_404(db.reservations, rid, "Reservation")
    check_own(res["customer_id"])
    return success(pub(res))


@bp.get("/shop/reservations")
def list_reservations():
    auth("Customer", "FrontDesk", "Technician", "Manager")
    items = list(db.reservations.values())
    if g.user_role == "Customer":
        items = [r for r in items if r["customer_id"] == g.user_id]
    customer_id = request.args.get("customer_id")
    fulfillment = request.args.get("fulfillment_status")
    payment = request.args.get("payment_status")
    if customer_id is not None:
        items = [r for r in items if r["customer_id"] == customer_id]
    if fulfillment is not None:
        items = [r for r in items if r["fulfillment_status"] == fulfillment]
    if payment is not None:
        items = [r for r in items if r["payment_status"] == payment]
    return list_response(items)


@bp.post("/shop/reservations/<rid>/items")
def add_reservation_item(rid):
    auth("Customer", "FrontDesk", "Manager")
    res = get_or_404(db.reservations, rid, "Reservation")
    check_own(res["customer_id"])
    if res["fulfillment_status"] not in ("DRAFT", "CONFIRMED"):
        raise err("ERR_INVALID_STATE",
                  "Items can only be added while the reservation is DRAFT or CONFIRMED")
    b = body()
    gear = req_enum(b, "gear_type_requested", GEAR_TYPES)
    tier = req_enum(b, "tier_requested", TIERS)
    item = new_entity({
        "reservation_id": res["id"],
        "equipment_item_id": None,
        "gear_type_requested": gear,
        "tier_requested": tier,
        "status": "QUEUED",
        "daily_rate_cents": None,
        "din_setting": None,
        "assigned_at": None,
        "planned_days": planned_days_of(res),
        "actual_days": None,
        "late_days": None,
        "line_final_cents": None,
    })
    db.reservation_items[item["id"]] = item
    touch(res)  # adding a line mutates the reservation (version + 1)
    return created(pub(item))


@bp.post("/shop/reservations/<rid>/confirm")
def confirm_reservation(rid):
    auth("Customer", "FrontDesk", "Manager")
    res = get_or_404(db.reservations, rid, "Reservation")
    check_own(res["customer_id"])
    if res["fulfillment_status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT reservation can be confirmed")
    recompute_quote(res)  # quote recomputed on confirm, then frozen
    deposit = req_int(body(), "deposit_authorized_cents", minimum=0)
    if not any(i["status"] == "ASSIGNED" for i in items_of(res["id"])):
        raise err("ERR_ITEMS_UNASSIGNED",
                  "At least one ASSIGNED item is required to confirm")
    if deposit < res["deposit_minimum_cents"]:
        raise err("ERR_DEPOSIT_BELOW_MINIMUM",
                  "deposit_authorized_cents is below deposit_minimum_cents")
    res["deposit_authorized_cents"] = deposit
    res["fulfillment_status"] = "CONFIRMED"
    res["payment_status"] = "AUTHORIZED"
    touch(res)
    return success(pub(res))


@bp.post("/shop/reservations/<rid>/cancel")
def cancel_reservation(rid):
    auth("Customer", "FrontDesk", "Manager")
    res = get_or_404(db.reservations, rid, "Reservation")
    check_own(res["customer_id"])
    if res["fulfillment_status"] not in ("DRAFT", "CONFIRMED"):
        raise err("ERR_INVALID_STATE",
                  "Only a DRAFT or CONFIRMED reservation can be cancelled")
    for item in items_of(res["id"]):
        if item["status"] == "ASSIGNED":
            release_item(item)  # frees unit + waitlist promotion cascade
        elif item["status"] == "QUEUED":
            item["status"] = "RELEASED"
            touch(item)
    if res["payment_status"] == "AUTHORIZED":
        res["payment_status"] = "VOIDED"
    res["deposit_released_cents"] = (res["deposit_authorized_cents"]
                                     - res["deposit_captured_cents"])
    res["fulfillment_status"] = "CANCELLED"
    touch(res)
    return success(pub(res))


@bp.post("/shop/reservations/<rid>/pickup")
def pickup_reservation(rid):
    auth("FrontDesk", "Manager")
    res = get_or_404(db.reservations, rid, "Reservation")
    if res["fulfillment_status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE",
                  "Only a CONFIRMED reservation can be picked up")
    if any(i["status"] == "QUEUED" for i in items_of(res["id"])):
        raise err("ERR_ITEMS_UNASSIGNED",
                  "QUEUED items remain; they must be assigned or released first")
    for item in items_of(res["id"]):
        if item["status"] == "ASSIGNED":
            unit = db.equipment_items[item["equipment_item_id"]]
            unit["status"] = "OUT"
            touch(unit)
    res["fulfillment_status"] = "ACTIVE"
    touch(res)
    return success(pub(res))


@bp.post("/shop/reservations/<rid>/return")
def return_reservation(rid):
    auth("FrontDesk", "Manager")
    res = get_or_404(db.reservations, rid, "Reservation")
    if res["fulfillment_status"] not in ("ACTIVE", "OVERDUE"):
        raise err("ERR_INVALID_STATE",
                  "Only an ACTIVE or OVERDUE reservation can be returned")
    today = now().date()
    start = parse_date(res["start_date"])
    planned = planned_days_of(res)
    discount = rental_discount(planned)
    final_total = 0
    any_late = False
    for item in items_of(res["id"]):
        if item["status"] != "ASSIGNED":
            continue
        actual = (today - start).days + 1
        regular = max(0, min(actual, planned))
        late = max(0, actual - planned)
        rate = Decimal(item["daily_rate_cents"])
        line_final = (rhu(Decimal(regular) * rate * (Decimal(1) - discount))
                      + rhu(Decimal(late) * rate * Decimal("1.5")))
        item["actual_days"] = actual
        item["late_days"] = late
        item["line_final_cents"] = line_final
        item["status"] = "RETURNED"
        touch(item)
        unit = db.equipment_items[item["equipment_item_id"]]
        unit["status"] = "AWAITING_INSPECTION"
        unit["accrued_rental_days"] += max(0, actual)
        touch(unit)
        final_total += line_final
        if late > 0:
            any_late = True
    res["final_total_cents"] = final_total
    res["fulfillment_status"] = "RETURNED"
    res["payment_status"] = "CAPTURED"
    touch(res)
    if any_late:
        cust = db.customers[res["customer_id"]]
        cust["late_return_count"] += 1  # once per reservation, not per line
        touch(cust)
        recompute_standing(cust["id"])
    return success(pub(res))


@bp.post("/shop/reservations/<rid>/close")
def close_reservation(rid):
    auth("FrontDesk", "Manager")
    res = get_or_404(db.reservations, rid, "Reservation")
    if res["fulfillment_status"] != "RETURNED":
        raise err("ERR_INVALID_STATE", "Only a RETURNED reservation can be closed")
    for item in items_of(res["id"]):
        if item["status"] == "RETURNED" and item["equipment_item_id"]:
            unit = db.equipment_items[item["equipment_item_id"]]
            if unit["status"] in ("OUT", "AWAITING_INSPECTION"):
                raise err("ERR_ITEMS_PENDING_INSPECTION",
                          "A unit of the reservation is still OUT or "
                          "AWAITING_INSPECTION")
    res["deposit_released_cents"] = (res["deposit_authorized_cents"]
                                     - res["deposit_captured_cents"])
    res["fulfillment_status"] = "CLOSED"
    res["payment_status"] = "SETTLED"
    touch(res)
    return success(pub(res))


# ---------------------------------------------------------------------------
# Reservation items
# ---------------------------------------------------------------------------

@bp.get("/shop/reservation-items/<iid>")
def get_reservation_item(iid):
    auth("Customer", "FrontDesk", "Technician", "Manager")
    item = get_or_404(db.reservation_items, iid, "Reservation item")
    check_own(db.reservations[item["reservation_id"]]["customer_id"])
    return success(pub(item))


@bp.get("/shop/reservation-items")
def list_reservation_items():
    auth("Customer", "FrontDesk", "Technician", "Manager")
    items = list(db.reservation_items.values())
    if g.user_role == "Customer":
        items = [i for i in items
                 if db.reservations[i["reservation_id"]]["customer_id"] == g.user_id]
    reservation_id = request.args.get("reservation_id")
    equipment_item_id = request.args.get("equipment_item_id")
    status = request.args.get("status")
    if reservation_id is not None:
        items = [i for i in items if i["reservation_id"] == reservation_id]
    if equipment_item_id is not None:
        items = [i for i in items if i["equipment_item_id"] == equipment_item_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    return list_response(items)


@bp.post("/shop/reservation-items/<iid>/assign")
def assign_reservation_item(iid):
    auth("FrontDesk", "Manager")
    item = get_or_404(db.reservation_items, iid, "Reservation item")
    if item["status"] != "QUEUED":
        raise err("ERR_INVALID_STATE", "Only a QUEUED item can be assigned")
    res = db.reservations[item["reservation_id"]]
    if res["fulfillment_status"] not in ("DRAFT", "CONFIRMED"):
        raise err("ERR_INVALID_STATE",
                  "Assignment requires the reservation to be DRAFT or CONFIRMED")
    cust = db.customers[res["customer_id"]]
    din = compute_din(cust)
    pref = body().get("preferred_equipment_item_id")
    if pref is not None:
        unit = get_or_404(db.equipment_items, pref, "Equipment item")
        if (unit["gear_type"] != item["gear_type_requested"]
                or unit["tier"] != item["tier_requested"]):
            raise err("ERR_INVALID_REQUEST",
                      "Preferred unit does not match the requested gear type/tier")
        if not (unit["din_min"] <= din <= unit["din_max"]):
            raise err("ERR_DIN_MISMATCH",
                      "Preferred unit's DIN range does not cover the fitment DIN")
        if unit["status"] not in ("AVAILABLE", "RESERVED"):
            raise err("ERR_EQUIPMENT_NOT_AVAILABLE",
                      "Preferred unit is not in a rentable status")
        if occupancy_conflict(unit["id"], res["start_date"], res["end_date"],
                              exclude_item_id=item["id"]):
            raise err("ERR_EQUIPMENT_OCCUPANCY_CONFLICT",
                      "Requested window collides with an existing window on the unit")
        assign_item(item, unit, din)
    else:
        pool = [u for u in db.equipment_items.values()
                if u["status"] == "AVAILABLE" and unit_eligible(u, item, res, din)]
        pool.sort(key=lambda u: (u["created_at"], u["_seq"]))
        if pool:
            assign_item(item, pool[0], din)
        # empty eligible pool: request still succeeds, line stays QUEUED
    return success(pub(item))


@bp.post("/shop/reservation-items/<iid>/release")
def release_reservation_item(iid):
    auth("FrontDesk", "Manager")
    item = get_or_404(db.reservation_items, iid, "Reservation item")
    if item["status"] != "ASSIGNED":
        raise err("ERR_INVALID_STATE", "Only an ASSIGNED item can be released")
    res = db.reservations[item["reservation_id"]]
    if res["fulfillment_status"] not in ("DRAFT", "CONFIRMED"):
        raise err("ERR_INVALID_STATE",
                  "Release requires the reservation to be DRAFT or CONFIRMED")
    release_item(item)
    return success(pub(item))
