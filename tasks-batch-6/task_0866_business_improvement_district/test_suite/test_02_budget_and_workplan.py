"""Budget creation, work-plan lines, reallocation, and the balanced-allocation invariant."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_budget_payload, create_work_plan_line_payload, create_reallocation_payload,
    setup_draft_budget_with_lines, new_bid, new_fiscal_year, set_clock,
    TEST_USERS,
)

ADMIN = TEST_USERS["district_administrator_headers"]


def _lines_by_category(api, budget_id):
    resp = api.list_work_plan_lines(budget_id, ADMIN)
    data = resp.json()["data"]
    return {row["category"]: row for row in data}


def test_budget_create_exposes_required_levy_immediately(api):
    """PRD §3.2: "the budget's required_levy_cents is computed as total_expenditure_cents
    minus other_revenue_cents — the amount the assessment must raise."

    Design: Corner/consistency_model/immediate_required_levy_visible_on_budget_create
    """
    set_clock("2027-06-01T00:00:00Z")
    bid = new_bid(name="IM BID")
    fy = new_fiscal_year(bid["id"])
    budget = validate_success(api.create_budget(fy["id"], create_budget_payload(
        total_expenditure_cents=5000000, other_revenue_cents=1500000), ADMIN), 201)
    assert budget["required_levy_cents"] == 3500000


def test_duplicate_work_plan_category_rejected(api):
    """PRD §3.2: "A category may appear at most once per budget; a duplicate is rejected
    with ERR_DUPLICATE_CATEGORY."

    Design: Corner/validations/duplicate_workplan_category_rejected
    """
    ctx = setup_draft_budget_with_lines([("CLEAN", 2000000)], total_expenditure=5000000)
    resp = api.create_work_plan_line(
        ctx["budget"]["id"], create_work_plan_line_payload(category="CLEAN", allocated_amount_cents=1000000), ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CATEGORY.value)


def test_second_budget_for_fiscal_year_rejected(api):
    """PRD §3.2: "Each fiscal year has at most one budget, in a strict one-to-one
    relationship through fiscal_year_id; a second attempt is rejected with ERR_BUDGET_EXISTS."

    Design: Corner/validations/budget_exists_rejected
    """
    set_clock("2027-06-01T00:00:00Z")
    bid = new_bid(name="BE BID")
    fy = new_fiscal_year(bid["id"])
    get_success_data(api.create_budget(fy["id"], create_budget_payload(
        total_expenditure_cents=5000000, other_revenue_cents=0), ADMIN))
    resp = api.create_budget(fy["id"], create_budget_payload(
        total_expenditure_cents=6000000, other_revenue_cents=0), ADMIN)
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXISTS.value)


def test_reallocation_exceeding_source_line_rejected(api):
    """PRD §3.2: "The amount may not exceed the source line's current allocated_amount_cents;
    an over-draw, or a reference to a category that has no line, is rejected with
    ERR_INVALID_REALLOCATION."

    Design: Corner/validations/invalid_reallocation_exceeds_line_rejected
    """
    ctx = setup_draft_budget_with_lines(
        [("CLEAN", 6000000), ("MARKETING", 2000000)], total_expenditure=8000000)
    resp = api.create_reallocation(ctx["budget"]["id"], create_reallocation_payload(
        from_category="MARKETING", to_category="CLEAN", amount_cents=9999999,
        expected_budget_version=ctx["version"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REALLOCATION.value)


def test_allocated_total_reconciled_from_lines(api):
    """PRD §3.2: "Adding a line recomputes the budget's allocated_total_cents as the sum of
    its lines' allocated_amount_cents and increments the budget's version."

    Design: Corner/cross_cutting/derived_allocated_total_reconciled
    """
    ctx = setup_draft_budget_with_lines(
        [("CLEAN", 6000000), ("SAFE", 4000000)], total_expenditure=10000000)
    assert ctx["budget"]["allocated_total_cents"] == 10000000


def test_stale_reallocation_rejected(api):
    """PRD §2.7: "If that value does not equal the budget's current version — because
    another reallocation or work-plan edit has advanced the budget since the client read it
    — the request is rejected with ERR_STALE_VERSION (HTTP 412), preventing a lost update
    to the balanced-allocation invariant."

    Design: Corner/cross_cutting/occ_stale_reallocation_rejected
    """
    ctx = setup_draft_budget_with_lines(
        [("CLEAN", 6000000), ("SAFE", 6000000)], total_expenditure=12000000)
    stale_version = ctx["version"]
    # First reallocation succeeds and advances the budget version.
    get_success_data(api.create_reallocation(ctx["budget"]["id"], create_reallocation_payload(
        from_category="SAFE", to_category="CLEAN", amount_cents=500000,
        expected_budget_version=stale_version), ADMIN))
    # Second reallocation still carries the pre-bump version.
    resp = api.create_reallocation(ctx["budget"]["id"], create_reallocation_payload(
        from_category="SAFE", to_category="CLEAN", amount_cents=100000,
        expected_budget_version=stale_version), ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_reallocation_conserves_allocated_total(api):
    """PRD §3.2: "The moved amount is subtracted from the source line's allocation and
    added to the destination line's allocation, leaving allocated_total_cents unchanged,
    and the budget's version is incremented."

    Design: Difficulty/compensating_invariant/budget_allocation_conserved_on_reallocation
    """
    ctx = setup_draft_budget_with_lines(
        [("CLEAN", 6000000), ("SAFE", 6000000), ("MARKETING", 2000000), ("ADMIN", 1800000)],
        total_expenditure=15800000, other_revenue=2000000)
    budget = validate_success(api.create_reallocation(ctx["budget"]["id"], create_reallocation_payload(
        from_category="SAFE", to_category="CLEAN", amount_cents=500000,
        expected_budget_version=ctx["version"]), ADMIN))
    assert budget["allocated_total_cents"] == 15800000


def test_reallocation_moves_cents_between_named_lines(api):
    """PRD §3.2: "The moved amount is subtracted from the source line's allocation and
    added to the destination line's allocation, leaving allocated_total_cents unchanged,
    and the budget's version is incremented."

    Design: Difficulty/compensating_invariant/budget_allocation_conserved_on_reallocation
    """
    ctx = setup_draft_budget_with_lines(
        [("CLEAN", 6000000), ("SAFE", 6000000), ("MARKETING", 2000000), ("ADMIN", 1800000)],
        total_expenditure=15800000, other_revenue=2000000)
    get_success_data(api.create_reallocation(ctx["budget"]["id"], create_reallocation_payload(
        from_category="SAFE", to_category="CLEAN", amount_cents=500000,
        expected_budget_version=ctx["version"]), ADMIN))
    lines = _lines_by_category(api, ctx["budget"]["id"])
    assert lines["CLEAN"]["allocated_amount_cents"] == 6500000
    assert lines["SAFE"]["allocated_amount_cents"] == 5500000
