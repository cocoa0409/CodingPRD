"""Calculation rules (SCAFFOLD 1.3 / PRD 3.x). All money is integer cents."""

from datetime import timedelta
from decimal import Decimal

from core import (
    add_months, clock_date, days_between, db, floor_cents, quantize, rhu,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LIQUIDITY_COVERAGE_PCT = Decimal("0.10")
EXPERIENCE_DEFAULT_PENALTY = Decimal(15)
RECENT_FLIP_TARGET = Decimal(5)
LIFETIME_FLIP_TARGET = Decimal(10)
DECAY_WEIGHT_OLDER_FLIPS = Decimal("0.5")
TIER_A_MIN = Decimal("80.00")
TIER_B_MIN = Decimal("65.00")
TIER_C_MIN = Decimal("45.00")

LTP_PCT = {"TIER_A": Decimal("0.90"), "TIER_B": Decimal("0.85"), "TIER_C": Decimal("0.80"), "TIER_D": Decimal("0.70")}
LTC_PCT = {"TIER_A": Decimal("0.90"), "TIER_B": Decimal("0.85"), "TIER_C": Decimal("0.80"), "TIER_D": Decimal("0.70")}
LTARV_PCT = {"TIER_A": Decimal("0.75"), "TIER_B": Decimal("0.70"), "TIER_C": Decimal("0.65"), "TIER_D": Decimal("0.60")}

MONTHS_PER_YEAR = Decimal(12)
BPS_BASIS = Decimal(10000)

RETAINAGE_PCT = {"INSPECTION": Decimal("0.10"), "PHOTO": Decimal("0.20")}
PHOTO_MAX_PCT = Decimal("0.50")
PHOTO_MAX_REQUEST_CENTS = 3000000
PHOTO_MIN_PHOTOS_PER_LINE = 3

DAY_BASIS = Decimal(360)
DEFAULT_RATE_SPREAD_BPS = 600

EXTENSION_FEE_BPS = Decimal(100)
EXTENSION_RATE_STEP_BPS = 50
MAX_EXTENSIONS = 2

EXIT_WATCH_DOM_DAYS = 90

SELLING_COST_PCT = Decimal("0.06")
COMPLETION_BUDGET_CAP_PCT = Decimal("0.20")

SINGLE_LINE_CAP_PCT = Decimal("0.50")
MAX_REVISION_ROUNDS = 3
DELINQUENCY_TO_DEFAULT_DAYS = 10
REDEMPTION_DAYS = 90
TRAVEL_BUFFER_MINUTES = 90

SCOPE_CODES = (
    "ROOF", "KITCHEN", "BATH", "ELECTRICAL", "PLUMBING", "HVAC",
    "FOUNDATION", "EXTERIOR", "FLOORING", "PERMITS", "CONTINGENCY",
)

ENTITY_TYPES = ("LLC", "CORP", "LP", "SOLE_PROP")
DAY_COUNT_CONVENTIONS = ("PER_DIEM_360", "PER_DIEM_365")
VERIFICATION_METHODS = ("INSPECTION", "PHOTO")
WAIVER_TYPES = ("PARTIAL_CONDITIONAL", "PARTIAL_UNCONDITIONAL", "FINAL_UNCONDITIONAL")
UNCONDITIONAL_WAIVER_TYPES = ("PARTIAL_UNCONDITIONAL", "FINAL_UNCONDITIONAL")
MILESTONE_TYPES = (
    "LISTED", "PRICE_REDUCED", "DELISTED", "UNDER_CONTRACT", "CONTRACT_FALLOUT",
    "REFI_APPLICATION", "REFI_APPRAISAL_COMPLETE", "REFI_COMMITMENT_ISSUED",
)
MILESTONE_EXIT_MAP = {
    "LISTED": "LISTED",
    "CONTRACT_FALLOUT": "LISTED",
    "PRICE_REDUCED": "LISTED",
    "UNDER_CONTRACT": "UNDER_CONTRACT",
    "REFI_APPLICATION": "REFI_IN_PROCESS",
    "REFI_APPRAISAL_COMPLETE": "REFI_IN_PROCESS",
    "REFI_COMMITMENT_ISSUED": "REFI_IN_PROCESS",
    "DELISTED": "NOT_LISTED",
}
LEDGER_ENTRY_TYPES = (
    "INITIAL_FUNDING", "DRAW_DISBURSEMENT", "RESERVE_SWEEP", "BORROWER_PAYMENT",
    "EXTENSION_FEE", "HOLDBACK_DECOMMIT", "COMPLETION_ADVANCE", "REO_SALE_PROCEEDS",
    "PAYOFF", "CHARGE_OFF",
)

LIVE_SCOPE_STATUSES = ("PROPOSED", "REVISION_REQUESTED", "APPROVED", "FULLY_RELEASED")
VOIDABLE_SCOPE_STATUSES = ("PROPOSED", "REVISION_REQUESTED", "APPROVED")
OPEN_DRAW_STATUSES = ("SUBMITTED", "INSPECTION_ORDERED", "INSPECTED", "REVISION_REQUESTED", "APPROVED")
SUSPENDABLE_DRAW_STATUSES = ("SUBMITTED", "INSPECTION_ORDERED", "INSPECTED", "APPROVED")
TERMINAL_PAYMENT_STATUSES = ("PAID_OFF", "CHARGED_OFF")


# ---------------------------------------------------------------------------
# borrower_experience_score (SCAFFOLD 1.3 / PRD 3.1)
# ---------------------------------------------------------------------------
def _clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


def experience_score(borrower, exp_units, basis_cents):
    credit = Decimal(borrower["credit_score"])
    liquidity = Decimal(borrower["liquidity_cents"])
    lifetime = Decimal(borrower["flips_lifetime"])
    defaults = Decimal(borrower["prior_default_count"])

    term_exp = Decimal(40) * min(Decimal(1), Decimal(exp_units) / RECENT_FLIP_TARGET)
    term_credit = Decimal(25) * _clamp((credit - Decimal(600)) / Decimal(200), Decimal(0), Decimal(1))
    basis = LIQUIDITY_COVERAGE_PCT * Decimal(basis_cents)
    if basis <= 0:
        ratio = Decimal(1)
    else:
        ratio = min(Decimal(1), liquidity / basis)
    term_liquidity = Decimal(20) * ratio
    term_career = Decimal(15) * min(Decimal(1), lifetime / LIFETIME_FLIP_TARGET)
    penalty = EXPERIENCE_DEFAULT_PENALTY * defaults

    raw = term_exp + term_credit + term_liquidity + term_career - penalty
    return quantize(_clamp(raw, Decimal(0), Decimal(100)), 2)


def intake_experience_score(borrower):
    return experience_score(borrower, Decimal(borrower["flips_last_24mo"]),
                            borrower["declared_target_loan_cents"])


def recert_basis_cents(borrower):
    best = None
    for loan in db.loans.values():
        if loan["borrower_id"] != borrower["id"]:
            continue
        if loan["payment_status"] not in ("CURRENT", "DELINQUENT", "DEFAULT"):
            continue
        amount = loan["committed_amount_cents"]
        if best is None or amount > best:
            best = amount
    if best is None:
        return borrower["declared_target_loan_cents"]
    return best


def recert_experience_score(borrower):
    last24 = Decimal(borrower["flips_last_24mo"])
    lifetime = Decimal(borrower["flips_lifetime"])
    exp_units = last24 + DECAY_WEIGHT_OLDER_FLIPS * (lifetime - last24)
    return experience_score(borrower, exp_units, recert_basis_cents(borrower))


def tier_for(score):
    if score is None:
        return "TIER_D"
    if score >= TIER_A_MIN:
        return "TIER_A"
    if score >= TIER_B_MIN:
        return "TIER_B"
    if score >= TIER_C_MIN:
        return "TIER_C"
    return "TIER_D"


def effective_score(borrower):
    if borrower.get("recertified_at") is not None:
        return borrower.get("recertified_experience_score")
    return borrower.get("intake_experience_score")


def experience_tier(borrower):
    return tier_for(effective_score(borrower))


# ---------------------------------------------------------------------------
# loan_sizing_max + commitment_allocation (SCAFFOLD 1.3 / PRD 3.3, 3.4)
# ---------------------------------------------------------------------------
def reserve_of(principal, quoted_rate_bps, interest_reserve_months):
    return rhu(Decimal(principal) * Decimal(quoted_rate_bps) / BPS_BASIS
               * Decimal(interest_reserve_months) / MONTHS_PER_YEAR)


def loan_sizing_max(tier, purchase_price_cents, arv_cents, rehab_cents):
    cap_purchase = floor_cents(LTP_PCT[tier] * Decimal(purchase_price_cents))
    cap_ltc = floor_cents(LTC_PCT[tier] * Decimal(purchase_price_cents + rehab_cents))
    cap_ltarv = floor_cents(LTARV_PCT[tier] * Decimal(arv_cents))
    max_total = min(cap_purchase + rehab_cents, cap_ltc, cap_ltarv)
    return cap_purchase, cap_ltc, cap_ltarv, max_total


def sizing_pass(cap_purchase, max_total, rehab, quoted_rate_bps, interest_reserve_months):
    provisional = min(cap_purchase, max_total - rehab)
    reserve_1 = reserve_of(provisional, quoted_rate_bps, interest_reserve_months)
    committed_1 = provisional + reserve_1 + rehab
    if committed_1 <= max_total:
        initial = provisional
        reserve = reserve_1
    else:
        excess = committed_1 - max_total
        initial = provisional - excess
        reserve = reserve_of(initial, quoted_rate_bps, interest_reserve_months)
    committed = initial + reserve + rehab
    return committed, initial, reserve


def decision_pass(approved_total, rehab, quoted_rate_bps, interest_reserve_months):
    provisional = approved_total - rehab
    reserve = reserve_of(provisional, quoted_rate_bps, interest_reserve_months)
    initial = provisional - reserve
    return initial, reserve, rehab


# ---------------------------------------------------------------------------
# draw_release_amount (SCAFFOLD 1.3 / PRD 3.6)
# ---------------------------------------------------------------------------
def effective_percent(claimed, verified, verification_method):
    if claimed is None or verified is None:
        return None
    eff = min(Decimal(claimed), Decimal(verified))
    if verification_method == "PHOTO":
        eff = min(eff, PHOTO_MAX_PCT)
    return quantize(eff, 2)


def line_release(approved_cost_cents, released_cents, eff, verification_method):
    if eff == Decimal("1.00"):
        retainage = Decimal(0)
    else:
        retainage = RETAINAGE_PCT[verification_method]
    earned = rhu(Decimal(approved_cost_cents) * eff)
    releasable = rhu(Decimal(earned) * (Decimal(1) - retainage))
    return releasable - released_cents


# ---------------------------------------------------------------------------
# interest accrual (SCAFFOLD 1.3 / PRD 3.7)
# ---------------------------------------------------------------------------
def rate_day_split(period_start, period_end, default_effective_date):
    day_count = days_between(period_start, period_end) + 1
    if default_effective_date is None:
        return day_count, day_count, 0
    note_days = 0
    cursor = period_start
    for _ in range(day_count):
        if cursor < default_effective_date:
            note_days += 1
        cursor = cursor + timedelta(days=1)
    return day_count, note_days, day_count - note_days


def rate_interest(principal_cents, rate_bps, days):
    return rhu(Decimal(principal_cents) * Decimal(rate_bps) / BPS_BASIS * Decimal(days) / DAY_BASIS)


# ---------------------------------------------------------------------------
# payoff_quote (SCAFFOLD 1.3 / PRD 3.7)
# ---------------------------------------------------------------------------
def payoff_quote(loan, quote_date, force_default_rate=False, principal_override=None):
    anchor = loan.get("last_accrual_through")
    if anchor is not None:
        anchor_date = anchor
    else:
        anchor_date = loan["closing_date"] - timedelta(days=1)
    per_diem_days = days_between(anchor_date, quote_date)
    if force_default_rate or loan["payment_status"] == "DEFAULT":
        rate_bps = loan["default_rate_bps"]
    else:
        rate_bps = loan["note_rate_bps"]
    divisor = Decimal(360) if loan["day_count_convention"] == "PER_DIEM_360" else Decimal(365)
    principal = loan["funded_principal_cents"] if principal_override is None else principal_override
    per_diem = rhu(Decimal(principal) * Decimal(rate_bps) / BPS_BASIS
                   * Decimal(per_diem_days) / divisor)
    return (principal + loan["accrued_interest_unpaid_cents"]
            + loan["fee_balance_cents"] + per_diem)


# ---------------------------------------------------------------------------
# extension repricing (SCAFFOLD 1.3 / PRD 3.8)
# ---------------------------------------------------------------------------
def extension_fee(funded_principal_cents, months):
    return rhu(Decimal(funded_principal_cents) * EXTENSION_FEE_BPS / BPS_BASIS * Decimal(months))


def maturity_date_for(loan):
    return add_months(loan["closing_date"], loan["term_months"] + loan["extension_months_total"])


# ---------------------------------------------------------------------------
# exit monitoring (SCAFFOLD 1.3 / PRD 3.8)
# ---------------------------------------------------------------------------
def loan_milestones(loan_id):
    return [m for m in db.exit_milestones.values() if m["loan_id"] == loan_id]


def _milestone_key(m):
    return (m["effective_date"], m["created_at"], m["_seq"])


def latest_milestone(loan_id):
    ms = loan_milestones(loan_id)
    if not ms:
        return None
    return max(ms, key=_milestone_key)


def governing_listing(loan_id):
    ms = loan_milestones(loan_id)
    listed = [m for m in ms if m["milestone_type"] == "LISTED"]
    if not listed:
        return None
    delisted = [m for m in ms if m["milestone_type"] == "DELISTED"]
    if delisted:
        newest_delist = max(delisted, key=_milestone_key)
        listed = [m for m in listed if m["effective_date"] > newest_delist["effective_date"]]
    if not listed:
        return None
    return max(listed, key=_milestone_key)


def live_days_on_market(loan):
    gov = governing_listing(loan["id"])
    if gov is None:
        return 0
    return days_between(gov["effective_date"], clock_date())


def days_on_market(loan):
    """Frozen once exit_status leaves the listing track (PRD 3.8)."""
    if loan["exit_status"] in ("REFI_IN_PROCESS", "EXITED", "FORECLOSED"):
        frozen = loan.get("_days_on_market_frozen")
        if frozen is not None:
            return frozen
    return live_days_on_market(loan)


def exit_watch_flag(loan):
    dom = days_on_market(loan)
    if dom <= EXIT_WATCH_DOM_DAYS:
        return False
    gov = governing_listing(loan["id"])
    if gov is None:
        return False
    for m in loan_milestones(loan["id"]):
        if m["milestone_type"] == "PRICE_REDUCED" and m["effective_date"] >= gov["effective_date"]:
            return False
    return True


# ---------------------------------------------------------------------------
# contractor payment control (SCAFFOLD 1.3 / PRD 3.6)
# ---------------------------------------------------------------------------
def license_status(contractor):
    return "ACTIVE" if clock_date() <= contractor["license_expires_on"] else "EXPIRED"


def payable(contractor):
    return license_status(contractor) == "ACTIVE" and bool(contractor["w9_on_file"])


def collected_waiver_coverage_cents(contractor_id):
    total = 0
    for w in db.lien_waivers.values():
        if w["contractor_id"] != contractor_id:
            continue
        if w["status"] == "COLLECTED" and w["waiver_type"] in UNCONDITIONAL_WAIVER_TYPES:
            total += w["amount_covered_cents"]
    return total


def released_to_contractor_cents(contractor_id):
    total = 0
    for line in db.rehab_line_items.values():
        if line["contractor_id"] == contractor_id:
            total += line["released_cents"]
    return total


def open_waiver_headroom_cents(contractor_id):
    return collected_waiver_coverage_cents(contractor_id) - released_to_contractor_cents(contractor_id)


def counts_toward_coverage(waiver):
    return waiver["status"] == "COLLECTED" and waiver["waiver_type"] in UNCONDITIONAL_WAIVER_TYPES


# ---------------------------------------------------------------------------
# Loan derived money views (PRD 2.5)
# ---------------------------------------------------------------------------
def available_rehab_pool_cents(loan):
    return loan["undisbursed_holdback_cents"] + loan["reserved_release_cents"]


def commitment_balance_check_cents(loan):
    return loan["committed_amount_cents"] - (
        loan["funded_principal_cents"] + loan["repaid_principal_cents"]
        + loan["reserved_release_cents"] + loan["undisbursed_holdback_cents"]
        + loan["interest_reserve_balance_cents"] + loan["decommitted_holdback_cents"]
    )


def reo_selling_costs(sale_price_cents):
    return floor_cents(SELLING_COST_PCT * Decimal(sale_price_cents))


def completion_budget_cap(arv_cents):
    return floor_cents(COMPLETION_BUDGET_CAP_PCT * Decimal(arv_cents))


def released_percent(line):
    approved = line.get("approved_cost_cents")
    if approved is None or approved == 0:
        return Decimal("0.0000")
    return quantize(Decimal(line["released_cents"]) / Decimal(approved), 4)
