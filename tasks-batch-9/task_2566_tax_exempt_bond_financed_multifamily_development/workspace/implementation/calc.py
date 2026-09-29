"""The eleven pinned calculations of PRD section 2.5 / SCAFFOLD 1.3.

Every derived figure is re-derived from stored inputs; nothing incremental.
"""


from store import (
    ceil_div, db, floor_div, parse_iso, round_half_up,
)

# ---- pinned constants -----------------------------------------------------

ISSUANCE_ALLOWANCE_BPS = 200          # two percent of provisional par
DENOMINATION_CENTS = 500000
NEG_ARB_ALLOWANCE_BPS = 200
DAY_COUNT_BASIS = 360

MIN_20_50_THRESHOLD_BPS = 2000
MIN_40_60_THRESHOLD_BPS = 4000
AVG_INCOME_THRESHOLD_BPS = 4000
AVG_INCOME_CEILING_BPS = 6000

AMI_100_ANNUAL_INCOME_CENTS = {
    1: 6300000, 2: 7200000, 3: 8100000,
    4: 9000000, 5: 9720000, 6: 10440000,
}
RENT_INCOME_SHARE_PERCENT = 30
MIN_RENT_FLOOR_CENTS = 25000

FIFTY_PERCENT_THRESHOLD_BPS = 5000
MIN_DSCR_BPS = 11500
STABILIZED_OCCUPANCY_BPS = 9000
CREDIT_PERIOD_YEARS = 10
INSPECTION_INTERVAL_DAYS = 1095
INSPECTION_BUFFER_DAYS = 14

SET_ASIDE_ELECTIONS = ("MIN_20_50", "MIN_40_60", "AVG_INCOME")
ALLOWED_AMI_PERCENTS = (20, 30, 40, 50, 60, 70, 80)

DSCR_WINDOWS = {"T3": (3, 4), "T12": (12, 1)}


# ---- row selectors --------------------------------------------------------

def unit_sort_key(unit):
    """`unit_number` is a string field, so ASC is plain lexicographic order."""
    return unit.get("unit_number") or ""


def project_units(project_id):
    rows = [u for u in db.units.values() if u.get("project_id") == project_id]
    rows.sort(key=unit_sort_key)
    return rows


def project_allocations(project_id):
    return [a for a in db.allocations.values() if a.get("project_id") == project_id]


def pool_allocations(cap_pool_id):
    return [a for a in db.allocations.values() if a.get("cap_pool_id") == cap_pool_id]


def project_issues(project_id):
    return [b for b in db.bond_issues.values() if b.get("project_id") == project_id]


def issue_draws(bond_issue_id):
    return [d for d in db.draws.values() if d.get("bond_issue_id") == bond_issue_id]


def project_agreements(project_id):
    return [r for r in db.agreements.values() if r.get("project_id") == project_id]


def project_credit_allocations(project_id):
    return [c for c in db.credit_allocations.values() if c.get("project_id") == project_id]


def allocation_deliveries(credit_allocation_id):
    return [d for d in db.deliveries.values()
            if d.get("credit_allocation_id") == credit_allocation_id]


def project_reports(project_id):
    return [r for r in db.reports.values() if r.get("project_id") == project_id]


def project_inspections(project_id):
    return [i for i in db.inspections.values() if i.get("project_id") == project_id]


def developer_projects(developer_id):
    return [p for p in db.projects.values() if p.get("developer_id") == developer_id]


def funded_draws_in_order(bond_issue_id):
    """FUNDED draws ordered by period_start ASC, draw_number ASC."""
    rows = [d for d in issue_draws(bond_issue_id) if d.get("status") == "FUNDED"]
    rows.sort(key=lambda d: (d.get("period_start") or "", d.get("draw_number") or 0))
    return rows


# ---- 1. bond sizing -------------------------------------------------------

def bond_sizing(eligible_cost_cents, capitalized_interest_cents):
    provisional_par = eligible_cost_cents + capitalized_interest_cents
    allowance = round_half_up(provisional_par * ISSUANCE_ALLOWANCE_BPS, 10000)
    unrounded_par = provisional_par + allowance
    par = ceil_div(unrounded_par, DENOMINATION_CENTS) * DENOMINATION_CENTS
    neg_arb_allowance = floor_div(par * NEG_ARB_ALLOWANCE_BPS, 10000)
    return {
        "issuance_allowance_cents": allowance,
        "par_amount_cents": par,
        "negative_arbitrage_allowance_cents": neg_arb_allowance,
    }


# ---- 2. applicable fraction ----------------------------------------------

def unit_counts(project):
    units = project_units(project["id"])
    restricted = [u for u in units if u.get("designation") == "RESTRICTED"]
    market = [u for u in units if u.get("designation") == "MARKET"]
    employee = [u for u in units if u.get("designation") == "EMPLOYEE_UNIT"]
    return units, restricted, market, employee


def applicable_fraction(project):
    units, restricted, market, employee = unit_counts(project)
    total_units = project.get("total_units") or 0
    total_sqft = project.get("total_floor_space_sqft") or 0
    unit_fraction = floor_div(len(restricted) * 10000, total_units) if total_units else 0
    restricted_sqft = sum((u.get("floor_space_sqft") or 0) for u in restricted)
    floor_fraction = floor_div(restricted_sqft * 10000, total_sqft) if total_sqft else 0
    return {
        "restricted_unit_count": len(restricted),
        "market_unit_count": len(market),
        "employee_unit_count": len(employee),
        "designated_unit_count": len(units),
        "unit_fraction_bps": unit_fraction,
        "floor_space_fraction_bps": floor_fraction,
        "applicable_fraction_bps": min(unit_fraction, floor_fraction),
    }


# ---- 3. set-aside compliance ratio ---------------------------------------

def set_aside_compliance_ratio(project, election=None):
    election = election or project.get("set_aside_election")
    if election == "MIN_20_50":
        band_cap, threshold, average_applies = 50, MIN_20_50_THRESHOLD_BPS, False
    elif election == "MIN_40_60":
        band_cap, threshold, average_applies = 60, MIN_40_60_THRESHOLD_BPS, False
    else:
        band_cap, threshold, average_applies = 80, AVG_INCOME_THRESHOLD_BPS, True

    _units, restricted, _m, _e = unit_counts(project)
    qualifying = [u for u in restricted
                  if u.get("ami_percent") is not None and u["ami_percent"] <= band_cap]
    total_units = project.get("total_units") or 0
    ratio = floor_div(len(qualifying) * 10000, total_units) if total_units else 0
    if qualifying:
        average_bps = floor_div(
            sum(u["ami_percent"] for u in qualifying) * 100, len(qualifying))
    else:
        average_bps = 0

    satisfied = ratio >= threshold
    if satisfied and average_applies:
        satisfied = bool(qualifying) and average_bps <= AVG_INCOME_CEILING_BPS
    return {
        "set_aside_ratio_bps": ratio,
        "set_aside_satisfied": satisfied,
        "average_ami_bps": average_bps,
        "threshold_bps": threshold,
    }


def required_set_aside_threshold_bps(election):
    return MIN_20_50_THRESHOLD_BPS if election == "MIN_20_50" else MIN_40_60_THRESHOLD_BPS


# ---- 4. restricted rent ceiling ------------------------------------------

def imputed_household_size(bedroom_count):
    return max(1, (bedroom_count or 0) + 1)


def election_ceiling_percent(election):
    if election == "MIN_20_50":
        return 50
    if election == "MIN_40_60":
        return 60
    return 80


def restricted_rent_ceiling(unit, project):
    if unit.get("designation") != "RESTRICTED":
        return None
    household = imputed_household_size(unit.get("bedroom_count"))
    table_key = household if household in AMI_100_ANNUAL_INCOME_CENTS else 6
    ami_percent = unit.get("ami_percent") or 0
    effective = min(ami_percent, election_ceiling_percent(project.get("set_aside_election")))
    annual_income = floor_div(AMI_100_ANNUAL_INCOME_CENTS[table_key] * effective, 100)
    monthly_gross = floor_div(
        floor_div(annual_income * RENT_INCOME_SHARE_PERCENT, 100), 12)
    utility_adjusted = monthly_gross - (unit.get("utility_allowance_cents") or 0)
    capped = min(utility_adjusted, unit.get("market_rent_cents") or 0)
    return max(MIN_RENT_FLOOR_CENTS, capped)


# ---- 5. fifty-percent aggregate basis test -------------------------------

def fifty_percent_ratio(numerator_cents, denominator_cents):
    if not denominator_cents:
        return 0
    return floor_div(numerator_cents * 10000, denominator_cents)


def fifty_percent_passes(ratio_bps):
    return ratio_bps >= FIFTY_PERCENT_THRESHOLD_BPS


# ---- 6. negative arbitrage cost ------------------------------------------

def negative_arbitrage_series(issue, extra_draw=None):
    """Walk the funded draws chronologically.

    `extra_draw` projects the series forward to include a draw about to be
    funded.  Returns (total_cents, {draw_id: accrual_cents}).
    """
    spread = max(0, (issue.get("bond_yield_bps") or 0) - (issue.get("investment_yield_bps") or 0))
    rows = funded_draws_in_order(issue["id"])
    if extra_draw is not None:
        rows = rows + [extra_draw]
        rows.sort(key=lambda d: (d.get("period_start") or "", d.get("draw_number") or 0))

    par = issue.get("par_amount_cents") or 0
    cumulative = 0
    total = 0
    accruals = {}
    for draw in rows:
        undrawn_before = par - cumulative
        start = parse_iso(draw.get("period_start"))
        end = parse_iso(draw.get("period_end"))
        days = (end - start).days if (start and end) else 0
        accrual = round_half_up(undrawn_before * spread * days, 10000 * DAY_COUNT_BASIS)
        accruals[draw["id"]] = accrual
        total += accrual
        cumulative += draw.get("approved_amount_cents") or 0
    return total, accruals


# ---- 7. debt service coverage ratio --------------------------------------

def dscr_window(issue, basis):
    size, factor = DSCR_WINDOWS[basis]
    months = sorted(issue.get("operating_months") or [],
                    key=lambda m: m.get("month_index") or 0)
    if len(months) < size:
        return None, size, factor
    return months[len(months) - size:], size, factor


def debt_service_coverage(issue, project, basis):
    window, _size, factor = dscr_window(issue, basis)
    if window is None:
        return None
    noi_total = sum((m.get("noi_cents") or 0) for m in window) * factor
    ds_total = sum((m.get("debt_service_cents") or 0) for m in window) * factor
    dscr_bps = floor_div(noi_total * 10000, ds_total) if ds_total else 0
    total_units = project.get("total_units") or 0
    occupancies = [
        floor_div((m.get("occupied_units") or 0) * 10000, total_units) if total_units else 0
        for m in window
    ]
    return {
        "dscr_bps": dscr_bps,
        "min_occupancy_bps": min(occupancies) if occupancies else 0,
    }


# ---- 8. qualified basis and annual credit --------------------------------

def qualified_basis_and_annual_credit(project, cert, credit_percentage_bps):
    _units, restricted, _m, _e = unit_counts(project)
    restricted = sorted(restricted, key=unit_sort_key)
    total_sqft = project.get("total_floor_space_sqft") or 0
    eligible = cert.get("certified_eligible_basis_cents") or 0
    qualified = 0
    for unit in restricted:
        qualified += floor_div(eligible * (unit.get("floor_space_sqft") or 0), total_sqft) \
            if total_sqft else 0
    annual = round_half_up(qualified * credit_percentage_bps, 10000)
    return {
        "qualified_basis_cents": qualified,
        "annual_credit_cents": annual,
        "total_credit_cents": annual * CREDIT_PERIOD_YEARS,
    }


# ---- 9. cap pool availability --------------------------------------------

def pool_ledger(pool):
    total_cap = (pool.get("base_cap_cents") or 0) + (pool.get("carryforward_cents") or 0)
    allocations = pool_allocations(pool["id"])
    reserved = sum((a.get("requested_amount_cents") or 0)
                   for a in allocations if a.get("status") == "PENDING")
    committed = sum((a.get("awarded_amount_cents") or 0)
                    for a in allocations if a.get("status") in ("AWARDED", "COMMITTED"))
    available = total_cap - reserved - committed
    awardable = total_cap - committed
    if awardable <= 0:
        status = "EXHAUSTED"
    elif available < 0:
        status = "OVERSUBSCRIBED"
    else:
        status = "OPEN"
    return {
        "total_cap_cents": total_cap,
        "reserved_cents": reserved,
        "committed_cents": committed,
        "available_cents": available,
        "awardable_cents": awardable,
        "pool_status": status,
    }


# ---- 10. credit delivery waterfall ---------------------------------------

DELIVERED_STATUSES = ("DELIVERED", "ACCEPTED", "RECAPTURE_FLAGGED")


def allocation_ledger(allocation):
    delivered = sum((d.get("delivered_credit_cents") or 0)
                    for d in allocation_deliveries(allocation["id"])
                    if d.get("status") in DELIVERED_STATUSES)
    total = allocation.get("total_credit_cents") or 0
    return {
        "delivered_credit_cents": delivered,
        "undelivered_credit_cents": total - delivered,
    }


def price_per_credit_dollar_bps(capital_contribution_cents, delivered_credit_cents):
    if not delivered_credit_cents:
        return 0
    return floor_div(capital_contribution_cents * 10000, delivered_credit_cents)


# ---- 11. recapture exposure ----------------------------------------------

def recapture_exposure(annual_credit_cents, shortfall_bps):
    return round_half_up(annual_credit_cents * shortfall_bps, 10000)


# ---- other derived ledgers ----------------------------------------------

def issue_ledger(issue):
    funded = sum((d.get("approved_amount_cents") or 0)
                 for d in issue_draws(issue["id"]) if d.get("status") == "FUNDED")
    return {
        "cumulative_funded_cents": funded,
        "undrawn_cents": (issue.get("par_amount_cents") or 0) - funded,
    }


def investor_accepted_total(investor):
    return sum((d.get("delivered_credit_cents") or 0)
               for d in db.deliveries.values()
               if d.get("investor_id") == investor["id"] and d.get("status") == "ACCEPTED")


def developer_active_project_count(developer):
    return sum(1 for p in developer_projects(developer["id"])
               if p.get("development_status") != "WITHDRAWN")


def achieved_set_aside_bps(restricted_units_occupied, total_units):
    return floor_div(restricted_units_occupied * 10000, total_units) if total_units else 0
