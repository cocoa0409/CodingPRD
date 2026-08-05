"""Assessment rate computation: estimate vs certify divergence, use-class multiplier + clamp,
per-parcel-then-sum levy rounding, and the adopt certification cascade."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    set_clock, new_bid, add_parcel, activate, new_fiscal_year, new_budget,
    add_line, propose, adopt, find_assessment, account_for,
    setup_draft_budget_with_lines,
    TEST_USERS,
)

ADMIN = TEST_USERS["district_administrator_headers"]
BOARD = TEST_USERS["board_member_headers"]


def _build_divergence_proposed(api):
    """Downtown BID with P1(wb700), P2(wb360), P3(wb1700); FY budget balanced at 15800000
    with other_revenue 2000000 (required_levy 13800000); proposed (estimate_rate 5000).
    Returns dict with a1_id (P1's assessment), p2_id, budget_id, fy_id.
    """
    set_clock("2027-06-01T00:00:00Z")
    bid = new_bid(name="Downtown BID", boundary_description="Core downtown")
    p1 = add_parcel(bid["id"], apn="AAA-1", owner_name="Alice Co", use_class="COMMERCIAL",
                    assessed_value_cents=100000000, linear_frontage_ft=50, building_sqft=10000)
    p2 = add_parcel(bid["id"], apn="BBB-2", owner_name="Bob LLC", use_class="COMMERCIAL",
                    assessed_value_cents=50000000, linear_frontage_ft=30, building_sqft=5000)
    add_parcel(bid["id"], apn="CCC-3", owner_name="Cara Inc", use_class="RETAIL",
               assessed_value_cents=200000000, linear_frontage_ft=80, building_sqft=20000)
    activate(bid["id"])
    fy = new_fiscal_year(bid["id"])
    budget = new_budget(fy["id"], total_expenditure_cents=15800000, other_revenue_cents=2000000)
    add_line(budget["id"], "CLEAN", 6000000)
    add_line(budget["id"], "SAFE", 6000000)
    add_line(budget["id"], "MARKETING", 2000000)
    add_line(budget["id"], "ADMIN", 1800000)
    propose(budget["id"])
    a1 = find_assessment(p1["id"], fy["id"])
    return {"a1_id": a1["id"], "p2_id": p2["id"], "budget_id": budget["id"], "fy_id": fy["id"]}


def test_estimated_amount_uses_propose_time_denominator(api):
    """PRD §3.3: "The estimate_rate is the required_levy_cents divided by the denominator,
    where the denominator is the sum of weighted_base over the district's parcels that are
    ACTIVE and non-exempt, evaluated as of the propose instant."

    Design: Difficulty/dual_variant_calc/assessment_estimate_vs_certify_diverge
    """
    ctx = _build_divergence_proposed(api)
    # denom 2760, rate 5000, P1 wb700 -> 3500000
    a1 = validate_success(api.get_assessment(ctx["a1_id"], ADMIN))
    assert a1["estimated_amount_cents"] == 3500000
    assert a1["status"] == "ESTIMATED"


def test_certified_amount_reevaluates_denominator_after_withdrawal(api):
    """PRD §3.3: "the certified_rate is the required_levy_cents divided by the sum of
    weighted_base over parcels that are ACTIVE and non-exempt at adopt time. This matters
    because a parcel may have withdrawn between propose and adopt, so the denominator — and
    therefore the rate and every per-parcel amount — can differ from the estimate."

    Design: Difficulty/dual_variant_calc/assessment_estimate_vs_certify_diverge
    """
    ctx = _build_divergence_proposed(api)
    get_success_data(api.withdraw_parcel(ctx["p2_id"], ADMIN))
    get_success_data(api.adopt_budget(ctx["budget_id"], BOARD))
    # denom now 2400, rate 5750, P1 wb700 -> 4025000
    a1 = validate_success(api.get_assessment(ctx["a1_id"], ADMIN))
    assert a1["certified_amount_cents"] == 4025000
    assert a1["status"] == "CERTIFIED"


def _build_multiplier_proposed(api):
    """CA BID: PR RETAIL (wb1700) and PC OFFICE (wb770); required_levy 24700000,
    estimate_rate 10000. Returns (apr_id, apc_id)."""
    set_clock("2027-06-01T00:00:00Z")
    bid = new_bid(name="CA BID")
    pr = add_parcel(bid["id"], apn="PR-1", owner_name="Retail Owner", use_class="RETAIL",
                    assessed_value_cents=200000000, linear_frontage_ft=80, building_sqft=20000)
    pc = add_parcel(bid["id"], apn="PC-1", owner_name="Office Owner", use_class="OFFICE",
                    assessed_value_cents=100000000, linear_frontage_ft=50, building_sqft=10000)
    activate(bid["id"])
    fy = new_fiscal_year(bid["id"])
    budget = new_budget(fy["id"], total_expenditure_cents=24700000, other_revenue_cents=0)
    add_line(budget["id"], "CLEAN", 24700000)
    propose(budget["id"])
    apr = find_assessment(pr["id"], fy["id"])
    apc = find_assessment(pc["id"], fy["id"])
    return apr["id"], apc["id"]


def test_retail_assessment_clamped_to_cap(api):
    """PRD §3.3: "clamping the rounded figure to lie between the district's floor and cap —
    that is, the assessment is the larger of the floor min_assessment_cents and the smaller
    of the cap max_assessment_cents and the rounded raw amount."
    PRD §3.1: "1.25 for RETAIL".

    Design: Difficulty/combinatorial_formula/assessment_multiplier_and_cap_nonlinear
    """
    apr_id, _ = _build_multiplier_proposed(api)
    # RETAIL wb1700 x rate 10000 = 17000000 raw, clamped to cap 10000000
    apr = validate_success(api.get_assessment(apr_id, ADMIN))
    assert apr["estimated_amount_cents"] == 10000000


def test_office_assessment_uncapped(api):
    """PRD §3.3: "Each such parcel's provisional charge is computed by taking the rate
    multiplied by that parcel's snapshotted weighted_base to get a raw amount, rounding that
    raw amount half up to whole cents, and then clamping the rounded figure to lie between
    the district's floor and cap."
    PRD §3.1: "1.10 for OFFICE".

    Design: Difficulty/combinatorial_formula/assessment_multiplier_and_cap_nonlinear
    """
    _, apc_id = _build_multiplier_proposed(api)
    # OFFICE wb770 x rate 10000 = 7700000 raw, within [50000, 10000000]
    apc = validate_success(api.get_assessment(apc_id, ADMIN))
    assert apc["estimated_amount_cents"] == 7700000


def _build_levy_rounding_adopted(api):
    """LR BID (weights value 0, frontage 0, sqft 1.0), 3 parcels each wb1, required_levy
    10000, certified_rate 3333.333. Returns (fy_id, one parcel's assessment id)."""
    set_clock("2027-06-01T00:00:00Z")
    bid = new_bid(name="LR BID", assessment_weight_value=0, assessment_weight_frontage=0,
                  assessment_weight_sqft=1.0, min_assessment_cents=1, max_assessment_cents=100000000)
    parcels = []
    for i in range(1, 4):
        parcels.append(add_parcel(bid["id"], apn=f"L-{i}", owner_name=f"O{i}",
                                  use_class="COMMERCIAL", assessed_value_cents=0,
                                  linear_frontage_ft=0, building_sqft=1))
    activate(bid["id"])
    fy = new_fiscal_year(bid["id"])
    budget = new_budget(fy["id"], total_expenditure_cents=10000, other_revenue_cents=0)
    add_line(budget["id"], "CLEAN", 10000)
    propose(budget["id"])
    adopt(budget["id"])
    a1 = find_assessment(parcels[0]["id"], fy["id"])
    return fy["id"], a1["id"]


def test_certified_levy_rounds_each_parcel_then_sums(api):
    """PRD §2.5: "each parcel's certified assessment is rounded to whole cents first, and
    only then are the per-parcel amounts summed. The total is never computed by summing raw
    rate-times-base products and rounding once at the end."

    Design: Difficulty/combinatorial_formula/levy_round_per_parcel_then_sum
    """
    fy_id, _ = _build_levy_rounding_adopted(api)
    # rate 3333.333 -> each parcel 3333, summed 9999 (sum-then-round would give 10000)
    fy = validate_success(api.get_fiscal_year(fy_id, ADMIN))
    assert fy["total_certified_levy_cents"] == 9999


def test_per_parcel_assessment_rounded_half_up(api):
    """PRD §2.5: "Wherever a computation must land on whole cents — an assessment amount, a
    delinquency penalty, an interest accrual — the result is rounded half up to the nearest
    cent."

    Design: Difficulty/combinatorial_formula/levy_round_per_parcel_then_sum
    """
    _, assessment_id = _build_levy_rounding_adopted(api)
    # 3333.333 rounded half up -> 3333
    a = validate_success(api.get_assessment(assessment_id, ADMIN))
    assert a["certified_amount_cents"] == 3333


def test_adopt_certifies_assessment_amount(api):
    """PRD §3.3: "each ESTIMATED assessment whose parcel is still ACTIVE is certified
    (ESTIMATED → CERTIFIED): its certified_amount_cents is computed with the same
    rate-times-base, round-half-up, then clamp-between-floor-and-cap procedure using the
    certified rate, and its certified_at is set to the clock."

    Design: Difficulty/transitive_cascade/budget_adopt_certify_account_cascade
    """
    set_clock("2027-06-01T00:00:00Z")
    bid = new_bid(name="Adopt BID")
    parcel = add_parcel(bid["id"], apn="PX-1")
    activate(bid["id"])
    fy = new_fiscal_year(bid["id"])
    budget = new_budget(fy["id"], total_expenditure_cents=4025000, other_revenue_cents=0)
    add_line(budget["id"], "CLEAN", 4025000)
    propose(budget["id"])
    assessment = find_assessment(parcel["id"], fy["id"])
    get_success_data(api.adopt_budget(budget["id"], BOARD))
    a = validate_success(api.get_assessment(assessment["id"], ADMIN))
    assert a["status"] == "CERTIFIED"
    assert a["certified_amount_cents"] == 4025000


def test_adopt_opens_billed_collection_account(api):
    """PRD §3.3: "each certification creates a child CollectionAccount in BILLED status
    whose billed_amount_cents equals the assessment's certified_amount_cents and whose
    due_date is copied from the fiscal year's assessment_due_date."

    Design: Difficulty/transitive_cascade/budget_adopt_certify_account_cascade
    """
    set_clock("2027-06-01T00:00:00Z")
    bid = new_bid(name="Adopt BID")
    parcel = add_parcel(bid["id"], apn="PX-1")
    activate(bid["id"])
    fy = new_fiscal_year(bid["id"], assessment_due_date="2027-08-01T00:00:00Z")
    budget = new_budget(fy["id"], total_expenditure_cents=4025000, other_revenue_cents=0)
    add_line(budget["id"], "CLEAN", 4025000)
    propose(budget["id"])
    assessment = find_assessment(parcel["id"], fy["id"])
    get_success_data(api.adopt_budget(budget["id"], BOARD))
    account = account_for(assessment["id"])
    assert account["status"] == "BILLED"
    assert account["billed_amount_cents"] == 4025000
    assert account["due_date"].startswith("2027-08-01"), f"due_date {account['due_date']}"


def test_propose_unbalanced_budget_rejected(api):
    """PRD §3.3: "the work-plan allocations sum exactly to total_expenditure_cents — an
    imbalance is rejected with ERR_BUDGET_UNBALANCED".

    Design: Corner/validations/budget_unbalanced_rejected
    """
    ctx = setup_draft_budget_with_lines([("CLEAN", 3000000)], total_expenditure=5000000, with_parcel=True)
    resp = api.propose_budget(ctx["budget"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_BUDGET_UNBALANCED.value)


def test_propose_negative_levy_rejected(api):
    """PRD §3.3: "the required_levy_cents is at least zero — a negative levy (revenue
    exceeding expenditure) is rejected with ERR_NEGATIVE_LEVY".

    Design: Corner/validations/negative_levy_rejected
    """
    ctx = setup_draft_budget_with_lines([("CLEAN", 1000000)], total_expenditure=1000000,
                                        other_revenue=2000000, with_parcel=True)
    resp = api.propose_budget(ctx["budget"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_NEGATIVE_LEVY.value)
