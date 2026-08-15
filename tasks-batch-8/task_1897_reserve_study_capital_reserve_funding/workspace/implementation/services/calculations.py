"""All calculation rules from the scaffold §1.3."""

from decimal import Decimal, ROUND_HALF_UP
from db import store


def find_state_rule(state_code):
    """Find the StateReserveRule for a state code."""
    for r in store.state_reserve_rules.values():
        if r["state_code"] == state_code:
            return r
    return None


def reevaluate_compliance(assoc):
    """Re-evaluate statutory_compliance_status on an association."""
    adopted = find_adopted_study(assoc["id"])
    if adopted is None:
        assoc["statutory_compliance_status"] = "COMPLIANCE_UNKNOWN"
        return
    state_rule = find_state_rule(assoc["state_code"])
    if not state_rule:
        assoc["statutory_compliance_status"] = "COMPLIANCE_UNKNOWN"
        return
    if adopted["percent_funded"] >= state_rule["min_percent_funded_pct"]:
        assoc["statutory_compliance_status"] = "COMPLIANT"
    else:
        assoc["statutory_compliance_status"] = "NON_COMPLIANT"


def round_half_up_cents(value):
    """Round a Decimal to integer cents, half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_pct(value):
    """Round a Decimal to 2 decimal places, half-up."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def get_active_included_components(study_id):
    """Get ACTIVE + is_included_in_funding components for a study, sorted by created_at ASC."""
    comps = [
        c for c in store.components.values()
        if c["study_id"] == study_id
        and c["status"] == "ACTIVE"
        and c.get("is_included_in_funding", True)
    ]
    comps.sort(key=lambda c: c["created_at"])
    return comps


def compute_ffb(study_id):
    """Compute fully_funded_balance_cents for a study (current, y=0)."""
    comps = get_active_included_components(study_id)
    total = 0
    for c in comps:
        age = c["useful_life_years"] - c["remaining_useful_life_years"]
        term = round_half_up_cents(
            Decimal(str(c["current_replacement_cost_cents"])) * age / c["useful_life_years"]
        )
        total += term
    return total


def compute_percent_funded(association_id, ffb):
    """Compute percent_funded: cash * 100 / FFB, rounded to 2dp; pinned to 100.00 when FFB==0."""
    if ffb == 0:
        return 100.00
    assoc = store.associations[association_id]
    cash = assoc["reserve_cash_balance_cents"]
    return round_half_up_pct(Decimal(str(cash)) * 100 / Decimal(str(ffb)))


def recompute_study_totals(study):
    """Recompute FFB and percent_funded on a study, bumping its version."""
    study["fully_funded_balance_cents"] = compute_ffb(study["id"])
    study["percent_funded"] = compute_percent_funded(study["association_id"], study["fully_funded_balance_cents"])
    store.touch(study)


def compute_replacement_schedule(study, components=None):
    """
    Compute the 30-year replacement schedule for a study.
    Returns O_y array: O[y] = total inflated cost of replacements in year y, for y in 0..29.
    """
    if components is None:
        components = get_active_included_components(study["id"])
    O = [0] * 30
    inflation = Decimal(str(study["inflation_rate"]))
    for c in components:
        rul = c["remaining_useful_life_years"]
        ul = c["useful_life_years"]
        cost = c["current_replacement_cost_cents"]
        y = rul
        k = 0
        while y <= 29:
            inflated = round_half_up_cents(
                Decimal(str(cost)) * (1 + inflation) ** y
            )
            O[y] += inflated
            k += 1
            y = rul + k * ul
    return O


def compute_projected_ffb(study, y, components=None):
    """Compute projected FFB for year y (y >= 1) under FULL plan."""
    if components is None:
        components = get_active_included_components(study["id"])
    inflation = Decimal(str(study["inflation_rate"]))
    total = 0
    for c in comps_iter(components):
        ul = c["useful_life_years"]
        rul = c["remaining_useful_life_years"]
        consumed = ul - rul
        age_y = (consumed + y) % ul
        inflated_cost = round_half_up_cents(
            Decimal(str(c["current_replacement_cost_cents"])) * (1 + inflation) ** y
        )
        term = round_half_up_cents(
            Decimal(str(inflated_cost)) * age_y / ul
        )
        total += term
    return total


def comps_iter(components):
    return components


def solve_funding_plan(study, plan_type, starting_cash_cents):
    """
    Solve for the minimal integer annual contribution C such that
    the projected balance stays >= floor_y for every y in 1..30.
    Returns (annual_contribution_cents, threshold_floor_cents).
    threshold_floor_cents is only non-None for THRESHOLD plans.
    """
    components = get_active_included_components(study["id"])
    O = compute_replacement_schedule(study, components)
    interest = Decimal(str(study["interest_rate"]))

    # Compute floor for each year
    threshold_floor = None
    if plan_type == "BASELINE":
        floors = [0] * 31  # floors[y] for y in 1..30
    elif plan_type == "THRESHOLD":
        max_O = max(O) if O else 0
        threshold_floor = round_half_up_cents(Decimal("0.5") * max_O)
        floors = [threshold_floor] * 31
    elif plan_type == "FULL":
        floors = [0] * 31
        for y in range(1, 31):
            floors[y] = compute_projected_ffb(study, y, components)
    else:
        floors = [0] * 31

    def simulate(C):
        """Simulate 30 years with annual contribution C. Return True if all floors met."""
        B = starting_cash_cents
        for y in range(30):
            # B_{y+1} = round_half_up((B_y + C - O_y) * (1 + interest))
            B = round_half_up_cents(
                (Decimal(str(B)) + C - O[y]) * (1 + interest)
            )
            if B < floors[y + 1]:
                return False
        return True

    # Binary search over [0, 10^12]
    lo, hi = 0, 10**12
    while lo < hi:
        mid = (lo + hi) // 2
        if simulate(mid):
            hi = mid
        else:
            lo = mid + 1

    return lo, threshold_floor


def compute_expenditure_planned(anchor_study, component_cost_cents, expenditure_fiscal_year):
    """Compute planned amount under an anchor study for an expenditure."""
    diff = expenditure_fiscal_year - anchor_study["fiscal_year"]
    inflation = Decimal(str(anchor_study["inflation_rate"]))
    return round_half_up_cents(
        Decimal(str(component_cost_cents)) * (1 + inflation) ** diff
    )


def compute_variance(amount_cents, planned_cents):
    """variance = amount - planned."""
    return amount_cents - planned_cents


def compute_tolerance(planned_chronological_cents):
    """Auto-match tolerance = max(500, round_half_up(0.10 * planned))."""
    pct = round_half_up_cents(Decimal("0.10") * planned_chronological_cents)
    return max(500, pct)


def find_chronological_anchor(association_id, expenditure_fiscal_year):
    """
    Find the anchor study for chronological variance:
    study of same association with fiscal_year == expenditure.fiscal_year
    and status in {ADOPTED, SUPERSEDED}; ties by greatest created_at.
    Fallback: current ADOPTED study.
    """
    candidates = [
        s for s in store.reserve_studies.values()
        if s["association_id"] == association_id
        and s["fiscal_year"] == expenditure_fiscal_year
        and s["status"] in ("ADOPTED", "SUPERSEDED")
    ]
    if candidates:
        candidates.sort(key=lambda s: s["created_at"], reverse=True)
        return candidates[0]
    # Fallback to current ADOPTED
    adopted = find_adopted_study(association_id)
    return adopted


def find_adopted_study(association_id):
    """Find the current ADOPTED study for an association."""
    for s in store.reserve_studies.values():
        if s["association_id"] == association_id and s["status"] == "ADOPTED":
            return s
    return None


def compute_forward_variance(expenditure):
    """Compute forward-looking variance for an expenditure read."""
    assoc_id = expenditure["association_id"]
    adopted = find_adopted_study(assoc_id)
    if adopted is None:
        return None, None
    component = store.components.get(expenditure["component_id"])
    if component is None:
        return None, None
    planned = compute_expenditure_planned(
        adopted, component["current_replacement_cost_cents"], expenditure["fiscal_year"]
    )
    variance = compute_variance(expenditure["amount_cents"], planned)
    return planned, variance


def compute_allocation_lines(disclosure, study):
    """Compute allocation_lines for an ADOPTION_SUMMARY disclosure."""
    if disclosure["disclosure_type"] != "ADOPTION_SUMMARY":
        return []

    adopted_plan_id = study.get("adopted_plan_id")
    if not adopted_plan_id or adopted_plan_id not in store.funding_plans:
        return []

    plan = store.funding_plans[adopted_plan_id]
    C = plan["annual_contribution_cents"]

    components = get_active_included_components(study["id"])
    if not components:
        return []

    # Compute weights: inflated cost at first replacement year <= 29
    inflation = Decimal(str(study["inflation_rate"]))
    weights = []
    for c in components:
        rul = c["remaining_useful_life_years"]
        ul = c["useful_life_years"]
        cost = c["current_replacement_cost_cents"]
        y = rul
        if y <= 29:
            w = round_half_up_cents(Decimal(str(cost)) * (1 + inflation) ** y)
        else:
            w = 0
        weights.append(w)

    S = sum(weights)

    if S > 0:
        # Floor shares
        shares = []
        fractions = []
        for i, w in enumerate(weights):
            exact = Decimal(str(C)) * w / S
            floored = int(exact)  # floor
            shares.append(floored)
            fractions.append(exact - floored)

        remainder = C - sum(shares)
        # Distribute remainder: largest fractional part first, ties by created_at ASC
        if remainder > 0:
            # Sort indices by (-fraction, created_at_index)
            order = sorted(range(len(components)), key=lambda i: (-fractions[i], i))
            for idx in order[:remainder]:
                shares[idx] += 1

        lines = []
        for i, c in enumerate(components):
            lines.append({
                "component_id": c["id"],
                "component_name": c["name"],
                "allocation_cents": shares[i],
            })
        return lines
    else:
        # S == 0: entire C to component with greatest cost (tie: earliest created_at)
        max_idx = 0
        for i, c in enumerate(components):
            if c["current_replacement_cost_cents"] > components[max_idx]["current_replacement_cost_cents"]:
                max_idx = i
        lines = []
        for i, c in enumerate(components):
            lines.append({
                "component_id": c["id"],
                "component_name": c["name"],
                "allocation_cents": C if i == max_idx else 0,
            })
        return lines


def special_assessment_analysis(study):
    """
    Special-assessment risk projection for an ADOPTED study.
    Returns dict with risk, first_shortfall_year, max_shortfall_cents, projected_min_balance_cents.
    """
    assoc = store.associations[study["association_id"]]
    C = assoc.get("current_annual_contribution_cents", 0)
    B = assoc["reserve_cash_balance_cents"]
    O = compute_replacement_schedule(study)
    interest = Decimal(str(study["interest_rate"]))

    min_balance = None
    first_shortfall_y = None
    balances = []

    for y in range(30):
        B = round_half_up_cents(
            (Decimal(str(B)) + C - O[y]) * (1 + interest)
        )
        balances.append(B)
        if min_balance is None or B < min_balance:
            min_balance = B
        if B < 0 and first_shortfall_y is None:
            first_shortfall_y = y + 1  # y+1 because years 1..30

    risk = "AT_RISK" if first_shortfall_y is not None else "NONE"
    first_shortfall_year = (
        study["fiscal_year"] + first_shortfall_y if first_shortfall_y is not None else None
    )
    projected_min = min_balance if min_balance is not None else 0
    max_shortfall = max(0, -projected_min)

    return {
        "risk": risk,
        "first_shortfall_year": first_shortfall_year,
        "max_shortfall_cents": max_shortfall,
        "projected_min_balance_cents": projected_min,
    }
