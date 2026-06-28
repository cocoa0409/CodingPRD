"""Calculation engine (scaffold §1.3, PRD §3.4 / §3.9 / §3.10).

All amounts are integer cents. Rounding everywhere is round half up. Line
duties round per line, then are summed (round-per-line-then-sum is pinned).
"""
from helpers import round_half_up_bps

# ---- duty rate constants ----
DUTY_RATE_BPS_APPAREL = 1650      # chapters 61, 62
DUTY_RATE_BPS_MACHINERY = 250     # chapters 84, 85
DUTY_RATE_BPS_GENERAL = 500       # any other chapter
FTA_ELIGIBLE_ORIGINS = {"MX", "CA"}

# ---- entry-charge constants ----
MPF_RATE_BPS = 35
MPF_MIN_CENTS = 3215
MPF_MAX_CENTS = 62333
HMF_RATE_BPS = 13
EXCISE_TAX_BPS = 200

# ---- ISF cutoff ----
ISF_CUTOFF_HOURS = 24


def duty_rate_for_hts(hts_code):
    """Rate in basis points selected by the first two digits (tariff chapter)."""
    chapter = hts_code[0:2]
    if chapter in ("61", "62"):
        return DUTY_RATE_BPS_APPAREL
    if chapter in ("84", "85"):
        return DUTY_RATE_BPS_MACHINERY
    return DUTY_RATE_BPS_GENERAL


def compute_line_dutiable_value(line):
    """dutiable_value_cents = customs_value_cents + assists_cents."""
    return line["customs_value_cents"] + line["assists_cents"]


def compute_line_duty_provisional(line):
    """Provisional: USMCA claim trusted unconditionally (duty 0 for any USMCA line)."""
    base = round_half_up_bps(line["dutiable_value_cents"], duty_rate_for_hts(line["hts_code"]))
    if line["preference_claim"] == "USMCA":
        return 0
    return base


def compute_line_duty_final(line, country_of_origin):
    """Final: USMCA zero-duty applies only if country in FTA_ELIGIBLE_ORIGINS.

    Returns (line_duty_cents, preference_verified).
    """
    base = round_half_up_bps(line["dutiable_value_cents"], duty_rate_for_hts(line["hts_code"]))
    if line["preference_claim"] == "USMCA":
        if country_of_origin in FTA_ELIGIBLE_ORIGINS:
            return 0, True
        return base, False
    # No preference claim: base duty, preference_verified stays false.
    return base, False


def compute_entry_charges(lines, entry_type, variant):
    """Assemble the entry grand total in the pinned six-step order.

    `lines` already carry the correct line_duty_cents for the active variant.
    For the MPF waiver test:
      provisional -> every line claims USMCA (preference_claim == USMCA)
      final       -> every line preference_verified == True
    For the tax test:
      any line pga_flag == FDA -> excise tax applies (uses the line's current
      pga_flag, which is the same field in both variants).
    Returns the grand total in integer cents.
    """
    # 1) total dutiable value
    total_dutiable_value = sum(l["dutiable_value_cents"] for l in lines)

    # 2) total duty: sum of per-line (already-rounded) line_duty_cents
    total_duty = sum(l["line_duty_cents"] for l in lines)

    # 3) MPF ad valorem with floor & ceiling, waived when every line has a
    #    verified preference for the active variant.
    if variant == "provisional":
        all_verified = bool(lines) and all(l["preference_claim"] == "USMCA" for l in lines)
    else:
        all_verified = bool(lines) and all(l.get("preference_verified") is True for l in lines)
    if all_verified:
        mpf = 0
    else:
        mpf_raw = round_half_up_bps(total_dutiable_value, MPF_RATE_BPS)
        mpf = min(MPF_MAX_CENTS, max(MPF_MIN_CENTS, mpf_raw))

    # 4) HMF for every entry whose entry_type != FTZ_06, no cap.
    if entry_type == "FTZ_06":
        hmf = 0
    else:
        hmf = round_half_up_bps(total_dutiable_value, HMF_RATE_BPS)

    # 5) Tax when any line pga_flag == FDA.
    if any(l["pga_flag"] == "FDA" for l in lines):
        tax = round_half_up_bps(total_dutiable_value, EXCISE_TAX_BPS)
    else:
        tax = 0

    # 6) grand total
    return total_duty + mpf + hmf + tax


def compute_psc_adjustment(lines, corrected_value_delta_cents):
    """Signed duty adjustment on a granted PSC/PROTEST.

    If every line preference_verified == True, the value change is duty-free
    under USMCA -> 0. Otherwise apply the general rate to the signed delta with
    sign preserved (negative delta -> refund).
    """
    if lines and all(l.get("preference_verified") is True for l in lines):
        return 0
    return _round_half_up_signed(corrected_value_delta_cents, DUTY_RATE_BPS_GENERAL)


def _round_half_up_signed(value_cents, rate_bps):
    """round_half_up of a possibly-negative value, preserving sign.

    round_half_up_bps uses Decimal ROUND_HALF_UP, which for negatives rounds
    toward larger magnitude (away from zero); the formula multiplies a signed
    delta so the symmetric magnitude behavior is what "round half up to integer
    cents; sign preserved (negative delta -> refund)" intends.
    """
    if value_cents >= 0:
        return round_half_up_bps(value_cents, rate_bps)
    return -round_half_up_bps(-value_cents, rate_bps)
