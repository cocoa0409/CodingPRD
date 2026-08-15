"""Calculation rules from scaffold Table 3."""
from decimal import Decimal, ROUND_HALF_UP

# medical_necessity_score constants
SEV_CAP = 12
INT_CAP = 12
SEV_W = 5
INT_W = 5
COMORB_CAP = 3
COMORB_W_MEDICARE = 4
COMORB_W_OTHER = 2
SCORE_CAP = 100
MET_THRESHOLD = 60

MEDICARE_FAMILY = {"MEDICARE", "MANAGED_MEDICARE"}

# two_midnight_benchmark
TWO_MIDNIGHT_THRESHOLD = 2

# escalation thresholds
T1_DAYS = 2
T2_DAYS = 4
T3_DAYS = 6


def medical_necessity_score(severity, intensity, comorbidity, plan_class):
    sev = min(severity, SEV_CAP) * SEV_W
    inten = min(intensity, INT_CAP) * INT_W
    cw = COMORB_W_MEDICARE if plan_class in MEDICARE_FAMILY else COMORB_W_OTHER
    com = min(comorbidity, COMORB_CAP) * cw
    score = min(SCORE_CAP, sev + inten + com)
    return score


def midnight_count(start_dt, end_dt):
    """Calendar-date difference in whole days; times of day do not matter."""
    return (end_dt.date() - start_dt.date()).days


def benchmark_met(count):
    return "MET" if count >= TWO_MIDNIGHT_THRESHOLD else "NOT_MET"


def cc44_rebill_estimate(service_lines):
    """Per-line round_half_up to whole cents, then exact integer sum. Pinned order."""
    total = 0
    for line in service_lines:
        raw = Decimal(line["charge_cents"]) * Decimal(line["rate_milli"]) / Decimal(1000)
        rounded = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        total += rounded
    return total


def tier_of(count):
    if count >= T3_DAYS:
        return 3
    if count >= T2_DAYS:
        return 2
    if count >= T1_DAYS:
        return 1
    return 0
