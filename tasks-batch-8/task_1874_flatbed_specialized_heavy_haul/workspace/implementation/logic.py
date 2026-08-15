"""Business logic: constants, calculations (SCAFFOLD 1.3), the readiness
gate, and cascades. All arithmetic is integer cents; divisions round
half-up via Decimal at the pinned rounding points."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from store import store, bump, new_entity

# --- Constants (PRD 2.5, SCAFFOLD calculations.constants) -------------------

TRAILER_CATALOG = {
    "FLATBED": {"max_payload_lbs": 48000, "deck_height_in": 60, "cost_per_mile_cents": 350},
    "STEP_DECK": {"max_payload_lbs": 46000, "deck_height_in": 42, "cost_per_mile_cents": 400},
    "RGN_LOWBOY": {"max_payload_lbs": 90000, "deck_height_in": 24, "cost_per_mile_cents": 550},
    "EXTENDABLE_DOUBLE_DROP": {"max_payload_lbs": 150000, "deck_height_in": 22, "cost_per_mile_cents": 700},
}

STATE_BASE_CENTS = {
    "CA": {"OVERSIZE": 9000, "OVERWEIGHT": 15000, "SUPERLOAD": 50000},
    "NV": {"OVERSIZE": 7000, "OVERWEIGHT": 12000, "SUPERLOAD": 40000},
    "AZ": {"OVERSIZE": 8000, "OVERWEIGHT": 13000, "SUPERLOAD": 45000},
    "TX": {"OVERSIZE": 10000, "OVERWEIGHT": 16000, "SUPERLOAD": 55000},
    "OR": {"OVERSIZE": 8500, "OVERWEIGHT": 14000, "SUPERLOAD": 48000},
}

STATES = ("CA", "NV", "AZ", "TX", "OR")
PERMIT_TYPES = ("OVERSIZE", "OVERWEIGHT", "SUPERLOAD")
SECUREMENT_METHODS = ("CHAINS", "STRAPS", "CHAINS_AND_TARPS")
ESCORT_POSITIONS = ("FRONT", "REAR", "POLE_FRONT")
CRANE_SITES = ("ORIGIN", "DESTINATION")
DELAY_KINDS = ("CUSTOMER_DELAY", "CARRIER_DELAY", "WEATHER")
FINE_KINDS = ("OVERWEIGHT", "DAMAGE", "PERMIT_VIOLATION")

LEGAL_GROSS_LBS = 80000
SUPERLOAD_WEIGHT_LBS = 150000
SUPERLOAD_WIDTH_IN = 192
LEGAL_WIDTH_IN = 102
LEGAL_HEIGHT_IN = 162
LEGAL_LENGTH_IN = 636
PER_AXLE_LIMIT_LBS = 20000
BRIDGE_SAFETY_MARGIN_IN = 6

ESCORT_WIDTH_TWO_IN = 168
ESCORT_WIDTH_ONE_IN = 144
POLE_HEIGHT_IN = 192

FREE_MINUTES = 120
PREMIUM_AFTER_BILLABLE_MINUTES = 360
STANDBY_RATE_CENTS_PER_HOUR = 17500
STANDBY_PREMIUM_CENTS_PER_HOUR = 26250

FUEL_TIER_THRESHOLD_CENTS = 5000000

CRANE_BUFFER_MINUTES = 45


def round_half_up_div(numer, denom):
    return int((Decimal(numer) / Decimal(denom)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- Load computed fields ----------------------------------------------------

def compute_flags(gross_weight_lbs, width_in, height_in, length_in):
    is_oversize = (width_in > LEGAL_WIDTH_IN or height_in > LEGAL_HEIGHT_IN
                   or length_in > LEGAL_LENGTH_IN)
    is_overweight = gross_weight_lbs > LEGAL_GROSS_LBS
    is_superload = (gross_weight_lbs > SUPERLOAD_WEIGHT_LBS
                    or width_in > SUPERLOAD_WIDTH_IN)
    return is_oversize, is_overweight, is_superload


def required_axles(gross_weight_lbs):
    return max(2, -(-gross_weight_lbs // PER_AXLE_LIMIT_LBS))


def escort_positions(width_in, overall_height_in):
    positions = []
    if width_in >= ESCORT_WIDTH_TWO_IN:
        positions += ["FRONT", "REAR"]
    elif width_in >= ESCORT_WIDTH_ONE_IN:
        positions += ["REAR"]
    if overall_height_in >= POLE_HEIGHT_IN:
        positions.append("POLE_FRONT")
    return positions


def survey_pass(overall_height_in, gross_weight_lbs, min_clearance_in, max_weight_lbs):
    return (overall_height_in + BRIDGE_SAFETY_MARGIN_IN <= min_clearance_in
            and gross_weight_lbs <= max_weight_lbs)


# --- Money calculations ------------------------------------------------------

def permit_fee_cents(state_code, permit_type, weight_basis_lbs, width_in):
    fee = STATE_BASE_CENTS[state_code][permit_type]
    if permit_type in ("OVERWEIGHT", "SUPERLOAD"):
        excess = max(0, weight_basis_lbs - LEGAL_GROSS_LBS)
        fee += (min(excess, 20000) * 1
                + min(max(0, excess - 20000), 30000) * 2
                + max(0, excess - 50000) * 4)
    if permit_type in ("OVERSIZE", "SUPERLOAD"):
        if width_in > 192:
            fee += 10000
        elif width_in > 168:
            fee += 5000
        elif width_in > 144:
            fee += 2500
    return fee


def latest_ticket_weight(load_id):
    """Latest ScaleTicket by creation order, or None."""
    tickets = [t for t in store.tickets.values() if t["load_id"] == load_id]
    if not tickets:
        return None
    return max(tickets, key=lambda t: t["_seq"])["measured_gross_lbs"]


def standby_cents(kind, duration_minutes):
    """Returns (billable_minutes, standby_amount_cents)."""
    if kind != "CUSTOMER_DELAY":
        return 0, 0
    billable = max(0, duration_minutes - FREE_MINUTES)
    tier1 = min(billable, PREMIUM_AFTER_BILLABLE_MINUTES)
    tier2 = max(0, billable - PREMIUM_AFTER_BILLABLE_MINUTES)
    amount = round_half_up_div(
        tier1 * STANDBY_RATE_CENTS_PER_HOUR + tier2 * STANDBY_PREMIUM_CENTS_PER_HOUR, 60)
    return billable, amount


def overweight_fine_cents(excess_lbs):
    return (min(excess_lbs, 2000) * 25
            + min(max(0, excess_lbs - 2000), 3000) * 50
            + max(0, excess_lbs - 5000) * 100)


def fuel_surcharge_cents(subtotal_cents):
    pct = Decimal("0.12") if subtotal_cents >= FUEL_TIER_THRESHOLD_CENTS else Decimal("0.08")
    return int((Decimal(subtotal_cents) * pct).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def escort_line_cents(booking):
    return round_half_up_div(booking["scheduled_minutes"] * booking["rate_per_hour_cents"], 60)


def compute_cost_estimate(load):
    """Provisional variant: permits in {FILED, GRANTED}, escorts CONFIRMED,
    standby and fines excluded."""
    linehaul = load["route_miles"] * TRAILER_CATALOG[load["trailer_type"]]["cost_per_mile_cents"]
    permits = sum(p["fee_cents"] for p in store.permits.values()
                  if p["load_id"] == load["id"] and p["status"] in ("FILED", "GRANTED"))
    escorts = sum(escort_line_cents(b) for b in store.escorts.values()
                  if b["load_id"] == load["id"] and b["status"] == "CONFIRMED")
    subtotal = linehaul + permits + escorts
    fuel = fuel_surcharge_cents(subtotal)
    return {
        "linehaul_cents": linehaul,
        "permits_cents": permits,
        "escorts_cents": escorts,
        "standby_cents": 0,
        "fines_cents": 0,
        "subtotal_cents": subtotal,
        "fuel_surcharge_cents": fuel,
        "total_cents": subtotal + fuel,
    }


# --- Permit requirement rules ------------------------------------------------

def permit_type_required(load, permit_type):
    if load["is_superload"]:
        return permit_type == "SUPERLOAD"
    if permit_type == "SUPERLOAD":
        return False
    if permit_type == "OVERSIZE":
        return bool(load["is_oversize"])
    if permit_type == "OVERWEIGHT":
        return bool(load["is_overweight"])
    return False


def required_permit_pairs(load):
    pairs = set()
    for state in (load["states_crossed"] or []):
        if load["is_superload"]:
            pairs.add((state, "SUPERLOAD"))
        else:
            if load["is_oversize"]:
                pairs.add((state, "OVERSIZE"))
            if load["is_overweight"]:
                pairs.add((state, "OVERWEIGHT"))
    return pairs


# --- Lookup helpers ----------------------------------------------------------

def permits_of(load_id):
    return [p for p in store.permits.values() if p["load_id"] == load_id]


def escorts_of(load_id):
    return [b for b in store.escorts.values() if b["load_id"] == load_id]


def cranes_of(load_id):
    return [c for c in store.cranes.values() if c["load_id"] == load_id]


# --- Lazy permit expiry + readiness gate (SURVEYED -> CLEARED) ---------------

def expire_overdue_permits(load, now):
    for p in permits_of(load["id"]):
        if (p["status"] == "GRANTED" and p.get("_twe_dt") is not None
                and now > p["_twe_dt"]):
            p["status"] = "EXPIRED"
            bump(p)


def readiness_gate(load):
    """Re-evaluated after permit grant, escort booking create, crane
    appointment create, securement approve, and release-hold. Strictly
    upward: only advances SURVEYED -> CLEARED, never demotes."""
    if load["status"] != "SURVEYED":
        return
    if load["survey_result"] != "PASSED":
        return
    expire_overdue_permits(load, store.clock_dt)
    for (state_code, permit_type) in required_permit_pairs(load):
        if not any(p["state_code"] == state_code and p["permit_type"] == permit_type
                   and p["status"] == "GRANTED" for p in permits_of(load["id"])):
            return
    for pos in (load["required_escort_positions"] or []):
        if not any(b["position"] == pos and b["status"] == "CONFIRMED"
                   for b in escorts_of(load["id"])):
            return
    if not any(c["site"] == "ORIGIN" and c["status"] == "SCHEDULED"
               for c in cranes_of(load["id"])):
        return
    if not any(c["site"] == "DESTINATION" and c["status"] == "SCHEDULED"
               for c in cranes_of(load["id"])):
        return
    if not any(sp["status"] == "APPROVED" for sp in store.securements.values()
               if sp["load_id"] == load["id"]):
        return
    load["status"] = "CLEARED"
    bump(load)


# --- Cascades ------------------------------------------------------------------

def load_cancel_cascade(load):
    for p in permits_of(load["id"]):
        if p["status"] in ("DRAFT", "FILED", "GRANTED", "DENIED", "REVOKED"):
            p["status"] = "WITHDRAWN"
            bump(p)
    for b in escorts_of(load["id"]):
        if b["status"] == "CONFIRMED":
            b["status"] = "CANCELLED"
            bump(b)
    for c in cranes_of(load["id"]):
        if c["status"] == "SCHEDULED":
            c["status"] = "CANCELLED"
            bump(c)
    load["status"] = "CANCELLED"
    bump(load)


def scale_violation_cascade(load, ticket):
    """One atomic step: OVERWEIGHT fine -> permit revocations -> load hold ->
    escort cancellations."""
    fine = new_entity()
    fine.update({
        "load_id": load["id"],
        "kind": "OVERWEIGHT",
        "amount_cents": overweight_fine_cents(ticket["excess_lbs"]),
        "description": (f"Overweight scale violation: measured "
                        f"{ticket['measured_gross_lbs']} lbs vs declared "
                        f"{load['gross_weight_lbs']} lbs"),
        "liable_party": "CUSTOMER",
        "status": "PENDING",
    })
    store.fines[fine["id"]] = fine
    for p in permits_of(load["id"]):
        if p["status"] == "GRANTED" and p["permit_type"] in ("OVERWEIGHT", "SUPERLOAD"):
            p["status"] = "REVOKED"
            bump(p)
    if load["status"] in ("CLEARED", "IN_TRANSIT"):
        load["status"] = "ON_HOLD"
        load["hold_reason"] = "SCALE_OVERWEIGHT"
        bump(load)
        for b in escorts_of(load["id"]):
            if b["status"] == "CONFIRMED":
                b["status"] = "CANCELLED"
                bump(b)


def whole_minutes(start_dt, end_dt):
    return int((end_dt - start_dt).total_seconds() // 60)


def crane_windows_overlap(s1, e1, s2, e2):
    buf = timedelta(minutes=CRANE_BUFFER_MINUTES)
    ns1, ne1 = s1 - buf, e1 + buf
    ns2, ne2 = s2 - buf, e2 + buf
    return ns1 < ne2 and ne1 > ns2
