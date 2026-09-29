"""Deterministic calculations (SCAFFOLD 1.3 / PRD 2.6).

All money and percentage arithmetic runs on decimal.Decimal with ROUND_HALF_UP.
Never float.
"""

from decimal import Decimal, ROUND_HALF_UP

from store import (by_created, date_start, db, month_start, now, plus_days,
                   whole_days_between)

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------

LOCK_TERM_BPS_TABLE = ((15, 0), (30, -12), (45, -25), (60, -40))
MANDATORY_TYPE_BPS = 25
BEST_EFFORTS_TYPE_BPS = -35
PRICE_FLOOR_PCT = Decimal("98.000")
PRICE_CEILING_PCT = Decimal("104.000")

PAIR_OFF_TOLERANCE_PCT = Decimal("2.00")
PAIR_OFF_ADMIN_FEE_CENTS = 25000

VOLUME_TIER_1_CENTS = 100000000
VOLUME_TIER_2_CENTS = 250000000
TIER_1_BPS = 5
TIER_2_BPS = 10

WIRE_FEE_CENTS = 3500
EXPIRED_DEFECT_PENALTY_BPS = -50
DAY_COUNT_BASIS = 360

MIN_SCORED_LOANS = 2
GRADE_A_MAX_BPS = 1000
GRADE_B_MAX_BPS = 2500
GRADE_C_MAX_BPS = 5000
DEFECT_RATE_WATCH_BPS = 1000
DEFECT_RATE_SUSPENSION_BPS = 5000

CURE_WINDOW_DAYS = {"LOW": 15, "MEDIUM": 10, "HIGH": 5}
SUSPENSE_WINDOW_DAYS = 7

CONDITIONAL_PASS_FINDINGS_THRESHOLD = 5

NET_WORTH_MULTIPLIER_STANDARD = 10
NET_WORTH_MULTIPLIER_CONDITIONAL = 5
MANDATORY_EXPOSURE_ABSOLUTE_CAP_CENTS = 5000000000
MIN_TANGIBLE_NET_WORTH_CENTS = 250000000
MIN_LIQUIDITY_CENTS = 50000000
FS_STALENESS_DAYS = 455

REPURCHASE_ADMIN_FEE_CENTS = 50000
EPD_DEMAND_WINDOW_DAYS = 120
APPEAL_WINDOW_DAYS = 30
ESCROW_TRANSFER_DAYS = 15

MAX_LOCK_TERM_DAYS = 60

PURCHASED_STATUSES = ("PURCHASED", "REPURCHASE_DEMANDED", "REPURCHASED")
ALLOCATED_STATUSES = ("DELIVERED", "IN_REVIEW", "SUSPENDED", "CLEARED_FOR_PURCHASE")


# --------------------------------------------------------------------------
# rounding primitives
# --------------------------------------------------------------------------

def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def cents(value):
    """Round an exact rational amount to whole cents, half-up."""
    return int(round_half_up(value, 0))


def pct3(value):
    """Round a percentage to exactly 3 decimal places, half-up."""
    return round_half_up(value, 3)


def floor_int(value):
    """Floor toward negative infinity on an exact Decimal."""
    d = dec(value)
    return int(d.to_integral_value(rounding="ROUND_FLOOR"))


# --------------------------------------------------------------------------
# commitment_price_pct
# --------------------------------------------------------------------------

def lock_term_bps(lock_term_days):
    """Largest tabled term <= lock_term_days; below 15 days selects 0 bps."""
    result = 0
    for term, bps in LOCK_TERM_BPS_TABLE:
        if lock_term_days >= term:
            result = bps
    return result


def matching_adjustments(product_id, reference_fico, reference_ltv_pct):
    """ACTIVE rows of the product whose FICO and LTV bands both match.

    FICO band: both bounds inclusive.
    LTV band: lower bound exclusive, upper bound inclusive.
    """
    ltv = dec(reference_ltv_pct)
    rows = []
    for row in by_created(list(db.adjustments.values())):
        if row["product_id"] != product_id:
            continue
        if row["status"] != "ACTIVE":
            continue
        if not (row["fico_min"] <= reference_fico <= row["fico_max"]):
            continue
        if not (dec(row["ltv_min_pct"]) < ltv <= dec(row["ltv_max_pct"])):
            continue
        rows.append(row)
    return rows


def llpa_bps(product_id, reference_fico, reference_ltv_pct):
    return sum(r["price_adjustment_bps"]
               for r in matching_adjustments(product_id, reference_fico,
                                             reference_ltv_pct))


def commitment_price_pct(product, commitment_type, lock_days, reference_fico,
                         reference_ltv_pct):
    """Returns (price_pct, lock_term_bps_applied, llpa_bps_applied)."""
    term_bps = lock_term_bps(lock_days)
    llpa = llpa_bps(product["id"], reference_fico, reference_ltv_pct)
    type_bps = (MANDATORY_TYPE_BPS if commitment_type == "MANDATORY"
                else BEST_EFFORTS_TYPE_BPS)
    raw = dec(product["base_price_pct"]) + dec(term_bps + llpa + type_bps) / dec(100)
    clamped = max(PRICE_FLOOR_PCT, min(PRICE_CEILING_PCT, raw))
    return pct3(clamped), term_bps, llpa


# --------------------------------------------------------------------------
# pair_off_fee_cents
# --------------------------------------------------------------------------

def tolerance_cents(notional_amount_cents):
    return floor_int(dec(notional_amount_cents) * PAIR_OFF_TOLERANCE_PCT / dec(100))


def pair_off_fee(commitment, variant, market_price_pct=None):
    """Returns (fee_cents, method).

    variant is one of MANDATORY_MARK_TO_MARKET, BEST_EFFORTS_ADMIN_ONLY,
    ADMINISTRATIVE_FLAT. shortfall is available_amount_cents measured BEFORE
    the write-off.
    """
    shortfall = commitment["available_amount_cents"]
    tol = commitment["tolerance_cents"]
    billable = max(0, shortfall - tol)
    admin_fee = PAIR_OFF_ADMIN_FEE_CENTS if billable > 0 else 0
    if variant == "MANDATORY_MARK_TO_MARKET":
        spread = dec(commitment["commitment_price_pct"]) - dec(market_price_pct)
        if spread < 0:
            spread = dec(0)
        market_loss = cents(dec(billable) * spread / dec(100))
        return market_loss + admin_fee, variant
    return admin_fee, variant


# --------------------------------------------------------------------------
# volume_incentive_bps
# --------------------------------------------------------------------------

def volume_incentive_bps(seller_id, exclude_loan_id, issuance_instant):
    """MTD purchased UPB tier, strictly excluding the loan under advice."""
    start = month_start(issuance_instant)
    mtd = 0
    for loan in db.loans.values():
        if loan["seller_id"] != seller_id:
            continue
        if loan["id"] == exclude_loan_id:
            continue
        if loan["purchase_status"] not in PURCHASED_STATUSES:
            continue
        purchased_dt = loan.get("_purchased_at_dt")
        if purchased_dt is None:
            continue
        if start <= purchased_dt < issuance_instant:
            mtd += loan["note_amount_cents"]
    bps = 0
    if mtd >= VOLUME_TIER_1_CENTS:
        bps = TIER_1_BPS
    if mtd >= VOLUME_TIER_2_CENTS:
        bps = TIER_2_BPS
    return bps


def final_purchase_price_pct(commitment_price, incentive_bps):
    return pct3(dec(commitment_price) + dec(incentive_bps) / dec(100))


# --------------------------------------------------------------------------
# purchase_advice_net_wire_cents
# --------------------------------------------------------------------------

def loan_defects(loan_id):
    return by_created([d for d in db.defects.values() if d["loan_id"] == loan_id])


def defect_price_adjustment_cents(loan):
    """Per-defect independent rounding, then summed; negative or zero."""
    total = 0
    for defect in loan_defects(loan["id"]):
        if defect["status"] == "WAIVED":
            bps = defect.get("price_adjustment_bps") or 0
        elif defect["status"] == "EXPIRED":
            bps = EXPIRED_DEFECT_PENALTY_BPS
        else:
            continue
        hit = cents(dec(loan["note_amount_cents"]) * dec(abs(bps)) / dec(10000))
        total += hit
    return -total


def advice_amounts(loan, product, final_price_pct, issuance_instant):
    """Every money component of a PurchaseAdvice, each rounded independently."""
    accrued_days = whole_days_between(loan["closing_date"],
                                      issuance_instant.date())
    note = dec(loan["note_amount_cents"])
    principal = cents(note * dec(final_price_pct) / dec(100))
    accrued_interest = cents(note * dec(loan["note_rate_pct"]) / dec(100)
                             * dec(accrued_days) / dec(DAY_COUNT_BASIS))
    released = loan["servicing_election"] == "RELEASED"
    escrow_funding = loan["escrow_balance_cents"] if released else 0
    srp = (cents(note * dec(product["srp_pct"]) / dec(100)) if released else 0)
    defect_adjustment = defect_price_adjustment_cents(loan)
    wire_fee = WIRE_FEE_CENTS
    net_wire = (principal + accrued_interest + escrow_funding + srp
                + defect_adjustment - wire_fee)
    return {
        "accrued_days": accrued_days,
        "principal_purchase_cents": principal,
        "accrued_interest_cents": accrued_interest,
        "escrow_funding_cents": escrow_funding,
        "service_release_premium_cents": srp,
        "defect_price_adjustment_cents": defect_adjustment,
        "wire_fee_cents": wire_fee,
        "net_wire_cents": net_wire,
    }


# --------------------------------------------------------------------------
# defect_classification
# --------------------------------------------------------------------------

def defect_classification(category, severity):
    if severity == "CRITICAL" or (category == "COMPLIANCE" and severity == "HIGH"):
        return "NON_CURABLE"
    return "CURABLE"


def cure_deadline(classification, severity, created_dt):
    if classification == "NON_CURABLE":
        return None
    return plus_days(created_dt, CURE_WINDOW_DAYS[severity])


def suspense_due(created_dt):
    return plus_days(created_dt, SUSPENSE_WINDOW_DAYS)


# --------------------------------------------------------------------------
# qc_review_outcome
# --------------------------------------------------------------------------

def qc_review_outcome(findings_count, critical_findings_count):
    if critical_findings_count >= 1:
        return "FAIL"
    if findings_count >= CONDITIONAL_PASS_FINDINGS_THRESHOLD:
        return "CONDITIONAL_PASS"
    return "PASS"


# --------------------------------------------------------------------------
# seller_mandatory_exposure_limit
# --------------------------------------------------------------------------

def mandatory_exposure_limit(outcome, tangible_net_worth_cents):
    multiplier = (NET_WORTH_MULTIPLIER_STANDARD if outcome == "PASS"
                  else NET_WORTH_MULTIPLIER_CONDITIONAL)
    return min(multiplier * tangible_net_worth_cents,
               MANDATORY_EXPOSURE_ABSOLUTE_CAP_CENTS)


# --------------------------------------------------------------------------
# repurchase_price_cents
# --------------------------------------------------------------------------

def repurchase_price(funding_recovery_cents):
    admin_fee = REPURCHASE_ADMIN_FEE_CENTS
    return funding_recovery_cents + admin_fee, admin_fee


# --------------------------------------------------------------------------
# seller_defect_rate_bps
# --------------------------------------------------------------------------

DEFECTIVE_DEMAND_STATUSES = ("ISSUED", "APPEALED", "UPHELD", "SATISFIED")


def loan_demands(loan_id):
    return by_created([d for d in db.demands.values() if d["loan_id"] == loan_id])


def is_defective(loan):
    for defect in loan_defects(loan["id"]):
        if (defect["severity"] in ("HIGH", "CRITICAL")
                and defect["status"] in ("WAIVED", "EXPIRED")):
            return True
    for demand in loan_demands(loan["id"]):
        if demand["status"] in DEFECTIVE_DEMAND_STATUSES:
            return True
    return False


def scored_loans(seller_id, period_start, period_end):
    """Loans purchased inside the CLOSED period interval (both ends inclusive)."""
    from store import date_end as _date_end
    window_start = date_start(period_start)
    window_end = _date_end(period_end)
    result = []
    for loan in db.loans.values():
        if loan["seller_id"] != seller_id:
            continue
        if loan["purchase_status"] not in PURCHASED_STATUSES:
            continue
        purchased_dt = loan.get("_purchased_at_dt")
        if purchased_dt is None:
            continue
        if window_start <= purchased_dt <= window_end:
            result.append(loan)
    return by_created(result)


def defect_rate_metrics(seller_id, period_start, period_end):
    scored = scored_loans(seller_id, period_start, period_end)
    purchased_loan_count = len(scored)
    purchased_upb_cents = sum(l["note_amount_cents"] for l in scored)
    defective = [l for l in scored if is_defective(l)]
    defective_loan_count = len(defective)
    defective_upb_cents = sum(l["note_amount_cents"] for l in defective)

    if purchased_loan_count == 0:
        defect_rate_bps = 0
        upb_weighted_defect_rate_bps = 0
    else:
        defect_rate_bps = int(round_half_up(
            dec(10000) * dec(defective_loan_count) / dec(purchased_loan_count), 0))
        if purchased_upb_cents == 0:
            upb_weighted_defect_rate_bps = 0
        else:
            upb_weighted_defect_rate_bps = int(round_half_up(
                dec(10000) * dec(defective_upb_cents) / dec(purchased_upb_cents), 0))

    if purchased_loan_count < MIN_SCORED_LOANS:
        grade = "UNRATED"
    elif defect_rate_bps <= GRADE_A_MAX_BPS:
        grade = "A"
    elif defect_rate_bps <= GRADE_B_MAX_BPS:
        grade = "B"
    elif defect_rate_bps <= GRADE_C_MAX_BPS:
        grade = "C"
    else:
        grade = "D"

    breach = (purchased_loan_count >= MIN_SCORED_LOANS
              and defect_rate_bps > DEFECT_RATE_SUSPENSION_BPS)

    return {
        "purchased_loan_count": purchased_loan_count,
        "purchased_upb_cents": purchased_upb_cents,
        "defective_loan_count": defective_loan_count,
        "defective_upb_cents": defective_upb_cents,
        "defect_rate_bps": defect_rate_bps,
        "upb_weighted_defect_rate_bps": upb_weighted_defect_rate_bps,
        "grade": grade,
        "breach": breach,
    }


# --------------------------------------------------------------------------
# scorecard_standing_action
# --------------------------------------------------------------------------

def scorecard_standing_action(metrics, seller):
    rate = metrics["defect_rate_bps"]
    if metrics["purchased_loan_count"] < MIN_SCORED_LOANS:
        return "NONE"
    if rate > DEFECT_RATE_SUSPENSION_BPS:
        return "SUSPENDED"
    if rate > DEFECT_RATE_WATCH_BPS:
        return "WATCH"
    if seller["delivery_standing"] == "WATCH":
        return "RECOVERED"
    return "NONE"
