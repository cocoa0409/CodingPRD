"""The domain calculations of PRD §2.7 and §3, with their exact constants."""

from datetime import timedelta

from util import D, add_days, floor_int, minutes_to_hhmm, round_half_up

# --- effective calling window -------------------------------------------------
FEDERAL_FLOOR_MINUTES = 480  # 08:00 recipient local
FEDERAL_CEILING_MINUTES = 1260  # 21:00 recipient local
NON_WRITTEN_CONSENT_EXTENSION_MINUTES = 60
SMS_NARROWING_MINUTES = 30
MINUTES_PER_DAY = 1440

# --- abandonment --------------------------------------------------------------
MIN_MEASURED_LIVE_ANSWERS = 2
REGULATORY_ABANDONMENT_CEILING_PCT = D("3.00")
ABANDON_CONNECT_SECONDS = 2

# --- rolling compliance -------------------------------------------------------
ROLLING_WINDOW_DAYS = 7

# --- pacing -------------------------------------------------------------------
PACING_HEADROOM_CAP_PCT = D("2.00")
PACING_GAIN_PER_PCT = D("0.25")

# --- complaint risk scoring ---------------------------------------------------
SOURCE_WEIGHT = {
    "DIRECT": D("1.0"),
    "STATE_AG": D("1.25"),
    "FTC": D("1.5"),
    "LITIGATION": D("2.0"),
}
VIOLATION_WEIGHT = {
    "NO_CONSENT": D("1.5"),
    "DNC_VIOLATION": D("1.25"),
    "TIME_WINDOW": D("1.0"),
    "ABANDONMENT": D("0.75"),
    "RECORDING_CONSENT": D("1.1"),
}
SOURCE_POINTS = D("10")
VIOLATION_POINTS = D("8")
PROVISIONAL_ATTEMPT_POINTS = D("2")
ADJUDICATED_ATTEMPT_POINTS = D("4")
ATTEMPT_POINT_CAP = 5
LITIGATION_BONUS = D("15")

MEDIUM_THRESHOLD = D("20")
HIGH_THRESHOLD = D("40")
CRITICAL_THRESHOLD = D("55")

STATUTORY_BASE_CENTS = 50000
WILLFUL_MULTIPLIER = 3

# --- temporal windows ---------------------------------------------------------
PROPAGATION_BUSINESS_DAYS = 10
SCRUB_VALIDITY_DAYS = 31
LIST_REFRESH_MAX_DAYS = 31
RND_VALIDITY_DAYS = 31
CONTACT_COOLDOWN_MINUTES = 30
PATTERN_WINDOW_DAYS = 30


# =============================================================================
# recipient-local projection (§3.8)
# =============================================================================


def recipient_local_minutes(clock_now, utc_offset_minutes):
    utc_minutes = clock_now.hour * 60 + clock_now.minute
    return ((utc_minutes + utc_offset_minutes) % MINUTES_PER_DAY + MINUTES_PER_DAY) % MINUTES_PER_DAY


def recipient_local_time(minutes):
    return minutes_to_hhmm(minutes)


def recipient_local_date(clock_now, utc_offset_minutes):
    return (clock_now + timedelta(minutes=utc_offset_minutes)).date()


# =============================================================================
# effective calling window (§3.8)
# =============================================================================


def effective_calling_window(base_start, base_end, consent_type, channel):
    consent_ext = 0 if consent_type == "EXPRESS_WRITTEN" else NON_WRITTEN_CONSENT_EXTENSION_MINUTES
    channel_shift = SMS_NARROWING_MINUTES if channel == "SMS" else 0
    effective_start = max(base_start + consent_ext, FEDERAL_FLOOR_MINUTES + channel_shift)
    effective_end = min(base_end - channel_shift, FEDERAL_CEILING_MINUTES)
    return effective_start, effective_end


def window_permits(local_minutes, start, end):
    return start <= local_minutes < end


# =============================================================================
# abandonment rates (§3.8)
# =============================================================================


def regulatory_rate(live, aband):
    if live == 0:
        return D("0.00")
    return round_half_up(D(100) * D(aband) / D(live), 2)


def internal_rate(live, machine, aband):
    denom = live + machine
    if denom == 0:
        return D("0.00")
    return round_half_up(D(100) * D(aband) / D(denom), 2)


def is_breach(live, rate, limit_pct):
    return live >= MIN_MEASURED_LIVE_ANSWERS and D(rate) > D(limit_pct)


# =============================================================================
# rolling compliance rate (§3.8) — round each day, then round the mean
# =============================================================================


def rolling_compliance_rate(day_samples):
    """``day_samples`` is an iterable of (live, aband) pairs for the window."""
    daily = []
    for live, aband in day_samples:
        if live > 0:
            daily.append(round_half_up(D(100) * D(aband) / D(live), 2))
    if not daily:
        return D("0.00")
    total = sum(daily, D(0))
    return round_half_up(total / D(len(daily)), 2)


# =============================================================================
# dialer pacing lines (§3.6)
# =============================================================================


def dialer_pacing_lines(mode, agents_available, abandonment_limit_pct, regulatory_rate_pct):
    headroom = D(abandonment_limit_pct) - D(regulatory_rate_pct)
    clamped = max(D("0.00"), min(headroom, PACING_HEADROOM_CAP_PCT))
    mult = D(1) + clamped * PACING_GAIN_PER_PCT
    max_lines = max(agents_available, floor_int(D(agents_available) * mult))
    if mode == "PREVIEW":
        max_lines = agents_available
    return int(max_lines)


# =============================================================================
# complaint risk scoring (§3.9)
# =============================================================================


def _base_terms(source, violation_type):
    return SOURCE_WEIGHT[source] * SOURCE_POINTS + VIOLATION_WEIGHT[violation_type] * VIOLATION_POINTS


def provisional_risk_score(source, violation_type, attempts_charged):
    contribution = D(min(attempts_charged, ATTEMPT_POINT_CAP)) * PROVISIONAL_ATTEMPT_POINTS
    return round_half_up(_base_terms(source, violation_type) + contribution, 2)


def adjudicated_risk_score(source, violation_type, verified_attempt_count, litigation_flag):
    total = _base_terms(source, violation_type)
    total = total + D(verified_attempt_count) * ADJUDICATED_ATTEMPT_POINTS
    if litigation_flag:
        total = total + LITIGATION_BONUS
    return round_half_up(total, 2)


def risk_tier(peak):
    if peak is None:
        return "LOW"
    peak = D(peak)
    if peak >= CRITICAL_THRESHOLD:
        return "CRITICAL"
    if peak >= HIGH_THRESHOLD:
        return "HIGH"
    if peak >= MEDIUM_THRESHOLD:
        return "MEDIUM"
    return "LOW"


def statutory_exposure(verified_attempt_count, willful):
    multiplier = WILLFUL_MULTIPLIER if willful else 1
    return int(verified_attempt_count) * STATUTORY_BASE_CENTS * multiplier


# =============================================================================
# propagation deadline (§3.3)
# =============================================================================


def propagation_deadline(received_at, holiday_dates):
    holidays = set(holiday_dates or [])
    cursor = received_at
    remaining = PROPAGATION_BUSINESS_DAYS
    while remaining > 0:
        cursor = add_days(cursor, 1)
        day = cursor.date()
        if day.weekday() < 5 and day.isoformat() not in holidays:
            remaining -= 1
    return cursor
