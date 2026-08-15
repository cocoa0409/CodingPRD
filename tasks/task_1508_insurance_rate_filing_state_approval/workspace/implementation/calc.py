"""Calculation rules (scaffold §1.3). All money in integer cents via Decimal;
percentages stored at 4dp ROUND_HALF_UP; balance_factor at 8dp ROUND_HALF_UP.
Intermediate values remain unrounded until the final stored result.
"""
from decimal import Decimal, ROUND_HALF_UP

from timeutil import parse_date
from datetime import timedelta

FULL_CREDIBILITY_EXPOSURE = Decimal(1082)
TARGET_LOSS_RATIO = Decimal("0.68")
LOSS_DEVELOPMENT_FACTOR = Decimal("1.12")
MIN_WAVE_GAP_DAYS = 7

_Q4 = Decimal("0.0001")
_Q8 = Decimal("0.00000001")
_Q0 = Decimal("1")


def round4(value):
    return value.quantize(_Q4, rounding=ROUND_HALF_UP)


def round8(value):
    return value.quantize(_Q8, rounding=ROUND_HALF_UP)


def round_cents(value):
    """Round half up to a whole cent (integer)."""
    return int(value.quantize(_Q0, rounding=ROUND_HALF_UP))


def compute_indication(
    variant,
    earned_premium_cents,
    incurred_loss_cents,
    paid_loss_cents,
    exposure_units,
    trend_factor,
    countrywide_change_pct,
):
    """indicated_rate_change: both variants computed at creation.

    Returns (credibility_z, chosen_result_4dp, alternate_result_4dp).
    """
    earned = Decimal(earned_premium_cents)
    incurred = Decimal(incurred_loss_cents)
    paid = Decimal(paid_loss_cents)
    ratio = Decimal(exposure_units) / FULL_CREDIBILITY_EXPOSURE
    credibility_z = min(Decimal(1), ratio.sqrt())

    ultimate_loss = incurred * LOSS_DEVELOPMENT_FACTOR
    experience_indication = ultimate_loss / (earned * TARGET_LOSS_RATIO) - 1
    countrywide_trended = countrywide_change_pct * (1 + trend_factor)
    incurred_variant = (
        credibility_z * experience_indication
        + (1 - credibility_z) * countrywide_trended
    )
    paid_variant = (paid / earned) / TARGET_LOSS_RATIO - 1

    if variant == "INCURRED_CREDIBILITY":
        chosen, alternate = incurred_variant, paid_variant
    else:
        chosen, alternate = paid_variant, incurred_variant
    return credibility_z, round4(chosen), round4(alternate)


def resolve_actual_effective_date(profile, proposed_effective_date, approval_date):
    """effective_date_resolution. approval_date is a date object."""
    proposed = parse_date(proposed_effective_date)
    if profile["filing_method"] == "PRIOR_APPROVAL":
        pushed = approval_date + timedelta(days=profile["min_effective_lead_days"])
        return max(proposed, pushed).isoformat()
    # FILE_AND_USE / USE_AND_FILE: exactly the proposed date
    return proposed.isoformat()


def compute_deemer_date(profile, submitted_dt):
    """deemer_date: date(submitted_at) + deemer_days, PRIOR_APPROVAL with
    deemer_days > 0 only; else None. Returns a YYYY-MM-DD string."""
    if profile["filing_method"] != "PRIOR_APPROVAL" or profile["deemer_days"] <= 0:
        return None
    return (submitted_dt.date() + timedelta(days=profile["deemer_days"])).isoformat()


def rerate_policy(approved_change_pct, cap_pct, class_rel_factor, current_premium_cents):
    """renewal_re_rate. Returns (raw_change_pct, raw_new, was_capped, capped).

    Rounding order is pinned: raw_change_pct rounded to 4dp first, every
    premium rounded to whole cents before any book-level aggregation.
    Capping triggers only on strict inequality.
    """
    raw_change_pct = round4(approved_change_pct * class_rel_factor)
    raw_new = round_cents(Decimal(current_premium_cents) * (1 + raw_change_pct))
    if raw_change_pct > cap_pct:
        capped = round_cents(Decimal(current_premium_cents) * (1 + cap_pct))
        was_capped = True
    elif raw_change_pct < -cap_pct:
        capped = round_cents(Decimal(current_premium_cents) * (1 - cap_pct))
        was_capped = True
    else:
        capped = raw_new
        was_capped = False
    return raw_change_pct, raw_new, was_capped, capped


def balance_wave(rated):
    """wave_balance_factor over the RATED set.

    rated: list of (policy, capped_premium). Mutates each policy's
    final_premium_cents. Returns (balance_factor|None, target, final_delta).
    After remainder allocation, sum(final - baseline) == target exactly.
    """
    if not rated:
        return None, 0, 0
    approved_change_pct = rated[0][0]["_approved_change_pct"]
    sum_baseline = sum(p["baseline_premium_cents"] for p, _ in rated)
    target = round_cents(approved_change_pct * Decimal(sum_baseline))
    capped_book_total = sum(capped for _, capped in rated)
    if capped_book_total != 0:
        balance_factor = round8(
            (Decimal(sum_baseline) + Decimal(target)) / Decimal(capped_book_total)
        )
    else:
        # Degenerate guard (all premiums capped to zero); unreachable in
        # practice since cap_pct <= max_single_change_pct keeps totals > 0.
        balance_factor = Decimal("1.00000000")
    for policy, capped in rated:
        policy["final_premium_cents"] = round_cents(Decimal(capped) * balance_factor)
    realized = sum(p["final_premium_cents"] - p["baseline_premium_cents"] for p, _ in rated)
    residual = target - realized
    if residual != 0:
        # Allocate the whole signed residual to the largest baseline;
        # ties break to the earliest created.
        anchor = min(
            rated,
            key=lambda pc: (-pc[0]["baseline_premium_cents"], pc[0]["created_at"], pc[0]["_seq"]),
        )[0]
        anchor["final_premium_cents"] += residual
    final_delta = sum(p["final_premium_cents"] - p["baseline_premium_cents"] for p, _ in rated)
    return balance_factor, target, final_delta


def wave_gap_ok(existing_windows, new_start, new_end):
    """wave_window_gap: strict separation by more than MIN_WAVE_GAP_DAYS.
    Exactly MIN_WAVE_GAP_DAYS is a violation; MIN_WAVE_GAP_DAYS + 1 is allowed.
    Windows are inclusive on both ends.
    """
    gap = timedelta(days=MIN_WAVE_GAP_DAYS)
    for start, end in existing_windows:
        if new_start > end + gap or start > new_end + gap:
            continue
        return False
    return True
