"""Calculation rules (SCAFFOLD §1.3 / PRD §3.3, §3.6, §3.9).

All money is integer cents; every division floors unless stated otherwise.
The engagement score is the single exception: round HALF-UP (implemented
exactly with fractions), clamped to [0, 100].
"""
from datetime import timedelta
from fractions import Fraction

from db import store

# refund_amount constants
COOLING_OFF_DAYS = 14
PER_SESSION_COOLING_OFF_CENTS = 7500
ADMIN_FEE_CENTS = 5000

# client_engagement_score constants
WINDOW_DAYS = 28
SESSIONS_EXPECTED_28 = 8

# reschedule_policy_gate constant
RESCHEDULE_FREE_HOURS = 24

# enrollment payment dimension
GRACE_DAYS = 14

# session buffer
BUFFER_MINUTES = 15

# pause limit
PAUSE_LIMIT = 2


# ---------------------------------------------------------------- installments

def installment_amounts(price_cents, count):
    """Waterfall split: base = floor(price / count); remainder lands entirely
    on the LAST installment (SCAFFOLD installment_schedule / PRD §3.3)."""
    base = price_cents // count
    remainder = price_cents - base * count
    amounts = [base] * count
    amounts[count - 1] = base + remainder
    return amounts


def paid_cents(enrollment_id):
    return sum(i["amount_cents"] for i in store.installments.values()
               if i["enrollment_id"] == enrollment_id and i["installment_status"] == "PAID")


def refunded_cents(enrollment_id):
    return sum(r["amount_cents"] for r in store.refunds.values()
               if r["enrollment_id"] == enrollment_id and r["refund_status"] == "APPROVED")


def sessions_of(enrollment_id):
    return [s for s in store.sessions.values() if s["enrollment_id"] == enrollment_id]


def sessions_consumed(enrollment_id):
    """Count of Sessions in COMPLETED or NO_SHOW."""
    return sum(1 for s in sessions_of(enrollment_id)
               if s["session_status"] in ("COMPLETED", "NO_SHOW"))


def sessions_remaining(enrollment):
    """sessions_total - consumed - SCHEDULED - FORFEITED (CANCELLED returns credit)."""
    sess = sessions_of(enrollment["id"])
    consumed = sum(1 for s in sess if s["session_status"] in ("COMPLETED", "NO_SHOW"))
    scheduled = sum(1 for s in sess if s["session_status"] == "SCHEDULED")
    forfeited = sum(1 for s in sess if s["session_status"] == "FORFEITED")
    return enrollment["sessions_total"] - consumed - scheduled - forfeited


# --------------------------------------------------------------------- refunds

def pro_rata_session_value(enrollment):
    """Gross pro-rata quote = per-remaining-session value x unconsumed count,
    capped at paid_cents. Uses the enrollment's PINNED price basis
    (sessions_total_price_basis), immune to later tier price edits (PRD §3.3).
    Floor at each division; MEMBERSHIP prorates by time first (SCAFFOLD §1.3).
    """
    tier = store.tiers.get(enrollment["program_tier_id"])
    tier_type = tier["tier_type"] if tier else None
    price = enrollment["sessions_total_price_basis"]
    session_count = enrollment["sessions_total"]
    consumed = sessions_consumed(enrollment["id"])
    remaining = session_count - consumed
    paid = paid_cents(enrollment["id"])

    if tier_type == "SINGLE":
        value_per_remaining = 0
    elif tier_type == "PACKAGE":
        value_per_remaining = price // session_count
    else:  # MEMBERSHIP
        days_total = tier["duration_days"]
        window_close = enrollment["activated_at"] + timedelta(days=days_total)
        days_left = max(0, (window_close - store.clock).days)
        time_prorated = (price * days_left) // days_total
        value_per_remaining = time_prorated // max(1, remaining)
    quote = value_per_remaining * remaining
    return min(quote, paid)


def refund_quote(enrollment):
    """Compute (basis, amount_cents) at filing time (SCAFFOLD refund_amount).
    Boundary: days_elapsed == COOLING_OFF_DAYS (14) exactly -> COOLING_OFF (<=).
    """
    days_elapsed = (store.clock.date() - enrollment["activated_at"].date()).days
    consumed = sessions_consumed(enrollment["id"])
    paid = paid_cents(enrollment["id"])
    if days_elapsed <= COOLING_OFF_DAYS:
        amount = paid - consumed * PER_SESSION_COOLING_OFF_CENTS
        return "COOLING_OFF", amount
    gross = pro_rata_session_value(enrollment)
    amount = min(gross, paid) - ADMIN_FEE_CENTS
    return "PRO_RATA", max(amount, 0)


# ------------------------------------------------------------- engagement score

def _client_engagement_inputs(client_id):
    """(sessions, habits) source rows for a client: sessions of the client's
    enrollments in COMPLETED, and completed check-ins on goals of the client's
    enrollments."""
    enrollment_ids = [e["id"] for e in store.enrollments.values()
                      if e["client_id"] == client_id]
    sessions = [s for s in store.sessions.values()
                if s["enrollment_id"] in enrollment_ids
                and s["session_status"] == "COMPLETED"]
    goal_ids = [g["id"] for g in store.goals.values()
                if g["enrollment_id"] in enrollment_ids]
    checkins = [h for h in store.check_ins.values()
                if h["goal_id"] in goal_ids and h["completed"] is True]
    return sessions, checkins


def engagement_score(client_id, variant="final"):
    """FINAL: window [today-27, today]; denominators 8 sessions / 28 days.
    PROVISIONAL: window anchored at the most recently ACTIVATED enrollment's
    activated_at date (ties: later created_at); days_elapsed capped at 28;
    session denominator = max(1, floor(8 * days_elapsed / 28)); habit
    denominator = days_elapsed. Round half-up, clamp [0, 100] (PRD §3.6).
    """
    today_d = store.clock.date()
    if variant == "provisional":
        activated = [e for e in store.enrollments.values()
                     if e["client_id"] == client_id and e["activated_at"] is not None]
        if activated:
            activated.sort(key=lambda e: (e["activated_at"], e["_created_sort"]),
                           reverse=True)
            anchor = activated[0]["activated_at"].date()
            days_elapsed = min(WINDOW_DAYS, (today_d - anchor).days + 1)
            if days_elapsed < 1:
                days_elapsed = 1
        else:
            days_elapsed = WINDOW_DAYS
        window_open = today_d - timedelta(days=days_elapsed - 1)
        sessions_expected = max(1, (SESSIONS_EXPECTED_28 * days_elapsed) // WINDOW_DAYS)
        habit_denominator = days_elapsed
    else:
        days_elapsed = WINDOW_DAYS
        window_open = today_d - timedelta(days=WINDOW_DAYS - 1)
        sessions_expected = SESSIONS_EXPECTED_28
        habit_denominator = WINDOW_DAYS

    sessions, checkins = _client_engagement_inputs(client_id)
    s_count = sum(1 for s in sessions
                  if window_open <= s["scheduled_start"].date() <= today_d)
    h_count = sum(1 for h in checkins
                  if window_open <= h["check_in_date"] <= today_d)

    score = Fraction(100) * (
        Fraction(3, 5) * Fraction(s_count, sessions_expected)
        + Fraction(2, 5) * Fraction(h_count, habit_denominator)
    )
    # round half-up (score is non-negative): floor(x + 1/2)
    rounded = (2 * score.numerator + score.denominator) // (2 * score.denominator)
    return max(0, min(100, rounded))
