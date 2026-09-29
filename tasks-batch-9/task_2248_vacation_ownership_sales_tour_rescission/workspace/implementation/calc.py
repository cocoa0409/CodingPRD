"""Calculation rules (SCAFFOLD 1.3 / PRD 2.6, 2.7, 3.x).

All money is whole cents held as int; every rate-derived monetary result is
rounded half-up.  Rates derived from counts are stored to 4 decimal places.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, localcontext

# ---------------------------------------------------------------- constants
RESCHEDULE_LIMIT = 2
MIN_BOOKING_LEAD_MINUTES = 60
NO_SHOW_MIN_SAMPLE = 4
NO_SHOW_SUSPEND_THRESHOLD = Decimal("0.5000")
NO_SHOW_PENALTY_WEIGHT = 30
REP_RESET_MINUTES = 15

SEVERITY_PENALTY_POINTS = {"MINOR": 5, "MAJOR": 15, "EGREGIOUS": 40}
DISCLOSURE_GAP_WEIGHT = 10
COMPLIANCE_CLEAR_FLOOR = 70
REQUIRED_DISCLOSURE_CODES = (
    "RESCISSION_RIGHTS",
    "PUBLIC_OFFERING_STATEMENT_DELIVERY",
    "NOT_AN_INVESTMENT",
)
DISCLOSURE_CODES = REQUIRED_DISCLOSURE_CODES + ("MAINTENANCE_FEE_ESCALATION",)
CLAIM_CODES = (
    "GUARANTEED_RESALE",
    "GUARANTEED_APPRECIATION",
    "RENTAL_INCOME_PROMISE",
    "UNLIMITED_AVAILABILITY",
)
COMPLIANCE_STRIKE_SUSPEND_THRESHOLD = 2
AUTO_RETRAINING_MODULE_COUNT = 4
RETRAINING_CYCLE_LIMIT = 3
RETRAINING_REASONS = (
    "CANCELLATION_RATE_BREACH",
    "PROHIBITED_CLAIM_POINTS",
    "DISCLOSURE_GAP",
)

EQUITY_RECOGNITION_RATE = Decimal("0.55")
ANNUAL_DEPRECIATION_RATE = Decimal("0.075")
LOYALTY_RATE = Decimal("0.025")
LOYALTY_YEARS_CAP = Decimal("10")
TRANSFER_FEE_CENTS = 49900

DOC_STAMP_RATE = Decimal("0.0035")
CLOSING_FLAT_FEE_CENTS = 129900

GIFT_RECAPTURE_CAP_RATE = Decimal("0.05")
DOC_PREP_FEE_CENTS = 19900

CANCELLATION_WINDOW_DAYS = 90
CANCELLATION_MIN_SAMPLE = 2
CANCELLATION_RATE_THRESHOLD = Decimal("0.5000")

MIN_UNDERWRITABLE_FICO = 620
CHANNEL_CODES = (
    "OFF_PROPERTY_CONTACT",
    "IN_HOUSE_REFERRAL",
    "MINI_VAC_PACKAGE",
    "TELEMARKETING",
    "OWNER_UPGRADE",
)
AFFINITY_CHANNEL_CODES = ("IN_HOUSE_REFERRAL", "OWNER_UPGRADE")

OCCUPYING_BOOKING_STATUSES = ("SCHEDULED", "RESCHEDULE_PENDING", "CHECKED_IN", "TOURED")
GIFT_ACCRUING_STATUSES = ("CHECKED_IN", "TOURED")
AVAILABLE_REP_STATUSES = ("ACTIVE", "ON_TOUR")
OWNER_FULFILLMENT_STATUSES = ("FUNDED", "RECORDED", "DOCS_DELIVERED", "TRADED_IN")

# state_code -> (days, anchor_mode, roll, refund_policy)
STATE_RESCISSION_RULES = {
    "FL": (10, "LATER_OF_EXECUTION_OR_POS", True, "STATUTORY_FULL"),
    "NV": (5, "EXECUTION", False, "STATUTORY_FULL"),
    "CA": (7, "LATER_OF_EXECUTION_OR_POS", True, "STATUTORY_FULL"),
    "TX": (6, "EXECUTION", False, "CONTRACTUAL_NET_OF_GIFT"),
    "HI": (7, "POS_DELIVERY", True, "CONTRACTUAL_NET_OF_GIFT"),
}
STATE_CODES = ("FL", "NV", "CA", "TX", "HI")

FEDERAL_HOLIDAYS = frozenset(
    [
        date(2026, 7, 3),
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
        date(2027, 1, 1),
        date(2028, 7, 4),
        date(2028, 9, 4),
        date(2028, 11, 23),
        date(2028, 12, 25),
        date(2029, 1, 1),
        date(2029, 7, 4),
        date(2029, 9, 3),
        date(2029, 11, 22),
        date(2029, 12, 25),
    ]
)

POS_WINDOW_BEFORE = timedelta(days=30)
POS_WINDOW_AFTER = timedelta(days=3)

SECONDS_PER_YEAR = Decimal(365 * 86400)


# ------------------------------------------------------------- arithmetic
def rhu(value, places=0):
    """Round half-up to `places` decimals, returning a Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def rate4(numerator, denominator):
    """Count-derived rate to 4 decimals; explicit empty-set branch, no division."""
    if denominator == 0:
        return Decimal("0.0000")
    return rhu(Decimal(numerator) / Decimal(denominator), 4)


def as_rate(value):
    """Serialise a 4-decimal rate as a JSON number."""
    return float(value)


def to_decimal_rate(value):
    return Decimal(str(value))


# ------------------------------------------------ channel_no_show_rate
def channel_no_show_denominator(channel):
    return channel["toured_count"] + channel["no_show_count"]


def channel_no_show_rate(channel):
    return rate4(channel["no_show_count"], channel_no_show_denominator(channel))


# ------------------------------------------ tour_qualification_evaluation
def income_points(household_income_cents):
    if household_income_cents >= 15000000:
        return 45
    if household_income_cents >= 10000000:
        return 35
    if household_income_cents >= 7500000:
        return 25
    if household_income_cents >= 5000000:
        return 15
    return 0


def qualification_score(prospect, channel):
    """Return (score, penalty_points).  Hard minimums are checked by the caller."""
    points = income_points(prospect["household_income_cents"])
    points += 25 if prospect["primary_age"] >= channel["min_age"] else 0
    points += 20 if prospect["marital_status"] == "MARRIED" else 0
    points += 25 if prospect["is_existing_owner"] else 0
    points += 20 if channel["channel_code"] in AFFINITY_CHANNEL_CODES else 0
    # Step order pinned: cap at 100 BEFORE subtracting the no-show penalty.
    capped = min(100, points)
    penalty = rhu_int(
        to_decimal_rate(channel["historical_no_show_rate"])
        * Decimal(NO_SHOW_PENALTY_WEIGHT)
    )
    return max(0, capped - penalty), penalty


def meets_hard_criteria(prospect, channel):
    if prospect["primary_age"] < channel["min_age"]:
        return False
    if prospect["household_income_cents"] < channel["min_household_income_cents"]:
        return False
    if channel["requires_married_household"] and prospect["marital_status"] != "MARRIED":
        return False
    return True


# --------------------------------------- gallery_capacity_overlap_check
def gallery_overlap_count(bookings, gallery, candidate_start, candidate_end, exclude_id=None):
    """Half-open geometry [start, end) with the buffer extending only each END."""
    buffer_delta = timedelta(minutes=gallery["buffer_minutes"])
    count = 0
    for booking in bookings:
        if booking["gallery_id"] != gallery["id"]:
            continue
        if booking["status"] not in OCCUPYING_BOOKING_STATUSES:
            continue
        if exclude_id is not None and booking["id"] == exclude_id:
            continue
        if (
            booking["scheduled_start_utc"] < candidate_end + buffer_delta
            and candidate_start < booking["scheduled_end_utc"] + buffer_delta
        ):
            count += 1
    return count


# ------------------------------------- representative_window_exclusivity
def rep_window_available(presentations, rep_id, candidate_start, candidate_end):
    """Closed geometry with a symmetric mandatory reset gap; touching collides."""
    gap = timedelta(minutes=REP_RESET_MINUTES)
    for presentation in presentations:
        if presentation["rep_id"] != rep_id:
            continue
        busy_start = presentation["window_start_utc"]
        busy_end = presentation["window_end_utc"]
        if candidate_start <= busy_end + gap and busy_start <= candidate_end + gap:
            return False
    return True


# ----------------------------------------- presentation_compliance_score
def compliance_score(prohibited_claim_points, required_count, ack_count):
    gap_points = DISCLOSURE_GAP_WEIGHT * (required_count - ack_count)
    return max(0, 100 - prohibited_claim_points - gap_points)


def auto_flag(score, findings):
    if score < COMPLIANCE_CLEAR_FLOOR:
        return True
    for finding in findings:
        if finding["severity"] == "EGREGIOUS":
            return True
    return False


# ------------------------------------------------- trade_in_equity_credit
def years_held(funded_at, now):
    seconds = Decimal(str((now - funded_at).total_seconds()))
    return rhu(seconds / SECONDS_PER_YEAR, 4)


def trade_in_equity_credit(prior_price_cents, held_years):
    price = Decimal(prior_price_cents)
    # Rounding order pinned: each component rounded to a whole cent first.
    c1 = rhu_int(price * EQUITY_RECOGNITION_RATE)
    c2 = -rhu_int(price * ANNUAL_DEPRECIATION_RATE * held_years)
    c3 = rhu_int(price * LOYALTY_RATE * min(held_years, LOYALTY_YEARS_CAP))
    c4 = -TRANSFER_FEE_CENTS
    return max(0, c1 + c2 + c3 + c4)


# ----------------------------------------------------- agreement_financials
def down_payment_rate(total_due_cents):
    if total_due_cents >= 5000000:
        return Decimal("0.12")
    if total_due_cents >= 2000000:
        return Decimal("0.10")
    return Decimal("0.08")


def agreement_financials(purchase_price_cents, trade_in_credit_cents, down_payment_cents):
    """Returns a dict of the six pinned steps, or raises via the caller's check.

    The caller must compare down_payment_cents against down_payment_required_cents
    and raise ERR_DOWN_PAYMENT_INSUFFICIENT before consuming the later steps.
    """
    total_due = max(0, purchase_price_cents - trade_in_credit_cents)
    required = rhu_int(Decimal(total_due) * down_payment_rate(total_due))
    base_financed = max(0, total_due - down_payment_cents)
    if base_financed == 0:
        doc_stamp = 0
        closing_fee = 0
        financed = 0
    else:
        doc_stamp = rhu_int(Decimal(base_financed) * DOC_STAMP_RATE)
        closing_fee = CLOSING_FLAT_FEE_CENTS + doc_stamp
        financed = base_financed + closing_fee
    return {
        "total_due_cents": total_due,
        "down_payment_required_cents": required,
        "base_financed_cents": base_financed,
        "doc_stamp_cents": doc_stamp,
        "closing_cost_fee_cents": closing_fee,
        "financed_amount_cents": financed,
        "escrow_collected_cents": down_payment_cents,
    }


# --------------------------------------------------- rescission_deadline
def rescission_deadline(state_code, executed_at, pos_delivered_at):
    days, anchor_mode, roll, refund_policy = STATE_RESCISSION_RULES[state_code]
    if anchor_mode == "EXECUTION":
        anchor = executed_at
    elif anchor_mode == "POS_DELIVERY":
        anchor = pos_delivered_at
    else:
        anchor = executed_at if executed_at >= pos_delivered_at else pos_delivered_at
    day = anchor.astimezone(timezone.utc).date() + timedelta(days=days)
    rolled = False
    if roll:
        while day.weekday() >= 5 or day in FEDERAL_HOLIDAYS:
            day = day + timedelta(days=1)
            rolled = True
    deadline = datetime(
        day.year, day.month, day.day, 23, 59, 59, 999000, tzinfo=timezone.utc
    )
    return {
        "statutory_rescission_days": days,
        "anchor_mode": anchor_mode,
        "rescission_anchor_utc": anchor,
        "rescission_deadline_utc": deadline,
        "business_day_rolled": rolled,
        "refund_policy": refund_policy,
    }


# ------------------------------------------------------ refund_settlement
def refund_settlement(refund_policy, escrow_collected_cents, gift_value_cents):
    base = escrow_collected_cents
    if refund_policy == "STATUTORY_FULL":
        gift_recapture = 0
        doc_fee = 0
    else:
        gift_recapture = min(
            gift_value_cents, rhu_int(Decimal(base) * GIFT_RECAPTURE_CAP_RATE)
        )
        doc_fee = min(DOC_PREP_FEE_CENTS, base - gift_recapture)
    return {
        "base_refund_cents": base,
        "gift_recapture_cents": gift_recapture,
        "doc_fee_retained_cents": doc_fee,
        "disbursed_amount_cents": base - gift_recapture - doc_fee,
    }


# --------------------------------------------------- financing_underwriting
def fico_tier(applicant_fico):
    if applicant_fico >= 740:
        return 1099, Decimal("0.95")
    if applicant_fico >= 680:
        return 1399, Decimal("0.90")
    if applicant_fico >= 620:
        return 1699, Decimal("0.80")
    return None, None


def monthly_payment_cents(approved_amount_cents, apr_bps, term_months):
    with localcontext() as ctx:
        ctx.prec = 60
        rate = Decimal(apr_bps) / Decimal(10000) / Decimal(12)
        one = Decimal(1)
        denominator = one - (one + rate) ** (-term_months)
        value = Decimal(approved_amount_cents) * rate / denominator
    return rhu_int(value)


def financing_underwriting(application, agreement):
    apr_bps, max_ltv = fico_tier(application["applicant_fico"])
    ltv_cap = rhu_int(
        Decimal(agreement["total_due_cents"] + agreement["closing_cost_fee_cents"])
        * max_ltv
    )
    approved = min(application["requested_amount_cents"], ltv_cap)
    payment = monthly_payment_cents(approved, apr_bps, application["term_months"])
    return {
        "apr_bps": apr_bps,
        "max_ltv_rate": float(max_ltv),
        "ltv_cap_cents": ltv_cap,
        "approved_amount_cents": approved,
        "monthly_payment_cents": payment,
    }


# ----------------------------------------- representative_cancellation_rate
def cancellation_analysis(agreements, rep_id, now):
    window_start = now - timedelta(days=CANCELLATION_WINDOW_DAYS)
    executed = []
    for agreement in agreements:
        if agreement["rep_id"] != rep_id:
            continue
        executed_at = agreement["executed_at"]
        if executed_at is None:
            continue
        if window_start <= executed_at <= now:
            executed.append(agreement)
    executed_count = len(executed)
    rescinded_count = sum(
        1 for a in executed if a["rescission_status"] == "RESCINDED"
    )
    rate = rate4(rescinded_count, executed_count)
    required = (
        executed_count >= CANCELLATION_MIN_SAMPLE and rate >= CANCELLATION_RATE_THRESHOLD
    )
    return {
        "window_start_utc": window_start,
        "window_end_utc": now,
        "executed_count": executed_count,
        "rescinded_count": rescinded_count,
        "cancellation_rate": rate,
        "min_sample": CANCELLATION_MIN_SAMPLE,
        "retraining_required": required,
    }
