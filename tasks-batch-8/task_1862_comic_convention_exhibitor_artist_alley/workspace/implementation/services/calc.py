"""Calculation rules from SCAFFOLD Table 3 / PRD §3. All money in integer
cents via Decimal with ROUND_HALF_UP; jury scores are the only non-integers,
always 2dp rounded half up."""

from decimal import Decimal, ROUND_HALF_UP

import db

# --------------------------------------------------------------------------
# Constants (SCAFFOLD calculations.constants)
# --------------------------------------------------------------------------
TIER_1_SOLD_LT = 20
TIER_2_SOLD_LT = 45
TIER_1_MULT = Decimal("1.00")
TIER_2_MULT = Decimal("1.20")
TIER_3_MULT = Decimal("1.45")

DISCOUNT_TIER_1_SUBTOTAL_CENTS = 150000
DISCOUNT_TIER_1_PCT = Decimal("0.05")
DISCOUNT_TIER_2_SUBTOTAL_CENTS = 300000
DISCOUNT_TIER_2_PCT = Decimal("0.10")
EARLY_BIRD_PCT = Decimal("0.10")
DEPOSIT_PCT = Decimal("0.25")

KIND_FLOOR_PRICE = {
    "BOOTH_10X10": 95000,
    "BOOTH_10X20": 175000,
    "CORNER_BOOTH": 140000,
    "ENDCAP": 160000,
    "FEATURED_ISLAND": 400000,
    "ARTIST_TABLE": 27500,
    "NONPROFIT_TABLE": 15000,
}

BADGES_PER_KIND = {
    "BOOTH_10X10": 4,
    "BOOTH_10X20": 6,
    "CORNER_BOOTH": 6,
    "ENDCAP": 8,
    "FEATURED_ISLAND": 12,
    "ARTIST_TABLE": 2,
    "NONPROFIT_TABLE": 2,
}
EXTRA_BADGE_FEE_CENTS = 7500

W_ORIGINALITY = Decimal("0.35")
W_CRAFT = Decimal("0.25")
W_CATEGORY_FIT = Decimal("0.25")
W_PROFESSIONALISM = Decimal("0.15")
QUORUM = 3
ACCEPT_THRESHOLD = Decimal("70.00")
WAITLIST_THRESHOLD = Decimal("50.00")

POINTS_BY_SEVERITY = {"MINOR": 1, "MAJOR": 2, "CRITICAL": 3}

# Category-zone map: which (kind, hall) pairs each category may occupy.
# Artist Alley artists sit at ARTIST_TABLEs in ARTIST_ALLEY_HALL; nonprofits
# at NONPROFIT_TABLEs in SMALL_PRESS; dealers/publishers/studios take the
# booth kinds in MAIN (SMALL_PRESS additionally hosts PUBLISHER tables and
# SMALL_PRESS booths for publishers).
CATEGORY_ZONE_MAP = {
    "ARTIST_ALLEY": {
        ("ARTIST_TABLE", "ARTIST_ALLEY_HALL"),
    },
    "NONPROFIT": {
        ("NONPROFIT_TABLE", "SMALL_PRESS"),
        ("NONPROFIT_TABLE", "MAIN"),
    },
    "DEALER": {
        ("BOOTH_10X10", "MAIN"),
        ("BOOTH_10X20", "MAIN"),
        ("CORNER_BOOTH", "MAIN"),
        ("ENDCAP", "MAIN"),
        ("FEATURED_ISLAND", "MAIN"),
    },
    "PUBLISHER": {
        ("BOOTH_10X10", "MAIN"),
        ("BOOTH_10X20", "MAIN"),
        ("CORNER_BOOTH", "MAIN"),
        ("ENDCAP", "MAIN"),
        ("FEATURED_ISLAND", "MAIN"),
        ("ARTIST_TABLE", "SMALL_PRESS"),
        ("BOOTH_10X10", "SMALL_PRESS"),
        ("BOOTH_10X20", "SMALL_PRESS"),
    },
    "STUDIO": {
        ("BOOTH_10X10", "MAIN"),
        ("BOOTH_10X20", "MAIN"),
        ("CORNER_BOOTH", "MAIN"),
        ("ENDCAP", "MAIN"),
        ("FEATURED_ISLAND", "MAIN"),
    },
}


def _rh(value):
    """Round half up to integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _rh2(value):
    """Round half up to two decimals; returned as float for JSON."""
    d = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def sold_count(convention_id):
    """Number of SpaceUnits of the convention in RESERVED or ASSIGNED."""
    n = 0
    for su in db.space_units.values():
        if su["convention_id"] == convention_id and su["status"] in ("RESERVED", "ASSIGNED"):
            n += 1
    return n


def _tier_mult(sc):
    if sc < TIER_1_SOLD_LT:
        return TIER_1_MULT
    if sc < TIER_2_SOLD_LT:
        return TIER_2_MULT
    return TIER_3_MULT


def _discount_pct(subtotal):
    if subtotal >= DISCOUNT_TIER_2_SUBTOTAL_CENTS:
        return DISCOUNT_TIER_2_PCT
    if subtotal >= DISCOUNT_TIER_1_SUBTOTAL_CENTS:
        return DISCOUNT_TIER_1_PCT
    return Decimal("0")


def _price_ladder(base_prices, tier_mult, submitted_at, convention):
    """Steps 1-5 of space_pricing. base_prices: list of integer cents."""
    prices = [_rh(Decimal(bp) * tier_mult) for bp in base_prices]
    subtotal = sum(prices)
    disc = _discount_pct(subtotal)
    eb = Decimal("0")
    ebd = db._parse_iso(convention["early_bird_deadline"])
    if submitted_at is not None and submitted_at <= ebd:
        eb = EARLY_BIRD_PCT
    total = _rh(Decimal(subtotal) * (Decimal("1") - disc - eb))
    return total


def provisional_quote(application, convention):
    """Provisional variant: each of requested_space_count spaces priced at the
    cheapest AVAILABLE unit among requested kinds (per-kind min), floor price
    for kinds with no AVAILABLE unit. Tier multiplier from sold_count at
    submit time."""
    sc = sold_count(convention["id"])
    mult = _tier_mult(sc)
    # cheapest AVAILABLE base price per requested kind
    cheapest = {}
    for su in db.space_units.values():
        if su["convention_id"] != convention["id"]:
            continue
        if su["status"] != "AVAILABLE":
            continue
        if su["kind"] not in application["requested_space_kinds"]:
            continue
        bp = su["base_price_cents"]
        if su["kind"] not in cheapest or bp < cheapest[su["kind"]]:
            cheapest[su["kind"]] = bp
    per_kind = []
    for kind in application["requested_space_kinds"]:
        if kind in cheapest:
            per_kind.append(cheapest[kind])
        else:
            per_kind.append(KIND_FLOOR_PRICE[kind])
    unit_price_basis = min(per_kind) if per_kind else 0
    bases = [unit_price_basis] * application["requested_space_count"]
    submitted_at = db._parse_iso(application["submitted_at"]) if application.get("submitted_at") else db.now_dt()
    return _price_ladder(bases, mult, submitted_at, convention)


def final_invoice(application, convention):
    """Final variant: scope = RESERVED SpaceUnits whose current_application_id
    is this application; space count from those units; tier multiplier from
    sold_count at accept time."""
    held = [su for su in db.space_units.values()
            if su["convention_id"] == convention["id"]
            and su["status"] == "RESERVED"
            and su.get("current_application_id") == application["id"]]
    bases = [su["base_price_cents"] for su in held]
    sc = sold_count(convention["id"])
    mult = _tier_mult(sc)
    submitted_at = db._parse_iso(application["submitted_at"]) if application.get("submitted_at") else None
    return _price_ladder(bases, mult, submitted_at, convention)


def deposit_for(invoice_cents):
    return _rh(Decimal(invoice_cents) * DEPOSIT_PCT)


def jury_weighted_total(originality, craft, category_fit, professionalism):
    v = (W_ORIGINALITY * Decimal(originality)
         + W_CRAFT * Decimal(craft)
         + W_CATEGORY_FIT * Decimal(category_fit)
         + W_PROFESSIONALISM * Decimal(professionalism))
    return _rh2(v)


def jury_composite(application_id):
    """Mean of distinct-juror weighted_total values, 2dp half-up. None when no
    scores. Per-juror rounding happens before the mean (weighted_total is
    already stored rounded)."""
    totals = [js["weighted_total"] for js in db.jury_scores.values()
              if js["application_id"] == application_id]
    if not totals:
        return None
    mean = sum(Decimal(str(t)) for t in totals) / Decimal(len(totals))
    return _rh2(mean)


def distinct_juror_count(application_id):
    return len({js["juror_user_id"] for js in db.jury_scores.values()
                if js["application_id"] == application_id})


def renewal_priority_score(exhibitor):
    return max(0, 10 * exhibitor["prior_years_completed"]
               + 3 * exhibitor["prior_on_time_payments"]
               - 8 * exhibitor["strike_points"])


def standing_for(strike_points):
    if strike_points >= 7:
        return "EVICTED"
    if strike_points >= 5:
        return "SUSPENDED"
    if strike_points >= 3:
        return "PROBATION"
    return "GOOD"


def selling_days(convention):
    s = db._parse_iso(convention["starts_at"]).date()
    e = db._parse_iso(convention["ends_at"]).date()
    return (e - s).days + 1


def sales_tax_estimate(application, convention):
    rate = Decimal(convention["sales_tax_rate_bp"]) / Decimal(10000)
    per_day = _rh(Decimal(application["estimated_daily_sales_cents"]) * rate)
    return per_day * selling_days(convention)


def sales_tax_settlement(lines, convention):
    rate = Decimal(convention["sales_tax_rate_bp"]) / Decimal(10000)
    return sum(_rh(Decimal(line["gross_cents"]) * rate) for line in lines)


def cancellation_refund(amount_paid_cents, convention, cancelled_at):
    from datetime import timedelta
    starts = db._parse_iso(convention["starts_at"])
    b60 = starts - timedelta(days=60)
    b30 = starts - timedelta(days=30)
    if cancelled_at <= b60:
        pct = Decimal("1.00")
    elif cancelled_at <= b30:
        pct = Decimal("0.50")
    else:
        pct = Decimal("0.00")
    return _rh(Decimal(amount_paid_cents) * pct)


def included_badges_for(application_id, convention_id):
    total = 0
    for su in db.space_units.values():
        if su["convention_id"] == convention_id and su["status"] == "ASSIGNED" \
                and su.get("current_application_id") == application_id:
            total += BADGES_PER_KIND[su["kind"]]
    return total


def recompute_balance_due(application):
    if application.get("final_invoice_cents") is None:
        application["balance_due_cents"] = 0
    else:
        application["balance_due_cents"] = (
            application["final_invoice_cents"]
            - application["amount_paid_cents"]
            + application["badge_fees_cents"]
        )
