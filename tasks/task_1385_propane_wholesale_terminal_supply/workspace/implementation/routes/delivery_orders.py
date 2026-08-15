"""Delivery order endpoints — creation with credit gate, scheduling pipeline, cancel."""
from datetime import timedelta

import clock
import db
import middleware as mw
import response as resp
import serializers as ser
import services as svc
from errors import (
    err_not_found,
    err_referenced_not_found,
    err_invalid_state,
    err_window_invalid,
    err_dealer_mismatch,
    err_dealer_suspended,
    err_truck_not_available,
    err_truck_terminal_mismatch,
    err_truck_capacity_exceeded,
    err_driver_hours_exceeded,
    err_truck_schedule_conflict,
    err_rack_capacity_exceeded,
    err_contract_not_active,
    err_outside_contract_window,
    err_zone_terminal_mismatch,
    err_contract_terminal_mismatch,
    err_contract_dealer_mismatch,
    err_volume_invalid,
    err_insufficient_supply,
    err_credit_limit_exceeded,
    err_reserve_floor_breach,
)
from flask import Blueprint

bp = Blueprint("delivery_orders", __name__)

READ_ROLES = ["DealerUser", "CreditManager", "Dispatcher", "SupplyPlanner", "SupplyAdmin"]
FULFILLMENT_STATES = {"REQUESTED", "ALLOCATED", "SHORTED", "SCHEDULED", "LOADED", "DELIVERED", "CANCELLED"}
INVOICE_STATES = {"NOT_READY", "OPEN", "PAID", "VOID"}


@bp.route("/delivery-orders", methods=["POST"])
def create_order():
    caller = mw.authenticate()
    mw.authorize(caller, ["DealerUser"])
    dealer_id = caller["user_id"]
    dealer = db.dealers[dealer_id]

    body = mw.get_json_body(required=True)
    terminal_id = mw.req_string(body, "terminal_id")
    freight_zone_id = mw.req_string(body, "freight_zone_id")
    dealer_contract_id = mw.opt_string(body, "dealer_contract_id")
    if body.get("requested_gal") is None:
        from errors import err_invalid_request

        raise err_invalid_request("Missing required field: requested_gal")
    requested_gal = mw.req_int(body, "requested_gal")

    # body FKs (priority 5)
    terminal = db.terminals.get(terminal_id)
    if terminal is None:
        raise err_referenced_not_found("terminal_id does not resolve")
    zone = db.freight_zones.get(freight_zone_id)
    if zone is None:
        raise err_referenced_not_found("freight_zone_id does not resolve")
    contract = None
    if dealer_contract_id is not None:
        contract = db.dealer_contracts.get(dealer_contract_id)
        if contract is None:
            raise err_referenced_not_found("dealer_contract_id does not resolve")

    # cross-entity state gates (priority 8)
    if contract is not None and contract["status"] != "ACTIVE":
        raise err_contract_not_active("DealerContract must be ACTIVE at order creation")
    committed_before = svc.committed_excluding(dealer)
    status_before = svc.credit_status_of(committed_before, dealer["credit_limit_cents"])
    if status_before == "SUSPENDED":
        raise err_dealer_suspended()

    # business constraints (priority 10)
    if requested_gal < 1000:
        raise err_volume_invalid("requested_gal must be an integer >= 1000")
    if zone["terminal_id"] != terminal_id:
        raise err_zone_terminal_mismatch()
    if contract is not None:
        if contract["terminal_id"] != terminal_id:
            raise err_contract_terminal_mismatch()
        if contract["dealer_id"] != dealer_id:
            raise err_contract_dealer_mismatch()
        today = clock.today_date()
        if not (contract["window_start"] <= today <= contract["window_end"]):
            raise err_outside_contract_window("Creation date outside the contract window")

    # priority 10 tail: supply gate (NORMAL posture only; exactly equal succeeds)
    if terminal["allocation_posture"] == "NORMAL":
        if requested_gal > ser.available_to_promise(terminal):
            raise err_insufficient_supply()

    pricing_mode = "SPOT" if contract is None else contract["pricing_mode"]
    watch_mc = svc.CREDIT_WATCH_SURCHARGE_MC if status_before == "WATCH" else 0

    # transient provisional for the credit gate (runs in both postures);
    # may raise ERR_NO_INDEX_PUBLISHED (priority 11, after supply gate)
    provisional = svc.delivered_price(
        pricing_mode=pricing_mode,
        volume_gal=requested_gal,
        contract=contract,
        zone=zone,
        terminal=terminal,
        ref_date=clock.today_date(),
        watch_mc=watch_mc,
    )
    # fiscal gate (priority 11)
    if committed_before + provisional > dealer["credit_limit_cents"]:
        raise err_credit_limit_exceeded()

    now = svc.stamp_now()
    o = {
        "id": db.new_id(),
        "dealer_id": dealer_id,
        "dealer_contract_id": dealer_contract_id,
        "terminal_id": terminal_id,
        "freight_zone_id": freight_zone_id,
        "truck_id": None,
        "requested_gal": requested_gal,
        "allocated_gal": None,
        "pricing_mode": pricing_mode,
        "provisional_total_cents": None,
        "final_total_cents": None,
        "open_balance_cents": None,
        "fulfillment_status": "REQUESTED",
        "invoice_status": "NOT_READY",
        "planned_load_start": None,
        "planned_load_end": None,
        "est_trip_minutes": None,
        "invoiced_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }

    if terminal["allocation_posture"] == "NORMAL":
        # fast path: allocate immediately
        o["fulfillment_status"] = "ALLOCATED"
        o["allocated_gal"] = requested_gal
        o["provisional_total_cents"] = provisional
    # CURTAILED: lands REQUESTED with allocated/provisional null

    db.delivery_orders[o["id"]] = o
    return resp.created(ser.serialize_order(o))


@bp.route("/delivery-orders/<oid>", methods=["GET"])
def get_order(oid):
    caller = mw.authenticate()
    mw.authorize(caller, READ_ROLES)
    o = db.delivery_orders.get(oid)
    if o is None:
        raise err_not_found()
    if caller["role"] == "DealerUser" and o["dealer_id"] != caller["user_id"]:
        raise err_dealer_mismatch()
    return resp.ok(ser.serialize_order(o))


@bp.route("/delivery-orders", methods=["GET"])
def list_orders():
    caller = mw.authenticate()
    mw.authorize(caller, READ_ROLES)
    limit, offset = mw.pagination_params()
    dealer_id = mw.opt_query_string("dealer_id")
    terminal_id = mw.opt_query_string("terminal_id")
    dealer_contract_id = mw.opt_query_string("dealer_contract_id")
    truck_id = mw.opt_query_string("truck_id")
    freight_zone_id = mw.opt_query_string("freight_zone_id")
    fulfillment_status = mw.opt_query_enum("fulfillment_status", FULFILLMENT_STATES)
    invoice_status = mw.opt_query_enum("invoice_status", INVOICE_STATES)
    if caller["role"] == "DealerUser":
        if dealer_id is not None and dealer_id != caller["user_id"]:
            raise err_dealer_mismatch()
        dealer_id = caller["user_id"]
    items = list(db.delivery_orders.values())
    if dealer_id is not None:
        items = [o for o in items if o["dealer_id"] == dealer_id]
    if terminal_id is not None:
        items = [o for o in items if o["terminal_id"] == terminal_id]
    if dealer_contract_id is not None:
        items = [o for o in items if o["dealer_contract_id"] == dealer_contract_id]
    if truck_id is not None:
        items = [o for o in items if o["truck_id"] == truck_id]
    if freight_zone_id is not None:
        items = [o for o in items if o["freight_zone_id"] == freight_zone_id]
    if fulfillment_status is not None:
        items = [o for o in items if o["fulfillment_status"] == fulfillment_status]
    if invoice_status is not None:
        items = [o for o in items if o["invoice_status"] == invoice_status]
    items.sort(key=lambda o: o["_seq"])
    total = len(items)
    page = items[offset : offset + limit]
    return resp.list_ok([ser.serialize_order(o) for o in page], limit, offset, total)


@bp.route("/delivery-orders/<oid>/schedule", methods=["POST"])
def schedule_order(oid):
    caller = mw.authenticate()
    mw.authorize(caller, ["Dispatcher"])
    o = db.delivery_orders.get(oid)
    if o is None:
        raise err_not_found()
    body = mw.get_json_body(required=True)
    truck_id = mw.req_string(body, "truck_id")
    planned_load_start = mw.req_datetime(body, "planned_load_start")
    planned_load_end = mw.req_datetime(body, "planned_load_end")

    # body FK (priority 5)
    truck = db.trucks.get(truck_id)
    if truck is None:
        raise err_referenced_not_found("truck_id does not resolve")

    # transition legality (priority 7)
    if o["fulfillment_status"] != "ALLOCATED":
        raise err_invalid_state("Only an ALLOCATED order can be scheduled")

    # cross-entity state gates (priority 8)
    if truck["status"] != "AVAILABLE":
        raise err_truck_not_available()
    contract = None
    if o["dealer_contract_id"] is not None:
        contract = db.dealer_contracts[o["dealer_contract_id"]]
        if contract["status"] != "ACTIVE":
            raise err_contract_not_active("DealerContract must be ACTIVE at scheduling")

    # request-shape business error: inverted window is checked before any
    # overlap arithmetic (schedule_window_inverted_rejected)
    if planned_load_end <= planned_load_start:
        raise err_window_invalid("planned_load_end must be > planned_load_start")

    # safety (priority 9): driver hours-of-service
    zone = db.freight_zones[o["freight_zone_id"]]
    est = svc.est_trip_minutes(zone)
    committed_minutes = ser.weekly_committed_minutes(
        truck["id"], ref_dt=planned_load_start
    )
    if committed_minutes + est > truck["weekly_hours_limit_minutes"]:
        raise err_driver_hours_exceeded()

    # constraints (priority 10)
    if truck["terminal_id"] != o["terminal_id"]:
        raise err_truck_terminal_mismatch()
    # Capacity gate (PRD 3.6): the order's allocated_gal must not exceed the
    # truck's capacity_gal — unconditional, per-order.
    if o["allocated_gal"] > truck["capacity_gal"]:
        raise err_truck_capacity_exceeded()

    # buffered window overlap on the same truck (half-open, symmetric 60-min buffer)
    buf = timedelta(minutes=svc.DEADHEAD_BUFFER_MINUTES)
    new_start = planned_load_start - buf
    new_end = planned_load_end + buf
    for other in db.delivery_orders.values():
        if other["id"] == o["id"] or other["truck_id"] != truck["id"]:
            continue
        if other["fulfillment_status"] not in ("SCHEDULED", "LOADED", "DELIVERED"):
            continue
        old_start = other["planned_load_start"] - buf
        old_end = other["planned_load_end"] + buf
        if max(new_start, old_start) < min(new_end, old_end):
            raise err_truck_schedule_conflict()

    # rack bay aggregate capacity: raw unbuffered windows vs terminal SCHEDULED/LOADED
    terminal = db.terminals[o["terminal_id"]]
    overlap_count = 0
    for other in db.delivery_orders.values():
        if other["id"] == o["id"] or other["terminal_id"] != o["terminal_id"]:
            continue
        if other["fulfillment_status"] not in ("SCHEDULED", "LOADED"):
            continue
        if max(planned_load_start, other["planned_load_start"]) < min(
            planned_load_end, other["planned_load_end"]
        ):
            overlap_count += 1
    if overlap_count >= terminal["rack_bay_count"]:
        raise err_rack_capacity_exceeded()

    if contract is not None:
        load_date = planned_load_start.date()
        if not (contract["window_start"] <= load_date <= contract["window_end"]):
            raise err_outside_contract_window("planned_load_start outside the contract window")

    o["fulfillment_status"] = "SCHEDULED"
    o["truck_id"] = truck["id"]
    o["planned_load_start"] = planned_load_start
    o["planned_load_end"] = planned_load_end
    o["est_trip_minutes"] = est
    svc.touch(o)
    return resp.ok(ser.serialize_order(o))


@bp.route("/delivery-orders/<oid>/unschedule", methods=["POST"])
def unschedule_order(oid):
    caller = mw.authenticate()
    mw.authorize(caller, ["Dispatcher"])
    o = db.delivery_orders.get(oid)
    if o is None:
        raise err_not_found()
    if o["fulfillment_status"] != "SCHEDULED":
        raise err_invalid_state("Only a SCHEDULED order can be unscheduled")
    svc.unschedule_order(o)
    svc.touch(o)
    return resp.ok(ser.serialize_order(o))


@bp.route("/delivery-orders/<oid>/load", methods=["POST"])
def load_order(oid):
    caller = mw.authenticate()
    mw.authorize(caller, ["Dispatcher"])
    o = db.delivery_orders.get(oid)
    if o is None:
        raise err_not_found()
    if o["fulfillment_status"] != "SCHEDULED":
        raise err_invalid_state("Only a SCHEDULED order can be loaded")

    terminal = db.terminals[o["terminal_id"]]
    # safety (priority 9): reserve floor — after drawing, terminal must hold >= floor
    if terminal["on_hand_gal"] - o["allocated_gal"] < ser.effective_reserve_floor(terminal):
        raise err_reserve_floor_breach()

    # final pricing: ref_date = date(planned_load_start); winter leg uses current
    # posture; banding uses volume_drawn_gal BEFORE this load's draw is applied
    zone = db.freight_zones[o["freight_zone_id"]]
    dealer = db.dealers[o["dealer_id"]]
    contract = (
        db.dealer_contracts.get(o["dealer_contract_id"]) if o["dealer_contract_id"] else None
    )
    committed = svc.committed_excluding(dealer, exclude_order_id=o["id"])
    status_before = svc.credit_status_of(committed, dealer["credit_limit_cents"])
    watch_mc = svc.CREDIT_WATCH_SURCHARGE_MC if status_before == "WATCH" else 0
    final_total = svc.delivered_price(
        pricing_mode=o["pricing_mode"],
        volume_gal=o["allocated_gal"],
        contract=contract,
        zone=zone,
        terminal=terminal,
        ref_date=o["planned_load_start"].date(),
        watch_mc=watch_mc,
    )

    o["final_total_cents"] = final_total
    o["fulfillment_status"] = "LOADED"
    svc.touch(o)

    terminal["on_hand_gal"] -= o["allocated_gal"]
    svc.touch(terminal)

    if contract is not None:
        in_band = min(
            o["allocated_gal"],
            max(0, contract["volume_committed_gal"] - contract["volume_drawn_gal"]),
        )
        if in_band:
            contract["volume_drawn_gal"] += in_band
            svc.touch(contract)

    return resp.ok(ser.serialize_order(o))


@bp.route("/delivery-orders/<oid>/deliver", methods=["POST"])
def deliver_order(oid):
    caller = mw.authenticate()
    mw.authorize(caller, ["Dispatcher"])
    o = db.delivery_orders.get(oid)
    if o is None:
        raise err_not_found()
    if o["fulfillment_status"] != "LOADED":
        raise err_invalid_state("Only a LOADED order can be delivered")
    o["fulfillment_status"] = "DELIVERED"
    o["invoice_status"] = "OPEN"
    o["open_balance_cents"] = o["final_total_cents"]
    o["invoiced_at"] = svc.stamp_now()
    svc.touch(o)
    return resp.ok(ser.serialize_order(o))


@bp.route("/delivery-orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    caller = mw.authenticate()
    mw.authorize(caller, ["DealerUser", "Dispatcher"])
    o = db.delivery_orders.get(oid)
    if o is None:
        raise err_not_found()
    if caller["role"] == "DealerUser" and o["dealer_id"] != caller["user_id"]:
        raise err_dealer_mismatch()
    if o["fulfillment_status"] not in ("REQUESTED", "ALLOCATED", "SHORTED", "SCHEDULED"):
        raise err_invalid_state("Order cannot be cancelled from its current state")
    if o["fulfillment_status"] == "SCHEDULED":
        svc.unschedule_order(o)
    o["fulfillment_status"] = "CANCELLED"
    if o["invoice_status"] == "NOT_READY":
        o["invoice_status"] = "VOID"
    svc.touch(o)
    return resp.ok(ser.serialize_order(o))
