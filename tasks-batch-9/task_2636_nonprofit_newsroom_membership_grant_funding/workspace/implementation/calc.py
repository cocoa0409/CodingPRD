"""Domain constants, enumerations and the eleven pinned calculations."""

from datetime import date, timedelta
from fractions import Fraction
from math import ceil, floor

from core import (
    DB, add_months_clamped, day_start, find, iso_ms, parse_date, parse_instant,
    round_half_up, rows, span_months,
)

# ---------------------------------------------------------------------------
# Constants (§2.6 / scaffold constants)
# ---------------------------------------------------------------------------

INSUBSTANTIAL_PCT_BPS = 200
INSUBSTANTIAL_CAP_CENTS = 13000
MAJOR_DONOR_THRESHOLD_CENTS = 500000
FEE_TIER_1_FLOOR_CENTS = 1000000
FEE_TIER_2_FLOOR_CENTS = 5000000
FEE_TIER_1_BPS = 150
FEE_TIER_2_BPS = 250
BOARD_RATIFICATION_THRESHOLD_CENTS = 2500000
RATIFICATION_RISK_FLOOR = 40
TYPE_WEIGHT = {"FOUNDATION": 10, "INDIVIDUAL": 5, "CORPORATE": 25, "GOVERNMENT": 20}
ADVOCACY_WEIGHT = 4
EDITORIAL_REQUEST_WEIGHT = 8
AFFILIATION_WEIGHT = 10
RELIABILITY_WEIGHT = 25
RELIABILITY_PENALTY_BPS = 2000
SELF_ATTESTED_ADVOCACY_INDEX = 3
RISK_DISCLOSURE_FLOOR = 40
RISK_HARD_BAR = 60
RESERVE_MONTHS_BASE = 3
HHI_ESCALATION_1 = 3000
TOP_SOURCE_ESCALATION = 3500
HHI_WATCH = 4000
CONCENTRATION_BOARD_FLOOR_HHI = 4500
RELEASE_CAP_BPS = {"HEALTHY": 10000, "WATCH": 6000, "CONSTRAINED": 2500, "CRITICAL": 0}
REPORT_GRACE_DAYS = 45
GRACE_DAYS = 30
MAX_CONDITION_ROUNDS = 2
MAX_REVISION_ROUNDS = 3
MAX_ACCEPTABLE_VARIANCE_BPS = 2000
MAX_RESTRICTED_GRANTS_PER_AREA = 2
COOLING_OFF_DAYS = 30

SEVERITY_WEIGHT = {
    "ROUTINE_STEWARDSHIP": 0,
    "COVERAGE_INQUIRY": 1,
    "CONDITION_ATTEMPT": 2,
    "EDITORIAL_DIRECTION_REQUEST": 3,
}

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

PERIOD_STATUSES = ("OPEN", "REVIEW_LOCKED", "CLOSED")
POSTURES = ("HEALTHY", "WATCH", "CONSTRAINED", "CRITICAL")
RENEWAL_CADENCES = ("MONTHLY", "ANNUAL")
FULFILLMENT_TYPES = ("TOTE_BAG", "EVENT_ACCESS", "NEWSLETTER", "BOOK",
                     "MERCH_DISCOUNT")
TIER_STATUSES = ("DRAFT", "PUBLISHED")
MEMBER_STATUSES = ("PENDING", "ACTIVE", "GRACE", "LAPSED", "CANCELLED")
DISCLOSURE_FRESHNESS = ("CURRENT", "STALE")
PUBLICATION_GATES = ("OPEN", "BLOCKED")
FUNDER_TYPES = ("FOUNDATION", "INDIVIDUAL", "CORPORATE", "GOVERNMENT")
RISK_BASES = ("SELF_ATTESTED", "AUDITED")
FUNDER_STATUSES = ("PROSPECT", "CLEARED", "RESTRICTED")
DESIGNATIONS = ("UNRESTRICTED", "PROGRAM_RESTRICTED", "PROJECT_RESTRICTED")
GIFT_STATUSES = ("PROPOSED", "INDEPENDENCE_REVIEW", "CONDITIONS_REQUESTED",
                 "CLEARED", "ACCEPTED", "DECLINED")
RESTRICTION_TYPES = ("UNRESTRICTED", "PROGRAM_RESTRICTED", "PROJECT_RESTRICTED")
REPORTING_CADENCES = ("NONE", "SEMIANNUAL", "ANNUAL")
PROPOSAL_STATUSES = ("DRAFT", "INDEPENDENCE_REVIEW", "REVISION_REQUESTED", "CLEARED",
                     "SUBMITTED", "AWARDED", "DECLINED", "WITHDRAWN", "SUSPENDED",
                     "CLOSED")
COMPLIANCE_FLAGS = ("COMPLIANT", "DELINQUENT")
SUSPENSION_REASONS = ("FIREWALL_BREACH", "REPORT_DELINQUENCY")
REPORT_STATUSES = ("SCHEDULED", "SUBMITTED", "ACCEPTED", "RETURNED", "OVERDUE", "WAIVED")
REVENUE_STREAMS = ("MEMBERSHIP", "MAJOR_GIFT", "EVENTS", "SYNDICATION")
STREAM_KEYS = ("MEMBERSHIP", "MAJOR_GIFT", "GRANTS", "EVENTS", "SYNDICATION")
SETTLEMENT_STATUSES = ("INITIATED", "SETTLED", "FAILED", "REFUNDED")
ACK_STATUSES = ("UNACKNOWLEDGED", "RECEIPTED", "DISCLOSED")
DISCLOSURE_STATUSES = ("ACTIVE", "REATTESTATION_REQUIRED", "SUPERSEDED", "VOID")
REATTESTATION_REASONS = ("FUNDER_RESTRICTED", "INFLUENCE_CONTACT")
CONTACT_TYPES = ("ROUTINE_STEWARDSHIP", "COVERAGE_INQUIRY",
                 "EDITORIAL_DIRECTION_REQUEST", "CONDITION_ATTEMPT")
COLLABORATION_STATUSES = ("DRAFT", "ACTIVE", "SETTLED", "DISSOLVED")
PARTNER_STATUSES = ("CONFIRMED", "WITHDRAWN")

PERIOD_TERMINAL = ("CLOSED",)
GIFT_TERMINAL = ("ACCEPTED", "DECLINED")
PROPOSAL_TERMINAL = ("DECLINED", "WITHDRAWN", "CLOSED")
REPORT_TERMINAL = ("ACCEPTED", "WAIVED")
DISCLOSURE_TERMINAL = ("SUPERSEDED", "VOID")
SETTLEMENT_TERMINAL = ("FAILED", "REFUNDED")
COLLABORATION_TERMINAL = ("SETTLED", "DISSOLVED")
PARTNER_TERMINAL = ("WITHDRAWN",)


# ---------------------------------------------------------------------------
# 1. tier_quid_pro_quo_value
# ---------------------------------------------------------------------------

def tier_quid_pro_quo_value(contribution_amount_cents, benefits, renewal_cadence):
    """Returns (threshold, qpq_per_period, insubstantial_codes, benefit_count).

    On a MONTHLY tier each benefit's annual fair market value is divided by 12
    and rounded half up *for that benefit individually*; only afterwards are the
    substantial per-period values summed.  The order is not interchangeable --
    three 1000-cent annual benefits on a MONTHLY tier give 83+83+83 = 249, not
    the 250 that summing first would produce.
    """
    threshold = min(
        round_half_up(int(contribution_amount_cents) * INSUBSTANTIAL_PCT_BPS, 10000),
        INSUBSTANTIAL_CAP_CENTS,
    )
    qpq = 0
    insubstantial = []
    for benefit in benefits:
        annual = int(benefit.get("annual_fair_market_value_cents") or 0)
        if renewal_cadence == "MONTHLY":
            per_period = round_half_up(annual, 12)
        else:
            per_period = annual
        if per_period <= threshold:
            insubstantial.append(benefit.get("benefit_code"))
        else:
            qpq += per_period
    return threshold, qpq, insubstantial, len(benefits)


# ---------------------------------------------------------------------------
# 2. contribution_deductible_split
# ---------------------------------------------------------------------------

def contribution_deductible_split(revenue_stream, amount_cents, tier):
    amount_cents = int(amount_cents)
    if revenue_stream in ("EVENTS", "SYNDICATION"):
        return 0, 0
    if revenue_stream == "MAJOR_GIFT":
        return 0, amount_cents
    qpq = int(tier["quid_pro_quo_per_period_cents"]) if tier else 0
    return qpq, max(0, amount_cents - qpq)


# ---------------------------------------------------------------------------
# 3. gift_stewardship_netting
# ---------------------------------------------------------------------------

def stewardship_fee_bps(gross_cents):
    gross_cents = int(gross_cents)
    if gross_cents < FEE_TIER_1_FLOOR_CENTS:
        return 0
    if gross_cents < FEE_TIER_2_FLOOR_CENTS:
        return FEE_TIER_1_BPS
    return FEE_TIER_2_BPS


def gift_stewardship_netting(gross_cents, funder_risk_score):
    gross_cents = int(gross_cents)
    fee = round_half_up(gross_cents * stewardship_fee_bps(gross_cents), 10000)
    net = gross_cents - fee
    ratify = (gross_cents >= BOARD_RATIFICATION_THRESHOLD_CENTS
              or int(funder_risk_score) >= RATIFICATION_RISK_FLOOR)
    return fee, net, ratify


# ---------------------------------------------------------------------------
# 4. funder_independence_risk
# ---------------------------------------------------------------------------

def funder_advocacy_index(funder, basis=None):
    basis = basis or funder.get("risk_basis") or "SELF_ATTESTED"
    if basis == "AUDITED":
        value = funder.get("audited_advocacy_index")
        return int(value) if value is not None else 0
    return SELF_ATTESTED_ADVOCACY_INDEX if funder.get("self_attested_advocacy") else 0


def funder_editorial_request_count(funder_id):
    total = 0
    for contact in DB["influence_contacts"].values():
        if contact.get("funder_id") == funder_id and contact.get("contact_type") in (
                "EDITORIAL_DIRECTION_REQUEST", "CONDITION_ATTEMPT"):
            total += 1
    return total


def funder_reporting_reliability_bps(funder_id):
    overdue_events = 0
    for proposal in DB["grant_proposals"].values():
        if proposal.get("funder_id") != funder_id:
            continue
        if proposal.get("status") == "WITHDRAWN":
            continue
        for report in DB["grant_reports"].values():
            if report.get("grant_proposal_id") != proposal["id"]:
                continue
            if report.get("_ever_overdue"):
                overdue_events += 1
    return max(0, 10000 - RELIABILITY_PENALTY_BPS * overdue_events)


def funder_independence_risk(funder, basis=None, advocacy_index=None,
                             reliability_bps=None, editorial_requests=None):
    basis = basis or funder.get("risk_basis") or "SELF_ATTESTED"
    if advocacy_index is None:
        advocacy_index = funder_advocacy_index(funder, basis)
    if reliability_bps is None:
        reliability_bps = funder_reporting_reliability_bps(funder["id"])
    if editorial_requests is None:
        editorial_requests = funder_editorial_request_count(funder["id"])
    raw = TYPE_WEIGHT.get(funder.get("funder_type"), 0)
    raw += ADVOCACY_WEIGHT * int(advocacy_index)
    raw += EDITORIAL_REQUEST_WEIGHT * int(editorial_requests)
    if funder.get("affiliated_coverage_area_id"):
        raw += AFFILIATION_WEIGHT
    raw += round_half_up(RELIABILITY_WEIGHT * (10000 - int(reliability_bps)), 10000)
    return min(100, raw)


# ---------------------------------------------------------------------------
# 5. revenue_diversification_index
# ---------------------------------------------------------------------------

def _pipeline_term(proposal):
    return round_half_up(int(proposal.get("requested_amount_cents") or 0)
                         * int(proposal.get("award_probability_bps") or 0), 10000)


def revenue_diversification_index(period, basis="RECOGNIZED"):
    """Returns (recognized_revenue_cents, stream_shares_bps, hhi, top_source_bps)."""
    settled_set = ("SETTLED",) if basis == "RECOGNIZED" else ("SETTLED", "INITIATED")
    totals = {key: 0 for key in STREAM_KEYS}
    source_totals = {}

    for contribution in DB["contributions"].values():
        if contribution.get("fiscal_period_id") != period["id"]:
            continue
        if contribution.get("settlement_status") not in settled_set:
            continue
        amount = int(contribution.get("amount_cents") or 0)
        stream = contribution.get("revenue_stream")
        if stream in totals:
            totals[stream] += amount
        funder_id = contribution.get("funder_id")
        if funder_id:
            source_totals[funder_id] = source_totals.get(funder_id, 0) + amount

    for proposal in DB["grant_proposals"].values():
        if proposal.get("fiscal_period_id") != period["id"]:
            continue
        contribution_amount = 0
        if proposal.get("status") in ("AWARDED", "CLOSED"):
            contribution_amount = int(proposal.get("awarded_amount_cents") or 0)
        elif basis == "PIPELINE" and proposal.get("status") == "SUBMITTED":
            contribution_amount = _pipeline_term(proposal)
        if contribution_amount:
            totals["GRANTS"] += contribution_amount
            funder_id = proposal.get("funder_id")
            if funder_id:
                source_totals[funder_id] = source_totals.get(funder_id, 0) + contribution_amount

    total = sum(totals.values())
    if total == 0:
        shares = {key: 0 for key in STREAM_KEYS}
    else:
        shares = {key: round_half_up(10000 * totals[key], total) for key in STREAM_KEYS}
    hhi = round_half_up(sum(shares[key] * shares[key] for key in STREAM_KEYS), 10000)
    if total == 0 or not source_totals:
        top_source = 0
    else:
        top_source = round_half_up(10000 * max(source_totals.values()), total)
    return total, shares, hhi, top_source


# ---------------------------------------------------------------------------
# 6. reserve_policy_posture
# ---------------------------------------------------------------------------

def reserve_policy_posture(monthly_expense_base_cents, reserve_balance_cents,
                          concentration_hhi, top_source_share_bps):
    """Returns (target_months, target_cents, ratio_bps, posture, cap_bps)."""
    base = int(monthly_expense_base_cents)
    balance = int(reserve_balance_cents)
    target_months = RESERVE_MONTHS_BASE
    if int(concentration_hhi) >= HHI_ESCALATION_1:
        target_months += 1
    if int(top_source_share_bps) >= TOP_SOURCE_ESCALATION:
        target_months += 1
    target_cents = base * target_months
    ratio_bps = round_half_up(10000 * balance, base) if base else 0
    if balance < base:
        posture = "CRITICAL"
    elif balance < round_half_up(target_cents, 2):
        posture = "CONSTRAINED"
    elif balance < target_cents or int(concentration_hhi) >= HHI_WATCH:
        posture = "WATCH"
    else:
        posture = "HEALTHY"
    return target_months, target_cents, ratio_bps, posture, RELEASE_CAP_BPS[posture]


# ---------------------------------------------------------------------------
# 7. restricted_release_waterfall (bucket allocation half)
# ---------------------------------------------------------------------------

def allocate_release_buckets(awarded_amount_cents, bucket_count):
    """Even split with the whole remainder landing on the LAST bucket."""
    if bucket_count <= 0:
        return []
    awarded = int(awarded_amount_cents)
    base = awarded // bucket_count
    allocations = [base] * bucket_count
    allocations[-1] = base + (awarded - base * bucket_count)
    return allocations


# ---------------------------------------------------------------------------
# 8. collaboration_cost_split (largest remainder apportionment)
# ---------------------------------------------------------------------------

def largest_remainder_split(total_cents, shares_bps):
    """`shares_bps` is in participant order (lead first, then partners by
    created_at ascending).  Exact rational products are floored, and the
    leftover cents go one each to the largest remainders, ties broken by that
    participant order.  Returns (amounts, ranks) with 1-based ranks."""
    count = len(shares_bps)
    if count == 0:
        return [], []
    total = int(total_cents)
    exact = [Fraction(total * int(share), 10000) for share in shares_bps]
    floors = [int(value // 1) for value in exact]
    remainders = [exact[i] - floors[i] for i in range(count)]
    leftover = total - sum(floors)
    order = sorted(range(count), key=lambda i: (-remainders[i], i))
    amounts = list(floors)
    ranks = [0] * count
    for position, index in enumerate(order):
        ranks[index] = position + 1
        if position < leftover:
            amounts[index] += 1
    return amounts, ranks


# ---------------------------------------------------------------------------
# 9. member_renewal_schedule
# ---------------------------------------------------------------------------

def member_renewal_schedule(cycle_start_date, renewal_cadence, grace_period_days):
    """Returns (next_renewal_date, grace_expires_at) or (None, None)."""
    if cycle_start_date is None:
        return None, None
    step = 1 if renewal_cadence == "MONTHLY" else 12
    next_renewal = add_months_clamped(cycle_start_date, step)
    grace_expires = day_start(next_renewal) + timedelta(days=int(grace_period_days or 0))
    return next_renewal, grace_expires


# ---------------------------------------------------------------------------
# 10. report_obligation_schedule
# ---------------------------------------------------------------------------

def report_obligation_schedule(window_start, window_end, reporting_cadence):
    if reporting_cadence not in ("SEMIANNUAL", "ANNUAL"):
        return []
    if window_start is None or window_end is None or window_end < window_start:
        return []
    interval = 6 if reporting_cadence == "SEMIANNUAL" else 12
    total_months = span_months(window_start, window_end)
    count = int(ceil(float(total_months) / interval))
    schedule = []
    for index in range(1, count + 1):
        period_start = add_months_clamped(window_start, (index - 1) * interval)
        boundary = add_months_clamped(window_start, index * interval) - timedelta(days=1)
        period_end = min(window_end, boundary)
        schedule.append({
            "sequence_no": index,
            "period_start": period_start,
            "period_end": period_end,
            "due_date": period_end + timedelta(days=REPORT_GRACE_DAYS),
        })
    return schedule


# ---------------------------------------------------------------------------
# Small shared predicates
# ---------------------------------------------------------------------------

def is_designated(designation):
    return designation is not None and designation != "UNRESTRICTED"


def is_restricted_scope(restriction_type):
    return restriction_type is not None and restriction_type != "UNRESTRICTED"


def windows_overlap(start_a, end_a, start_b, end_b):
    """Inclusive-range overlap for restriction windows."""
    if None in (start_a, end_a, start_b, end_b):
        return False
    return start_a <= end_b and start_b <= end_a


def windows_within_days(start_a, end_a, start_b, end_b, days):
    """True when the two inclusive windows fall within `days` of one another."""
    if None in (start_a, end_a, start_b, end_b):
        return False
    slack = timedelta(days=days)
    return start_a - slack <= end_b and start_b - slack <= end_a
