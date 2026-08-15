"""Calculation rules (SCAFFOLD §1.3) and TaxYear derived-field recomputation.

Every function here is a pure function of stored state (plus the logical clock
for interest). All money arithmetic is integer-cents exact; the single
round-half-up step named by each rule is applied via round_half_up_int.
"""
from db import db, touch_year
from util import parse_date, whole_months, round_half_up_int

# Calculation constants (SCAFFOLD §1.3)
UTP_RECOGNITION_THRESHOLD_BP = 5000   # strictly greater-than: exactly 5000 is NOT recognized
UTP_INTEREST_RATE_BP = 500            # 5% per annum on the unrecognized benefit
SAFE_HARBOR_PCT_BP = 10000            # 100% of prior-year tax
LATE_PENALTY_RATE_BP = 400            # 4% of the shortfall, assessed once
STATUTE_YEARS = 3                     # DISCLOSED -> LAPSED once clock > filed_on + 3 years


# ---------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------

def filings_of_year(tax_year_id: str):
    return [f for f in db.filings.values() if f["tax_year_id"] == tax_year_id]


def differences_of_year(tax_year_id: str):
    return [d for d in db.differences.values() if d["tax_year_id"] == tax_year_id]


def deferred_items_of_year(tax_year_id: str):
    return [i for i in db.deferred_items.values() if i["tax_year_id"] == tax_year_id]


def vas_of_year(tax_year_id: str):
    return [v for v in db.valuation_allowances.values() if v["tax_year_id"] == tax_year_id]


def utps_of_year(tax_year_id: str):
    return [p for p in db.utps.values() if p["tax_year_id"] == tax_year_id]


def payments_of_pair(tax_year_id: str, jurisdiction_id: str):
    return [p for p in db.payments.values()
            if p["tax_year_id"] == tax_year_id and p["jurisdiction_id"] == jurisdiction_id]


# ---------------------------------------------------------------------------
# calculations.difference_amount — exact integer subtraction, no rounding
# ---------------------------------------------------------------------------

def compute_difference_cents(book_amount_cents: int, tax_amount_cents: int) -> int:
    return book_amount_cents - tax_amount_cents


# ---------------------------------------------------------------------------
# calculations.deferred_tax_movement — one round_half_up on the product
# ---------------------------------------------------------------------------

def compute_deferred_movement(difference_cents: int, enacted_federal_rate_bp: int):
    """Returns (item_kind, movement_cents) for a LOCKED TEMPORARY difference."""
    item_kind = "ASSET" if difference_cents > 0 else "LIABILITY"
    movement = round_half_up_int(abs(difference_cents) * enacted_federal_rate_bp, 10000)
    return item_kind, movement


# ---------------------------------------------------------------------------
# calculations.valuation_allowance_measurement — threshold with nested min/max
# ---------------------------------------------------------------------------

def compute_allowance_amount(va: dict, year: dict) -> int:
    total_gross_dta = sum(i["closing_balance_cents"]
                          for i in deferred_items_of_year(year["id"])
                          if i["item_kind"] == "ASSET")
    if not va["more_likely_than_not"]:
        return total_gross_dta  # full allowance
    income_support = round_half_up_int(
        va["projected_taxable_income_cents"] * year["enacted_federal_rate_bp"], 10000)
    realizable = min(total_gross_dta, va["reversing_dtl_cents"] + income_support)
    return max(0, total_gross_dta - realizable)


# ---------------------------------------------------------------------------
# calculations.utp_recognition_measurement — strict > threshold
# ---------------------------------------------------------------------------

def compute_utp_measurement(position_amount_cents: int, cumulative_probability_bp: int):
    recognized = position_amount_cents if cumulative_probability_bp > UTP_RECOGNITION_THRESHOLD_BP else 0
    liability = position_amount_cents - recognized
    disclosure_required = liability > 0
    return recognized, liability, disclosure_required


def compute_utp_interest(pos: dict, today) -> int:
    """interest = round_half_up(liability * 500bp/10000 * whole_months(measured_on -> today)/12).

    Single round-half-up on the final product: (liability * 500 * months) / 120000.
    Zero until first measured.
    """
    liability = pos.get("liability_cents") or 0
    measured_on = pos.get("measured_on")
    if not measured_on or liability <= 0:
        return 0
    months = whole_months(parse_date(measured_on), today)
    if months <= 0:
        return 0
    return round_half_up_int(liability * UTP_INTEREST_RATE_BP * months, 10000 * 12)


# ---------------------------------------------------------------------------
# calculations.current_tax_stack — pinned 5-step evaluation order (state tax
# is federally deductible; state components computed first, then deducted).
# Returns (total_cents, {jurisdiction_id: component_cents}).
# ---------------------------------------------------------------------------

def compute_current_tax_stack(year: dict):
    perm_total = sum(d["difference_cents"] for d in differences_of_year(year["id"])
                     if d["status"] == "LOCKED" and d["difference_type"] == "PERMANENT")
    # Jurisdictions with >= 1 Filing in this year, in filing-creation order
    jur_ids = []
    for f in filings_of_year(year["id"]):
        if f["jurisdiction_id"] not in jur_ids:
            jur_ids.append(f["jurisdiction_id"])

    components = {}
    state_sum = 0
    for jid in jur_ids:
        j = db.jurisdictions.get(jid)
        if j is None or j["level"] == "FEDERAL":
            continue
        base = year["pretax_book_income_cents"] + perm_total
        comp = round_half_up_int(base * j["apportionment_pct_bp"] * j["statutory_rate_bp"], 10 ** 8)
        components[jid] = comp
        state_sum += comp

    federal_tax = 0
    has_federal_filing = any(
        (db.jurisdictions.get(jid) or {}).get("level") == "FEDERAL" for jid in jur_ids)
    if has_federal_filing:
        federal_base = year["pretax_book_income_cents"] + perm_total - state_sum
        federal_tax = round_half_up_int(federal_base * year["enacted_federal_rate_bp"], 10000)
    for jid in jur_ids:
        j = db.jurisdictions.get(jid)
        if j is not None and j["level"] == "FEDERAL":
            components[jid] = federal_tax

    return state_sum + federal_tax, components


# ---------------------------------------------------------------------------
# calculations.estimated_payment_schedule — pinned round-per-quarter
# cumulatively against the exact (unrounded) rational cumulative target.
# ---------------------------------------------------------------------------

def compute_annual_estimate(year: dict, jurisdiction: dict, method: str) -> int:
    if method == "PRIOR_YEAR_SAFE_HARBOR":
        return round_half_up_int(
            year["prior_year_total_tax_cents"] * jurisdiction["apportionment_pct_bp"]
            * SAFE_HARBOR_PCT_BP, 10 ** 8)
    # CURRENT_YEAR_ANNUALIZED
    return round_half_up_int(
        year["pretax_book_income_cents"] * jurisdiction["apportionment_pct_bp"]
        * jurisdiction["statutory_rate_bp"], 10 ** 8)


def compute_quarterly_amounts(annual_estimate_cents: int) -> list:
    """[q1..q4]; quarter n = round_half_up(annual*n/4 - sum(q1..qn-1))."""
    amounts = []
    prev_sum = 0
    for n in range(1, 5):
        q = round_half_up_int(annual_estimate_cents * n - 4 * prev_sum, 4)
        amounts.append(q)
        prev_sum += q
    return amounts


# ---------------------------------------------------------------------------
# calculations.underpayment_penalty — assessed once at the LATE transition
# ---------------------------------------------------------------------------

def compute_underpayment_penalty(scheduled_amount_cents: int, paid_amount_cents: int) -> int:
    shortfall = scheduled_amount_cents - paid_amount_cents
    return round_half_up_int(shortfall * LATE_PENALTY_RATE_BP, 10000)


# ---------------------------------------------------------------------------
# TaxYear derived fields — eager recomputation (PRD §2.10)
# ---------------------------------------------------------------------------

def recompute_current_provision(year: dict):
    """Maintained only while the year is OPEN; frozen at lock-provision."""
    if year["status"] != "OPEN":
        return
    total, _components = compute_current_tax_stack(year)
    if year["current_provision_cents"] != total:
        year["current_provision_cents"] = total
        touch_year(year)


def recompute_deferred(year: dict):
    items = deferred_items_of_year(year["id"])
    liab_mov = sum(i["movement_cents"] for i in items if i["item_kind"] == "LIABILITY")
    asset_mov = sum(i["movement_cents"] for i in items if i["item_kind"] == "ASSET")
    asset_close = sum(i["closing_balance_cents"] for i in items if i["item_kind"] == "ASSET")
    liab_close = sum(i["closing_balance_cents"] for i in items if i["item_kind"] == "LIABILITY")
    year["deferred_expense_cents"] = liab_mov - asset_mov
    year["net_deferred_asset_cents"] = asset_close - liab_close
    touch_year(year)


def recompute_valuation_allowance_ref(year: dict):
    """allowance_amount_cents of the year's APPROVED assessment; 0 when none."""
    approved = [v for v in vas_of_year(year["id"]) if v["status"] == "APPROVED"]
    year["valuation_allowance_cents"] = approved[-1]["allowance_amount_cents"] if approved else 0
    touch_year(year)


def recompute_utp_reserve(year: dict):
    """Sum of liability_cents over MEASURED or DISCLOSED positions."""
    year["utp_liability_cents"] = sum(
        (p["liability_cents"] or 0) for p in utps_of_year(year["id"])
        if p["status"] in ("MEASURED", "DISCLOSED"))
    touch_year(year)


def recompute_rtp(year: dict):
    """Sum over FILED/ACCEPTED filings of (return liability - estimate). Full recompute."""
    year["return_to_provision_adjustment_cents"] = sum(
        (f["return_tax_liability_cents"] or 0) - f["estimated_liability_cents"]
        for f in filings_of_year(year["id"]) if f["status"] in ("FILED", "ACCEPTED"))
    touch_year(year)


def recompute_etrs(year: dict):
    """calculations.etr_calculation — both variants, one round_half_up each."""
    pretax = year["pretax_book_income_cents"]
    forecast_total = (year["current_provision_cents"] + year["deferred_expense_cents"]
                      + year["utp_liability_cents"] + year["valuation_allowance_cents"])
    filed_sum = sum((f["return_tax_liability_cents"] or 0)
                    for f in filings_of_year(year["id"]) if f["status"] in ("FILED", "ACCEPTED"))
    actual_total = filed_sum + year["deferred_expense_cents"] + year["valuation_allowance_cents"]
    year["forecast_etr_bp"] = round_half_up_int(forecast_total * 10000, pretax)
    year["actual_etr_bp"] = round_half_up_int(actual_total * 10000, pretax)
    touch_year(year)


def recompute_open_year_stack_and_etrs(year: dict):
    """Filing creation / difference lock-or-reject / jurisdiction creation trigger."""
    recompute_current_provision(year)
    recompute_etrs(year)


# ---------------------------------------------------------------------------
# calculations.rtp_trueup hop (b): re-spread the filing's own delta across the
# jurisdiction's SCHEDULED CURRENT_YEAR_ANNUALIZED quarters, FROM BASE, so the
# spread sums exactly to delta and repeated files are idempotent.
# ---------------------------------------------------------------------------

def respread_rtp_payments(year: dict, filing: dict):
    delta = (filing["return_tax_liability_cents"] or 0) - filing["estimated_liability_cents"]
    targets = sorted(
        (p for p in payments_of_pair(year["id"], filing["jurisdiction_id"])
         if p["status"] == "SCHEDULED" and p["method"] == "CURRENT_YEAR_ANNUALIZED"),
        key=lambda p: p["quarter_index"])
    if not targets:
        return
    from db import touch
    n = len(targets)
    base_delta = round_half_up_int(delta, n)
    for idx, p in enumerate(targets):
        assigned = base_delta if idx < n - 1 else delta - base_delta * (n - 1)
        p["scheduled_amount_cents"] = p["base_scheduled_amount_cents"] + assigned
        touch(p)
