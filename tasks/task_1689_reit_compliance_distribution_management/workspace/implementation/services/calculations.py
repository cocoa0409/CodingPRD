"""Calculation functions per SCAFFOLD §1.3 / PRD §3.

Money: integer cents, round-half-up (Decimal). Percentages: 4 decimal places,
round-half-up. Never float arithmetic for money.
"""

from decimal import Decimal, ROUND_HALF_UP

from db import db

PCT4 = Decimal("0.0001")


def _pct(numerator, denominator):
    """Percentage to 4 decimals, round-half-up. Returns float for JSON output."""
    if denominator == 0:
        return 0.0
    value = (Decimal(numerator) * Decimal(100) / Decimal(denominator)).quantize(
        PCT4, rounding=ROUND_HALF_UP
    )
    return float(value)


def _round_cents(value):
    """Round a Decimal to whole cents, half-up, returning int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# calc_asset_test_75 + calc_trs_concentration (same sweep)
# ---------------------------------------------------------------------------

def calc_asset_test(reit_id):
    """Sweep HELD AssetHolding rows for the reit.

    Returns dict: qualifying_75_pct, trs_concentration_pct, test_75_passed,
    trs_test_passed, gross_asset_total_cents.
    """
    held = [
        a for a in db.asset_holdings.values()
        if a["reit_id"] == reit_id and a["status"] == "HELD"
    ]
    total = sum(a["value_cents"] for a in held)
    qualifying = sum(
        a["value_cents"] for a in held
        if a["asset_class"] in ("REAL_ESTATE", "QUALIFYING_SECURITY")
    )
    trs_value = sum(a["value_cents"] for a in held if a["held_by_trs"])

    # Empty-set rule: no held assets -> 0.0000 for both (fails the 75% test).
    if total == 0:
        qualifying_75_pct = 0.0
        trs_concentration_pct = 0.0
    else:
        qualifying_75_pct = _pct(qualifying, total)
        trs_concentration_pct = _pct(trs_value, total)

    return {
        "qualifying_75_pct": qualifying_75_pct,
        "trs_concentration_pct": trs_concentration_pct,
        "test_75_passed": Decimal(str(qualifying_75_pct)) >= Decimal("75.0000"),
        "trs_test_passed": Decimal(str(trs_concentration_pct)) <= Decimal("20.0000"),
        "gross_asset_total_cents": total,
    }


# ---------------------------------------------------------------------------
# calc_income_test
# ---------------------------------------------------------------------------

def calc_income_test(quarter_id):
    """Sweep IncomeItem rows for the quarter (all classes, regardless of source_is_trs)."""
    items = [i for i in db.income_items.values() if i["quarter_id"] == quarter_id]
    total = sum(i["amount_cents"] for i in items)
    q75 = sum(i["amount_cents"] for i in items if i["income_class"] == "RENTS")
    q95 = sum(
        i["amount_cents"] for i in items
        if i["income_class"] in ("RENTS", "MORTGAGE_INTEREST")
    )
    if total == 0:
        qualifying_75_pct = 0.0
        qualifying_95_pct = 0.0
    else:
        qualifying_75_pct = _pct(q75, total)
        qualifying_95_pct = _pct(q95, total)
    return {
        "qualifying_75_pct": qualifying_75_pct,
        "qualifying_95_pct": qualifying_95_pct,
        "test_75_passed": Decimal(str(qualifying_75_pct)) >= Decimal("75.0000"),
        "test_95_passed": Decimal(str(qualifying_95_pct)) >= Decimal("95.0000"),
        "gross_income_total_cents": total,
    }


# ---------------------------------------------------------------------------
# calc_five_fifty
# ---------------------------------------------------------------------------

def calc_five_fifty(snapshot, reit):
    """Compute concentration percentages, top-5 individual concentration, and
    charter-limit violators for a snapshot.

    Sort key: shares_held DESC, tie-break Shareholder.created_at ASC (never id).
    Returns dict with per-position concentrations, top5_individual_pct,
    five_fifty_passed, violator_shareholder_ids.
    """
    positions = [
        p for p in db.shareholder_positions.values()
        if p["snapshot_id"] == snapshot["id"]
    ]
    total_shares = snapshot["total_shares_outstanding"]

    # Per-position concentration (4 decimals, half-up)
    conc_by_position = {}
    for p in positions:
        conc_by_position[p["id"]] = _pct(p["shares_held"], total_shares)

    # Individuals only for the top-5 test
    individuals = []
    for p in positions:
        sh = db.shareholders.get(p["shareholder_id"])
        if sh is not None and sh["holder_type"] == "INDIVIDUAL":
            individuals.append((p, sh))
    individuals.sort(key=lambda t: (-t[0]["shares_held"], t[1]["created_at"]))
    top5 = individuals[:5]
    top5_sum = sum(Decimal(str(conc_by_position[p["id"]])) for p, _ in top5)
    top5_individual_pct = float(top5_sum.quantize(PCT4, rounding=ROUND_HALF_UP))
    five_fifty_passed = Decimal(str(top5_individual_pct)) <= Decimal("50.0000")

    # Violators: concentration strictly exceeds charter limit; both holder types count.
    limit = Decimal(str(reit["charter_ownership_limit_pct"]))
    violators = [
        (p, db.shareholders.get(p["shareholder_id"]))
        for p in positions
        if Decimal(str(conc_by_position[p["id"]])) > limit
    ]
    violators.sort(
        key=lambda t: (
            -t[0]["shares_held"],
            t[1]["created_at"] if t[1] is not None else "",
        )
    )
    violator_shareholder_ids = [p["shareholder_id"] for p, _ in violators]

    return {
        "concentration_by_position": conc_by_position,
        "top5_individual_pct": top5_individual_pct,
        "five_fifty_passed": five_fifty_passed,
        "violator_shareholder_ids": violator_shareholder_ids,
    }


# ---------------------------------------------------------------------------
# calc_distribution_requirement
# ---------------------------------------------------------------------------

def calc_distribution_requirement(taxable_income_cents, net_capital_gain_cents):
    """90% of (taxable_income - net_capital_gain), floor 0, round-half-up cents."""
    base = taxable_income_cents - net_capital_gain_cents
    if base <= 0:
        return 0
    return _round_cents(Decimal(base) * Decimal("0.90"))


# ---------------------------------------------------------------------------
# calc_dividend_characterization (waterfall + pro-rata variant)
# ---------------------------------------------------------------------------

def capital_gain_pool(reit_id, taxable_year, requirement):
    """Remaining capital-gain pool: requirement.net_capital_gain_cents minus
    capital_gain_cents already characterized on DECLARED/PAID siblings."""
    used = sum(
        d["capital_gain_cents"]
        for d in db.dividend_declarations.values()
        if d["reit_id"] == reit_id
        and d["taxable_year"] == taxable_year
        and d["status"] in ("DECLARED", "PAID")
    )
    return requirement["net_capital_gain_cents"] - used


def calc_dividend_characterization_waterfall(amount_cents, ep_balance_cents, cg_pool):
    """Waterfall (conduit) allocation: ordinary from E&P first, then capital
    gain against the remaining pool, then return of capital. Integer cents."""
    ordinary = min(amount_cents, max(0, ep_balance_cents))
    remainder1 = amount_cents - ordinary
    capital_gain = min(remainder1, max(0, cg_pool))
    remainder2 = remainder1 - capital_gain
    return {
        "ordinary_cents": ordinary,
        "capital_gain_cents": capital_gain,
        "return_of_capital_cents": remainder2,
    }


def calc_dividend_characterization_pro_rata(amount_cents, ep_balance_cents, cg_pool):
    """Pro-rata variant: ordinary = amount * clamped_E&P / (clamped_E&P + clamped_pool),
    half-up to whole cents (0 when denominator == 0); capital gain = remainder
    capped at pool; ROC absorbs the rest."""
    ep = max(0, ep_balance_cents)
    pool = max(0, cg_pool)
    denom = ep + pool
    if denom <= 0:
        ordinary = 0
    else:
        ordinary = _round_cents(Decimal(amount_cents) * Decimal(ep) / Decimal(denom))
    remainder = amount_cents - ordinary
    capital_gain = min(remainder, pool)
    if capital_gain < 0:
        capital_gain = 0
    roc = amount_cents - ordinary - capital_gain
    return {
        "ordinary_cents": ordinary,
        "capital_gain_cents": capital_gain,
        "return_of_capital_cents": roc,
    }


# ---------------------------------------------------------------------------
# calc_ep_balance
# ---------------------------------------------------------------------------

def calc_ep_balance(reit_id, as_of=None):
    """Chronological replay of POSTED EpAdjustment rows ordered by
    effective_date ASC, tie-break created_at ASC (never id).

    TAXABLE_INCOME / DISALLOWED_DEDUCTION add; FEDERAL_TAX subtracts. Then
    subtract ordinary_cents of DECLARED/PAID dividends. When as_of is given
    (frozen year-end view), only adjustments with effective_date <= as_of are
    replayed; dividend ordinary debits still apply in full (the variant
    difference excludes only late adjustments).
    """
    adjustments = [
        a for a in db.ep_adjustments.values()
        if a["reit_id"] == reit_id and a["status"] == "POSTED"
    ]
    if as_of is not None:
        adjustments = [a for a in adjustments if a["effective_date"] <= as_of]
    adjustments.sort(key=lambda a: (a["effective_date"], a["created_at"]))

    balance = 0
    for adj in adjustments:
        if adj["kind"] in ("TAXABLE_INCOME", "DISALLOWED_DEDUCTION"):
            balance += adj["amount_cents"]
        elif adj["kind"] == "FEDERAL_TAX":
            balance -= adj["amount_cents"]

    ordinary_debits = sum(
        d["ordinary_cents"]
        for d in db.dividend_declarations.values()
        if d["reit_id"] == reit_id and d["status"] in ("DECLARED", "PAID")
    )
    balance -= ordinary_debits
    return balance


# ---------------------------------------------------------------------------
# calc_prohibited_transaction
# ---------------------------------------------------------------------------

def calc_prohibited_transaction(asset, sale_price_cents, basis_cents, sale_date):
    """holding_period_months = floor(days / 30); prohibited when dealer inventory
    and < 24 months; tax = 100% of net gain when prohibited and gain > 0."""
    acq = asset["acquisition_date"]
    days = (parse(sale_date) - parse(acq)).days
    holding_period_months = days // 30
    is_prohibited = bool(asset["is_dealer_inventory"]) and holding_period_months < 24
    gain = sale_price_cents - basis_cents
    prohibited_tax_cents = gain if (is_prohibited and gain > 0) else 0
    return {
        "holding_period_months": holding_period_months,
        "is_prohibited": is_prohibited,
        "prohibited_tax_cents": prohibited_tax_cents,
    }


def parse(s):
    from datetime import date
    return date.fromisoformat(s)
