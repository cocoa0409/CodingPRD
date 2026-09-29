"""The sixteen calculations of PRD 3 with their pinned rounding and evaluation orders."""

from decimal import Decimal, ROUND_HALF_UP

from store import S, add_days

# Statutory constants the carrier may not tune (PRD 2.9, 3.4, 3.6, 3.9).
ELECTION_WINDOW_DAYS = 5
AUTO_CLOSE_DAYS = 30
REOPEN_LIMIT = 2
INVOLUNTARY_NO_COMP_MAX_MINUTES = 60
TIER1_MAX_MINUTES_DOMESTIC = 120
TIER1_MAX_MINUTES_INTERNATIONAL = 240
INVOLUNTARY_TIER1_MULTIPLIER = Decimal("2.0")
INVOLUNTARY_TIER2_MULTIPLIER = Decimal("4.0")
INVOLUNTARY_TIER1_CAP_CENTS = 77500
INVOLUNTARY_TIER2_CAP_CENTS = 155000
VOLUNTARY_DISCLOSURE_FLOOR_PCT = Decimal("0.50")

UNUSED_SEGMENT_STATUSES = ("SCHEDULED", "DELAYED", "CANCELLED", "DISRUPTED_UNUSED")
FLOWN_SEGMENT_STATUSES = ("DEPARTED", "ARRIVED")
OPEN_COMPLAINT_STATUSES = ("RECEIVED", "ACKNOWLEDGED", "INFO_REQUESTED")


# --------------------------------------------------------------------------
# money and elapsed-time primitives (PRD 2.7)
# --------------------------------------------------------------------------

def round_half_up(value):
    """Round a Decimal/int/float quantity half up to a whole cent."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def whole_seconds(start, end):
    delta = end - start
    return delta.days * 86400 + delta.seconds


def whole_minutes(start, end):
    """Difference in whole minutes with the remainder dropped."""
    return whole_seconds(start, end) // 60


def hours_2dp(start, end):
    seconds = whole_seconds(start, end)
    return round_half_up_2(Decimal(seconds) / Decimal(3600))


# --------------------------------------------------------------------------
# child-row lookups
# --------------------------------------------------------------------------

def segments_of(booking_id):
    rows = [r for r in S.flight_segments.values() if r["booking_id"] == booking_id]
    return sorted(rows, key=lambda r: r["sequence_index"])


def ancillaries_of(booking_id):
    rows = [r for r in S.ancillary_purchases.values() if r["booking_id"] == booking_id]
    return sorted(rows, key=lambda r: r["_seq"])


def bags_of(booking_id):
    rows = [r for r in S.checked_bags.values() if r["booking_id"] == booking_id]
    return sorted(rows, key=lambda r: r["_seq"])


def obligations_of(booking_id):
    rows = [r for r in S.refund_obligations.values() if r["booking_id"] == booking_id]
    return sorted(rows, key=lambda r: r["_seq"])


def complaints_of(booking_id):
    rows = [r for r in S.consumer_complaints.values() if r["booking_id"] == booking_id]
    return sorted(rows, key=lambda r: r["_seq"])


def events_of(segment_id):
    rows = [r for r in S.tarmac_delay_events.values() if r["flight_segment_id"] == segment_id]
    return sorted(rows, key=lambda r: (r["tarmac_start_utc"], r["_seq"]))


def policy_of(booking):
    return S.policy_profiles.get(booking["policy_profile_id"])


# --------------------------------------------------------------------------
# significant_delay_determination (PRD 3.2)
# --------------------------------------------------------------------------

def significant_delay(segment, policy, delay_minutes):
    if segment["is_international"]:
        threshold = policy["international_significant_delay_minutes"]
    else:
        threshold = policy["domestic_significant_delay_minutes"]
    return delay_minutes >= threshold


# --------------------------------------------------------------------------
# fare_refund_entitlement (PRD 3.6)
# --------------------------------------------------------------------------

def fare_gross_proactive(booking):
    """Variant PROACTIVE_FULL_ITINERARY."""
    if not booking["travel_commenced"]:
        return booking["total_fare_cents"]
    total = 0
    for segment in segments_of(booking["id"]):
        if segment["status"] in UNUSED_SEGMENT_STATUSES:
            total += segment["segment_fare_cents"]
    return total


def fare_gross_request_based(booking):
    """Variant REQUEST_BASED_UNUSED_PRORATION -- round the per-leg share first."""
    if booking["segment_count"] == 0:
        return 0
    per_segment = round_half_up(
        Decimal(booking["total_fare_cents"]) / Decimal(booking["segment_count"])
    )
    return per_segment * booking["unused_segment_count"]


# --------------------------------------------------------------------------
# booking_refund_headroom (PRD 3.6 step 2)
# --------------------------------------------------------------------------

def collected_total(booking):
    total = booking["total_fare_cents"]
    for row in ancillaries_of(booking["id"]):
        total += row["amount_cents"]
    for row in bags_of(booking["id"]):
        total += row["fee_cents"]
    return total


def consumed_cents(booking):
    total = 0
    for row in obligations_of(booking["id"]):
        if row["settlement_status"] == "VOIDED":
            continue
        if row["basis"] == "DENIED_BOARDING":
            continue
        total += row["amount_cents"]
    return total


def headroom(booking):
    return collected_total(booking) - consumed_cents(booking)


# --------------------------------------------------------------------------
# denied_boarding_compensation (PRD 3.4)
# --------------------------------------------------------------------------

def statutory_ladder(one_way_fare_cents, substitute_delay_minutes, is_international):
    tier1_max = (
        TIER1_MAX_MINUTES_INTERNATIONAL if is_international else TIER1_MAX_MINUTES_DOMESTIC
    )
    if substitute_delay_minutes <= INVOLUNTARY_NO_COMP_MAX_MINUTES:
        return 0
    if substitute_delay_minutes <= tier1_max:
        multiple = round_half_up(Decimal(one_way_fare_cents) * INVOLUNTARY_TIER1_MULTIPLIER)
        return min(multiple, INVOLUNTARY_TIER1_CAP_CENTS)
    multiple = round_half_up(Decimal(one_way_fare_cents) * INVOLUNTARY_TIER2_MULTIPLIER)
    return min(multiple, INVOLUNTARY_TIER2_CAP_CENTS)


def resolve_effective_category(record):
    if (
        record["category"] == "VOLUNTARY"
        and record["oversale_confirmed"]
        and record["written_disclosure_provided"]
    ):
        return "VOLUNTARY"
    return "INVOLUNTARY"


def voluntary_floor(statutory_compensation_cents):
    return round_half_up(
        Decimal(statutory_compensation_cents) * VOLUNTARY_DISCLOSURE_FLOOR_PCT
    )


# --------------------------------------------------------------------------
# baggage_delivery_delay (PRD 3.3)
# --------------------------------------------------------------------------

def bag_threshold_hours(booking, policy):
    if booking["itinerary_scope"] == "INTERNATIONAL":
        return policy["bag_delay_threshold_hours_international"]
    return policy["bag_delay_threshold_hours_domestic"]


# --------------------------------------------------------------------------
# tarmac_compliance_evaluation (PRD 3.5)
# --------------------------------------------------------------------------

def tarmac_deadline_minutes(segment, policy):
    if segment["is_international"]:
        return policy["tarmac_deplane_deadline_minutes_international"]
    return policy["tarmac_deplane_deadline_minutes_domestic"]


# --------------------------------------------------------------------------
# refund_deadline_resolution (PRD 3.6)
# --------------------------------------------------------------------------

def refund_deadlines(booking, policy, obligation_start_utc):
    if booking["payment_method"] == "CREDIT_CARD":
        days = policy["credit_card_refund_deadline_days"]
    else:
        days = policy["other_method_refund_deadline_days"]
    return (
        add_days(obligation_start_utc, days),
        add_days(obligation_start_utc, ELECTION_WINDOW_DAYS),
    )


# --------------------------------------------------------------------------
# travel_credit_bonus + settlement_method_resolution (PRD 3.7)
# --------------------------------------------------------------------------

def credit_bonus(amount_cents, policy):
    return round_half_up(
        Decimal(amount_cents) * Decimal(str(policy["travel_credit_election_bonus_pct"]))
    )


def settlement_method_for(election, booking):
    if election == "TRAVEL_CREDIT":
        return "TRAVEL_CREDIT"
    payment_method = booking["payment_method"]
    if payment_method == "CREDIT_CARD":
        return "ORIGINAL_PAYMENT"
    if payment_method == "CASH_OR_CHECK":
        return "CASH_OR_CHECK"
    if payment_method == "MILES":
        return "MILES"
    return "TRAVEL_CREDIT"


# --------------------------------------------------------------------------
# complaint_deadline_resolution (PRD 3.8)
# --------------------------------------------------------------------------

def answer_days_for(category, policy):
    if category == "DISABILITY":
        return policy["complaint_answer_deadline_days_disability"]
    return policy["complaint_answer_deadline_days_general"]
