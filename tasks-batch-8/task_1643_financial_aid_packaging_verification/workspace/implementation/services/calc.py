"""Pinned calculation rules (PRD 3.2-3.9, scaffold 1.3).

Every rounding discipline is pinned per PRD 2.5 and implemented exactly:
- round half-up to whole cents: each EFC income-tier product and the EFC
  per-college-member division;
- floor: the EFC asset contribution and the Pell enrollment proration;
- integer floor division in basis points: the SAP pace.
"""
import hashlib
from decimal import Decimal

from util import floor_div, round_half_up_div

# ---------------------------------------------------------------------------
# EFC (PRD 3.3) — seven pinned steps, PROVISIONAL / VERIFIED variants
# ---------------------------------------------------------------------------

IPA_DEPENDENT = [1000000, 1500000, 2000000, 2400000, 2800000]
IPA_INDEPENDENT = [1700000, 2200000, 2600000, 3000000, 3300000]
TIER1_MAX = 500000
TIER2_MAX = 1500000
TIER1_RATE = (22, 100)   # 22%
TIER2_RATE = (35, 100)   # 35%
TIER3_RATE = (47, 100)   # 47%
ASSET_ALLOWANCE = 1000000
ASSET_RATE_NUM, ASSET_RATE_DEN = 564, 10000  # 5.64 / 100
EFC_FLOOR = 0
EFC_CAP = 99999900


def compute_efc(dependency_status, household_size, number_in_college,
                agi_cents, untaxed_income_cents, asset_net_worth_cents) -> int:
    # Step 1: total income.
    total_income = agi_cents + untaxed_income_cents
    # Step 2: income protection allowance; household size capped at five.
    table = IPA_DEPENDENT if dependency_status == "DEPENDENT" else IPA_INDEPENDENT
    idx = max(1, min(household_size, 5)) - 1
    ipa = table[idx]
    # Step 3: available income floored at zero.
    available = max(0, total_income - ipa)
    # Step 4: tiered marginal rates; each tier product rounded half-up to whole
    # cents BEFORE summing (pinned rounding order).
    t1_base = min(available, TIER1_MAX)
    t2_base = min(max(available - TIER1_MAX, 0), TIER2_MAX - TIER1_MAX)
    t3_base = max(available - TIER2_MAX, 0)
    ic = (round_half_up_div(t1_base * TIER1_RATE[0], TIER1_RATE[1])
          + round_half_up_div(t2_base * TIER2_RATE[0], TIER2_RATE[1])
          + round_half_up_div(t3_base * TIER3_RATE[0], TIER3_RATE[1]))
    # Step 5: asset contribution — floor rounding to whole cents.
    if asset_net_worth_cents > ASSET_ALLOWANCE:
        ac = floor_div((asset_net_worth_cents - ASSET_ALLOWANCE) * ASSET_RATE_NUM,
                       ASSET_RATE_DEN)
    else:
        ac = 0
    # Step 6: per-college-member division, integer division rounding half-up.
    efc_raw = round_half_up_div(ic + ac, number_in_college)
    # Step 7: clamp.
    return max(EFC_FLOOR, min(efc_raw, EFC_CAP))


def deterministic_verification_selected(ssn: str, year_code: str, rate) -> bool:
    """sha256(ssn || '-' || year_code) mod 10000 < rate * 10000 (PRD 3.3)."""
    digest = hashlib.sha256(f"{ssn}-{year_code}".encode("utf-8")).hexdigest()
    residue = int(digest, 16) % 10000
    threshold = Decimal(str(rate)) * 10000
    return Decimal(residue) < threshold


# ---------------------------------------------------------------------------
# Pell schedule lookup + enrollment proration (PRD 3.6)
# ---------------------------------------------------------------------------

PRORATION = {
    "FULL_TIME": 100,
    "THREE_QUARTER": 75,
    "HALF_TIME": 50,
    "LESS_THAN_HALF": 0,
}


def pell_offer(pell_schedule, efc_used_cents, enrollment_status) -> int:
    """Inclusive [efc_min, efc_max] lookup; proration floored after multiply."""
    row = None
    for r in pell_schedule:
        if r["efc_min"] <= efc_used_cents <= r["efc_max"]:
            row = r
            break
    if row is None:
        return 0
    pct = PRORATION[enrollment_status]
    return floor_div(row["award_cents"] * pct, 100)


def validate_pell_schedule_shape(rows):
    """Contiguity / coverage gate evaluated when an aid year is OPENED (PRD 3.1).

    Rows must be sorted by efc_min ascending, contiguous with no gaps or
    overlaps, and collectively cover the inclusive range from 0 to 999,999
    (a final row extending past 999,999 satisfies coverage).
    """
    if not isinstance(rows, list) or len(rows) == 0:
        return False
    prev_max = None
    for r in rows:
        if not isinstance(r, dict):
            return False
        efc_min, efc_max = r.get("efc_min"), r.get("efc_max")
        if not _is_int(efc_min) or not _is_int(efc_max) or efc_min > efc_max:
            return False
        if prev_max is None:
            if efc_min != 0:
                return False
        else:
            if efc_min != prev_max + 1:
                return False
        prev_max = efc_max
    return prev_max is not None and prev_max >= 999999


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


# ---------------------------------------------------------------------------
# Stafford caps (PRD 3.6)
# ---------------------------------------------------------------------------

SUB_CAP = {1: 350000, 2: 450000, 3: 550000, 4: 550000, 5: 550000}
UNSUB_CAP_DEPENDENT = {1: 200000, 2: 200000, 3: 200000, 4: 200000, 5: 200000}
UNSUB_CAP_INDEPENDENT = {1: 600000, 2: 600000, 3: 700000, 4: 700000, 5: 700000}


def sub_cap(grade_level, dependency_status) -> int:
    # SUB caps are identical for DEPENDENT and INDEPENDENT at every level.
    return SUB_CAP[grade_level]


def unsub_cap(grade_level, dependency_status) -> int:
    if dependency_status == "INDEPENDENT":
        return UNSUB_CAP_INDEPENDENT[grade_level]
    return UNSUB_CAP_DEPENDENT[grade_level]


# ---------------------------------------------------------------------------
# SAP evaluation (PRD 3.2) — STANDARD / TRANSFER variants
# ---------------------------------------------------------------------------

GPA_FLOOR = 200
PACE_FLOOR_BPS = 6667


def evaluate_sap(student, transfer_credits=0):
    """Returns the new sap_status per the pinned outcome mapping."""
    if transfer_credits and transfer_credits > 0:
        # TRANSFER variant: transfer credits count as both attempted and completed.
        eff_attempted = student["cumulative_attempted_credits"] + transfer_credits
        eff_completed = student["cumulative_completed_credits"] + transfer_credits
    else:
        eff_attempted = student["cumulative_attempted_credits"]
        eff_completed = student["cumulative_completed_credits"]

    qualitative_pass = student["gpa_hundredths"] >= GPA_FLOOR
    if eff_attempted == 0:
        pace_bps = 10000
    else:
        pace_bps = floor_div(eff_completed * 10000, eff_attempted)
    pace_pass = pace_bps >= PACE_FLOOR_BPS
    # Max-timeframe gate reads the as-reported cumulative attempted credits.
    timeframe_pass = not (student["cumulative_attempted_credits"] > student["max_timeframe_credits"])

    all_pass = qualitative_pass and pace_pass and timeframe_pass
    prior = student["sap_status"]
    if all_pass:
        if prior == "SUSPENDED":
            return "SUSPENDED"  # only a director's appeal lifts a suspension
        return "GOOD_STANDING"
    if prior in ("WARNING", "APPEAL_APPROVED", "SUSPENDED"):
        return "SUSPENDED"
    return "WARNING"


# ---------------------------------------------------------------------------
# Disbursement eligibility (PRD 3.7) — five checks in pinned order
# ---------------------------------------------------------------------------

def evaluate_disbursement_eligibility(disb, line, fund, pkg, student, aid_year,
                                      verification_case, package_posted_total):
    """Returns the ordered list of failing codes ([] => ELIGIBILITY_PASSED)."""
    failures = []
    # 1. ENROLLMENT_BELOW_REQUIRED
    category = fund["category"]
    enrollment = student["enrollment_status"]
    if category == "FEDERAL_TITLE_IV":
        if enrollment not in ("FULL_TIME", "THREE_QUARTER", "HALF_TIME"):
            failures.append("ENROLLMENT_BELOW_REQUIRED")
    elif category == "INSTITUTIONAL":
        if enrollment not in ("FULL_TIME", "THREE_QUARTER"):
            failures.append("ENROLLMENT_BELOW_REQUIRED")
    # STATE / EXTERNAL: no enrollment floor.
    # 2. SAP_NOT_SATISFACTORY
    if student["sap_status"] not in ("GOOD_STANDING", "WARNING", "APPEAL_APPROVED"):
        failures.append("SAP_NOT_SATISFACTORY")
    # 3. VERIFICATION_INCOMPLETE (FEDERAL_TITLE_IV only)
    if category == "FEDERAL_TITLE_IV":
        if verification_case is not None and verification_case["status"] not in (
                "COMPLETED_SATISFIED", "WAIVED"):
            failures.append("VERIFICATION_INCOMPLETE")
    # 4. COA_HEADROOM_EXCEEDED
    if (line["disbursed_cents"] + disb["scheduled_cents"] > line["accepted_cents"]
            or package_posted_total + disb["scheduled_cents"] > pkg["coa_used_cents"]):
        failures.append("COA_HEADROOM_EXCEEDED")
    # 5. AID_YEAR_LOCKED
    if aid_year["status"] not in ("OPEN", "PACKAGING_LOCKED"):
        failures.append("AID_YEAR_LOCKED")
    return failures
