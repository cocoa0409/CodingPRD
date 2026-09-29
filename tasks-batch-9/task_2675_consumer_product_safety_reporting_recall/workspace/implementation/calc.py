"""The eight derived-figure calculations (PRD sections 3.1-3.9)."""

import math
from decimal import Decimal

import store
from store import rhu

# --- 1. incident severity weight (PRD 3.1) --------------------------------
INJURY_BASE_WEIGHT = {
    "NO_INJURY": Decimal("1"),
    "FIRST_AID": Decimal("3"),
    "MEDICAL_TREATMENT": Decimal("8"),
    "HOSPITALIZATION": Decimal("20"),
    "FATALITY": Decimal("50"),
}

CHANNEL_CREDIBILITY = {
    "CONSUMER_HOTLINE": Decimal("1.00"),
    "WEB_FORM": Decimal("1.00"),
    "RETAILER": Decimal("1.20"),
    "MEDICAL_EXAMINER": Decimal("1.50"),
}

INJURY_SEVERITY_ORDER = [
    "NO_INJURY",
    "FIRST_AID",
    "MEDICAL_TREATMENT",
    "HOSPITALIZATION",
    "FATALITY",
]


def severity_weight(injury_class, report_channel, injury_verified):
    product = INJURY_BASE_WEIGHT[injury_class] * CHANNEL_CREDIBILITY[report_channel]
    if not injury_verified:
        product = product * Decimal("0.5")
    return rhu(product, 2)


# --- 2. hazard pattern snapshot (PRD 3.2) ---------------------------------
PATTERN_INPUT_STATUSES = ("CLASSIFIED", "CLUSTERED", "ESCALATED")


def qualifying_incidents(product_model_id, window_start, window_end, analysis_basis):
    """Incidents in the closed date window, in created_at ascending order."""
    def keep(row):
        if row["product_model_id"] != product_model_id:
            return False
        if row["duplicate_of_incident_id"] is not None:
            return False
        if row["status"] not in PATTERN_INPUT_STATUSES:
            return False
        if row["incident_date"] < window_start or row["incident_date"] > window_end:
            return False
        if analysis_basis == "PRELIMINARY" and not row["injury_verified"]:
            return False
        return True

    return store.ordered(store.incidents, keep)


def pattern_snapshot(model, window_start, window_end, analysis_basis):
    rows = qualifying_incidents(model["id"], window_start, window_end, analysis_basis)
    incident_count = len(rows)
    severity_sum = rhu(sum((r["severity_weight"] for r in rows), Decimal("0")), 2)

    exposure = Decimal(model["units_distributed"]) / Decimal("10000")
    if exposure < Decimal("1.0"):
        exposure = Decimal("1.0")
    exposure_per_10k = rhu(exposure, 4)

    tally = {}
    for row in rows:
        code = row["hazard_code"]
        if code is None:
            continue
        tally[code] = tally.get(code, 0) + 1

    dominant_hazard_code = None
    dominant_count = 0
    if tally:
        top = max(tally.values())
        # Tie break: the code carried by the earliest-created incident in the
        # set, taking incidents in created_at ascending order.
        for row in rows:
            code = row["hazard_code"]
            if code is not None and tally.get(code) == top:
                dominant_hazard_code = code
                dominant_count = top
                break

    if incident_count == 0:
        dominant_hazard_code = None
        concentration_ratio = rhu(Decimal("0"), 4)
    else:
        concentration_ratio = rhu(
            Decimal(dominant_count) / Decimal(incident_count), 4)

    density = severity_sum / exposure_per_10k
    raw_index = density * (Decimal("0.5") + concentration_ratio)
    if raw_index > Decimal("100"):
        raw_index = Decimal("100")
    risk_index = rhu(raw_index, 2)

    pattern_confirmed = (
        incident_count >= 3
        and concentration_ratio >= Decimal("0.6000")
        and risk_index >= Decimal("10.00")
    )

    return {
        "incident_count": incident_count,
        "severity_sum": severity_sum,
        "exposure_per_10k": exposure_per_10k,
        "dominant_hazard_code": dominant_hazard_code,
        "concentration_ratio": concentration_ratio,
        "risk_index": risk_index,
        "pattern_confirmed": pattern_confirmed,
    }, rows


# --- 3. internal escalation window (PRD 3.3) ------------------------------
def escalation_window_hours(pattern):
    if pattern["risk_index"] >= Decimal("25.00"):
        return 48
    return 120


# --- 4. section report lateness (PRD 3.4) ---------------------------------
def lateness(report_due_at, submitted_at):
    if report_due_at is None:
        return 0, 0
    late_seconds = (submitted_at - report_due_at).total_seconds()
    if late_seconds < 0:
        late_seconds = 0
    days_late = int(math.ceil(late_seconds / 86400.0))
    if days_late <= 0:
        return 0, 0
    surcharge = days_late * 250000
    if surcharge > 5000000:
        surcharge = 5000000
    return days_late, surcharge


# --- 5. remedy reimbursement total (PRD 3.8) ------------------------------
FIXED_REMEDY_BASE = {"REPAIR": 2500, "RETROFIT_KIT": 4200}
HANDLING_FEE_RATE = Decimal("0.075")


def reimbursement_total(remedy_type, unit_price_cents, shipping_cents_per_unit,
                        quantity):
    if remedy_type in FIXED_REMEDY_BASE:
        base = FIXED_REMEDY_BASE[remedy_type]
    else:
        base = unit_price_cents
    per_unit_subtotal = base + shipping_cents_per_unit
    fee = int(rhu(Decimal(per_unit_subtotal) * HANDLING_FEE_RATE, 0))
    per_unit_total = per_unit_subtotal + fee
    return per_unit_total * quantity


# --- 6. recall effectiveness rate (PRD 3.8) -------------------------------
def effectiveness_rate(recall, basis, model):
    if basis == "PARTICIPATION_BASIS":
        denominator = model["units_registered"] if model else 0
        if denominator < 1:
            denominator = 1
    else:
        denominator = recall["units_in_commerce"]
    if denominator <= 0:
        denominator = 1
    return rhu(Decimal(recall["units_corrected"]) * Decimal("100")
               / Decimal(denominator), 2)


def assessment_for(rate, goal_pct):
    if rate >= goal_pct:
        return "ON_TRACK"
    if rate >= rhu(goal_pct * Decimal("0.5"), 2):
        return "BELOW_TARGET"
    return "CRITICAL"


# --- 7. civil penalty assessment (PRD 3.9) --------------------------------
PENALTY_CEILING_CENTS = 17150000


def worst_injury_multiplier(hazard_pattern_id):
    worst_rank = -1
    for row in store.incidents.values():
        if row["hazard_pattern_id"] != hazard_pattern_id:
            continue
        if row["status"] != "ESCALATED":
            continue
        injury = row["injury_class"]
        if injury is None:
            continue
        rank = INJURY_SEVERITY_ORDER.index(injury)
        if rank > worst_rank:
            worst_rank = rank
    if worst_rank < 0:
        return Decimal("1.00")
    worst = INJURY_SEVERITY_ORDER[worst_rank]
    if worst == "FATALITY":
        return Decimal("1.50")
    if worst == "HOSPITALIZATION":
        return Decimal("1.25")
    return Decimal("1.00")


def penalty_assessment(violation_count, hazard_pattern_id, days_late):
    base = Decimal(1000000) * Decimal(violation_count)
    severity_mult = worst_injury_multiplier(hazard_pattern_id)
    lateness_add = Decimal("0.05") * Decimal(days_late)
    if lateness_add > Decimal("0.50"):
        lateness_add = Decimal("0.50")
    lateness_mult = Decimal("1.00") + lateness_add
    product = base * severity_mult * lateness_mult
    if product > Decimal(PENALTY_CEILING_CENTS):
        product = Decimal(PENALTY_CEILING_CENTS)
    return int(rhu(product, 0))


# --- 8. consent agreement arithmetic (PRD 3.9) ----------------------------
COOPERATION_TIERS = (
    ("TIER_1", Decimal("0.10")),
    ("TIER_2", Decimal("0.15")),
    ("TIER_3", Decimal("0.20")),
)
COOPERATION_BONUS_POINTS = Decimal("0.05")
COOPERATION_RATE_CEILING = Decimal("0.30")


def cooperation_tier(settlement_base):
    """Tier keyed on the pre-credit settlement base, never on the total."""
    amount = Decimal(settlement_base)
    if amount < Decimal(5000000):
        return COOPERATION_TIERS[0]
    if amount <= Decimal(12000000):
        return COOPERATION_TIERS[1]
    return COOPERATION_TIERS[2]


def consent_figures(settlement_base, cooperation_bonus_applied):
    tier, pct = cooperation_tier(settlement_base)
    if cooperation_bonus_applied:
        pct = pct + COOPERATION_BONUS_POINTS
        if pct > COOPERATION_RATE_CEILING:
            pct = COOPERATION_RATE_CEILING
    credit = int(rhu(Decimal(settlement_base) * pct, 0))
    total = int(settlement_base) - credit
    return tier, credit, total


def preview_base(case):
    """Preview variant: the standing offer when one exists, else the assessment."""
    if case["current_offer_cents"] is not None:
        return case["current_offer_cents"]
    return case["assessed_penalty_cents"]


def recompute_preview(case):
    base = preview_base(case)
    _tier, _credit, total = consent_figures(base, case["cooperation_bonus_applied"])
    case["consent_agreement_preview_cents"] = total
    return total
