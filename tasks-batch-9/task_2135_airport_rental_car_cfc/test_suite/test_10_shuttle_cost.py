"""Allocating shuttle bus operating cost by largest remainder."""

from test_helpers import (
    ADMIN,
    TREASURY,
    ApiErrorId,
    assert_shuttle_allocation_line,
    assert_shuttle_period,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def _lines_by_agreement(api, shuttle_period_id):
    rows, _meta = validate_paginated(
        api.list_shuttle_allocations(
            ADMIN, params={"shuttle_period_id": shuttle_period_id, "limit": 100}
        )
    )
    return {row["agreement_id"]: row for row in rows}


def _three_brands_with_january_reports(api, revenues, transaction_days=1_000, month=1):
    """Three brands AVX, BUD and CRZ registered in that order, each holding one ACCEPTED
    report for the given period."""
    facility = fx.create_facility(api)
    sides = []
    for brand_code, legal_name, revenue in zip(
        ("AVX", "BUD", "CRZ"),
        ("Avex Rent A Car", "Budline Auto Rental", "Cruzo Cars"),
        revenues,
    ):
        side = fx.add_brand_with_active_agreement(
            api, facility["id"], brand_code, legal_name
        )
        fx.create_accepted_report(
            api, side["agreement"]["id"], side["operator"],
            period_year=2026, period_month=month,
            reported_gross_revenue_cents=revenue,
            reported_on_airport_transaction_days=transaction_days,
        )
        sides.append(side)
    return facility, sides


def test_transaction_day_basis_charges_by_head_count(api):
    """PRD §3.9: "Under the `TRANSACTION_DAYS` basis the value is the total of
    `audited_on_airport_transaction_days` over that report set, so shuttle cost follows
    head-count of rentals and an operator with many low-value rentals pays more than its
    revenue would imply."
    PRD §3.9: "On completion the pool's `total_basis_value` and `line_count` — the number of
    lines created — are written, `allocated_total_cents` is set to the sum of every line's
    `amount_cents`, which equals `total_cost_cents` exactly, and the pool's `version` advances
    by 1."

    Design: Difficulty/dual_variant_calc/shuttle_cost_basis_transaction_days_vs_gross_revenue_split
    """
    facility, sides = _three_brands_with_january_reports(
        api, (5_000_000, 20_000_000, 5_000_000)
    )
    period = fx.create_shuttle_period(
        api, facility["id"], period_year=2026, period_month=1,
        total_cost_cents=1_000_000, allocation_basis="TRANSACTION_DAYS",
    )

    allocated = validate_success(api.allocate_shuttle_period(period["id"], TREASURY))

    assert_shuttle_period(allocated)
    lines = _lines_by_agreement(api, period["id"])
    assert lines[sides[0]["agreement"]["id"]]["amount_cents"] == 333_334
    assert lines[sides[1]["agreement"]["id"]]["amount_cents"] == 333_333
    assert lines[sides[2]["agreement"]["id"]]["amount_cents"] == 333_333
    assert allocated["allocated_total_cents"] == 1_000_000
    assert allocated["total_basis_value"] == 3_000, (
        "the transaction-day basis totals 3,000 days across the three brands"
    )
    assert allocated["line_count"] == 3


def test_gross_revenue_basis_charges_by_revenue(api):
    """PRD §3.9: "Under the `GROSS_REVENUE` basis it is the total of
    `audited_gross_revenue_cents` over the same report set, so cost follows revenue instead;
    for identical report sets the two bases assign materially different amounts to the same
    agreement."
    PRD §3.9: "`total_basis_value` is the sum of the basis values across the candidate set."

    Design: Difficulty/dual_variant_calc/shuttle_cost_basis_transaction_days_vs_gross_revenue_split
    """
    facility, sides = _three_brands_with_january_reports(
        api, (5_000_000, 20_000_000, 5_000_000)
    )
    days_period = fx.create_shuttle_period(
        api, facility["id"], period_year=2026, period_month=1,
        total_cost_cents=1_000_000, allocation_basis="TRANSACTION_DAYS",
    )
    revenue_period = fx.create_shuttle_period(
        api, facility["id"], period_year=2026, period_month=1,
        total_cost_cents=1_000_000, allocation_basis="GROSS_REVENUE",
    )
    validate_success(api.allocate_shuttle_period(days_period["id"], TREASURY))

    allocated = validate_success(api.allocate_shuttle_period(revenue_period["id"], TREASURY))

    lines = _lines_by_agreement(api, revenue_period["id"])
    assert lines[sides[0]["agreement"]["id"]]["amount_cents"] == 166_667
    assert lines[sides[1]["agreement"]["id"]]["amount_cents"] == 666_667
    assert lines[sides[2]["agreement"]["id"]]["amount_cents"] == 166_666
    assert allocated["allocated_total_cents"] == 1_000_000
    assert allocated["total_basis_value"] == 30_000_000
    assert allocated["line_count"] == 3
    day_lines = _lines_by_agreement(api, days_period["id"])
    assert day_lines[sides[0]["agreement"]["id"]]["amount_cents"] == 333_334, (
        "the same brand is charged materially differently under the two bases"
    )


def test_largest_remainder_reproduces_the_pool_exactly(api):
    """PRD §3.9: "For each candidate the exact share is `total_cost_cents` multiplied by that
    agreement's basis value and divided by `total_basis_value`, kept as an exact rational;
    `floor_cents` is that exact share truncated downward to a whole cent, and the fractional
    part left over is remembered. The remainder pool is `total_cost_cents` minus the sum of
    every line's `floor_cents`."
    PRD §3.9: "Rounding each exact share to the nearest cent and summing is explicitly wrong
    here and will not reproduce `total_cost_cents`."

    Design: Difficulty/combinatorial_formula/shuttle_pool_floor_then_largest_remainder_beats_round_then_sum
    """
    facility, sides = _three_brands_with_january_reports(
        api, (6_000_000, 6_000_000, 6_000_000), month=3
    )
    period = fx.create_shuttle_period(
        api, facility["id"], period_year=2026, period_month=3,
        total_cost_cents=100_000, allocation_basis="TRANSACTION_DAYS",
    )

    allocated = validate_success(api.allocate_shuttle_period(period["id"], TREASURY))

    lines = _lines_by_agreement(api, period["id"])
    for side in sides:
        assert lines[side["agreement"]["id"]]["floor_cents"] == 33_333
    total = sum(line["amount_cents"] for line in lines.values())
    assert total == 100_000, (
        f"the three lines must reproduce the 100,000 cent pool exactly, got {total}"
    )
    assert allocated["allocated_total_cents"] == 100_000
    assert allocated["total_basis_value"] == 3_000


def test_remainder_ranking_breaks_ties_by_agreement_creation_order(api):
    """PRD §3.9: "The lines are then ranked by fractional part descending, ties broken by the
    agreement's `created_at` ascending, and each line's one-based position in that ranking is
    stored as `remainder_rank`. A line's `amount_cents` is its `floor_cents` plus exactly one
    cent when its `remainder_rank` is less than or equal to the size of the remainder pool,
    and its `floor_cents` unchanged otherwise."
    PRD §3.9: "Each line also carries `basis_value`, the transaction days or gross revenue
    cents the agreement contributed, and `share_bps`, that basis value multiplied by 10,000,
    divided by `total_basis_value` and rounded half up."

    Design: Difficulty/combinatorial_formula/shuttle_pool_floor_then_largest_remainder_beats_round_then_sum
    """
    facility, sides = _three_brands_with_january_reports(
        api, (6_000_000, 6_000_000, 6_000_000), month=3
    )
    period = fx.create_shuttle_period(
        api, facility["id"], period_year=2026, period_month=3,
        total_cost_cents=100_000, allocation_basis="TRANSACTION_DAYS",
    )

    validate_success(api.allocate_shuttle_period(period["id"], TREASURY))

    lines = _lines_by_agreement(api, period["id"])
    first, second, third = (lines[side["agreement"]["id"]] for side in sides)
    assert first["remainder_rank"] == 1, (
        "the three-way fractional tie is broken by the agreements' creation order"
    )
    assert second["remainder_rank"] == 2
    assert third["remainder_rank"] == 3
    assert first["amount_cents"] == 33_334, "only rank 1 is inside the one-cent remainder pool"
    assert second["amount_cents"] == 33_333
    assert third["amount_cents"] == 33_333
    assert first["share_bps"] == 3_333


def test_empty_candidate_set_refuses_to_allocate(api):
    """PRD §3.9: "When the candidate set is empty or `total_basis_value` comes out as zero,
    the pool cannot be divided and the request is rejected with `ERR_NO_ALLOCATION_BASIS`
    (HTTP 422); the pool stays `OPEN`."
    PRD §3.9: "An agreement's basis value is drawn strictly from its reports in `ACCEPTED`
    status whose `period_year` and `period_month` match the pool's exactly — reports in
    `DRAFT`, `SUBMITTED`, `UNDER_AUDIT`, `REJECTED` or `SUPERSEDED` contribute nothing."

    Design: Difficulty/boundary_precision_check/empty_eligible_set_blocks_shuttle_allocation
    """
    scenario = fx.setup_active_agreement(api)
    fx.create_accepted_report(
        api, scenario["agreement"]["id"], scenario["operator"],
        period_year=2026, period_month=1,
        reported_gross_revenue_cents=5_000_000,
        reported_on_airport_transaction_days=4_000,
    )
    period = fx.create_shuttle_period(
        api, scenario["facility"]["id"], period_year=2026, period_month=9,
        total_cost_cents=500_000, allocation_basis="TRANSACTION_DAYS",
    )

    response = api.allocate_shuttle_period(period["id"], TREASURY)

    validate_error(response, ApiErrorId.ERR_NO_ALLOCATION_BASIS.value, 422)
    stored = validate_success(api.get_shuttle_period(period["id"], ADMIN))
    assert stored["status"] == "OPEN", "the pool must stay OPEN after a refused allocation"


def test_refused_allocation_writes_no_lines(api):
    """PRD §3.9: "When the candidate set is empty or `total_basis_value` comes out as zero,
    the pool cannot be divided and the request is rejected with `ERR_NO_ALLOCATION_BASIS`
    (HTTP 422); the pool stays `OPEN`."
    PRD §3.9: "A pool opens in `OPEN` status with `total_basis_value`,
    `allocated_total_cents` and `line_count` all at 0."
    PRD §2.3: "Shuttle cost allocation lines filter on `shuttle_period_id` and
    `agreement_id`."

    Design: Difficulty/boundary_precision_check/empty_eligible_set_blocks_shuttle_allocation
    """
    scenario = fx.setup_active_agreement(api)
    fx.create_accepted_report(
        api, scenario["agreement"]["id"], scenario["operator"],
        period_year=2026, period_month=1,
        reported_gross_revenue_cents=5_000_000,
        reported_on_airport_transaction_days=4_000,
    )
    period = fx.create_shuttle_period(
        api, scenario["facility"]["id"], period_year=2026, period_month=9,
        total_cost_cents=500_000, allocation_basis="TRANSACTION_DAYS",
    )

    api.allocate_shuttle_period(period["id"], TREASURY)

    stored = validate_success(api.get_shuttle_period(period["id"], ADMIN))
    assert stored["line_count"] == 0
    assert stored["allocated_total_cents"] == 0
    assert stored["total_basis_value"] == 0
    _rows, meta = validate_paginated(
        api.list_shuttle_allocations(ADMIN, params={"shuttle_period_id": period["id"]})
    )
    assert meta["total_count"] == 0, "no empty lines may be written"


def test_allocation_lines_are_immutable_ledger_rows(api):
    """PRD §2.4: "`ShuttleCostAllocation` is the single exception. Its rows are immutable
    ledger lines created only as a by-product of allocating a shuttle cost pool, and they
    carry only `id` and `created_at`: both `updated_at` and `version` are absent from a
    shuttle cost allocation line."
    PRD §3.9: "They are immutable ledger rows: nothing ever mutates a line, and they are
    discoverable only by listing or reading them directly, because no other resource embeds
    them."

    Design: Corner/entities/shuttle_cost_allocation_rows_are_immutable_and_carry_no_version
    """
    scenario = fx.setup_active_agreement(api)
    fx.create_accepted_report(
        api, scenario["agreement"]["id"], scenario["operator"],
        period_year=2026, period_month=1,
        reported_gross_revenue_cents=6_000_000,
        reported_on_airport_transaction_days=1_000,
    )
    period = fx.create_shuttle_period(
        api, scenario["facility"]["id"], period_year=2026, period_month=1,
        total_cost_cents=100_000, allocation_basis="TRANSACTION_DAYS",
    )
    validate_success(api.allocate_shuttle_period(period["id"], TREASURY))

    rows, meta = validate_paginated(
        api.list_shuttle_allocations(TREASURY, params={"shuttle_period_id": period["id"]})
    )

    assert meta["total_count"] == 1
    line = rows[0]
    assert_shuttle_allocation_line(line)
    assert line["amount_cents"] == 100_000
    assert line["basis_value"] == 1_000
    assert line["share_bps"] == 10_000
    assert line["agreement_id"] == scenario["agreement"]["id"]
    assert line["shuttle_period_id"] == period["id"]
    fetched = validate_success(api.get_shuttle_allocation(line["id"], ADMIN))
    assert "updated_at" not in fetched
    assert "version" not in fetched


def test_allocation_counts_only_reports_of_the_exact_period(api):
    """PRD §3.9: "An agreement's basis value is drawn strictly from its reports in `ACCEPTED`
    status whose `period_year` and `period_month` match the pool's exactly — reports in
    `DRAFT`, `SUBMITTED`, `UNDER_AUDIT`, `REJECTED` or `SUPERSEDED` contribute nothing."
    PRD §3.9: "The candidate set is every agreement at the pool's facility whose
    `contract_status` is either `ACTIVE` or `SUSPENDED` and whose basis value for the period
    is greater than zero; agreements sitting in `DRAFT`, `TERMINATED` or `EXPIRED` are
    excluded even when they hold accepted reports for the period."

    Design: Corner/calculations/shuttle_allocation_counts_only_reports_of_the_exact_period
    """
    facility = fx.create_facility(api)
    january = fx.add_brand_with_active_agreement(
        api, facility["id"], "AVX", "Avex Rent A Car"
    )
    february = fx.add_brand_with_active_agreement(
        api, facility["id"], "BUD", "Budline Auto Rental"
    )
    fx.create_accepted_report(
        api, january["agreement"]["id"], january["operator"],
        period_year=2026, period_month=1,
        reported_gross_revenue_cents=6_000_000,
        reported_on_airport_transaction_days=1_000,
    )
    fx.create_accepted_report(
        api, february["agreement"]["id"], february["operator"],
        period_year=2026, period_month=2,
        reported_gross_revenue_cents=6_000_000,
        reported_on_airport_transaction_days=1_000,
    )
    period = fx.create_shuttle_period(
        api, facility["id"], period_year=2026, period_month=1,
        total_cost_cents=400_000, allocation_basis="TRANSACTION_DAYS",
    )

    allocated = validate_success(api.allocate_shuttle_period(period["id"], TREASURY))

    assert allocated["line_count"] == 1, (
        "the brand whose only accepted report is for 2026-02 contributes nothing"
    )
    assert allocated["total_basis_value"] == 1_000
    assert allocated["allocated_total_cents"] == 400_000
    lines = _lines_by_agreement(api, period["id"])
    line = lines[january["agreement"]["id"]]
    assert line["basis_value"] == 1_000
    assert line["share_bps"] == 10_000
    assert line["amount_cents"] == 400_000
    _rows, meta = validate_paginated(
        api.list_shuttle_allocations(
            ADMIN, params={"agreement_id": february["agreement"]["id"]}
        )
    )
    assert meta["total_count"] == 0
