"""Pure calculations (PRD sections 2.8, 2.9, 2.11, 3.2, 3.5, 3.6, 3.8).

Every monetary figure is an integer number of cents. Ratios that feed a later
step are carried as exact rationals (fractions.Fraction) and are never rounded
to a decimal approximation before use.
"""
import calendar
import re
from datetime import datetime, timedelta, timezone
from fractions import Fraction

import db

# ------------------------------------------------------------ rounding

def round_half_up(value):
    """Round an exact rational half up (away from zero) to a whole cent."""
    if not isinstance(value, Fraction):
        value = Fraction(value)
    num, den = value.numerator, value.denominator
    if num >= 0:
        return (2 * num + den) // (2 * den)
    return -((2 * (-num) + den) // (2 * den))


# ------------------------------------------------- address normalization

_NON_ALNUM_UPPER = re.compile(r"[^A-Z0-9]")


def _norm_component(text):
    return _NON_ALNUM_UPPER.sub("", (text or "").upper())


def address_hash(address_line1, unit_designator, city, state_code, postal_code):
    """Uppercase each component, delete every character that is not a letter or
    digit, and join the five results with a vertical bar. The postal component
    uses only the first five characters of postal_code."""
    postal5 = (postal_code or "")[:5]
    parts = [
        _norm_component(address_line1),
        _norm_component(unit_designator if unit_designator else ""),
        _norm_component(city),
        _norm_component(state_code),
        _norm_component(postal5),
    ]
    return "|".join(parts)


def identity_key(full_name, date_of_birth, last4_ssn):
    stripped = re.sub(r"[^A-Za-z0-9]", "", full_name or "").upper()
    return "%s|%s|%s" % (stripped, date_of_birth, last4_ssn)


# ------------------------------------------------------- income threshold

FPG_BASE_CENTS = 1560000
FPG_INCREMENT_CENTS = 552000
MULTIPLIER_TRIBAL = Fraction(3, 2)
MULTIPLIER_STANDARD = Fraction(27, 20)
INCOME_CEILING_CENTS = 6000000
INCOME_FLOOR_CENTS = 2106000


def fpg_income_threshold(household_size, tribal_lands_flag):
    guideline = FPG_BASE_CENTS + FPG_INCREMENT_CENTS * (household_size - 1)
    multiplier = MULTIPLIER_TRIBAL if tribal_lands_flag else MULTIPLIER_STANDARD
    raw = round_half_up(Fraction(guideline) * multiplier)
    if raw > INCOME_CEILING_CENTS:
        raw = INCOME_CEILING_CENTS
    if raw < INCOME_FLOOR_CENTS:
        raw = INCOME_FLOOR_CENTS
    return raw


def annualize_three_month(last_3mo_income_cents):
    """The trailing-quarter annualization rounds exactly once."""
    return round_half_up(Fraction(last_3mo_income_cents or 0) * 4)


# ------------------------------------------------- certification validity

CERTIFICATION_VALID_DAYS = 90
MAX_DOCUMENTATION_RESUBMISSIONS = 2


def certification_expiry(confirmed_at):
    """confirmed_at plus 90 days at the identical time of day in UTC."""
    return confirmed_at + timedelta(days=CERTIFICATION_VALID_DAYS)


# ------------------------------------------------------------- windows

NON_USAGE_IDLE_DAYS = 30
CURE_WINDOW_DAYS = 15
RECERT_CYCLE_DAYS = 365
RECERT_NOTICE_LEAD_DAYS = 60
RECERT_RESPONSE_DAYS = 60
PORT_FREEZE_DAYS = 60
DEVICE_REISSUE_FREEZE_DAYS = 395
APPEAL_WINDOW_DAYS = 30


def port_freeze_until(benefit_start_date):
    return db.day_start(benefit_start_date, PORT_FREEZE_DAYS)


def recert_due_date(anchor):
    return db.day_start(anchor, RECERT_CYCLE_DAYS)


def cure_deadline(flagged_at):
    return db.day_end(flagged_at, CURE_WINDOW_DAYS)


def recert_response_deadline(notice_at):
    return db.day_end(notice_at, RECERT_RESPONSE_DAYS)


def appeal_deadline(de_enrolled_at):
    return db.day_end(de_enrolled_at, APPEAL_WINDOW_DAYS)


def recert_notice_opens_at(due_date):
    return due_date - timedelta(days=RECERT_NOTICE_LEAD_DAYS)


def device_freeze_end(last_device_issued_at):
    return last_device_issued_at + timedelta(days=DEVICE_REISSUE_FREEZE_DAYS)


def idle_days(now, anchor):
    return db.whole_days_between(now, anchor)


# --------------------------------------------------------- support money

BASE_MONTHLY_RATE_CENTS = 925
TRIBAL_ENHANCEMENT_CENTS = 2500
BROADBAND_ENHANCEMENT_CENTS = 275
BROADBAND_SERVICE_TYPES = ("BROADBAND", "BUNDLED")


def monthly_rate_cents(tribal_lands_flag, service_type):
    rate = BASE_MONTHLY_RATE_CENTS
    if tribal_lands_flag:
        rate += TRIBAL_ENHANCEMENT_CENTS
    if service_type in BROADBAND_SERVICE_TYPES:
        rate += BROADBAND_ENHANCEMENT_CENTS
    return rate


def support_line_cents(rate, support_days, days_in_month):
    """Each line is rounded to an integer first; the integer lines are then
    summed. Summing exact rationals and rounding once is incorrect."""
    return round_half_up(Fraction(rate * support_days, days_in_month))


def month_bounds(service_month):
    year = int(service_month[0:4])
    month = int(service_month[5:7])
    days = calendar.monthrange(year, month)[1]
    first = datetime(year, month, 1, tzinfo=timezone.utc).date()
    last = datetime(year, month, days, tzinfo=timezone.utc).date()
    return first, last, days


# --------------------------------------------------------- audit scoring

RISK_DUPLICATE_ADDRESS = 40
RISK_NON_USAGE = 30
RISK_RECERT = 20
RISK_PER_DEVICE = 10
RISK_DEVICE_CAP = 2
RISK_TRANSFER = 15
RISK_CEILING = 100


def audit_risk_score(address_status, usage_status, recert_status,
                     device_issuance_count, transfer_count):
    total = 0
    if address_status == "DUPLICATE_FLAGGED":
        total += RISK_DUPLICATE_ADDRESS
    if usage_status in ("NON_USAGE_FLAGGED", "CURE_EXPIRED"):
        total += RISK_NON_USAGE
    if recert_status in ("NON_RESPONSIVE", "RESPONDED_INELIGIBLE"):
        total += RISK_RECERT
    total += RISK_PER_DEVICE * min(device_issuance_count or 0, RISK_DEVICE_CAP)
    if (transfer_count or 0) >= 1:
        total += RISK_TRANSFER
    return min(total, RISK_CEILING)


# ------------------------------------------------------- recoupment math

SAMPLE_SIZE_MIN = 1
SAMPLE_SIZE_MAX = 50
PENALTY_TIER_LOW_CUTOFF = 500
PENALTY_TIER_HIGH_CUTOFF = 1500
PENALTY_RATE_LOW = Fraction(5, 100)
PENALTY_RATE_MID = Fraction(10, 100)
PENALTY_RATE_HIGH = Fraction(20, 100)


def penalty_rate_for(extrapolated_cents):
    if extrapolated_cents < PENALTY_TIER_LOW_CUTOFF:
        return PENALTY_RATE_LOW
    if extrapolated_cents < PENALTY_TIER_HIGH_CUTOFF:
        return PENALTY_RATE_MID
    return PENALTY_RATE_HIGH


def audit_recoupment(final_amount_cents, audit_sample_count, failed_sample_count):
    """Returns (recoupment_amount_cents, penalty_cents, net_payable_cents)."""
    final_amount_cents = final_amount_cents or 0
    if not failed_sample_count or not audit_sample_count:
        return 0, 0, final_amount_cents
    rate = Fraction(failed_sample_count, audit_sample_count)
    extrapolated = round_half_up(Fraction(final_amount_cents) * rate)
    penalty = round_half_up(Fraction(extrapolated) * penalty_rate_for(extrapolated))
    recoupment = extrapolated + penalty
    return recoupment, penalty, final_amount_cents - recoupment


DEVICE_TIER_ORDER = ("BASIC", "STANDARD", "SMART")


def device_tier_rank(model_tier):
    try:
        return DEVICE_TIER_ORDER.index(model_tier)
    except ValueError:
        return len(DEVICE_TIER_ORDER)
