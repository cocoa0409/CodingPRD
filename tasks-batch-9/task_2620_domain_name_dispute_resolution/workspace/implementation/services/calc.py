"""Every calculation the specification pins, implemented with integer cents and
Decimal arithmetic.  No float ever touches money.
"""

from datetime import timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

# ---------------------------------------------------------------- fee constants
BASE_ADMIN_FEE_CENTS = 150000
THREE_MEMBER_SUPPLEMENT_CENTS = 250000
EXPEDITED_SURCHARGE_PCT = Decimal("0.125")
PANELIST_HONORARIA_SHARE_PCT = Decimal("0.70")

SEAT_HONORARIA_PCT = {
    "SOLE": Decimal("1.00"),
    "PRESIDING": Decimal("0.40"),
    "CO_PANELIST_1": Decimal("0.30"),
    "CO_PANELIST_2": Decimal("0.30"),
}

# ----------------------------------------------------------- conflict constants
W_PRIOR_REPRESENTATION = 45
W_SAME_FIRM = 35
W_FINANCIAL_INTEREST = 60
W_PRIOR_APPOINTMENT_EACH = 8
PRIOR_APPOINTMENT_CAP = 24
CONFLICT_DECAY_HORIZON_MONTHS = 24
CONFLICT_DECAY_FLOOR = Decimal("0.25")
CONFLICT_DISQUALIFY_THRESHOLD = Decimal("60")
CONFLICT_WAIVER_THRESHOLD = Decimal("30")

# ---------------------------------------------------------- deadline constants
RESPONSE_PERIOD_DAYS = 20
LATE_RESPONSE_GRACE_HOURS = 24
TRANSMISSION_ALLOWANCE_DAYS = {"EMAIL": 0, "COURIER": 2, "POSTAL": 5}
CORRECTION_PERIOD_DAYS = 5
DECISION_PERIOD_DAYS = 14
IMPLEMENTATION_WAIT_BUSINESS_DAYS = 10
PROVIDER_HOLIDAYS = ("2026-09-07",)
COOLING_OFF_DAYS = 30
MIN_EVIDENCE_PER_GROUND = 1
MAX_DEFICIENCY_ROUNDS = 2
MAX_NOTIFICATION_ATTEMPTS = 5

# --------------------------------------------------------- precedent constants
PRECEDENT_DECAY_HORIZON_MONTHS = 60
PRECEDENT_DECAY_FLOOR = Decimal("0.20")

REQUIRED_GROUND_TYPES = ("TRADEMARK_RIGHTS", "NO_LEGITIMATE_INTEREST", "BAD_FAITH")

DEFICIENCY_CODES = (
    "MISSING_GROUND",
    "MISSING_MARK_EVIDENCE",
    "MISSING_SIGNATURE",
    "ILLEGIBLE_EVIDENCE_ANNEX",
    "FEE_SHORTFALL",
    "MUTUAL_JURISDICTION_ABSENT",
    "DOMAIN_MISMATCH",
)


def round_half_up(value, places=0):
    quant = Decimal(1) if places == 0 else Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def floor_cents(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_FLOOR))


def cents_half_up(value):
    return int(round_half_up(value, 0))


# ------------------------------------------------------- filing_fee_assessment
def filing_fee_assessment(seat_count, expedited):
    panel_supplement = THREE_MEMBER_SUPPLEMENT_CENTS if seat_count == 3 else 0
    surcharge = (cents_half_up(Decimal(BASE_ADMIN_FEE_CENTS) * EXPEDITED_SURCHARGE_PCT)
                 if expedited else 0)
    assessed = BASE_ADMIN_FEE_CENTS + panel_supplement + surcharge
    respondent_share = (floor_cents(Decimal(THREE_MEMBER_SUPPLEMENT_CENTS) / 2)
                        if seat_count == 3 else 0)
    return {
        "assessed_fee_cents": assessed,
        "respondent_share_cents": respondent_share,
        "complainant_share_cents": assessed - respondent_share,
        "honoraria_pool_cents": cents_half_up(Decimal(assessed) * PANELIST_HONORARIA_SHARE_PCT),
    }


# -------------------------------------------------- panelist_honoraria_allocation
def honoraria_allocation(pool, seat_count):
    if seat_count == 1:
        return {"SOLE": pool}
    presiding_floor = floor_cents(Decimal(pool) * SEAT_HONORARIA_PCT["PRESIDING"])
    co1_floor = floor_cents(Decimal(pool) * SEAT_HONORARIA_PCT["CO_PANELIST_1"])
    co2_floor = floor_cents(Decimal(pool) * SEAT_HONORARIA_PCT["CO_PANELIST_2"])
    remainder = pool - (presiding_floor + co1_floor + co2_floor)
    return {
        "PRESIDING": presiding_floor + remainder,
        "CO_PANELIST_1": co1_floor,
        "CO_PANELIST_2": co2_floor,
    }


# ------------------------------------------------------ panelist_conflict_score
def conflict_score(prior_representation, same_firm, financial_interest,
                   prior_appointments, months_since_last_contact):
    appointment_term = min(W_PRIOR_APPOINTMENT_EACH * prior_appointments,
                           PRIOR_APPOINTMENT_CAP)
    financial_component = W_FINANCIAL_INTEREST if financial_interest else 0
    raw = (W_PRIOR_REPRESENTATION * (1 if prior_representation else 0)
           + W_SAME_FIRM * (1 if same_firm else 0)
           + financial_component
           + appointment_term)
    if months_since_last_contact is None:
        decay = Decimal("1.00")
    else:
        decay = Decimal(1) - (Decimal(months_since_last_contact)
                              / Decimal(CONFLICT_DECAY_HORIZON_MONTHS))
        if decay < CONFLICT_DECAY_FLOOR:
            decay = CONFLICT_DECAY_FLOOR
    decayable = Decimal(raw - financial_component)
    score = round_half_up(decayable * decay, 2) + Decimal(financial_component)
    if score > Decimal("100.00"):
        score = Decimal("100.00")
    score = score.quantize(Decimal("0.01"))

    factors = []
    if financial_interest:
        factors.append("FINANCIAL_INTEREST")
    if appointment_term > 0:
        factors.append("PRIOR_APPOINTMENTS")
    if prior_representation:
        factors.append("PRIOR_REPRESENTATION")
    if same_firm:
        factors.append("SAME_FIRM")
    factors.sort()
    if score == Decimal("0.00"):
        factors = []
    return score, factors


def conflict_band(score):
    if score >= CONFLICT_DISQUALIFY_THRESHOLD:
        return "CONFLICTED"
    if score >= CONFLICT_WAIVER_THRESHOLD:
        return "WAIVER_PENDING"
    return "ACCEPTED"


# --------------------------------------------------------- panel_outcome_tally
OUTCOME_OF_VOTE = {
    "TRANSFER": "TRANSFER",
    "CANCELLATION": "CANCELLATION",
    "DENY": "COMPLAINT_DENIED",
}


def panel_outcome_tally(vote_rows, required_seat_count):
    transfer_votes = sum(1 for v in vote_rows if v["vote"] == "TRANSFER")
    cancellation_votes = sum(1 for v in vote_rows if v["vote"] == "CANCELLATION")
    deny_votes = sum(1 for v in vote_rows if v["vote"] == "DENY")
    counts = {
        "TRANSFER": transfer_votes,
        "CANCELLATION": cancellation_votes,
        "DENY": deny_votes,
    }
    leader_count = max(counts.values())
    if leader_count * 2 > required_seat_count:
        # Exactly one vote value can hold strictly more than half the seats.
        leading = next(k for k in ("TRANSFER", "CANCELLATION", "DENY")
                       if counts[k] == leader_count)
        outcome = OUTCOME_OF_VOTE[leading]
        basis = "STRICT_MAJORITY"
    else:
        presiding = next((v for v in vote_rows if v["seat"] == "PRESIDING"), None)
        outcome = OUTCOME_OF_VOTE[presiding["vote"]] if presiding else None
        basis = "PRESIDING_CASTING"
    rdnh_flags = sum(1 for v in vote_rows if v.get("rdnh_vote"))
    return {
        "transfer_votes": transfer_votes,
        "cancellation_votes": cancellation_votes,
        "deny_votes": deny_votes,
        "outcome": outcome,
        "outcome_basis": basis,
        "dissent_present": leader_count < required_seat_count,
        "rdnh_finding": outcome == "COMPLAINT_DENIED" and rdnh_flags * 2 > required_seat_count,
    }


# --------------------------------------------------- response_deadline_projection
def transmission_allowance(channel):
    return TRANSMISSION_ALLOWANCE_DAYS[channel]


def provisional_response_due(dispatched_at, channel):
    return dispatched_at + timedelta(days=transmission_allowance(channel)
                                     + RESPONSE_PERIOD_DAYS)


def final_response_due(deemed_received_at):
    return deemed_received_at + timedelta(days=RESPONSE_PERIOD_DAYS)


def default_cutoff(response_due_at):
    return response_due_at + timedelta(hours=LATE_RESPONSE_GRACE_HOURS)


# ------------------------------------------------------- implementation_window
def _is_business_day(day):
    if day.weekday() >= 5:
        return False
    return day.date().isoformat() not in PROVIDER_HOLIDAYS


def implementation_deadline(anchor, business_days=IMPLEMENTATION_WAIT_BUSINESS_DAYS):
    """Ten business days on the provider calendar; the anchor day is never counted
    and the anchor's time of day is carried through untouched."""
    cursor = anchor
    counted = 0
    while counted < business_days:
        cursor = cursor + timedelta(days=1)
        if _is_business_day(cursor):
            counted += 1
    return cursor


def decision_due(accepted_at):
    return accepted_at + timedelta(days=DECISION_PERIOD_DAYS)


# ----------------------------------------------------- precedent_citation_metrics
def months_elapsed(start, end):
    if end <= start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if (end.day, end.hour, end.minute, end.second, end.microsecond) < \
       (start.day, start.hour, start.minute, start.second, start.microsecond):
        months -= 1
    return max(0, months)


def precedent_weight(citation_count, issued_at, clock):
    elapsed = months_elapsed(issued_at, clock)
    age_weight = Decimal(1) - (Decimal(elapsed) / Decimal(PRECEDENT_DECAY_HORIZON_MONTHS))
    if age_weight < PRECEDENT_DECAY_FLOOR:
        age_weight = PRECEDENT_DECAY_FLOOR
    return round_half_up(Decimal(citation_count) * age_weight, 2)


# ------------------------------------------------------------ withdrawal_refund
REFUND_PCT_PRE_CLEARANCE = Decimal("1.00")
REFUND_PCT_PRE_COMMENCEMENT = Decimal("0.50")
REFUND_PCT_POST_COMMENCEMENT = Decimal("0.00")


def refund_pct(case_status):
    if case_status in ("FILED", "DEFICIENT"):
        return REFUND_PCT_PRE_CLEARANCE
    if case_status in ("VERIFICATION_PENDING", "NOTIFICATION_PENDING"):
        return REFUND_PCT_PRE_COMMENCEMENT
    return REFUND_PCT_POST_COMMENCEMENT
