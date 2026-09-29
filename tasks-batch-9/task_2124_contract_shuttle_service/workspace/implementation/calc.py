"""Calculations, derived-counter recomputations and cascades.

Every derived counter is a FULL recomputation from its source rows, never an
incremental delta (PRD section 2.7).  All money is integer cents computed with
decimal.Decimal and rounded half up (PRD section 2.9).
"""

import calendar
import datetime as _dt
import math
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

import store
from store import touch

# ------------------------------------------------------------------ constants
LAYOVER_BUFFER_MIN = 12
BOARDING_LEAD_MINUTES = 3
WAIT_SLA_GRACE_MINUTES = 2
WAIT_CREDIT_CENTS_PER_MINUTE = 150
ON_TIME_GRACE_MINUTES = 5
SLA_TIER_1_MAX_SHORTFALL = Decimal("5.00")
SLA_TIER_2_MAX_SHORTFALL = Decimal("15.00")
VOLUME_TIER_1_BOARDINGS = 2000
VOLUME_TIER_2_BOARDINGS = 5000
CLAWBACK_PCT = Decimal("2.0")
MIN_ESCALATION_PCT = Decimal("0.0")
MAX_ESCALATION_PCT = Decimal("6.0")
RENEWAL_WINDOW_DAYS = 60
MEMO_CAP_MULTIPLIER = 3

ACTIVE_CONTRACT_STATES = ("ACTIVE", "RENEWAL_PENDING")
BLOCKING_DISPATCH_STATES = ("ASSIGNED", "IN_SERVICE", "COMPLETED")


# --------------------------------------------------------------- number tools
def dec(value):
    """Exact Decimal from an int/float/str/Decimal without binary noise."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places):
    """Round half up (away from zero at the midpoint) to `places` decimals."""
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def pct_out(value):
    """Serialise a percentage with two decimals as a JSON number."""
    return float(rhu(value, 2))


def ceil_frac(numerator, denominator):
    """Ceiling of an exact rational, never of a pre-rounded decimal."""
    return int(math.ceil(Fraction(numerator) / Fraction(denominator)))


def parse_date(value):
    return _dt.date.fromisoformat(value)


def add_months(day, months):
    total = day.month - 1 + months
    year = day.year + total // 12
    month = total % 12 + 1
    dom = min(day.day, calendar.monthrange(year, month)[1])
    return _dt.date(year, month, dom)


def date_in_range(value, start, end):
    return start <= value <= end


# =============================================================================
# route_fleet_requirement
# =============================================================================
def compute_route_fleet_requirement(route, contract):
    headway_vehicles = ceil_frac(route["loop_minutes"], route["headway_minutes"])
    demand_vehicles = ceil_frac(
        route["demand_forecast_pax_per_hour"] * route["loop_minutes"],
        60 * route["reference_seat_capacity"])
    required = max(headway_vehicles, demand_vehicles)
    route["required_vehicle_count"] = required
    route["ada_required_count"] = ceil_frac(
        Fraction(required) * Fraction(dec(contract["ada_min_accessible_pct"])), 100)


# =============================================================================
# trip_generation
# =============================================================================
def generate_trips(route, service_date):
    span = route["service_window_end_min"] - route["service_window_start_min"]
    count = span // route["headway_minutes"] + 1
    made = []
    for k in range(count):
        departure = route["service_window_start_min"] + k * route["headway_minutes"]
        arrival = departure + route["loop_minutes"]
        trip = store.base_row()
        trip.update({
            "route_id": route["id"],
            "contract_id": route["contract_id"],
            "vehicle_id": None,
            "driver_id": None,
            "service_date": service_date,
            "scheduled_departure_min": departure,
            "scheduled_arrival_min": arrival,
            "actual_departure_min": None,
            "actual_completion_min": None,
            "dispatch_status": "SCHEDULED",
            "settlement_status": "UNBILLED",
            "missed_reason": None,
            "counted_boardings": 0,
            "counted_ada_boardings": 0,
            "matched_party_seats": 0,
        })
        store.register_new(trip)
        store.trips[trip["id"]] = trip
        made.append(trip)
    return made


# =============================================================================
# derived counter recomputations
# =============================================================================
def recompute_contract_credit_balance(contract):
    contract["credit_balance_cents"] = sum(
        m["amount_cents"] for m in store.credit_memos.values()
        if m["contract_id"] == contract["id"] and m["status"] == "ISSUED")
    touch(contract)


def recompute_contract_branded_counts(contract):
    branded = [v for v in store.vehicles.values()
               if v["branding_contract_id"] == contract["id"]
               and v["status"] in ("AVAILABLE", "IN_MAINTENANCE")]
    contract["branded_vehicle_count"] = len(branded)
    contract["branded_ada_vehicle_count"] = sum(1 for v in branded if v["is_ada_accessible"])
    touch(contract)


def branded_counts_after_wrap(contract, vehicle):
    """Resulting branded counts once `vehicle` carries `contract`'s livery."""
    total = 0
    ada = 0
    for v in store.vehicles.values():
        if v["status"] not in ("AVAILABLE", "IN_MAINTENANCE"):
            continue
        wrapped = contract["id"] if v["id"] == vehicle["id"] else v["branding_contract_id"]
        if wrapped == contract["id"]:
            total += 1
            if v["is_ada_accessible"]:
                ada += 1
    return total, ada


def recompute_vehicle_committed_block_minutes(vehicle):
    vehicle["committed_block_minutes"] = sum(
        (t["scheduled_arrival_min"] - t["scheduled_departure_min"]) + LAYOVER_BUFFER_MIN
        for t in store.trips.values()
        if t["vehicle_id"] == vehicle["id"] and t["dispatch_status"] in BLOCKING_DISPATCH_STATES)
    touch(vehicle)


def driver_duty_minutes_on(driver_id, service_date):
    return sum(
        t["scheduled_arrival_min"] - t["scheduled_departure_min"]
        for t in store.trips.values()
        if t["driver_id"] == driver_id and t["service_date"] == service_date
        and t["dispatch_status"] in BLOCKING_DISPATCH_STATES)


def recompute_driver_duty(driver, bump=True):
    value = driver_duty_minutes_on(driver["id"], store.clock_service_date())
    changed = driver["assigned_duty_minutes_current_date"] != value
    driver["assigned_duty_minutes_current_date"] = value
    if bump or changed:
        touch(driver)
    return changed


def recompute_trip_matched_party_seats(trip):
    trip["matched_party_seats"] = sum(
        r["party_size"] for r in store.on_demand_requests.values()
        if r["matched_trip_id"] == trip["id"] and r["status"] in ("MATCHED", "SERVED"))
    touch(trip)


def recompute_trip_counted_boardings(trip):
    rows = [r for r in store.ridership_counts.values() if r["trip_id"] == trip["id"]]
    pool = [r for r in rows if r["source"] == "APC_SENSOR"]
    if not pool:
        pool = [r for r in rows if r["source"] == "DRIVER_TALLY"]
    if pool:
        chosen = max(pool, key=lambda r: r["sequence_no"])
        trip["counted_boardings"] = chosen["boarded"]
        trip["counted_ada_boardings"] = chosen["ada_boardings"]
    else:
        trip["counted_boardings"] = 0
        trip["counted_ada_boardings"] = 0
    touch(trip)


def next_sequence_no(trip_id):
    highest = 0
    for row in store.ridership_counts.values():
        if row["trip_id"] == trip_id and row["sequence_no"] > highest:
            highest = row["sequence_no"]
    return highest + 1


def append_ridership_row(trip, boarded, alighted, ada_boardings, source, user_id):
    row = store.base_row(with_version=False)
    row.update({
        "trip_id": trip["id"],
        "boarded": boarded,
        "alighted": alighted,
        "ada_boardings": ada_boardings,
        "source": source,
        "sequence_no": next_sequence_no(trip["id"]),
        "recorded_by_user_id": user_id,
    })
    store.register_new(row)
    store.ridership_counts[row["id"]] = row
    return row


# =============================================================================
# credit memos
# =============================================================================
def mint_credit_memo(contract, trip_id, reason, amount_cents):
    memo = store.base_row()
    memo.update({
        "contract_id": contract["id"],
        "trip_id": trip_id,
        "applied_report_id": None,
        "amount_cents": amount_cents,
        "reason": reason,
        "status": "ISSUED",
        "voided_reason": None,
    })
    store.register_new(memo)
    store.credit_memos[memo["id"]] = memo
    recompute_contract_credit_balance(contract)
    return memo


# =============================================================================
# on_demand_wait_estimate — PROMISED variant
# =============================================================================
def eligible_promise_routes(contract_id, service_date, pickup_min):
    candidates = [r for r in store.routes.values()
                  if r["contract_id"] == contract_id
                  and r["status"] == "PUBLISHED"
                  and r["published_service_date"] == service_date
                  and r["service_window_start_min"] <= pickup_min
                  and pickup_min <= r["service_window_end_min"]]
    candidates.sort(key=lambda r: (r["headway_minutes"], r["created_at"], r["_seq"]))
    return candidates


def promised_wait_from_headway(headway_minutes):
    return ceil_frac(headway_minutes, 2) + BOARDING_LEAD_MINUTES


def recompute_promised_wait(request_row):
    """PROMISED variant re-run after a match is undone.  promised_headway_minutes
    stays frozen at its creation value (entity contract)."""
    candidates = eligible_promise_routes(request_row["contract_id"],
                                         request_row["service_date"],
                                         request_row["requested_pickup_min"])
    if not candidates:
        return
    request_row["promised_wait_minutes"] = promised_wait_from_headway(
        candidates[0]["headway_minutes"])


# =============================================================================
# trip_match_selector
# =============================================================================
def trip_seat_basis(trip):
    if trip["vehicle_id"]:
        vehicle = store.vehicles.get(trip["vehicle_id"])
        if vehicle is not None:
            return vehicle["seat_capacity"]
    route = store.routes.get(trip["route_id"])
    return route["reference_seat_capacity"] if route else 0


def remaining_seats(trip):
    return trip_seat_basis(trip) - trip["matched_party_seats"]


def selector_candidates(request_row):
    out = []
    for trip in store.trips.values():
        if trip["contract_id"] != request_row["contract_id"]:
            continue
        if trip["service_date"] != request_row["service_date"]:
            continue
        if trip["dispatch_status"] not in ("SCHEDULED", "ASSIGNED"):
            continue
        if trip["scheduled_departure_min"] < request_row["requested_pickup_min"]:
            continue
        route = store.routes.get(trip["route_id"])
        if route is None or route["status"] != "PUBLISHED":
            continue
        if request_row["requires_ada"]:
            vehicle = store.vehicles.get(trip["vehicle_id"]) if trip["vehicle_id"] else None
            if vehicle is None or not vehicle["is_ada_accessible"]:
                continue
        if remaining_seats(trip) < request_row["party_size"]:
            continue
        out.append((trip, route))
    out.sort(key=lambda pair: (pair[0]["scheduled_departure_min"],
                               pair[1]["headway_minutes"],
                               pair[0]["created_at"],
                               pair[0]["_seq"]))
    return [pair[0] for pair in out]


# =============================================================================
# cascades
# =============================================================================
def release_trip_bindings(trip):
    """Clear vehicle/driver from a trip and recompute both derived counters."""
    vehicle = store.vehicles.get(trip["vehicle_id"]) if trip["vehicle_id"] else None
    driver = store.drivers.get(trip["driver_id"]) if trip["driver_id"] else None
    trip["vehicle_id"] = None
    trip["driver_id"] = None
    if vehicle is not None:
        recompute_vehicle_committed_block_minutes(vehicle)
    if driver is not None:
        recompute_driver_duty(driver)
    return vehicle, driver


def revert_matched_requests_to_pending(trip):
    """MATCHED -> PENDING for every rider of `trip` (unassign / displacement /
    republish cascade)."""
    reverted = []
    for req in store.on_demand_requests.values():
        if req["matched_trip_id"] == trip["id"] and req["status"] == "MATCHED":
            req["status"] = "PENDING"
            req["matched_trip_id"] = None
            recompute_promised_wait(req)
            touch(req)
            reverted.append(req)
    if reverted:
        recompute_trip_matched_party_seats(trip)
    return reverted


def deny_matched_requests(trip):
    """MATCHED -> DENIED (mark-missed cascade)."""
    denied = []
    for req in store.on_demand_requests.values():
        if req["matched_trip_id"] == trip["id"] and req["status"] == "MATCHED":
            req["status"] = "DENIED"
            req["matched_trip_id"] = None
            touch(req)
            denied.append(req)
    if denied:
        recompute_trip_matched_party_seats(trip)
    return denied


def cancel_trip(trip):
    """SCHEDULED / ASSIGNED -> CANCELLED (republish, retire, terminate)."""
    if trip["dispatch_status"] not in ("SCHEDULED", "ASSIGNED"):
        return False
    was_assigned = trip["dispatch_status"] == "ASSIGNED"
    trip["dispatch_status"] = "CANCELLED"
    if was_assigned:
        release_trip_bindings(trip)
    touch(trip)
    return True


def retire_route(route, cancel_children=True):
    route["status"] = "RETIRED"
    touch(route)
    if cancel_children:
        for trip in list(store.trips.values()):
            if trip["route_id"] == route["id"]:
                cancel_trip(trip)


def check_route_degradation(route, service_date):
    """PUBLISHED -> DEGRADED after a maintenance displacement (PRD 3.2 / 3.3)."""
    if route["status"] != "PUBLISHED":
        return False
    bound = {t["vehicle_id"] for t in store.trips.values()
             if t["route_id"] == route["id"]
             and t["service_date"] == service_date
             and t["dispatch_status"] in ("ASSIGNED", "IN_SERVICE")
             and t["vehicle_id"]}
    if len(bound) < route["required_vehicle_count"]:
        route["status"] = "DEGRADED"
        touch(route)
        return True
    return False


# =============================================================================
# period settlement — period_gross_amount / period_sla_penalty /
#                     period_net_settlement
# =============================================================================
def _period_trips(report):
    start = report["period_start_date"]
    end = report["period_end_date"]
    return [t for t in store.trips.values()
            if t["contract_id"] == report["contract_id"]
            and start <= t["service_date"] <= end]


def settlement_input_set(report, variant):
    period = _period_trips(report)
    if variant == "PROVISIONAL":
        return [t for t in period
                if t["dispatch_status"] in ("SCHEDULED", "ASSIGNED", "IN_SERVICE", "COMPLETED")]
    return [t for t in period if t["dispatch_status"] == "COMPLETED"]


def period_credit_memos(report):
    start = report["period_start_date"]
    end = report["period_end_date"]
    out = []
    for memo in store.credit_memos.values():
        if memo["contract_id"] != report["contract_id"]:
            continue
        if memo["status"] != "ISSUED":
            continue
        if not memo["trip_id"]:
            continue
        trip = store.trips.get(memo["trip_id"])
        if trip is None:
            continue
        if start <= trip["service_date"] <= end:
            out.append(memo)
    return out


def compute_settlement(report, contract, variant):
    """Single-pass, pinned evaluation order: gross -> penalty -> credit -> net."""
    period = _period_trips(report)
    input_set = settlement_input_set(report, variant)

    # ---- 1. gross -----------------------------------------------------------
    if variant == "PROVISIONAL":
        minutes = sum(t["scheduled_arrival_min"] - t["scheduled_departure_min"]
                      for t in input_set)
    else:
        minutes = sum((t["actual_completion_min"] or 0) - (t["actual_departure_min"] or 0)
                      for t in input_set)
    report["total_billable_minutes"] = minutes
    hours = rhu(Decimal(minutes) / Decimal(60), 2)
    report["billable_service_hours"] = float(hours)
    gross = rhu_int(hours * Decimal(report["effective_rate_cents_per_service_hour"]))
    report["gross_amount_cents"] = gross

    # ---- 2. penalty (reads gross) ------------------------------------------
    countable = [t for t in period
                 if t["dispatch_status"] in ("COMPLETED", "MISSED")
                 and t["settlement_status"] != "WAIVED"]
    on_time = [t for t in countable
               if t["dispatch_status"] == "COMPLETED"
               and t["actual_departure_min"] is not None
               and (t["actual_departure_min"] - t["scheduled_departure_min"])
               <= ON_TIME_GRACE_MINUTES]
    report["countable_trip_count"] = len(countable)
    report["on_time_trip_count"] = len(on_time)
    if not countable:
        on_time_pct = Decimal("100.00")
    else:
        on_time_pct = rhu(Decimal(100) * Decimal(len(on_time)) / Decimal(len(countable)), 2)
    report["on_time_pct"] = float(on_time_pct)

    shortfall = dec(contract["sla_on_time_threshold_pct"]) - on_time_pct
    if shortfall <= 0:
        tier = Decimal(0)
    elif shortfall <= SLA_TIER_1_MAX_SHORTFALL:
        tier = Decimal(2)
    elif shortfall <= SLA_TIER_2_MAX_SHORTFALL:
        tier = Decimal(5)
    else:
        tier = Decimal(10)
    report["penalty_tier_pct"] = float(tier)
    report["sla_penalty_cents"] = rhu_int(Decimal(gross) * tier / Decimal(100))

    missed = [t for t in period
              if t["dispatch_status"] == "MISSED" and t["settlement_status"] != "WAIVED"]
    waived = [t for t in period
              if t["dispatch_status"] == "MISSED" and t["settlement_status"] == "WAIVED"]
    report["missed_trip_count"] = len(missed)
    report["waived_trip_count"] = len(waived)
    report["missed_trip_penalty_cents"] = (
        len(missed) * contract["penalty_rate_cents_per_missed_trip"])
    report["penalty_amount_cents"] = (report["sla_penalty_cents"]
                                      + report["missed_trip_penalty_cents"])

    # ---- 3. credits (reads neither) ----------------------------------------
    memos = period_credit_memos(report)
    report["credit_amount_cents"] = sum(m["amount_cents"] for m in memos)

    # ---- 4. net (reads 1..3, floored at 0 and never fed back) ---------------
    report["net_amount_cents"] = max(0, gross
                                     - report["penalty_amount_cents"]
                                     - report["credit_amount_cents"])

    report["total_boardings"] = sum(t["counted_boardings"] for t in input_set)
    report["total_ada_boardings"] = sum(t["counted_ada_boardings"] for t in input_set)
    report["scheduled_trip_count"] = len(input_set)
    report["completed_trip_count"] = sum(1 for t in period
                                         if t["dispatch_status"] == "COMPLETED")
    report["settlement_variant"] = variant
    return input_set, memos


SETTLEMENT_FIGURES = (
    "scheduled_trip_count", "completed_trip_count", "missed_trip_count",
    "waived_trip_count", "countable_trip_count", "on_time_trip_count", "on_time_pct",
    "total_boardings", "total_ada_boardings", "total_billable_minutes",
    "billable_service_hours", "gross_amount_cents", "penalty_tier_pct",
    "sla_penalty_cents", "missed_trip_penalty_cents", "penalty_amount_cents",
    "credit_amount_cents", "net_amount_cents",
)


def zero_settlement(report):
    for field in SETTLEMENT_FIGURES:
        report[field] = 0
    report["settlement_variant"] = "NONE"


# =============================================================================
# renewal_proposed_rate
# =============================================================================
def basis_report_for(contract):
    approved = [r for r in store.service_period_reports.values()
                if r["contract_id"] == contract["id"] and r["status"] == "APPROVED"]
    if not approved:
        return None
    approved.sort(key=lambda r: (r["period_end_date"], r["created_at"], r["_seq"]))
    return approved[-1]


def compute_renewal_pricing(contract):
    basis = basis_report_for(contract)
    if basis is None:
        volume = Decimal("0.0")
        clawback = Decimal("0.0")
    else:
        boardings = basis["total_boardings"]
        if boardings < VOLUME_TIER_1_BOARDINGS:
            volume = Decimal("0.0")
        elif boardings < VOLUME_TIER_2_BOARDINGS:
            volume = Decimal("1.5")
        else:
            volume = Decimal("3.0")
        if dec(basis["on_time_pct"]) < dec(contract["sla_on_time_threshold_pct"]):
            clawback = CLAWBACK_PCT
        else:
            clawback = Decimal("0.0")
    raw = dec(contract["escalation_index_pct"]) + volume - clawback
    applied = min(max(raw, MIN_ESCALATION_PCT), MAX_ESCALATION_PCT)
    rate = rhu_int(Decimal(contract["base_rate_cents_per_service_hour"])
                   * (Decimal(1) + applied / Decimal(100)))
    return {
        "basis_report_id": None if basis is None else basis["id"],
        "volume_pct": pct_out(volume),
        "clawback_pct": pct_out(clawback),
        "applied_escalation_pct": pct_out(applied),
        "proposed_rate_cents_per_service_hour": rate,
    }
