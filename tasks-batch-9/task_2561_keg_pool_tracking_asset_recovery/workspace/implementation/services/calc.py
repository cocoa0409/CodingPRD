"""Pure calculations: scrap value, loss valuation, fill billing, incentives,
loss rates and the dwell classification.  Money is integer cents, rates are
integer basis points, and every fractional result is rounded half up."""
from datetime import timedelta
from decimal import Decimal

import clock
import db
import util

SCRAP_RECOVERY_PCT = Decimal("0.65")
PRESSURE_TEST_INTERVAL_FILLS = 25
PRESSURE_TEST_INTERVAL_DAYS = 730

DWELL_BREWER_LIMIT_DAYS = 30
DWELL_BREWER_APPROACHING_DAYS = 24
DWELL_DISTRIBUTOR_LIMIT_DAYS = 45
DWELL_DISTRIBUTOR_APPROACHING_DAYS = 36

DWELL_SURCHARGE_CENTS_PER_DAY = 30
DWELL_SURCHARGE_CAP_PCT = Decimal("0.20")
VOLUME_TIER_1_CENTS = 9000
VOLUME_TIER_1_BP = 300
VOLUME_TIER_2_CENTS = 4500
VOLUME_TIER_2_BP = 150

CLAIM_WINDOW_DAYS = 30
MAX_CLAIM_ROUNDS = 3

CHARGEBACK_PROBATION_CENTS = 25000
LOSS_RATE_PROBATION_BP = 1500
LOSS_RATE_WINDOW_DAYS = 90

DEPRECIATION_BP_PER_FILL = 45
DEPRECIATION_CAP_BP = 7000
BOOK_FLOOR_PCT = Decimal("0.30")

CAUSTIC_MIN_MINUTES = 12
PRESSURE_TEST_MIN_PSI = 30

BREWER_LIABILITY_BP = {
    "LOST_IN_TRADE": 6000,
    "DAMAGED_BEYOND_REPAIR": 10000,
    "NOT_RETURNED_DWELL": 10000,
    "STOLEN_SUSPECTED": 0,
}

COOPERATION_MULTIPLIER_BP = {
    "NONE": 0,
    "BRONZE": 10000,
    "SILVER": 11500,
    "GOLD": 13000,
}

CIRCULATING_STATES = ("ISSUED_TO_BREWER", "FILLED", "IN_TRADE", "AT_RETAIL")
SERVICING_STATES = ("IN_SERVICE", "QUARANTINED")
WRITTEN_OFF_STATES = ("LOST", "STOLEN", "SCRAPPED")

# ------------------------------------------------------- commodity index -----


def effective_index(on_date=None):
    """The index row with the greatest effective_date on or before the
    valuation date.  A future-dated row is never selected."""
    valuation_date = on_date or clock.now().date()
    best = None
    for row in db.commodity_index.values():
        if row["effective_date"] <= valuation_date:
            if best is None or row["effective_date"] > best["effective_date"]:
                best = row
    return best


def scrap_value_for_pool(pool, index_row):
    if index_row is None:
        return 0
    return util.rhu(util.dec(pool["stainless_weight_kg"])
                    * util.dec(index_row["usd_cents_per_kg"])
                    * SCRAP_RECOVERY_PCT)


def keg_scrap_value(keg, index_row=None):
    pool = db.pools.get(keg["pool_id"])
    if pool is None:
        return 0
    if index_row is None:
        index_row = effective_index()
    return scrap_value_for_pool(pool, index_row)


# ------------------------------------------------------------------ dwell ----


def dwell_limits(custody_state):
    """Which clock and which limits apply to a keg's open spell."""
    if custody_state in ("ISSUED_TO_BREWER", "FILLED"):
        return ("brewer", DWELL_BREWER_LIMIT_DAYS,
                DWELL_BREWER_APPROACHING_DAYS)
    if custody_state in ("IN_TRADE", "AT_RETAIL"):
        return ("distributor", DWELL_DISTRIBUTOR_LIMIT_DAYS,
                DWELL_DISTRIBUTOR_APPROACHING_DAYS)
    return (None, 0, 0)


def brewer_spell_days(keg, at=None):
    return util.spell_days(keg["dwell_started_at"], at or clock.now())


def distributor_spell_days(keg, at=None):
    return util.spell_days(keg["distributor_custody_started_at"],
                           at or clock.now())


def classify_dwell(keg, at=None):
    """OVERDUE strictly past the limit, APPROACHING at or beyond the
    approaching point, WITHIN_LIMIT otherwise.  States with no limit at all
    are forced to WITHIN_LIMIT."""
    which, limit, approaching = dwell_limits(keg["custody_state"])
    if which is None:
        return "WITHIN_LIMIT", 0, 0, 0
    days = (brewer_spell_days(keg, at) if which == "brewer"
            else distributor_spell_days(keg, at))
    if days > limit:
        flag = "OVERDUE"
    elif days >= approaching:
        flag = "APPROACHING"
    else:
        flag = "WITHIN_LIMIT"
    return flag, days, limit, approaching


def certification_lapsed(keg, at=None):
    return util.elapsed_days(keg["last_pressure_test_at"],
                             at or clock.now()) > PRESSURE_TEST_INTERVAL_DAYS


def derive_service_state(fill_count, fills_at_last_test, last_test_at,
                         at=None):
    if fill_count - fills_at_last_test >= PRESSURE_TEST_INTERVAL_FILLS:
        return "SERVICE_DUE"
    if util.elapsed_days(last_test_at, at or clock.now()) \
            > PRESSURE_TEST_INTERVAL_DAYS:
        return "SERVICE_OVERDUE"
    return "SERVICE_OK"


# --------------------------------------------------------- fill billing ------


def fill_charge(agreement, brewer_days):
    """The pinned order of PRD 3.5: base from the agreement, raw surcharge
    capped at 20 percent of the base alone, the volume tier read off the
    already-billed amount plus this fill's own pre-discount charge."""
    base = agreement["per_fill_rate_cents"]
    excess_days = max(0, brewer_days - DWELL_BREWER_LIMIT_DAYS)
    raw_surcharge = excess_days * DWELL_SURCHARGE_CENTS_PER_DAY
    cap = util.rhu(util.dec(base) * DWELL_SURCHARGE_CAP_PCT)
    surcharge = min(raw_surcharge, cap)
    pre_discount = base + surcharge
    tier_basis = agreement["billed_amount_cents"] + pre_discount
    if tier_basis >= VOLUME_TIER_1_CENTS:
        discount_bp = VOLUME_TIER_1_BP
    elif tier_basis >= VOLUME_TIER_2_CENTS:
        discount_bp = VOLUME_TIER_2_BP
    else:
        discount_bp = 0
    discount = util.rhu(util.dec(pre_discount) * util.dec(discount_bp)
                        / util.dec(10000))
    return {
        "base_cents": base,
        "raw_surcharge_cents": raw_surcharge,
        "surcharge_cap_cents": cap,
        "surcharge_cents": surcharge,
        "pre_discount_cents": pre_discount,
        "tier_basis_cents": tier_basis,
        "discount_bp": discount_bp,
        "discount_cents": discount,
        "net_cents": pre_discount - discount,
    }


# ------------------------------------------------------- loss valuation ------


def coerce_basis(basis, keg, cause):
    """Silent coercion, never an error."""
    if basis is None:
        return "REPLACEMENT_COST"
    if basis == "DEPRECIATED_BOOK" and (keg["fill_count"] == 0
                                        or cause == "STOLEN_SUSPECTED"):
        return "REPLACEMENT_COST"
    return basis


def loss_value(pool, keg, cause, basis, scrap_value_cents):
    replacement = pool["replacement_cost_cents"]
    if basis == "DEPRECIATED_BOOK":
        depreciation_bp = min(keg["fill_count"] * DEPRECIATION_BP_PER_FILL,
                              DEPRECIATION_CAP_BP)
        book = util.rhu(util.dec(replacement)
                        * util.dec(10000 - depreciation_bp) / util.dec(10000))
        floor_value = util.rhu(util.dec(replacement) * BOOK_FLOOR_PCT)
        gross = max(book, floor_value)
    else:
        gross = replacement
    scrap_credit = scrap_value_cents if cause == "DAMAGED_BEYOND_REPAIR" else 0
    assessed = max(0, gross - scrap_credit)
    liability_bp = BREWER_LIABILITY_BP[cause]
    net = util.rhu(util.dec(assessed) * util.dec(liability_bp)
                   / util.dec(10000))
    return {
        "gross_value_cents": gross,
        "scrap_credit_cents": scrap_credit,
        "assessed_value_cents": assessed,
        "brewer_liability_pct_bp": liability_bp,
        "net_chargeback_cents": net,
    }


# ---------------------------------------------------- return incentives ------


def dwell_band_bp(dwell_days):
    if dwell_days <= 14:
        return 10000
    if dwell_days <= 29:
        return 6000
    if dwell_days <= 44:
        return 2500
    return 0


def return_incentive(distributor, dwell_days):
    band_bp = dwell_band_bp(dwell_days)
    multiplier_bp = COOPERATION_MULTIPLIER_BP[distributor["cooperation_tier"]]
    cents = util.rhu(util.dec(distributor["return_incentive_rate_cents_per_keg"])
                     * util.dec(band_bp) / util.dec(10000)
                     * util.dec(multiplier_bp) / util.dec(10000))
    return band_bp, multiplier_bp, cents


# --------------------------------------------------------- loss rate ---------


def loss_rate(brewer, basis):
    """TRAILING_90D counts UPHELD assessments by created_at against FILL scans
    by scanned_at inside a window inclusive at both ends.  LIFETIME divides
    the unwindowed counters."""
    if basis == "LIFETIME":
        numerator = brewer["upheld_loss_count"]
        denominator = brewer["lifetime_fill_count"]
        window_start = None
        window_end = None
    else:
        window_end = clock.now()
        window_start = window_end - timedelta(days=LOSS_RATE_WINDOW_DAYS)
        numerator = 0
        for row in db.assessments.values():
            if row["brewer_id"] != brewer["id"]:
                continue
            if row["assessment_status"] != "UPHELD":
                continue
            if window_start <= row["created_at"] <= window_end:
                numerator += 1
        denominator = 0
        for scan in db.scan_events.values():
            if scan["scan_point"] != "FILL":
                continue
            if scan["brewer_id"] != brewer["id"]:
                continue
            if window_start <= scan["scanned_at"] <= window_end:
                denominator += 1
    if denominator == 0:
        return {"loss_rate_bp": 0, "upheld_loss_count": numerator,
                "fill_count": denominator, "window_start": window_start,
                "window_end": window_end, "basis_insufficient": True}
    rate = util.rhu(util.dec(10000) * util.dec(numerator)
                    / util.dec(denominator))
    return {"loss_rate_bp": rate, "upheld_loss_count": numerator,
            "fill_count": denominator, "window_start": window_start,
            "window_end": window_end, "basis_insufficient": False}
