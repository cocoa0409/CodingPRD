"""Calculation rules (scaffold section 1.3 / PRD 2.6, 3.x)."""

from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------- constants ---
TURN_CLASS_BY_VALVE_TYPE = {
    "BALL": "QUARTER_TURN",
    "BUTTERFLY": "QUARTER_TURN",
    "GATE": "MULTI_TURN",
    "CONTROL": "MULTI_TURN",
}
TURN_PRESSURE_DIVISOR = {"QUARTER_TURN": Decimal("10000"), "MULTI_TURN": Decimal("20000")}
SERVICE_FACTOR = {
    "FIRE_SAFE": Decimal("1.25"),
    "CRYOGENIC": Decimal("1.40"),
    "FUGITIVE_EMISSION": Decimal("1.15"),
}
SEAT_FACTOR = {"SOFT": Decimal("1.00"), "METAL": Decimal("1.30")}
DATASHEET_UNCERTAINTY_FACTOR = Decimal("1.10")

SPECIAL_SERVICE_SURCHARGE_RATE = {
    "FIRE_SAFE": Decimal("0.06"),
    "CRYOGENIC": Decimal("0.12"),
    "FUGITIVE_EMISSION": Decimal("0.04"),
}
EXPEDITE_FEE_RATE = Decimal("0.08")
CANCELLATION_RETENTION_RATE = {
    "APPROVED": Decimal("0.10"),
    "IN_PRODUCTION": Decimal("0.35"),
    "HELD": Decimal("0.35"),
}

REJECT_RATE_PENALTY = Decimal("40")
REVOCATION_PENALTY = Decimal("8")

PRESSURE_CLASS_RATED_BAR = {
    150: Decimal("19.6"),
    300: Decimal("51.1"),
    600: Decimal("102.1"),
    900: Decimal("153.2"),
    1500: Decimal("255.3"),
    2500: Decimal("425.5"),
}
SHELL_TEST_MULTIPLIER = Decimal("1.5")
SEAT_TEST_MULTIPLIER = Decimal("1.1")

DOC_WEIGHT = {
    "MATERIAL_TEST_REPORT": Decimal("0.25"),
    "TEST_CERTIFICATE": Decimal("0.25"),
    "DIMENSIONAL_REPORT": Decimal("0.15"),
    "NDE_REPORT": Decimal("0.15"),
    "ACTUATOR_DATASHEET": Decimal("0.10"),
    "DECLARATION_OF_CONFORMITY": Decimal("0.10"),
}

MAX_CARBON_EQUIVALENT_PCT = {
    "WCB": Decimal("0.45"),
    "LCC": Decimal("0.43"),
    "A105": Decimal("0.48"),
    "CF8M": Decimal("0.40"),
    "F316": Decimal("0.40"),
}
MIN_IMPACT_ENERGY_J = {
    "WCB": Decimal("20"),
    "LCC": Decimal("27"),
    "A105": Decimal("20"),
    "CF8M": Decimal("34"),
    "F316": Decimal("34"),
}

MAJOR_FINDING_FREEZE_THRESHOLD = 2
MINOR_FINDING_CONDITIONAL_THRESHOLD = 5
CONDITIONAL_VALIDITY_DAYS = 180
AUDIT_COOLING_OFF_DAYS = 30
MAX_CLARIFICATION_ROUNDS = 3
TYPE_TEST_VALIDITY_DAYS = 1825


# ------------------------------------------------------------------ helpers ---
def dec(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to `places` decimal places, returning a Decimal."""
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def fnum(value, places):
    return float(rhu(value, places))


# ------------------------------------------------- required actuator torque ---
def required_actuator_torque(model, unit, sizing_basis, order):
    turn_class = TURN_CLASS_BY_VALVE_TYPE[model["valve_type"]]
    pressure_factor = Decimal(1) + (
        dec(model["pressure_class"]) / TURN_PRESSURE_DIVISOR[turn_class]
    )
    services = unit.get("special_services") or []
    if services:
        service_factor = max(SERVICE_FACTOR[s] for s in services)
    else:
        service_factor = Decimal("1.00")
    seat_factor = SEAT_FACTOR[model["seat_type"]]

    if sizing_basis == "DATASHEET" and order and order.get("datasheet_break_torque_nm") is not None:
        base = dec(order["datasheet_break_torque_nm"])
        if order.get("datasheet_torque_source") == "CUSTOMER_STATED":
            base = base * DATASHEET_UNCERTAINTY_FACTOR
    else:
        base = dec(model["base_break_torque_nm"])

    required = rhu(base * pressure_factor * service_factor * seat_factor, 1)
    if required < Decimal("500"):
        margin = Decimal("0.30")
    elif required <= Decimal("2000"):
        margin = Decimal("0.25")
    else:
        margin = Decimal("0.20")
    sized = rhu(required * (Decimal(1) + margin), 1)
    return float(required), float(margin), float(sized)


# --------------------------------------------------- fugitive emission class ---
def leak_class_band(ppm):
    ppm = dec(ppm)
    if ppm <= Decimal("50"):
        return "AA"
    if ppm <= Decimal("100"):
        return "A"
    if ppm <= Decimal("500"):
        return "B"
    if ppm <= Decimal("1000"):
        return "C"
    return "FAIL"


def peak_reading_class(records):
    values = [dec(r.get("leak_rate_ppm")) for r in records if r.get("leak_rate_ppm") is not None]
    if not values:
        return None
    return leak_class_band(max(values))


def time_weighted_class(records):
    usable = [r for r in records if r.get("leak_rate_ppm") is not None]
    if not usable:
        return None
    weight_sum = sum((dec(r.get("hold_seconds")) for r in usable), Decimal("0"))
    if weight_sum == 0:
        return None
    weighted = sum(
        (dec(r.get("leak_rate_ppm")) * dec(r.get("hold_seconds")) for r in usable),
        Decimal("0"),
    )
    ppm = rhu(weighted / weight_sum, 2)
    return leak_class_band(ppm)


# ------------------------------------------------- documentation completeness ---
def documentation_completeness(documents, ordered_qty, has_approved_actuator):
    required_counts = {
        "MATERIAL_TEST_REPORT": int(ordered_qty),
        "TEST_CERTIFICATE": int(ordered_qty),
        "DIMENSIONAL_REPORT": 1,
        "NDE_REPORT": 1,
        "ACTUATOR_DATASHEET": 1 if has_approved_actuator else 0,
        "DECLARATION_OF_CONFORMITY": 1,
    }
    weighted_sum = Decimal("0")
    for doc_type, weight in DOC_WEIGHT.items():
        required = required_counts[doc_type]
        present = len([d for d in documents if d.get("doc_type") == doc_type])
        if required == 0:
            fraction = Decimal("1.00")
        else:
            fraction = rhu(dec(min(present, required)) / dec(required), 2)
        weighted_sum += weight * fraction
    return float(rhu(Decimal("100") * weighted_sum, 2))


# ------------------------------------------------------------- order pricing ---
def eto_order_price_cents(unit_price_cents, ordered_qty, requested_special_services, expedite):
    subtotal = int(unit_price_cents) * int(ordered_qty)
    rate = Decimal("0")
    for service in requested_special_services or []:
        rate += SPECIAL_SERVICE_SURCHARGE_RATE[service]
    surcharge = int(rhu(dec(subtotal) * rate, 0))
    pre_discount = subtotal + surcharge
    if pre_discount >= 6000000:
        discount_pct = Decimal("0.06")
    elif pre_discount >= 2000000:
        discount_pct = Decimal("0.03")
    else:
        discount_pct = Decimal("0.00")
    discount = int(rhu(dec(pre_discount) * discount_pct, 0))
    if expedite:
        expedite_fee = int(rhu(dec(pre_discount - discount) * EXPEDITE_FEE_RATE, 0))
    else:
        expedite_fee = 0
    return pre_discount - discount + expedite_fee


def cancellation_split(gross_quoted_cents, status_at_cancel):
    rate = CANCELLATION_RETENTION_RATE[status_at_cancel]
    net = int(rhu(dec(gross_quoted_cents) * rate, 0))
    credit = int(gross_quoted_cents) - net
    return net, credit


# ------------------------------------------------------- foundry quality index ---
def foundry_quality_index(total_lot_count, rejected_lot_count, revoked_qualification_count):
    if total_lot_count == 0:
        reject_rate = Decimal("0")
    else:
        reject_rate = dec(rejected_lot_count) / dec(total_lot_count)
    index = rhu(
        Decimal("100")
        - REJECT_RATE_PENALTY * reject_rate
        - REVOCATION_PENALTY * dec(revoked_qualification_count),
        2,
    )
    if index < Decimal("0.00"):
        index = Decimal("0.00")
    if index > Decimal("100.00"):
        index = Decimal("100.00")
    return float(index)


def foundry_status_band(quality_index):
    index = dec(quality_index)
    if index >= Decimal("80"):
        return "ACTIVE"
    if index >= Decimal("60"):
        return "PROBATION"
    return "SUSPENDED"


# ---------------------------------------------------------- test envelope ---
def required_test_envelope(model, test_type):
    rated = PRESSURE_CLASS_RATED_BAR[int(model["pressure_class"])]
    if test_type == "SHELL":
        pressure = rhu(rated * SHELL_TEST_MULTIPLIER, 1)
    elif test_type in ("SEAT", "FIRE_SAFE", "CRYOGENIC"):
        pressure = rhu(rated * SEAT_TEST_MULTIPLIER, 1)
    else:
        pressure = Decimal("0.0")
    bore = int(model["bore_size_mm"])
    if bore <= 50:
        hold = 15
    elif bore <= 150:
        hold = 60
    elif bore <= 300:
        hold = 120
    else:
        hold = 300
    return float(pressure), hold
