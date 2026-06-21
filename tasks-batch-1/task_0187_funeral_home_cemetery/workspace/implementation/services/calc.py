"""Calculation rules (PRD §2.6, §2.8, §3; SCAFFOLD §1.3).

All money is integer cents. Tax / trust fraction rounding uses round-half-up;
the projected-earnings term uses floor. Decimal is used so the half-up boundary
is exact (never IEEE-754 drift).
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

import db

PROJECTION_RATE = Decimal("0.03")


def round_half_up(value):
    """Round a Decimal to the nearest whole cent, halves up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_to_int(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_FLOOR))


def _frac(x):
    """Represent a stored fraction (e.g. sales_tax_pct) exactly as Decimal."""
    return Decimal(str(x))


# --------------------------------------------------------------------------
# StatementLine contribution: per-line rounded tax then summed (pinned order).
# --------------------------------------------------------------------------
def line_total(line, sales_tax_pct):
    subtotal = line["unit_price_cents"] * line["quantity"]
    if line.get("taxable"):
        tax = round_half_up(Decimal(subtotal) * _frac(sales_tax_pct))
    else:
        tax = 0
    return subtotal + tax


def _home_for_case(case):
    return db.funeral_homes.get(case["funeral_home_id"])


def _lines_for_case(case_id):
    return [l for l in db.statement_lines.values() if l["case_id"] == case_id]


def case_statement_totals(case):
    """Return (provisional, final_over_selected) recomputed from current lines.

    provisional = sum over PROPOSED+SELECTED lines.
    final_over_selected = sum over SELECTED-only lines (used to lock at GFS).
    """
    home = _home_for_case(case)
    sales_tax_pct = home["sales_tax_pct"] if home else 0
    lines = _lines_for_case(case["id"])
    provisional = 0
    final = 0
    for l in lines:
        status = l["line_status"]
        if status == "REMOVED":
            continue
        contrib = line_total(l, sales_tax_pct)
        if status in ("PROPOSED", "SELECTED"):
            provisional += contrib
        if status == "SELECTED":
            final += contrib
    return provisional, final


def trustable_base_selected(case):
    """Sum of per-line contributions over SELECTED + preneed_trustable lines."""
    home = _home_for_case(case)
    sales_tax_pct = home["sales_tax_pct"] if home else 0
    total = 0
    for l in _lines_for_case(case["id"]):
        if l["line_status"] == "SELECTED" and l.get("preneed_trustable"):
            total += line_total(l, sales_tax_pct)
    return total


# --------------------------------------------------------------------------
# Trust ledger (conserved). Per-contract principal / earnings.
# --------------------------------------------------------------------------
def _deposits_for_contract(contract_id):
    return [d for d in db.trust_deposits.values() if d["contract_id"] == contract_id]


def trust_principal(contract_id):
    deposits = _deposits_for_contract(contract_id)
    principal = 0
    for d in deposits:
        if d["status"] != "POSTED":
            continue
        if d["kind"] == "PRINCIPAL":
            principal += d["amount_cents"]
        elif d["kind"] == "REFUND":
            principal -= d["amount_cents"]
    return principal


def credited_earnings(contract_id):
    total = 0
    for d in _deposits_for_contract(contract_id):
        if d["status"] == "POSTED" and d["kind"] == "EARNINGS":
            total += d["amount_cents"]
    return total


def projected_earnings(contract, principal):
    if contract["funding_type"] != "PRENEED_TRUST":
        return 0
    return floor_to_int(Decimal(principal) * PROJECTION_RATE)


# --------------------------------------------------------------------------
# trust_required_cents (PRENEED only): conditional + tiered floor at zero.
# --------------------------------------------------------------------------
def trust_required(contract, case):
    if contract["funding_type"] != "PRENEED_TRUST":
        return 0
    home = _home_for_case(case)
    state_trust_pct = home["state_trust_pct"] if home else 0
    admin_retention = home.get("trust_admin_retention_cents", 0) if home else 0
    base = trustable_base_selected(case)
    gross = round_half_up(Decimal(base) * _frac(state_trust_pct))
    return max(0, gross - admin_retention)


# --------------------------------------------------------------------------
# contract_amount_cents: final once GFS issued, provisional before.
# --------------------------------------------------------------------------
def contract_amount(contract, case):
    if case.get("gfs_issued"):
        return case.get("statement_total_final_cents", 0)
    prov, _final = case_statement_totals(case)
    return prov


# --------------------------------------------------------------------------
# Insurance assignment verified sum.
# --------------------------------------------------------------------------
def _assignments_for_contract(contract_id):
    return [a for a in db.insurance_assignments.values() if a["contract_id"] == contract_id]


def verified_assignment_total(contract_id):
    total = 0
    for a in _assignments_for_contract(contract_id):
        if a["status"] == "VERIFIED":
            total += a["assigned_value_cents"]
    return total


def at_need_principal_chronological(contract_id):
    """Chronological replay of POSTED PRINCIPAL deposits.

    Ordered by posted_at asc, created_at asc tie-break (never id). The result is
    a plain sum so order does not change the value, but ordering is honored to
    match the specified replay semantics.
    """
    posted = [
        d for d in _deposits_for_contract(contract_id)
        if d["kind"] == "PRINCIPAL" and d["status"] == "POSTED"
    ]
    posted.sort(key=lambda d: (d.get("_posted_at_seq", 0), d.get("_seq", 0)))
    return sum(d["amount_cents"] for d in posted)


# --------------------------------------------------------------------------
# funded_amount_cents — dual variant by funding_type.
# --------------------------------------------------------------------------
def funded_amount(contract):
    ft = contract["funding_type"]
    if ft == "PRENEED_TRUST":
        principal = trust_principal(contract["id"])
        earnings = credited_earnings(contract["id"])
        projected = projected_earnings(contract, principal)
        return principal + earnings + projected
    if ft == "INSURANCE_ASSIGNMENT":
        return verified_assignment_total(contract["id"])
    # AT_NEED_DIRECT
    return at_need_principal_chronological(contract["id"])


# --------------------------------------------------------------------------
# Aggregated contract figures for serialization / gates.
# --------------------------------------------------------------------------
def contract_figures(contract):
    case = db.cases.get(contract["case_id"])
    principal = trust_principal(contract["id"])
    earnings = credited_earnings(contract["id"])
    projected = projected_earnings(contract, principal)
    return {
        "contract_amount_cents": contract_amount(contract, case) if case else 0,
        "trust_required_cents": trust_required(contract, case) if case else 0,
        "trust_principal_cents": principal,
        "credited_earnings_cents": earnings,
        "projected_earnings_cents": projected,
        "funded_amount_cents": funded_amount(contract),
    }


# --------------------------------------------------------------------------
# FuneralHome.trust_balance_cents — rollup over the home's contracts.
# --------------------------------------------------------------------------
def home_trust_balance(home_id):
    total = 0
    for con in db.contracts.values():
        case = db.cases.get(con["case_id"])
        if not case or case.get("funeral_home_id") != home_id:
            continue
        total += trust_principal(con["id"]) + credited_earnings(con["id"])
    return total


# --------------------------------------------------------------------------
# plot_charge — dual price source by reserving case mode.
# --------------------------------------------------------------------------
def plot_charge(plot, case):
    if case.get("case_mode") == "PRENEED":
        return plot.get("locked_price_cents")
    return plot.get("current_price_cents")
