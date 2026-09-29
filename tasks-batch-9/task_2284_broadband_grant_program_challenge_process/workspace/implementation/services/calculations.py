"""The ten calculation rules of PRD section 2 / scaffold section 1.3.

Every monetary or scored figure is computed with decimal.Decimal and rounded
half up exactly where the specification says it is rounded.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

# ------------------------------------------------------------------ constants

UNRELIABLE_TECHNOLOGIES = ("UNLICENSED_FIXED_WIRELESS", "GEOSTATIONARY_SATELLITE")

TECHNOLOGIES = (
    "FIBER",
    "CABLE",
    "DSL",
    "LICENSED_FIXED_WIRELESS",
    "UNLICENSED_FIXED_WIRELESS",
    "GEOSTATIONARY_SATELLITE",
    "LEO_SATELLITE",
)

EVIDENCE_WEIGHTS = {
    "SPEED_TEST": 15,
    "SUBSCRIBER_BILL": 25,
    "SERVICE_DENIAL_LETTER": 30,
    "FIELD_SURVEY": 20,
    "PROVIDER_ATTESTATION": 35,
    "MAP_DATA_EXPORT": 10,
    "CONSTRUCTION_PERMIT_RECORD": 20,
}
EVIDENCE_TYPES = tuple(EVIDENCE_WEIGHTS.keys())
PRIVILEGED_PROVIDER_EVIDENCE = ("PROVIDER_ATTESTATION", "MAP_DATA_EXPORT")

RECENCY_FULL_DAYS = 180
RECENCY_HALF_DAYS = 365
PROVIDER_STANDARD_THRESHOLD = Decimal("60.00")
COMMUNITY_STANDARD_THRESHOLD = Decimal("40.00")
REBUTTAL_WINDOW_DAYS = 30
MAX_REBUTTAL_ROUNDS = 2
MAX_CHALLENGE_RESUBMISSIONS = 2
MAX_APPLICATION_CURES = 2
MAX_MILESTONE_RESUBMISSIONS = 2
AUDIT_BUFFER_HOURS = 24

LIQUIDITY_REQUIREMENT_RATIO = Decimal("0.25")
REMEDIATION_FINANCIAL_HAIRCUT = Decimal("0.85")
PERSONNEL_POINTS = Decimal("5")
PRIOR_AWARD_POINTS = Decimal("5")
TECHNICAL_CAP = Decimal("40.00")
FINANCIAL_CAP = Decimal("35.00")
MANAGERIAL_CAP = Decimal("25.00")
QUALIFY_INDEX = Decimal("70.00")
QUALIFY_TECHNICAL_FLOOR = Decimal("24.00")
QUALIFY_FINANCIAL_FLOOR = Decimal("17.50")
REMEDIATION_INDEX_FLOOR = Decimal("55.00")

CAPABILITY_BONUS_THRESHOLD = Decimal("90.00")
MAX_TOTAL_SCORE = Decimal("100.00")

PENALTY_TIER_BREAKPOINTS = (Decimal("0.10"), Decimal("0.25"), Decimal("0.50"))
PENALTY_TIER_MULTIPLIERS = (
    Decimal("1.00"),
    Decimal("1.10"),
    Decimal("1.25"),
    Decimal("1.50"),
)


# ------------------------------------------------------------------- numerics

def D(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(0)
    return Decimal(str(value))


def round_half_up(value, places):
    quant = Decimal(1).scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def num(value, places=2):
    """A rounded decimal rendered as a JSON number."""
    return float(round_half_up(value, places))


def cents(value):
    return int(round_half_up(value, 0))


# --------------------------------------------------- 1. location_classification

def classify_location(program, technology, down_mbps, up_mbps, latency_ms):
    """Four tests in a fixed order; the first match wins."""
    if technology in UNRELIABLE_TECHNOLOGIES:
        return "UNSERVED"
    if D(latency_ms) > D(program["max_latency_ms"]):
        return "UNSERVED"
    if (D(down_mbps) < D(program["unserved_down_mbps_threshold"])
            or D(up_mbps) < D(program["unserved_up_mbps_threshold"])):
        return "UNSERVED"
    if (D(down_mbps) < D(program["served_down_mbps_threshold"])
            or D(up_mbps) < D(program["served_up_mbps_threshold"])):
        return "UNDERSERVED"
    return "SERVED"


# ---------------------------------------- 2. challenge_evidence_sufficiency

def evidence_age_days(challenge_created_at, collected_at):
    delta = (challenge_created_at - collected_at).total_seconds()
    return int(math.floor(delta / 86400.0))


def recency_multiplier(age_days):
    if age_days <= RECENCY_FULL_DAYS:
        return Decimal("1.0")
    if age_days <= RECENCY_HALF_DAYS:
        return Decimal("0.5")
    return Decimal("0.0")


def evidence_weights(evidence_type, age_days):
    base = D(EVIDENCE_WEIGHTS[evidence_type])
    mult = recency_multiplier(age_days)
    weighted = round_half_up(base * mult, 2)
    state = "ACCEPTED" if mult > 0 else "STALE_EXCLUDED"
    return base, mult, weighted, state


def sum_weighted(items):
    """Per-item values are already rounded; sum then round the sum."""
    total = Decimal(0)
    for item in items:
        total += round_half_up(item["weighted_value"], 2)
    return round_half_up(total, 2)


def required_threshold(challenger_type):
    if challenger_type == "PROVIDER":
        return PROVIDER_STANDARD_THRESHOLD
    return COMMUNITY_STANDARD_THRESHOLD


def evidence_standard_met(challenge, challenge_side_accepted):
    if D(challenge["evidence_sufficiency_score"]) < D(challenge["required_sufficiency_threshold"]):
        return False
    if challenge["challenger_type"] == "PROVIDER":
        for item in challenge_side_accepted:
            if item["evidence_type"] in PRIVILEGED_PROVIDER_EVIDENCE:
                return True
        return False
    return int(challenge.get("distinct_evidence_type_count") or 0) >= 2


# ------------------------------------------- 3. subgrantee_capability_index

def capability_components(subgrantee, variant):
    if variant == "REMEDIATION":
        net_basis = D(subgrantee.get("audited_net_assets_cents"))
        haircut = REMEDIATION_FINANCIAL_HAIRCUT
        personnel = (int(subgrantee.get("key_personnel_count") or 0)
                     - int(subgrantee.get("withdrawn_personnel_count") or 0))
    else:
        net_basis = D(subgrantee.get("net_assets_cents"))
        haircut = Decimal("1.00")
        personnel = int(subgrantee.get("key_personnel_count") or 0)

    technical = round_half_up(min(TECHNICAL_CAP, D(subgrantee.get("technical_raw_score"))), 2)

    liquidity_need = D(subgrantee["requested_amount_cents"]) * LIQUIDITY_REQUIREMENT_RATIO
    if liquidity_need > 0:
        ratio = min(Decimal("1.0"), net_basis / liquidity_need)
    else:
        ratio = Decimal("1.0")
    financial = round_half_up(min(FINANCIAL_CAP, FINANCIAL_CAP * ratio) * haircut, 2)

    managerial_raw = PERSONNEL_POINTS * D(personnel)
    if subgrantee.get("has_prior_federal_award"):
        managerial_raw += PRIOR_AWARD_POINTS
    managerial = round_half_up(min(MANAGERIAL_CAP, managerial_raw), 2)

    index = round_half_up(technical + financial + managerial, 2)
    return technical, financial, managerial, index


def capability_outcome(index, technical, financial, variant):
    """Exhaustive routing (PRD section 3.4)."""
    if (index >= QUALIFY_INDEX
            and technical >= QUALIFY_TECHNICAL_FLOOR
            and financial >= QUALIFY_FINANCIAL_FLOOR):
        return "QUALIFIED"
    if variant == "INITIAL" and index >= REMEDIATION_INDEX_FLOOR:
        return "REMEDIATION_REQUIRED"
    return "DISQUALIFIED"


# ----------------------------------------- 4. application_cost_per_location

def preliminary_cost_per_location(total_project_cost_cents, claim_count):
    if not claim_count:
        return None
    return cents(D(total_project_cost_cents) / D(claim_count))


def final_cost_per_location(eligible_project_cost_cents, confirmed_location_count):
    if not confirmed_location_count:
        return None
    return cents(D(eligible_project_cost_cents) / D(confirmed_location_count))


# --------------------------------------------- 5. application_total_score

def cost_points(final_cost):
    c = D(final_cost)
    if c <= 100000:
        return Decimal("30.00")
    if c <= 250000:
        return Decimal("24.00")
    if c <= 500000:
        return Decimal("16.00")
    if c <= 1000000:
        return Decimal("8.00")
    return Decimal("0.00")


def speed_points(down, up, latency):
    points = Decimal("25.00")
    if D(down) >= 1000 and D(up) >= 1000:
        points += Decimal("5.00")
    if D(latency) <= 50:
        points += Decimal("2.00")
    return min(Decimal("30.00"), points)


def affordability_points(price_cents, participates):
    price = D(price_cents)
    if price <= 3000:
        base = Decimal("20.00")
    elif price <= 5000:
        base = Decimal("14.00")
    elif price <= 7500:
        base = Decimal("6.00")
    else:
        base = Decimal("0.00")
    if participates:
        base += Decimal("5.00")
    return min(Decimal("20.00"), base)


def workforce_points(has_dbe, has_union, local_hire_pct):
    total = Decimal("0.00")
    if has_dbe:
        total += Decimal("5.00")
    if has_union:
        total += Decimal("5.00")
    total += round_half_up(Decimal("10.00") * D(local_hire_pct) / Decimal(100), 2)
    return min(Decimal("20.00"), total)


def application_total_score(application, capability_index):
    cp = cost_points(application.get("final_cost_per_location_cents"))
    sp = speed_points(
        application["committed_down_mbps"],
        application["committed_up_mbps"],
        application["committed_latency_ms"],
    )
    ap = affordability_points(
        application["low_cost_plan_price_cents"],
        application.get("participates_in_state_affordability_program"),
    )
    wp = workforce_points(
        application.get("has_dbe_plan"),
        application.get("has_union_agreement"),
        application.get("local_hire_pct") or 0,
    )
    multiplier = (Decimal("1.05")
                  if D(capability_index) >= CAPABILITY_BONUS_THRESHOLD
                  else Decimal("1.00"))
    subtotal = cp + sp + ap + wp
    total = min(MAX_TOTAL_SCORE, round_half_up(subtotal * multiplier, 2))
    return cp, sp, ap, wp, multiplier, total


# ------------------------------------------------ 6. award_match_requirement

def match_share(claimed_cost_cents, min_match_pct):
    return cents(D(claimed_cost_cents) * D(min_match_pct) / Decimal(100))


# ------------------------------------------------ 7/8. milestone disbursement

def milestone_payable(award, program, milestone, verified_location_count):
    remaining_cap = D(award["holdback_cap_cents"]) - D(award["disbursed_to_date_cents"])
    if milestone.get("is_final"):
        return int(D(award["obligation_amount_cents"]) - D(award["disbursed_to_date_cents"]))
    if milestone["evidence_basis"] == "BUILD_PROGRESS":
        confirmed = D(award["confirmed_location_count"])
        if confirmed <= 0:
            gross = Decimal(0)
        else:
            gross = D(cents(D(award["obligation_amount_cents"])
                            * D(verified_location_count) / confirmed))
        return int(min(gross, remaining_cap))
    eligible = D(cents(D(milestone.get("invoiced_cost_cents"))
                       * (Decimal(100) - D(program["min_match_pct"])) / Decimal(100)))
    return int(min(eligible, remaining_cap))


# ------------------------------------------------- 10. clawback calculation

def noncompliant_share(failed_count, confirmed_count):
    if not confirmed_count:
        return None
    return round_half_up(D(failed_count) / D(confirmed_count), 4)


def penalty_multiplier(share):
    s = D(share)
    for idx, breakpoint in enumerate(PENALTY_TIER_BREAKPOINTS):
        if s <= breakpoint:
            return PENALTY_TIER_MULTIPLIERS[idx]
    return PENALTY_TIER_MULTIPLIERS[-1]


def recovery_amount(disbursed_to_date_cents, failed_count, confirmed_count, multiplier):
    if not confirmed_count:
        return 0
    base = cents(D(disbursed_to_date_cents) * D(failed_count) / D(confirmed_count))
    return int(min(D(disbursed_to_date_cents), D(cents(D(base) * D(multiplier)))))
