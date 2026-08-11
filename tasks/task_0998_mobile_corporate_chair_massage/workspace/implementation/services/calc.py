"""Calculation rules (scaffold 1.3). All monetary values are integer cents.
Percentage-derived amounts use floor; payout lines use round-half-up per line."""
import calendar
import math
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from clock import clock
from db import stores


def floor_pct(base_cents, pct):
    """floor(base * pct) to whole cents; pct given as a JSON number."""
    val = (Decimal(base_cents) * Decimal(str(pct))).quantize(
        Decimal("1"), rounding=ROUND_FLOOR)
    return int(val)


def round_half_up_div(numer, denom):
    val = (Decimal(numer) / Decimal(denom)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    return int(val)


# ---------------------------------------------------------------------------
# travel_fee (variants QUOTED / SETTLED)
# ---------------------------------------------------------------------------
HIGH_VOLUME_SESSION_THRESHOLD = 20
HIGH_VOLUME_DISCOUNT_PCT = Decimal("0.20")


def travel_fee_quoted(distance_miles, region):
    billable = max(0, distance_miles - region["travel_included_miles"])
    return billable * region["base_mileage_rate_cents"]


def completed_claim_count_for(booking_id, therapist_id):
    n = 0
    for claim in stores["slot_claims"].values():
        if claim["booking_id"] != booking_id or claim["status"] != "COMPLETED":
            continue
        chair = stores["chair_slots"].get(claim["chair_slot_id"])
        if chair and chair["therapist_id"] == therapist_id:
            n += 1
    return n


def travel_fee_settled(leg, booking, region):
    billable = max(0, leg["distance_miles"] - region["travel_included_miles"])
    base = billable * region["base_mileage_rate_cents"]
    s = completed_claim_count_for(booking["id"], leg["therapist_id"])
    discount = 0
    if s >= HIGH_VOLUME_SESSION_THRESHOLD:
        discount = int((Decimal(base) * HIGH_VOLUME_DISCOUNT_PCT).quantize(
            Decimal("1"), rounding=ROUND_FLOOR))
    return base - discount


# ---------------------------------------------------------------------------
# payout_earnings: per-line round-half-up THEN integer sum
# ---------------------------------------------------------------------------
def payout_earning_amount(booking, therapist):
    rate = therapist["per_hour_rate_cents"]
    minutes = booking["slot_minutes"]
    total = 0
    for claim in stores["slot_claims"].values():
        if claim["booking_id"] != booking["id"] or claim["status"] != "COMPLETED":
            continue
        chair = stores["chair_slots"].get(claim["chair_slot_id"])
        if chair and chair["therapist_id"] == therapist["id"]:
            total += round_half_up_div(minutes * rate, 60)
    return total


# ---------------------------------------------------------------------------
# cancellation_fee: tiered by floored whole hours until event start
# ---------------------------------------------------------------------------
def event_start(booking):
    d = date.fromisoformat(booking["event_date"])
    return datetime.combine(d, time(0, 0), tzinfo=timezone.utc) + timedelta(
        minutes=booking["window_start_minutes"])


def cancellation_fee(booking):
    delta_seconds = (event_start(booking) - clock.now()).total_seconds()
    hours = math.floor(delta_seconds / 3600)
    committed = booking["booked_chair_minutes"] * booking["per_minute_rate_cents"]
    if hours < 24:
        return floor_pct(committed, "0.50")
    if hours < 72:
        return floor_pct(committed, "0.25")
    if hours < 168:
        return floor_pct(committed, "0.10")
    return 0


# ---------------------------------------------------------------------------
# satisfaction_credit: tiered on average rating across COMPLETED-claim surveys
# ---------------------------------------------------------------------------
def booking_ratings(booking_id):
    ratings = []
    claims = {c["id"]: c for c in stores["slot_claims"].values()
              if c["booking_id"] == booking_id and c["status"] == "COMPLETED"}
    for survey in stores["satisfaction_surveys"].values():
        if survey["slot_claim_id"] in claims:
            ratings.append(survey["rating"])
    return ratings


def avg_x100(ratings):
    if not ratings:
        return None
    return round_half_up_div(100 * sum(ratings), len(ratings))


def satisfaction_credit(booking_id, subtotal_cents):
    ratings = booking_ratings(booking_id)
    if not ratings:
        return 0
    avg = avg_x100(ratings)
    if avg < 200:
        return floor_pct(subtotal_cents, "0.25")
    if avg < 300:
        return floor_pct(subtotal_cents, "0.10")
    return 0


# ---------------------------------------------------------------------------
# therapist rating_avg_x100: rolling average of last 10 surveys, half-up
# ---------------------------------------------------------------------------
def recompute_therapist_rating(therapist_id):
    therapist = stores["therapists"].get(therapist_id)
    if therapist is None:
        return
    entries = []
    for survey in stores["satisfaction_surveys"].values():
        claim = stores["slot_claims"].get(survey["slot_claim_id"])
        if not claim:
            continue
        chair = stores["chair_slots"].get(claim["chair_slot_id"])
        if chair and chair["therapist_id"] == therapist_id:
            entries.append(survey)
    entries.sort(key=lambda s: (s["created_at"], s["_seq"]))
    last10 = entries[-10:]
    if not last10:
        avg = 0
    else:
        avg = round_half_up_div(100 * sum(s["rating"] for s in last10), len(last10))
    therapist["rating_avg_x100"] = avg


# ---------------------------------------------------------------------------
# next_occurrence_date
# ---------------------------------------------------------------------------
def _clamp_day(year, month, day):
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last))


def _next_month(year, month):
    month += 1
    if month > 12:
        month = 1
        year += 1
    return year, month


def next_occurrence_from_clock(program, today):
    """Smallest schedule date strictly after `today` (a date object)."""
    created = datetime.fromisoformat(program["created_at"].replace("Z", "+00:00")).date()
    cadence = program["cadence"]
    if cadence == "WEEKLY":
        anchor_wd = created.weekday()
        delta = (anchor_wd - today.weekday()) % 7
        if delta == 0:
            delta = 7
        return today + timedelta(days=delta)
    if cadence == "BIWEEKLY":
        rem = (today - created).days % 14
        delta = (14 - rem) % 14
        if delta == 0:
            delta = 14
        return today + timedelta(days=delta)
    # MONTHLY: same calendar day-of-month, clamped; strictly after today
    anchor_day = created.day
    y, m = today.year, today.month
    cand = _clamp_day(y, m, anchor_day)
    if cand <= today:
        y, m = _next_month(y, m)
        cand = _clamp_day(y, m, anchor_day)
    return cand


def cadence_successor(event_date_str, cadence):
    """One cadence step after a materialized occurrence's event_date."""
    d = date.fromisoformat(event_date_str)
    if cadence == "WEEKLY":
        return d + timedelta(days=7)
    if cadence == "BIWEEKLY":
        return d + timedelta(days=14)
    y, m = _next_month(d.year, d.month)
    return _clamp_day(y, m, d.day)
