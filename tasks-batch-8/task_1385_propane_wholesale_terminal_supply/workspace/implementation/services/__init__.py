"""Business logic services: pricing, cascades, allocation waterfall, payments.

All prices are integer millicents per gallon (mc); amounts are integer cents.
Every delivered-price segment (in-band product, overage product, freight,
winter) is rounded half-up to integer cents BEFORE summing.
"""
from datetime import timedelta

import clock
import db
from errors import err_no_index_published

OVERAGE_PREMIUM_MC = 25000
SPOT_PREMIUM_MC = 40000
CREDIT_WATCH_SURCHARGE_MC = 15000
WINTER_SURCHARGE_MC = 30000
LOAD_SERVICE_MINUTES = 90
DEADHEAD_BUFFER_MINUTES = 60
NSF_FEE_CENTS = 3500

INDEX_BASIS = "MT_BELVIEU"


# ---------------------------------------------------------------------------
# Timestamps / record bookkeeping
# ---------------------------------------------------------------------------

def stamp_now():
    return clock.now()


def touch(rec):
    """Refresh updated_at and bump version on a mutation of stored fields."""
    rec["updated_at"] = clock.now()
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Rounding helpers
# ---------------------------------------------------------------------------

def rhu_millicents(numer):
    """round_half_up(numer / 1000) with exact integer arithmetic."""
    return (2 * numer + 1000) // 2000


# ---------------------------------------------------------------------------
# Index resolution
# ---------------------------------------------------------------------------

def resolve_index(index_name, ref_date):
    """Publication for index_name with greatest effective_date <= ref_date."""
    best = None
    for p in db.price_index_publications.values():
        if p["index_name"] != index_name:
            continue
        if p["effective_date"] <= ref_date:
            if best is None or p["effective_date"] > best["effective_date"]:
                best = p
    return best


# ---------------------------------------------------------------------------
# Delivered price engine
# ---------------------------------------------------------------------------

def delivered_price(*, pricing_mode, volume_gal, contract, zone, terminal, ref_date, watch_mc):
    """Delivered total in integer cents for the given volume (segment rounding)."""
    V = volume_gal

    in_band = 0
    over = 0
    needs_index = False
    if pricing_mode == "SPOT":
        needs_index = V > 0
    elif contract is not None:
        in_band = min(V, max(0, contract["volume_committed_gal"] - contract["volume_drawn_gal"]))
        over = V - in_band
        if pricing_mode == "INDEX" and in_band > 0:
            needs_index = True
        if over > 0:
            needs_index = True

    base_index_mc = None
    if needs_index:
        pub = resolve_index(INDEX_BASIS, ref_date)
        if pub is None:
            raise err_no_index_published()
        base_index_mc = pub["price_mc_per_gal"]

    if pricing_mode == "SPOT":
        product_cents = rhu_millicents(V * (base_index_mc + SPOT_PREMIUM_MC + watch_mc))
    else:
        if pricing_mode == "FIXED":
            in_band_cents = rhu_millicents(in_band * contract["fixed_price_mc_per_gal"])
        else:  # INDEX
            in_band_cents = rhu_millicents(in_band * (base_index_mc + watch_mc))
        over_cents = (
            rhu_millicents(over * (base_index_mc + OVERAGE_PREMIUM_MC + watch_mc)) if over > 0 else 0
        )
        product_cents = in_band_cents + over_cents

    freight_cents = max(zone["min_freight_cents"], rhu_millicents(V * zone["freight_mc_per_gal"]))

    winter_cents = 0
    if terminal["allocation_posture"] == "CURTAILED":
        winter_cents = rhu_millicents(V * WINTER_SURCHARGE_MC)

    return product_cents + freight_cents + winter_cents


# ---------------------------------------------------------------------------
# Credit exposure helpers
# ---------------------------------------------------------------------------

def committed_excluding(dealer, exclude_order_id=None):
    """Committed exposure for the dealer, optionally ignoring one order."""
    total = dealer["fee_balance_cents"]
    for o in db.delivery_orders.values():
        if o["dealer_id"] != dealer["id"]:
            continue
        if exclude_order_id is not None and o["id"] == exclude_order_id:
            continue
        if o["invoice_status"] == "OPEN":
            total += o["open_balance_cents"] or 0
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


def restamp_provisional(order):
    """Recompute provisional_total_cents for an ALLOCATED/SCHEDULED order in place.

    Provisional variant: ref_date = current logical date; winter leg uses the
    terminal's CURRENT posture; watch surcharge from the dealer's status
    evaluated excluding this order.
    """
    terminal = db.terminals[order["terminal_id"]]
    zone = db.freight_zones[order["freight_zone_id"]]
    dealer = db.dealers[order["dealer_id"]]
    contract = (
        db.dealer_contracts.get(order["dealer_contract_id"]) if order["dealer_contract_id"] else None
    )
    committed = committed_excluding(dealer, exclude_order_id=order["id"])
    status_before = credit_status_of(committed, dealer["credit_limit_cents"])
    watch_mc = CREDIT_WATCH_SURCHARGE_MC if status_before == "WATCH" else 0
    order["provisional_total_cents"] = delivered_price(
        pricing_mode=order["pricing_mode"],
        volume_gal=order["allocated_gal"],
        contract=contract,
        zone=zone,
        terminal=terminal,
        ref_date=clock.now().date(),
        watch_mc=watch_mc,
    )
    order["updated_at"] = clock.now()
    order["version"] += 1


# ---------------------------------------------------------------------------
# Cold snap cascades
# ---------------------------------------------------------------------------

def terminal_curtail(terminal):
    """NORMAL -> CURTAILED with full provisional reprice cascade."""
    terminal["allocation_posture"] = "CURTAILED"
    touch(terminal)
    for o in db.delivery_orders.values():
        if o["terminal_id"] == terminal["id"] and o["fulfillment_status"] in ("ALLOCATED", "SCHEDULED"):
            restamp_provisional(o)


def terminal_restore(terminal):
    """CURTAILED -> NORMAL with surcharge removal, SHORTED requeue, FIFO auto-allocate."""
    terminal["allocation_posture"] = "NORMAL"
    touch(terminal)
    for o in db.delivery_orders.values():
        if o["terminal_id"] == terminal["id"] and o["fulfillment_status"] in ("ALLOCATED", "SCHEDULED"):
            restamp_provisional(o)
    # SHORTED -> REQUESTED (created_at preserved)
    for o in db.delivery_orders.values():
        if o["terminal_id"] == terminal["id"] and o["fulfillment_status"] == "SHORTED":
            o["fulfillment_status"] = "REQUESTED"
            o["allocated_gal"] = None
            o["provisional_total_cents"] = None
            touch(o)
    # FIFO auto-allocate: created_at ASC (tie: requested_gal DESC), independent per order
    pending = [
        o
        for o in db.delivery_orders.values()
        if o["terminal_id"] == terminal["id"] and o["fulfillment_status"] == "REQUESTED"
    ]
    pending.sort(key=lambda o: (o["_seq"], -o["requested_gal"]))
    for o in pending:
        from serializers import available_to_promise

        if available_to_promise(terminal) >= o["requested_gal"]:
            o["fulfillment_status"] = "ALLOCATED"
            o["allocated_gal"] = o["requested_gal"]
            touch(o)
            restamp_provisional(o)


# ---------------------------------------------------------------------------
# Dealer contract order-cancellation cascade (shared by cancel/supersede)
# ---------------------------------------------------------------------------

def unschedule_order(order):
    order["truck_id"] = None
    order["est_trip_minutes"] = None
    order["planned_load_start"] = None
    order["planned_load_end"] = None
    order["fulfillment_status"] = "ALLOCATED"


def cascade_cancel_contract_orders(contract):
    for o in db.delivery_orders.values():
        if o["dealer_contract_id"] != contract["id"]:
            continue
        if o["fulfillment_status"] in ("REQUESTED", "ALLOCATED"):
            o["fulfillment_status"] = "CANCELLED"
            if o["invoice_status"] == "NOT_READY":
                o["invoice_status"] = "VOID"
            touch(o)
        elif o["fulfillment_status"] == "SCHEDULED":
            unschedule_order(o)
            o["fulfillment_status"] = "CANCELLED"
            if o["invoice_status"] == "NOT_READY":
                o["invoice_status"] = "VOID"
            touch(o)
        # LOADED / DELIVERED / CANCELLED unaffected


# ---------------------------------------------------------------------------
# Allocation pro-rata waterfall
# ---------------------------------------------------------------------------

def allocation_tier(order):
    if order["pricing_mode"] == "FIXED":
        return 1
    if order["pricing_mode"] == "INDEX":
        return 2
    return 3


def allocation_weight(order):
    tier = allocation_tier(order)
    if tier == 3:
        return 1
    total = 0
    for c in db.dealer_contracts.values():
        if (
            c["dealer_id"] == order["dealer_id"]
            and c["terminal_id"] == order["terminal_id"]
            and c["status"] == "ACTIVE"
        ):
            total += c["volume_committed_gal"]
    return total


def compute_waterfall(terminal, run):
    """Populate run.pool_gal and run.results per allocation_pro_rata_waterfall."""
    from serializers import available_to_promise

    pool = available_to_promise(terminal)
    run["pool_gal"] = pool

    eligible = [
        o
        for o in db.delivery_orders.values()
        if o["terminal_id"] == terminal["id"]
        and o["fulfillment_status"] == "REQUESTED"
        and o["_seq"] < run["_seq"]
    ]
    eligible.sort(key=lambda o: (o["_seq"], -o["requested_gal"]))

    results = {}  # order_id -> allocated gallons
    remaining_pool = pool
    for tier in (1, 2, 3):
        if remaining_pool <= 0:
            break
        candidates = [
            o
            for o in eligible
            if allocation_tier(o) == tier and results.get(o["id"], None) is None
        ]
        if not candidates:
            continue
        W = sum(allocation_weight(o) for o in candidates)
        if W <= 0:
            continue
        # raw share exact rational: pool * w / W ; floor per order, capped at request
        shares = {}
        for o in candidates:
            raw = (remaining_pool * allocation_weight(o)) // W  # floor of exact rational
            shares[o["id"]] = min(o["requested_gal"], raw)
        allocated_sum = sum(shares.values())
        remainder = remaining_pool - allocated_sum
        # distribute remainder one gallon at a time, created_at ASC (tie: requested DESC),
        # looping until remainder == 0 or all satisfied
        while remainder > 0:
            progressed = False
            for o in candidates:  # candidates already sorted created_at ASC / requested DESC
                if remainder <= 0:
                    break
                if shares[o["id"]] < o["requested_gal"]:
                    shares[o["id"]] += 1
                    remainder -= 1
                    progressed = True
            if not progressed:
                break
        for oid, share in shares.items():
            results[oid] = share
        remaining_pool -= sum(shares.values())

    run["results"] = [
        {
            "order_id": o["id"],
            "allocated_gal": results.get(o["id"], 0),
            "outcome": "ALLOCATED" if results.get(o["id"], 0) > 0 else "SHORTED",
        }
        for o in eligible
    ]


# ---------------------------------------------------------------------------
# Trip estimate / ISO week helpers
# ---------------------------------------------------------------------------

def est_trip_minutes(zone):
    return LOAD_SERVICE_MINUTES + 2 * zone["one_way_drive_minutes"]


def iso_week_monday(dt):
    from datetime import timezone

    d = dt.astimezone(timezone.utc).date()
    return d - timedelta(days=d.isoweekday() - 1)
