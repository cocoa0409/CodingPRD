"""Every calculation rule of the service, with the constants pinned by the PRD."""

import math
from decimal import Decimal, ROUND_HALF_UP

import db
from timeutil import hours, minutes

# ---------------------------------------------------------------------------
# pinned constants

CABIN_ORDER = ("FIRST", "BUSINESS", "ECONOMY")
STORAGE_ORDER = ("HOT", "CHILL", "DRY")

PAX_FIELD = {"FIRST": "pax_first", "BUSINESS": "pax_business", "ECONOMY": "pax_economy"}

ZONE_CAPACITY = {"CHILL": 250, "HOT": 120, "DRY": 400}
OVERFLOW_CHAIN = {"HOT": "CHILL", "CHILL": "DRY", "DRY": None}
OVERFLOW_MIN_SHELF_LIFE_HOURS = {"HOT": 24, "CHILL": 72}
ZONE_CUTOFF_HOURS = {"HOT": 4, "CHILL": 72, "DRY": 720}

SLOT_PREP_LEAD_MINUTES = 90
SLOT_EARLIEST_LEAD_MINUTES = 300
SLOT_LATEST_LEAD_MINUTES = 45
DISPATCH_LEAD_MINUTES = 60
DELAY_RESLOT_THRESHOLD_MINUTES = 90

OVERHEAD_RATE = Decimal("0.12")

COOK_TEMP_MIN_C = Decimal("75.0")
CHILL_DOWN_MAX_C = Decimal("8.0")
HOLD_TEMP_MAX_C = Decimal("5.0")
BLAST_CHILL_MAX_C = Decimal("3.0")

HACCP_FAIL_WEIGHT = Decimal("40.00")
HACCP_REWORK_WEIGHT = Decimal("15.00")
HACCP_MAX_FAILS = 2
HACCP_MAX_REWORK_ROUNDS = 2

HANDLING_TIERS = (
    (0, 199999, Decimal("0.09")),
    (200000, 499999, Decimal("0.07")),
    (500000, None, Decimal("0.05")),
)

MISSED_FLAT_PENALTY_CENTS = 750000
LATENESS_BANDS = ((30, 250), (60, 400), (None, 600))

FINDING_BASE_CENTS = {
    "SPEC_DEVIATION": 120000,
    "HACCP_BREACH": 500000,
    "SEAL_MISMATCH": 200000,
    "LATE_DELIVERY": 80000,
}
SEVERITY_MULTIPLIER = {
    "MINOR": Decimal("1.0"),
    "MAJOR": Decimal("2.5"),
    "CRITICAL": Decimal("5.0"),
}
OPEN_FINDING_SUSPEND_THRESHOLD = 3

DEVIATION_SEVERITY_BANDS = (
    (Decimal("5.00"), Decimal("9.99"), "MINOR"),
    (Decimal("10.00"), Decimal("19.99"), "MAJOR"),
    (Decimal("20.00"), None, "CRITICAL"),
)

ALLOWED_DISPOSAL = {
    "BONDED": ("INCINERATION",),
    "DOMESTIC": ("INCINERATION", "RENDERING", "LANDFILL"),
}


# ---------------------------------------------------------------------------
# rounding


def rhu(value, places=0):
    """ROUND_HALF_UP — never banker's rounding."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


# ---------------------------------------------------------------------------
# row helpers


def spec_of_batch(batch):
    return db.get("meal_specifications", batch["meal_specification_id"])


def spec_of_item(item):
    batch = db.get("production_batches", item["production_batch_id"])
    return spec_of_batch(batch) if batch else None


def flight_of_cart(cart):
    return db.get("flights", cart["flight_id"])


def flight_carts(flight_id):
    return db.where("carts", flight_id=flight_id)


def cart_active_items(cart_id):
    return [i for i in db.where("cart_items", cart_id=cart_id) if i["status"] == "ACTIVE"]


def cart_loaded_units(cart_id):
    return sum(i["qty_units"] for i in cart_active_items(cart_id))


def flight_active_items(flight_id):
    """ACTIVE cart items of every cart of the flight, in created_at ASC order."""
    cart_ids = {c["id"] for c in flight_carts(flight_id)}
    return [
        item for item in db.rows("cart_items")
        if item["cart_id"] in cart_ids and item["status"] == "ACTIVE"
    ]


def flight_batches(flight_id):
    return db.where("production_batches", flight_id=flight_id)


def flight_manifests(flight_id):
    return db.where("loading_manifests", flight_id=flight_id)


def manifest_runs(manifest_id):
    return db.where("delivery_runs", loading_manifest_id=manifest_id)


def flight_runs(flight_id):
    out = []
    for manifest in flight_manifests(flight_id):
        out.extend(manifest_runs(manifest["id"]))
    return sorted(out, key=lambda r: (r["_ct"], r["_seq"]))


def flight_of_run(run):
    manifest = db.get("loading_manifests", run["loading_manifest_id"])
    return db.get("flights", manifest["flight_id"]) if manifest else None


def airline_of_flight(flight):
    return db.get("airlines", flight["airline_id"])


def revised_std(flight):
    """std_utc plus the cumulative delay; every slot and cutoff rule reads this."""
    return flight["_std"] + minutes(flight["delay_minutes"])


def special_meal_cutoff(flight):
    airline = airline_of_flight(flight)
    lead = airline["special_meal_cutoff_minutes"] if airline else 0
    return revised_std(flight) - minutes(lead)


def pax_of(flight, cabin):
    return flight[PAX_FIELD[cabin]]


def total_pax(flight):
    return sum(pax_of(flight, c) for c in CABIN_ORDER)


# ---------------------------------------------------------------------------
# flight unit aggregates (computed fields)


def units_produced(flight_id):
    return sum(
        b["produced_qty"] for b in flight_batches(flight_id)
        if b["production_status"] in ("COMPLETED", "RELEASED", "DISPOSED")
    )


def units_loaded(flight_id):
    return sum(i["qty_units"] for i in flight_active_items(flight_id))


def units_scrapped(flight_id):
    return sum(b["scrapped_qty"] for b in flight_batches(flight_id))


# ---------------------------------------------------------------------------
# cost


def item_gross_cents(qty_units, unit_cost_cents):
    return rhu_int(Decimal(qty_units) * Decimal(unit_cost_cents) * (Decimal(1) + OVERHEAD_RATE))


def gross_cost_cents(flight_id, extra=None):
    total = 0
    for item in flight_active_items(flight_id):
        spec = spec_of_item(item)
        if spec is None:
            continue
        total += item_gross_cents(item["qty_units"], spec["unit_cost_cents"])
    if extra is not None:
        total += item_gross_cents(extra[1], extra[0]["unit_cost_cents"])
    return total


def cabin_costs(flight_id, extra=None):
    """Per-cabin overhead-loaded cost, accumulated in created_at ASC order."""
    costs = {cabin: 0 for cabin in CABIN_ORDER}
    for item in flight_active_items(flight_id):
        spec = spec_of_item(item)
        if spec is None:
            continue
        cabin = spec["cabin"]
        if cabin in costs:
            costs[cabin] += item_gross_cents(item["qty_units"], spec["unit_cost_cents"])
    if extra is not None:
        spec, qty = extra
        if spec["cabin"] in costs:
            costs[spec["cabin"]] += item_gross_cents(qty, spec["unit_cost_cents"])
    return costs


def cost_per_pax_cents(flight, extra=None):
    """Round once per cabin, then once over the weighted blend."""
    costs = cabin_costs(flight["id"], extra=extra)
    denominator = 0
    numerator = 0
    for cabin in CABIN_ORDER:
        pax = pax_of(flight, cabin)
        if pax == 0:
            continue
        cabin_cpp = rhu_int(Decimal(costs[cabin]) / Decimal(pax))
        numerator += cabin_cpp * pax
        denominator += pax
    if denominator == 0:
        return 0
    return rhu_int(Decimal(numerator) / Decimal(denominator))


def cost_report(flight):
    costs = cabin_costs(flight["id"])
    breakdown = []
    for cabin in CABIN_ORDER:
        pax = pax_of(flight, cabin)
        cpp = 0 if pax == 0 else rhu_int(Decimal(costs[cabin]) / Decimal(pax))
        breakdown.append({
            "cabin": cabin,
            "cabin_pax": pax,
            "cabin_cost_cents": costs[cabin],
            "cabin_cost_per_pax_cents": cpp,
        })
    airline = airline_of_flight(flight)
    cap = airline["cost_cap_per_pax_cents"] if airline else 0
    blended = cost_per_pax_cents(flight)
    return {
        "flight_id": flight["id"],
        "total_pax": total_pax(flight),
        "gross_cost_cents": gross_cost_cents(flight["id"]),
        "cabin_breakdown": breakdown,
        "cost_per_pax_cents": blended,
        "cost_cap_per_pax_cents": cap,
        "cap_breached": blended > cap,
        "spec_deviation_pct": float(spec_deviation_pct(flight)),
    }


# ---------------------------------------------------------------------------
# meal requirement


def standard_spec_for(airline_id, cabin):
    """ACTIVE STANDARD spec of the airline for a cabin; lowest spec_code wins."""
    candidates = [
        s for s in db.rows("meal_specifications")
        if s["airline_id"] == airline_id
        and s["cabin"] == cabin
        and s["meal_code"] == "STANDARD"
        and s["status"] == "ACTIVE"
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda s: s["spec_code"])[0]


def provisional_requirement(flight):
    total = 0
    for cabin in CABIN_ORDER:
        spec = standard_spec_for(flight["airline_id"], cabin)
        if spec is None:
            continue
        pax = Decimal(pax_of(flight, cabin))
        factor = Decimal(1) + (Decimal(str(spec["load_factor_pct"])) / Decimal(100))
        total += int(math.ceil(pax * factor))
    return total


def effective_spec_id(order):
    return order.get("substitute_meal_specification_id") or order["meal_specification_id"]


def confirmed_orders(flight_id):
    return [
        o for o in db.where("special_meal_orders", flight_id=flight_id)
        if o["status"] == "CONFIRMED"
    ]


def final_requirement(flight):
    """Return (units_planned, demand rows) where each row is (spec, qty)."""
    orders = confirmed_orders(flight["id"])
    confirmed_by_cabin = {cabin: 0 for cabin in CABIN_ORDER}
    special_counts = {}
    for order in orders:
        spec = db.get("meal_specifications", effective_spec_id(order))
        if spec is None:
            continue
        if spec["cabin"] in confirmed_by_cabin:
            confirmed_by_cabin[spec["cabin"]] += 1
        special_counts[spec["id"]] = special_counts.get(spec["id"], 0) + 1

    demand = {}
    order_of_appearance = []

    def add(spec, qty):
        if qty <= 0:
            return
        if spec["id"] not in demand:
            demand[spec["id"]] = [spec, 0]
            order_of_appearance.append(spec["id"])
        demand[spec["id"]][1] += qty

    for cabin in CABIN_ORDER:
        standard_units = max(0, pax_of(flight, cabin) - confirmed_by_cabin[cabin])
        spec = standard_spec_for(flight["airline_id"], cabin)
        if spec is not None:
            add(spec, standard_units)

    for spec_id, qty in special_counts.items():
        add(db.get("meal_specifications", spec_id), qty)

    rows = [tuple(demand[spec_id]) for spec_id in order_of_appearance]
    units = sum(qty for _, qty in rows)
    return units, rows


def visit_order(rows):
    """storage_class [HOT, CHILL, DRY], then cabin [FIRST, BUSINESS, ECONOMY], then spec_code."""
    def key(row):
        spec = row[0]
        return (
            STORAGE_ORDER.index(spec["storage_class"]),
            CABIN_ORDER.index(spec["cabin"]),
            spec["spec_code"],
        )
    return sorted(rows, key=key)


def allocate_zones(rows):
    """Waterfall allocation; returns [(spec, zone, qty)] in visit order.

    Raises ERR_STORE_CAPACITY_EXCEEDED (via the caller) by returning None.
    """
    from errors import fail

    remaining = dict(ZONE_CAPACITY)
    allocations = []
    for spec, qty in visit_order(rows):
        primary = spec["storage_class"]
        take = min(qty, remaining[primary])
        if take >= 1:
            allocations.append((spec, primary, take))
            remaining[primary] -= take
        overflow = qty - take
        if overflow >= 1:
            fallback = OVERFLOW_CHAIN.get(primary)
            if fallback is None:
                fail("ERR_STORE_CAPACITY_EXCEEDED")
            floor = OVERFLOW_MIN_SHELF_LIFE_HOURS.get(primary)
            if floor is not None and spec["shelf_life_hours"] < floor:
                fail("ERR_STORE_CAPACITY_EXCEEDED")
            take2 = min(overflow, remaining[fallback])
            if take2 >= 1:
                allocations.append((spec, fallback, take2))
                remaining[fallback] -= take2
            if overflow - take2 >= 1:
                fail("ERR_STORE_CAPACITY_EXCEEDED")
    return allocations


def release_deadline(plan_instant, spec, zone, revised_std):
    candidates = [
        plan_instant + hours(spec["shelf_life_hours"]),
        revised_std - minutes(SLOT_PREP_LEAD_MINUTES),
        plan_instant + hours(ZONE_CUTOFF_HOURS[zone]),
    ]
    chosen = min(candidates)
    return chosen.replace(microsecond=0)


# ---------------------------------------------------------------------------
# HACCP


def haccp_verdict(step_code, temp):
    temp = Decimal(str(temp))
    if step_code == "COOK_TEMP":
        return "PASS" if temp >= COOK_TEMP_MIN_C else "FAIL"
    if step_code == "CHILL_DOWN":
        return "PASS" if temp <= CHILL_DOWN_MAX_C else "FAIL"
    if step_code == "HOLD_TEMP":
        return "PASS" if temp <= HOLD_TEMP_MAX_C else "FAIL"
    if step_code == "BLAST_CHILL":
        return "PASS" if temp <= BLAST_CHILL_MAX_C else "FAIL"
    return "FAIL"


def batch_checks(batch_id):
    checks = db.where("haccp_checks", production_batch_id=batch_id)
    return sorted(checks, key=lambda c: (c["sequence_no"], c["_seq"]))


def fail_count(batch_id):
    return len([c for c in batch_checks(batch_id) if c["verdict"] == "FAIL"])


def risk_score(batch):
    raw = HACCP_FAIL_WEIGHT * Decimal(fail_count(batch["id"])) \
        + HACCP_REWORK_WEIGHT * Decimal(batch["haccp_rework_rounds"])
    if raw > Decimal("100.00"):
        raw = Decimal("100.00")
    return rhu(raw, 2)


def latest_check_for_step(batch_id, step_code):
    checks = [c for c in batch_checks(batch_id) if c["step_code"] == step_code]
    if not checks:
        return None
    return max(checks, key=lambda c: (c["sequence_no"], c["_seq"]))


# ---------------------------------------------------------------------------
# billing / lateness


def weighted_rate_cents(gross, uplifted):
    if uplifted <= 0:
        return 0
    return rhu_int(Decimal(gross) / Decimal(uplifted))


def recovery_credit_cents(credit_basis, rate, recovery_rate_pct):
    return rhu_int(
        Decimal(credit_basis) * Decimal(rate) * Decimal(str(recovery_rate_pct)) / Decimal(100)
    )


def handling_rate_for(net):
    for low, high, rate in HANDLING_TIERS:
        if net >= low and (high is None or net <= high):
            return rate
    return HANDLING_TIERS[-1][2]


def handling_fee_cents(net):
    return rhu_int(Decimal(net) * handling_rate_for(net))


def late_penalty_cents(flight_id):
    return sum(run["penalty_cents"] for run in flight_runs(flight_id))


def lateness_minutes(delivered_at, window_end):
    seconds = (delivered_at - window_end).total_seconds()
    if seconds <= 0:
        return 0
    return int(math.ceil(seconds / 60.0))


def banded_penalty_cents(billable):
    """Marginal banding: each band prices only the minutes inside it."""
    remaining = billable
    total = 0
    previous_ceiling = 0
    for ceiling, rate in LATENESS_BANDS:
        if remaining <= 0:
            break
        if ceiling is None:
            span = remaining
        else:
            span = min(remaining, ceiling - previous_ceiling)
            previous_ceiling = ceiling
        total += span * rate
        remaining -= span
    return total


# ---------------------------------------------------------------------------
# deviation, penalties, waste


def spec_deviation_pct(flight):
    requirement = flight.get("_final_requirement") or {}
    if not requirement:
        return Decimal("0.00")
    delivered = {}
    for item in flight_active_items(flight["id"]):
        batch = db.get("production_batches", item["production_batch_id"])
        if batch is None:
            continue
        spec_id = batch["meal_specification_id"]
        delivered[spec_id] = delivered.get(spec_id, 0) + item["qty_units"]
    worst = Decimal("0.00")
    for spec_id, required in requirement.items():
        if required <= 0:
            continue
        got = delivered.get(spec_id, 0)
        deviation = rhu(
            abs(Decimal(got) - Decimal(required)) / Decimal(required) * Decimal(100), 2
        )
        if deviation > worst:
            worst = deviation
    return worst


def deviation_severity(pct):
    for low, high, severity in DEVIATION_SEVERITY_BANDS:
        if pct >= low and (high is None or pct <= high):
            return severity
    return None


def finding_penalty_cents(finding_type, severity):
    base = FINDING_BASE_CENTS[finding_type]
    return rhu_int(Decimal(base) * SEVERITY_MULTIPLIER[severity])


def waste_mass_grams(record):
    total = 0
    for line in record["lines"]:
        spec = db.get("meal_specifications", line["meal_specification_id"])
        if spec is None:
            continue
        total += line.get("destroy_units", 0) * spec["gross_weight_grams"]
    return total


# ---------------------------------------------------------------------------
# slot occupancy


def _live_runs_on(field, value, exclude_ids):
    return [
        run for run in db.rows("delivery_runs")
        if run[field] == value
        and run["status"] != "CANCELLED"
        and run["id"] not in exclude_ids
    ]


def truck_conflict(truck_id, start, end, buffer_minutes, exclude_ids=()):
    """Half-open with buffering."""
    for run in _live_runs_on("truck_id", truck_id, set(exclude_ids)):
        other_start = run["_window_start"]
        other_end = run["_window_end"]
        if start < other_end + minutes(buffer_minutes) and end > other_start:
            return True
    return False


def stand_conflict(stand_id, start, end, max_concurrent, exclude_ids=()):
    """Closed intervals with an aggregate concurrency limit."""
    others = _live_runs_on("stand_id", stand_id, set(exclude_ids))
    intervals = [(start, end)] + [(r["_window_start"], r["_window_end"]) for r in others]
    probes = {start, end}
    for other_start, other_end in intervals:
        if start <= other_start <= end:
            probes.add(other_start)
        if start <= other_end <= end:
            probes.add(other_end)
    for instant in probes:
        covering = 0
        for interval_start, interval_end in intervals:
            if interval_start <= instant <= interval_end:
                covering += 1
        if covering > max_concurrent:
            return True
    return False
