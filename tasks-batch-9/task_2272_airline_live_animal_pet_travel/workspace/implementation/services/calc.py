"""Pure calculation rules (PRD section 2.5 / 3.x).

All money is an integer number of minor currency units. Every rounding step
uses Decimal with ROUND_HALF_UP (away from zero on a tie); every ceiling step
uses ROUND_CEILING. Never float.
"""
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

# ---- constants (verbatim from the specification) --------------------------
BASE_FEE_CABIN = 12500
BASE_FEE_CHECKED = 20000
BASE_FEE_CARGO = 27500
BASE_FEE = {
    "CABIN": BASE_FEE_CABIN,
    "CHECKED": BASE_FEE_CHECKED,
    "CARGO": BASE_FEE_CARGO,
}
WEIGHT_RATE_MID = 450          # per kg for the 11..32 kg band
WEIGHT_RATE_HIGH = 700         # per kg above 32 kg
WEIGHT_FREE_KG = 10
WEIGHT_MID_CAP_KG = 32
SNUB_NOSED_SURCHARGE_PCT = Decimal("1.15")
LONG_HAUL_SURCHARGE_PCT = Decimal("1.20")
LONG_HAUL_BLOCK_MINUTES = 480
VOLUMETRIC_DIVISOR = Decimal(6000)

LOYALTY_TIER_HIGH_THRESHOLD = 100000
LOYALTY_TIER_LOW_THRESHOLD = 65000
LOYALTY_TIER_HIGH_PCT = Decimal("0.10")
LOYALTY_TIER_LOW_PCT = Decimal("0.05")
CANCEL_REFUND_PCT = Decimal("0.5")
IROPS_CARE_FEE_PER_ANIMAL = 3500

CONTAINER_HEIGHT_CLEARANCE_CM = 8
CONTAINER_LENGTH_FACTOR = Decimal("1.15")
VENT_BASE_PCT = 8
VENT_PER_KG_DIVISOR = Decimal(5)

CONNECTION_MIN_CABIN = 60
CONNECTION_MIN_CHECKED = 90
CONNECTION_MIN_CARGO = 120
CONNECTION_MINIMUM = {
    "CABIN": CONNECTION_MIN_CABIN,
    "CHECKED": CONNECTION_MIN_CHECKED,
    "CARGO": CONNECTION_MIN_CARGO,
}
CONNECTION_MAXIMUM_MINUTES = 720
WELFARE_CHECK_INTERVAL_MINUTES = 240

RESTRICTED_LOAD_NUMERATOR = 10
RESTRICTED_LOAD_DENOMINATOR = 9

KENNEL_SANITATION_BUFFER_MINUTES = 45

SEVERITY_BASE = {"INJURY": 40, "LOSS": 70, "DEATH": 85}
SEVERITY_IN_TRANSIT_ADDER = 10
SEVERITY_WELFARE_GAP_WEIGHT = 6
SEVERITY_WELFARE_GAP_CAP = 12
SEVERITY_MAX = 100
SEVERITY_DISCLOSURE_PENALTY = 20
FINDING_FACTOR = {
    "CARRIER_ATTRIBUTABLE": Decimal("1.0"),
    "INDETERMINATE": Decimal("0.9"),
    "PRE_EXISTING_CONDITION": Decimal("0.8"),
}

DISCLOSURE_BASE_HOURS = {"DEATH": 24, "LOSS": 48, "INJURY": 168}
DISCLOSURE_SCORE_THRESHOLD = 60

MAX_DOCUMENT_REVISIONS = 3


# ---- primitives ----------------------------------------------------------
def dec(value):
    return Decimal(str(value))


def round_half_up(value):
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


# ---- animal_travel_fee --------------------------------------------------
def gross_weight_kg(weight_basis_kg, container):
    return dec(weight_basis_kg) + dec(container["tare_weight_kg"])


def volumetric_weight_kg(container):
    return (dec(container["interior_length_cm"])
            * dec(container["interior_width_cm"])
            * dec(container["interior_height_cm"])) / VOLUMETRIC_DIVISOR


def chargeable_weight_kg(weight_basis_kg, container):
    gross = gross_weight_kg(weight_basis_kg, container)
    volumetric = volumetric_weight_kg(container)
    return ceil_int(gross if gross >= volumetric else volumetric)


def weight_component(chargeable):
    if chargeable <= WEIGHT_FREE_KG:
        return 0
    mid = (min(chargeable, WEIGHT_MID_CAP_KG) - WEIGHT_FREE_KG) * WEIGHT_RATE_MID
    high = max(chargeable - WEIGHT_MID_CAP_KG, 0) * WEIGHT_RATE_HIGH
    return mid + high


def animal_travel_fee(chargeable, routing_type, snub_nosed, block_minutes, animal_kind):
    fee = Decimal(BASE_FEE[routing_type] + weight_component(chargeable))
    if snub_nosed and routing_type != "CABIN":
        fee = Decimal(round_half_up(fee * SNUB_NOSED_SURCHARGE_PCT))
    if block_minutes is not None and block_minutes > LONG_HAUL_BLOCK_MINUTES \
            and animal_kind == "PET":
        fee = Decimal(round_half_up(fee * LONG_HAUL_SURCHARGE_PCT))
    return int(fee)


# ---- container_compliance_evaluation ------------------------------------
def required_interior_height_cm(height_at_shoulder_cm):
    return ceil_int(dec(height_at_shoulder_cm) + CONTAINER_HEIGHT_CLEARANCE_CM)


def required_interior_length_cm(length_nose_to_tail_cm):
    return ceil_int(dec(length_nose_to_tail_cm) * CONTAINER_LENGTH_FACTOR)


def required_ventilation_pct(chargeable):
    return VENT_BASE_PCT + ceil_int(dec(chargeable) / VENT_PER_KG_DIVISOR)


def required_ventilated_sides(chargeable):
    if chargeable <= 20:
        return 2
    if chargeable <= 32:
        return 3
    return 4


def container_deficiency_codes(animal, container, species, routing_type, chargeable, gross):
    """Deficiency codes appended in exactly the specified order."""
    codes = []
    if dec(container["interior_height_cm"]) < required_interior_height_cm(
            animal["height_at_shoulder_cm"]):
        codes.append("HEIGHT")
    if dec(container["interior_length_cm"]) < required_interior_length_cm(
            animal["length_nose_to_tail_cm"]):
        codes.append("LENGTH")
    if dec(container["ventilation_area_pct"]) < required_ventilation_pct(chargeable):
        codes.append("VENT_PCT")
    if container["ventilated_side_count"] < required_ventilated_sides(chargeable):
        codes.append("VENT_SIDES")
    if routing_type == "CABIN":
        if dec(gross) > dec(species["max_cabin_weight_kg"]):
            codes.append("GROSS_WEIGHT")
        if not container["cabin_eligible"]:
            codes.append("CABIN_DIM")
    if routing_type == "CARGO" and not container["wheels_removable"]:
        codes.append("WHEELS")
    return codes


# ---- reservation_charge_assembly ---------------------------------------
def loyalty_tier_pct(subtotal_amount):
    if subtotal_amount >= LOYALTY_TIER_HIGH_THRESHOLD:
        return LOYALTY_TIER_HIGH_PCT
    if subtotal_amount >= LOYALTY_TIER_LOW_THRESHOLD:
        return LOYALTY_TIER_LOW_PCT
    return Decimal(0)


def charge_assembly(segment_fee_total, irops_fee_total, refunded_amount):
    subtotal = int(segment_fee_total) + int(irops_fee_total)
    tier = loyalty_tier_pct(subtotal)
    discount = round_half_up((Decimal(subtotal) - Decimal(refunded_amount)) * tier)
    net = subtotal - int(refunded_amount) - discount
    return subtotal, tier, discount, net


def tier_pct_out(tier):
    if tier == LOYALTY_TIER_HIGH_PCT:
        return 0.1
    if tier == LOYALTY_TIER_LOW_PCT:
        return 0.05
    return 0


def cancellation_refund(subtotal_amount):
    return round_half_up(Decimal(subtotal_amount) * CANCEL_REFUND_PCT)


# ---- incident_severity_score -------------------------------------------
def raw_severity(incident_type, in_transit, required_checks, completed_checks):
    base = SEVERITY_BASE[incident_type]
    adder = SEVERITY_IN_TRANSIT_ADDER if in_transit else 0
    if in_transit:
        gap = max(int(required_checks) - int(completed_checks), 0)
    else:
        gap = 0
    welfare = min(gap * SEVERITY_WELFARE_GAP_WEIGHT, SEVERITY_WELFARE_GAP_CAP)
    return base + adder + welfare


def preliminary_severity(raw):
    return min(raw, SEVERITY_MAX)


def adjudicated_severity(raw, finding, disclosure_required, disclosure_on_time):
    scaled = round_half_up(Decimal(raw) * FINDING_FACTOR[finding])
    if disclosure_required and disclosure_on_time is not True:
        scaled += SEVERITY_DISCLOSURE_PENALTY
    return min(scaled, SEVERITY_MAX)


# ---- connection_welfare_window ----------------------------------------
def required_welfare_checks(connection_minutes):
    return 1 + int(connection_minutes // WELFARE_CHECK_INTERVAL_MINUTES)


# ---- season helpers ----------------------------------------------------
def season_contains(month_day, season_start, season_end):
    if season_start <= season_end:
        return season_start <= month_day <= season_end
    return month_day >= season_start or month_day <= season_end
