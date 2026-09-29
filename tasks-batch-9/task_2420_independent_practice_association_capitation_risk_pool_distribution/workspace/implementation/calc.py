"""The twelve calculations (PRD 2.6, 3.3 - 3.8).

All money is whole cents held as Python ints; all rates are basis points.
No floating point is used anywhere in this module.
"""

import calendar
import datetime

import db

# ------------------------------------------------------------------ constants
AGE_BAND_FACTOR_BPS = {"PEDIATRIC": 6500, "ADULT": 10000, "SENIOR": 14500}
BENEFIT_TIER_ADD_CENTS = {"HMO": 0, "POS": 1200, "HMO_PLUS": 2500}
PMPM_FLOOR_CENTS = 8000
PMPM_CEILING_CENTS = 95000

POOL_DEFICIT_LOSS_RATIO_BPS = 9500
SETTLEMENT_LAG_DAYS = {"PROFESSIONAL": 180, "INSTITUTIONAL": 270}

ADMIN_FEE_BPS_BY_TIER = {"NONE": 0, "TIER_1": 300, "TIER_2": 600, "TIER_3": 1000}
SHARED_SAVINGS_SHARE_BPS_BY_TIER = {"NONE": 0, "TIER_1": 4000, "TIER_2": 5000,
                                    "TIER_3": 6000}

HEDIS_WEIGHT_BPS = 5000
PATIENT_EXPERIENCE_WEIGHT_BPS = 3000
ACCESS_WEIGHT_BPS = 2000

APPEAL_LIMIT = 2

DELEGATION_SCOPES = ("CLAIMS_ONLY", "CLAIMS_AND_UM", "FULL_RISK")
RECONCILIATION_METHODS = ("ROSTER_SNAPSHOT", "MEMBER_MONTHS_PRORATED")
IBNR_METHODS = ("COMPLETION_FACTOR", "PMPM_LOSS_RATIO")


def round_half_up(numerator, denominator):
    """Exact integer round-half-up, halves going away from zero."""
    if denominator == 0:
        return 0
    negative = (numerator < 0) != (denominator < 0)
    n = abs(numerator)
    d = abs(denominator)
    quotient, remainder = divmod(n, d)
    if 2 * remainder >= d:
        quotient += 1
    return -quotient if negative else quotient


def truncate_div(numerator, denominator):
    """Division truncated toward zero."""
    if denominator == 0:
        return 0
    negative = (numerator < 0) != (denominator < 0)
    quotient = abs(numerator) // abs(denominator)
    return -quotient if negative else quotient


# ------------------------------------------------------ 1. member_pmpm_components
def member_pmpm_components(agreement, enrollee):
    base = agreement["base_pmpm_cents"]
    age_bps = AGE_BAND_FACTOR_BPS[enrollee["age_band"]]
    risk_bps = enrollee["risk_score_bps"]
    # both multiplications carried on the unrounded product, rounded once
    raw = round_half_up(base * age_bps * risk_bps, 100000000)
    raw += BENEFIT_TIER_ADD_CENTS[enrollee["benefit_tier"]]
    # nested clamp: floor first, then ceiling
    gross = max(PMPM_FLOOR_CENTS, raw)
    gross = min(PMPM_CEILING_CENTS, gross)
    withhold = round_half_up(gross * agreement["quality_withhold_bps"], 10000)
    return gross, withhold, gross - withhold


# ---------------------------------------------------- 2. enrollment_row_matching
def enrollment_row_match_status(row, agreement_id):
    enrollee = None
    for candidate in db.enrollees.values():
        if (candidate["agreement_id"] == agreement_id
                and candidate["external_member_id"] == row["external_member_id"]):
            enrollee = candidate
            break
    physician = None
    for candidate in db.physicians.values():
        if (candidate["agreement_id"] == agreement_id
                and candidate["npi"] == row["physician_npi"]):
            physician = candidate
            break
    if enrollee is None:
        return "UNMATCHED"
    if physician is None:
        return "MATCHED_ENROLLEE_ONLY"
    if physician["credential_status"] not in ("ACTIVE", "NOTICE_GIVEN"):
        return "EXCEPTION_PHYSICIAN_INACTIVE"
    return "MATCHED"


# ------------------------------------------------------ 3. file_claimed_capitation
def file_claimed_capitation(file_rows):
    claimed = 0
    retro = 0
    for row in file_rows:
        if row["match_status"] != "MATCHED":
            continue
        action = row["row_action"]
        amount = row["claimed_capitation_cents"]
        if action in ("ADD", "CHANGE", "TERM"):
            claimed += amount
        elif action == "RETRO_ADD":
            retro += amount
        elif action == "RETRO_TERM":
            retro -= amount
    return claimed, retro


# ------------------------- 4. expected_capitation_for_coverage_month (2 variants)
def month_window(coverage_month):
    year = int(coverage_month[0:4])
    month = int(coverage_month[5:7])
    days = calendar.monthrange(year, month)[1]
    start = datetime.datetime(year, month, 1, tzinfo=db.UTC)
    end_exclusive = start + datetime.timedelta(days=days)
    return start, end_exclusive, days


def _covers(assignment, moment):
    """Half-open [effective_date, term_date) containment."""
    effective = assignment["effective_date"].dt
    if moment < effective:
        return False
    term = assignment.get("term_date")
    if term is not None and moment >= term.dt:
        return False
    return True


def _overlaps_month(assignment, start, end_exclusive):
    effective = assignment["effective_date"].dt
    if effective >= end_exclusive:
        return False
    term = assignment.get("term_date")
    if term is not None and term.dt <= start:
        return False
    return True


def _in_coverage(enrollee, moment):
    if moment < enrollee["coverage_start_date"].dt:
        return False
    end = enrollee.get("coverage_end_date")
    if end is not None and moment > end.dt:
        return False
    return True


def expected_capitation_for_coverage_month(agreement, coverage_month, method):
    """Returns (expected_cents, member_month_bps, per_enrollee_mm, attribution)."""
    start, end_exclusive, days_in_month = month_window(coverage_month)
    expected_total = 0
    member_months_total = 0
    per_enrollee_mm = {}
    attribution = {}

    for enrollee in db.enrollees_of_agreement(agreement["id"]):
        qualifying = [a for a in db.assignments_of_enrollee(enrollee["id"])
                      if _overlaps_month(a, start, end_exclusive)]
        if not qualifying:
            continue

        if method == "ROSTER_SNAPSHOT":
            on_roster = any(_covers(a, start) for a in qualifying)
            amount = enrollee["gross_pmpm_cents"] if on_roster else 0
            mm_bps = 10000 if on_roster else 0
        else:  # MEMBER_MONTHS_PRORATED
            covered_days = 0
            for day in range(1, days_in_month + 1):
                moment = datetime.datetime(start.year, start.month, day, tzinfo=db.UTC)
                if not _in_coverage(enrollee, moment):
                    continue
                if any(_covers(a, moment) for a in qualifying):
                    covered_days += 1
            amount = round_half_up(enrollee["gross_pmpm_cents"] * covered_days,
                                   days_in_month)
            mm_bps = round_half_up(covered_days * 10000, days_in_month)

        # per-member amounts are rounded FIRST and then summed
        expected_total += amount
        member_months_total += mm_bps
        per_enrollee_mm[enrollee["id"]] = mm_bps
        earliest = sorted(qualifying, key=lambda a: (a["effective_date"].dt, a["_seq"]))[0]
        attribution[enrollee["id"]] = earliest["physician_id"]

    return expected_total, member_months_total, per_enrollee_mm, attribution


# ------------------------------------- 5. remittance_variance_and_allocation
def remittance_variance_and_allocation(agreement, expected, claimed, retro):
    variance = claimed + retro - expected
    withhold = round_half_up(expected * agreement["quality_withhold_bps"], 10000)
    net_payable = expected - withhold + retro
    institutional = round_half_up(
        net_payable * agreement["institutional_pool_share_bps"], 10000)
    professional = net_payable - institutional
    return variance, withhold, net_payable, institutional, professional


# --------------------------------------------- 6. capitation_posture_derivation
def capitation_posture(agreement):
    agreement_id = agreement["id"]
    file_ids = {f["id"] for f in db.files.values() if f["agreement_id"] == agreement_id}
    for remittance in db.remittances.values():
        if remittance["file_id"] in file_ids and remittance["status"] == "DISPUTED":
            return "WITHHELD"
    for pool in db.pools.values():
        if pool["agreement_id"] == agreement_id and pool["deficit_flag"]:
            return "UNDER_REVIEW"
    return "CURRENT"


# ------------------------------------------- 7. pool_loss_ratio_and_deficit
def pool_loss_ratio_and_deficit(paid_claims_cents, funded_cents):
    if funded_cents == 0:
        ratio = 0
    else:
        ratio = round_half_up(paid_claims_cents * 10000, funded_cents)
    return ratio, ratio > POOL_DEFICIT_LOSS_RATIO_BPS


# -------------------------------------------------- 8. ibnr_reserve_estimate
def ibnr_reserve_estimate(agreement, pool, method):
    paid = pool["paid_claims_cents"]
    if method == "COMPLETION_FACTOR":
        ultimate = round_half_up(paid * 10000, agreement["ibnr_completion_factor_bps"])
        return max(0, ultimate - paid)
    expected = round_half_up(
        agreement["target_claims_pmpm_cents"] * pool["member_months_bps"], 10000)
    return max(0, expected - paid)


# ------------------------------------------------------- 9. stop_loss_recovery
def stop_loss_recovery_amounts(agreement, pool, enrollee_id):
    attachment = agreement["stop_loss_attachment_cents"]
    eligible = 0
    for claim in db.claims.values():
        if (claim["pool_id"] == pool["id"] and claim["enrollee_id"] == enrollee_id
                and claim["status"] == "PAID"):
            eligible += claim["paid_cents"] or 0
    excess = max(0, eligible - attachment)
    recovery = round_half_up(excess * agreement["reinsurance_recovery_bps"], 10000)
    return attachment, eligible, excess, recovery


# ------------------------------------------------ 10. pool_settlement_waterfall
def pool_settlement_waterfall(pool, ibnr_reserve_cents):
    gross_claims = pool["paid_claims_cents"]                      # S1
    recovery = pool["stop_loss_recovery_cents"]                   # S2
    net_claims = gross_claims - recovery + ibnr_reserve_cents     # S3
    funded = pool["funded_cents"]
    raw_surplus = funded - net_claims                             # S4
    if raw_surplus <= 0 or funded == 0:                           # S5 (truncated)
        ratio = 0
    else:
        ratio = truncate_div(raw_surplus * 10000, funded)
    if raw_surplus <= 0:
        tier = "NONE"
    elif ratio <= 500:
        tier = "TIER_1"
    elif ratio <= 1500:
        tier = "TIER_2"
    else:
        tier = "TIER_3"
    fee_bps = ADMIN_FEE_BPS_BY_TIER[tier]                         # S6
    admin_fee = round_half_up(max(0, raw_surplus) * fee_bps, 10000)   # S7
    distributable = max(0, raw_surplus) - admin_fee               # S8
    shared_savings = round_half_up(
        distributable * SHARED_SAVINGS_SHARE_BPS_BY_TIER[tier], 10000)  # S9
    return {
        "gross_claims_cents": gross_claims,
        "stop_loss_recovery_cents": recovery,
        "ibnr_reserve_cents": ibnr_reserve_cents,
        "net_claims_cents": net_claims,
        "raw_surplus_cents": raw_surplus,
        "surplus_ratio_bps": ratio,
        "surplus_tier": tier,
        "admin_fee_bps": fee_bps,
        "admin_fee_cents": admin_fee,
        "distributable_surplus_cents": distributable,
        "shared_savings_pool_cents": shared_savings,
    }


# ------------------------- 11. quality_composite_and_withhold_release
def quality_composite_and_withhold_release(scorecard):
    # the three weighted terms accumulate unrounded, rounded once at the end
    accumulated = (scorecard["hedis_composite_bps"] * HEDIS_WEIGHT_BPS
                   + scorecard["access_score_bps"] * ACCESS_WEIGHT_BPS
                   + scorecard["patient_experience_bps"] * PATIENT_EXPERIENCE_WEIGHT_BPS)
    composite = round_half_up(accumulated, 10000)
    if composite >= 8500:
        release = 10000
    elif composite >= 7000:
        release = 7500
    elif composite >= 5500:
        release = 5000
    else:
        release = 0
    return composite, release


# ------------------------------------------- 12. pool_distribution_allocation
def largest_remainder_allocate(total, weights):
    """Floor each exact share, then hand out leftover cents by largest fraction."""
    count = len(weights)
    shares = [0] * count
    weight_sum = sum(weights)
    if count == 0 or weight_sum == 0 or total == 0:
        return shares
    for index, weight in enumerate(weights):
        shares[index] = (total * weight) // weight_sum
    leftover = total - sum(shares)
    if leftover <= 0:
        return shares
    # fractional part of exact share i == (total * w_i) - share_i * weight_sum
    order = sorted(
        range(count),
        key=lambda i: (-(total * weights[i] - shares[i] * weight_sum), i),
    )
    for index in order[:leftover]:
        shares[index] += 1
    return shares
