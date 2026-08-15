"""The five calculation rules from SCAFFOLD §1.3 / PRD §3.

1. booking_fare_quote — tiered pricing, peak multiplier on vehicle component only.
2. vehicle_deck_allocation — waterfall split pinned at open.
3. standby_clearance_count — chronological priority sweep at begin-boarding.
4. crew_manning_compliance — Coast Guard manning table + passenger escalator.
5. fuel_surcharge_determination — threshold tiers pinned at submission.
"""

from decimal import Decimal, ROUND_HALF_UP
import math

from db import db

OVERSIZE_LENGTH_THRESHOLD_FEET = 22
PEAK_RESERVED_RATIO = Decimal("0.70")
OFF_PEAK_RESERVED_RATIO = Decimal("0.60")
STANDBY_FLOOR_FEET = 40
RESERVED_FLOOR_FEET = 20
PASSENGER_ESCALATOR_THRESHOLD = 500

# Fuel surcharge tiers
TIER1_LOW_CENTS = 300
TIER2_LOW_CENTS = 500
TIER1_SURCHARGE_CENTS = 100
TIER2_SURCHARGE_CENTS = 250

# Booking statuses that hold capacity (PRD §2.7)
HOLDING_BOOKING_STATUSES = ("RESERVED", "CONFIRMED", "MODIFIED", "CHECKED_IN", "BOARDED")


# ---------------------------------------------------------------------------
# Calculation 5: fuel_surcharge_determination (threshold)
# ---------------------------------------------------------------------------
def fuel_surcharge_for_index(fuel_price_index_cents):
    """index < 300 -> 0; 300 <= index < 500 -> 100; index >= 500 -> 250.
    Boundaries: exactly 300 -> 100; exactly 500 -> 250 (>= semantics)."""
    idx = int(fuel_price_index_cents)
    if idx >= TIER2_LOW_CENTS:
        return TIER2_SURCHARGE_CENTS
    if idx >= TIER1_LOW_CENTS:
        return TIER1_SURCHARGE_CENTS
    return 0


# ---------------------------------------------------------------------------
# Calculation 1: booking_fare_quote (tiered_pricing)
# ---------------------------------------------------------------------------
def booking_fare_quote(fare_schedule, fare_class, passenger_count, has_vehicle,
                       vehicle_length_feet, season):
    """Per-component assembly in pinned order; peak multiplier on vehicle only.

    Returns integer cents.
    """
    # Step 1 — passenger component
    if fare_class == "STANDARD":
        passenger_rate = int(fare_schedule["passenger_standard_cents"])
    elif fare_class == "RESIDENT":
        passenger_rate = int(fare_schedule["passenger_resident_cents"])
    else:  # COMMUTER
        passenger_rate = int(fare_schedule["passenger_commuter_cents"])
    passenger_component = int(passenger_count) * passenger_rate

    # Step 2 — vehicle component (0 when no vehicle)
    vehicle_component = 0
    if has_vehicle:
        length = int(vehicle_length_feet)
        if length < OVERSIZE_LENGTH_THRESHOLD_FEET:
            vehicle_component = int(fare_schedule["vehicle_standard_base_cents"])
        else:
            vehicle_component = (
                int(fare_schedule["vehicle_oversize_base_cents"])
                + (length - (OVERSIZE_LENGTH_THRESHOLD_FEET - 1))
                * int(fare_schedule["vehicle_overlength_per_foot_cents"])
            )
        # peak_load_variant: multiplier 1.25 on the FULLY COMPUTED vehicle
        # component, rounded half-up once, before adding other components.
        if season == "PEAK":
            mult = (Decimal(vehicle_component) * Decimal("1.25")).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP)
            vehicle_component = int(mult)

    # Step 3 — fuel surcharge per FARE COMPONENT PRESENT
    surcharge_component = int(fare_schedule["fuel_surcharge_cents"]) * (
        (1 if int(passenger_count) > 0 else 0) + (1 if has_vehicle else 0)
    )

    # Step 4 — total
    return passenger_component + vehicle_component + surcharge_component


# ---------------------------------------------------------------------------
# Calculation 2: vehicle_deck_allocation (waterfall_allocation)
# ---------------------------------------------------------------------------
def vehicle_deck_allocation(deck_feet, season=None, ratio=None):
    """Compute (reserved_deck_allotment_feet, standby_pool_feet).

    ratio = 0.70 PEAK / 0.60 OFF_PEAK unless a caller-supplied ratio is given
    (dynamic_ratio_variant for the deck-projection endpoint).
    raw_reserved = floor(D * ratio)
    reserved = max(20, min(raw_reserved, D - 40))
    standby  = D - reserved
    Invariant: reserved + standby == D.
    """
    D = int(deck_feet)
    if ratio is None:
        r = PEAK_RESERVED_RATIO if season == "PEAK" else OFF_PEAK_RESERVED_RATIO
    else:
        r = Decimal(str(ratio))
    raw_reserved = math.floor(Decimal(D) * r)
    reserved = max(RESERVED_FLOOR_FEET, min(raw_reserved, D - STANDBY_FLOOR_FEET))
    standby = D - reserved
    return reserved, standby


# ---------------------------------------------------------------------------
# Sailing computed counters (PRD §2.7)
# ---------------------------------------------------------------------------
def recompute_sailing_counters(sailing):
    """Recompute reserved_vehicle_feet, standby_cleared_feet, booked_passengers,
    manning_ok from live child state. Bumps sailing version/updated_at — the
    caller decides whether this is a mutation of the sailing itself."""
    sid = sailing["id"]
    reserved_feet = 0
    booked_pax = 0
    for b in db.bookings.values():
        if b["sailing_id"] != sid:
            continue
        if b["status"] in HOLDING_BOOKING_STATUSES:
            if b.get("has_vehicle"):
                reserved_feet += int(b.get("vehicle_length_feet") or 0)
            booked_pax += int(b["passenger_count"])
    cleared_feet = 0
    for e in db.standby_entries.values():
        if e["sailing_id"] != sid:
            continue
        if e["status"] == "CLEARED":
            if e.get("has_vehicle"):
                cleared_feet += int(e.get("vehicle_length_feet") or 0)
            booked_pax += int(e["passenger_count"])
    sailing["reserved_vehicle_feet"] = reserved_feet
    sailing["standby_cleared_feet"] = cleared_feet
    sailing["booked_passengers"] = booked_pax
    sailing["manning_ok"] = crew_manning_compliance(sailing)


# ---------------------------------------------------------------------------
# Calculation 4: crew_manning_compliance (threshold)
# ---------------------------------------------------------------------------
def crew_manning_compliance(sailing):
    """True iff the ASSIGNED crew meets the manning table for the vessel class,
    plus the passenger-load escalator (booked_passengers strictly > 500 -> +1 DECK).
    """
    vessel = db.vessels.get(sailing["vessel_id"])
    if vessel is None:
        return False
    counts = {"CAPTAIN": 0, "DECK": 0, "ENGINE": 0}
    for a in db.crew_assignments.values():
        if a["sailing_id"] != sailing["id"] or a["status"] != "ASSIGNED":
            continue
        member = db.crew_members.get(a["crew_member_id"])
        if member is None:
            continue
        counts[member["credential_class"]] = counts.get(member["credential_class"], 0) + 1

    crew_class = vessel["crew_class"]
    if crew_class == "SMALL":
        req = {"CAPTAIN": 1, "DECK": 1, "ENGINE": 0}
    elif crew_class == "MEDIUM":
        req = {"CAPTAIN": 1, "DECK": 2, "ENGINE": 1}
    else:  # LARGE
        req = {"CAPTAIN": 1, "DECK": 3, "ENGINE": 2}

    # Passenger-load escalator: strictly greater than 500; exactly 500 does NOT trigger.
    if int(sailing.get("booked_passengers", 0)) > PASSENGER_ESCALATOR_THRESHOLD:
        req["DECK"] += 1

    return (counts.get("CAPTAIN", 0) >= req["CAPTAIN"]
            and counts.get("DECK", 0) >= req["DECK"]
            and counts.get("ENGINE", 0) >= req["ENGINE"])


# ---------------------------------------------------------------------------
# Calculation 3: standby_clearance_count (chronological sweep)
# ---------------------------------------------------------------------------
def standby_clearance_sweep(sailing):
    """Single sweep at BOOKING_CLOSED -> BOARDING.

    Candidates: WAITING entries, ranked by priority band (MEDICAL < COMMUTER <
    STANDARD in sort order, MEDICAL highest), then queued_at ASC. Clear iff
    needed feet <= remaining standby pool AND passenger_count <= remaining pax
    capacity. Skip-over allowed. Boundary: needed_feet == remaining clears (<=).
    """
    vessel = db.vessels[sailing["vessel_id"]]
    D = int(vessel["vehicle_deck_linear_feet"])
    standby_pool = D - int(sailing["reserved_deck_allotment_feet"])

    band_order = {"MEDICAL": 0, "COMMUTER": 1, "STANDARD": 2}
    candidates = [e for e in db.standby_entries.values()
                  if e["sailing_id"] == sailing["id"] and e["status"] == "WAITING"]
    candidates.sort(key=lambda e: (band_order[e["priority_class"]], e["queued_at"]))

    running_cleared_feet = int(sailing.get("standby_cleared_feet", 0))
    running_pax = int(sailing.get("booked_passengers", 0))

    for entry in candidates:
        needed_feet = int(entry["vehicle_length_feet"]) if entry.get("has_vehicle") else 0
        remaining_standby = standby_pool - running_cleared_feet
        remaining_pax = int(vessel["passenger_capacity"]) - running_pax
        if needed_feet <= remaining_standby and int(entry["passenger_count"]) <= remaining_pax:
            entry["status"] = "CLEARED"  # WAITING -> CALLED -> CLEARED within the sweep
            touch(entry)
            running_cleared_feet += needed_feet
            running_pax += int(entry["passenger_count"])
        # else: stays WAITING; skip-over allowed, continue.

    sailing["standby_cleared_feet"] = running_cleared_feet
    sailing["booked_passengers"] = running_pax
    sailing["manning_ok"] = crew_manning_compliance(sailing)


def touch(entity):
    """Refresh updated_at and bump version on a mutation (PRD §2.5)."""
    from db import now_iso
    entity["updated_at"] = now_iso()
    entity["version"] = int(entity.get("version", 1)) + 1
