"""The eleven calculation rules (SCAFFOLD §1.3 / PRD §2.8, §3.6, §3.7, §3.9).

All money is whole cents held in Decimal during evaluation; every rounding is
half up, and every pinned evaluation order is honoured literally.
"""

from decimal import Decimal, ROUND_HALF_UP

# ------------------------------------------------------------------ constants
HAZARD_UPLIFT_PCT = Decimal("0.10")
EXCLUSIVITY_PREMIUM_PER_30D_CENTS = 40000
PRESS_APPEARANCE_RATE_CENTS = 25000
REUNION_FLAT_CENTS = 150000
DEPICTION_ADJ_PCT = {
    "FULL": Decimal("0.00"),
    "LIMITED": Decimal("-0.05"),
    "PSEUDONYMIZED": Decimal("-0.12"),
}
PROVISIONAL_PRESS_RESERVE = 2

KIND_WEIGHT = {
    "INTERVIEW": Decimal("1.5"),
    "BACKGROUND_CHECK": Decimal("3.0"),
    "PSYCH_EVAL": Decimal("4.0"),
    "MEDICAL_EXAM": Decimal("2.0"),
}
OUTCOME_FACTOR = {
    "PASS": Decimal("0.0"),
    "CONDITIONAL": Decimal("0.5"),
    "FAIL": Decimal("1.0"),
}
PENDING_SEVERITY_CEILING = 5
DECAY_LADDER = [Decimal("1.00"), Decimal("0.80"), Decimal("0.60"), Decimal("0.50")]
DECAY_TAIL = Decimal("0.50")
RISK_REJECT_THRESHOLD = Decimal("12.00")
RISK_ENHANCED_SUPPORT_THRESHOLD = Decimal("8.00")

BASE_SCREENING_KINDS = ("INTERVIEW", "BACKGROUND_CHECK", "MEDICAL_EXAM")

VALIDITY_DAYS_BY_KIND = {
    "MEDICAL_EXAM": 30,
    "PSYCH_EVAL": 60,
    "BACKGROUND_CHECK": 180,
    "INTERVIEW": None,
}

BAND_LOW_RATE = Decimal("0.04")
BAND_MID_RATE = Decimal("0.07")
BAND_HIGH_RATE = Decimal("0.09")
BAND_MID_FLOOR_CENTS = 5000000
BAND_HIGH_FLOOR_CENTS = 20000000
TIER_FACTOR = {
    "STANDARD": Decimal("1.0"),
    "ENHANCED": Decimal("1.5"),
    "CRITICAL": Decimal("2.0"),
}
TIER_LADDER = ["STANDARD", "ENHANCED", "CRITICAL"]

RESTRICTED_UTILISATION_NUMERATOR = 90
RESTRICTED_UTILISATION_DENOMINATOR = 100
FROZEN_INCIDENT_COUNT = 2

MINOR_DAILY_TOTAL_HOURS_CAP = Decimal("8.0")
EDUCATION_DAYS_PER_WEEK = Decimal("5")

PRESS_SPACING_DAYS = 30
REUNION_OFFSET_DAYS = 180

BASE_SESSIONS = {1: 2, 2: 4, 3: 8, 4: 12, 5: 16}
AFTERCARE_SESSION_CAP = 24

MIN_EDUCATION_HOURS_BY_JURISDICTION = {"CA": 15, "NY": 12, "GA": 10, "IL": 12}
MIN_TRUST_PCT_BY_JURISDICTION = {
    "CA": Decimal("0.15"),
    "NY": Decimal("0.15"),
    "GA": Decimal("0.10"),
    "IL": Decimal("0.10"),
}


# ------------------------------------------------------------------- rounding
def round_half_up(value, places=0):
    quantum = Decimal(1).scaleb(-places) if places else Decimal(1)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def cents(value):
    return int(round_half_up(value))


def dec(value):
    return Decimal(str(value))


# --------------------------------------------- agreement_stipend_commitment
def tier_multiplier(episodes):
    if episodes <= 4:
        return Decimal("1.00")
    if episodes <= 8:
        return Decimal("1.15")
    return Decimal("1.30")


def agreement_stipend_commitment(agreement, production, variant):
    """Whole cents; per-component rounding precedes summation, and the
    depiction adjustment is applied to the rounded subtotal."""
    if variant == "FINAL":
        episodes_used = agreement["episodes_committed"]
        press_count = agreement["press_appearance_obligation_count"]
        reunion = bool(agreement["reunion_obligation"])
        depiction_pct = DEPICTION_ADJ_PCT[agreement["depiction_rights_scope"]]
    elif variant == "PROVISIONAL":
        episodes_used = max(agreement["episodes_committed"], production["episode_order"])
        press_count = agreement["press_appearance_obligation_count"] + PROVISIONAL_PRESS_RESERVE
        reunion = True
        depiction_pct = Decimal("0")
    else:  # pragma: no cover - defensive
        raise ValueError("unknown stipend variant %r" % variant)

    base_component = cents(
        Decimal(agreement["base_stipend_cents"]) * Decimal(episodes_used) * tier_multiplier(episodes_used)
    )
    if production["format_type"] == "COMPETITION_HIGH_STRESS":
        hazard_component = cents(Decimal(base_component) * HAZARD_UPLIFT_PCT)
    else:
        hazard_component = 0
    days = agreement["exclusivity_window_days"]
    blocks = -(-int(days) // 30)
    exclusivity_component = blocks * EXCLUSIVITY_PREMIUM_PER_30D_CENTS
    press_component = press_count * PRESS_APPEARANCE_RATE_CENTS
    reunion_component = REUNION_FLAT_CENTS if reunion else 0

    subtotal = (
        base_component
        + hazard_component
        + exclusivity_component
        + press_component
        + reunion_component
    )
    depiction_adjustment = cents(Decimal(subtotal) * depiction_pct)
    return subtotal + depiction_adjustment


# ------------------------------------------------------- applicant_risk_score
def required_kinds(psych_eval_required):
    kinds = set(BASE_SCREENING_KINDS)
    if psych_eval_required:
        kinds.add("PSYCH_EVAL")
    return kinds


def item_points(item):
    outcome = item["outcome"]
    factor = OUTCOME_FACTOR.get(outcome)
    if factor is None:
        return Decimal("0")
    return Decimal(item["severity_flags"]) * KIND_WEIGHT[item["kind"]] * factor


def provisional_ceiling_score(items):
    total = Decimal("0")
    for item in items:
        if item["recorded_at"] is None:
            total += Decimal(PENDING_SEVERITY_CEILING) * KIND_WEIGHT[item["kind"]] * Decimal("1.0")
        else:
            total += item_points(item)
    return round_half_up(total, 2)


def final_decayed_score(ordered_recorded_items):
    total = Decimal("0")
    for index, item in enumerate(ordered_recorded_items, start=1):
        decay = DECAY_LADDER[index - 1] if index <= len(DECAY_LADDER) else DECAY_TAIL
        total += item_points(item) * decay
    return round_half_up(total, 2)


# ---------------------------------------------------- welfare_commitment_rollup
def welfare_committed(protocol_subtotal, duty_of_care_tier):
    subtotal = int(protocol_subtotal)
    if subtotal < BAND_MID_FLOOR_CENTS:
        band_rate = BAND_LOW_RATE
    elif subtotal < BAND_HIGH_FLOOR_CENTS:
        band_rate = BAND_MID_RATE
    else:
        band_rate = BAND_HIGH_RATE
    factor = TIER_FACTOR[duty_of_care_tier]
    surcharge = cents(Decimal(subtotal) * band_rate * factor)
    return subtotal + surcharge


# -------------------------------------------------- minor_trust_deposit_schedule
def trust_deposit_schedule(total_stipend_commitment_cents, trust_deposit_pct, installment_count):
    target = Decimal(total_stipend_commitment_cents) * dec(trust_deposit_pct)
    per_installment = cents(target / Decimal(installment_count))
    deposited = per_installment * installment_count
    return per_installment, deposited


# ---------------------------------------------------- casting_posture_derivation
def derive_casting_posture(production):
    if production["welfare_committed_cents"] > production["welfare_budget_cents"]:
        return "FROZEN"
    if production["welfare_incident_count"] >= FROZEN_INCIDENT_COUNT:
        return "FROZEN"
    if (production["stipend_committed_cents"] * RESTRICTED_UTILISATION_DENOMINATOR) >= (
        production["stipend_pool_cents"] * RESTRICTED_UTILISATION_NUMERATOR
    ):
        return "RESTRICTED"
    if production["minor_participant_cap"] > 0 and (
        production["minor_participant_count"] >= production["minor_participant_cap"]
    ):
        return "RESTRICTED"
    return "OPEN"


# --------------------------------------------------- aftercare_session_authorization
def aftercare_sessions(severity, duty_of_care_tier):
    base = BASE_SESSIONS[int(severity)]
    factor = TIER_FACTOR[duty_of_care_tier]
    rounded = int(round_half_up(Decimal(base) * factor))
    return min(AFTERCARE_SESSION_CAP, rounded)


def escalate_tier(tier):
    index = TIER_LADDER.index(tier)
    return TIER_LADDER[min(index + 1, len(TIER_LADDER) - 1)]


# ------------------------------------------------------- minor_daily_onset_hours
def hours(value):
    return round_half_up(dec(value), 1)
