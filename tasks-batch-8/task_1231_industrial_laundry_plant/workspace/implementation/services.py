"""Business logic: cascades, scheduling guards, billing calculations."""

from datetime import timedelta, date
from decimal import Decimal

import clock
import db
from util import D, round0, round2, round4

# ------------------------------------------------------------ constants
MAX_REWASH_COUNT = 2
RENTAL_RATE_PCT = 2
CREDIT_RATE_PCT = 60
TIER1_LBS = 5000
TIER1_PCT = 3
TIER2_LBS = 20000
TIER2_PCT = 7
TIER_A_CAP = 100000   # cents
TIER_A_PCT = 50
TIER_B_CAP = 500000   # cents
TIER_B_PCT = 75
TIER_C_PCT = 100
BUFFER_MINUTES = 10

MACHINE_ACTIVE_STATES = {"STAGED", "RUNNING", "AWAITING_TEST", "REWASH_PENDING"}
LINE_ACTIVE_STATES = {"QUEUED", "TALLIED"}

FORMULA_ESCALATION = {
    "WF_STANDARD": "WF_HEAVY_SOIL",
    "WF_CHEM_DISINFECT": "WF_THERMAL_DISINFECT",
    "WF_THERMAL_DISINFECT": "WF_THERMAL_DISINFECT",
    "WF_HEAVY_SOIL": "WF_HEAVY_SOIL",
}


# ------------------------------------------------------------ lookups / graph walks
def stop_of_batch(batch):
    return db.stops.get(batch["stop_id"])


def route_of_stop(stop):
    return db.routes.get(stop["route_id"])


def customer_of_stop(stop):
    return db.customers.get(stop["customer_id"])


def plant_of_batch(batch):
    stop = stop_of_batch(batch)
    route = route_of_stop(stop) if stop else None
    return db.plants.get(route["plant_id"]) if route else None


def customer_of_wash_load(load):
    batch = db.sort_batches.get(load["batch_id"])
    if not batch:
        return None
    stop = stop_of_batch(batch)
    if not stop:
        return None
    return stop["customer_id"]


def plant_of_wash_load(load):
    batch = db.sort_batches.get(load["batch_id"])
    return db.plants.get(batch["plant_id"]) if batch else None


def accepted_pieces(batch_id, category_id):
    return sum(
        it["pieces"]
        for it in db.sort_items.values()
        if it["batch_id"] == batch_id
        and it["category_id"] == category_id
        and it["disposition"] == "ACCEPTED"
    )


def deliveries_of_stop(stop_id):
    return [d for d in db.sorted_all(db.deliveries) if d["stop_id"] == stop_id]


def discrepancies_of_delivery(delivery_id):
    return [x for x in db.sorted_all(db.discrepancies) if x["delivery_id"] == delivery_id]


# ------------------------------------------------------------ garment cascades
def garment_cascade(customer, from_state, to_state, category_id=None, limit=None):
    if not customer or not customer.get("chip_tracking_enabled"):
        return
    gs = [
        g
        for g in db.garments.values()
        if g["customer_id"] == customer["id"]
        and g["state"] == from_state
        and (category_id is None or g["category_id"] == category_id)
    ]
    if limit is not None:
        # Earliest created first; ties broken by chip_code ascending.
        gs.sort(key=lambda g: (g["created_at"], g["chip_code"]))
        gs = gs[:limit]
    for g in gs:
        g["state"] = to_state
        db.touch(g)


# ------------------------------------------------------------ stop / delivery lifecycle helpers
def maybe_advance_stop_after_delivery(stop):
    """When the last MANIFESTED delivery of the stop resolves, stop -> DELIVERED."""
    if stop["status"] != "PICKED_UP":
        return
    if not any(d["status"] == "MANIFESTED" for d in deliveries_of_stop(stop["id"])):
        stop["status"] = "DELIVERED"
        db.touch(stop)


def maybe_close_stop(stop):
    ds = deliveries_of_stop(stop["id"])
    if not ds:
        return
    if all(d["status"] in ("CONFIRMED", "SETTLED") for d in ds):
        if stop["status"] == "DELIVERED":
            stop["status"] = "CLOSED"
            db.touch(stop)
        elif stop["status"] == "DISPUTED" and any(d["status"] == "SETTLED" for d in ds):
            stop["status"] = "CLOSED"
            db.touch(stop)


def maybe_settle_delivery(delivery):
    """Delivery DISPUTED -> SETTLED once all its discrepancies are terminal."""
    if delivery["status"] != "DISPUTED":
        return
    discs = discrepancies_of_delivery(delivery["id"])
    if discs and all(x["status"] in ("CREDITED", "REJECTED") for x in discs):
        delivery["status"] = "SETTLED"
        db.touch(delivery)
        stop = db.stops.get(delivery["stop_id"])
        if stop:
            maybe_close_stop(stop)


# ------------------------------------------------------------ scheduling guards
def machine_conflict(machine_id, start, end, exclude_id=None):
    """Half-open [start, end) overlap against active loads on the same machine."""
    for load in db.wash_loads.values():
        if load["machine_id"] != machine_id or load["id"] == exclude_id:
            continue
        if load["status"] not in MACHINE_ACTIVE_STATES:
            continue
        os_ = clock.parse_dt(load["scheduled_start"])
        oe = clock.parse_dt(load["scheduled_end"])
        if os_ is None or oe is None:
            continue
        if os_ < end and start < oe:
            return True
    return False


def line_conflict(line_id, start, end, exclude_id=None):
    """Buffered closed-interval overlap against QUEUED/TALLIED runs on the line."""
    buf = timedelta(minutes=BUFFER_MINUTES)
    bs, be = start - buf, end + buf
    for run in db.finish_runs.values():
        if run["line_id"] != line_id or run["id"] == exclude_id:
            continue
        if run["status"] not in LINE_ACTIVE_STATES:
            continue
        os_ = clock.parse_dt(run["scheduled_start"])
        oe = clock.parse_dt(run["scheduled_end"])
        if os_ is None or oe is None:
            continue
        os_ -= buf
        oe += buf
        if os_ <= be and bs <= oe:
            return True
    return False


# ------------------------------------------------------------ billing calculations
def _projected_lbs(load, cat):
    return round2(D(accepted_pieces(load["batch_id"], load["category_id"])) * D(cat["piece_weight_lb"]))


def linen_charges(customer, start_d, end_d, estimated=False, override_par=None):
    """COG tiered or RENTAL forward-looking linen charge, whole cents."""
    if customer["billing_mode"] == "COG":
        by_cat = {}
        for load in db.wash_loads.values():
            if customer_of_wash_load(load) != customer["id"]:
                continue
            cat = db.categories.get(load["category_id"])
            if not cat:
                continue
            if load["status"] == "FINISHED":
                unloaded = load.get("_unloaded_at")
                if unloaded is None:
                    continue
                if not (start_d <= unloaded.date() < end_d):
                    continue
                lbs = D(load.get("clean_weight_lb") or 0)
            elif estimated and load["status"] in (
                "STAGED",
                "RUNNING",
                "AWAITING_TEST",
                "TESTED_PASS",
                "REWASH_PENDING",
            ):
                lbs = _projected_lbs(load, cat)
            else:
                continue
            key = load["category_id"]
            by_cat[key] = by_cat.get(key, D(0)) + lbs
        volume = sum(by_cat.values(), D(0))
        if volume >= D(TIER2_LBS):
            discount = D(TIER2_PCT)
        elif volume >= D(TIER1_LBS):
            discount = D(TIER1_PCT)
        else:
            discount = D(0)
        total = 0
        for cid, lbs in by_cat.items():
            cat = db.categories[cid]
            gross = D(round0(lbs * D(cat["cog_wash_rate_cents_per_lb"])))
            net = round0(gross * (D(100) - discount) / D(100))
            total += net
        return total
    # RENTAL: 2% of replacement cost per piece-day over whole days.
    days = (end_d - start_d).days
    total = 0
    for par in db.par_levels.values():
        if par["customer_id"] != customer["id"]:
            continue
        cat = db.categories.get(par["category_id"])
        if not cat:
            continue
        pp = override_par if override_par is not None else par["par_pieces"]
        line = D(pp) * D(cat["replacement_cost_cents"]) * D(RENTAL_RATE_PCT) * D(days) / D(100)
        total += round0(line)
    return total


def tiered_excess_cents(reading, plant):
    """Tiered pass-through of the month's excess utility cost (Decimal cents)."""
    kwh_rate = D(reading["kwh_rate_cents"])
    gal_rate = D(reading["gallon_rate_cents"])
    actual = D(reading["kwh_used"]) * kwh_rate + D(reading["gallons_used"]) * gal_rate
    lbs = D(reading["clean_lbs_processed"])
    baseline = D(
        round0(
            lbs * D(plant["utility_baseline_kwh_per_lb"]) * kwh_rate
            + lbs * D(plant["utility_baseline_gal_per_lb"]) * gal_rate
        )
    )
    excess = actual - baseline
    if excess < 0:
        excess = D(0)
    a = min(excess, D(TIER_A_CAP)) * D(TIER_A_PCT) / D(100)
    b = max(D(0), min(excess, D(TIER_B_CAP)) - D(TIER_A_CAP)) * D(TIER_B_PCT) / D(100)
    c = max(D(0), excess - D(TIER_B_CAP)) * D(TIER_C_PCT) / D(100)
    return a + b + c


def customer_month_lbs(customer_id, month):
    """Clean pounds from the customer's FINISHED loads unloaded in month YYYY-MM."""
    total = D(0)
    for load in db.wash_loads.values():
        if load["status"] != "FINISHED":
            continue
        if customer_of_wash_load(load) != customer_id:
            continue
        unloaded = load.get("_unloaded_at")
        if unloaded is None:
            continue
        if unloaded.strftime("%Y-%m") == month:
            total += D(load.get("clean_weight_lb") or 0)
    return total


def find_reading(plant_id, month):
    for r in db.utility_readings.values():
        if r["plant_id"] == plant_id and r["period_month"] == month:
            return r
    return None


def utility_surcharge(customer, plant, month):
    """Returns (surcharge_cents, variant). Actual when a reading exists for the
    invoice month, else estimated from the trailing window."""
    cl = customer_month_lbs(customer["id"], month)
    reading = find_reading(plant["id"], month)
    if reading is not None:
        te = tiered_excess_cents(reading, plant)
        denom = D(reading["clean_lbs_processed"])
        share = round4(cl / denom * D(100)) if denom != 0 else D(0)
        return round0(te * share / D(100)), "actual"
    prev = sorted(
        (
            r
            for r in db.utility_readings.values()
            if r["plant_id"] == plant["id"] and r["period_month"] < month
        ),
        key=lambda r: r["period_month"],
        reverse=True,
    )[:3]
    if not prev:
        return 0, "estimated"
    avg = D(round0(sum((tiered_excess_cents(r, plant) for r in prev), D(0)) / D(len(prev))))
    denom = D(prev[0]["clean_lbs_processed"])
    share = round4(cl / denom * D(100)) if denom != 0 else D(0)
    return round0(avg * share / D(100)), "estimated"


def recompute_invoice_total(inv):
    inv["total_due_cents"] = max(
        0,
        inv["linen_charges_cents"]
        + inv["lost_item_charges_cents"]
        + inv["utility_surcharge_cents"]
        - inv["credits_cents"],
    )


def unbilled_lost_charges(customer_id):
    return sum(
        e["charge_cents"]
        for e in db.lost_queue
        if e["customer_id"] == customer_id and e["invoice_id"] is None
    )


def drain_lost_charges(customer_id, invoice_id):
    total = 0
    for e in db.lost_queue:
        if e["customer_id"] == customer_id and e["invoice_id"] is None:
            total += e["charge_cents"]
            e["invoice_id"] = invoice_id
    return total


def release_lost_charges(invoice_id):
    for e in db.lost_queue:
        if e["invoice_id"] == invoice_id:
            e["invoice_id"] = None


def true_up_reading(reading):
    """Posting a reading trues up invoices of that month generated with the
    estimated surcharge variant: the delta lands on the customer's next DRAFT
    invoice, or on a new DRAFT delta-only invoice when none exists."""
    plant = db.plants.get(reading["plant_id"])
    if not plant:
        return
    month = reading["period_month"]
    for inv in list(db.invoices.values()):
        if inv.get("_surcharge_variant") != "estimated":
            continue
        if inv.get("_surcharge_month") != month:
            continue
        if inv.get("_trued_up"):
            continue
        cust = db.customers.get(inv["customer_id"])
        if not cust or cust["plant_id"] != plant["id"]:
            continue
        actual, _ = utility_surcharge(cust, plant, month)
        delta = actual - inv["utility_surcharge_cents"]
        inv["_trued_up"] = True
        drafts = [
            i
            for i in db.invoices.values()
            if i["customer_id"] == cust["id"] and i["status"] == "DRAFT"
        ]
        drafts.sort(key=lambda i: (i["created_at"], i["_seq"]))
        if drafts:
            target = drafts[0]
            target["utility_surcharge_cents"] += delta
            recompute_invoice_total(target)
            db.touch(target)
        else:
            y, m = int(month[:4]), int(month[5:7])
            start = date(y, m, 1)
            end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
            new_inv = db.new_entity()
            new_inv.update(
                {
                    "customer_id": cust["id"],
                    "billing_period_start": start.isoformat(),
                    "billing_period_end": end.isoformat(),
                    "linen_charges_cents": 0,
                    "lost_item_charges_cents": 0,
                    "utility_surcharge_cents": delta,
                    "credits_cents": 0,
                    "status": "DRAFT",
                    "_surcharge_variant": "delta",
                    "_surcharge_month": month,
                    "_trued_up": True,
                }
            )
            recompute_invoice_total(new_inv)
            db.invoices[new_inv["id"]] = new_inv
