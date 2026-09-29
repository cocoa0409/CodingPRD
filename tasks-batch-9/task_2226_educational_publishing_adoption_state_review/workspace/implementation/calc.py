"""Calculation rules (scaffold 1.3 / PRD 2.9, 3.4, 3.6, 3.7, 3.8, 3.9)."""

from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 80

# --- constants -------------------------------------------------------------
DEPTH_MULTIPLIERS = {
    "MENTION": Decimal("0.40"),
    "PRACTICE": Decimal("0.70"),
    "MASTERY": Decimal("1.00"),
}

MAX_TOTAL_DISCOUNT_PCT = Decimal("0.20")

FREIGHT_WAIVER_THRESHOLD_CENTS = 2500000
FREIGHT_RATE = Decimal("0.015")
ADOPTED_LIST_REBATE_PCT = Decimal("0.02")
DEFAULT_OPEN_TERRITORY_SEAT_CENTS = 1200

CONDITIONS_WEIGHT = Decimal("0.5")
RECOMMEND_RATIO_THRESHOLD = Decimal("0.6667")

PENALTY_PROHIBITED = 25
PENALTY_MISSING_TOPIC = 10
PENALTY_CRITICAL = 15
PENALTY_OVERDUE = 5
BLOCK_THRESHOLD = 70

MAX_REVISION_ROUNDS = 3
ARCHIVE_DELAY_DAYS = 30
SECONDS_PER_DAY = 86400


def round_half_up(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def round_cents(value):
    return int(round_half_up(Decimal(value), 0))


# --- state_net_price -------------------------------------------------------
def volume_discount(projected_adoption_units):
    if projected_adoption_units >= 20000:
        return Decimal("0.12")
    if projected_adoption_units >= 5000:
        return Decimal("0.07")
    return Decimal("0.00")


def term_discount(term_years):
    if term_years >= 5:
        return Decimal("0.06")
    if term_years >= 3:
        return Decimal("0.03")
    return Decimal("0.00")


def bundle_discount(bundle):
    if bundle is None:
        return Decimal("0.00")
    if bundle["component_count"] >= 4:
        return Decimal("0.09")
    if bundle["component_count"] >= 2:
        return Decimal("0.05")
    return Decimal("0.00")


def state_net_price(base_price_cents, term_years, annual_escalator_bps,
                    projected_adoption_units, bundle):
    """Returns the discount tiers plus the net and average annual price."""
    vol = volume_discount(projected_adoption_units)
    term = term_discount(term_years)
    bund = bundle_discount(bundle)
    total = min(MAX_TOTAL_DISCOUNT_PCT, vol + term + bund)
    total = round_half_up(total, 2)

    multiplier = Decimal(1) + (Decimal(annual_escalator_bps) / Decimal(10000))
    discounted_base = Decimal(base_price_cents) * (Decimal(1) - total)

    net = 0
    factor = Decimal(1)
    for _year in range(term_years):
        net += round_cents(discounted_base * factor)
        factor = factor * multiplier

    avg = round_cents(Decimal(net) / Decimal(term_years))
    return {
        "volume_discount_pct": round_half_up(vol, 2),
        "term_discount_pct": round_half_up(term, 2),
        "bundle_discount_pct": round_half_up(bund, 2),
        "total_discount_pct": total,
        "net_state_price_cents": net,
        "avg_annual_price_cents": avg,
    }


# --- order_total_value -----------------------------------------------------
def order_total_value(variant, print_units, digital_seats, title, state, proposal):
    """Pinned evaluation order: the freight waiver is decided on the pre-freight total."""
    if variant == "quoted":
        unit_price = title["list_price_cents"]
    else:
        unit_price = (
            proposal["avg_annual_price_cents"] if proposal is not None
            else title["list_price_cents"]
        )
    seat_price = (
        proposal["digital_seat_price_cents"] if proposal is not None
        else DEFAULT_OPEN_TERRITORY_SEAT_CENTS
    )
    print_subtotal = unit_price * print_units
    digital_subtotal = seat_price * digital_seats
    pre_freight = print_subtotal + digital_subtotal

    if pre_freight >= FREIGHT_WAIVER_THRESHOLD_CENTS:
        freight = 0
    else:
        freight = round_cents(Decimal(print_subtotal) * FREIGHT_RATE)

    if variant == "contracted" and state["adoption_model"] == "ADOPTION_LIST":
        rebate = round_cents(Decimal(print_subtotal) * ADOPTED_LIST_REBATE_PCT)
    else:
        rebate = 0

    return pre_freight + freight - rebate, freight


# --- committee_tally -------------------------------------------------------
def project_ballots(votes):
    """One ballot per member: latest created_at, ties broken by higher sequence_no."""
    latest = {}
    for vote in votes:
        member = vote["member_user_id"]
        current = latest.get(member)
        if current is None or (vote["created_at"], vote["sequence_no"]) > (
            current["created_at"], current["sequence_no"]
        ):
            latest[member] = vote
    return list(latest.values())


def tally_ratio(counted):
    non_abstain = [v for v in counted if v["vote"] != "ABSTAIN"]
    recommend = sum(1 for v in non_abstain if v["vote"] == "RECOMMEND")
    conditions = sum(1 for v in non_abstain if v["vote"] == "RECOMMEND_WITH_CONDITIONS")
    weighted = Decimal(recommend) + CONDITIONS_WEIGHT * Decimal(conditions)
    ratio = round_half_up(weighted / Decimal(len(non_abstain)), 4)
    if ratio >= RECOMMEND_RATIO_THRESHOLD:
        if any(v["vote"] == "RECOMMEND_WITH_CONDITIONS" for v in counted):
            outcome = "RECOMMEND_WITH_CONDITIONS"
        else:
            outcome = "RECOMMEND"
    else:
        outcome = "REJECT"
    return ratio, outcome


# --- compliance_score ------------------------------------------------------
def compliance_score(prohibited_hits, missing_topics, unresolved_critical, overdue):
    score = (
        100
        - PENALTY_PROHIBITED * prohibited_hits
        - PENALTY_MISSING_TOPIC * missing_topics
        - PENALTY_CRITICAL * unresolved_critical
        - PENALTY_OVERDUE * overdue
    )
    return max(0, score)


def is_adoption_blocked(score, prohibited_hits, content_pin_stale):
    return bool(score < BLOCK_THRESHOLD or prohibited_hits > 0 or content_pin_stale)


# --- sampling_fulfilment ---------------------------------------------------
def sampling_status(required, shipped):
    if required == 0:
        return "NOT_REQUIRED"
    if shipped >= required:
        return "SHIPPED"
    if shipped > 0:
        return "PARTIAL"
    return "PENDING"
