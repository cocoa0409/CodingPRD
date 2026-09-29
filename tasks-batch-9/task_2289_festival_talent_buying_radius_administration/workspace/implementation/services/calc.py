"""The fourteen calculations of SCAFFOLD section 1.3 / PRD sections 2.7 and 3."""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from fractions import Fraction

from db import db
from validators import stored_date, stored_instant

# ---- pinned constants ------------------------------------------------------ #
EARTH_RADIUS_MILES = 3958.7613
GENRE_CAP = Fraction(40, 100)
GENRE_FACTOR_LOW = Fraction(30, 100)
DRAW_FLOOR_CENTS = 500000
DRAW_CENTS_PER_POINT = 25000
HOSPITALITY_LINE_CAP_CENTS = 150000
TRAVEL_ESCALATION_PCT = Decimal("0.12")
RISK_BLOCK_THRESHOLD = 60
DRAW_PENALTY_RATE = Decimal("0.20")
MAX_NEGOTIATION_ROUNDS = 3
MAX_ADVANCE_SUBMISSIONS = 3
STAGE_CHANNEL_ADVISORY = 96
STAGE_CHANNEL_HARD_MAX = 112
RELEASE_WINDOW_DAYS = 7
RADIUS_WINDOW_MAX_DAYS = 365
RESTRICTED_RATIO = Fraction(85, 100)
LIVE_OFFER_STATES = ("ISSUED", "COUNTERED")
STAGE_OCCUPANT_OFFER_STATES = ("DRAFT", "ISSUED", "COUNTERED")
BILLING_HOLDER_OFFER_STATES = ("DRAFT", "ISSUED", "COUNTERED", "ACCEPTED")
PHASE_LADDER = ("PRESALE", "TIER1_ONSALE", "TIER2_ONSALE", "GA_ONSALE")


# ---- rounding primitives --------------------------------------------------- #
def dec(value):
    return Decimal(str(value))


def round_half_up(value):
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def round_half_up_2(value):
    return dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


# ---- collection helpers ---------------------------------------------------- #
def sorted_rows(rows, keys):
    """keys: list of (field, reverse). created_at (via _seq) is the final break."""
    result = list(rows)
    result.sort(key=lambda r: r["_seq"])
    for field, reverse in reversed(keys):
        result.sort(key=lambda r: r[field], reverse=reverse)
    return result


def festival_tiers(festival_id):
    return [t for t in db.budget_tiers.values() if t["festival_id"] == festival_id]


def festival_bookings(festival_id):
    return [b for b in db.bookings.values() if b["festival_id"] == festival_id]


def tier_bookings(tier_id):
    return [b for b in db.bookings.values() if b["budget_tier_id"] == tier_id]


def stage_bookings(stage_id):
    return [b for b in db.bookings.values() if b["stage_id"] == stage_id]


def booking_rider_items(booking_id):
    return [r for r in db.rider_items.values() if r["booking_id"] == booking_id]


def booking_installments(booking_id):
    return [p for p in db.payment_installments.values() if p["booking_id"] == booking_id]


def booking_advance_packets(booking_id):
    return [a for a in db.advance_packets.values() if a["booking_id"] == booking_id]


def clause_for_offer(offer_id):
    for clause in db.radius_clauses.values():
        if clause["offer_id"] == offer_id:
            return clause
    return None


def clause_for_booking(booking_id):
    for clause in db.radius_clauses.values():
        if clause["booking_id"] == booking_id:
            return clause
    return None


def clauses_for_booking(booking_id):
    return [c for c in db.radius_clauses.values() if c["booking_id"] == booking_id]


def artist_performances(artist_id):
    return [
        p for p in db.competing_performances.values() if p["artist_id"] == artist_id
    ]


# ---- 1. tier_allocation_waterfall ----------------------------------------- #
def contingency_reserve_cents(talent_budget_cents, contingency_reserve_pct):
    return round_half_up(dec(talent_budget_cents) * dec(contingency_reserve_pct))


def allocatable_from_budget(talent_budget_cents, contingency_reserve_pct):
    return talent_budget_cents - contingency_reserve_cents(
        talent_budget_cents, contingency_reserve_pct
    )


def waterfall_order(festival_id):
    return sorted_rows(festival_tiers(festival_id), [("tier_rank", False)])


def allocation_pct_closes(tiers):
    if not tiers:
        return False
    total = sum(dec(t["allocation_pct"]) for t in tiers)
    return abs(total - Decimal("1.00")) <= Decimal("1e-9")


def run_waterfall(festival, tiers):
    """Floor per tier; the whole remainder lands on the lowest tier_rank."""
    allocatable = festival["allocatable_budget_cents"]
    figures = []
    for tier in tiers:
        figures.append(floor_int(dec(allocatable) * dec(tier["allocation_pct"])))
    remainder = allocatable - sum(figures)
    if figures:
        figures[0] += remainder
    return figures


# ---- 2. genre_balance_share ----------------------------------------------- #
def genre_committed_share(festival, genre, evaluated_offer, include_evaluated):
    numerator = 0
    for booking in festival_bookings(festival["id"]):
        if booking["contract_status"] == "CANCELLED":
            continue
        artist = db.artists.get(booking["artist_id"])
        if artist is not None and artist["primary_genre"] == genre:
            numerator += booking["guarantee_cents"]
    evaluated_id = evaluated_offer["id"] if evaluated_offer else None
    for offer in db.offers.values():
        if offer["festival_id"] != festival["id"]:
            continue
        if offer["id"] == evaluated_id:
            continue
        if offer["status"] not in LIVE_OFFER_STATES:
            continue
        artist = db.artists.get(offer["artist_id"])
        if artist is not None and artist["primary_genre"] == genre:
            numerator += offer["guarantee_cents"]
    if include_evaluated and evaluated_offer is not None:
        numerator += evaluated_offer["guarantee_cents"]
    return Fraction(numerator, festival["allocatable_budget_cents"])


def genre_factor_for_share(share):
    if share <= GENRE_FACTOR_LOW:
        return Decimal("1.00")
    if share <= GENRE_CAP:
        return Decimal("0.85")
    return Decimal("0.60")


# ---- 3. offer_guarantee_ceiling ------------------------------------------- #
def guarantee_ceiling(festival, tier, artist, evaluated_offer):
    tier_headroom = tier["allocation_cents"] - tier["committed_cents"]
    festival_headroom = (
        festival["allocatable_budget_cents"] - festival["committed_budget_cents"]
    )
    share = genre_committed_share(
        festival, artist["primary_genre"], evaluated_offer, include_evaluated=False
    )
    factor = genre_factor_for_share(share)
    draw_component = max(
        DRAW_FLOOR_CENTS, artist["draw_score"] * DRAW_CENTS_PER_POINT
    )
    scaled = floor_int(dec(draw_component) * factor)
    ceiling = min(tier_headroom, festival_headroom, scaled)
    return ceiling, factor


# ---- 4. rider_cost_estimate ---------------------------------------------- #
def rider_line_cost(item):
    effective_unit = (
        item["substitute_unit_cost_cents"]
        if item["approval_status"] == "SUBSTITUTED"
        and item["substitute_unit_cost_cents"] is not None
        else item["unit_cost_cents"]
    )
    escalation = (
        TRAVEL_ESCALATION_PCT if item["category"] == "TRAVEL" else Decimal("0")
    )
    raw = dec(item["quantity"]) * dec(effective_unit) * (Decimal("1") + escalation)
    return round_half_up(raw)


def rider_totals(booking_id):
    proposed = 0
    contracted = 0
    priced = 0
    capped = 0
    zeroed = 0
    for item in booking_rider_items(booking_id):
        status = item["approval_status"]
        line = item["line_cost_cents"]
        if status in ("PROPOSED", "APPROVED", "SUBSTITUTED"):
            proposed += line
        if status in ("APPROVED", "SUBSTITUTED"):
            if item["is_promoter_provided"]:
                zeroed += 1
                continue
            priced += 1
            if item["category"] == "HOSPITALITY" and line > HOSPITALITY_LINE_CAP_CENTS:
                capped += 1
                contracted += HOSPITALITY_LINE_CAP_CENTS
            else:
                contracted += line
    return {
        "proposed_scope_cents": proposed,
        "contracted_scope_cents": contracted,
        "priced_line_count": priced,
        "capped_line_count": capped,
        "zeroed_line_count": zeroed,
    }


# ---- 5. artist_radius_risk_score ----------------------------------------- #
def risk_components(artist):
    reported = 0
    breaches = 0
    for report in artist_performances(artist["id"]):
        if report["status"] == "REPORTED" and report["conflict_assessment"] == "CONFLICT":
            reported += 1
        if report["status"] == "VIOLATION":
            breaches += 1
    draw_penalty = round_half_up(DRAW_PENALTY_RATE * dec(100 - artist["draw_score"]))
    strict = min(100, 12 * reported + 25 * breaches + draw_penalty)
    adjudicated = min(100, 25 * breaches + draw_penalty)
    return {
        "reported_conflict_count": reported,
        "radius_breach_count": breaches,
        "draw_penalty": draw_penalty,
        "strict_risk_score": strict,
        "adjudicated_risk_score": adjudicated,
    }


# ---- 6. radius_conflict_detection ---------------------------------------- #
def haversine_miles(lat1, lon1, lat2, lon2):
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    d_phi = math.radians(float(lat2) - float(lat1))
    d_lambda = math.radians(float(lon2) - float(lon1))
    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def clause_market(clause):
    """A clause measures from the market of the festival its offer belongs to."""
    offer = db.offers.get(clause["offer_id"])
    if offer is None:
        return None
    return db.festivals.get(offer["festival_id"])


def detect_conflict(performance):
    perf_date = stored_date(performance["performance_date"])
    candidates = []
    for clause in db.radius_clauses.values():
        if clause["artist_id"] != performance["artist_id"]:
            continue
        if clause["enforcement_status"] != "ACTIVE":
            continue
        start = stored_date(clause["window_start_date"])
        end = stored_date(clause["window_end_date"])
        if perf_date < start or perf_date > end:
            continue
        scope = clause["exclusivity_scope"]
        if scope == "TICKETED_ONLY" and not performance["is_ticketed"]:
            continue
        if scope == "FESTIVAL_ONLY" and not performance["is_festival"]:
            continue
        festival = clause_market(clause)
        if festival is None:
            continue
        distance = round_half_up_2(
            haversine_miles(
                festival["market_latitude"],
                festival["market_longitude"],
                performance["venue_latitude"],
                performance["venue_longitude"],
            )
        )
        if distance > dec(clause["radius_miles"]):
            continue
        candidates.append((clause, distance))
    if not candidates:
        return None, None
    ordered = list(candidates)
    ordered.sort(key=lambda pair: pair[0]["_seq"])
    ordered.sort(key=lambda pair: stored_date(pair[0]["window_start_date"]))
    ordered.sort(key=lambda pair: dec(pair[0]["radius_miles"]), reverse=True)
    winner, distance = ordered[0]
    return winner, distance


# ---- 7/8. stage interval collision and day load -------------------------- #
def _stage_offer_occupants(stage_id, exclude_offer_id, states):
    return [
        o
        for o in db.offers.values()
        if o["stage_id"] == stage_id
        and o["status"] in states
        and o["id"] != exclude_offer_id
    ]


def stage_interval_conflict(stage, start, end, exclude_offer_id):
    buffer_delta = timedelta(minutes=stage["changeover_buffer_minutes"])
    intervals = []
    for offer in _stage_offer_occupants(
        stage["id"], exclude_offer_id, STAGE_OCCUPANT_OFFER_STATES
    ):
        intervals.append(
            (stored_instant(offer["slot_start_utc"]), stored_instant(offer["slot_end_utc"]))
        )
    for booking in stage_bookings(stage["id"]):
        if booking["contract_status"] == "CANCELLED":
            continue
        intervals.append(
            (
                stored_instant(booking["slot_start_utc"]),
                stored_instant(booking["slot_end_utc"]),
            )
        )
    for other_start, other_end in intervals:
        if start < other_end + buffer_delta and other_start < end + buffer_delta:
            return True
    return False


def stage_day_load(stage, slot_start, set_length_minutes, exclude_offer_id):
    buffer_minutes = stage["changeover_buffer_minutes"]
    day = slot_start.date()
    total = 0
    for offer in _stage_offer_occupants(
        stage["id"], exclude_offer_id, STAGE_OCCUPANT_OFFER_STATES
    ):
        if stored_instant(offer["slot_start_utc"]).date() == day:
            total += offer["set_length_minutes"] + buffer_minutes
    for booking in stage_bookings(stage["id"]):
        if booking["contract_status"] == "CANCELLED":
            continue
        if stored_instant(booking["slot_start_utc"]).date() == day:
            total += booking["set_length_minutes"] + buffer_minutes
    total += set_length_minutes + buffer_minutes
    return total


def curfew_minute_of(slot_start, slot_end):
    midnight = slot_start.replace(hour=0, minute=0, second=0, microsecond=0)
    return int((slot_end - midnight).total_seconds() // 60)


def billing_position_taken(stage_id, day, billing_position, exclude_offer_id):
    for offer in db.offers.values():
        if offer["stage_id"] != stage_id or offer["id"] == exclude_offer_id:
            continue
        if offer["status"] not in BILLING_HOLDER_OFFER_STATES:
            continue
        if offer["billing_position"] != billing_position:
            continue
        if stored_instant(offer["slot_start_utc"]).date() == day:
            return True
    for booking in stage_bookings(stage_id):
        if booking["contract_status"] == "CANCELLED":
            continue
        if booking["billing_position"] != billing_position:
            continue
        if stored_instant(booking["slot_start_utc"]).date() == day:
            return True
    return False


def artist_double_booked(festival_id, artist_id, day, exclude_offer_id):
    for offer in db.offers.values():
        if offer["festival_id"] != festival_id or offer["artist_id"] != artist_id:
            continue
        if offer["id"] == exclude_offer_id:
            continue
        if offer["status"] not in LIVE_OFFER_STATES:
            continue
        if stored_instant(offer["slot_start_utc"]).date() == day:
            return True
    for booking in festival_bookings(festival_id):
        if booking["artist_id"] != artist_id:
            continue
        if booking["contract_status"] == "CANCELLED":
            continue
        if stored_instant(booking["slot_start_utc"]).date() == day:
            return True
    return False


# ---- 9. payment_schedule_build ------------------------------------------- #
def deposit_pct_for(days_until_show):
    if days_until_show >= 120:
        return Decimal("0.50")
    if days_until_show >= 60:
        return Decimal("0.40")
    return Decimal("0.25")


def payment_schedule(booking, festival, clock):
    event_start = stored_date(festival["event_start_date"])
    today = clock.date()
    days_until_show = (event_start - today).days
    pct = deposit_pct_for(days_until_show)
    deposit = round_half_up(dec(booking["guarantee_cents"]) * pct)
    balance = booking["guarantee_cents"] - deposit
    deposit_due = max(today, min(today + timedelta(days=30), event_start - timedelta(days=14)))
    balance_due = stored_instant(booking["slot_start_utc"]).date()
    return {
        "deposit_cents": deposit,
        "balance_cents": balance,
        "deposit_due_date": deposit_due,
        "balance_due_date": balance_due,
    }


# ---- 10. settlement_total ------------------------------------------------ #
def promoter_share_for(gross_pre_share_cents):
    if gross_pre_share_cents >= 5000000:
        return Decimal("0.60")
    if gross_pre_share_cents >= 2000000:
        return Decimal("0.75")
    return Decimal("0.90")


def settlement_breakdown(booking):
    rider = booking["rider_estimate_cents"]
    clause = clause_for_booking(booking["id"])
    waiver_fee = clause["waiver_fee_cents"] if clause is not None else 0
    gross_pre_share = booking["guarantee_cents"] + rider + waiver_fee
    share = promoter_share_for(gross_pre_share)
    reimbursed = round_half_up(dec(rider) * share)
    total = (
        booking["guarantee_cents"]
        + reimbursed
        + waiver_fee
        - booking["deposit_paid_cents"]
    )
    return {
        "guarantee_cents": booking["guarantee_cents"],
        "rider_estimate_cents": rider,
        "waiver_fee_cents": waiver_fee,
        "gross_pre_share_cents": gross_pre_share,
        "promoter_share_pct": float(share),
        "reimbursed_rider_cents": reimbursed,
        "deposit_paid_cents": booking["deposit_paid_cents"],
        "settlement_total_cents": total,
    }


# ---- 11. deposit_recovery ------------------------------------------------ #
def contractual_recovery(booking, festival, cancelled_at, cancelling_party):
    event_start = stored_date(festival["event_start_date"])
    days_until_show = (event_start - cancelled_at.date()).days
    if cancelling_party == "ARTIST":
        party_pct = Decimal("1.00")
    elif cancelling_party == "FORCE_MAJEURE":
        party_pct = Decimal("0.50")
    else:
        party_pct = Decimal("0.00")
    if cancelling_party == "ARTIST":
        liquidated_pct = Decimal("0.10") if days_until_show < 30 else Decimal("0.05")
    else:
        liquidated_pct = Decimal("0.00")
    deposit_part = round_half_up(dec(booking["deposit_paid_cents"]) * party_pct)
    liquidated_part = round_half_up(dec(booking["guarantee_cents"]) * liquidated_pct)
    return deposit_part + liquidated_part


def actual_recovered(booking):
    rows = booking_installments(booking["id"])
    rows.sort(key=lambda r: r["_seq"])
    rows.sort(key=lambda r: stored_date(r["due_date"]))
    running = 0
    for row in rows:
        if row["status"] == "RECOVERED":
            running += row["recovered_cents"]
    ceiling = booking["contractual_recovery_cents"]
    return min(running, ceiling)


# ---- 12. festival_lineup_posture ---------------------------------------- #
def committed_ratio(festival):
    return Fraction(
        festival["committed_budget_cents"], festival["allocatable_budget_cents"]
    )


def lineup_posture(festival):
    ratio = committed_ratio(festival)
    tiers = festival_tiers(festival["id"])
    all_closed = bool(tiers) and all(t["status"] == "CLOSED" for t in tiers)
    if festival["announcement_phase"] == "GA_ONSALE" or ratio >= 1 or all_closed:
        return "FROZEN"
    if ratio >= RESTRICTED_RATIO:
        return "RESTRICTED"
    return "OPEN"
