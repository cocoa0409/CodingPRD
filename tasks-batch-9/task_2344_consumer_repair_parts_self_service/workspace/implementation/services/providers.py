"""provider_compliance_score and training-credit ledger helpers."""
from fractions import Fraction

import db
from serializers import required_cert_count
from util import as_number, round_half_up

VARIANTS = ("ROLLING_ATTESTED", "LIVE_RECOMPUTE")

CASE_STATES = {
    "ROLLING_ATTESTED": ("CREDIT_ISSUED", "REJECTED"),
    "LIVE_RECOMPUTE": ("REQUESTED", "RECEIVED", "ANALYSIS_COMPLETE", "CREDIT_ISSUED", "REJECTED"),
}

TIER_STRICTNESS = {
    "TIER_1_UNRESTRICTED": 1,
    "TIER_2_SAFETY": 2,
    "TIER_3_STANDARD": 3,
}

CERT_CREDIT_COST = 2


def stricter_tier(left, right):
    if left is None:
        return right
    if right is None:
        return left
    return left if TIER_STRICTNESS[left] >= TIER_STRICTNESS[right] else right


def band_for_score(score):
    if score >= 85:
        return "TIER_1_UNRESTRICTED"
    if score >= 65:
        return "TIER_2_SAFETY"
    return "TIER_3_STANDARD"


def provider_orders(provider_id):
    return [o for o in db.ordered(db.db.orders.all()) if o.get("provider_id") == provider_id]


def _counted_certs(provider_id, variant):
    at = db.now()
    total = 0
    for cert in db.db.certs.all():
        if cert["provider_id"] != provider_id or cert["status"] != "ACTIVE":
            continue
        if variant == "ROLLING_ATTESTED":
            if not (cert["valid_from"] <= at <= cert["valid_until"]):
                continue
        total += 1
    return total


def compute_score(provider, variant="ROLLING_ATTESTED"):
    required = required_cert_count(provider)
    counted = _counted_certs(provider["id"], variant)
    if required <= 0:
        coverage = Fraction(1)
    else:
        coverage = min(Fraction(1), Fraction(counted, required))

    order_ids = set(o["id"] for o in provider_orders(provider["id"]))
    line_ids = set(
        l["id"] for l in db.db.lines.all() if l["order_id"] in order_ids
    )

    allowed_states = CASE_STATES[variant]
    breach_count = 0
    for case in db.db.cases.all():
        if case.get("root_cause_code") != "PROVIDER_INSTALL_ERROR":
            continue
        if case["order_line_id"] not in line_ids:
            continue
        if case["status"] not in allowed_states:
            continue
        breach_count += 1

    attempted = 0
    failed = 0
    for line in db.db.lines.all():
        if line["order_id"] not in order_ids:
            continue
        if line.get("calibration_attempt_count", 0) < 1:
            continue
        attempted += 1
        if line["calibration_status"] in ("CALIBRATION_FAILED", "CALIBRATION_ESCALATED"):
            failed += 1
    failure_ratio = Fraction(0) if attempted == 0 else Fraction(failed, attempted)

    raw = (
        Fraction(45, 100) * coverage
        + Fraction(35, 100) * (Fraction(1) - min(Fraction(1), Fraction(breach_count, 5)))
        + Fraction(20, 100) * (Fraction(1) - failure_ratio)
    )
    score = round_half_up(100 * raw)
    return {
        "variant": variant,
        "cert_coverage_ratio": as_number(coverage),
        "breach_count": breach_count,
        "calibration_failure_ratio": as_number(failure_ratio),
        "score": score,
        "access_tier_band": band_for_score(score),
    }
