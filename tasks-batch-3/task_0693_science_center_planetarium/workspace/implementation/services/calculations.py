"""The five money calculations (SCAFFOLD §1.3, PRD §3.4/§3.5/§3.6/§3.7/§3.2).

All monetary amounts are integer cents. round_half_up is applied PER SEAT
before multiplying by party_size (round-then-sum, never sum-then-round).
Deposits are floored.
"""
import math

from services.common import round_half_up

# show_admission_pricing constants
PATRON_BASE_DISCOUNT_PCT = 1.00
FAMILY_DISCOUNT_PCT = 0.50
INDIVIDUAL_BASE_DISCOUNT_PCT = 0.25

# group_invoice_total constants
CHAPERONE_FREE_RATIO = 10
GROUP_STUDENT_PCT = 0.30
GROUP_DEPOSIT_PCT = 0.25

# program_tuition_pricing constants
PATRON_TUITION_PCT = 0.40
STD_MEMBER_TUITION_PCT = 0.15
EARLY_BIRD_SEATS = 3
EARLY_BIRD_OFF_CENTS = 1000

# rental_quote constants
GUEST_TIER_1 = 20
RATE_1_CENTS = 500
RATE_2_CENTS = 300
RENTAL_DEPOSIT_PCT = 0.25

# astc_reciprocal_eligibility constants
CENTER_ZIP_PREFIX = "606"


def show_admission_pricing(show, party_size, membership):
    """Compute (gross, member_discount, net) cents for a ShowBooking hold.

    PRD §3.4: per-seat discount rounded to whole cents BEFORE multiplying by
    party_size. Discount is 0 for walk-ups and for cards not currently ACTIVE.
    """
    per_seat = show["base_price_cents"] + show["feature_surcharge_cents"]
    gross = party_size * per_seat

    if membership is None:
        discount = 0
    elif membership["status"] != "ACTIVE":
        discount = 0
    elif membership["tier"] == "PATRON":
        # 100% off base; feature surcharge never discounted.
        discount = party_size * show["base_price_cents"]
    elif membership["tier"] == "FAMILY":
        # 50% off the per-seat total (base + surcharge), rounded per seat.
        per_seat_disc = round_half_up(per_seat * FAMILY_DISCOUNT_PCT)
        discount = party_size * per_seat_disc
    else:  # INDIVIDUAL
        # 25% off base only; surcharge full price; rounded per seat.
        per_seat_disc = round_half_up(show["base_price_cents"] * INDIVIDUAL_BASE_DISCOUNT_PCT)
        discount = party_size * per_seat_disc

    net = gross - discount
    return gross, discount, net


def group_grand_total(show, s_count, c_count):
    """Grand total over a student count and chaperone count (PRD §3.5)."""
    per_seat = show["base_price_cents"] + show["feature_surcharge_cents"]
    free_chaperones = math.floor(s_count / CHAPERONE_FREE_RATIO)
    billable_chaperones = max(0, c_count - free_chaperones)
    student_seat = round_half_up(per_seat * (1 - GROUP_STUDENT_PCT))
    students_total = s_count * student_seat
    chaperones_total = billable_chaperones * show["base_price_cents"]
    return students_total + chaperones_total


def group_deposit(show, student_count, chaperone_count):
    """DEPOSIT variant: 25% of grand total over requested counts, floored."""
    grand = group_grand_total(show, student_count, chaperone_count)
    return math.floor(grand * GROUP_DEPOSIT_PCT)


def group_balance(show, actual_student_count, actual_chaperone_count, deposit_cents):
    """FINAL variant: grand total over actual counts minus deposit."""
    grand = group_grand_total(show, actual_student_count, actual_chaperone_count)
    return grand - deposit_cents


def program_tuition_pricing(program, membership, enrolled_count_before):
    """Tuition snapshotted at enrollment (PRD §3.6).

    Percentage discount (round half up) first, then flat early-bird, then floor
    at 0. enrolled_count_before is the session's enrolled_count observed
    immediately BEFORE this enrollment is committed.
    """
    base = program["tuition_cents"]
    if membership is None or membership["status"] != "ACTIVE":
        charged = base
    elif membership["tier"] == "PATRON":
        charged = round_half_up(base * (1 - PATRON_TUITION_PCT))
    else:  # FAMILY or INDIVIDUAL
        charged = round_half_up(base * (1 - STD_MEMBER_TUITION_PCT))

    if enrolled_count_before < EARLY_BIRD_SEATS:
        charged = max(0, charged - EARLY_BIRD_OFF_CENTS)
    return charged


def rental_grand_total(rental, guests):
    """Marginal two-tier guest charge on the flat hall fee (PRD §3.7)."""
    tier1 = min(guests, GUEST_TIER_1)
    tier2 = max(0, guests - GUEST_TIER_1)
    guest_charge = tier1 * RATE_1_CENTS + tier2 * RATE_2_CENTS
    return rental["base_rental_cents"] + guest_charge


def rental_deposit(rental, guest_count):
    """DEPOSIT variant: 25% of grand total over estimated guests, floored."""
    grand = rental_grand_total(rental, guest_count)
    return math.floor(grand * RENTAL_DEPOSIT_PCT)


def rental_total(rental, actual_guest_count):
    """FINAL variant: full grand total over the actual guest count."""
    return rental_grand_total(rental, actual_guest_count)


def astc_reciprocal_admit(membership):
    """ASTC 90-mile reciprocal admission determination (PRD §3.2).

    Admitted free iff the card is ASTC-eligible AND currently ACTIVE AND its
    home_zip does NOT begin with the center's prefix (606).
    """
    if not membership.get("astc_eligible"):
        return False
    if membership["status"] != "ACTIVE":
        return False
    if str(membership.get("home_zip", ""))[0:3] == CENTER_ZIP_PREFIX:
        return False
    return True
