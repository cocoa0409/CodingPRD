"""Calculation rules (SCAFFOLD §1.3, PRD §3) — exact decimal arithmetic.

Rounding discipline (PRD §2.6): monetary values and composite scores are
rounded half-up; composites at 2dp, participation at 4dp, money at 2dp.
"""

from decimal import Decimal, ROUND_HALF_UP

from db import store

CENT = Decimal("0.01")
TEN_THOUSANDTH = Decimal("0.0001")

# alignment_coverage constants
W_FULL = Decimal("1.0")
W_PARTIAL = Decimal("0.5")
W_NONE = Decimal("0.0")
ADOPTION_COVERAGE_THRESHOLD_PCT = Decimal("85.00")

# pilot_composite_score constants
W_PEDAGOGY = Decimal("0.4")
W_ALIGNMENT = Decimal("0.3")
W_USABILITY = Decimal("0.2")
W_EQUITY = Decimal("0.1")
TRIM_MIN_REVIEWS = 5

# participation_rate constants
PARTICIPATION_FLOOR = Decimal("0.60")

# award constants
COMPOSITE_THRESHOLD = Decimal("3.20")
FORMAL_BID_THRESHOLD = Decimal("250000.00")

# best_value_score constants
BV_W_PRICE = Decimal("0.50")
BV_W_TRAINING = Decimal("0.25")
BV_W_LICENSE = Decimal("0.25")
TRAINING_POINTS_PER_SESSION = 10
LICENSE_POINTS_PER_YEAR = 20

# budget_forecast constants
PER_PUPIL_RATE = Decimal("120.00")
REPLACEMENT_RATIO = Decimal("0.20")
FORECAST_YEARS = 5
INFLATION_FACTOR = Decimal("1.03")
FORECAST_HISTORY_CYCLES = 3


def r2(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def r4(value):
    return Decimal(value).quantize(TEN_THOUSANDTH, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# alignment_coverage (SCAFFOLD §1.3): coverage_pct =
#   round(100 * sum(weights) / framework.standards_required_count, 2)
# ---------------------------------------------------------------------------


def recompute_coverage(material):
    cycle = store.cycles.get(material["cycle_id"])
    framework = store.frameworks.get(cycle["framework_id"]) if cycle else None
    required = framework["standards_required_count"] if framework else 0
    weights = {"FULL": W_FULL, "PARTIAL": W_PARTIAL, "NONE": W_NONE}
    covered = Decimal("0")
    for mapping in store.alignments.values():
        if mapping["material_id"] == material["id"]:
            covered += weights[mapping["coverage_rating"]]
    if required and required >= 1:
        material["coverage_pct"] = r2(Decimal(100) * covered / Decimal(required))
    else:
        material["coverage_pct"] = Decimal("0.00")


# ---------------------------------------------------------------------------
# pilot_composite_score — per-review composite (exact decimal, PRD §3.3)
# ---------------------------------------------------------------------------


def review_composite(pedagogy, alignment, usability, equity):
    return (W_PEDAGOGY * Decimal(pedagogy)
            + W_ALIGNMENT * Decimal(alignment)
            + W_USABILITY * Decimal(usability)
            + W_EQUITY * Decimal(equity))


def _review_pool(material):
    """SUBMITTED reviews over this material's pilots in its cycle whose pilot
    status is ACTIVE or CLOSED (PRD §3.3 pool definition)."""
    pilot_ids = {
        p["id"] for p in store.pilots.values()
        if p["material_id"] == material["id"]
        and p["cycle_id"] == material["cycle_id"]
        and p["status"] in ("ACTIVE", "CLOSED")
    }
    return [
        rv for rv in store.reviews.values()
        if rv["pilot_id"] in pilot_ids and rv["status"] == "SUBMITTED"
    ]


def provisional_composite(material):
    """PROVISIONAL variant: untrimmed mean, rounded half-up 2dp; null when the
    pool is empty."""
    pool = _review_pool(material)
    if not pool:
        return None
    total = sum((rv["review_composite"] for rv in pool), Decimal("0"))
    return r2(total / Decimal(len(pool)))


def recompute_provisional(material):
    material["provisional_composite"] = provisional_composite(material)


def pilot_submitted_review_count(pilot):
    return sum(
        1 for rv in store.reviews.values()
        if rv["pilot_id"] == pilot["id"] and rv["status"] == "SUBMITTED"
    )


def compute_official_scores(material):
    """OFFICIAL variant + participation rate, computed at close-pilots
    (PILOT_OPEN -> SCORING). Returns (official_composite, participation_rate).

    OFFICIAL: with >= TRIM_MIN_REVIEWS reviews, drop exactly one lowest and one
    highest composite (one instance each even when tied) and average the rest;
    with fewer, identical to PROVISIONAL.
    participation_rate: submitted / sum(teacher_count of ACTIVE/CLOSED pilots),
    rounded half-up to 4dp; null when the denominator is zero.
    """
    pool = _review_pool(material)
    composites = sorted(rv["review_composite"] for rv in pool)
    if len(composites) >= TRIM_MIN_REVIEWS:
        trimmed = composites[1:-1]
    else:
        trimmed = composites
    if trimmed:
        official = r2(sum(trimmed, Decimal("0")) / Decimal(len(trimmed)))
    else:
        official = None

    pilots = [
        p for p in store.pilots.values()
        if p["material_id"] == material["id"]
        and p["cycle_id"] == material["cycle_id"]
        and p["status"] in ("ACTIVE", "CLOSED")
    ]
    seats = sum(p["teacher_count"] for p in pilots)
    if seats == 0:
        participation = None
    else:
        submitted = sum(1 for rv in pool)  # pool is already ACTIVE/CLOSED-scoped
        participation = r4(Decimal(submitted) / Decimal(seats))
    return official, participation


# ---------------------------------------------------------------------------
# bundled_pricing_total (PRD §3.5) — pinned rounding order:
#   1. round each line to cents FIRST
#   2. apply the bundle discount to the digital line SECOND (rounding again)
#   3. sum LAST
# ---------------------------------------------------------------------------


def bundled_pricing_total(print_unit_price, print_quantity,
                          digital_seat_rate, digital_seat_count,
                          bundle_discount_pct):
    print_line = r2(Decimal(print_unit_price) * Decimal(print_quantity))
    digital_line = r2(Decimal(digital_seat_rate) * Decimal(digital_seat_count))
    if (bundle_discount_pct is not None and bundle_discount_pct > 0
            and print_quantity > 0 and digital_seat_count > 0):
        digital_line = r2(digital_line * (Decimal(1) - Decimal(bundle_discount_pct)))
    return print_line + digital_line


# ---------------------------------------------------------------------------
# best_value_score (PRD §3.5) — full precision until the final rounding.
# ---------------------------------------------------------------------------


def best_value_scores(pool):
    """Compute best_value_score for every quote in `pool` (list of quote
    dicts). Returns {quote_id: Decimal score}."""
    if not pool:
        return {}
    min_total = min(q["evaluated_total"] for q in pool)
    scores = {}
    for q in pool:
        if min_total == 0:
            price_score = Decimal(100)
        else:
            price_score = Decimal(100) * (Decimal(2) - q["evaluated_total"] / min_total)
            if price_score < 0:
                price_score = Decimal(0)
        training_score = Decimal(min(100, q["training_sessions"] * TRAINING_POINTS_PER_SESSION))
        license_score = Decimal(min(100, q["license_years"] * LICENSE_POINTS_PER_YEAR))
        score = (BV_W_PRICE * price_score
                 + BV_W_TRAINING * training_score
                 + BV_W_LICENSE * license_score)
        scores[q["id"]] = r2(score)
    return scores


# ---------------------------------------------------------------------------
# budget_ledger_balances (PRD §2.10)
# ---------------------------------------------------------------------------


def ledger_available(ledger):
    return (ledger["appropriation_total"]
            - ledger["encumbered_total"]
            - ledger["expended_total"])


# ---------------------------------------------------------------------------
# inventory_availability (PRD §2.11) — allocated/available derived on read.
# ---------------------------------------------------------------------------


def lot_allocated_units(material_id):
    return sum(
        do["quantity"] for do in store.distribution_orders.values()
        if do["material_id"] == material_id and do["status"] == "APPROVED"
    )


def lot_available_units(lot):
    return lot["on_hand_units"] - lot_allocated_units(lot["material_id"])


def recompute_open_backorder_count(cycle):
    """open_backorder_count: DistributionOrders in BACKORDERED for the cycle's
    adopted material (recomputed on every allocation event)."""
    adopted_id = cycle.get("adopted_material_id")
    if adopted_id is None:
        count = 0
    else:
        count = sum(
            1 for do in store.distribution_orders.values()
            if do["material_id"] == adopted_id and do["status"] == "BACKORDERED"
        )
    if cycle.get("open_backorder_count") != count:
        cycle["open_backorder_count"] = count
        from db import refresh
        refresh(cycle)


# ---------------------------------------------------------------------------
# budget_forecast (PRD §3.10) — pinned evaluation order:
#   1. compute base_amount and round to 2dp
#   2. select contingency_rate from the tier table keyed on the ROUNDED base
#   3. forecast_total = round(base_amount * (1 + contingency_rate), 2)
# ---------------------------------------------------------------------------


def budget_forecast(cycle, variant):
    if variant == "ROLLING":
        base = r2(Decimal(cycle["district_enrollment"]) * PER_PUPIL_RATE
                  * REPLACEMENT_RATIO * Decimal(FORECAST_YEARS))
    else:  # STRAIGHT_LINE
        others = [
            c for c in store.cycles.values()
            if c["id"] != cycle["id"] and c["status"] in ("ACTIVE", "SUNSET")
        ]
        others.sort(key=lambda c: c.get("_seq", 0))  # created_at ASC stable base
        others.sort(key=lambda c: (-c["school_year_start"],
                                   c["created_at"], c.get("_seq", 0)))
        history = []
        for c in others[:FORECAST_HISTORY_CYCLES]:
            ledger = store.ledgers.get(c["id"])
            history.append(ledger["expended_total"] if ledger else Decimal("0"))
        if not history:
            base = Decimal("0.00")
        else:
            mean = sum(history, Decimal("0")) / Decimal(len(history))
            base = r2(mean * (INFLATION_FACTOR ** FORECAST_YEARS))

    if base < Decimal("100000.00"):
        rate = Decimal("0.05")
    elif base < Decimal("500000.00"):
        rate = Decimal("0.08")
    else:
        rate = Decimal("0.12")
    total = r2(base * (Decimal(1) + rate))
    return {
        "variant": variant,
        "base_amount": base,
        "contingency_rate": rate,
        "forecast_total": total,
    }
