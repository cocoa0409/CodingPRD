"""The twelve named calculations of SCAFFOLD.yaml section 1.3.

Every constant here is transcribed from the scaffold's `constants:` blocks and
cross-checked against the PRD narrative; where the two disagree the PRD wins.
Pure functions only -- nothing in this module touches the store.
"""
import math
from datetime import timedelta
from decimal import Decimal

from core import add_days, add_years, round_half_up

# ------------------------------------------------- meeting_notice_requirement
BASE_NOTICE_HOURS = {
    "REGULAR": 72,
    "SPECIAL": 48,
    "EMERGENCY": 24,
    "WORKSHOP": 48,
}
PUBLIC_HEARING_ADDITIONAL_HOURS = 168
LATE_ADDENDUM_PENALTY_HOURS = 24
BODY_MULTIPLIER = {
    "COUNCIL": Decimal("1.0"),
    "PLANNING_COMMISSION": Decimal("1.5"),
    "BOARD_OF_ADJUSTMENT": Decimal("1.5"),
}


def meeting_notice_requirement(meeting, contains_public_hearing, late_addendum):
    """Returns (required_notice_hours, notice_deadline_at).

    The body multiplier is applied to the SUM of the three components and the
    product is rounded UP before the subtraction, never after.
    """
    raw = BASE_NOTICE_HOURS[meeting["meeting_type"]]
    if contains_public_hearing:
        raw += PUBLIC_HEARING_ADDITIONAL_HOURS
    if late_addendum:
        raw += LATE_ADDENDUM_PENALTY_HOURS
    product = Decimal(raw) * BODY_MULTIPLIER[meeting["body_type"]]
    hours = int(math.ceil(product))
    deadline = meeting["scheduled_start"] - timedelta(hours=hours)
    return hours, deadline


def agenda_notice_compliance(posted_at, notice_deadline_at):
    """Posting exactly at the deadline instant is compliant."""
    if posted_at is None or notice_deadline_at is None:
        return False
    return posted_at <= notice_deadline_at


# ------------------------------------------------------- motion_vote_outcome
def required_yes_for(majority_rule, effective_base):
    if majority_rule == "SIMPLE":
        return effective_base // 2 + 1
    if majority_rule == "TWO_THIRDS":
        return -((-effective_base * 2) // 3)
    if majority_rule == "FOUR_FIFTHS":
        return -((-effective_base * 4) // 5)
    # UNANIMOUS_CONSENT
    return effective_base


def motion_vote_outcome(present_member_count, yes_count, no_count,
                        abstain_count, recused_count, majority_rule,
                        presiding_tie_break):
    """Returns (effective_base, required_yes, outcome, tie_break_used).

    Callers must have already enforced ERR_VOTE_TALLY_MISMATCH and
    ERR_NO_VOTING_MEMBERS (in that order, per PRD 3.3).
    """
    effective_base = present_member_count - recused_count
    required_yes = required_yes_for(majority_rule, effective_base)
    tie_break_used = False
    if yes_count >= required_yes:
        outcome = "PASSED"
    elif (yes_count == no_count and majority_rule == "SIMPLE"
          and presiding_tie_break is not None):
        outcome = "TIE_BROKEN_PASSED" if presiding_tie_break == "YES" else "TIE_BROKEN_FAILED"
        tie_break_used = True
    else:
        outcome = "FAILED"
    return effective_base, required_yes, outcome, tie_break_used


PASSING_OUTCOMES = ("PASSED", "TIE_BROKEN_PASSED")
FAILING_OUTCOMES = ("FAILED", "TIE_BROKEN_FAILED")


# --------------------------------------------------- instrument_effective_date
EFFECTIVE_LAG_DAYS = 30


def effective_date_basis_for(instrument):
    """First match wins (PRD 3.5)."""
    if instrument["instrument_class"] == "RESOLUTION":
        return "ADOPTION_IMMEDIATE"
    category = instrument.get("ordinance_category")
    if category == "EMERGENCY":
        return "ADOPTION_IMMEDIATE"
    if category == "CODE_AMENDMENT":
        return "SUPPLEMENT_CERTIFIED"
    return "PUBLICATION_PLUS_30"


def _rolled_publication_date(publication_completed_on):
    if publication_completed_on is None:
        return None
    base = add_days(publication_completed_on, EFFECTIVE_LAG_DAYS)
    weekday = base.weekday()          # Monday == 0 ... Saturday == 5, Sunday == 6
    if weekday == 5:
        return add_days(base, 2)
    if weekday == 6:
        return add_days(base, 1)
    return base


def instrument_effective_date(instrument, basis, cycle_certified_on=None):
    """The weekend roll is applied AFTER the 30-day addition, never before."""
    if basis == "ADOPTION_IMMEDIATE":
        return instrument.get("adoption_date")
    rolled = _rolled_publication_date(instrument.get("publication_completed_on"))
    if basis == "PUBLICATION_PLUS_30":
        return rolled
    # SUPPLEMENT_CERTIFIED
    if cycle_certified_on is None:
        return None
    if rolled is None:
        return cycle_certified_on
    return max(rolled, cycle_certified_on)


# ------------------------------------------------------ publication_requirement
REQUIRED_INSERTIONS = {
    "ORDINANCE_FULL_TEXT": 2,
    "ORDINANCE_SUMMARY": 1,
    "MEETING_AGENDA": 1,
    "CANCELLATION": 1,
}
SUMMARY_THRESHOLD_CHARS = 4000
PUBLICATION_DEADLINE_DAYS = 15
PUBLICATION_MIN_GAP_DAYS = 7


def instrument_notice_type(instrument):
    """A LONG ordinance needs FEWER insertions -- the threshold inverts."""
    if instrument["full_text_length"] > SUMMARY_THRESHOLD_CHARS:
        return "ORDINANCE_SUMMARY"
    return "ORDINANCE_FULL_TEXT"


def publication_requirement(notice_type, instrument=None, meeting=None):
    """Returns (required_publication_count, publication_deadline_on)."""
    count = REQUIRED_INSERTIONS[notice_type]
    if notice_type in ("ORDINANCE_FULL_TEXT", "ORDINANCE_SUMMARY"):
        adoption = instrument.get("adoption_date")
        deadline = add_days(adoption, PUBLICATION_DEADLINE_DAYS) if adoption else None
    elif notice_type == "MEETING_AGENDA":
        deadline = add_days(meeting["scheduled_start"].date(), -1)
    else:  # CANCELLATION
        deadline = meeting["scheduled_start"].date()
    return count, deadline


# ----------------------------------------------------- publication_invoice_total
RATE_CENTS_PER_COLUMN_INCH = 500
AFFIDAVIT_CENTS_PER_INSERTION = 2500


def volume_discount_pct(gross_cost_cents):
    if gross_cost_cents < 50000:
        return 0.0
    if gross_cost_cents < 150000:
        return 0.05
    return 0.10


def publication_invoice_total(column_inches, insertion_count, affidavit_required):
    """Returns (gross_cost_cents, discount_pct, invoice_total_cents)."""
    per_insertion = round_half_up(Decimal(column_inches) * RATE_CENTS_PER_COLUMN_INCH)
    gross = per_insertion * insertion_count
    pct = volume_discount_pct(gross)
    discounted = round_half_up(Decimal(gross) * (Decimal(1) - Decimal(str(pct))))
    affidavit = AFFIDAVIT_CENTS_PER_INSERTION * insertion_count if affidavit_required else 0
    return gross, pct, discounted + affidavit


# ---------------------------------------------------- records_request_due_date
RESPONSE_BUSINESS_DAYS = 5


def records_request_due_date(intake_on):
    cursor = intake_on
    remaining = RESPONSE_BUSINESS_DAYS
    while remaining > 0:
        cursor = add_days(cursor, 1)
        if cursor.weekday() < 5:
            remaining -= 1
    return cursor


# ------------------------------------------------ records_request_fee_assessment
COPY_RATE_CENTS_PER_PAGE = 15
FLAT_RATE_CENTS_PER_PAGE = 25
FREE_PAGE_ALLOWANCE = 20
STAFF_RATE_CENTS_PER_QUARTER_HOUR = 875
FREE_STAFF_QUARTER_HOURS = 2
ELECTRONIC_MEDIUM_DISCOUNT = Decimal("0.50")
COMMERCIAL_SURCHARGE_PCT = Decimal("0.20")


def records_request_fee_assessment(variant, fee_lines, commercial_purpose):
    """The two variants differ in WHERE the allowances and the rounding land."""
    if variant == "ACTUAL_COST":
        allowance = FREE_PAGE_ALLOWANCE
        copy_subtotal = 0
        for line in fee_lines:
            pages = line["page_count"]
            billable_pages = max(0, pages - allowance)
            allowance = max(0, allowance - pages)
            line_copy = billable_pages * COPY_RATE_CENTS_PER_PAGE
            if line["delivery_medium"] == "ELECTRONIC":
                line_copy = round_half_up(
                    Decimal(line_copy) * (Decimal(1) - ELECTRONIC_MEDIUM_DISCOUNT))
            copy_subtotal += line_copy
        quarter_hours = 0
        for line in fee_lines:
            quarter_hours += -((-line["staff_minutes"]) // 15)
    else:  # FLAT_SCHEDULE -- quantities pooled BEFORE anything is priced
        total_pages = sum(line["page_count"] for line in fee_lines)
        billable_pages = max(0, total_pages - FREE_PAGE_ALLOWANCE)
        copy_subtotal = billable_pages * FLAT_RATE_CENTS_PER_PAGE
        total_minutes = sum(line["staff_minutes"] for line in fee_lines)
        quarter_hours = -((-total_minutes) // 15)
    billable_qh = max(0, quarter_hours - FREE_STAFF_QUARTER_HOURS)
    staff_subtotal = billable_qh * STAFF_RATE_CENTS_PER_QUARTER_HOUR
    subtotal = copy_subtotal + staff_subtotal
    if commercial_purpose:
        return round_half_up(Decimal(subtotal) * (Decimal(1) + COMMERCIAL_SURCHARGE_PCT))
    return subtotal


# -------------------------------------------------- records_request_fee_ledger
def records_request_fee_ledger(request):
    """Recomputed from the four stored counters on every money-axis write."""
    net_cash = request["total_collected_cents"] - request["refunded_cents"]
    balance = request["total_assessed_cents"] - request["total_waived_cents"] - net_cash
    request["net_cash_cents"] = net_cash
    request["fee_balance_cents"] = balance
    return balance, net_cash


# ------------------------------------------------ supplement_conflict_precedence
SPECIFICITY_RANK = {"ZONING": 3, "CODE_AMENDMENT": 2, "GENERAL": 1, "EMERGENCY": 0}
_MIN_DATE_KEY = (-9999, -1, -1)


def _adoption_key(instrument):
    value = instrument.get("adoption_date") if instrument else None
    if value is None:
        return _MIN_DATE_KEY
    return (value.year, value.month, value.day)


def _sequence_component(instrument):
    """The numeric tail of assigned_number, e.g. ORD-2026-007 -> 7."""
    number = instrument.get("assigned_number") if instrument else None
    if not number:
        return -1
    tail = str(number).rsplit("-", 1)[-1]
    try:
        return int(tail)
    except (TypeError, ValueError):
        return -1


def supplement_conflict_precedence(basis, pair, instrument_of):
    """`pair` is [submission_a, submission_b]; returns (winner, loser).

    Ranking keys are inverted where the scaffold asks for DESC so that a plain
    ascending sort selects the winner first.
    """
    if basis == "LATER_ADOPTION_WINS":
        def key(sub):
            inst = instrument_of(sub)
            adoption = _adoption_key(inst)
            return (
                tuple(-part for part in adoption),
                -_sequence_component(inst),
                (sub["created_at"], sub["_seq"]),
            )
    else:  # SPECIFIC_OVER_GENERAL
        def key(sub):
            inst = instrument_of(sub)
            category = inst.get("ordinance_category") if inst else None
            rank = SPECIFICITY_RANK.get(category, -1)
            adoption = _adoption_key(inst)
            return (
                -rank,
                tuple(-part for part in adoption),
                (sub["created_at"], sub["_seq"]),
            )
    ordered = sorted(pair, key=key)
    return ordered[0], ordered[1]


# ---------------------------------------------- destruction_eligibility_date
FISCAL_YEAR_END_MONTH = 6
FISCAL_YEAR_END_DAY = 30


def _fiscal_year_end_on_or_after(anchor):
    from datetime import date as _date
    candidate = _date(anchor.year, FISCAL_YEAR_END_MONTH, FISCAL_YEAR_END_DAY)
    if candidate < anchor:
        candidate = _date(anchor.year + 1, FISCAL_YEAR_END_MONTH, FISCAL_YEAR_END_DAY)
    return candidate


def destruction_anchor(series, closure_dates):
    """Returns the anchor date, or None when the anchor is UNRESOLVED."""
    trigger = series["retention_trigger"]
    if trigger == "CREATION":
        return series.get("last_accessioned_on")
    if trigger == "FISCAL_YEAR_END":
        anchor = series.get("last_accessioned_on")
        if anchor is None:
            return None
        return _fiscal_year_end_on_or_after(anchor)
    # REQUEST_CLOSURE
    if not closure_dates:
        return None
    return max(closure_dates)


def destruction_eligibility_date(series, closure_dates):
    if series.get("permanent"):
        return None
    anchor = destruction_anchor(series, closure_dates)
    if anchor is None:
        return None
    return add_years(anchor, series["retention_years"])


# ------------------------------------------------------------------- caps
MAX_CLIENT_SUBMISSIONS_PER_CYCLE = 3
MAX_PACKET_REVISIONS = 3
MAX_SEQUENCE = 999
