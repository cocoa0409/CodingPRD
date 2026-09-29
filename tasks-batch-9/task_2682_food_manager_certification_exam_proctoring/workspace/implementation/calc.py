"""Deterministic arithmetic: pricing, refunds, timing, scores, risk, occupancy."""
import calendar
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError
from store import store

CENT = Decimal("1")
TWO_PLACES = Decimal("0.01")

UNIT_PRICE_CENTS = {"EXAM_ONLY": Decimal("3600"),
                    "COURSE_PLUS_EXAM": Decimal("8900")}

CERT_ISSUANCE_FEE_CENTS = 1500
LEAD_TIME_MINUTES = 1440
PROCTOR_BUFFER_MINUTES = 15
MAX_ALLOWED_MINUTES = 240
REMOTE_SETUP_MINUTES = 10
CHECKIN_OPENS_MINUTES = 30
CHECKIN_CLOSES_MINUTES = 15
INCIDENT_WINDOW_HOURS = 72
RECERT_WINDOW_DAYS = 180
ROLLING_WINDOW_SIZE = 2
RISK_SUSPENSION_THRESHOLD = Decimal("10.00")
BIOMETRIC_MIN_SCORE = 85

OCCUPYING_SESSION_STATUSES = ("SCHEDULED", "CHECKED_IN", "IN_PROGRESS")
TERMINAL_RISK_STATUSES = ("SUBMITTED", "CLOSED", "INVALIDATED")


def half_up_int(value):
    return int(Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP))


def half_up_2(value):
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def volume_discount_rate(quantity):
    if quantity >= 100:
        return Decimal("0.15")
    if quantity >= 50:
        return Decimal("0.10")
    if quantity >= 20:
        return Decimal("0.05")
    return Decimal("0")


def price_line_items(line_items, surcharge_pct):
    """Per-line, per-component rounding before any summation (PRD 3.3)."""
    total = 0
    for line in line_items:
        quantity = line["quantity"]
        unit = UNIT_PRICE_CENTS[line["bundle_type"]]
        rate = volume_discount_rate(quantity)
        subtotal = half_up_int(unit * Decimal(quantity) * (Decimal("1") - rate))
        surcharge = half_up_int(Decimal(subtotal) * Decimal(surcharge_pct))
        total += subtotal + surcharge
    return total


def restock_fee_rate(gross_credit_cents):
    if gross_credit_cents >= 50000:
        return Decimal("0.05")
    if gross_credit_cents >= 10000:
        return Decimal("0.10")
    return Decimal("0.15")


def void_refund(total_price_cents, refundable_units, quantity_purchased):
    gross = half_up_int(Decimal(total_price_cents) * Decimal(refundable_units)
                        / Decimal(quantity_purchased))
    fee = half_up_int(Decimal(gross) * restock_fee_rate(gross))
    return gross, fee, gross - fee


def truncate_minute(moment):
    return moment.replace(second=0, microsecond=0)


def session_multiplier(accommodation):
    if accommodation is None:
        return Decimal("1.0")
    if accommodation["status"] != "APPROVED":
        return Decimal("1.0")
    granted = accommodation["approved_multiplier"]
    if granted is None:
        return Decimal("1.0")
    return Decimal(granted)


def compute_allowed_minutes(form, accommodation, delivery_mode):
    multiplier = session_multiplier(accommodation)
    translation_extra = 0
    if form["language"] != "EN":
        translation_extra = form["translated_extra_minutes"]
    delivery_extra = REMOTE_SETUP_MINUTES if delivery_mode == "REMOTE" else 0
    uncapped = half_up_int(Decimal(form["base_minutes"]) * multiplier)
    uncapped = uncapped + translation_extra + delivery_extra
    return min(MAX_ALLOWED_MINUTES, uncapped)


def scaled_score(correct, denominator):
    return half_up_int(Decimal(100) * Decimal(correct) / Decimal(denominator))


def add_months(moment, months):
    total = moment.month - 1 + months
    year = moment.year + total // 12
    month = total % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


# --- proctor risk ----------------------------------------------------------

def terminal_population(proctor_id):
    rows = [s for s in store.sessions.values()
            if s["proctor_id"] == proctor_id
            and s["session_status"] in TERMINAL_RISK_STATUSES]
    rows.sort(key=lambda s: (s["scheduled_start_at"], s["created_at"]),
              reverse=True)
    return rows


def substantiated_weight_for_sessions(session_ids):
    total = 0
    for incident in store.incidents.values():
        if incident["exam_session_id"] in session_ids \
                and incident["status"] == "SUBSTANTIATED":
            total += incident["severity_weight"]
    return total


def rolling_window_risk(proctor_id):
    population = terminal_population(proctor_id)[:ROLLING_WINDOW_SIZE]
    ids = set(s["id"] for s in population)
    weight = substantiated_weight_for_sessions(ids)
    return half_up_2(Decimal(weight) * Decimal(10) / Decimal(ROLLING_WINDOW_SIZE))


def lifetime_cumulative_risk(proctor):
    population = terminal_population(proctor["id"])
    if len(population) == 0:
        return Decimal("0.00")
    return half_up_2(Decimal(proctor["substantiated_incident_weight_total"])
                     * Decimal(10) / Decimal(len(population)))


# --- occupancy -------------------------------------------------------------

def proctor_interval_conflict(proctor_id, start_at, end_at, exclude_session_id):
    buffer_delta = timedelta(minutes=PROCTOR_BUFFER_MINUTES)
    new_start = truncate_minute(start_at)
    new_end = truncate_minute(end_at)
    for other in store.sessions.values():
        if other["id"] == exclude_session_id:
            continue
        if other["proctor_id"] != proctor_id:
            continue
        if other["session_status"] not in OCCUPYING_SESSION_STATUSES:
            continue
        if other["proctoring_status"] != "ASSIGNED":
            continue
        other_start = truncate_minute(other["scheduled_start_at"])
        other_end = truncate_minute(other["scheduled_end_at"])
        if new_start < other_end + buffer_delta \
                and other_start < new_end + buffer_delta:
            return True
    return False


def site_overlap_count(site_id, start_at, end_at, exclude_session_id):
    new_start = truncate_minute(start_at)
    new_end = truncate_minute(end_at)
    count = 0
    for other in store.sessions.values():
        if other["id"] == exclude_session_id:
            continue
        if other["testing_site_id"] != site_id:
            continue
        if other["session_status"] not in OCCUPYING_SESSION_STATUSES:
            continue
        other_start = truncate_minute(other["scheduled_start_at"])
        other_end = truncate_minute(other["scheduled_end_at"])
        if new_start < other_end and other_start < new_end:
            count += 1
    return count


def check_occupancy(proctor_id, site_id, start_at, end_at, exclude_session_id):
    """Priority 47 then 48 (PRD 2.10)."""
    if proctor_id is not None and proctor_interval_conflict(
            proctor_id, start_at, end_at, exclude_session_id):
        raise ApiError("ERR_PROCTOR_INTERVAL_CONFLICT",
                       "the proctor's interval is not free")
    if site_id is not None:
        site = store.testing_sites.get(site_id)
        if site is not None:
            occupied = site_overlap_count(site_id, start_at, end_at,
                                          exclude_session_id)
            if occupied >= site["seat_count"]:
                raise ApiError("ERR_SITE_SEAT_CAPACITY_EXCEEDED",
                               "the testing site has no free seat")
