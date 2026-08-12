"""Calculation rules: certification_score, retention_rate, claim_computation."""

from decimal import Decimal, ROUND_HALF_UP

import db
from db import parse_date

# certification_score constants
W_FEE_COMPLIANCE = Decimal("0.25")
W_ACCESS = Decimal("0.20")
W_ALT_ID = Decimal("0.15")
W_CHEX_POLICY = Decimal("0.20")
W_EDUCATION_SUPPORT = Decimal("0.20")

CRITERIA = ("FEE_COMPLIANCE", "ACCESS", "ALT_ID", "CHEX_POLICY", "EDUCATION_SUPPORT")
CRITERION_WEIGHTS = {
    "FEE_COMPLIANCE": W_FEE_COMPLIANCE,
    "ACCESS": W_ACCESS,
    "ALT_ID": W_ALT_ID,
    "CHEX_POLICY": W_CHEX_POLICY,
    "EDUCATION_SUPPORT": W_EDUCATION_SUPPORT,
}

STANDARD_PASS = Decimal("90.00")
STANDARD_CONDITIONAL = Decimal("75.00")
REMEDIATION_PASS = Decimal("85.00")
REMEDIATION_CONDITIONAL = Decimal("70.00")

# claim_computation constants
TIER1_MAX = 25
TIER2_MAX = 100
TIER1_GROSS_CENTS = 5000
TIER2_GROSS_CENTS = 7500
TIER3_GROSS_CENTS = 10000
ADMIN_WITHHOLDING_BPS = 75
BONUS_TIER_HIGH = Decimal("0.80")
BONUS_TIER_MID = Decimal("0.60")
BONUS_HIGH_CENTS = 2500
BONUS_MID_CENTS = 1500
EDUCATION_STIPEND_RATE = Decimal("0.10")
EDUCATION_COMPLETION_FLOOR = Decimal("0.5")


def round_half_up_2dp(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_half_up_4dp(value):
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def round_half_up_int(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_weighted_score(criteria_ratings):
    """criteria_ratings: [{criterion, rating}]; returns (weighted_score Decimal 2dp, floor_failed bool)."""
    by_criterion = {r["criterion"]: r["rating"] for r in criteria_ratings}
    total = Decimal("0")
    for crit, weight in CRITERION_WEIGHTS.items():
        total += weight * Decimal(by_criterion[crit])
    weighted = round_half_up_2dp(Decimal("100") * total / Decimal("4"))
    floor_failed = by_criterion["FEE_COMPLIANCE"] <= 1 or by_criterion["CHEX_POLICY"] <= 1
    return weighted, floor_failed


def compute_outcome(rubric_mode, weighted_score, mandatory_floor_failed):
    if mandatory_floor_failed:
        return "FAIL"
    if rubric_mode == "STANDARD_RUBRIC":
        pass_t, cond_t = STANDARD_PASS, STANDARD_CONDITIONAL
    else:
        pass_t, cond_t = REMEDIATION_PASS, REMEDIATION_CONDITIONAL
    if weighted_score >= pass_t:
        return "PASS"
    if weighted_score >= cond_t:
        return "CONDITIONAL"
    return "FAIL"


def retention_rate(institution_id, kind, period_end, evaluation_mode):
    """Compute retention rate for one kind. Returns Decimal 4dp or None when no eligible."""
    eligible = []
    for cp in db.retention_checkpoints.values():
        app = db.account_applications.get(cp["application_id"])
        if app is None or app["institution_id"] != institution_id:
            continue
        if cp["kind"] != kind:
            continue
        if parse_date(cp["due_date"]) > parse_date(period_end):
            continue
        eligible.append(cp)
    if not eligible:
        return None
    if evaluation_mode == "PROVISIONAL":
        retained_states = {"EVALUATED_RETAINED", "PENDING", "EXPIRED_UNCONFIRMED"}
    else:
        retained_states = {"EVALUATED_RETAINED"}
    retained = [c for c in eligible if c["status"] in retained_states]
    rate = round_half_up_4dp(Decimal(len(retained)) / Decimal(len(eligible)))
    return rate, retained


def compute_claim(institution_id, period_start, period_end, evaluation_mode):
    """Full claim_computation per SCAFFOLD §1.3. Returns dict of computed fields."""
    ps = parse_date(period_start)
    pe = parse_date(period_end)

    # (1) eligible_opened ordered by opened_at ASC, then created_at ASC
    eligible_opened = []
    for app in db.account_applications.values():
        if app["institution_id"] != institution_id:
            continue
        if app["status"] not in ("OPENED", "CLOSED_EARLY"):
            continue
        opened_date = parse_date(app["opened_at"])
        if opened_date < ps or opened_date > pe:
            continue
        eligible_opened.append(app)
    eligible_opened.sort(key=lambda a: (db.parse_dt(a["opened_at"]), db.parse_dt(a["created_at"])))
    opened_count = len(eligible_opened)

    # (2)+(3) per-account tier, net with per-account rounding
    opening_claim_cents = 0
    for idx, _app in enumerate(eligible_opened, start=1):
        if idx <= TIER1_MAX:
            gross = TIER1_GROSS_CENTS
        elif idx <= TIER2_MAX:
            gross = TIER2_GROSS_CENTS
        else:
            gross = TIER3_GROSS_CENTS
        net = round_half_up_int(Decimal(gross) * (Decimal("1") - Decimal(ADMIN_WITHHOLDING_BPS) / Decimal("10000")))
        opening_claim_cents += net

    # (4) retention rates
    m6_result = retention_rate(institution_id, "M6", period_end, evaluation_mode)
    m12_result = retention_rate(institution_id, "M12", period_end, evaluation_mode)
    retention_rate_m6 = float(m6_result[0]) if m6_result is not None else None
    retention_rate_m12 = float(m12_result[0]) if m12_result is not None else None

    # (5) retention bonus: union of retained numerator sets; tier by primary rate (m6)
    retained_ids = set()
    if m6_result is not None:
        retained_ids.update(c["id"] for c in m6_result[1])
    if m12_result is not None:
        retained_ids.update(c["id"] for c in m12_result[1])
    retained_count = len(retained_ids)

    primary = m6_result[0] if m6_result is not None else None
    if primary is None:
        tier_rate = 0
    elif primary >= BONUS_TIER_HIGH:
        tier_rate = BONUS_HIGH_CENTS
    elif primary >= BONUS_TIER_MID:
        tier_rate = BONUS_MID_CENTS
    else:
        tier_rate = 0
    retention_bonus_cents = tier_rate * retained_count

    # (6) education stipend on pre-stipend subtotal
    institution = db.partner_institutions.get(institution_id)
    standard = None
    if institution is not None and institution.get("certified_standard_id"):
        standard = db.account_standards.get(institution["certified_standard_id"])

    education_stipend_cents = 0
    if standard is not None and standard.get("requires_financial_education") and opened_count > 0:
        qualifying = 0
        for app in eligible_opened:
            has_pairing = any(
                p["participant_id"] == app["participant_id"]
                and p["status"] in ("COMPLETED", "FOLLOW_UP_DUE", "FOLLOW_UP_DONE")
                for p in db.education_pairings.values()
            )
            if has_pairing:
                qualifying += 1
        fraction = Decimal(qualifying) / Decimal(opened_count)
        if fraction >= EDUCATION_COMPLETION_FLOOR:
            subtotal = opening_claim_cents + retention_bonus_cents
            education_stipend_cents = round_half_up_int(EDUCATION_STIPEND_RATE * Decimal(subtotal))

    # (7) total
    claim_total_cents = opening_claim_cents + retention_bonus_cents + education_stipend_cents

    return {
        "opened_count": opened_count,
        "opening_claim_cents": opening_claim_cents,
        "retention_rate_m6": retention_rate_m6,
        "retention_rate_m12": retention_rate_m12,
        "retention_bonus_cents": retention_bonus_cents,
        "education_stipend_cents": education_stipend_cents,
        "claim_total_cents": claim_total_cents,
    }
