"""Business logic: calculations, cascades, sweeps, shared lookups.

Implements SCAFFOLD.yaml section 1.3 (calculations) and the state-machine
side effects from section 1.2, with PRD.md prose as the tie-breaker.
All money is integer cents; every pinned rounding step is round-half-up.
"""

from datetime import timedelta
from decimal import Decimal

from httpkit import err_not_found
from store import db
from util import D, new_uuid, round_money

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD section 1.3)
# ---------------------------------------------------------------------------

CATEGORIES = ["TURBOPROP", "LIGHT_JET", "MIDSIZE_JET", "HEAVY_JET"]

CATEGORY_RATE_CENTS_PER_HOUR = {
    "TURBOPROP": 150000,
    "LIGHT_JET": 250000,
    "MIDSIZE_JET": 400000,
    "HEAVY_JET": 650000,
}

POSITIONING_RATE_FACTOR = Decimal("0.6")
DISCOUNT_TIER1_THRESHOLD_CENTS = 2000000
DISCOUNT_TIER1_PCT = Decimal("0.05")
DISCOUNT_TIER2_THRESHOLD_CENTS = 5000000
DISCOUNT_TIER2_PCT = Decimal("0.10")
FUEL_SURCHARGE_PCT = Decimal("0.08")
FUEL_STOP_FEE_CENTS = 15000
INTL_FEE_CENTS = 250000
DEPOSIT_PCT = Decimal("0.25")
QUOTE_VALIDITY_HOURS = 48

MIN_BILLED_REVENUE_LEG_MINUTES = 60

TIER_FULL_REFUND_HOURS = 72
TIER_HALF_REFUND_HOURS = 24
FEE_PCT_TIER1 = Decimal("0.10")
FEE_PCT_TIER2 = Decimal("0.50")
FEE_PCT_TIER3 = Decimal("1.00")

DUTY_MAX_MINUTES = 840
REST_MIN_MINUTES = 600
REPORT_DEBRIEF_MINUTES = 60
REPORT_MINUTES = 30
DEBRIEF_MINUTES = 30

TURMAROUND_BUFFER_MINUTES = 45
INSPECTION_100H_INTERVAL_MINUTES = 6000

TSA_VALIDITY_HOURS = 72
PERMIT_VALIDITY_DAYS = 30

AIRCRAFT_STATUSES = ["AVAILABLE", "IN_TRIP", "MAINTENANCE_HOLD", "GROUNDED"]
TRIP_STATUSES = ["QUOTE_DRAFT", "QUOTED", "BOOKED", "DISPATCHED",
                 "COMPLETED", "CANCELLED", "EXPIRED"]
ASSIGNMENT_STATUSES = ["TENTATIVE", "CONFIRMED", "RELEASED"]
CREW_ASSIGNMENT_STATUSES = ["PROPOSED", "VETTED", "FLAGGED_ILLEGAL", "RELEASED"]


# ---------------------------------------------------------------------------
# Generic resource helpers
# ---------------------------------------------------------------------------

def touch(resource):
    """Mutation bookkeeping: refresh updated_at and increment version by 1."""
    resource["updated_at"] = db.now()
    resource["version"] += 1


def new_common():
    ts = db.now()
    return {
        "id": new_uuid(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def new_ledger():
    """Payment / FlightLog / WeatherAdvisory carry only id + created_at."""
    return {
        "id": new_uuid(),
        "created_at": db.now(),
        "_seq": db.next_seq(),
    }


# ---------------------------------------------------------------------------
# Lookup helpers (priority-5 existence, resource-specific 404s)
# ---------------------------------------------------------------------------

def get_owner_or_404(owner_id):
    o = db.owners.get(owner_id)
    if o is None:
        raise err_not_found("AIRCRAFT_OWNER", f"AircraftOwner {owner_id} does not exist")
    return o


def get_aircraft_or_404(aircraft_id):
    a = db.aircraft.get(aircraft_id)
    if a is None:
        raise err_not_found("AIRCRAFT", f"Aircraft {aircraft_id} does not exist")
    return a


def get_crew_member_or_404(crew_member_id):
    c = db.crew_members.get(crew_member_id)
    if c is None:
        raise err_not_found("CREW_MEMBER", f"CrewMember {crew_member_id} does not exist")
    return c


def get_trip_or_404(trip_id):
    t = db.trips.get(trip_id)
    if t is None:
        raise err_not_found("TRIP_REQUEST", f"TripRequest {trip_id} does not exist")
    return t


def get_leg_or_404(leg_id):
    lg = db.quote_legs.get(leg_id)
    if lg is None:
        raise err_not_found("QUOTE_LEG", f"QuoteLeg {leg_id} does not exist")
    return lg


def get_assignment_or_404(assignment_id):
    a = db.aircraft_assignments.get(assignment_id)
    if a is None:
        raise err_not_found("AIRCRAFT_ASSIGNMENT",
                            f"AircraftAssignment {assignment_id} does not exist")
    return a


def get_crew_assignment_or_404(crew_assignment_id):
    c = db.crew_assignments.get(crew_assignment_id)
    if c is None:
        raise err_not_found("CREW_ASSIGNMENT",
                            f"CrewAssignment {crew_assignment_id} does not exist")
    return c


def get_window_or_404(window_id):
    w = db.maintenance_windows.get(window_id)
    if w is None:
        raise err_not_found("MAINTENANCE_WINDOW",
                            f"MaintenanceWindow {window_id} does not exist")
    return w


def get_passenger_or_404(passenger_id):
    p = db.passengers.get(passenger_id)
    if p is None:
        raise err_not_found("PASSENGER", f"Passenger {passenger_id} does not exist")
    return p


def get_permit_or_404(permit_id):
    p = db.permits.get(permit_id)
    if p is None:
        raise err_not_found("OVERFLIGHT_PERMIT",
                            f"OverflightPermit {permit_id} does not exist")
    return p


def get_flight_log_or_404(flight_log_id):
    fl = db.flight_logs.get(flight_log_id)
    if fl is None:
        raise err_not_found("FLIGHT_LOG", f"FlightLog {flight_log_id} does not exist")
    return fl


def get_statement_or_404(statement_id):
    s = db.statements.get(statement_id)
    if s is None:
        raise err_not_found("OWNER_STATEMENT",
                            f"OwnerStatement {statement_id} does not exist")
    return s


def get_finding_or_404(finding_id):
    f = db.findings.get(finding_id)
    if f is None:
        raise err_not_found("COMPLIANCE_FINDING",
                            f"ComplianceFinding {finding_id} does not exist")
    return f


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------

def trip_legs(trip_id):
    """All QuoteLegs of a trip in seq_no ascending order (calculation order)."""
    legs = [lg for lg in db.quote_legs.values() if lg["trip_request_id"] == trip_id]
    legs.sort(key=lambda lg: (lg["seq_no"], lg["_seq"]))
    return legs


def planned_block_minutes(trip_id):
    return sum(lg["block_minutes"] for lg in trip_legs(trip_id))


def trip_aircraft_assignments(trip_id):
    return [a for a in db.aircraft_assignments.values()
            if a["trip_request_id"] == trip_id]


def trip_crew_assignments(trip_id):
    return [c for c in db.crew_assignments.values()
            if c["trip_request_id"] == trip_id]


def trip_passengers(trip_id):
    return [p for p in db.passengers.values() if p["trip_request_id"] == trip_id]


def trip_permits(trip_id):
    return [p for p in db.permits.values() if p["trip_request_id"] == trip_id]


def trip_payments(trip_id):
    return [p for p in db.payments.values() if p["trip_request_id"] == trip_id]


def trip_flight_logs(trip_id):
    return [f for f in db.flight_logs.values() if f["trip_request_id"] == trip_id]


def confirmed_assignment_for(trip_id):
    """The trip's unique CONFIRMED assignment, or None."""
    confirmed = [a for a in trip_aircraft_assignments(trip_id)
                 if a["status"] == "CONFIRMED"]
    return confirmed[0] if len(confirmed) == 1 else None


def has_active_window(aircraft_id):
    return any(w["aircraft_id"] == aircraft_id and w["status"] == "ACTIVE"
               for w in db.maintenance_windows.values())


def has_open_grounding_finding(aircraft_id):
    return any(f["subject_type"] == "AIRCRAFT" and f["subject_id"] == aircraft_id
               and f["grounding"] and f["status"] == "OPEN"
               for f in db.findings.values())


# ---------------------------------------------------------------------------
# Occupancy windows (PRD section 2.8)
# ---------------------------------------------------------------------------

def compute_occupied_window(trip):
    """Buffered, half-open occupancy interval for an assignment on this trip."""
    start = trip["departure_at"] - timedelta(minutes=TURMAROUND_BUFFER_MINUTES)
    end = (trip["departure_at"] + timedelta(minutes=planned_block_minutes(trip["id"]))
           + timedelta(minutes=TURMAROUND_BUFFER_MINUTES))
    return start, end


def raw_flight_interval(trip):
    """Closed flight interval: departure_at .. departure_at + planned block."""
    return (trip["departure_at"],
            trip["departure_at"] + timedelta(minutes=planned_block_minutes(trip["id"])))


def half_open_intersects(s1, e1, s2, e2):
    """[s1, e1) vs [s2, e2): touching endpoints do NOT count."""
    return s1 < e2 and s2 < e1


def closed_intersects(s1, e1, s2, e2):
    """[s1, e1] vs [s2, e2]: touching endpoints DO count as intersection."""
    return s1 <= e2 and s2 <= e1


# ---------------------------------------------------------------------------
# Calculations (SCAFFOLD section 1.3)
# ---------------------------------------------------------------------------

def run_quote_price(trip):
    """quote_price: category rate card on planned minutes, per-leg rounding,
    then volume-discount tier, then fuel surcharge on the discounted amount."""
    rate = CATEGORY_RATE_CENTS_PER_HOUR[trip["requested_category"]]
    legs_total = 0
    fuel_stop_count = 0
    for lg in trip_legs(trip["id"]):
        base = D(lg["block_minutes"] * rate) / D(60)
        if lg["leg_type"] == "POSITIONING":
            base = base * POSITIONING_RATE_FACTOR
        legs_total += round_money(base)
        if lg["fuel_stop"]:
            fuel_stop_count += 1

    if legs_total >= DISCOUNT_TIER2_THRESHOLD_CENTS:
        volume_discount = round_money(D(legs_total) * DISCOUNT_TIER2_PCT)
    elif legs_total >= DISCOUNT_TIER1_THRESHOLD_CENTS:
        volume_discount = round_money(D(legs_total) * DISCOUNT_TIER1_PCT)
    else:
        volume_discount = 0

    fuel_surcharge = round_money(D(legs_total - volume_discount) * FUEL_SURCHARGE_PCT)
    stop_fees = FUEL_STOP_FEE_CENTS * fuel_stop_count
    intl_fee = INTL_FEE_CENTS if trip["international"] else 0
    quoted_total = legs_total - volume_discount + fuel_surcharge + stop_fees + intl_fee
    deposit_required = round_money(D(quoted_total) * DEPOSIT_PCT)
    return quoted_total, deposit_required


def run_final_price(trip, aircraft):
    """final_price: the confirmed tail's hourly rate on logged actuals.
    No volume discount, no fuel surcharge; 60-minute minimum on revenue legs;
    positioning legs bill planned minutes regardless of actuals."""
    logs_by_leg = {f["quote_leg_id"]: f for f in trip_flight_logs(trip["id"])}
    rate = aircraft["hourly_rate_cents"]
    legs_total = 0
    fuel_stop_count = 0
    for lg in trip_legs(trip["id"]):
        if lg["leg_type"] == "REVENUE":
            log = logs_by_leg[lg["id"]]
            billed = max(log["actual_block_minutes"], MIN_BILLED_REVENUE_LEG_MINUTES)
            legs_total += round_money(D(billed * rate) / D(60))
        else:  # POSITIONING bills planned minutes
            billed = lg["block_minutes"]
            legs_total += round_money(D(billed * rate) * POSITIONING_RATE_FACTOR / D(60))
        if lg["fuel_stop"]:
            fuel_stop_count += 1
    stop_fees = FUEL_STOP_FEE_CENTS * fuel_stop_count
    intl_fee = INTL_FEE_CENTS if trip["international"] else 0
    return legs_total + stop_fees + intl_fee


def compute_collected_cents(trip_id):
    gross = sum(p["amount_cents"] for p in trip_payments(trip_id)
                if p["payment_type"] in ("DEPOSIT", "BALANCE"))
    refunds = sum(p["amount_cents"] for p in trip_payments(trip_id)
                  if p["payment_type"] == "REFUND")
    return gross - refunds


def recompute_payment_posture(trip):
    """payment_posture is derived solely from POSTED payment rows."""
    net = compute_collected_cents(trip["id"])
    trip["collected_cents"] = net
    if trip["status"] == "CANCELLED":
        refund = trip["refund_cents"] or 0
        fee = trip["cancellation_fee_cents"] or 0
        if refund > 0 and fee == 0:
            trip["payment_posture"] = "REFUNDED_FULL"
        elif refund > 0 and fee > 0:
            trip["payment_posture"] = "REFUNDED_PARTIAL"
        # refund == 0: posture unchanged from its pre-cancel value
        return
    quoted = trip["quoted_total_cents"]
    if net == 0:
        trip["payment_posture"] = "UNPAID"
    elif quoted is not None and net < quoted:
        trip["payment_posture"] = "DEPOSIT_PAID"
    elif quoted is not None and net >= quoted:
        trip["payment_posture"] = "PAID_IN_FULL"
    else:
        trip["payment_posture"] = "UNPAID"


def create_payment(trip_id, payment_type, amount_cents):
    p = new_ledger()
    p.update({
        "trip_request_id": trip_id,
        "payment_type": payment_type,
        "amount_cents": amount_cents,
        "status": "POSTED",
    })
    db.payments[p["id"]] = p
    return p


def duty_interval(trip):
    """[departure_at - 30min report, departure_at + block + 30min debrief]."""
    start = trip["departure_at"] - timedelta(minutes=REPORT_MINUTES)
    end = (trip["departure_at"] + timedelta(minutes=planned_block_minutes(trip["id"]))
           + timedelta(minutes=DEBRIEF_MINUTES))
    return start, end


def run_crew_duty_legality(crew_assignment):
    """crew_duty_legality: duty cap 840 min (inclusive); rest gap to every
    other VETTED assignment of the same member >= 600 min on both sides."""
    trip = db.trips[crew_assignment["trip_request_id"]]
    planned = planned_block_minutes(trip["id"]) + REPORT_DEBRIEF_MINUTES
    duty_legal = planned <= DUTY_MAX_MINUTES

    my_start, my_end = duty_interval(trip)
    rest_legal = True
    for other in db.crew_assignments.values():
        if other["id"] == crew_assignment["id"]:
            continue
        if other["crew_member_id"] != crew_assignment["crew_member_id"]:
            continue
        if other["status"] != "VETTED":
            continue
        other_trip = db.trips.get(other["trip_request_id"])
        if other_trip is None:
            continue
        o_start, o_end = duty_interval(other_trip)
        if my_start >= o_end:
            gap = (my_start - o_end).total_seconds() / 60.0
        elif o_start >= my_end:
            gap = (o_start - my_end).total_seconds() / 60.0
        else:
            gap = 0.0  # overlapping intervals violate rest
        if gap < REST_MIN_MINUTES:
            rest_legal = False
            break
    return planned, duty_legal, rest_legal


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def reset_crew_vetting(trip_id):
    """Itinerary changed (leg add/delete, requote): VETTED and FLAGGED_ILLEGAL
    crew assignments fall back to PROPOSED with computed fields cleared."""
    for c in trip_crew_assignments(trip_id):
        if c["status"] in ("VETTED", "FLAGGED_ILLEGAL"):
            c["status"] = "PROPOSED"
            c["duty_legal"] = None
            c["rest_legal"] = None
            c["vetted_at"] = None
            touch(c)


def release_trip_crew(trip_id):
    """Trip cancelled or completed: all non-RELEASED crew assignments release."""
    for c in trip_crew_assignments(trip_id):
        if c["status"] in ("PROPOSED", "VETTED", "FLAGGED_ILLEGAL"):
            c["status"] = "RELEASED"
            touch(c)


def release_assignment(assignment):
    assignment["status"] = "RELEASED"
    touch(assignment)


def resolve_aircraft_after_trip(aircraft):
    """Aircraft leaves IN_TRIP after its final leg is logged (or its confirmed
    trip is cancelled post-dispatch): MAINTENANCE_HOLD when the inspection
    horizon is reached or an ACTIVE window exists, else AVAILABLE. Entering
    MAINTENANCE_HOLD releases every TENTATIVE assignment on the tail."""
    if aircraft["total_airframe_minutes"] >= aircraft["next_check_due_minutes"] \
            or has_active_window(aircraft["id"]):
        aircraft["status"] = "MAINTENANCE_HOLD"
        touch(aircraft)
        for a in db.aircraft_assignments.values():
            if a["aircraft_id"] == aircraft["id"] and a["status"] == "TENTATIVE":
                release_assignment(a)
    else:
        aircraft["status"] = "AVAILABLE"
        touch(aircraft)


def run_owner_statement(trip, aircraft):
    """owner_statement: pinned order gross -> standard share -> guarantee floor
    -> owner share (max) -> operator retained (residual, may go negative)."""
    owner = db.owners[aircraft["owner_id"]]
    gross = trip["final_total_cents"]
    standard_share = round_money(D(gross) * D(str(owner["revenue_share_pct"])) / D(100))
    logged_minutes = sum(f["actual_block_minutes"] for f in trip_flight_logs(trip["id"]))
    guarantee_floor = owner["guarantee_cents_per_block_min"] * logged_minutes
    owner_share = max(standard_share, guarantee_floor)
    s = new_common()
    s.update({
        "owner_id": owner["id"],
        "trip_request_id": trip["id"],
        "gross_cents": gross,
        "standard_share_cents": standard_share,
        "guarantee_floor_cents": guarantee_floor,
        "owner_share_cents": owner_share,
        "operator_retained_cents": gross - owner_share,
        "status": "DRAFT",
        "issued_at": None,
    })
    db.statements[s["id"]] = s
    return s


def complete_trip(trip):
    """DISPATCHED -> COMPLETED once every QuoteLeg has exactly one FlightLog."""
    assignment = confirmed_assignment_for(trip["id"])
    aircraft = db.aircraft[assignment["aircraft_id"]] if assignment else None

    if aircraft is not None:
        trip["final_total_cents"] = run_final_price(trip, aircraft)
    trip["status"] = "COMPLETED"
    touch(trip)

    if aircraft is not None:
        resolve_aircraft_after_trip(aircraft)
        run_owner_statement(trip, aircraft)

    release_trip_crew(trip["id"])


# ---------------------------------------------------------------------------
# Time-based expiry sweep (pinned order: trips -> passengers -> permits ->
# maintenance windows), run on every logical-clock set
# ---------------------------------------------------------------------------

def run_expiry_sweep():
    now = db.now()

    for t in list(db.trips.values()):
        if t["status"] == "QUOTED" and t["quote_valid_until"] is not None \
                and now > t["quote_valid_until"]:
            t["status"] = "EXPIRED"
            touch(t)

    for p in list(db.passengers.values()):
        if p["tsa_status"] == "CLEARED" and p["screened_at"] is not None \
                and now > p["screened_at"] + timedelta(hours=TSA_VALIDITY_HOURS):
            p["tsa_status"] = "EXPIRED"
            touch(p)

    for p in list(db.permits.values()):
        if p["status"] == "GRANTED" and p["decided_at"] is not None \
                and now > p["decided_at"] + timedelta(days=PERMIT_VALIDITY_DAYS):
            p["status"] = "EXPIRED"
            touch(p)

    for w in list(db.maintenance_windows.values()):
        if w["status"] != "PLANNED" or w["starts_at"] > now:
            continue
        aircraft = db.aircraft.get(w["aircraft_id"])
        if aircraft is None or aircraft["status"] == "IN_TRIP":
            # Activation is skipped while the tail is flying; re-evaluated on
            # the next clock set.
            continue
        w["status"] = "ACTIVE"
        touch(w)
        if aircraft["status"] == "AVAILABLE":
            aircraft["status"] = "MAINTENANCE_HOLD"
            touch(aircraft)
