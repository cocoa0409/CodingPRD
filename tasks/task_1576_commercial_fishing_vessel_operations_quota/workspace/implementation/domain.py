"""Business logic: calculations, projections, cascades, clock transitions."""

import math
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from errors import ApiError
import store
from common import touch, make_event
from store import parse_dt, now_iso

FISHERY_CODES = ["HALIBUT", "SABLEFISH", "POLLOCK", "PACIFIC_COD"]
GEAR_TYPES = ["TRAWL_NET", "LONGLINE", "POT", "GILLNET"]

OBSERVER_DAY_RATE_CENTS = 45000
GEAR_UNIT_REPLACEMENT_CENTS = 25000
VESSEL_SHARE_PCT = Decimal("0.60")
PROCESSING_FEE_PCT = Decimal("0.015")
DISCREPANCY_TOLERANCE_PCT = Decimal("0.05")
FLAT_FEE_CENTS = 25000
VMS_MAX_GAP_MINUTES = 120
SUSPENSION_THRESHOLD = 50

BASE_POINTS = {
    "OVER_QUOTA": 20,
    "OUT_OF_SEASON": 25,
    "OBSERVER_BREACH": 15,
    "VMS_GAP": 10,
    "GEAR_MISMATCH": 5,
    "MANUAL_CITATION": 10,
}

VIOLATION_TYPES = list(BASE_POINTS.keys())


def rhu(value):
    """Round half-up a Decimal to an integer."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Quota availability
# ---------------------------------------------------------------------------

def availability(holding):
    leased_in = 0
    leased_out = 0
    pending_out = 0
    for t in store.db.transfers.values():
        if t["fishery_code"] != holding["fishery_code"]:
            continue
        if t["season_year"] != holding["season_year"]:
            continue
        if t["from_vessel_id"] == holding["vessel_id"]:
            if t["status"] in ("ACCEPTED", "SETTLED"):
                leased_out += t["pounds"]
            elif t["status"] in ("PROPOSED", "COUNTERED"):
                pending_out += t["pounds"]
        if t["to_vessel_id"] == holding["vessel_id"]:
            if t["status"] in ("ACCEPTED", "SETTLED"):
                leased_in += t["pounds"]
    committed = holding["initial_pounds"] - holding["landed_pounds"] + leased_in - leased_out
    conservative = committed - pending_out
    return {
        "available_committed_pounds": committed,
        "available_conservative_pounds": conservative,
        "landed_pounds": holding["landed_pounds"],
        "leased_in_pounds": leased_in,
        "leased_out_pounds": leased_out,
    }


# ---------------------------------------------------------------------------
# Trips and observer coverage
# ---------------------------------------------------------------------------

def compute_observer_required(vessel, planned_departure, planned_return):
    cls = vessel["observer_coverage_class"]
    if cls == "FULL":
        return True
    if cls == "EXEMPT":
        return False
    # PARTIAL: required only when planned duration strictly exceeds 72 hours
    return (planned_return - planned_departure).total_seconds() > 72 * 3600


def create_observer_request(trip):
    assignment = {
        "trip_id": trip["id"],
        "observer_id": None,
        "coverage_from": None,
        "coverage_to": None,
        "auto_created": True,
        "status": "REQUESTED",
    }
    from common import make_entity

    entity = make_entity(assignment)
    store.db.assignments[entity["id"]] = entity
    return entity


def recompute_observer_status(observer):
    active = any(
        a["observer_id"] == observer["id"] and a["status"] in ("ASSIGNED", "CONFIRMED", "DEPLOYED")
        for a in store.db.assignments.values()
    )
    new_status = "ON_ASSIGNMENT" if active else "AVAILABLE"
    if observer["status"] != new_status:
        observer["status"] = new_status
        touch(observer)


def cancel_trip_cascade(trip):
    """PLANNED -> CANCELLED plus non-terminal assignment cancellation."""
    if trip["status"] != "PLANNED":
        return
    trip["status"] = "CANCELLED"
    touch(trip)
    for a in store.db.assignments.values():
        if a["trip_id"] == trip["id"] and a["status"] in ("REQUESTED", "ASSIGNED", "CONFIRMED"):
            a["status"] = "CANCELLED"
            touch(a)
            if a.get("observer_id"):
                observer = store.db.observers.get(a["observer_id"])
                if observer:
                    recompute_observer_status(observer)


def suspend_vessel_cascade(vessel):
    if vessel["status"] != "ACTIVE":
        return
    vessel["status"] = "SUSPENDED"
    touch(vessel)
    for p in store.db.permits.values():
        if p["vessel_id"] == vessel["id"] and p["status"] == "ISSUED":
            p["status"] = "SUSPENDED"
            touch(p)
    for t in store.db.trips.values():
        if t["vessel_id"] == vessel["id"] and t["status"] == "PLANNED":
            cancel_trip_cascade(t)


def close_opening_cascade(opening, early):
    opening["status"] = "CLOSED_EARLY" if early else "CLOSED"
    touch(opening)
    for t in store.db.trips.values():
        if t["season_opening_id"] == opening["id"] and t["status"] == "PLANNED":
            cancel_trip_cascade(t)


# ---------------------------------------------------------------------------
# Logical clock transitions
# ---------------------------------------------------------------------------

def _season_year_end(season_year):
    return datetime(season_year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)


def advance_clock(to_dt):
    store.db.clock = to_dt

    for o in list(store.db.openings.values()):
        if o["status"] == "SCHEDULED" and parse_dt(o["opens_at"]) <= to_dt:
            o["status"] = "OPEN"
            touch(o)
    for o in list(store.db.openings.values()):
        if o["status"] == "OPEN" and parse_dt(o["closes_at"]) < to_dt:
            close_opening_cascade(o, early=False)
        elif o["status"] == "SCHEDULED" and parse_dt(o["closes_at"]) < to_dt:
            # Unreachable in practice (opens_at < closes_at crossed first); kept
            # for completeness.
            o["status"] = "CLOSED"
            touch(o)

    for p in list(store.db.permits.values()):
        if p["status"] in ("ISSUED", "SUSPENDED") and parse_dt(p["valid_to"]) < to_dt:
            p["status"] = "EXPIRED"
            touch(p)

    for t in list(store.db.transfers.values()):
        if t["status"] in ("PROPOSED", "COUNTERED", "ACCEPTED") and _season_year_end(
            t["season_year"]
        ) < to_dt:
            was = t["status"]
            t["status"] = "EXPIRED"
            touch(t)
            if was == "ACCEPTED":
                # Compensating release of the reserved pounds: availability is
                # computed from transfer statuses, so the release is implicit;
                # bump both holdings to record the mutation.
                from common import find_holding

                from_h = find_holding(t["from_vessel_id"], t["fishery_code"], t["season_year"])
                to_h = find_holding(t["to_vessel_id"], t["fishery_code"], t["season_year"])
                if from_h:
                    touch(from_h)
                if to_h:
                    touch(to_h)

    for h in list(store.db.holdings.values()):
        if h["status"] == "ACTIVE" and _season_year_end(h["season_year"]) < to_dt:
            h["status"] = "CLOSED"
            touch(h)


# ---------------------------------------------------------------------------
# Landing declarations
# ---------------------------------------------------------------------------

def compute_discrepancy_details(trip_id, lines):
    details = []
    for line in lines:
        fishery = line["fishery_code"]
        harvest = sum(
            r["reported_lbs"]
            for r in store.db.catch_reports.values()
            if r["trip_id"] == trip_id
            and r["fishery_code"] == fishery
            and r["report_type"] == "HARVEST"
        )
        discard = sum(
            r["reported_lbs"]
            for r in store.db.catch_reports.values()
            if r["trip_id"] == trip_id
            and r["fishery_code"] == fishery
            and r["report_type"] == "DISCARD"
        )
        expected = harvest - discard
        declared = line["declared_lbs"]
        if expected == 0:
            within = declared == 0
        else:
            tolerance = rhu(DISCREPANCY_TOLERANCE_PCT * expected)
            within = abs(declared - expected) <= tolerance
        details.append(
            {
                "fishery_code": fishery,
                "expected_lbs": expected,
                "declared_lbs": declared,
                "within_tolerance": within,
            }
        )
    return details


# ---------------------------------------------------------------------------
# Settlement math
# ---------------------------------------------------------------------------

def observer_fee_for_trip(trip_id):
    fee = 0
    us_per_day = 86400 * 1_000_000
    for a in store.db.assignments.values():
        if a["trip_id"] != trip_id or a["status"] not in ("DEPLOYED", "DEBRIEFED"):
            continue
        delta = parse_dt(a["coverage_to"]) - parse_dt(a["coverage_from"])
        micros = int(delta.total_seconds() * 1_000_000)
        days = math.ceil(micros / us_per_day)
        fee += days * OBSERVER_DAY_RATE_CENTS
    return fee


def gear_loss_charge_for_trip(trip_id):
    loss = sum(
        e["units"]
        for e in store.db.gear_events.values()
        if e.get("trip_id") == trip_id and e["event_type"] == "LOSS"
    )
    repair = sum(
        e["units"]
        for e in store.db.gear_events.values()
        if e.get("trip_id") == trip_id and e["event_type"] == "REPAIR"
    )
    return max(0, loss - repair) * GEAR_UNIT_REPLACEMENT_CENTS


def settlement_math(trip, gross_revenue_cents, variant):
    """variant: 'provisional' counts PENDING+VERIFIED; 'final' counts VERIFIED."""
    statuses = ("VERIFIED",) if variant == "final" else ("PENDING", "VERIFIED")
    total_expenses = sum(
        e["amount_cents"]
        for e in store.db.expenses.values()
        if e["trip_id"] == trip["id"] and e["status"] in statuses
    )
    observer_fee = observer_fee_for_trip(trip["id"])
    gear_loss = gear_loss_charge_for_trip(trip["id"])
    net_before_fee = gross_revenue_cents - total_expenses - observer_fee - gear_loss
    processing_fee = rhu(PROCESSING_FEE_PCT * net_before_fee)
    net = net_before_fee - processing_fee
    vessel_share = rhu(VESSEL_SHARE_PCT * net)
    crew_pool = net - vessel_share
    return {
        "total_expenses_cents": total_expenses,
        "observer_fee_cents": observer_fee,
        "gear_loss_charge_cents": gear_loss,
        "net_before_fee_cents": net_before_fee,
        "processing_fee_cents": processing_fee,
        "net_cents": net,
        "vessel_share_cents": vessel_share,
        "crew_pool_cents": crew_pool,
    }


def crew_pool_split(vessel_id, crew_pool_cents):
    contracts = [
        c
        for c in store.db.crew_contracts.values()
        if c["vessel_id"] == vessel_id and c["status"] == "ACTIVE"
    ]
    contracts.sort(
        key=lambda c: (
            -Fraction(str(c["share_points"])),
            parse_dt(c["joined_at"]),
            c["created_at"],
            c["_seq"],
        )
    )
    total_points = sum(Fraction(str(c["share_points"])) for c in contracts)
    payouts = []
    for c in contracts:
        raw = Fraction(crew_pool_cents) * Fraction(str(c["share_points"])) / total_points
        floored = raw.numerator // raw.denominator
        payouts.append(
            {
                "crew_contract_id": c["id"],
                "crew_name": c["crew_name"],
                "payout_cents": floored,
            }
        )
    remainder = crew_pool_cents - sum(p["payout_cents"] for p in payouts)
    idx = 0
    while remainder > 0 and payouts:
        payouts[idx % len(payouts)]["payout_cents"] += 1
        remainder -= 1
        idx += 1
    return payouts


# ---------------------------------------------------------------------------
# Quota transfer fee schedule
# ---------------------------------------------------------------------------

def transfer_fee(pounds, price_per_lb_cents):
    if pounds <= 1000:
        return FLAT_FEE_CENTS
    if pounds <= 10000:
        value = pounds * price_per_lb_cents
        return FLAT_FEE_CENTS + rhu(Decimal("0.04") * value)
    mid = rhu(Decimal("0.04") * (10000 * price_per_lb_cents))
    high = rhu(Decimal("0.07") * ((pounds - 10000) * price_per_lb_cents))
    return FLAT_FEE_CENTS + mid + high


# ---------------------------------------------------------------------------
# Compliance
# ---------------------------------------------------------------------------

def penalty_points(violation, vessel):
    base = BASE_POINTS[violation["violation_type"]]
    points = vessel["compliance_points"]
    if points >= 80:
        tier = Decimal("1.0")
    elif points >= 50:
        tier = Decimal("1.5")
    else:
        tier = Decimal("2.0")
    repeat = any(
        o["id"] != violation["id"]
        and o["vessel_id"] == vessel["id"]
        and o["violation_type"] == violation["violation_type"]
        and o["season_year"] == violation["season_year"]
        and o["status"] in ("ADJUDICATED", "UPHELD")
        for o in store.db.violations.values()
    )
    factor = Decimal("1.5") if repeat else Decimal("1.0")
    return rhu(Decimal(base) * tier * factor)


def create_violation(vessel_id, violation_type, details, trip_id=None):
    violation = {
        "vessel_id": vessel_id,
        "trip_id": trip_id,
        "violation_type": violation_type,
        "details": details,
        "season_year": store.db.clock.year,
        "severity_points": None,
        "status": "OPEN",
    }
    from common import make_entity

    entity = make_entity(violation)
    store.db.violations[entity["id"]] = entity
    return entity


def vms_gap_check(vessel, trip):
    if not vessel.get("vms_unit_id"):
        return
    departure = parse_dt(trip["actual_departure_utc"])
    returned = parse_dt(trip["actual_return_utc"])
    pings = [
        p
        for p in store.db.vms_pings.values()
        if p["vessel_id"] == vessel["id"]
        and departure <= parse_dt(p["recorded_at"]) <= returned
    ]
    pings.sort(key=lambda p: (parse_dt(p["recorded_at"]), p["created_at"], p["_seq"]))
    points = [departure] + [parse_dt(p["recorded_at"]) for p in pings] + [returned]
    longest = None
    for earlier, later in zip(points, points[1:]):
        gap = later - earlier
        if longest is None or gap > longest:
            longest = gap
    if longest is not None and longest.total_seconds() > VMS_MAX_GAP_MINUTES * 60:
        minutes = longest.total_seconds() / 60.0
        details = (
            f"VMS gap detected: longest gap {minutes:g} minutes exceeded the "
            f"{VMS_MAX_GAP_MINUTES}-minute limit during the trip window"
        )
        create_violation(vessel["id"], "VMS_GAP", details, trip_id=trip["id"])


# ---------------------------------------------------------------------------
# Gear projection
# ---------------------------------------------------------------------------

def replay_gear_events(asset, events):
    """Replay events in occurred_at/created_at order; raise on illegal events."""
    lost = 0
    in_maintenance = 0
    ordered = sorted(
        events,
        key=lambda e: (parse_dt(e["occurred_at"]), e["created_at"], e["_seq"]),
    )
    for ev in ordered:
        units = ev["units"]
        kind = ev["event_type"]
        if kind == "LOSS":
            lost += units
        elif kind == "REPAIR":
            lost = max(0, lost - units)
        elif kind == "MAINTENANCE_START":
            operational = asset["units_total"] - lost - in_maintenance
            if operational < units:
                raise ApiError(
                    422,
                    "ERR_INVALID_GEAR_EVENT",
                    "MAINTENANCE_START exceeds units_operational",
                )
            in_maintenance += units
        elif kind == "MAINTENANCE_END":
            if in_maintenance < units:
                raise ApiError(
                    422,
                    "ERR_INVALID_GEAR_EVENT",
                    "MAINTENANCE_END exceeds units_in_maintenance",
                )
            in_maintenance -= units
    return lost, in_maintenance


def apply_gear_projection(asset):
    events = [e for e in store.db.gear_events.values() if e["gear_asset_id"] == asset["id"]]
    lost, in_maintenance = replay_gear_events(asset, events)
    asset["units_lost"] = lost
    asset["units_in_maintenance"] = in_maintenance
    asset["units_operational"] = asset["units_total"] - lost - in_maintenance
    asset["status"] = "OPERATIONAL" if asset["units_operational"] > 0 else "DOWN"
    touch(asset)


def check_gear_event_legal(asset, new_event):
    events = [e for e in store.db.gear_events.values() if e["gear_asset_id"] == asset["id"]]
    replay_gear_events(asset, events + [new_event])
