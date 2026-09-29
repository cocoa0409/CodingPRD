"""The fourteen calculation rules of the disposition engine (PRD 3.2 - 3.10)."""

from decimal import Decimal

import clockmod
import db
from services import derive
from services.money import round_half_up

# statutory_window_deadlines
NOTICE_RESPONSE_WINDOW_MIN_DAYS = 60
NOTICE_RESPONSE_WINDOW_MAX_DAYS = 90
NOTICE_RESPONSE_WINDOW_DEFAULT_DAYS = 60
GOOD_FAITH_NEGOTIATION_DAYS = 90
TIMELY_RESPONSE_DAYS = 15
APPRAISAL_VALIDITY_DAYS = 365
REOFFER_COOLING_OFF_DAYS = 30
CHALLENGE_WINDOW_DAYS = 30
REOFFER_LIMIT = 2

# good_faith_compliance_score
ENGAGEMENT_WEIGHT = Decimal(45)
TIMELINESS_WEIGHT = Decimal(30)
CONCESSION_WEIGHT = Decimal(25)
CONCESSION_PARTIAL = Decimal(12)
REQUIRED_ROUNDS = 3
NEAR_BAND_MULT = Decimal("1.05")
WIDE_BAND_MULT = Decimal("1.20")
PREMATURE_IMPASSE_PENALTY = Decimal(15)
GOOD_FAITH_PASS_SCORE = 70
INTERIM_SCORE_CAP = 75

# minimum_price_determination
AH_WRITE_DOWN = Decimal("0.35")
REOFFER_DISCOUNT_STEP = Decimal("0.10")
REOFFER_DISCOUNT_CAP = Decimal("0.20")

# required_bid_deposit
BID_DEPOSIT_PCT = Decimal("0.05")
BID_DEPOSIT_FLOOR_CENTS = 5000000

# challenge_deposit_requirement
CHALLENGE_DEPOSIT_PCT = Decimal("0.01")
CHALLENGE_DEPOSIT_MIN_CENTS = 100000
CHALLENGE_DEPOSIT_MAX_CENTS = 2500000
CHALLENGE_DELTA_PCT = Decimal("0.05")

# appraiser_engagement_load
APPRAISER_MAX_CONCURRENT_ENGAGEMENTS = 2

# environmental_recirculation_window
ENV_CIRCULATION_MIN_DAYS = 30
RECIRCULATION_BUFFER_DAYS = 30

# net_proceeds_determination
CURATIVE_RECOVERY_CAP_PCT = Decimal("0.15")


# --------------------------------------------------------------------------
# 1. minimum_price_determination
# --------------------------------------------------------------------------

def minimum_price(parcel, declaration, variant):
    """Return the frozen minimum price, or None when no ACCEPTED appraisal exists."""
    appraisal = derive.accepted_appraisal(parcel["id"])
    if appraisal is None or appraisal.get("appraised_value_cents") is None:
        return None
    base = Decimal(appraisal["appraised_value_cents"])
    cure_deduction = derive.cured_cost_total(parcel["id"])
    write_down = AH_WRITE_DOWN if variant == "AFFORDABLE_HOUSING_PREFERENCE" else Decimal(0)
    reoffer_count = declaration.get("reoffer_count") or 0
    reoffer_discount = min(Decimal(reoffer_count) * REOFFER_DISCOUNT_STEP, REOFFER_DISCOUNT_CAP)
    gross = round_half_up(base * (Decimal(1) - write_down) * (Decimal(1) - reoffer_discount))
    raw = gross - cure_deduction
    if variant == "AFFORDABLE_HOUSING_PREFERENCE":
        return max(raw, 0)
    return max(raw, parcel["book_value_cents"])


def agreed_ah_offer(declaration_id):
    """The AGREED preference offer on the declaration, when one exists."""
    for offer in derive.declaration_offers(declaration_id):
        if offer["negotiation_status"] == "AGREED":
            return offer
    return None


def offering_price_variant(declaration, offering_type):
    if offering_type == "COMPETITIVE_SALE":
        return "MARKET_FLOOR"
    agreed = agreed_ah_offer(declaration["id"])
    if agreed is not None and agreed["preference_category"] == "AFFORDABLE_HOUSING":
        return "AFFORDABLE_HOUSING_PREFERENCE"
    return "MARKET_FLOOR"


def offer_price_variant(offer):
    if offer["preference_category"] == "AFFORDABLE_HOUSING":
        return "AFFORDABLE_HOUSING_PREFERENCE"
    return "MARKET_FLOOR"


def recompute_offer_minimum(offer):
    declaration = db.get("declarations", offer["declaration_id"])
    parcel = db.get("parcels", declaration["parcel_id"])
    offer["ah_minimum_price_cents"] = minimum_price(
        parcel, declaration, offer_price_variant(offer))


# --------------------------------------------------------------------------
# 6. required_bid_deposit
# --------------------------------------------------------------------------

def required_bid_deposit(minimum_price_cents):
    product = round_half_up(Decimal(minimum_price_cents) * BID_DEPOSIT_PCT)
    return max(product, BID_DEPOSIT_FLOOR_CENTS)


# --------------------------------------------------------------------------
# 7. challenge_deposit_requirement
# --------------------------------------------------------------------------

def challenge_required_deposit(appraised_value_cents):
    raw = round_half_up(Decimal(appraised_value_cents) * CHALLENGE_DEPOSIT_PCT)
    return min(max(raw, CHALLENGE_DEPOSIT_MIN_CENTS), CHALLENGE_DEPOSIT_MAX_CENTS)


def challenge_delta_threshold(appraised_value_cents):
    return round_half_up(Decimal(appraised_value_cents) * CHALLENGE_DELTA_PCT)


# --------------------------------------------------------------------------
# 5. good_faith_compliance_score
# --------------------------------------------------------------------------

def good_faith_score(offer, variant):
    rounds = derive.offer_rounds(offer["id"])
    officer_rounds = [r for r in rounds if r["party"] == "CUSTODIAN_AGENCY"]
    officer_count = len(officer_rounds)
    timely_officer_count = len([r for r in officer_rounds if r.get("is_timely") is True])

    engagement = ENGAGEMENT_WEIGHT * min(officer_count, REQUIRED_ROUNDS) / REQUIRED_ROUNDS
    timeliness = TIMELINESS_WEIGHT * min(timely_officer_count, REQUIRED_ROUNDS) / REQUIRED_ROUNDS

    concession = Decimal(0)
    penalty = Decimal(0)
    if variant == "FINAL":
        concession = _concession_points(offer, officer_rounds)
        penalty = _premature_impasse_penalty(offer)

    total = engagement + timeliness + concession - penalty
    score = round_half_up(total)
    score = max(0, min(100, score))
    if variant == "INTERIM":
        score = min(score, INTERIM_SCORE_CAP)
    return score


def _concession_points(offer, officer_rounds):
    if not officer_rounds:
        return Decimal(0)
    floor_price = offer.get("ah_minimum_price_cents")
    if floor_price is None:
        return Decimal(0)
    latest = max(officer_rounds, key=lambda r: r["round_number"])
    price = latest["price_offered_cents"]
    near_band = round_half_up(Decimal(floor_price) * NEAR_BAND_MULT)
    wide_band = round_half_up(Decimal(floor_price) * WIDE_BAND_MULT)
    if price <= near_band:
        return CONCESSION_WEIGHT
    if price <= wide_band:
        return CONCESSION_PARTIAL
    return Decimal(0)


def _premature_impasse_penalty(offer):
    if offer["negotiation_status"] != "IMPASSE":
        return Decimal(0)
    concluded_at = offer.get("_concluded_at")
    deadline = offer.get("negotiation_deadline_at")
    if concluded_at is None or deadline is None:
        return Decimal(0)
    if concluded_at < deadline:
        return PREMATURE_IMPASSE_PENALTY
    return Decimal(0)


def recompute_interim_score(offer):
    offer["interim_good_faith_score"] = good_faith_score(offer, "INTERIM")


# --------------------------------------------------------------------------
# 10. appraiser_engagement_load  (closed intervals: shared endpoint overlaps)
# --------------------------------------------------------------------------

def intersecting_engagements(appraiser_id, start, end, exclude_id=None):
    hits = []
    for row in db.all_rows("appraisals"):
        if row["appraiser_id"] != appraiser_id:
            continue
        if exclude_id is not None and row["id"] == exclude_id:
            continue
        if row["status"] not in derive.IN_FLIGHT_APPRAISAL_STATUSES:
            continue
        if closed_intervals_overlap(row["engagement_start_on"], row["engagement_end_on"],
                                    start, end):
            hits.append(row)
    return hits


def closed_intervals_overlap(a_start, a_end, b_start, b_end):
    """NOT (a ends before b starts OR a starts after b ends)."""
    return not (a_end < b_start or a_start > b_end)


# --------------------------------------------------------------------------
# 11. environmental_recirculation_window
# --------------------------------------------------------------------------

def circulation_long_enough(start, end):
    return clockmod.whole_days_between(start, end) >= ENV_CIRCULATION_MIN_DAYS


def circulation_overlaps(declaration_id, start, end, exclude_id=None):
    for row in db.all_rows("environmental_reviews"):
        if row["declaration_id"] != declaration_id:
            continue
        if exclude_id is not None and row["id"] == exclude_id:
            continue
        if row.get("circulation_start_on") is None or row.get("circulation_end_on") is None:
            continue
        if closed_intervals_overlap(row["circulation_start_on"], row["circulation_end_on"],
                                    start, end):
            return True
    return False


# --------------------------------------------------------------------------
# 12. offering_window_placement  (half-open: adjacency is legal)
# --------------------------------------------------------------------------

def offering_window_conflict(parcel_id, open_at, close_at, exclude_id=None):
    for row in db.all_rows("offerings"):
        if exclude_id is not None and row["id"] == exclude_id:
            continue
        if row["status"] not in derive.LIVE_OFFERING_STATUSES:
            continue
        declaration = db.get("declarations", row["declaration_id"])
        if declaration is None or declaration["parcel_id"] != parcel_id:
            continue
        if open_at < row["bid_close_at"] and row["bid_open_at"] < close_at:
            return True
    return False


# --------------------------------------------------------------------------
# 8. award_selection
# --------------------------------------------------------------------------

def award_candidates(offering):
    candidates = []
    for bid in db.all_rows("bids"):
        if bid["offering_id"] != offering["id"]:
            continue
        if bid["qualification_status"] != "QUALIFIED":
            continue
        if bid["amount_cents"] < offering["minimum_price_cents"]:
            continue
        if bid["deposit_amount_cents"] < offering["required_deposit_cents"]:
            continue
        bidder = db.get("bidders", bid["bidder_id"])
        if bidder is None or bidder["debarment_status"] != "CLEAR":
            continue
        candidates.append(bid)
    candidates.sort(key=lambda b: (-b["amount_cents"], b["submitted_at"], b["created_at"]))
    return candidates


# --------------------------------------------------------------------------
# 2. net_proceeds_determination
# --------------------------------------------------------------------------

def provisional_net(conveyance):
    return (conveyance["sale_price_cents"]
            - conveyance["closing_costs_cents"]
            - conveyance["broker_fee_cents"])


def freeze_net_proceeds(conveyance):
    provisional = provisional_net(conveyance)
    cap = round_half_up(Decimal(provisional) * CURATIVE_RECOVERY_CAP_PCT)
    incurred = derive.cured_cost_total(conveyance["parcel_id"])
    recoverable = min(incurred, cap)
    conveyance["recoverable_curative_cost_cents"] = recoverable
    conveyance["net_proceeds_cents"] = provisional - recoverable


# --------------------------------------------------------------------------
# 14. bidder_escrow_ledger
# --------------------------------------------------------------------------

def credit_funding(bidder, amount_cents):
    bidder["available_funds_cents"] += amount_cents
    bidder["lifetime_deposits_cents"] += amount_cents
    db.touch(bidder)


def hold_deposit(bidder, amount_cents):
    bidder["available_funds_cents"] -= amount_cents
    bidder["escrow_held_cents"] += amount_cents
    db.touch(bidder)


def release_deposit(bidder, amount_cents):
    bidder["escrow_held_cents"] -= amount_cents
    bidder["available_funds_cents"] += amount_cents
    db.touch(bidder)


def apply_deposit(bidder, amount_cents):
    bidder["escrow_held_cents"] -= amount_cents
    db.touch(bidder)


def release_bid_deposit(bid):
    """Move a HELD deposit back to the bidder's spendable cash."""
    if bid.get("deposit_status") != "HELD":
        return
    bid["deposit_status"] = "RELEASED"
    bidder = db.get("bidders", bid["bidder_id"])
    if bidder is not None:
        release_deposit(bidder, bid["deposit_amount_cents"])
