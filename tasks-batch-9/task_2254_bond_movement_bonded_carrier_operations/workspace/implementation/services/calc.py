"""The ten normative calculations of SCAFFOLD 1.3 / PRD 2.5-2.6, 3.2, 3.6, 3.7."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

SECONDS_PER_DAY = 86400

# ---- transit_allowance_and_deadline --------------------------------------
BASE_TRANSIT_DAYS = {"IT": 30, "TE": 30, "IE": 15}
INTERPORT_LEG_DAYS = 5
MIN_TRANSIT_DAYS = 5
MAX_TRANSIT_DAYS = 60
SANCTION_THROTTLE_THRESHOLD = Decimal("6.0")
SANCTION_THROTTLE_FACTOR = Decimal("0.5")
EXTENSION_DAYS_MAX = 30
LATE_EXTENSION_GRACE_DAYS = 2

# ---- movement_bond_obligation -------------------------------------------
VALUE_RATE = Decimal("0.0325")
WEIGHT_RATE = Decimal("0.0125")
PACKAGE_RATE = Decimal("0.1275")
MIN_OBLIGATION = Decimal("25.00")

# ---- liquidated_damages_assessment --------------------------------------
LD_PER_DIEM = Decimal("250.00")
LD_MIN_CLAIM = Decimal("1000.00")
SEVERITY = {
    "LATE_ARRIVAL": Decimal("1.0"),
    "NO_PROOF_OF_EXPORT": Decimal("2.0"),
    "SEAL_VIOLATION": Decimal("3.0"),
    "UNAUTHORIZED_DIVERSION": Decimal("3.0"),
    "NON_ARRIVAL": Decimal("4.0"),
}

# ---- mitigation_offer_amount --------------------------------------------
CREDIT_ORDER = [
    "FIRST_VIOLATION",
    "CARGO_SECURED_INTACT",
    "PROMPT_ARRIVAL_REPORT",
    "CBP_ADMIN_DELAY",
    "EXTRAORDINARY_CIRCUMSTANCE",
]
CREDIT = {
    "FIRST_VIOLATION": Decimal("0.20"),
    "CARGO_SECURED_INTACT": Decimal("0.15"),
    "PROMPT_ARRIVAL_REPORT": Decimal("0.10"),
    "CBP_ADMIN_DELAY": Decimal("0.25"),
    "EXTRAORDINARY_CIRCUMSTANCE": Decimal("0.30"),
}
PRIOR_VIOLATION_DEBIT = Decimal("0.05")
CAP_FIRST = Decimal("0.50")
CAP_SUPPLEMENTAL = Decimal("0.75")
FEE_TIER1_CEILING = Decimal("2000.00")
FEE_TIER1_FLAT = Decimal("100.00")
FEE_TIER2_CEILING = Decimal("10000.00")
FEE_TIER2_FLAT = Decimal("250.00")
FEE_TIER3_RATE = Decimal("0.025")
MAX_PETITION_ROUNDS = 2
PARTIAL_GRANT_FACTOR = Decimal("0.5")

# ---- carrier_sanction_points --------------------------------------------
POINTS = {
    "LATE_ARRIVAL": Decimal("2"),
    "NO_PROOF_OF_EXPORT": Decimal("3"),
    "SEAL_VIOLATION": Decimal("4"),
    "UNAUTHORIZED_DIVERSION": Decimal("4"),
    "NON_ARRIVAL": Decimal("6"),
}
DECAY_FRESH = Decimal("1.0")
DECAY_RECENT = Decimal("0.75")
DECAY_STALE = Decimal("0.5")
DECAY_EXPIRED = Decimal("0.0")
SANCTION_POINTS_CAP = Decimal("12.0")
SANCTION_SUSPENSION_THRESHOLD = Decimal("10.0")
COUNTABLE_CLAIM_STATUSES = ("ISSUED", "PETITIONED", "MITIGATED", "PAID")

# ---- general_order_deadline ---------------------------------------------
GO_DAYS = 15
GO_HOLD_GRACE_DAYS = 5

# ---- bond_selection_policy ----------------------------------------------
BOND_COVERAGE_MARGIN_DAYS = 3

OPEN_MOVEMENT_STATUSES = ("FILED", "IN_TRANSIT", "OVERDUE", "ARRIVED", "EXPORTED")
LIVE_CLAIM_STATUSES = ("ISSUED", "PETITIONED", "MITIGATED")


# --------------------------------------------------------------------------
# rounding primitives
# --------------------------------------------------------------------------
def round2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round1(value):
    return Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def days(count):
    return timedelta(seconds=int(count) * SECONDS_PER_DAY)


# --------------------------------------------------------------------------
# 1. transit allowance and deadline
# --------------------------------------------------------------------------
def transit_allowance(in_bond_type, origin_region, destination_region,
                      sanction_points, extension_days_granted):
    raw = BASE_TRANSIT_DAYS.get(in_bond_type, 30)
    if origin_region != destination_region:
        raw += INTERPORT_LEG_DAYS
    if Decimal(sanction_points) >= SANCTION_THROTTLE_THRESHOLD:
        halved = int(math.floor(raw * float(SANCTION_THROTTLE_FACTOR)))
        raw = max(MIN_TRANSIT_DAYS, halved)
    raw = min(raw, MAX_TRANSIT_DAYS)
    return raw + int(extension_days_granted or 0)


def deadline_from(anchor, transit_days_allowed):
    return anchor + days(transit_days_allowed)


# --------------------------------------------------------------------------
# 2. movement bond obligation
# --------------------------------------------------------------------------
def movement_obligation(cargo_value, gross_weight_kg, package_count):
    c_value = round2(Decimal(cargo_value) * VALUE_RATE)
    c_weight = round2(Decimal(gross_weight_kg) * WEIGHT_RATE)
    c_pkg = round2(Decimal(package_count) * PACKAGE_RATE)
    subtotal = c_value + c_weight + c_pkg
    return max(MIN_OBLIGATION, subtotal)


# --------------------------------------------------------------------------
# 5. shared overdue-day measure (ceil, 0 at or before the deadline)
# --------------------------------------------------------------------------
def overdue_days_measure(deadline_utc, reference_ts):
    if deadline_utc is None or reference_ts is None:
        return 0
    if reference_ts <= deadline_utc:
        return 0
    delta = reference_ts - deadline_utc
    whole = delta.days * SECONDS_PER_DAY + delta.seconds
    quotient, remainder = divmod(whole, SECONDS_PER_DAY)
    if remainder or delta.microseconds:
        quotient += 1
    return quotient


def age_days(start, now):
    """Whole days from start to now, rounded down; never negative."""
    if start is None or now is None or now <= start:
        return 0
    delta = now - start
    return (delta.days * SECONDS_PER_DAY + delta.seconds) // SECONDS_PER_DAY


# --------------------------------------------------------------------------
# 4. liquidated damages assessment
# --------------------------------------------------------------------------
def ld_assessment(claim_type, deadline_utc, reference_ts, cargo_value, bond_limit):
    overdue = overdue_days_measure(deadline_utc, reference_ts)
    severity = SEVERITY[claim_type]
    chargeable = max(1, overdue)
    raw = max(LD_MIN_CLAIM, round2(LD_PER_DIEM * severity * Decimal(chargeable)))
    cap = min(Decimal(cargo_value), Decimal(bond_limit))
    return overdue, round2(min(raw, cap))


# --------------------------------------------------------------------------
# 6. mitigation offer
# --------------------------------------------------------------------------
def mitigation_offer(factors, petition_round, gross, prior_violation_count):
    credit = Decimal("0.00")
    for code in CREDIT_ORDER:
        if code in factors:
            credit += CREDIT[code]
    credit = max(Decimal("0.00"),
                 credit - Decimal(int(prior_violation_count)) * PRIOR_VIOLATION_DEBIT)
    cap = CAP_FIRST if int(petition_round) == 1 else CAP_SUPPLEMENTAL
    pct = min(credit, cap)
    gross = Decimal(gross)
    net_before_fee = round2(gross * (Decimal("1") - pct))
    if net_before_fee < FEE_TIER1_CEILING:
        fee = FEE_TIER1_FLAT
    elif net_before_fee < FEE_TIER2_CEILING:
        fee = FEE_TIER2_FLAT
    else:
        fee = round2(net_before_fee * FEE_TIER3_RATE)
    offer = round2(min(gross, net_before_fee + fee))
    return pct, net_before_fee, fee, offer


def partial_grant_amount(assessed, offer):
    assessed = Decimal(assessed)
    offer = Decimal(offer)
    return round2(assessed - (assessed - offer) * PARTIAL_GRANT_FACTOR)


# --------------------------------------------------------------------------
# 7. carrier sanction points
# --------------------------------------------------------------------------
def decay_factor(claim_age_days):
    if claim_age_days <= 90:
        return DECAY_FRESH
    if claim_age_days <= 180:
        return DECAY_RECENT
    if claim_age_days <= 365:
        return DECAY_STALE
    return DECAY_EXPIRED


def sanction_points(claims, now):
    raw = Decimal("0.0")
    for claim in claims:
        factor = decay_factor(age_days(claim["issued_at"], now))
        raw += POINTS[claim["claim_type"]] * factor
    return min(SANCTION_POINTS_CAP, round1(raw))


# --------------------------------------------------------------------------
# 9. examination window occupancy (half-open intervals)
# --------------------------------------------------------------------------
def windows_overlap(a_start, a_end, b_start, b_end):
    if None in (a_start, a_end, b_start, b_end):
        return False
    return a_start < b_end and b_start < a_end


# --------------------------------------------------------------------------
# 3.2 single-transaction bond window (closed interval)
# --------------------------------------------------------------------------
def closed_windows_collide(a_start, a_end, b_start, b_end):
    if None in (a_start, a_end, b_start, b_end):
        return False
    return a_start <= b_end and b_start <= a_end
