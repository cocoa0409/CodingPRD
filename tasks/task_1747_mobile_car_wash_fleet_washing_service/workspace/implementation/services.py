"""Business logic: pricing, planning, water budget, cascades, billing."""

from datetime import datetime, timedelta
from decimal import Decimal

from db import store
from util import now, clock_date, touch, stamp_new, gal_round, round_half_up_cents

# ----------------------------------------------------------------------------
# Constants (scaffold calculations table)
# ----------------------------------------------------------------------------

RETAIL_CARD = {
    "SEDAN": 3500,
    "SUV_PICKUP": 4500,
    "VAN_BOXTRUCK": 7000,
    "HEAVY_FLEET": 12000,
}

GROSS_GAL = {"SEDAN": 8, "SUV_PICKUP": 10, "VAN_BOXTRUCK": 15, "HEAVY_FLEET": 25}

RECOVERY = {"NONE": Decimal("0"), "BASIC": Decimal("0.60"), "ADVANCED": Decimal("0.85")}

SERVICE_MINUTES = {"SEDAN": 20, "SUV_PICKUP": 25, "VAN_BOXTRUCK": 35, "HEAVY_FLEET": 50}

CLAIM_CAPS = {"SEDAN": 25000, "SUV_PICKUP": 30000, "VAN_BOXTRUCK": 40000, "HEAVY_FLEET": 60000}

DRIVE_MINUTES = 20

OPEN_REWASH_STATES = ("DRAFT", "SCHEDULED", "ASSIGNED", "IN_PROGRESS", "WEATHER_HELD")


def parse_d(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


# ----------------------------------------------------------------------------
# Pricing (wash_quote_cents)
# ----------------------------------------------------------------------------

def active_contract_for(customer_id):
    for c in sorted(store.contracts.values(), key=lambda r: r["_seq"]):
        if c["customer_id"] == customer_id and c["status"] == "ACTIVE":
            return c
    return None


def rate_card_for(customer_id):
    contract = active_contract_for(customer_id)
    if contract is None:
        return RETAIL_CARD
    return {
        "SEDAN": contract["sedan_rate_cents"],
        "SUV_PICKUP": contract["suv_pickup_rate_cents"],
        "VAN_BOXTRUCK": contract["van_boxtruck_rate_cents"],
        "HEAVY_FLEET": contract["heavy_fleet_rate_cents"],
    }


def wash_quote_cents(customer_id, site, vehicle_classes):
    """Pinned evaluation order: subtotal -> volume discount -> reclaim surcharge."""
    card = rate_card_for(customer_id)
    subtotal = sum(card[cls] for cls in vehicle_classes)
    n = len(vehicle_classes)
    if n >= 20:
        pct = Decimal("0.15")
    elif n >= 10:
        pct = Decimal("0.10")
    elif n >= 5:
        pct = Decimal("0.05")
    else:
        pct = Decimal("0")
    discount = round_half_up_cents(Decimal(subtotal) * pct)
    after = subtotal - discount
    if site["water_reclaim_required"]:
        surcharge = round_half_up_cents(Decimal(after) * Decimal("0.08"))
    else:
        surcharge = 0
    return after + surcharge


# ----------------------------------------------------------------------------
# Water budget (route_water_budget / discharge_projection)
# ----------------------------------------------------------------------------

def gross_gallons(vehicle_classes):
    return Decimal(sum(GROSS_GAL[cls] for cls in vehicle_classes))


def van_recovery(van):
    return RECOVERY[van["reclaim_system"]]


def net_gallons(vehicle_classes, van):
    return gal_round(gross_gallons(vehicle_classes) * (Decimal("1") - van_recovery(van)))


def van_free_gal(van):
    return Decimal(str(van["water_loaded_gal"])) - Decimal(str(van["water_used_gal"])) \
        - Decimal(str(van["water_reserved_gal"]))


def van_water_mutated(van):
    touch(van)


# ----------------------------------------------------------------------------
# Stop planning (stop_planning)
# ----------------------------------------------------------------------------

def lot_setup_minutes(site):
    sqft = site["lot_size_sqft"]
    if sqft < 10000:
        return 15
    if sqft < 50000:
        return 25
    return 40


def service_minutes(vehicle_classes):
    return sum(SERVICE_MINUTES[cls] for cls in vehicle_classes)


def stops_of_route(route_id):
    return sorted(
        (s for s in store.stops.values() if s["route_id"] == route_id),
        key=lambda s: s["sequence"],
    )


def order_stop(order_id):
    """The order's current non-cancelled stop, if any."""
    for s in store.stops.values():
        if s["wash_order_id"] == order_id and s["status"] != "CANCELLED":
            return s
    return None


# ----------------------------------------------------------------------------
# Wash order helpers
# ----------------------------------------------------------------------------

def hold_order(order):
    order["status"] = "WEATHER_HELD"
    order["hold_reason"] = "WEATHER_FREEZE"
    order["held_at"] = now()
    touch(order)


def release_stop_water(stop, route, van_touched):
    """Release a stop's reservation from the route's van (once per van)."""
    van = store.vans.get(route["van_id"])
    if van is not None and stop["status"] in ("PLANNED", "ARRIVED"):
        van["water_reserved_gal"] = gal_round(
            Decimal(str(van["water_reserved_gal"])) - Decimal(str(stop["reserved_water_gal"])))
        if van["id"] not in van_touched:
            van_water_mutated(van)
            van_touched.add(van["id"])


def cancel_order(order, reason, van_touched=None):
    """Cancel an order in any cancellable state, unwinding its stop if present.

    Applies the rewash compensation: a cancelled rewash reverts its original
    from REWASH_PENDING back to COMPLETED.
    """
    if van_touched is None:
        van_touched = set()
    routes_touched = set()
    stop = order_stop(order["id"])
    if stop is not None and stop["status"] in ("PLANNED", "ARRIVED"):
        route = store.routes.get(stop["route_id"])
        release_stop_water(stop, route, van_touched)
        stop["status"] = "CANCELLED"
        touch(stop)
        if route is not None and route["id"] not in routes_touched:
            touch(route)
            routes_touched.add(route["id"])
    order["status"] = "CANCELLED"
    order["cancel_reason"] = reason
    touch(order)
    # Rewash compensation (any cancellation before completion).
    if order["rewash_of_id"] is not None:
        original = store.orders.get(order["rewash_of_id"])
        if original is not None and original["status"] == "REWASH_PENDING":
            original["status"] = "COMPLETED"
            touch(original)


def create_rewash_order(original):
    """Create the guarantee rewash order per PRD 3.8."""
    next_day = clock_date() + timedelta(days=1)
    start = datetime(next_day.year, next_day.month, next_day.day, 8, 0, 0)
    from datetime import timezone
    start = start.replace(tzinfo=timezone.utc)
    end = start + timedelta(hours=2)
    rec = {
        "customer_id": original["customer_id"],
        "site_id": original["site_id"],
        "subscription_id": None,
        "vehicle_ids": list(original["vehicle_ids"]),
        "scheduled_window_start": start,
        "scheduled_window_end": end,
        "requires_inspection": False,
        "status": "SCHEDULED",
        "billing_status": "WAIVED",
        "quote_cents": 0,
        "final_cents": None,
        "vehicles_washed_ids": None,
        "rewash_of_id": original["id"],
        "hold_reason": None,
        "held_at": None,
        "cancel_reason": None,
        "completed_at": None,
    }
    stamp_new(rec)
    store.orders[rec["id"]] = rec
    return rec


def has_open_rewash(order_id):
    for o in store.orders.values():
        if o["rewash_of_id"] == order_id and o["status"] in OPEN_REWASH_STATES:
            return True
    return False


def complete_order(order, vehicles_washed_ids):
    """COMPLETE side effects: pricing, water draw, stop DONE, rewash close."""
    site = store.sites[order["site_id"]]
    classes = [store.vehicles[vid]["vehicle_class"] for vid in vehicles_washed_ids]
    if order["rewash_of_id"] is not None:
        # Rewash orders always price 0 regardless of the pricing formula.
        order["final_cents"] = 0
    else:
        order["final_cents"] = wash_quote_cents(order["customer_id"], site, classes)
    order["vehicles_washed_ids"] = list(vehicles_washed_ids)
    order["completed_at"] = now()
    order["status"] = "COMPLETED"
    stop = order_stop(order["id"])
    if stop is not None and stop["status"] in ("PLANNED", "ARRIVED"):
        route = store.routes.get(stop["route_id"])
        van = store.vans.get(route["van_id"]) if route else None
        actual_net = net_gallons(classes, van)
        if van is not None:
            van["water_reserved_gal"] = gal_round(
                Decimal(str(van["water_reserved_gal"])) - Decimal(str(stop["reserved_water_gal"])))
            van["water_used_gal"] = gal_round(
                Decimal(str(van["water_used_gal"])) + actual_net)
            van_water_mutated(van)
        stop["status"] = "DONE"
        touch(stop)
        if route is not None:
            touch(route)
    touch(order)
    # A completed rewash closes its original.
    if order["rewash_of_id"] is not None:
        original = store.orders.get(order["rewash_of_id"])
        if original is not None and original["status"] == "REWASH_PENDING":
            original["status"] = "CLOSED"
            touch(original)


# ----------------------------------------------------------------------------
# Site suspension cascade (PRD 3.7)
# ----------------------------------------------------------------------------

def suspend_site(site, reason):
    site["status"] = "SUSPENDED"
    site["suspension_reason"] = reason
    touch(site)
    van_touched = set()
    for order in sorted(store.orders.values(), key=lambda r: r["_seq"]):
        if order["site_id"] == site["id"] and order["status"] in ("SCHEDULED", "ASSIGNED"):
            cancel_order(order, "SITE_SUSPENDED", van_touched=van_touched)


def confirmed_incident_open(site_id, exclude_id=None):
    for inc in store.incidents.values():
        if inc["site_id"] == site_id and inc["status"] == "CONFIRMED" and inc["id"] != exclude_id:
            return True
    return False


# ----------------------------------------------------------------------------
# Route cancellation cascade (manual + weather, PRD 3.4/3.6)
# ----------------------------------------------------------------------------

def cancel_route(route, reason, weather):
    route["status"] = "CANCELLED"
    route["cancel_reason"] = reason
    van_touched = set()
    for stop in stops_of_route(route["id"]):
        if stop["status"] in ("PLANNED", "ARRIVED"):
            release_stop_water(stop, route, van_touched)
            stop["status"] = "CANCELLED"
            touch(stop)
            order = store.orders.get(stop["wash_order_id"])
            if order is not None and order["status"] == "ASSIGNED":
                if weather:
                    hold_order(order)
                else:
                    order["status"] = "SCHEDULED"
                    touch(order)
    touch(route)


def weather_freeze(eval_date):
    """Freeze cascade; returns (cancelled_route_ids, held_order_ids)."""
    eval_date_str = eval_date.strftime("%Y-%m-%d")
    cancelled_route_ids = []
    held_order_ids = []
    for route in sorted(store.routes.values(), key=lambda r: r["_seq"]):
        if route["route_date"] == eval_date_str and route["status"] in ("PUBLISHED", "LOCKED"):
            before = set()
            for stop in stops_of_route(route["id"]):
                if stop["status"] in ("PLANNED", "ARRIVED"):
                    order = store.orders.get(stop["wash_order_id"])
                    if order is not None and order["status"] == "ASSIGNED":
                        before.add(order["id"])
            cancel_route(route, "WEATHER_FREEZE", weather=True)
            cancelled_route_ids.append(route["id"])
            held_order_ids.extend(sorted(before, key=lambda oid: store.orders[oid]["_seq"]))
    # Unrouted SCHEDULED orders whose window date equals the evaluation date.
    for order in sorted(store.orders.values(), key=lambda r: r["_seq"]):
        if order["status"] == "SCHEDULED" \
                and order["scheduled_window_start"].date() == eval_date:
            hold_order(order)
            held_order_ids.append(order["id"])
    return cancelled_route_ids, held_order_ids


# ----------------------------------------------------------------------------
# Early termination fee (early_termination_fee)
# ----------------------------------------------------------------------------

def early_termination_fee(contract):
    cd = clock_date()
    end = parse_d(contract["end_date"])
    if cd >= end:
        return 0
    months = 0
    year, month = cd.year, cd.month
    # iterate months strictly after the clock month up to the end month
    while True:
        month += 1
        if month > 12:
            month = 1
            year += 1
        if (year, month) > (end.year, end.month):
            break
        months += 1
    return round_half_up_cents(
        Decimal(months) * Decimal(contract["monthly_minimum_cents"]) * Decimal("0.50"))


# ----------------------------------------------------------------------------
# Fleet invoicing (fleet_invoice_billing + claim_credit_cap)
# ----------------------------------------------------------------------------

def period_of_dt(dt):
    return "%04d-%02d" % (dt.year, dt.month)


def compute_invoice_lines(contract, period, variant):
    customer_id = contract["customer_id"]
    lines = []
    for order in sorted(store.orders.values(), key=lambda r: r["_seq"]):
        if order["customer_id"] != customer_id:
            continue
        if order["status"] in ("COMPLETED", "REWASH_PENDING", "CLOSED") \
                and order["completed_at"] is not None \
                and period_of_dt(order["completed_at"]) == period \
                and order["billing_status"] != "WAIVED":
            lines.append((order, order["final_cents"]))
        elif variant == "PROJECTION" \
                and order["status"] in ("SCHEDULED", "ASSIGNED", "IN_PROGRESS") \
                and period_of_dt(order["scheduled_window_start"]) == period:
            lines.append((order, order["quote_cents"]))
    return lines


def build_invoice_record(contract, period, variant):
    lines = compute_invoice_lines(contract, period, variant)
    pct = Decimal(str(contract["loyalty_credit_pct"]))
    charges = 0
    credits = 0
    for _order, charge in lines:
        charges += charge
        credits += round_half_up_cents(Decimal(charge) * pct)
    net_before = charges - credits
    minimum = contract["monthly_minimum_cents"]
    billed = max(net_before, minimum)
    minimum_applied = net_before < minimum
    cap = round_half_up_cents(Decimal(billed) * Decimal("0.25"))
    eligible = 0
    customer_id = contract["customer_id"]
    for claim in store.claims.values():
        if claim["status"] != "PAID":
            continue
        order = store.orders.get(claim["wash_order_id"])
        if order is None or order["customer_id"] != customer_id:
            continue
        if order["completed_at"] is not None \
                and period_of_dt(order["completed_at"]) == period:
            eligible += claim["approved_amount_cents"] or 0
    claim_credits = min(eligible, cap)
    rec = {
        "fleet_contract_id": contract["id"],
        "period_month": period,
        "variant": variant,
        "status": "PREVIEW" if variant == "PROJECTION" else "DRAFT",
        "line_count": len(lines),
        "charges_cents": charges,
        "loyalty_credits_cents": credits,
        "minimum_applied": minimum_applied,
        "billed_cents": billed,
        "claim_credits_cents": claim_credits,
        "net_due_cents": billed - claim_credits,
        "_line_order_ids": [o["id"] for o, _ in lines],
    }
    stamp_new(rec)
    store.invoices[rec["id"]] = rec
    return rec
