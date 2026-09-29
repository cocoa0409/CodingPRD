"""Requests that violate two rules at once, where only one error may come back.

Each scenario is built so that a lower band and a higher band are both violated
by the same call. The lower band must win, which is what distinguishes a correct
ordering from an implementation that simply checks whatever is convenient first.
"""

from test_helpers import (
    ApiErrorId,
    assertions,
    fixtures,
    get_success_data,
    validate_error,
)


def test_refiling_an_adjusted_claim_reports_the_claim_state_not_the_failed_test(api):
    """The state band wins over the fiscal band on the same filing attempt.

    The 2029 claim was filed for its full 2500001 and then moved to ADJUSTED by the
    audit disallowance that also flipped the substantial test to NOT_MET. Filing it
    again violates two rules at once: the claim is no longer DRAFT, and the
    project's substantial test no longer reads MET. The claim-state error is the one
    returned, because state precedes fiscal.

    PRD: "And an attempt to re-file an already-filed claim on a project whose substantial test has since failed reports `ERR_CREDIT_CLAIM_ALREADY_FILED`, not `ERR_SUBSTANTIAL_TEST_NOT_MET`, because the state band precedes the fiscal band."
    PRD: "The claim must still be `DRAFT`: a `FILED` or `ADJUSTED` claim cannot be filed again and is refused with `ERR_CREDIT_CLAIM_ALREADY_FILED`."

    Design: Difficulty/priority_pair_validation_conflict/claim_state_error_precedes_substantial_test_fiscal_error
    """
    scenario = fixtures.claim_filed_project(
        api,
        structure_type="MASTER_LEASE",
        adjusted_basis_cents=60_000_000,
        qre_cents=62_500_013,
        tax_year=2029,
    )
    cast = scenario["cast"]
    fixtures.classify_cost(
        api,
        cast,
        scenario["cost"]["id"],
        "NON_QRE",
        exclusion_reason="REVIEWER_DISALLOWED",
        headers=fixtures.MONITOR,
    )
    assertions.assert_ledger(
        fixtures.read_project(api, cast, scenario["project"]["id"]),
        substantial_test_status="NOT_MET",
    )

    response = api.file_credit_claim(
        scenario["claim"]["id"], fixtures.investor_headers(scenario["interest"])
    )

    error = validate_error(
        response, ApiErrorId.CREDIT_CLAIM_ALREADY_FILED.value, 409
    )
    assert error["error_id"] != ApiErrorId.SUBSTANTIAL_TEST_NOT_MET.value, (
        "the fiscal error must not surface while the claim state is already wrong"
    )


def test_the_refused_refiling_moves_neither_the_claim_nor_the_ledger(api):
    """A refused refiling leaves the terminal claim and the ledger where they were.

    The claim stays ADJUSTED, which is terminal, and its version reflects only the
    single move the disallowance made. The project's claimed-to-date figure stays at
    the 2500001 that the one surviving ADJUSTED claim contributes, even though the
    disallowance had already opened a recapture balance of the same amount.

    PRD: "`ADJUSTED` is terminal: such a claim can never be filed again."
    PRD: "Consistently with that, `credit_claimed_to_date_cents` is always the sum of `net_claim_cents` over the project's claims whose `status` is `FILED` or `ADJUSTED`, and `credit_recaptured_cents` is always the cumulative recapture actually applied against filed claims."

    Design: Difficulty/priority_pair_validation_conflict/claim_state_error_precedes_substantial_test_fiscal_error
    """
    scenario = fixtures.claim_filed_project(
        api,
        structure_type="MASTER_LEASE",
        adjusted_basis_cents=60_000_000,
        qre_cents=62_500_013,
        tax_year=2029,
    )
    cast = scenario["cast"]
    project_id = scenario["project"]["id"]
    fixtures.classify_cost(
        api,
        cast,
        scenario["cost"]["id"],
        "NON_QRE",
        exclusion_reason="REVIEWER_DISALLOWED",
        headers=fixtures.MONITOR,
    )
    validate_error(
        api.file_credit_claim(
            scenario["claim"]["id"], fixtures.investor_headers(scenario["interest"])
        ),
        ApiErrorId.CREDIT_CLAIM_ALREADY_FILED.value,
        409,
    )

    claim = get_success_data(
        api.get_credit_claim(scenario["claim"]["id"], cast.developer_headers)
    )
    assertions.assert_fields(
        claim,
        "claim after the refused refiling",
        status="ADJUSTED",
        version=scenario["claim"]["version"] + 1,
        net_claim_cents=2_500_001,
    )
    after = fixtures.read_project(api, cast, project_id)
    assertions.assert_ledger(
        after,
        credit_claimed_to_date_cents=2_500_001,
        recapture_balance_cents=2_500_001,
    )


def test_qualifying_an_excluded_category_reports_the_category_not_the_period(api):
    """The safety band wins over the temporal band on the same reclassification.

    The measuring period runs from 2026-09-01 for 24 months, and an ACQUISITION cost
    of 1000000 incurred on 2028-09-15 falls outside it. Trying to move that item
    onto the qualified side violates two rules: acquisition can never be a qualified
    rehabilitation expenditure, and the cost is out of period. The category error is
    the one returned, because safety precedes temporal.

    PRD: "A cost in a statutorily non-qualified category that was also incurred outside the measuring period reports `ERR_NONQUALIFIED_CATEGORY`, not `ERR_OUTSIDE_MEASURING_PERIOD`, because the safety band precedes the temporal band."
    PRD: "Moving an item onto the qualified side has two hard preconditions: its `category` must not be one of the statutorily excluded categories `ACQUISITION`, `ENLARGEMENT`, `SITE_WORK`, `PERSONAL_PROPERTY`, `FFE`, or `LANDSCAPING` — those can never be qualified rehabilitation expenditures, and an attempt is refused with `ERR_NONQUALIFIED_CATEGORY` — and its `in_measuring_period` must be true, else `ERR_OUTSIDE_MEASURING_PERIOD`."

    Design: Difficulty/priority_pair_validation_conflict/nonqualified_category_error_precedes_outside_measuring_period_error
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api,
        cast,
        structure_type="SINGLE_TIER",
        adjusted_basis_cents=60_000_000,
        measuring_period_months=24,
        measuring_period_start_date="2026-09-01",
    )
    fixtures.set_clock(api, "2028-10-01T00:00:00Z")
    cost = fixtures.add_cost(
        api,
        cast,
        project["id"],
        vendor_name="Elm Street Holdings",
        category="ACQUISITION",
        amount_cents=1_000_000,
        incurred_date="2028-09-15",
    )
    assertions.assert_fields(
        cost,
        "out-of-period acquisition cost",
        classification="PENDING_CLASSIFICATION",
        in_measuring_period=False,
    )

    response = api.classify_cost_line_item(
        cost["id"], cast.developer_headers, classification="QRE"
    )

    error = validate_error(response, ApiErrorId.NONQUALIFIED_CATEGORY.value, 422)
    assert error["error_id"] != ApiErrorId.OUTSIDE_MEASURING_PERIOD.value, (
        "the temporal error must not surface while the category is excluded outright"
    )


def test_the_refused_reclassification_leaves_the_item_and_the_totals_alone(api):
    """A rejected classify does not count as a reclassification.

    The item stays in PENDING_CLASSIFICATION with a reclassification count of zero,
    so the refused attempt did not register as one of the cycles the developer is
    allowed to make, and the project's qualified total is still zero because the
    item never joined the counted set.

    PRD: "Reclassification is a first-class operation, and each successful one raises `reclassification_count` by one."
    PRD: "An item that fails either check may still be recorded and kept on the non-qualified side."

    Design: Difficulty/priority_pair_validation_conflict/nonqualified_category_error_precedes_outside_measuring_period_error
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api,
        cast,
        structure_type="SINGLE_TIER",
        adjusted_basis_cents=60_000_000,
        measuring_period_months=24,
        measuring_period_start_date="2026-09-01",
    )
    fixtures.set_clock(api, "2028-10-01T00:00:00Z")
    cost = fixtures.add_cost(
        api,
        cast,
        project["id"],
        category="ACQUISITION",
        amount_cents=1_000_000,
        incurred_date="2028-09-15",
    )

    validate_error(
        api.classify_cost_line_item(
            cost["id"], cast.developer_headers, classification="QRE"
        ),
        ApiErrorId.NONQUALIFIED_CATEGORY.value,
        422,
    )

    stored = get_success_data(
        api.get_cost_line_item(cost["id"], cast.developer_headers)
    )
    assertions.assert_fields(
        stored,
        "cost after the refused reclassification",
        classification="PENDING_CLASSIFICATION",
        reclassification_count=0,
        in_measuring_period=False,
    )
    assertions.assert_ledger(
        fixtures.read_project(api, cast, project["id"]),
        qre_total_final_cents=0,
        classified_cost_total_cents=0,
    )
