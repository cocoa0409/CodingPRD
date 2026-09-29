"""Calculations: match scores, ranking, deadlines, windows, claims, counters.

Every constant is the one the PRD states literally.  Money is integer cents and
every fractional value goes through Decimal with ROUND_HALF_UP (PRD 2.6).
"""

from collections import Counter
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, getcontext

from store import db

getcontext().prec = 60

LOCI = ("A", "B", "C", "DRB1", "DQB1")

# --- match_probability_score ----------------------------------------------
LOCUS_WEIGHTS = {
    "A": Decimal("1.0"),
    "B": Decimal("1.0"),
    "C": Decimal("0.8"),
    "DRB1": Decimal("1.4"),
    "DQB1": Decimal("0.6"),
}
LOCUS_WEIGHT_TOTAL = Decimal("9.6")
AMBIGUITY_PENALTY_PER_LOCUS = Decimal("3.5")
CMV_MATCH_BONUS = Decimal("1.5")
DOMESTIC_BONUS = Decimal("1.0")
MIN_ACCEPTABLE_ALLELE_MATCHES = 9

# --- candidate_rank_score --------------------------------------------------
RANK_W_SCORE = Decimal("0.55")
RANK_W_AGE = Decimal("0.25")
RANK_W_LOGISTICS = Decimal("0.20")
AGE_FACTOR_IDEAL = 27
AGE_FACTOR_SLOPE = Decimal("2.5")
PRIOR_DONATION_PENALTY = Decimal("15")
INTL_BASE_FACTOR = Decimal("55")
TIER_BONUS = Decimal("5")

# --- candidate_pool_materialization ---------------------------------------
DONOR_MIN_AGE = 18
DONOR_MAX_AGE = 60
MIN_PRELIM_SCORE_DEFAULT = Decimal("60.00")
MAX_CANDIDATES_MATERIALIZED = 5
BACKUP_SLOTS = 2

# --- ct_deadline_and_expiry_sweep -----------------------------------------
INTERNATIONAL_GRACE_HOURS = 48
PRIORITY_DEADLINE_REDUCTION_HOURS = 24
MAX_CT_ATTEMPTS = 2

# --- collection_window_derivation -----------------------------------------
CONDITIONING_TO_COLLECTION_MIN_DAYS = 6
CONDITIONING_TO_COLLECTION_MAX_DAYS = 8
METHOD_WINDOW_OFFSETS = {"PBSC": (4, 1), "MARROW": (1, 6)}
VIABILITY_HOURS = {"PBSC": 72, "MARROW": 48}
METHOD_DURATION_MINUTES = {"PBSC": 300, "MARROW": 240}
MIN_CD34_E6_PER_KG = Decimal("2.00")
PLANNED_WINDOW_DAYS = {"PBSC": 6, "MARROW": 8}
PLANNED_WINDOW_DAYS_DEFAULT = 6

# --- center_slot_conflict_detection ---------------------------------------
TURNAROUND_BUFFER_MINUTES = 90

# --- donor calendar / deferral --------------------------------------------
CLEARANCE_FAIL_DEFERRAL_DAYS = 90
ADVERSE_EVENT_DEFERRAL_GRADE = 4
IDM_VALIDITY_DAYS = 30

# --- reimbursement_claim_amount -------------------------------------------
CT_TYPING_FEE_CENTS = 34500
WORKUP_PHYSICAL_FEE_CENTS = 78000
IDM_PANEL_FEE_CENTS = 52500
COLLECTION_FEE_CENTS = {"PBSC": 1450000, "MARROW": 1980000}
COURIER_BASE_CENTS = 265000
COURIER_INTERNATIONAL_SURCHARGE_PCT = Decimal("0.35")
DONOR_LOST_WAGE_PER_DAY_CENTS = 32000
CANCELLATION_FEE_PCT = Decimal("0.40")
INTL_COORDINATION_FEE_PCT = Decimal("0.08")
DISCOUNT_TIER_1_CENTS = 2500000
DISCOUNT_TIER_1_PCT = Decimal("0.05")
DISCOUNT_TIER_2_CENTS = 4000000
DISCOUNT_TIER_2_PCT = Decimal("0.09")
PROVISIONAL_ASSUMED_METHOD = "PBSC"
PROVISIONAL_ASSUMED_WINDOW_DAYS = 6

LINE_ORDER = (
    "CT_TYPING",
    "WORKUP_PHYSICAL",
    "IDM_PANEL",
    "COLLECTION",
    "COURIER",
    "DONOR_LOST_WAGE",
    "CANCELLATION",
)


def rhu(value, places):
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def matched_count(left, right, antigen_level):
    """Multiset intersection size of two two-element allele lists."""
    def reduce(values):
        if antigen_level:
            return [v.split(":")[0] for v in values]
        return list(values)

    left_counter = Counter(reduce(left))
    right_counter = Counter(reduce(right))
    total = 0
    for key, count in left_counter.items():
        total += min(count, right_counter.get(key, 0))
    return total


def age_bonus(age_years):
    if 18 <= age_years <= 25:
        return Decimal("4.0")
    if 26 <= age_years <= 35:
        return Decimal("2.0")
    if 36 <= age_years <= 44:
        return Decimal("0.5")
    return Decimal("0.0")


def allele_matched_alleles(patient_typing, other_typing):
    """Allele-level matched count across the five loci, 0..10."""
    total = 0
    for locus in LOCI:
        total += matched_count(patient_typing[locus], other_typing[locus], False)
    return total


def match_probability_score(patient, donor, registry, donor_typing,
                            ambiguous_loci, variant):
    """PRELIMINARY or CONFIRMED variant of the weighted allele-matching score."""
    weighted_sum = Decimal(0)
    for locus in LOCI:
        antigen = (variant == "PRELIMINARY") and (locus in ambiguous_loci)
        count = matched_count(patient["hla_typing"][locus], donor_typing[locus], antigen)
        weighted_sum += LOCUS_WEIGHTS[locus] * Decimal(count)
    base = Decimal(100) * weighted_sum / LOCUS_WEIGHT_TOTAL
    if variant == "PRELIMINARY":
        penalty = AMBIGUITY_PENALTY_PER_LOCUS * Decimal(len(ambiguous_loci))
    else:
        penalty = Decimal(0)
    bonus = age_bonus(donor["age_years"])
    if donor["cmv_status"] == patient["cmv_status"]:
        bonus += CMV_MATCH_BONUS
    if registry["is_domestic"]:
        bonus += DOMESTIC_BONUS
    raw = base - penalty + bonus
    score = rhu(raw, 2)
    if score < Decimal("0.00"):
        score = Decimal("0.00")
    if score > Decimal("100.00"):
        score = Decimal("100.00")
    return score


def candidate_rank_score(donor, registry, preliminary_score):
    age_factor = Decimal(100) - AGE_FACTOR_SLOPE * Decimal(
        abs(donor["age_years"] - AGE_FACTOR_IDEAL))
    if age_factor < Decimal(0):
        age_factor = Decimal(0)
    if age_factor > Decimal(100):
        age_factor = Decimal(100)
    if registry["is_domestic"]:
        if donor["prior_donation_count"] == 0:
            logistics = Decimal(100)
        else:
            logistics = Decimal(100) - PRIOR_DONATION_PENALTY * Decimal(
                donor["prior_donation_count"])
            if logistics < Decimal(40):
                logistics = Decimal(40)
    else:
        logistics = INTL_BASE_FACTOR + TIER_BONUS * Decimal(registry["cooperation_tier"])
        if logistics > Decimal(70):
            logistics = Decimal(70)
    raw = (RANK_W_SCORE * preliminary_score + RANK_W_AGE * age_factor
           + RANK_W_LOGISTICS * logistics)
    score = rhu(raw, 3)
    if score < Decimal("0.000"):
        score = Decimal("0.000")
    if score > Decimal("100.000"):
        score = Decimal("100.000")
    return score


def ct_deadline(requested_at, registry, priority_flag):
    hours = registry["ct_response_deadline_hours"]
    if not registry["is_domestic"]:
        hours += INTERNATIONAL_GRACE_HOURS
    if priority_flag:
        hours -= PRIORITY_DEADLINE_REDUCTION_HOURS
    return requested_at + timedelta(hours=hours)


def day_count(date_from, date_to):
    return (date_to - date_from).days + 1


def windows_conflict(a_from, a_to, b_from, b_to):
    """Closed inclusive whole-day intervals, capacity 1, no buffer."""
    return a_from <= b_to and b_from <= a_to


def collection_window_dates(collection_date, method):
    before, after = METHOD_WINDOW_OFFSETS[method]
    return (collection_date - timedelta(days=before),
            collection_date + timedelta(days=after))


def buffered_overlap(new_start, new_end, other_start, other_end):
    """Half-open minute intervals; the existing booking carries the buffer."""
    buffered_start = other_start - timedelta(minutes=TURNAROUND_BUFFER_MINUTES)
    buffered_end = other_end + timedelta(minutes=TURNAROUND_BUFFER_MINUTES)
    return new_start < buffered_end and buffered_start < new_end


# --------------------------------------------------------------------------
# Derived counters (PRD 2.10) -- always re-derived, never accumulated.
# --------------------------------------------------------------------------
BOOKING_COMMITTED_STATUSES = ("HELD", "CONFIRMED", "COMPLETED")
CLAIM_COMMITTED_STATUSES = ("PROVISIONAL", "FINALIZED")
BACKUP_LIVE_STATUSES = ("IDENTIFIED", "TYPING_REQUESTED", "TYPING_RESPONDED",
                        "SCREENING_PASSED")


def committed_slot_minutes(center_id):
    total = 0
    for booking in db.bookings.values():
        if booking["collection_center_id"] == center_id and \
                booking["status"] in BOOKING_COMMITTED_STATUSES:
            total += booking["duration_minutes"]
    return total


def blocked_day_count(donor_id):
    total = 0
    for window in db.windows.values():
        if window["donor_id"] == donor_id and window["status"] == "ACTIVE":
            total += window["day_count"]
    return total


def committed_cost_cents(patient_id):
    total = 0
    for claim in db.claims.values():
        if claim["patient_id"] == patient_id and \
                claim["status"] in CLAIM_COMMITTED_STATUSES:
            total += claim["total_usd_cents"]
    return total


def donor_count(registry_id):
    return sum(1 for donor in db.donors.values()
               if donor["registry_id"] == registry_id)


def adverse_event_count(donor_id):
    return sum(1 for row in db.followups.values()
               if row["donor_id"] == donor_id and row["event_type"] == "ADVERSE_EVENT")


def match_pool_size(search_id):
    return sum(1 for c in db.candidates.values()
               if c["search_request_id"] == search_id)


def backup_candidate_count(search_id):
    return sum(1 for c in db.candidates.values()
               if c["search_request_id"] == search_id
               and c["candidate_role"] == "BACKUP"
               and c["status"] in BACKUP_LIVE_STATUSES)


# --------------------------------------------------------------------------
# reimbursement_claim_amount
# --------------------------------------------------------------------------
def claim_amounts(variant, ct_attempt_count, method, window_days,
                  is_domestic, fx_rate, cancellation_charged):
    """Return the seven pinned lines and every derived amount."""
    lines = []
    lines.append(("CT_TYPING", CT_TYPING_FEE_CENTS * ct_attempt_count))
    lines.append(("WORKUP_PHYSICAL", WORKUP_PHYSICAL_FEE_CENTS))
    lines.append(("IDM_PANEL", IDM_PANEL_FEE_CENTS))
    lines.append(("COLLECTION", COLLECTION_FEE_CENTS[method]))
    surcharge = Decimal(0) if is_domestic else COURIER_INTERNATIONAL_SURCHARGE_PCT
    lines.append(("COURIER", rhu_cents(
        Decimal(COURIER_BASE_CENTS) * (Decimal(1) + surcharge))))
    lines.append(("DONOR_LOST_WAGE", DONOR_LOST_WAGE_PER_DAY_CENTS * window_days))
    if variant == "FINAL" and cancellation_charged:
        cancellation = rhu_cents(
            Decimal(COLLECTION_FEE_CENTS[method]) * CANCELLATION_FEE_PCT)
    else:
        cancellation = 0
    lines.append(("CANCELLATION", cancellation))

    subtotal = sum(amount for _, amount in lines)
    if subtotal >= DISCOUNT_TIER_2_CENTS:
        discount_pct = DISCOUNT_TIER_2_PCT
    elif subtotal >= DISCOUNT_TIER_1_CENTS:
        discount_pct = DISCOUNT_TIER_1_PCT
    else:
        discount_pct = Decimal("0")
    discount = rhu_cents(Decimal(subtotal) * discount_pct)
    fee_base = subtotal - discount
    if is_domestic:
        coordination_fee = 0
    else:
        coordination_fee = rhu_cents(Decimal(fee_base) * INTL_COORDINATION_FEE_PCT)
    total = subtotal - discount + coordination_fee
    billed_local = rhu_cents(Decimal(total) / Decimal(fx_rate))
    return {
        "line_items": [{"line_type": name, "amount_usd_cents": amount}
                       for name, amount in lines],
        "subtotal_usd_cents": subtotal,
        "volume_discount_pct": discount_pct,
        "discount_usd_cents": discount,
        "intl_coordination_fee_usd_cents": coordination_fee,
        "total_usd_cents": total,
        "billed_amount_local_cents": billed_local,
        "cancellation_fee_applied": bool(cancellation),
    }
