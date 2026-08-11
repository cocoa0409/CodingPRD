"""Core domain services: serializers, derived statuses, calculations, cascades.

Everything traces to PRD.md §2-§3 and SCAFFOLD.yaml §1.2-§1.4.
"""

import math
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import STORE, now_iso_ms, _parse_dt


# ---------------------------------------------------------------------------
# Constants (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
SIZE_SURCHARGE = {35: 0, 64: 1500, 96: 3000}
EXTRA_CART_FEE_CENTS = 2500
REINSTATEMENT_SURCHARGE_CENTS = 2000
AVG_TICKET_WEIGHT_LBS = 200
COMPOST_YIELD_RATIO = Decimal("0.5")
COMPOST_LBS_PER_GALLON = Decimal("20")
DELIVERY_BUFFER_MINUTES = 30

WEEKDAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
VIOLATION_CODES = {"PLASTIC_BAG", "FOOD_WASTE", "DIRT_ROCK", "HAZARDOUS", "NON_YARD_MATERIAL"}

TERMINAL_SUB_STATUSES = {"CANCELLED", "EXPIRED"}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def new_id() -> str:
    return str(uuid.uuid4())


def parse_date(s):
    if not isinstance(s, str):
        raise ValueError("date must be a string")
    return date.fromisoformat(s)


def touch(rec):
    """Refresh updated_at and bump version (PRD §2.5)."""
    rec["updated_at"] = now_iso_ms()
    rec["version"] = rec.get("version", 1) + 1


def base_record():
    ts = now_iso_ms()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def light_record():
    """For ContaminationInspection and ServiceCredit: only id + created_at (PRD §2.5)."""
    return {"id": new_id(), "created_at": now_iso_ms()}


# ---------------------------------------------------------------------------
# Derived statuses (PRD §2.4) — recomputed lazily on every read/write
# ---------------------------------------------------------------------------
def zone_status(zone) -> str:
    d = STORE.clock_date()
    start = parse_date(zone["season_start_date"])
    end = parse_date(zone["season_end_date"])
    if d < start:
        return "OPEN_ENROLLMENT"
    if d <= end:
        return "IN_SEASON"
    return "OFF_SEASON"


def surge_event_status(event) -> str:
    now = STORE.clock()
    ws = _parse_dt(event["booking_window_start"])
    we = _parse_dt(event["booking_window_end"])
    if now < ws:
        return "SCHEDULED"
    if now < we:
        return "OPEN"
    # CLOSED from window_end until clock date passes service_date; then COMPLETED
    svc = parse_date(event["service_date"])
    if STORE.clock_date() <= svc:
        return "CLOSED"
    return "COMPLETED"


def giveback_event_status(event) -> str:
    d = STORE.clock_date()
    ed = parse_date(event["event_date"])
    if d < ed:
        return "SCHEDULED"
    if d == ed:
        return "OPEN"
    return "CLOSED"


def total_season_weeks(zone) -> int:
    start = parse_date(zone["season_start_date"])
    end = parse_date(zone["season_end_date"])
    return math.ceil((end - start).days / 7)


# ---------------------------------------------------------------------------
# Lazy system reconciliations (PRD §2.4): run on access
# ---------------------------------------------------------------------------
def reconcile_all():
    """Apply clock-driven transitions lazily. Called at the top of every request."""
    reconcile_zones_and_subscriptions()
    reconcile_routes()
    reconcile_carts()
    reconcile_surge_events()
    reconcile_campaigns()


def reconcile_zones_and_subscriptions():
    """When a zone is OFF_SEASON, expire its PENDING_PAYMENT/ACTIVE/SUSPENDED subscriptions."""
    for zone in STORE.zones.values():
        if zone_status(zone) != "OFF_SEASON":
            continue
        end = parse_date(zone["season_end_date"])
        for hh in STORE.households.values():
            if hh["zone_id"] != zone["id"]:
                continue
            for sub in STORE.subscriptions.values():
                if sub["household_id"] != hh["id"]:
                    continue
                if sub["status"] in ("PENDING_PAYMENT", "ACTIVE", "SUSPENDED"):
                    sub["status"] = "EXPIRED"
                    if sub["status"] in ("ACTIVE", "SUSPENDED"):
                        pass
                    # carts DELIVERED -> RETRIEVAL_SCHEDULED
                    for cart in STORE.carts.values():
                        if cart["subscription_id"] == sub["id"] and cart["status"] == "DELIVERED":
                            cart["status"] = "RETRIEVAL_SCHEDULED"
                            touch(cart)
                    sub["suspended_reason"] = None
                    touch(sub)


def reconcile_routes():
    d = STORE.clock_date()
    for route in STORE.routes.values():
        if route["status"] == "PUBLISHED":
            if d > parse_date(route["effective_end_date"]):
                route["status"] = "ARCHIVED"
                touch(route)


def reconcile_carts():
    """RETRIEVAL_SCHEDULED -> RETRIEVED when clock_date > zone.season_end_date + 14 days."""
    for cart in STORE.carts.values():
        if cart["status"] != "RETRIEVAL_SCHEDULED":
            continue
        hh = STORE.households.get(cart["household_id"])
        if not hh:
            continue
        zone = STORE.zones.get(hh["zone_id"])
        if not zone:
            continue
        if STORE.clock_date() > parse_date(zone["season_end_date"]) + timedelta(days=14):
            cart["status"] = "RETRIEVED"
            touch(cart)
            recompute_cart_fees(cart["subscription_id"])


def reconcile_surge_events():
    """When event -> COMPLETED, CONFIRMED bookings -> NO_SHOW."""
    for event in STORE.surge_events.values():
        if surge_event_status(event) == "COMPLETED":
            for b in STORE.surge_bookings.values():
                if b["surge_event_id"] == event["id"] and b["status"] == "CONFIRMED":
                    b["status"] = "NO_SHOW"
                    touch(b)


def reconcile_campaigns():
    d = STORE.clock_date()
    for c in STORE.campaigns.values():
        if c["status"] in ("ACTIVE", "PAUSED") and d > parse_date(c["end_date"]):
            c["status"] = "COMPLETED"
            touch(c)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def compute_base_fee_cents(zone, service_model, signup_date) -> int:
    """PRD §3.2: UNIVERSAL -> 0; OPT_IN full fee on/before season start, else prorated."""
    if service_model == "UNIVERSAL":
        return 0
    start = parse_date(zone["season_start_date"])
    end = parse_date(zone["season_end_date"])
    if signup_date <= start:
        return zone["base_seasonal_fee_cents"]
    tsw = math.ceil((end - start).days / 7)
    full_weeks_remaining = (end - signup_date).days // 7
    if full_weeks_remaining < 0:
        full_weeks_remaining = 0
    return (zone["base_seasonal_fee_cents"] * full_weeks_remaining) // tsw


def recompute_cart_fees(subscription_id):
    """PRD §3.3: sum size surcharges + extra-cart fee over non-RETRIEVED carts,
    ordered created_at ASC; first cart exempt from extra-cart fee."""
    sub = STORE.subscriptions.get(subscription_id)
    if not sub:
        return
    carts = [c for c in STORE.carts.values()
             if c["subscription_id"] == subscription_id and c["status"] != "RETRIEVED"]
    carts.sort(key=lambda c: (c["created_at"], c["id"]))
    fees = sum(SIZE_SURCHARGE[c["size_gallons"]] for c in carts)
    fees += EXTRA_CART_FEE_CENTS * max(0, len(carts) - 1)
    sub["cart_fees_cents"] = fees
    sub["total_due_cents"] = sub["base_fee_cents"] + sub["cart_fees_cents"] + sub["surcharge_cents"]
    touch(sub)


def recompute_total_due(sub):
    sub["total_due_cents"] = sub["base_fee_cents"] + sub["cart_fees_cents"] + sub["surcharge_cents"]


def recompute_strikes(subscription_id):
    """DEPRECATED: strikes_this_season is a stored counter (see routes/inspections.py);
    a pure recount would undo the cure's reset-to-zero (PRD §3.5)."""
    sub = STORE.subscriptions.get(subscription_id)
    return sub["strikes_this_season"] if sub else 0


def recompute_entitlement(household_id):
    """PRD §3.8: per-pickup round_half_up to 2dp, then sum. COMPLETED tickets only,
    across all the household's subscriptions."""
    hh = STORE.households.get(household_id)
    if not hh:
        return
    sub_ids = {s["id"] for s in STORE.subscriptions.values() if s["household_id"] == household_id}
    total = Decimal("0")
    for t in STORE.tickets.values():
        if t["subscription_id"] in sub_ids and t["status"] == "COMPLETED":
            gal = (Decimal(t["weight_lbs"]) * COMPOST_YIELD_RATIO / COMPOST_LBS_PER_GALLON)
            gal = gal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            total += gal
    hh["compost_entitlement_gallons"] = float(total)
    touch(hh)


def recompute_credit_balance(household_id, bump_version=True):
    hh = STORE.households.get(household_id)
    if not hh:
        return
    bal = sum(c["amount_cents"] for c in STORE.credits.values()
              if c["household_id"] == household_id and c["status"] == "GRANTED")
    hh["credit_balance_cents"] = bal
    if bump_version:
        touch(hh)


def household_remaining_entitlement(household_id) -> Decimal:
    """Entitlement minus gallons consumed by FULFILLED claims."""
    hh = STORE.households.get(household_id)
    if not hh:
        return Decimal("0")
    ent = Decimal(str(hh.get("compost_entitlement_gallons", 0)))
    consumed = sum(c["gallons"] for c in STORE.claims.values()
                   if c["household_id"] == household_id and c["status"] == "FULFILLED")
    return ent - Decimal(consumed)


# ---------------------------------------------------------------------------
# Cascades (PRD §3.2, §3.5)
# ---------------------------------------------------------------------------
def suspend_subscription(sub):
    """Strike-threshold suspension side effects."""
    sub["status"] = "SUSPENDED"
    sub["surcharge_cents"] += REINSTATEMENT_SURCHARGE_CENTS
    sub["suspended_reason"] = "CONTAMINATION_STRIKES"
    recompute_total_due(sub)
    clock_d = STORE.clock_date()
    for t in STORE.tickets.values():
        if (t["subscription_id"] == sub["id"] and t["status"] == "SCHEDULED"
                and parse_date(t["service_date"]) > clock_d):
            t["status"] = "SKIPPED"
            touch(t)
    touch(sub)


def cancel_subscription_cascade(sub):
    """PRD §3.2 cancel cascades: bookings, carts, future tickets."""
    hh = STORE.households.get(sub["household_id"])
    zone_id = hh["zone_id"] if hh else None
    # Surge bookings of this household for events in this zone
    for b in list(STORE.surge_bookings.values()):
        if b["household_id"] != sub["household_id"]:
            continue
        if b["status"] not in ("CONFIRMED", "WAITLISTED"):
            continue
        event = STORE.surge_events.get(b["surge_event_id"])
        if not event or event["zone_id"] != zone_id:
            continue
        _cancel_booking(b, event)
    # Carts DELIVERED -> RETRIEVAL_SCHEDULED
    for cart in STORE.carts.values():
        if cart["subscription_id"] == sub["id"] and cart["status"] == "DELIVERED":
            cart["status"] = "RETRIEVAL_SCHEDULED"
            touch(cart)
    # Future SCHEDULED tickets -> SKIPPED
    clock_d = STORE.clock_date()
    for t in STORE.tickets.values():
        if (t["subscription_id"] == sub["id"] and t["status"] == "SCHEDULED"
                and parse_date(t["service_date"]) > clock_d):
            t["status"] = "SKIPPED"
            touch(t)
    recompute_cart_fees(sub["id"])


def _cancel_booking(booking, event):
    """Cancel one booking + waitlist promotion (PRD §3.7)."""
    was_confirmed = booking["status"] == "CONFIRMED"
    booking["status"] = "CANCELLED"
    touch(booking)
    if was_confirmed:
        event["reserved_slots"] -= 1
        # promote earliest WAITLISTED: created_at ASC, tie quantity_bundles ASC
        candidates = [b for b in STORE.surge_bookings.values()
                      if b["surge_event_id"] == event["id"] and b["status"] == "WAITLISTED"]
        candidates.sort(key=lambda b: (b["created_at"], b["quantity_bundles"]))
        while event["reserved_slots"] < event["capacity_slots"] and candidates:
            promoted = candidates.pop(0)
            promoted["status"] = "CONFIRMED"
            touch(promoted)
            event["reserved_slots"] += 1
    touch(event)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def zone_out(z):
    return {
        "id": z["id"], "name": z["name"], "service_model": z["service_model"],
        "season_start_date": z["season_start_date"], "season_end_date": z["season_end_date"],
        "base_seasonal_fee_cents": z["base_seasonal_fee_cents"],
        "universal_flat_credit_cents": z["universal_flat_credit_cents"],
        "max_strikes_per_season": z["max_strikes_per_season"],
        "status": zone_status(z),
        "created_at": z["created_at"], "updated_at": z["updated_at"], "version": z["version"],
    }


def household_out(h):
    return {
        "id": h["id"], "address_line": h["address_line"], "zone_id": h["zone_id"],
        "credit_balance_cents": h["credit_balance_cents"],
        "compost_entitlement_gallons": h["compost_entitlement_gallons"],
        "created_at": h["created_at"], "updated_at": h["updated_at"], "version": h["version"],
    }


def subscription_out(s):
    return {
        "id": s["id"], "household_id": s["household_id"], "season_year": s["season_year"],
        "service_model": s["service_model"], "status": s["status"],
        "base_fee_cents": s["base_fee_cents"], "cart_fees_cents": s["cart_fees_cents"],
        "surcharge_cents": s["surcharge_cents"], "total_due_cents": s["total_due_cents"],
        "paid_cents": s["paid_cents"], "strikes_this_season": s["strikes_this_season"],
        "suspended_reason": s["suspended_reason"],
        "created_at": s["created_at"], "updated_at": s["updated_at"], "version": s["version"],
    }


def cart_out(c):
    return {
        "id": c["id"], "household_id": c["household_id"], "subscription_id": c["subscription_id"],
        "size_gallons": c["size_gallons"], "status": c["status"],
        "delivered_at": c["delivered_at"], "surcharge_cents": c["surcharge_cents"],
        "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"],
    }


def route_out(r):
    return {
        "id": r["id"], "zone_id": r["zone_id"], "weekday": r["weekday"],
        "effective_start_date": r["effective_start_date"], "effective_end_date": r["effective_end_date"],
        "max_stops": r["max_stops"], "max_tonnage_lbs": r["max_tonnage_lbs"],
        "status": r["status"],
        "created_at": r["created_at"], "updated_at": r["updated_at"], "version": r["version"],
    }


def ticket_out(t):
    return {
        "id": t["id"], "subscription_id": t["subscription_id"], "route_id": t["route_id"],
        "service_date": t["service_date"], "status": t["status"],
        "weight_lbs": t["weight_lbs"], "completed_at": t["completed_at"],
        "missed_reported_by": t["missed_reported_by"], "missed_validated_by": t["missed_validated_by"],
        "created_at": t["created_at"], "updated_at": t["updated_at"], "version": t["version"],
    }


def inspection_out(i):
    return {
        "id": i["id"], "pickup_ticket_id": i["pickup_ticket_id"], "result": i["result"],
        "violation_codes": i["violation_codes"], "notes": i["notes"],
        "inspector_user_id": i["inspector_user_id"], "created_at": i["created_at"],
    }


def surge_event_out(e):
    return {
        "id": e["id"], "zone_id": e["zone_id"], "event_type": e["event_type"],
        "service_date": e["service_date"],
        "booking_window_start": e["booking_window_start"], "booking_window_end": e["booking_window_end"],
        "capacity_slots": e["capacity_slots"], "reserved_slots": e["reserved_slots"],
        "status": surge_event_status(e),
        "created_at": e["created_at"], "updated_at": e["updated_at"], "version": e["version"],
    }


def surge_booking_out(b):
    return {
        "id": b["id"], "surge_event_id": b["surge_event_id"], "household_id": b["household_id"],
        "quantity_bundles": b["quantity_bundles"], "status": b["status"],
        "created_at": b["created_at"], "updated_at": b["updated_at"], "version": b["version"],
    }


def facility_out(f):
    return {
        "id": f["id"], "name": f["name"],
        "daily_receiving_capacity_lbs": f["daily_receiving_capacity_lbs"],
        "safety_contamination_item_limit": f["safety_contamination_item_limit"],
        "status": f["status"], "season_accepted_lbs": f["season_accepted_lbs"],
        "created_at": f["created_at"], "updated_at": f["updated_at"], "version": f["version"],
    }


def delivery_out(d):
    return {
        "id": d["id"], "facility_id": d["facility_id"], "route_id": d["route_id"],
        "delivery_date": d["delivery_date"], "window_start": d["window_start"],
        "window_end": d["window_end"], "status": d["status"],
        "gross_weight_lbs": d["gross_weight_lbs"],
        "contaminated_item_count": d["contaminated_item_count"],
        "accepted_weight_lbs": d["accepted_weight_lbs"],
        "created_at": d["created_at"], "updated_at": d["updated_at"], "version": d["version"],
    }


def giveback_event_out(e):
    return {
        "id": e["id"], "zone_id": e["zone_id"], "event_date": e["event_date"],
        "per_household_cap_gallons": e["per_household_cap_gallons"],
        "initial_inventory_gallons": e["initial_inventory_gallons"],
        "remaining_gallons": e["remaining_gallons"],
        "status": giveback_event_status(e),
        "created_at": e["created_at"], "updated_at": e["updated_at"], "version": e["version"],
    }


def claim_out(c):
    return {
        "id": c["id"], "giveback_event_id": c["giveback_event_id"], "household_id": c["household_id"],
        "gallons": c["gallons"], "status": c["status"],
        "entitlement_snapshot_gallons": c["entitlement_snapshot_gallons"],
        "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"],
    }


def credit_out(c):
    return {
        "id": c["id"], "household_id": c["household_id"], "subscription_id": c["subscription_id"],
        "missed_pickup_ticket_id": c["missed_pickup_ticket_id"], "amount_cents": c["amount_cents"],
        "status": c["status"], "validated_by": c["validated_by"], "approved_by": c["approved_by"],
        "created_at": c["created_at"],
    }


def campaign_out(c):
    return {
        "id": c["id"], "zone_id": c["zone_id"], "channel": c["channel"], "topic": c["topic"],
        "budget_cents": c["budget_cents"], "audience_size": c["audience_size"],
        "cost_per_impression_cents": c["cost_per_impression_cents"], "end_date": c["end_date"],
        "spent_cents": c["spent_cents"], "status": c["status"],
        "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"],
    }
