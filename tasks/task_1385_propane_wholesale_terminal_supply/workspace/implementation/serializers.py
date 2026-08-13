"""Entity serializers — computed fields are evaluated on read, never stored."""
from datetime import date, timedelta, timezone

import clock
import db

WINTER_MONTHS = {10, 11, 12, 1, 2, 3}


def _dt_iso(dt):
    """Format an aware datetime to ISO 8601 UTC with Z suffix (<=3 frac digits)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        s = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}"
    else:
        s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return s + "Z"


# ---------------------------------------------------------------------------
# Terminal computed fields
# ---------------------------------------------------------------------------

def season_posture(now=None):
    n = now or clock.now()
    return "WINTER_DRAW" if n.month in WINTER_MONTHS else "SUMMER_BUILD"


def effective_reserve_floor(t, now=None):
    return t["winter_reserve_floor_gal"] if season_posture(now) == "WINTER_DRAW" else t["reserve_floor_gal"]


def reserved_gal(terminal_id):
    total = 0
    for o in db.delivery_orders.values():
        if o["terminal_id"] == terminal_id and o["fulfillment_status"] in ("ALLOCATED", "SCHEDULED"):
            total += o["allocated_gal"] or 0
    return total


def available_to_promise(t, now=None):
    return t["on_hand_gal"] - effective_reserve_floor(t, now) - reserved_gal(t["id"])


def serialize_terminal(t):
    n = clock.now()
    return {
        "id": t["id"],
        "name": t["name"],
        "region_code": t["region_code"],
        "storage_capacity_gal": t["storage_capacity_gal"],
        "reserve_floor_gal": t["reserve_floor_gal"],
        "winter_reserve_floor_gal": t["winter_reserve_floor_gal"],
        "rack_bay_count": t["rack_bay_count"],
        "on_hand_gal": t["on_hand_gal"],
        "allocation_posture": t["allocation_posture"],
        "ops_epoch": t["ops_epoch"],
        "season_posture": season_posture(n),
        "reserved_gal": reserved_gal(t["id"]),
        "effective_reserve_floor_gal": effective_reserve_floor(t, n),
        "available_to_promise_gal": available_to_promise(t, n),
        "created_at": _dt_iso(t["created_at"]),
        "updated_at": _dt_iso(t["updated_at"]),
        "version": t["version"],
    }


def serialize_inventory_summary(t):
    n = clock.now()
    open_request = 0
    for o in db.delivery_orders.values():
        if o["terminal_id"] == t["id"] and o["fulfillment_status"] == "REQUESTED":
            open_request += o["requested_gal"]
    return {
        "on_hand_gal": t["on_hand_gal"],
        "reserved_gal": reserved_gal(t["id"]),
        "effective_reserve_floor_gal": effective_reserve_floor(t, n),
        "available_to_promise_gal": available_to_promise(t, n),
        "season_posture": season_posture(n),
        "allocation_posture": t["allocation_posture"],
        "open_request_gal": open_request,
    }


# ---------------------------------------------------------------------------
# SupplyContract
# ---------------------------------------------------------------------------

def serialize_supply_contract(c):
    return {
        "id": c["id"],
        "terminal_id": c["terminal_id"],
        "supplier_name": c["supplier_name"],
        "contracted_volume_gal": c["contracted_volume_gal"],
        "delivered_volume_gal": c["delivered_volume_gal"],
        "receipt_window_start": c["receipt_window_start"].isoformat(),
        "receipt_window_end": c["receipt_window_end"].isoformat(),
        "status": c["status"],
        "created_at": _dt_iso(c["created_at"]),
        "updated_at": _dt_iso(c["updated_at"]),
        "version": c["version"],
    }


# ---------------------------------------------------------------------------
# RailShipment
# ---------------------------------------------------------------------------

def serialize_rail_shipment(s):
    return {
        "id": s["id"],
        "supply_contract_id": s["supply_contract_id"],
        "terminal_id": s["terminal_id"],
        "volume_gal": s["volume_gal"],
        "railcar_count": s["railcar_count"],
        "scheduled_arrival_date": s["scheduled_arrival_date"].isoformat(),
        "unloaded_at": _dt_iso(s["unloaded_at"]) if s["unloaded_at"] else None,
        "status": s["status"],
        "created_at": _dt_iso(s["created_at"]),
        "updated_at": _dt_iso(s["updated_at"]),
        "version": s["version"],
    }


# ---------------------------------------------------------------------------
# Dealer computed fields
# ---------------------------------------------------------------------------

def ledger_exposure(dealer_id):
    total = 0
    for o in db.delivery_orders.values():
        if o["dealer_id"] == dealer_id and o["invoice_status"] == "OPEN":
            total += o["open_balance_cents"] or 0
    return total


def committed_exposure(d):
    total = d["fee_balance_cents"] + ledger_exposure(d["id"])
    for o in db.delivery_orders.values():
        if o["dealer_id"] != d["id"]:
            continue
        if o["fulfillment_status"] == "LOADED":
            total += o["final_total_cents"] or 0
        elif o["fulfillment_status"] in ("ALLOCATED", "SCHEDULED"):
            total += o["provisional_total_cents"] or 0
    return total


def credit_status_of(committed, credit_limit):
    if committed >= credit_limit:
        return "SUSPENDED"
    if committed * 5 >= credit_limit * 4:
        return "WATCH"
    return "GOOD_STANDING"


def serialize_dealer(d):
    committed = committed_exposure(d)
    return {
        "id": d["id"],
        "legal_name": d["legal_name"],
        "credit_limit_cents": d["credit_limit_cents"],
        "fee_balance_cents": d["fee_balance_cents"],
        "ledger_exposure_cents": ledger_exposure(d["id"]),
        "committed_exposure_cents": committed,
        "credit_status": credit_status_of(committed, d["credit_limit_cents"]),
        "created_at": _dt_iso(d["created_at"]),
        "updated_at": _dt_iso(d["updated_at"]),
        "version": d["version"],
    }


# ---------------------------------------------------------------------------
# DealerContract
# ---------------------------------------------------------------------------

def serialize_dealer_contract(c):
    return {
        "id": c["id"],
        "dealer_id": c["dealer_id"],
        "terminal_id": c["terminal_id"],
        "pricing_mode": c["pricing_mode"],
        "fixed_price_mc_per_gal": c["fixed_price_mc_per_gal"],
        "volume_committed_gal": c["volume_committed_gal"],
        "volume_drawn_gal": c["volume_drawn_gal"],
        "window_start": c["window_start"].isoformat(),
        "window_end": c["window_end"].isoformat(),
        "status": c["status"],
        "created_at": _dt_iso(c["created_at"]),
        "updated_at": _dt_iso(c["updated_at"]),
        "version": c["version"],
    }


# ---------------------------------------------------------------------------
# PriceIndexPublication (append-only: id + created_at only)
# ---------------------------------------------------------------------------

def serialize_price_index_publication(p):
    return {
        "id": p["id"],
        "index_name": p["index_name"],
        "effective_date": p["effective_date"].isoformat(),
        "price_mc_per_gal": p["price_mc_per_gal"],
        "created_at": _dt_iso(p["created_at"]),
    }


# ---------------------------------------------------------------------------
# FreightZone
# ---------------------------------------------------------------------------

def serialize_freight_zone(z):
    return {
        "id": z["id"],
        "terminal_id": z["terminal_id"],
        "zone_code": z["zone_code"],
        "one_way_drive_minutes": z["one_way_drive_minutes"],
        "freight_mc_per_gal": z["freight_mc_per_gal"],
        "min_freight_cents": z["min_freight_cents"],
        "created_at": _dt_iso(z["created_at"]),
        "updated_at": _dt_iso(z["updated_at"]),
        "version": z["version"],
    }


# ---------------------------------------------------------------------------
# TransportTruck
# ---------------------------------------------------------------------------

def _iso_week_monday(dt):
    """Monday 00:00 UTC of the ISO week containing aware datetime dt."""
    d = dt.astimezone(timezone.utc).date()
    monday = d - timedelta(days=d.isoweekday() - 1)
    return monday


def weekly_committed_minutes(truck_id, ref_dt=None):
    ref = ref_dt or clock.now()
    ref_monday = _iso_week_monday(ref)
    total = 0
    for o in db.delivery_orders.values():
        if o["truck_id"] != truck_id:
            continue
        if o["fulfillment_status"] not in ("SCHEDULED", "LOADED", "DELIVERED"):
            continue
        if o["planned_load_start"] is None:
            continue
        if _iso_week_monday(o["planned_load_start"]) == ref_monday:
            total += o["est_trip_minutes"] or 0
    return total


def serialize_truck(t):
    return {
        "id": t["id"],
        "terminal_id": t["terminal_id"],
        "unit_number": t["unit_number"],
        "capacity_gal": t["capacity_gal"],
        "weekly_hours_limit_minutes": t["weekly_hours_limit_minutes"],
        "status": t["status"],
        "weekly_committed_minutes": weekly_committed_minutes(t["id"]),
        "created_at": _dt_iso(t["created_at"]),
        "updated_at": _dt_iso(t["updated_at"]),
        "version": t["version"],
    }


# ---------------------------------------------------------------------------
# DeliveryOrder
# ---------------------------------------------------------------------------

def serialize_order(o):
    return {
        "id": o["id"],
        "dealer_id": o["dealer_id"],
        "dealer_contract_id": o["dealer_contract_id"],
        "terminal_id": o["terminal_id"],
        "freight_zone_id": o["freight_zone_id"],
        "truck_id": o["truck_id"],
        "requested_gal": o["requested_gal"],
        "allocated_gal": o["allocated_gal"],
        "pricing_mode": o["pricing_mode"],
        "provisional_total_cents": o["provisional_total_cents"],
        "final_total_cents": o["final_total_cents"],
        "open_balance_cents": o["open_balance_cents"],
        "fulfillment_status": o["fulfillment_status"],
        "invoice_status": o["invoice_status"],
        "planned_load_start": _dt_iso(o["planned_load_start"]) if o["planned_load_start"] else None,
        "planned_load_end": _dt_iso(o["planned_load_end"]) if o["planned_load_end"] else None,
        "est_trip_minutes": o["est_trip_minutes"],
        "invoiced_at": _dt_iso(o["invoiced_at"]) if o["invoiced_at"] else None,
        "created_at": _dt_iso(o["created_at"]),
        "updated_at": _dt_iso(o["updated_at"]),
        "version": o["version"],
    }


# ---------------------------------------------------------------------------
# ColdSnapEvent
# ---------------------------------------------------------------------------

def serialize_cold_snap(e):
    return {
        "id": e["id"],
        "terminal_id": e["terminal_id"],
        "severity": e["severity"],
        "start_date": e["start_date"].isoformat(),
        "end_date": e["end_date"].isoformat(),
        "status": e["status"],
        "created_at": _dt_iso(e["created_at"]),
        "updated_at": _dt_iso(e["updated_at"]),
        "version": e["version"],
    }


# ---------------------------------------------------------------------------
# AllocationRun
# ---------------------------------------------------------------------------

def serialize_allocation_run(r):
    return {
        "id": r["id"],
        "terminal_id": r["terminal_id"],
        "run_index": r["run_index"],
        "status": r["status"],
        "pool_gal": r["pool_gal"],
        "results": r["results"],
        "created_at": _dt_iso(r["created_at"]),
        "updated_at": _dt_iso(r["updated_at"]),
        "version": r["version"],
    }


# ---------------------------------------------------------------------------
# DealerPayment
# ---------------------------------------------------------------------------

def serialize_payment(p):
    return {
        "id": p["id"],
        "dealer_id": p["dealer_id"],
        "amount_cents": p["amount_cents"],
        "method": p["method"],
        "status": p["status"],
        "applications": p["applications"],
        "created_at": _dt_iso(p["created_at"]),
        "updated_at": _dt_iso(p["updated_at"]),
        "version": p["version"],
    }
