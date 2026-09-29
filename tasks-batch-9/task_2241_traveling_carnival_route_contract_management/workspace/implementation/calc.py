"""All nine calculations of PRD section 3 with their pinned constants and orders."""

from datetime import timedelta
from decimal import Decimal

import db
import errors
from errors import fail
from validators import amps1, ceil_int, cents, dec, floor_int, hours2, rhu

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------
AVG_HAUL_SPEED_MPH = Decimal(45)
MAX_DRIVE_HOURS_PER_SHIFT = Decimal(11)
MANDATED_REST_HOURS = Decimal(10)
LOAD_OUT_BUFFER_HOURS = Decimal(6)
TRANSPORT_BUFFER_HOURS = Decimal(4)

SPACING_MULTIPLIER = {"MAJOR": Decimal("1.35"), "FLAT": Decimal("1.20"),
                     "KIDDIE": Decimal("1.10")}
STARTUP_SURGE_PCT = {"MAJOR": Decimal(25), "FLAT": Decimal(15),
                     "KIDDIE": Decimal(0)}
USABLE_LOT_PCT = Decimal(80)
CIRCULATION_SQFT_PER_ATTENDEE = Decimal("0.5")
POWER_HEADROOM_PCT = Decimal(90)

OVERTIME_THRESHOLD_HOURS = Decimal(10)
OVERTIME_MULTIPLIER = Decimal("1.5")
RIGGING_PREMIUM_PCT = Decimal(10)
HOUSING_STIPEND_CENTS_PER_SHIFT = 3500

DAILY_OPERATING_HOURS = Decimal(8)
ABATEMENT_MIN_HOURS = Decimal(2)

SPLIT_TIER_1_CENTS = 2000000
SPLIT_TIER_2_CENTS = 5000000
MAX_OPERATOR_PCT = Decimal("72.5")
RIDE_SHORTFALL_PENALTY_CENTS = 25000
SHORTFALL_CAP_PCT = Decimal(10)
RIDE_COUNT_STATUS_SET = {
    "PROVISIONAL": ("COMMITTED", "INSPECTION_HELD", "OPERATING"),
    "FINAL": ("OPERATING", "STRUCK"),
}

KIND_MULTIPLIER = {"CASH_REFUND": Decimal("1.00"),
                   "SPONSOR_CREDIT": Decimal("1.25"),
                   "BONUS_DAY": Decimal("0.00")}
MAKEGOOD_CAP_PCT = Decimal(30)

VISA_EXPIRING_WINDOW_DAYS = 30
MIN_OPERATORS_PER_RIDE = 1
MAX_NEGOTIATION_ROUNDS = 2
OUT_OF_SERVICE_DEFECT_THRESHOLD = 3
TRANSPORT_AXLE_SURCHARGE_CENTS = 1500
SLOT_TIME_OF_DAY_UTC = "14:00:00"

ALLOC_ACTIVE = ("RESERVED", "COMMITTED", "INSPECTION_HELD", "OPERATING")
ASSIGN_SCHEDULED_SET = ("SCHEDULED", "COMPLETED")
CONTRACT_LIVE = ("DRAFT", "SENT", "COUNTERED", "EXECUTED")


# --------------------------------------------------------------------------
# graph accessors
# --------------------------------------------------------------------------
def venue_of(stop):
    return db.store.venues.get(stop["venue_id"])


def jurisdiction_of(stop):
    venue = venue_of(stop)
    if venue is None:
        return None
    return db.store.jurisdictions.get(venue["jurisdiction_id"])


def route_of(stop):
    return db.store.routes.get(stop["route_id"])


def stop_of_allocation(alloc):
    return db.store.route_stops.get(alloc["route_stop_id"])


def stops_of_route(route_id, include_dark=False):
    rows = [s for s in db.store.route_stops.values() if s["route_id"] == route_id]
    if not include_dark:
        rows = [s for s in rows if s["status"] != "DARK"]
    return db.sorted_rows(rows)


def allocations_of_stop(stop_id, statuses=None):
    rows = [a for a in db.store.ride_allocations.values()
            if a["route_stop_id"] == stop_id
            and (statuses is None or a["status"] in statuses)]
    return db.sorted_rows(rows)


def allocations_of_ride(ride_id, statuses=None):
    rows = [a for a in db.store.ride_allocations.values()
            if a["ride_id"] == ride_id
            and (statuses is None or a["status"] in statuses)]
    return db.sorted_rows(rows)


def assignments_of_stop(stop_id, statuses=None):
    rows = [a for a in db.store.crew_assignments.values()
            if a["route_stop_id"] == stop_id
            and (statuses is None or a["status"] in statuses)]
    return db.sorted_rows(rows)


def assignments_of_worker(worker_id, statuses=None):
    rows = [a for a in db.store.crew_assignments.values()
            if a["worker_id"] == worker_id
            and (statuses is None or a["status"] in statuses)]
    return db.sorted_rows(rows)


def permits_of_stop(stop_id, statuses=None, permit_type=None):
    rows = [p for p in db.store.permit_applications.values()
            if p["route_stop_id"] == stop_id
            and (statuses is None or p["status"] in statuses)
            and (permit_type is None or p["permit_type"] == permit_type)]
    return db.sorted_rows(rows)


def inspections_of_allocation(alloc_id, statuses=None):
    rows = [i for i in db.store.inspection_orders.values()
            if i["ride_allocation_id"] == alloc_id
            and (statuses is None or i["status"] in statuses)]
    return db.sorted_rows(rows)


def closures_of_stop(stop_id, statuses=None):
    rows = [c for c in db.store.weather_closures.values()
            if c["route_stop_id"] == stop_id
            and (statuses is None or c["status"] in statuses)]
    return db.sorted_rows(rows)


def sales_of_stop(stop_id):
    rows = [s for s in db.store.ticket_sales.values()
            if s["route_stop_id"] == stop_id]
    return db.sorted_rows(rows)


def settlements_of_contract(contract_id, statuses=None):
    rows = [s for s in db.store.settlements.values()
            if s["contract_id"] == contract_id
            and (statuses is None or s["status"] in statuses)]
    return db.sorted_rows(rows)


def make_goods_of_contract(contract_id, statuses=None):
    rows = [m for m in db.store.make_goods.values()
            if m["contract_id"] == contract_id
            and (statuses is None or m["status"] in statuses)]
    return db.sorted_rows(rows)


def contracts_of_stop(stop_id, statuses=None):
    rows = [c for c in db.store.contracts.values()
            if c["route_stop_id"] == stop_id
            and (statuses is None or c["status"] in statuses)]
    return db.sorted_rows(rows)


def executed_contract_of_stop(stop_id):
    rows = contracts_of_stop(stop_id, ("EXECUTED",))
    return rows[0] if rows else None


def live_contract_of_stop(stop_id):
    rows = contracts_of_stop(stop_id, CONTRACT_LIVE)
    return rows[0] if rows else None


def dt(row, field):
    value = row.get(field)
    if value is None:
        return None
    return db.parse_iso(value)


def hours_between(start, end):
    return dec(Decimal((end - start).total_seconds())) / Decimal(3600)


# --------------------------------------------------------------------------
# 1. route_travel_feasibility
# --------------------------------------------------------------------------
def travel_hours_for(haul_miles):
    raw = dec(haul_miles) / AVG_HAUL_SPEED_MPH
    rest_blocks = floor_int(raw / MAX_DRIVE_HOURS_PER_SHIFT)
    return rhu(raw + rest_blocks * MANDATED_REST_HOURS, 2)


def build_chain(route_id):
    """Return the ordered chain or raise ERR_STOP_CHAIN_INVALID."""
    stops = stops_of_route(route_id)
    heads = [s for s in stops if not s.get("previous_stop_id")]
    if len(heads) != 1:
        fail(errors.ERR_STOP_CHAIN_INVALID,
             "Exactly one non-DARK stop must have a null previous_stop_id.")
    by_prev = {}
    for s in stops:
        prev = s.get("previous_stop_id")
        if prev:
            by_prev.setdefault(prev, []).append(s)
    for prev, children in by_prev.items():
        if len(children) > 1:
            fail(errors.ERR_STOP_CHAIN_INVALID,
                 "A stop is the predecessor of more than one stop.")
    chain = [heads[0]]
    seen = {heads[0]["id"]}
    while True:
        children = by_prev.get(chain[-1]["id"], [])
        if not children:
            break
        nxt = children[0]
        if nxt["id"] in seen:
            fail(errors.ERR_STOP_CHAIN_INVALID, "The haul chain contains a cycle.")
        chain.append(nxt)
        seen.add(nxt["id"])
    if len(chain) != len(stops):
        fail(errors.ERR_STOP_CHAIN_INVALID,
             "The haul chain does not cover every non-DARK stop.")
    return chain


def route_travel_feasibility(route):
    chain = build_chain(route["id"])
    computed = []
    for index, stop in enumerate(chain):
        travel = travel_hours_for(stop.get("haul_miles_from_previous", 0))
        computed.append(travel)
        if index >= 1:
            required = travel + LOAD_OUT_BUFFER_HOURS
            available = hours_between(dt(chain[index - 1], "teardown_deadline"),
                                      dt(stop, "load_in_start"))
            if available < required:
                fail(errors.ERR_INSUFFICIENT_TRAVEL_WINDOW,
                     "The gap before this stop does not cover its haul plus the "
                     "load-out buffer.")
    total_travel = Decimal(0)
    for index, stop in enumerate(chain):
        stop["sequence_index"] = index
        stop["travel_hours_from_previous"] = float(computed[index])
        total_travel += computed[index]
        db.touch(stop)
    route["total_travel_hours"] = float(rhu(total_travel, 2))
    return chain


def reset_sequencing(route):
    """Route SEQUENCED -> DRAFT: sequencing is invalidated by a stop-set change."""
    for stop in stops_of_route(route["id"]):
        if stop.get("sequence_index") or stop.get("travel_hours_from_previous"):
            stop["sequence_index"] = 0
            stop["travel_hours_from_previous"] = 0
            db.touch(stop)
    route["total_travel_hours"] = 0
    route["status"] = "DRAFT"
    db.touch(route)


# --------------------------------------------------------------------------
# route / stop aggregates
# --------------------------------------------------------------------------
def route_stop_count(route_id):
    return len(stops_of_route(route_id))


def route_total_haul_miles(route_id):
    return sum(int(s.get("haul_miles_from_previous", 0))
               for s in stops_of_route(route_id))


def route_closed_stop_count(route_id):
    return len([s for s in stops_of_route(route_id, include_dark=True)
                if s["status"] in ("CLOSED", "DARK")])


def route_total_guaranteed_cents(route_id):
    total = 0
    stop_ids = set(s["id"] for s in stops_of_route(route_id, include_dark=True))
    for contract in db.store.contracts.values():
        if contract["route_stop_id"] in stop_ids and contract["status"] == "EXECUTED":
            total += int(contract.get("guarantee_cents", 0))
    return total


def stop_operating_days(open_dt, close_dt):
    days = ceil_int(dec(Decimal((close_dt - open_dt).total_seconds()))
                    / Decimal(86400))
    return max(1, days)


def stop_allocated_sqft_used(stop_id):
    return sum(int(a["footprint_charged_sqft"])
               for a in allocations_of_stop(stop_id, ALLOC_ACTIVE))


def stop_power_amps_used(stop_id):
    total = Decimal(0)
    for a in allocations_of_stop(stop_id, ALLOC_ACTIVE):
        total += dec(a["power_charged_amps"])
    return float(rhu(total, 1))


def stop_operating_ride_count(stop_id):
    return len(allocations_of_stop(stop_id, ("OPERATING", "STRUCK")))


def stop_labor_cost_provisional_cents(stop_id):
    return sum(int(a["cost_cents"])
               for a in assignments_of_stop(stop_id, ASSIGN_SCHEDULED_SET))


def worker_scheduled_hours_total(worker_id):
    total = Decimal(0)
    for a in assignments_of_worker(worker_id, ASSIGN_SCHEDULED_SET):
        total += dec(a["shift_hours"])
    return float(rhu(total, 2))


# --------------------------------------------------------------------------
# 2. lot_capacity_charge
# --------------------------------------------------------------------------
def charged_footprint_sqft(ride):
    return ceil_int(dec(ride["footprint_sqft"]) * SPACING_MULTIPLIER[ride["ride_class"]])


def charged_power_amps(ride):
    factor = Decimal(1) + STARTUP_SURGE_PCT[ride["ride_class"]] / Decimal(100)
    return amps1(dec(ride["power_amps"]) * factor)


def usable_lot_sqft(venue):
    circulation = ceil_int(dec(venue["expected_attendance"])
                           * CIRCULATION_SQFT_PER_ATTENDEE)
    usable = floor_int(dec(venue["lot_area_sqft"]) * USABLE_LOT_PCT / Decimal(100))
    return usable - circulation


def allowed_amps(venue):
    return rhu(dec(venue["power_amps_available"]) * POWER_HEADROOM_PCT
               / Decimal(100), 1)


# --------------------------------------------------------------------------
# 3. stop_labor_cost
# --------------------------------------------------------------------------
def assignment_cost(worker, crew_role, shift_start, shift_end):
    shift_hours = rhu(hours_between(shift_start, shift_end), 2)
    straight = min(shift_hours, OVERTIME_THRESHOLD_HOURS)
    overtime = max(Decimal(0), shift_hours - OVERTIME_THRESHOLD_HOURS)
    rate = dec(worker["hourly_rate_cents"])
    base_cents = cents(straight * rate + overtime * rate * OVERTIME_MULTIPLIER)
    if crew_role in ("SETUP", "TEARDOWN"):
        premium_cents = cents(dec(base_cents) * RIGGING_PREMIUM_PCT / Decimal(100))
    else:
        premium_cents = 0
    housing_cents = HOUSING_STIPEND_CENTS_PER_SHIFT if worker["housing_required"] else 0
    return float(shift_hours), base_cents + premium_cents + housing_cents


# --------------------------------------------------------------------------
# 4. stop_settlement
# --------------------------------------------------------------------------
GROSS_CHANNELS = ("WRISTBAND", "SINGLE", "PRESALE")


def stop_settlement(contract, stop, variant):
    jurisdiction = jurisdiction_of(stop)
    tax_pct = dec(jurisdiction["amusement_tax_pct"]) if jurisdiction else Decimal(0)

    # 1. per-channel gross
    channel_gross = dict((c, 0) for c in GROSS_CHANNELS)
    for sale in sales_of_stop(stop["id"]):
        if sale["channel"] in channel_gross:
            channel_gross[sale["channel"]] += int(sale["units"]) * int(
                sale["unit_price_cents"])
    gross_cents = sum(channel_gross[c] for c in GROSS_CHANNELS)

    # 2. tax rounded per channel then summed
    tax_cents = 0
    for channel in GROSS_CHANNELS:
        tax_cents += cents(dec(channel_gross[channel]) * tax_pct / Decimal(100))

    # 3.
    taxable_net_cents = gross_cents - tax_cents

    # 4. volume tier on the post-tax net
    if taxable_net_cents >= SPLIT_TIER_2_CENTS:
        bonus_pp = Decimal("5.0")
    elif taxable_net_cents >= SPLIT_TIER_1_CENTS:
        bonus_pp = Decimal("2.5")
    else:
        bonus_pp = Decimal("0.0")
    effective_pct = min(dec(contract["revenue_split_pct_operator"]) + bonus_pp,
                        MAX_OPERATOR_PCT)

    # 5.
    split_share_cents = cents(dec(taxable_net_cents) * effective_pct / Decimal(100))

    # 6. ride minimum penalty, capped against the split
    counted = len(allocations_of_stop(stop["id"], RIDE_COUNT_STATUS_SET[variant]))
    shortfall = max(0, int(contract["ride_minimum_count"]) - counted)
    raw_penalty = shortfall * RIDE_SHORTFALL_PENALTY_CENTS
    penalty_cap = cents(dec(split_share_cents) * SHORTFALL_CAP_PCT / Decimal(100))
    shortfall_penalty_cents = min(raw_penalty, penalty_cap)

    # 7. guarantee floor
    operating_days = int(stop["operating_days"])
    guarantee = dec(contract["guarantee_cents"])
    if variant == "PROVISIONAL":
        open_dt = dt(stop, "open_date")
        close_dt = dt(stop, "close_date")
        clock = db.now()
        edge = close_dt if close_dt < clock else clock
        elapsed_raw = floor_int(dec(Decimal((edge - open_dt).total_seconds()))
                                / Decimal(86400)) + 1
        elapsed_days = min(operating_days, max(1, elapsed_raw))
        guarantee_effective_cents = cents(guarantee * dec(elapsed_days)
                                          / dec(operating_days))
        makegood_deduction_cents = 0
    else:
        scheduled_hours = dec(stop["scheduled_operating_hours"])
        adjudicated = dec(stop_closure_hours_adjudicated(stop))
        ratio = adjudicated / scheduled_hours if scheduled_hours > 0 else Decimal(0)
        if ratio > 1:
            ratio = Decimal(1)
        guarantee_effective_cents = cents(guarantee * (Decimal(1) - ratio))
        makegood_deduction_cents = sum(
            int(m["amount_cents"])
            for m in make_goods_of_contract(contract["id"], ("ACCEPTED",))
            if m["kind"] == "CASH_REFUND")

    # 8.
    base_due = split_share_cents - shortfall_penalty_cents
    if contract["settlement_basis"] == "GREATER_OF":
        due = max(base_due, guarantee_effective_cents)
    else:
        due = base_due
    settlement_due_cents = max(0, due - makegood_deduction_cents)

    return {
        "gross_cents": gross_cents,
        "tax_cents": tax_cents,
        "taxable_net_cents": taxable_net_cents,
        "effective_operator_pct": float(rhu(effective_pct, 2)),
        "split_share_cents": split_share_cents,
        "shortfall_penalty_cents": shortfall_penalty_cents,
        "guarantee_effective_cents": guarantee_effective_cents,
        "makegood_deduction_cents": makegood_deduction_cents,
        "settlement_due_cents": settlement_due_cents,
    }


# --------------------------------------------------------------------------
# 5. worker_duty_exposure
# --------------------------------------------------------------------------
def covered_dates(shift_start, shift_end):
    first = db.day_bucket(shift_start)
    last = db.day_bucket(shift_end - timedelta(seconds=1))
    if last < first:
        last = first
    out = set()
    day = first
    while day <= last:
        out.add(day)
        day = day + timedelta(days=1)
    return out


def longest_run(dates):
    if not dates:
        return 0
    ordered = sorted(dates)
    best = 1
    run = 1
    for index in range(1, len(ordered)):
        if (ordered[index] - ordered[index - 1]).days == 1:
            run += 1
        else:
            run = 1
        if run > best:
            best = run
    return best


def worker_consecutive_days(worker_id, jurisdiction_id, extra=None):
    dates = set()
    for assignment in assignments_of_worker(worker_id, ASSIGN_SCHEDULED_SET):
        stop = db.store.route_stops.get(assignment["route_stop_id"])
        if stop is None:
            continue
        jur = jurisdiction_of(stop)
        if jur is None or jur["id"] != jurisdiction_id:
            continue
        dates |= covered_dates(dt(assignment, "shift_start"),
                               dt(assignment, "shift_end"))
    if extra is not None:
        dates |= extra
    return longest_run(dates)


def worker_worked_days_count(worker_id):
    dates = set()
    for assignment in assignments_of_worker(worker_id, ("COMPLETED",)):
        dates |= covered_dates(dt(assignment, "shift_start"),
                               dt(assignment, "shift_end"))
    return len(dates)


def worker_compliance_status(worker):
    if worker["employment_type"] != "H2B_VISA":
        return "CLEAR"
    expires = dt(worker, "visa_expires_on")
    if expires is None:
        return "CLEAR"
    clock = db.now()
    if expires < clock:
        return "VISA_LAPSED"
    if (expires - clock) <= timedelta(days=VISA_EXPIRING_WINDOW_DAYS):
        return "VISA_EXPIRING"
    return "CLEAR"


# --------------------------------------------------------------------------
# 6. weather_abatement_hours
# --------------------------------------------------------------------------
def operating_windows(stop):
    open_dt = dt(stop, "open_date")
    windows = []
    for day in range(int(stop["operating_days"])):
        start = open_dt + timedelta(hours=24 * day)
        windows.append((start, start + timedelta(hours=float(DAILY_OPERATING_HOURS))))
    return windows


def _clip(interval, windows):
    start, end = interval
    out = []
    for w_start, w_end in windows:
        lo = start if start > w_start else w_start
        hi = end if end < w_end else w_end
        if lo < hi:
            out.append((lo, hi))
    return out


def _merge(intervals):
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda iv: (iv[0], iv[1]))
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            if end > last_end:
                merged[-1] = (last_start, end)
        else:
            merged.append((start, end))
    return merged


def _length_hours(intervals):
    total = Decimal(0)
    for start, end in intervals:
        total += hours_between(start, end)
    return total


def _subtract(intervals, claimed):
    """intervals minus the claimed interval set."""
    remaining = list(intervals)
    for c_start, c_end in _merge(claimed):
        nxt = []
        for start, end in remaining:
            if c_end <= start or c_start >= end:
                nxt.append((start, end))
                continue
            if c_start > start:
                nxt.append((start, min(c_start, end)))
            if c_end < end:
                nxt.append((max(c_end, start), end))
        remaining = nxt
    return remaining


def _closure_order_key(closure):
    return (closure["closed_from"], closure["closed_to"], closure["created_at"],
            closure.get("_seq", 0))


def weather_abatement_hours(stop):
    """Writes abated_hours on every ADJUDICATED closure of the stop; returns the
    stop's closure_hours_adjudicated."""
    windows = operating_windows(stop)
    ordered = sorted(closures_of_stop(stop["id"], ("ADJUDICATED",)),
                     key=_closure_order_key)
    clipped_by_row = []
    all_intervals = []
    for closure in ordered:
        clipped = _clip((dt(closure, "closed_from"), dt(closure, "closed_to")),
                        windows)
        clipped_by_row.append((closure, clipped))
        all_intervals.extend(clipped)
    merged_total = rhu(_length_hours(_merge(all_intervals)), 2)

    claimed = []
    for closure, clipped in clipped_by_row:
        own = rhu(_length_hours(_subtract(clipped, claimed)), 2)
        if dec(closure.get("abated_hours", 0)) != own:
            closure["abated_hours"] = float(own)
            db.touch(closure)
        else:
            closure["abated_hours"] = float(own)
        claimed.extend(clipped)

    if merged_total >= ABATEMENT_MIN_HOURS:
        return float(merged_total)
    return 0


def stop_closure_hours_adjudicated(stop):
    """Read-only recomputation (no row writes)."""
    windows = operating_windows(stop)
    intervals = []
    for closure in closures_of_stop(stop["id"], ("ADJUDICATED",)):
        intervals.extend(_clip((dt(closure, "closed_from"),
                                dt(closure, "closed_to")), windows))
    merged_total = rhu(_length_hours(_merge(intervals)), 2)
    if merged_total >= ABATEMENT_MIN_HOURS:
        return float(merged_total)
    return 0


def closure_intersects_window(stop, closed_from, closed_to):
    return bool(_clip((closed_from, closed_to), operating_windows(stop)))


# --------------------------------------------------------------------------
# 7. stop_compliance_posture
# --------------------------------------------------------------------------
def event_permit_ok(stop):
    open_dt = dt(stop, "open_date")
    close_dt = dt(stop, "close_date")
    for permit in permits_of_stop(stop["id"], permit_type="EVENT"):
        if permit["status"] != "APPROVED":
            continue
        if dt(permit, "valid_from") <= open_dt and dt(permit, "valid_until") >= close_dt:
            return True
    return False


def _event_permit_expired_exists(stop):
    for permit in permits_of_stop(stop["id"], permit_type="EVENT"):
        if permit["status"] == "EXPIRED":
            return True
    return False


def inspections_ok(stop):
    jurisdiction = jurisdiction_of(stop)
    open_dt = dt(stop, "open_date")
    for alloc in allocations_of_stop(stop["id"], ALLOC_ACTIVE):
        if alloc["status"] == "INSPECTION_HELD":
            return False
        ride = db.store.rides.get(alloc["ride_id"])
        if ride is None or not ride.get("requires_state_inspection"):
            continue
        if jurisdiction is None or not jurisdiction.get("requires_state_ride_inspection"):
            continue
        passed = False
        for inspection in inspections_of_allocation(alloc["id"]):
            if (inspection["authority"] == "STATE"
                    and inspection["status"] == "PASSED"
                    and dt(inspection, "scheduled_date") <= open_dt):
                passed = True
                break
        if not passed:
            return False
    return True


def crew_coverage_ok(stop):
    venue = venue_of(stop)
    scheduled = assignments_of_stop(stop["id"], ("SCHEDULED",))
    operators = len([a for a in scheduled if a["crew_role"] == "RIDE_OPERATOR"])
    committed = len(allocations_of_stop(stop["id"], ("COMMITTED", "OPERATING")))
    if operators < MIN_OPERATORS_PER_RIDE * committed:
        return False
    for assignment in scheduled:
        worker = db.store.workers.get(assignment["worker_id"])
        if worker is not None and worker_compliance_status(worker) == "VISA_LAPSED":
            return False
    pads_used = len([a for a in scheduled if a.get("housing_pad_assigned")])
    if venue is not None and pads_used > int(venue["housing_pads_available"]):
        return False
    return True


def stop_compliance_posture(stop):
    """First-match-wins ladder; returns (posture, blocking_error_id)."""
    if not event_permit_ok(stop):
        if _event_permit_expired_exists(stop):
            return "PERMIT_HOLD", errors.ERR_PERMIT_EXPIRED
        return "PERMIT_HOLD", errors.ERR_PERMIT_NOT_APPROVED
    if not inspections_ok(stop):
        return "INSPECTION_HOLD", errors.ERR_INSPECTION_NOT_PASSED
    if not crew_coverage_ok(stop):
        return "LABOR_HOLD", errors.ERR_CREW_COVERAGE_INSUFFICIENT
    return "CLEAR", None


def recompute_posture(stop, forced=None):
    posture = forced if forced else stop_compliance_posture(stop)[0]
    if stop.get("compliance_posture") != posture:
        stop["compliance_posture"] = posture
    db.touch(stop)
    return posture


# --------------------------------------------------------------------------
# 8. inspection_slot_selector
# --------------------------------------------------------------------------
def _inspection_jurisdiction_id(inspection):
    alloc = db.store.ride_allocations.get(inspection["ride_allocation_id"])
    if alloc is None:
        return None
    stop = stop_of_allocation(alloc)
    if stop is None:
        return None
    jur = jurisdiction_of(stop)
    return jur["id"] if jur else None


def slots_used(jurisdiction_id, day):
    used = 0
    for inspection in db.store.inspection_orders.values():
        if inspection["status"] not in ("SCHEDULED", "PASSED", "FAILED"):
            continue
        if db.day_bucket(dt(inspection, "scheduled_date")) != day:
            continue
        if _inspection_jurisdiction_id(inspection) != jurisdiction_id:
            continue
        used += 1
    return used


def select_inspection_slot(stop):
    """Earliest UTC day with free capacity, rendered at 14:00:00Z; None when full."""
    jurisdiction = jurisdiction_of(stop)
    if jurisdiction is None:
        return None
    capacity = int(jurisdiction["inspection_slot_capacity_per_day"])
    first = db.day_bucket(dt(stop, "load_in_start"))
    last = db.day_bucket(dt(stop, "open_date"))
    day = first
    while day <= last:
        if slots_used(jurisdiction["id"], day) < capacity:
            return "%04d-%02d-%02dT%sZ" % (day.year, day.month, day.day,
                                           SLOT_TIME_OF_DAY_UTC)
        day = day + timedelta(days=1)
    return None


# --------------------------------------------------------------------------
# 9. makegood_amount
# --------------------------------------------------------------------------
def makegood_amount(contract, stop, closure, settlement, kind):
    scheduled_hours = dec(stop["scheduled_operating_hours"])
    abated = dec(closure.get("abated_hours", 0))
    ratio = abated / scheduled_hours if scheduled_hours > 0 else Decimal(0)
    if ratio > 1:
        ratio = Decimal(1)
    base_cents = cents(dec(settlement["split_share_cents"]) * ratio)
    raw_cents = cents(dec(base_cents) * KIND_MULTIPLIER[kind])
    cap_cents = cents(dec(contract["guarantee_cents"]) * MAKEGOOD_CAP_PCT
                      / Decimal(100))
    already = sum(int(m["amount_cents"]) for m in make_goods_of_contract(
        contract["id"], ("PROPOSED", "ACCEPTED")))
    amount = min(raw_cents, cap_cents)
    if already + amount > cap_cents:
        fail(errors.ERR_MAKEGOOD_CAP_EXCEEDED,
             "The make-good cap for this contract would be exceeded.")
    return amount


# --------------------------------------------------------------------------
# ride double-booking (validation priority 70)
# --------------------------------------------------------------------------
def ride_double_booked(ride, candidate_stop, occupation_start, occupation_end):
    for other in allocations_of_ride(ride["id"], ALLOC_ACTIVE):
        other_stop = stop_of_allocation(other)
        if other_stop is None:
            continue
        other_start = dt(other, "occupation_start")
        other_end = dt(other, "occupation_end")
        # closed intervals on both ends
        if occupation_start <= other_end and other_start <= occupation_end:
            return True
        if other_start > occupation_end:
            gap = hours_between(occupation_end, other_start)
        else:
            gap = hours_between(other_end, occupation_start)
        # the required haul gap belongs to whichever stop sits later in its chain
        if int(other_stop.get("sequence_index", 0)) > int(
                candidate_stop.get("sequence_index", 0)):
            later_stop = other_stop
        else:
            later_stop = candidate_stop
        required = dec(later_stop.get("travel_hours_from_previous", 0)) \
            + TRANSPORT_BUFFER_HOURS
        if gap < required:
            return True
    return False
