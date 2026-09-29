"""The eight calculations of the PRD, kept free of storage concerns."""
from datetime import timedelta
from decimal import Decimal

from util import date_key, dec2, dt_of, minutes_between, money, pct2, round_half_up

# Both utilization variants share this rounding: percent to two decimals, half up.
pct = pct2

# --- rotation feasibility -------------------------------------------------
INTERNATIONAL_TURN_BUMP_MINUTES = 15

# --- gate occupancy -------------------------------------------------------
GATE_PREP_MINUTES = 45
GATE_RELEASE_MINUTES = 30

# --- compliance score ----------------------------------------------------
SCORE_BASE = Decimal("100.00")
W_CURFEW = Decimal("12.00")
W_MCT = Decimal("7.00")
W_GATE = Decimal("9.00")
W_UNSLOTTED = Decimal("8.00")
W_AT_RISK_SLOT = Decimal("15.00")
BLOCK_THRESHOLD = Decimal("60.00")
WARN_THRESHOLD = Decimal("85.00")

# --- filing change charge ------------------------------------------------
BASE_RATE_PER_LEG_CENTS = 4225
TIER_1_MAX_LEGS = 5
TIER_2_MAX_LEGS = 20
TIER_1_SURCHARGE_PCT = Decimal("0.00")
TIER_2_SURCHARGE_PCT = Decimal("12.50")
TIER_3_SURCHARGE_PCT = Decimal("22.00")
EXPEDITE_RATE_PCT = {
    "STANDARD": Decimal("0.00"),
    "EXPEDITED": Decimal("35.00"),
    "EMERGENCY": Decimal("80.00"),
}

# --- notification compensation -------------------------------------------
MIN_MAGNITUDE_MINUTES = 30
TIER_THRESHOLD_MINUTES = 120
ADVISORY_MULTIPLIER_PCT = Decimal("37.50")
MANDATORY_MULTIPLIER_PCT = Decimal("100.00")
RATE_FIRST_CENTS = 61500
RATE_BUSINESS_CENTS = 40252
RATE_ECONOMY_CENTS = 25124
NOTIFY_WINDOW_HOURS = 72
CANCELLATION_EQUIVALENT_MINUTES = 240

# --- slot utilization ----------------------------------------------------
CREDITED_OUTCOMES = ("OPERATED", "CANCELLED_ATC", "RETURNED_IN_TIME")
UTILIZATION_THRESHOLD = 80.00


def leg_order_key(leg):
    """The pinned rotation order: dep_utc ascending, then created_at ascending."""
    return (leg["dep_utc"], leg["_seq"])


def group_by_dep_date(legs):
    """Ordered list of (date, legs) groups, each group in pinned order."""
    groups = {}
    for leg in legs:
        key = date_key(dt_of(leg["dep_utc"]))
        groups.setdefault(key, []).append(leg)
    return [(key, groups[key]) for key in sorted(groups)]


def required_turn_minutes(aircraft, inbound_leg, station_lookup):
    station = station_lookup(inbound_leg["dest_station_id"])
    floor = station["min_turn_override_minutes"] if station else 0
    required = max(aircraft["min_turn_minutes"], floor or 0)
    if inbound_leg.get("is_international"):
        required += INTERNATIONAL_TURN_BUMP_MINUTES
    return required


def rotation_walk(aircraft, legs, station_lookup):
    """Return (status, first_violation_leg_id, first_required_turn, total_block)."""
    ordered = sorted(legs, key=leg_order_key)
    total_block = sum(leg["block_minutes"] or 0 for leg in ordered)
    groups = group_by_dep_date(ordered)

    first_turn = 0
    for _, group in groups:
        if len(group) >= 2:
            first_turn = required_turn_minutes(aircraft, group[0], station_lookup)
            break

    if not ordered:
        return "UNCHECKED", None, first_turn, total_block

    # 1. continuity, across every date group, before any other check runs.
    for _, group in groups:
        for index in range(len(group) - 1):
            earlier, later = group[index], group[index + 1]
            if earlier["dest_station_id"] != later["origin_station_id"]:
                return "INFEASIBLE_CONTINUITY", later["id"], first_turn, total_block

    # 2. turn time, inclusive comparison.
    for _, group in groups:
        for index in range(len(group) - 1):
            earlier, later = group[index], group[index + 1]
            needed = required_turn_minutes(aircraft, earlier, station_lookup)
            earliest_departure = dt_of(earlier["arr_utc"]) + timedelta(minutes=needed)
            if dt_of(later["dep_utc"]) < earliest_departure:
                return "INFEASIBLE_TURN", later["id"], first_turn, total_block

    # 3. daily block cap, per date group.
    cap = aircraft["max_daily_block_minutes"]
    for _, group in groups:
        running = 0
        for leg in group:
            running += leg["block_minutes"] or 0
            if running > cap:
                return "INFEASIBLE_BLOCK_CAP", leg["id"], first_turn, total_block

    return "FEASIBLE", None, first_turn, total_block


def maintenance_windows(legs, station_lookup):
    """Merged kept ground intervals, as (contiguous_minutes, cumulative_minutes)."""
    ordered = sorted(legs, key=leg_order_key)
    kept = {}
    for _, group in group_by_dep_date(ordered):
        for index in range(len(group) - 1):
            earlier, later = group[index], group[index + 1]
            station = station_lookup(earlier["dest_station_id"])
            if not station or not station.get("maintenance_capable"):
                continue
            start = dt_of(earlier["arr_utc"])
            end = dt_of(later["dep_utc"])
            if end <= start:
                continue
            kept.setdefault(earlier["dest_station_id"], []).append((start, end))

    contiguous = 0
    cumulative = 0
    for intervals in kept.values():
        merged = []
        for start, end in sorted(intervals):
            if merged and start <= merged[-1][1]:
                if end > merged[-1][1]:
                    merged[-1] = (merged[-1][0], end)
            else:
                merged.append((start, end))
        for start, end in merged:
            length = minutes_between(start, end)
            cumulative += length
            if length > contiguous:
                contiguous = length
    return contiguous, cumulative


def gate_intervals(legs, station_id, day):
    """Half-open occupancy intervals at one station on one UTC calendar date."""
    intervals = []
    for leg in legs:
        if leg["origin_station_id"] == station_id:
            departure = dt_of(leg["dep_utc"])
            if date_key(departure) == day:
                intervals.append((departure - timedelta(minutes=GATE_PREP_MINUTES), departure))
        if leg["dest_station_id"] == station_id:
            arrival = dt_of(leg["arr_utc"])
            if date_key(arrival) == day:
                intervals.append((arrival, arrival + timedelta(minutes=GATE_RELEASE_MINUTES)))
    return intervals


def peak_concurrency(intervals):
    """Sweep endpoints ascending, processing every ending before any beginning."""
    events = []
    for start, end in intervals:
        events.append((start, 1))
        events.append((end, -1))
    events.sort(key=lambda item: (item[0], item[1]))
    peak = 0
    active = 0
    for _, delta in events:
        active += delta
        if active > peak:
            peak = active
    return peak


def station_date_pairs(legs):
    """Every (station_id, UTC date) pair a set of legs touches."""
    pairs = set()
    for leg in legs:
        pairs.add((leg["origin_station_id"], date_key(dt_of(leg["dep_utc"]))))
        pairs.add((leg["dest_station_id"], date_key(dt_of(leg["arr_utc"]))))
    return pairs


def in_curfew(station, instant):
    """Local minute-of-day inside the station's curfew: start inclusive, end exclusive."""
    start = station.get("curfew_start_local_minutes")
    end = station.get("curfew_end_local_minutes")
    if start is None or end is None:
        return False
    local = (instant.hour * 60 + instant.minute + station["utc_offset_minutes"]) % 1440
    if start <= end:
        return start <= local < end
    return local >= start or local < end


def compliance_score(counters):
    """Weighted score: raw penalty, capped at 100.00, subtracted from the base."""
    raw = (
        Decimal(counters["curfew_violation_count"]) * W_CURFEW
        + Decimal(counters["mct_violation_count"]) * W_MCT
        + Decimal(counters["gate_overflow_count"]) * W_GATE
        + Decimal(counters["unslotted_leg_count"]) * W_UNSLOTTED
        + Decimal(counters["at_risk_slot_count"]) * W_AT_RISK_SLOT
    )
    capped = raw if raw < SCORE_BASE else SCORE_BASE
    score = SCORE_BASE - capped
    if score < 0:
        score = Decimal("0.00")
    return dec2(score)


def compliance_state(score, at_risk_slot_count):
    """The at-risk test is first, which is what makes a single at-risk slot block."""
    value = Decimal(str(score))
    if at_risk_slot_count >= 1 or value < BLOCK_THRESHOLD:
        return "BLOCKED"
    if value < WARN_THRESHOLD:
        return "WARNED"
    return "CLEAN"


def surcharge_pct(changed_leg_count):
    if changed_leg_count <= TIER_1_MAX_LEGS:
        return TIER_1_SURCHARGE_PCT
    if changed_leg_count <= TIER_2_MAX_LEGS:
        return TIER_2_SURCHARGE_PCT
    return TIER_3_SURCHARGE_PCT


def filing_charge(changed_leg_count, change_window):
    """The five pinned steps of the filing change charge."""
    raw = Decimal(changed_leg_count) * Decimal(BASE_RATE_PER_LEG_CENTS)
    surcharge = surcharge_pct(changed_leg_count)
    subtotal = money(raw * (Decimal(100) + surcharge) / Decimal(100))
    rate = EXPEDITE_RATE_PCT[change_window]
    fee = money(Decimal(subtotal) * rate / Decimal(100))
    return {
        "base_charge_subtotal_cents": subtotal,
        "expedite_rate_pct": dec2(rate),
        "expedite_fee_cents": fee,
        "total_charge_cents": subtotal + fee,
    }


def obligation_tier(magnitude):
    if magnitude >= TIER_THRESHOLD_MINUTES:
        return "MANDATORY_REACCOMMODATION"
    return "ADVISORY"


def compensation_cents(tier, booked_first, booked_business, booked_economy):
    """Each cabin is rounded to whole cents first; only then are the three summed."""
    multiplier = MANDATORY_MULTIPLIER_PCT if tier == "MANDATORY_REACCOMMODATION" else ADVISORY_MULTIPLIER_PCT
    total = 0
    for count, rate in (
        (booked_first, RATE_FIRST_CENTS),
        (booked_business, RATE_BUSINESS_CENTS),
        (booked_economy, RATE_ECONOMY_CENTS),
    ):
        amount = Decimal(count) * Decimal(rate) * multiplier / Decimal(100)
        total += int(round_half_up(amount, 0))
    return total
