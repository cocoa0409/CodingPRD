"""Pinned calculations: brand ladder, damage ratio, completeness, scores,
fees, adequacy and the odometer replay.  All money is integer cents and every
rounding is ROUND_HALF_UP."""

from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------- enumerations

ROLE_ALL = (
    "ProgramAdmin",
    "StateTitleClerk",
    "InsurerAdjuster",
    "Rebuilder",
    "Inspector",
    "HearingOfficer",
    "FraudInvestigator",
)

BODY_CLASSES = ("SEDAN", "SUV", "TRUCK", "MOTORCYCLE", "TRAILER")
BRAND_CODES = ("NONE", "SALVAGE", "REBUILT", "FLOOD", "NON_REPAIRABLE")
BRAND_SEVERITY = {"NONE": 0, "SALVAGE": 30, "REBUILT": 40, "FLOOD": 50, "NON_REPAIRABLE": 90}

BASIS_CODES = ("GROSS_ESTIMATE", "NET_OF_SALVAGE")
DAMAGE_TYPES = ("COLLISION", "FLOOD", "HAIL", "THEFT_RECOVERY", "FIRE")

DOC_TYPES = ("RECEIPT", "PHOTOGRAPH", "PARTS_INVOICE", "DONOR_CERTIFICATE")
PART_CLASSES = (
    "STRUCTURAL",
    "RESTRAINT",
    "POWERTRAIN",
    "BODY_PANEL",
    "GLAZING",
    "LIGHTING",
    "WHEEL",
    "PHOTO_SET",
)
SOURCE_TYPES = ("NEW", "USED_DONOR", "RECYCLER", "OWNER_SUPPLIED")
PHOTO_VIEW_CODES = ("FRONT", "REAR", "LEFT", "RIGHT", "VIN_PLATE", "ENGINE_BAY")
REJECTION_REASONS = ("STOLEN_COMPONENT", "UNTRACEABLE_SOURCE", "ILLEGIBLE", "DUPLICATE")
CERTIFICATIONS = ("STRUCTURAL", "FLOOD", "THEFT_RECOVERY")

FINDING_CATEGORIES = (
    "STOLEN_COMPONENT",
    "VIN_ALTERATION",
    "STRUCTURAL_INADEQUACY",
    "ODOMETER_DISCREPANCY",
    "DOCUMENTATION_GAP",
)
FINDING_SEVERITIES = ("ADVISORY", "MAJOR", "CRITICAL")

APPEAL_GROUNDS = ("SCORING_ERROR", "PART_TRACEABILITY_DISPUTE", "PROCEDURAL_DEFECT")
APPEAL_DECISIONS = ("GRANT", "DENY", "REMAND")
REVIEW_DECISIONS = ("OPEN", "ACCEPT", "RETURN")
LICENSE_ACTIONS = ("PROBATION", "CLEAR_PROBATION", "SUSPEND", "REINSTATE", "REVOKE")
REFERRAL_TYPES = ("ODOMETER", "IDENTITY_TAMPERING", "DOCUMENT_FORGERY")
REFERRAL_OUTCOMES = ("SUBSTANTIATED", "UNSUBSTANTIATED")
CHECKPOINT_OUTCOMES = ("PASS", "MARGINAL", "FAIL")

TERMINAL_APP_STATUSES = ("TITLE_ISSUED", "DENIED_FINAL", "WITHDRAWN", "VOID_FRAUD")
LIVE_INSPECTION_STATUSES = ("SCHEDULED", "IN_PROGRESS")

REQUIRED_PART_CLASSES = {
    "SEDAN": ("STRUCTURAL", "RESTRAINT", "LIGHTING"),
    "SUV": ("STRUCTURAL", "RESTRAINT", "LIGHTING"),
    "TRUCK": ("STRUCTURAL", "RESTRAINT", "LIGHTING"),
    "MOTORCYCLE": ("STRUCTURAL", "LIGHTING"),
    "TRAILER": (),
}

CHECKPOINT_WEIGHTS = {
    "STRUCTURAL_FRAME": 35,
    "RESTRAINT_SYSTEM": 20,
    "VIN_INTEGRITY": 20,
    "SUSPENSION_STEERING": 15,
    "LAMPS_GLAZING": 10,
}
CHECKPOINT_CODES = tuple(CHECKPOINT_WEIGHTS.keys())
CHECKPOINT_FACTOR = {"PASS": Decimal("1"), "MARGINAL": Decimal("0.5"), "FAIL": Decimal("0")}

# pinned constants
BASE_APPLICATION_FEE_CENTS = 7500
REINSPECTION_FEE_CENTS = 4000
DONOR_SURCHARGE_RATE = Decimal("0.015")
STRUCTURAL_SURCHARGE_CENTS = 12500
SURCHARGE_CAP_CENTS = 45000
VOLUME_DISCOUNT_RATE = Decimal("0.05")
VOLUME_DISCOUNT_MIN_TITLES = 5
FLOOD_BUFFER_MINUTES = 30
FLOOD_DEPTH_THRESHOLD_CM = 46
NON_REPAIRABLE_RATIO = Decimal("1.20")
SALVAGE_RATIO = Decimal("0.75")
ADEQUACY_PASS_SCORE = Decimal("70.00")
SUBMISSION_WINDOW_DAYS = 180
APPEAL_WINDOW_DAYS = 30
ROLLING_WINDOW_DAYS = 365
BASE_ATTEMPT_LIMIT = 3
REINSTATE_MIN_ROLLING = Decimal("60.00")
REVOKE_MAX_LIFETIME = Decimal("40.00")
MIN_PHOTO_VIEWS = 4
PROBATION_REFERRAL_THRESHOLD = 2
SUSPEND_SUBSTANTIATED_THRESHOLD = 1


# --------------------------------------------------------------- number helpers


def cents(value):
    """Round a Decimal amount half up to a whole number of cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct2(value):
    """Two decimal places, half up, clamped to the closed range 0.00..100.00."""
    quantized = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if quantized < Decimal("0.00"):
        quantized = Decimal("0.00")
    if quantized > Decimal("100.00"):
        quantized = Decimal("100.00")
    return quantized


def ratio4(value):
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def as_number(dec):
    """Publish a Decimal as a JSON number."""
    if dec is None:
        return None
    return float(dec)


def severity(brand_code):
    return BRAND_SEVERITY.get(brand_code, 0)


def most_severe(brand_codes):
    best = "NONE"
    for code in brand_codes:
        if severity(code) > severity(best):
            best = code
    return best


def sort_brands(brand_codes):
    """Distinct, NONE excluded, severity descending."""
    distinct = set(code for code in brand_codes if code and code != "NONE")
    return sorted(distinct, key=lambda code: -severity(code))


# ------------------------------------------------------------------ §3.2 report


def damage_ratio(basis_code, acv_cents, repair_estimate_cents, salvage_retention_cents):
    if basis_code == "NET_OF_SALVAGE":
        denominator = Decimal(acv_cents) - Decimal(salvage_retention_cents)
    else:
        denominator = Decimal(acv_cents)
    if denominator <= 0:
        return ratio4(Decimal(0))
    return ratio4(Decimal(repair_estimate_cents) / denominator)


def recommended_brand(damage_type, flood_water_depth_cm, ratio):
    """Four-rung ladder, top down, first match wins."""
    if damage_type == "FLOOD" and flood_water_depth_cm >= FLOOD_DEPTH_THRESHOLD_CM:
        return "FLOOD"
    if ratio >= NON_REPAIRABLE_RATIO:
        return "NON_REPAIRABLE"
    if ratio >= SALVAGE_RATIO:
        return "SALVAGE"
    return "NONE"


# ------------------------------------------------- §3.5 completeness and scores


def documentation_completeness(body_class, docs):
    required = REQUIRED_PART_CLASSES.get(body_class, ())
    if not required:
        return pct2(Decimal("100"))
    covered = 0
    for part_class in required:
        for doc in docs:
            if doc["status"] == "VERIFIED" and doc["part_class"] == part_class:
                covered += 1
                break
    return pct2(Decimal(covered) * Decimal(100) / Decimal(len(required)))


def recordkeeping_score(docs):
    graded = [doc for doc in docs if doc["part_class"] != "PHOTO_SET"]
    if not graded:
        return pct2(Decimal("100"))
    points = Decimal(0)
    for doc in graded:
        if doc["status"] == "VERIFIED":
            points += Decimal(100) if doc.get("traceable") else Decimal(40)
    return pct2(points / Decimal(len(graded)))


# ------------------------------------------------------------------ §3.6 money


def assess_fee(docs):
    verified = [doc for doc in docs if doc["status"] == "VERIFIED"]
    donor_surcharge = 0
    for doc in verified:
        if doc["source_type"] in ("USED_DONOR", "RECYCLER"):
            # each line item is rounded on its own before any summation
            donor_surcharge += cents(Decimal(doc.get("amount_cents") or 0) * DONOR_SURCHARGE_RATE)
    structural_surcharge = (
        STRUCTURAL_SURCHARGE_CENTS
        if any(doc["part_class"] == "STRUCTURAL" for doc in verified)
        else 0
    )
    surcharge_total = donor_surcharge + structural_surcharge
    if surcharge_total > SURCHARGE_CAP_CENTS:
        surcharge_total = SURCHARGE_CAP_CENTS
    return BASE_APPLICATION_FEE_CENTS + surcharge_total


def expedite_rate(subtotal_cents):
    if subtotal_cents < 10000:
        return Decimal("0.10")
    if subtotal_cents < 25000:
        return Decimal("0.07")
    return Decimal("0.05")


def program_charge(assessed_fee_cents, attempts_completed, expedite_requested, titled_count):
    attempts = attempts_completed if attempts_completed and attempts_completed > 0 else 0
    subtotal = assessed_fee_cents + REINSPECTION_FEE_CENTS * attempts
    rate = expedite_rate(subtotal)
    expedite = cents(Decimal(subtotal) * rate) if expedite_requested else 0
    discount_rate = (
        VOLUME_DISCOUNT_RATE if (titled_count or 0) >= VOLUME_DISCOUNT_MIN_TITLES else Decimal("0")
    )
    discount = cents(Decimal(subtotal + expedite) * discount_rate)
    return {
        "assessed_fee_cents": assessed_fee_cents,
        "subtotal_cents": subtotal,
        "expedite_fee_cents": expedite,
        "discount_cents": discount,
        "total_program_charge_cents": subtotal + expedite - discount,
    }


# ---------------------------------------------------------------- §3.8 adequacy


def adequacy_score(checkpoint_results):
    total = Decimal(0)
    for entry in checkpoint_results:
        weight = CHECKPOINT_WEIGHTS.get(entry.get("code"), 0)
        factor = CHECKPOINT_FACTOR.get(entry.get("outcome"), Decimal(0))
        total += Decimal(weight) * factor
    return pct2(total)


def finding_is_blocking(category, severity_value):
    return severity_value == "CRITICAL" or category in ("STOLEN_COMPONENT", "VIN_ALTERATION")


# --------------------------------------------------------- §3.11 odometer replay


def odometer_flag(events, new_effective_at, new_reading):
    """`events` is a list of (effective_at, created_seq, reading) triples."""
    ordered = sorted(events, key=lambda event: (event[0], event[1]))
    prior = [event[2] for event in ordered if event[0] <= new_effective_at]
    if not prior:
        return "OK"
    highest = max(prior)
    return "ROLLBACK_SUSPECTED" if new_reading < highest else "OK"
