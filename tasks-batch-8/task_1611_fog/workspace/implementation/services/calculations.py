"""Calculation rules (scaffold §1.3 / PRD §3)."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from db import STORE

# --- risk_classification ---
CUISINE_POINTS = {"LOW_GREASE": 10, "MEDIUM_GREASE": 20, "HIGH_GREASE": 30}
RISK_CLASSES = ("LOW_GREASE", "MEDIUM_GREASE", "HIGH_GREASE")
FREQ_TABLE = {"HIGH": 90, "MEDIUM": 180, "LOW": 365}

# --- interceptor_required_capacity ---
MIN_CAPACITY_GAL = 50
SEAT_GAL = 2
FRYER_GAL = 15
CHARBROILER_GAL = 40
RETENTION_MINUTES = 30
CUISINE_ADDER_GAL = {"LOW_GREASE": 0, "MEDIUM_GREASE": 25, "HIGH_GREASE": 50}

# --- inspection_score ---
SEVERITY_DEDUCTION = {"MINOR": 3, "MAJOR": 8, "CRITICAL": 20}
SEVERITY_RANK = {"MINOR": 1, "MAJOR": 2, "CRITICAL": 3}
PASS_THRESHOLD = 70

# --- citation_fine ---
CITATION_FINE = {"MINOR": 10000, "MAJOR": 50000, "CRITICAL": 250000}
CURE_DAYS = {"MINOR": 30, "MAJOR": 14, "CRITICAL": 3}

# --- disposal_tolerance ---
DISPOSAL_TOLERANCE = 0.05

# --- campaign window buffer ---
CAMPAIGN_ZONE_BUFFER = timedelta(days=14)


def risk_classification(seating_capacity, fryer_count, has_charbroiler, cuisine_profile):
    """risk_score at one decimal place; risk_class from the exact score."""
    capacity = min(Decimal(40), Decimal(seating_capacity) / Decimal(10))
    equipment = min(Decimal(30), Decimal(fryer_count * 10 + (10 if has_charbroiler else 0)))
    cuisine = Decimal(CUISINE_POINTS[cuisine_profile])
    score = (capacity + equipment + cuisine).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if score >= 70:
        rclass = "HIGH"
    elif score >= 40:
        rclass = "MEDIUM"
    else:
        rclass = "LOW"
    return float(score), rclass


def provisional_capacity(est):
    total = (
        est["seating_capacity"] * SEAT_GAL
        + est["fryer_count"] * FRYER_GAL
        + (CHARBROILER_GAL if est["has_charbroiler"] else 0)
        + CUISINE_ADDER_GAL[est["cuisine_profile"]]
    )
    return max(MIN_CAPACITY_GAL, math.ceil(total))


def measured_capacity(measured_flow_gpm):
    req = Decimal(str(measured_flow_gpm)) * Decimal(RETENTION_MINUTES)
    return int(req.to_integral_value(rounding=ROUND_CEILING))


def final_sizing(interceptor):
    """(required_min_capacity_gal, sizing_method) fixed at approval."""
    provisional = interceptor["provisional_required_gal"]
    gpm = interceptor["measured_flow_gpm"]
    if gpm is None:
        return provisional, "PROVISIONAL"
    measured = measured_capacity(gpm)
    required = max(provisional, measured)
    method = "MEASURED" if measured > provisional else "PROVISIONAL"
    return required, method


def inspection_score(items):
    score = max(0, 100 - sum(SEVERITY_DEDUCTION[i["severity"]] for i in items))
    return score, score >= PASS_THRESHOLD


def highest_severity(items):
    return max(items, key=lambda i: SEVERITY_RANK[i["severity"]])["severity"]


def pumping_frequency_days(est):
    override = est["variance_override_frequency_days"]
    if override is not None:
        return override
    return FREQ_TABLE[est["risk_class"]]


def pumping_overdue(est, current):
    """Forward-looking variant: now > baseline + pumping_frequency_days."""
    baseline = est["last_verified_pump_at"] or est["created_at"]
    return current > baseline + timedelta(days=pumping_frequency_days(est))


def missed_pump_windows(est, current):
    """Chronological variant: count fully elapsed half-open windows anchored at
    created_at containing no VERIFIED manifest pump_date."""
    freq = timedelta(days=pumping_frequency_days(est))
    created = est["created_at"]
    verified = [
        m["pump_date"]
        for m in STORE["manifests"].values()
        if m["establishment_id"] == est["id"] and m["status"] == "VERIFIED"
    ]
    count = 0
    k = 1
    while created + freq * k <= current:
        w_start = created + freq * (k - 1)
        w_end = created + freq * k
        if not any(w_start <= pd < w_end for pd in verified):
            count += 1
        k += 1
    return count


def open_violation_count(est_id):
    return sum(
        1
        for v in STORE["violations"].values()
        if v["establishment_id"] == est_id and v["status"] in ("NOTICED", "CITATION")
    )


def compute_posture(est, current):
    """compliance_posture: SUSPENDED > DELINQUENT > WATCH > COMPLIANT."""
    est_id = est["id"]
    violations = [v for v in STORE["violations"].values() if v["establishment_id"] == est_id]
    if any(v["status"] == "CITATION" for v in violations):
        return "SUSPENDED"
    if pumping_overdue(est, current):
        return "DELINQUENT"
    if any(v["status"] == "NOTICED" for v in violations):
        return "WATCH"
    return "COMPLIANT"


def apportion_shares(total_cents, contributions):
    """cost_share_apportionment: round each share half-up first, then assign the
    remainder to the largest weight (tie -> earliest Establishment.created_at,
    then earliest in array)."""
    shares = []
    for c in contributions:
        s = (Decimal(total_cents) * Decimal(c["weight_percent"]) / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        shares.append(int(s))
    remainder = total_cents - sum(shares)
    if remainder != 0 and contributions:
        best = 0
        for idx in range(1, len(contributions)):
            cand = contributions[idx]
            cur = contributions[best]
            if cand["weight_percent"] > cur["weight_percent"]:
                best = idx
            elif cand["weight_percent"] == cur["weight_percent"]:
                cand_est = STORE["establishments"][cand["establishment_id"]]
                cur_est = STORE["establishments"][cur["establishment_id"]]
                if (cand_est["created_at"], cand_est["_seq"]) < (cur_est["created_at"], cur_est["_seq"]):
                    best = idx
        shares[best] += remainder
    return shares


def disposal_exceeds_tolerance(disposed_volume_gal, pumped_volume_gal):
    """Floating-point ratio; reject only when ratio is strictly > 0.05."""
    ratio = abs(disposed_volume_gal - pumped_volume_gal) / pumped_volume_gal
    return ratio > DISPOSAL_TOLERANCE


def campaign_remaining_budget(campaign):
    spent = sum(
        e["cost_cents"]
        for e in STORE["outreach_events"].values()
        if e["campaign_id"] == campaign["id"] and e["status"] == "RECORDED"
    )
    return campaign["budget_cents"] - spent
