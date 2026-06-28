"""Calculation rules (PRD §3, SCAFFOLD §1.3).

All monetary amounts are integer cents; weights are integer grams. Fractional
results are rounded half-up (PRD §2.8). Floors discard the fractional part
toward zero.
"""
from .common import round_half_up, parse_iso

NO_SHOW_SUSPEND_THRESHOLD = 3
DME_WINDOW_DAYS = 30


def sliding_scale_fee(tiers, household_income_cents, standard_rate_cents):
    """sliding_scale_fee (PRD §3.3).

    `tiers` is every SlidingScaleTier of the consult's practice. Select those
    whose income_ceiling_cents >= household_income_cents. If none qualify, the
    discount is 0 (full rate). Otherwise pick the tightest matching bracket:
    smallest income_ceiling_cents; tie-break by lowest discount_pct, then
    earliest created_at. Apply: standard_rate * (100 - discount_pct) / 100,
    rounded half-up to whole cents.
    """
    candidates = [
        t for t in tiers
        if t["income_ceiling_cents"] >= household_income_cents
    ]
    if not candidates:
        discount_pct = 0
    else:
        tier = min(
            candidates,
            key=lambda t: (t["income_ceiling_cents"], t["discount_pct"],
                           t["created_at"], t["_seq"]),
        )
        discount_pct = tier["discount_pct"]
    fee_cents = round_half_up(standard_rate_cents * (100 - discount_pct), 100)
    return fee_cents


def reimbursement_amount(superbill, aca_preventive_enabled):
    """reimbursement_amount (PRD §3.9).

    ACA-preventive branch (is_aca_preventive AND practice.aca_preventive_enabled):
      full allowed amount reimbursed; patient_responsibility = 0.
    Standard cost-share branch:
      deductible_applied = min(allowed, deductible_remaining)
      after_deductible = allowed - deductible_applied
      coinsurance = round_half_up(after_deductible * coinsurance_pct / 100)
      patient_responsibility = deductible_applied + coinsurance
      reimbursed = allowed - patient_responsibility
    Returns (reimbursed_amount_cents, patient_responsibility_cents).
    """
    allowed = superbill["allowed_amount_cents"]
    if superbill["is_aca_preventive"] and aca_preventive_enabled:
        reimbursed = allowed
        patient_responsibility = 0
    else:
        deductible_applied = min(allowed, superbill["deductible_remaining_cents"])
        after_deductible = allowed - deductible_applied
        coinsurance = round_half_up(
            after_deductible * superbill["coinsurance_pct"], 100
        )
        patient_responsibility = deductible_applied + coinsurance
        reimbursed = allowed - patient_responsibility
    return reimbursed, patient_responsibility


def weighted_feed_rollup(feeds, target_daily_transfer_grams):
    """weighted_feed_rollup (PRD §3.8).

    total = sum of per-feed transfers (post - pre); each transfer is integer.
    avg = 0 when no feeds, else round_half_up(total / count) — rounded ONCE
    after summing, not per-feed. meets_target = total >= target.
    Returns (total_transfer_grams, avg_transfer_grams, meets_target).
    """
    per_feed = [
        f["post_feed_weight_grams"] - f["pre_feed_weight_grams"] for f in feeds
    ]
    total = sum(per_feed)
    if len(feeds) == 0:
        avg = 0
    else:
        avg = round_half_up(total, len(feeds))
    meets_target = total >= target_daily_transfer_grams
    return total, avg, meets_target


def dme_qualified(consult_status, pump_type, requested_utc_iso, infant_dob_iso):
    """dme_qualification_window (PRD §3.10).

    If parent consult not COMPLETED -> false.
    HOSPITAL_GRADE -> true.
    STANDARD_ELECTRIC -> age_days = floor((requested_utc - infant_dob) / 86400s);
      qualified = age_days <= DME_WINDOW_DAYS (inclusive: 30 qualifies, 31 not).
    """
    if consult_status != "COMPLETED":
        return False
    if pump_type == "HOSPITAL_GRADE":
        return True
    # STANDARD_ELECTRIC
    requested = parse_iso(requested_utc_iso)
    dob = parse_iso(infant_dob_iso)
    elapsed_seconds = (requested - dob).total_seconds()
    # floor toward zero of seconds / 86400
    age_days = int(elapsed_seconds // 86400)
    return age_days <= DME_WINDOW_DAYS
