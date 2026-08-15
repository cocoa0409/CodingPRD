"""Property data submissions: NOI dual variants, the stabilized expense
floor, inclusive period overlap, and review rejection (PRD §3.3, §3.5)."""
from test_helpers import (
    TEST_USERS,
    add_data_submission,
    add_income_approach,
    add_support_comparables,
    create_in_progress_engagement,
    validate_error,
    validate_success,
)

EM = TEST_USERS["engagement_manager_headers"]

STMT_2025 = dict(
    submission_type="OPERATING_STATEMENT",
    period_start="2025-01-01T00:00:00Z",
    period_end="2025-12-31T00:00:00Z",
    scheduled_gross_rent_cents=12000000,
    vacancy_loss_cents=600000,
    expense_reimbursements_cents=300000,
    operating_expenses_cents=4000000,
)


def test_noi_trailing_and_stabilized_variants(api):
    """PRD §3.3: "The trailing-actual variant uses the figures as reported:
    scheduled gross rent minus vacancy and collection loss, plus expense
    reimbursements, minus operating expenses." (12,000,000 - 600,000 +
    300,000 - 4,000,000 = 7,700,000.) "The stabilized variant normalizes to
    market assumptions in a pinned step order, rounding half-up to whole
    cents at every step: first, effective gross income is the scheduled gross
    rent reduced by a five percent market vacancy allowance; second,
    stabilized expenses are the greater of the as-reported operating expenses
    and thirty percent of the scheduled gross rent — the expense floor;
    third, a replacement reserve of two percent of the scheduled gross rent
    is computed; finally, the stabilized NOI is the effective gross income
    plus the expense reimbursements, minus the stabilized expenses, minus the
    reserves." (11,400,000 + 300,000 - 4,000,000 - 240,000 = 7,460,000.)

    Design: Difficulty/dual_variant_calc/noi_trailing_vs_stabilized_diverge
    """
    bundle = create_in_progress_engagement()
    sub = add_data_submission(bundle, accept=True, **STMT_2025)
    assert sub["noi_trailing_cents"] == 7700000, (
        f"trailing NOI expected 7700000, got {sub['noi_trailing_cents']}")
    assert sub["noi_stabilized_cents"] == 7460000, (
        f"stabilized NOI expected 7460000, got {sub['noi_stabilized_cents']}")
    assert sub["noi_trailing_cents"] != sub["noi_stabilized_cents"]


def test_income_direct_cap_consumes_stabilized_noi(api):
    """PRD §3.5: "When the DCF set is absent, direct capitalization applies:
    the selected statement's `noi_stabilized_cents` is multiplied by ten
    thousand and divided by the approach's `cap_rate_bps`, rounded half-up to
    whole cents." Stabilized NOI 7,460,000 at 700 bps yields
    round_half_up(7,460,000 * 10,000 / 700) = 106,571,429 — deliberately the
    stabilized variant, not the 7,700,000 trailing figure.

    Design: Difficulty/dual_variant_calc/noi_trailing_vs_stabilized_diverge
    """
    bundle = create_in_progress_engagement()
    bundle["statement"] = add_data_submission(bundle, accept=True, **STMT_2025)
    bundle["comparables"] = add_support_comparables(bundle)
    approach = add_income_approach(bundle, complete=True, cap_rate_bps=700)
    assert approach["status"] == "COMPLETE"
    assert approach["indicated_value_cents"] == 106571429, (
        f"direct cap on stabilized NOI expected 106571429, "
        f"got {approach['indicated_value_cents']}")


def test_noi_stabilized_expense_floor_branch(api):
    """PRD §3.3: "stabilized expenses are the greater of the as-reported
    operating expenses and thirty percent of the scheduled gross rent — the
    expense floor". Reported expenses 2,000,000 fall below the floor of
    3,000,000 (30% of 10,000,000), so the floor binds: trailing NOI =
    10,000,000 - 0 + 0 - 2,000,000 = 8,000,000 while stabilized NOI =
    9,500,000 + 0 - 3,000,000 - 200,000 = 6,300,000.

    Design: Corner/calculations/noi_stabilized_expense_floor_branch
    """
    bundle = create_in_progress_engagement()
    sub = add_data_submission(
        bundle, accept=True,
        submission_type="OPERATING_STATEMENT",
        period_start="2025-01-01T00:00:00Z",
        period_end="2025-12-31T00:00:00Z",
        scheduled_gross_rent_cents=10000000,
        vacancy_loss_cents=0,
        expense_reimbursements_cents=0,
        operating_expenses_cents=2000000)
    assert sub["noi_trailing_cents"] == 8000000
    assert sub["noi_stabilized_cents"] == 6300000, (
        f"expense floor branch must use max(2000000, 3000000); "
        f"expected 6300000, got {sub['noi_stabilized_cents']}")


def test_operating_statement_touching_inclusive_end_overlaps(api):
    """PRD §3.3: "Two statements on the same engagement may not cover
    overlapping time: if a new `OPERATING_STATEMENT`'s inclusive window from
    `period_start` through `period_end` intersects the inclusive window of
    any other statement on the engagement that is not `REJECTED`, the
    creation is rejected with `ERR_STATEMENT_PERIOD_OVERLAP`." A new
    statement starting on the first statement's inclusive end date
    (2025-12-31) intersects that shared day.

    Design: Difficulty/resource_temporal_overlap/operating_statement_inclusive_interval_overlap
    """
    bundle = create_in_progress_engagement()
    add_data_submission(bundle, **STMT_2025)
    res = api.create_data_submission(
        bundle["engagement"]["id"],
        dict(submission_type="OPERATING_STATEMENT",
             period_start="2025-12-31T00:00:00Z",
             period_end="2026-06-30T00:00:00Z",
             scheduled_gross_rent_cents=6000000,
             vacancy_loss_cents=300000,
             expense_reimbursements_cents=150000,
             operating_expenses_cents=2000000),
        bundle["client_headers"])
    validate_error(res, "ERR_STATEMENT_PERIOD_OVERLAP", expected_status=409)


def test_operating_statement_first_clean_day_accepted(api):
    """PRD §3.3: "if a new `OPERATING_STATEMENT`'s inclusive window from
    `period_start` through `period_end` intersects the inclusive window of
    any other statement on the engagement that is not `REJECTED`, the
    creation is rejected with `ERR_STATEMENT_PERIOD_OVERLAP`" — a statement
    starting 2026-01-01, the first day after the existing window's inclusive
    2025-12-31 end, shares no day and is created in `SUBMITTED`.

    Design: Difficulty/resource_temporal_overlap/operating_statement_inclusive_interval_overlap
    """
    bundle = create_in_progress_engagement()
    add_data_submission(bundle, **STMT_2025)
    res = api.create_data_submission(
        bundle["engagement"]["id"],
        dict(submission_type="OPERATING_STATEMENT",
             period_start="2026-01-01T00:00:00Z",
             period_end="2026-06-30T00:00:00Z",
             scheduled_gross_rent_cents=6000000,
             vacancy_loss_cents=300000,
             expense_reimbursements_cents=150000,
             operating_expenses_cents=2000000),
        bundle["client_headers"])
    sub = validate_success(res, 201)
    assert sub["status"] == "SUBMITTED"


def test_data_submission_reject_then_accept_returns_409(api):
    """PRD §3.3: "rejecting moves it to `REJECTED` and records the supplied
    `review_note` on the submission" and "`REJECTED` and `LOCKED` are the
    submission's terminal states", so a later accept fails state validity
    with `ERR_INVALID_STATE_TRANSITION` (§2.9).

    Design: Corner/state_machines/data_submission_reject_then_accept_returns_409
    """
    bundle = create_in_progress_engagement()
    sub = add_data_submission(
        bundle, reject_note="Stale rent roll",
        submission_type="RENT_ROLL",
        period_start="2026-07-01T00:00:00Z",
        period_end="2026-07-31T00:00:00Z",
        scheduled_gross_rent_cents=1000000,
        vacancy_loss_cents=50000,
        expense_reimbursements_cents=0,
        operating_expenses_cents=0)
    assert sub["status"] == "REJECTED"
    assert sub["review_note"] == "Stale rent roll"

    res = api.accept_data_submission(sub["id"], bundle["author_headers"])
    validate_error(res, "ERR_INVALID_STATE_TRANSITION", expected_status=409)
