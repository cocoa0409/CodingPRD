"""The nine normative calculations (PRD 2.7 and section 3)."""

from decimal import Decimal, ROUND_HALF_UP, getcontext

import clock
from services import constants as C

getcontext().prec = 60

ONE = Decimal(1)
HUNDRED = Decimal(100)


def round_half_up(value) -> int:
    """Money and integer rounding: half away from zero at the cent."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_1dp(value) -> float:
    return float(Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value) -> float:
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def dec2(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# 1. applicant_annual_income_and_category
# ---------------------------------------------------------------------------


def applicant_income(applicant, program_year):
    size = applicant["household_size"]
    if size > 8:
        size = 8
    factor = Decimal(C.HOUSEHOLD_ADJUSTMENT[size])
    income_limit = round_half_up(Decimal(program_year["ami_median_income_cents"]) * factor)

    wage = Decimal(applicant["wage_income_cents"])
    benefit = Decimal(applicant["benefit_income_cents"])
    actual_asset = Decimal(applicant["actual_asset_income_cents"])
    assets = Decimal(applicant["household_assets_cents"])

    if applicant["income_calc_method"] == "PART_5_ANNUAL":
        if assets > C.ASSET_IMPUTATION_THRESHOLD_CENTS:
            imputed = Decimal(round_half_up(assets * Decimal(C.ASSET_IMPUTATION_RATE)))
            asset_income = max(actual_asset, imputed)
        else:
            asset_income = actual_asset
        annual = wage + benefit + asset_income
    else:
        deductions = (
            Decimal(applicant["dependents_count"]) * C.DEPENDENT_DEDUCTION_CENTS
        )
        if applicant["elderly_household"]:
            deductions += Decimal(C.ELDERLY_DEDUCTION_CENTS)
        annual = wage + actual_asset - deductions
        if annual < 0:
            annual = Decimal(0)

    annual_income = int(annual)

    if income_limit == 0:
        ami_percent = round_half_up_1dp(Decimal(0))
    else:
        ami_percent = round_half_up_1dp(
            HUNDRED * Decimal(annual_income) / Decimal(income_limit)
        )

    percent = Decimal(str(ami_percent))
    if percent <= Decimal(C.EXTREMELY_LOW_CEILING):
        category = "EXTREMELY_LOW"
    elif percent <= Decimal(C.VERY_LOW_CEILING):
        category = "VERY_LOW"
    elif percent <= Decimal(C.LOW_CEILING):
        category = "LOW"
    else:
        category = "OVER_INCOME"

    return {
        "annual_income_cents": annual_income,
        "income_limit_cents": income_limit,
        "ami_percent": ami_percent,
        "income_category": category,
    }


# ---------------------------------------------------------------------------
# 2. work_write_up_estimate
# ---------------------------------------------------------------------------


def work_item_multiplier(is_lead, is_historic) -> Decimal:
    multiplier = ONE
    if is_lead:
        multiplier += Decimal(C.LEAD_PROTOCOL_UPLIFT)
    if is_historic:
        multiplier += Decimal(C.HISTORIC_PROTOCOL_UPLIFT)
    return multiplier


def work_item_line_total(estimated_cost_cents, multiplier) -> int:
    return round_half_up(Decimal(estimated_cost_cents) * multiplier)


def write_up_totals(items):
    """Per-line rounding first, then the sum, then the contingency."""
    base = 0
    priority_total = 0
    for item in items:
        base += item["line_total_cents"]
        if item["priority_class"] in C.PRIORITY_REPAIR_CLASSES:
            priority_total += item["line_total_cents"]
    contingency = round_half_up(Decimal(base) * Decimal(C.CONTINGENCY_PCT))
    return {
        "work_item_count": len(items),
        "base_estimate_cents": base,
        "contingency_cents": contingency,
        "total_estimate_cents": base + contingency,
        "priority_repair_total_cents": priority_total,
    }


# ---------------------------------------------------------------------------
# 3. bid_tabulation_and_ranking
# ---------------------------------------------------------------------------


def responsive_band(independent_cost_estimate_cents):
    ice = Decimal(independent_cost_estimate_cents)
    ceiling = round_half_up(ice * (ONE + Decimal(C.BID_CEILING_PCT)))
    floor = round_half_up(ice * (ONE - Decimal(C.BID_FLOOR_PCT)))
    return ceiling, floor


def classify_bid(bid, solicitation, application, contractor):
    """Ordered non-responsiveness reasons; None means responsive."""
    amount = bid["amount_cents"]
    if amount > solicitation["responsive_ceiling_cents"]:
        return "OVER_CEILING"
    if amount < solicitation["responsive_floor_cents"]:
        return "UNDER_FLOOR"
    if contractor is None or contractor["approved_list_status"] != "APPROVED":
        return "CONTRACTOR_NOT_APPROVED"
    if application["lead_review_required"] and not contractor["lead_safe_certified"]:
        return "NOT_LEAD_CERTIFIED"
    return None


def rank_key(bid, contractor_score):
    return (bid["amount_cents"], -contractor_score, bid["created_at"], bid["_seq"])


# ---------------------------------------------------------------------------
# 4. loan_structuring
# ---------------------------------------------------------------------------


def lien_recording_fee(approved_project_cost_cents) -> int:
    if approved_project_cost_cents <= C.LIEN_FEE_TIER_1_MAX_CENTS:
        return C.LIEN_FEE_TIER_1_CENTS
    if approved_project_cost_cents <= C.LIEN_FEE_TIER_2_MAX_CENTS:
        return C.LIEN_FEE_TIER_2_CENTS
    return C.LIEN_FEE_TIER_3_CENTS


def principal_for(approved_project_cost_cents, fee_cents, max_loan_amount_cents) -> int:
    return min(approved_project_cost_cents + fee_cents, max_loan_amount_cents)


def monthly_payment(structure_type, principal_cents, interest_rate_bps, term_months) -> int:
    if structure_type != "AMORTIZING":
        return 0
    if not term_months:
        return 0
    principal = Decimal(principal_cents)
    if not interest_rate_bps:
        return round_half_up(principal / Decimal(term_months))
    monthly_rate = Decimal(interest_rate_bps) / Decimal(120000)
    growth = (ONE + monthly_rate) ** term_months
    return round_half_up(principal * monthly_rate * growth / (growth - ONE))


# ---------------------------------------------------------------------------
# 5. change_order_cumulative_delta
# ---------------------------------------------------------------------------


def superseded_closure(change_order, all_change_orders):
    """Transitive closure of the supersedes chain reachable from this order."""
    seen = set()
    frontier = [change_order.get("supersedes_change_order_id")]
    while frontier:
        current = frontier.pop()
        if not current or current in seen:
            continue
        seen.add(current)
        row = all_change_orders.get(current)
        if row is not None:
            frontier.append(row.get("supersedes_change_order_id"))
    return seen


def cumulative_delta(change_order, loan, loan_change_orders, all_change_orders):
    closure = superseded_closure(change_order, all_change_orders)
    prior = 0
    for row in loan_change_orders:
        if row["id"] == change_order["id"]:
            continue
        if row["status"] != "APPROVED":
            continue
        if row["id"] in closure:
            continue
        prior += row["amount_delta_cents"]
    cumulative = prior + change_order["amount_delta_cents"]
    awarded = loan["awarded_bid_amount_cents"]
    if not awarded:
        pct = round_half_up_2dp(Decimal(0))
    else:
        pct = round_half_up_2dp(HUNDRED * Decimal(cumulative) / Decimal(awarded))
    return cumulative, pct


def exceeds_change_order_limit(pct) -> bool:
    return Decimal(str(pct)) > Decimal(C.CHANGE_ORDER_LIMIT_PCT)


# ---------------------------------------------------------------------------
# 6. draw_payment_and_retainage
# ---------------------------------------------------------------------------


def draw_amounts(requested_amount_cents, is_final_draw, retainage_held_cents):
    approved = requested_amount_cents
    if is_final_draw:
        return approved, 0, approved + retainage_held_cents
    retainage = round_half_up(Decimal(approved) * Decimal(C.RETAINAGE_PCT))
    return approved, retainage, approved - retainage


# ---------------------------------------------------------------------------
# 7. recapture_amount
# ---------------------------------------------------------------------------


def forgiveness_earned(loan, recapture_event_date) -> int:
    term = loan["forgiveness_term_months"] or 0
    if term == 0:
        return 0
    elapsed = clock.whole_months_between(loan["forgiveness_start_date"], recapture_event_date)
    if elapsed >= term:
        return loan["principal_cents"]
    return round_half_up(Decimal(loan["principal_cents"]) * Decimal(elapsed) / Decimal(term))


def recapture_figures(loan, application, event_type, event_date, sale_price, closing_costs,
                      homeowner_investment):
    forgiven = forgiveness_earned(loan, event_date)
    unforgiven = loan["principal_cents"] - forgiven - loan["principal_repaid_cents"]
    if unforgiven < 0:
        unforgiven = 0
    if event_type == "SALE":
        net_proceeds = (
            sale_price
            - application["senior_lien_balance_cents"]
            - closing_costs
            - homeowner_investment
        )
        if net_proceeds < 0:
            net_proceeds = 0
        recapture = min(unforgiven, net_proceeds)
    else:
        net_proceeds = 0
        recapture = unforgiven
    return {
        "forgiven_cents": forgiven,
        "unforgiven_balance_cents": unforgiven,
        "net_proceeds_cents": net_proceeds,
        "recapture_amount_cents": recapture,
        "shortfall_forgiven_cents": unforgiven - recapture,
        "program_income_posted_cents": recapture,
    }


# ---------------------------------------------------------------------------
# 8. contractor_performance_score
# ---------------------------------------------------------------------------


def performance_score(open_complaint_count, sanction_count, on_time_completion_count) -> int:
    raw = (
        C.BASE_PERFORMANCE_SCORE
        - C.COMPLAINT_PENALTY * open_complaint_count
        - C.SANCTION_PENALTY * sanction_count
        + C.ON_TIME_BONUS * min(on_time_completion_count, C.ON_TIME_BONUS_CAP)
    )
    return max(0, min(100, raw))
