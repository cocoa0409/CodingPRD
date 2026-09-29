"""The sixteen interacting calculations (PRD 2.8 and section 3).

Every rounding mode here is pinned by the PRD: round-half-up is the default for
money, with deliberate departures for arc-flash values (ceiling), staged billing
(floor plus a single remainder holder), the punch completion ratio (floor) and
storage billable days (ceiling).
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING

import clock
import store

CENT = Decimal(1)


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def half_up(value):
    return int(D(value).quantize(CENT, rounding=ROUND_HALF_UP))


def floor_int(value):
    return int(D(value).quantize(CENT, rounding=ROUND_FLOOR))


def ceil_int(value):
    return int(D(value).quantize(CENT, rounding=ROUND_CEILING))


def half_up_places(value, places):
    q = Decimal(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- #
# YYYY-MM month helpers
# --------------------------------------------------------------------------- #

def month_add(month, delta):
    y, m = int(month[0:4]), int(month[5:7])
    total = (y * 12 + (m - 1)) + delta
    return "%04d-%02d" % (total // 12, total % 12 + 1)


# --------------------------------------------------------------------------- #
# 1. escalation adjustment (six pinned steps)
# --------------------------------------------------------------------------- #
COMMODITY_FIELDS = (
    ("COPPER", "copper_weight_bp", "copper_component_cents"),
    ("ALUMINUM", "aluminum_weight_bp", "aluminum_component_cents"),
    ("CORE_STEEL", "core_steel_weight_bp", "core_steel_component_cents"),
)


def usable_index_points(commodity, variant):
    now = clock.sec(clock.now())
    rows = []
    for p in store.all_rows("index_point"):
        if p.get("commodity") != commodity:
            continue
        pub = clock.sec(clock.parse(p.get("published_at")))
        if pub is None or pub > now:
            continue
        if variant == "FINAL" and p.get("is_provisional"):
            continue
        rows.append(p)
    return rows


def escalation_components(clause, variant):
    """Returns the computed field dict, or raises the pinned temporal errors."""
    from errors import ApiError

    base_month = clause.get("base_index_month")
    end_month = clause.get("final_window_end_month")
    escalatable = D(clause.get("escalatable_base_cents") or 0)
    months_used = set()
    components = {}
    raw_total = 0
    for commodity, weight_field, component_field in COMMODITY_FIELDS:
        weight = clause.get(weight_field) or 0
        rows = usable_index_points(commodity, variant)
        base_row = None
        for r in rows:
            if r.get("index_month") == base_month:
                base_row = r
                break
        if weight == 0:
            components[component_field] = 0
            continue
        if base_row is None:
            raise ApiError("ERR_INDEX_POINT_MISSING",
                           "no usable %s index point for base month %s" % (commodity, base_month))
        base_level = D(base_row.get("index_value"))
        months_used.add(base_month)
        if variant == "PROVISIONAL":
            candidates = [r for r in rows if r.get("index_month") <= end_month]
            if not candidates:
                raise ApiError("ERR_INDEX_POINT_MISSING",
                               "no usable %s index point at or before %s" % (commodity, end_month))
            spot = max(candidates, key=lambda r: r.get("index_month"))
            current = D(spot.get("index_value"))
            months_used.add(spot.get("index_month"))
        else:
            lo = month_add(base_month, 1)
            window = sorted([r for r in rows if lo <= r.get("index_month") <= end_month],
                            key=lambda r: r.get("index_month"))
            if not window:
                raise ApiError("ERR_INDEX_WINDOW_EMPTY",
                               "no usable %s index points in the final window" % commodity)
            total = sum((D(r.get("index_value")) for r in window), Decimal(0))
            current = half_up_places(total / Decimal(len(window)), 4)
            for r in window:
                months_used.add(r.get("index_month"))
        movement = (current - base_level) / base_level
        contribution = escalatable * (D(weight) / Decimal(10000)) * movement
        cents = half_up(contribution)
        components[component_field] = cents
    raw_total = sum(components.values())
    out = dict(components)
    out["raw_movement_cents"] = raw_total
    out["index_months_used"] = sorted(months_used)

    collar = half_up(escalatable * D(clause.get("collar_bp") or 0) / Decimal(10000))
    cap = half_up(escalatable * D(clause.get("cap_bp") or 0) / Decimal(10000))
    if abs(raw_total) < collar:
        out["adjustment_amount_cents"] = 0
        out["collar_absorbed"] = True
        out["cap_applied"] = False
        return out
    if raw_total < 0 and not clause.get("de_escalation_enabled", True):
        out["adjustment_amount_cents"] = 0
        out["collar_absorbed"] = False
        out["cap_applied"] = False
        return out
    amount = max(-cap, min(cap, raw_total))
    out["adjustment_amount_cents"] = amount
    out["collar_absorbed"] = False
    out["cap_applied"] = amount != raw_total
    return out


# --------------------------------------------------------------------------- #
# 2. allocation release penalty
# --------------------------------------------------------------------------- #

def release_penalty_cents(allocation, component, order):
    lead = component.get("lead_time_days") or 0
    if lead <= 30:
        per_unit = 0
    elif lead <= 120:
        per_unit = 25000
    else:
        per_unit = 60000
    raw = per_unit * (allocation.get("quantity") or 0)
    ceiling = half_up(D(order.get("contract_value_cents") or 0) * Decimal(5) / Decimal(100))
    return min(raw, ceiling)


# --------------------------------------------------------------------------- #
# 3. component unit buckets
# --------------------------------------------------------------------------- #

def refresh_component_buckets(component):
    allocations = store.where("allocation", long_lead_component_id=component["id"])

    def total(status):
        return sum(a.get("quantity") or 0 for a in allocations if a.get("status") == status)

    component["quantity_reserved"] = total("RESERVED")
    component["quantity_committed"] = total("COMMITTED")
    component["quantity_consumed"] = total("CONSUMED")
    available = (component.get("quantity_on_hand") or 0) - component["quantity_reserved"] \
        - component["quantity_committed"]
    component["quantity_available"] = max(0, available)
    return component


# --------------------------------------------------------------------------- #
# 4. bay occupation window
# --------------------------------------------------------------------------- #

def window_end(start_dt, test_duration_hours, changeover_buffer_hours):
    from datetime import timedelta
    hours = (test_duration_hours or 0) + (changeover_buffer_hours or 0)
    return start_dt + timedelta(hours=hours)


OCCUPYING_STATES = ("BAY_SCHEDULED", "WITNESS_CONFIRMED", "IN_PROGRESS")


def bay_windows(bay_id, exclude_fat_id=None):
    out = []
    for t in store.where("fat", test_bay_id=bay_id):
        if t.get("status") not in OCCUPYING_STATES:
            continue
        if exclude_fat_id is not None and t["id"] == exclude_fat_id:
            continue
        s = clock.sec(clock.parse(t.get("window_start_at")))
        e = clock.sec(clock.parse(t.get("window_end_at")))
        if s is None or e is None:
            continue
        out.append((s, e, t))
    return out


def windows_conflict(cand_start, cand_end, other_start, other_end):
    return other_start < cand_end and cand_start < other_end


def refresh_bay_hours(bay):
    total = 0
    for t in store.where("fat", test_bay_id=bay["id"]):
        if t.get("status") in OCCUPYING_STATES:
            total += t.get("test_duration_hours") or 0
    bay["scheduled_hours_total"] = total
    return bay


# --------------------------------------------------------------------------- #
# 5. witness daily load
# --------------------------------------------------------------------------- #

def assignment_day(assignment):
    fat = store.get("fat", assignment.get("factory_acceptance_test_id"))
    if fat is None:
        return None
    return clock.day(clock.parse(fat.get("window_start_at")))


def blackout_for(travel_region):
    return 0 if travel_region == "NA" else 1


def blackout_days_set(day, travel_region):
    from datetime import timedelta
    if day is None or blackout_for(travel_region) == 0:
        return set()
    return {day - timedelta(days=1), day + timedelta(days=1)}


def party_confirmed_assignments(party_id, exclude_id=None):
    out = []
    for a in store.where("assignment", witness_party_id=party_id):
        if a.get("status") != "CONFIRMED":
            continue
        if exclude_id is not None and a["id"] == exclude_id:
            continue
        out.append(a)
    return out


def party_day_load(party_id, day, exclude_id=None):
    return len([a for a in party_confirmed_assignments(party_id, exclude_id)
                if assignment_day(a) == day])


# --------------------------------------------------------------------------- #
# 6. test report verdict
# --------------------------------------------------------------------------- #

def report_verdict(report, fat):
    failed = []
    if report.get("winding_temp_rise_c") is not None and report.get("temp_rise_limit_c") is not None:
        if D(report["winding_temp_rise_c"]) > D(report["temp_rise_limit_c"]):
            failed.append("TEMP_RISE")
    if fat is not None and fat.get("requires_impulse"):
        withstand = report.get("impulse_withstand_kv")
        required = report.get("impulse_required_kv")
        if withstand is not None and required is not None and D(withstand) < D(required):
            failed.append("IMPULSE")
    sc = report.get("short_circuit_current_ka")
    if sc is not None and D(sc) <= 0:
        failed.append("SHORT_CIRCUIT")
    failed = sorted(failed)
    return ("PASS" if not failed else "FAIL"), failed


# --------------------------------------------------------------------------- #
# 7. arc-flash label values
# --------------------------------------------------------------------------- #
ENERGY_COEFFICIENT = Decimal("512000.0")


def voltage_factor(rated_kv):
    kv = D(rated_kv)
    if kv <= 15:
        return Decimal("1.00")
    if kv <= 38:
        return Decimal("1.25")
    return Decimal("1.60")


def ppe_category(energy):
    e = D(energy)
    if e < Decimal("1.2"):
        return 0
    if e < Decimal("4.0"):
        return 1
    if e < Decimal("8.0"):
        return 2
    if e < Decimal("25.0"):
        return 3
    if e < Decimal("40.0"):
        return 4
    return None


def arc_flash_values(order, report):
    factor = voltage_factor(order.get("rated_kv"))
    ka = D(report.get("short_circuit_current_ka"))
    seconds = D(report.get("arc_duration_ms")) / Decimal(1000)
    wd = D(report.get("working_distance_mm"))
    raw = ENERGY_COEFFICIENT * ka * seconds * factor / (wd * wd)
    energy = D(raw).quantize(Decimal("0.1"), rounding=ROUND_CEILING)
    category = ppe_category(energy)
    if category is None:
        return None, None, None, None
    boundary_sq = ENERGY_COEFFICIENT * ka * seconds * factor / Decimal("1.2")
    boundary = boundary_sq.sqrt().quantize(Decimal(1), rounding=ROUND_CEILING)
    rating_text = "%skV / %skA / PPE %d" % (order.get("rated_kv"),
                                            report.get("short_circuit_current_ka"),
                                            category)
    return float(energy), category, int(boundary), rating_text


# --------------------------------------------------------------------------- #
# 8. staged billing waterfall
# --------------------------------------------------------------------------- #

def stage_billing_allocation(order):
    releases = sorted([r for r in store.where("release", engineered_order_id=order["id"])
                       if r.get("status") != "CANCELLED"],
                      key=lambda r: r.get("stage_index") or 0)
    for r in store.where("release", engineered_order_id=order["id"]):
        if r.get("status") == "CANCELLED":
            r["stage_billing_cents"] = 0
    if not releases:
        return
    net = D(order.get("net_contract_value_cents") or 0)
    provisional = {}
    for r in releases:
        provisional[r["id"]] = floor_int(net * D(r.get("stage_share_bp") or 0) / Decimal(10000))
    remainder = int(net) - sum(provisional.values())
    holder = None
    for r in releases:
        if r.get("is_final_stage"):
            holder = r
            break
    if holder is None:
        holder = max(releases, key=lambda r: r.get("stage_index") or 0)
    for r in releases:
        amount = provisional[r["id"]]
        if r["id"] == holder["id"]:
            amount += remainder
        r["stage_billing_cents"] = amount


# --------------------------------------------------------------------------- #
# 9. site storage fee (six pinned steps)
# --------------------------------------------------------------------------- #

def storage_fee(agreement):
    start = clock.parse(agreement.get("storage_start_at"))
    end = clock.parse(agreement.get("storage_end_at"))
    hours = D((end - start).total_seconds()) / Decimal(3600)
    days = ceil_int(hours / Decimal(24))
    days = max(1, days)
    band1 = min(days, 30) * 1200
    band2 = min(max(days - 30, 0), 60) * 900
    band3 = max(days - 90, 0) * 700
    crates = agreement.get("crate_count") or 0
    subtotal = half_up(D(band1 + band2 + band3) * D(crates))
    insured = D(agreement.get("insured_value_cents") or 0)
    by_rate = insured * Decimal(3) / Decimal(10000)
    by_cap = D(subtotal) * Decimal(25) / Decimal(100)
    surcharge = half_up(min(by_rate, by_cap))
    pre = subtotal + surcharge
    if pre < 500000:
        bp = 0
    elif pre < 2000000:
        bp = 300
    else:
        bp = 750
    discount = half_up(D(pre) * D(bp) / Decimal(10000))
    return {
        "billable_days": days,
        "storage_subtotal_cents": subtotal,
        "insurance_surcharge_cents": surcharge,
        "long_stay_discount_cents": discount,
        "total_fee_cents": pre - discount,
    }


# --------------------------------------------------------------------------- #
# 10. punch aggregates
# --------------------------------------------------------------------------- #

def punch_aggregates(job):
    items = store.where("punch", commissioning_job_id=job["id"])
    open_count = len([i for i in items if i.get("status") in ("OPEN", "ASSIGNED", "RESOLVED")])
    blocking = len([i for i in items if i.get("severity") == "BLOCKING"
                    and i.get("status") not in ("CLOSED", "REJECTED")])
    considered = [i for i in items if i.get("status") != "REJECTED"]
    closed = len([i for i in considered if i.get("status") == "CLOSED"])
    if not considered:
        ratio = 10000
    else:
        ratio = floor_int(D(closed) * Decimal(10000) / D(len(considered)))
    return open_count, blocking, ratio


def refresh_job_aggregates(job):
    open_count, blocking, ratio = punch_aggregates(job)
    job["open_punch_count"] = open_count
    job["blocking_punch_count"] = blocking
    job["completion_ratio_bp"] = ratio
    return job


# --------------------------------------------------------------------------- #
# 11. warranty window and liability cap
# --------------------------------------------------------------------------- #

def warranty_anchor(order):
    jobs = [j for j in store.where("job", engineered_order_id=order["id"])
            if j.get("status") == "COMPLETE" and j.get("energized_at")]
    if not jobs:
        return None
    jobs.sort(key=lambda j: (clock.parse(j.get("energized_at")), j.get("created_at"), j.get("_seq", 0)))
    return jobs[0]


def warranty_window_expiry(order):
    job = warranty_anchor(order)
    if job is None:
        return None
    anchor = clock.parse(job.get("energized_at"))
    months = 18 if order.get("product_family") == "POWER_TRANSFORMER" else 12
    return clock.add_calendar_months(anchor, months)


def liability_cap_cents(order):
    family = order.get("product_family")
    if family == "POWER_TRANSFORMER":
        pct = 25
    elif family == "PAD_MOUNT_TRANSFORMER":
        pct = 20
    else:
        pct = 15
    value = half_up(D(order.get("contract_value_cents") or 0) * D(pct) / Decimal(100))
    value = min(value, 50000000)
    return max(value, 100000)


def credit_waterfall(claim):
    remaining = claim.get("liability_cap_cents") or 0
    parts_claim = claim.get("parts_claim_cents") or 0
    labor_claim = claim.get("labor_claim_cents") or 0
    freight_claim = claim.get("freight_claim_cents") or 0
    conseq_claim = (claim.get("consequential_claim_cents") or 0) if claim.get("consequential_covered") else 0
    parts = min(parts_claim, remaining)
    remaining -= parts
    sub_limit = half_up(D(parts) * Decimal(60) / Decimal(100))
    labor = min(labor_claim, sub_limit, remaining)
    remaining -= labor
    freight = min(freight_claim, 250000, remaining)
    remaining -= freight
    conseq = min(conseq_claim, remaining)
    buckets = {"PARTS": parts, "LABOR": labor, "FREIGHT": freight, "CONSEQUENTIAL": conseq}
    return parts + labor + freight + conseq, buckets


# --------------------------------------------------------------------------- #
# 12. supplier quality indices
# --------------------------------------------------------------------------- #

def _published_reports(supplier_id):
    rows = [r for r in store.where("failure_report", attributed_supplier_id=supplier_id)
            if r.get("status") == "PUBLISHED"]
    rows.sort(key=lambda r: (clock.parse(r.get("published_at")) or clock.now(),
                             r.get("created_at"), r.get("_seq", 0)))
    return rows


def _index(reports, denominator):
    penalty = D(sum(r.get("defect_weight") or 0 for r in reports)) * Decimal(100) \
        / (D(denominator) * Decimal(10))
    value = half_up_places(Decimal(100) - penalty, 2)
    if value < 0:
        value = Decimal("0.00")
    if value > 100:
        value = Decimal("100.00")
    return float(value)


def refresh_supplier_indices(supplier):
    reports = _published_reports(supplier["id"])
    receipts = supplier.get("receipt_event_count") or 0
    trailing = _index(reports[-8:], max(receipts, 8))
    lifetime = _index(reports, max(receipts, 1))
    supplier["quality_index_trailing"] = trailing
    supplier["quality_index_lifetime"] = lifetime
    return supplier
