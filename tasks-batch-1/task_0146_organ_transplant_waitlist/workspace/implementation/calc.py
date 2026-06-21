"""Calculation rules (PRD §2.9, §3.3, §3.5; SCAFFOLD §1.3).

All rounding is round-half-up (away from zero at the .5 midpoint).
"""
import math
from decimal import Decimal, ROUND_HALF_UP

SECONDS_PER_DAY = 86400
SECONDS_PER_HOUR = 3600
OFFER_RESPONSE_WINDOW_HOURS = 1


def round_half_up(value, places=0):
    q = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)


def round_half_up_int(value):
    return int(round_half_up(value, 0))


# ----------------------------------------------------------------------------
# Clinical scoring (PRD §3.3)
# ----------------------------------------------------------------------------
def meld_na_score(bilirubin, inr, creatinine, sodium, on_dialysis):
    """MELD-Na for adults. Returns (raw_score, allocation_score)."""
    bili = max(bilirubin, 1.0)
    inr_c = max(inr, 1.0)
    if on_dialysis:
        creat = 4.0
    else:
        creat = min(max(creatinine, 1.0), 4.0)
    meld_i = 0.957 * math.log(creat) + 0.378 * math.log(bili) + 1.120 * math.log(inr_c) + 0.643
    meld_i = round_half_up_int(meld_i * 10)
    if meld_i > 11:
        na = min(max(sodium, 125.0), 137.0)
        raw = meld_i + 1.32 * (137 - na) - (0.033 * meld_i * (137 - na))
    else:
        raw = float(meld_i)
    clamped = min(max(raw, 6), 40)
    allocation = int(round_half_up(clamped, 0))
    return raw, allocation


def peld_score(bilirubin, inr, albumin, growth_failure):
    """PELD for pediatrics. Returns (raw_score, allocation_score)."""
    bili = max(bilirubin, 1.0)
    inr_c = max(inr, 1.0)
    alb = albumin  # albumin is NOT floored
    gf = 0.667 if growth_failure else 0.0
    raw = 0.480 * math.log(bili) + 1.857 * math.log(inr_c) - 0.687 * math.log(alb) + gf + 0.436
    raw = round_half_up_int(raw * 10)
    clamped = min(max(raw, 6), 40)
    allocation = int(round_half_up(clamped, 0))
    return float(raw), allocation


# ----------------------------------------------------------------------------
# Allocation priority points (PRD §3.5)
# ----------------------------------------------------------------------------
def allocation_priority_points(meld_peld, waiting_days, hla_mismatch, is_pediatric,
                               out_of_region, broader_sharing):
    """Per-component round-half-up, then sum. Under BROADER_SHARING only,
    out-of-region candidates' summed points are x0.9 and re-rounded."""
    med_pts = round_half_up_int(meld_peld * 2.5)
    wait_pts = round_half_up_int(min(waiting_days, 365) / 365 * 10)
    hla_pts = round_half_up_int((6 - hla_mismatch) * 1.5)
    ped_pts = 8 if is_pediatric else 0
    total = med_pts + wait_pts + hla_pts + ped_pts
    if broader_sharing and out_of_region:
        total = round_half_up_int(total * 0.9)
    return total


# ----------------------------------------------------------------------------
# HLA mismatch (PRD §3.5)
# ----------------------------------------------------------------------------
def hla_mismatch_count(donor, candidate):
    """Number of the donor's six HLA-A/B/DR antigens not shared with the
    candidate (0..6)."""
    cand_antigens = set(candidate["hla_a"]) | set(candidate["hla_b"]) | set(candidate["hla_dr"])
    donor_antigens = list(donor["hla_a"]) + list(donor["hla_b"]) + list(donor["hla_dr"])
    return sum(1 for a in donor_antigens if a not in cand_antigens)


# ----------------------------------------------------------------------------
# ABO compatibility (PRD §3.5)
# ----------------------------------------------------------------------------
ABO_COMPAT = {
    "O": {"O", "A", "B", "AB"},
    "A": {"A", "AB"},
    "B": {"B", "AB"},
    "AB": {"AB"},
}


def abo_compatible(donor_blood, recipient_blood):
    return recipient_blood in ABO_COMPAT.get(donor_blood, set())


# ----------------------------------------------------------------------------
# Size compatibility (PRD §3.5)
# ----------------------------------------------------------------------------
def size_compatible(donor_weight, candidate_weight, organ_type):
    ratio = donor_weight / candidate_weight
    if organ_type in ("HEART", "LUNG"):
        lo, hi = 0.80, 1.20
    else:  # LIVER, KIDNEY
        lo, hi = 0.70, 1.50
    return ratio >= lo and ratio <= hi


# ----------------------------------------------------------------------------
# Cold ischemia actual (PRD §3.9)
# ----------------------------------------------------------------------------
def cold_ischemia_hours_actual(recovered_at, transplanted_at):
    seconds = (transplanted_at - recovered_at).total_seconds()
    return float(round_half_up(seconds / SECONDS_PER_HOUR, 2))


# ----------------------------------------------------------------------------
# HTTP-presentable numeric (so 6.50 vs 6.5 doesn't matter as JSON number)
# ----------------------------------------------------------------------------
def to_number(dec_or_float):
    return float(dec_or_float)
