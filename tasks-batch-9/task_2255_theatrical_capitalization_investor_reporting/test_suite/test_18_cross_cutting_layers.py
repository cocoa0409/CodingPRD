"""
The layers that cut across every entity: concurrency, atomicity, immediacy.

A stale version token is refused without writing; a refused cascade leaves not
one of its hops behind; a cumulative ceiling walks down to exactly zero; and a
successful cascade is already visible in the response that caused it.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    COMPTROLLER_HEADERS,
    GM_HEADERS,
    ApiClient,
    ApiErrorId,
    factories,
    fixtures,
)


class TestStaleVersionToken:
    """The second line quoting the first line's token is refused, not merged."""

    def test_a_stale_token_is_refused_and_the_refreshed_one_succeeds(
        self, api: ApiClient
    ):
        """Two lines land, 55,000,000 in total, and the refused attempt leaves no row.

        "If `expected_production_version` does not equal the production's current
        `version`, the create is rejected with `ERR_STALE_PRODUCTION_VERSION`
        (HTTP 412), forcing the client to re-read the rolled-up
        `budget_total_cents` before allocating again."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_production_version_blocks_a_second_budget_line
        """
        world = fixtures.base_world(api)
        stale_token = world.production_version()
        assert stale_token == 1

        first = get_success_data(
            api.create_budget_line(
                factories.budget_line_payload(
                    world.production_id,
                    40_000_000,
                    stale_token,
                    component="PRODUCTION",
                    description="Scenery build",
                ),
                GM_HEADERS,
            ),
            201,
        )
        assert first["commitment_status"] == "PLANNED"
        assert world.production_version() == 2

        second_body = factories.budget_line_payload(
            world.production_id,
            15_000_000,
            stale_token,
            component="REHEARSAL",
            description="Rehearsal salaries",
        )
        validate_error(
            api.create_budget_line(second_body, GM_HEADERS),
            ApiErrorId.STALE_PRODUCTION_VERSION,
            412,
        )
        assert world.production()["version"] == 2

        second_body["expected_production_version"] = world.production_version()
        get_success_data(api.create_budget_line(second_body, GM_HEADERS), 201)

        rows, meta = validate_paginated(
            api.list_budget_lines(GM_HEADERS, {"production_id": world.production_id})
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2

        production = world.production()
        assert production["budget_total_cents"] == 55_000_000
        assert production["version"] == 3


class TestRefusedCascadeAtomicity:
    """A settlement stopped by an uncertified wrap runs none of its four hops."""

    def test_the_refused_settlement_leaves_the_reserve_line_and_notice_untouched(
        self, api: ApiClient
    ):
        """The line is still COMMITTED, the notice still ISSUED, the axis still open.

        "It carries four preconditions: the notice must be `ISSUED`, else
        `ERR_INVALID_CLOSING_NOTICE_STATE` (HTTP 409); the production's
        `operating_status` must read `CLOSING_NOTICE`; the settling operator's
        `X-User-ID` must differ from the notice's `issued_by_user_id`, else
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403); and no wrap of the production may
        still be in `DRAFT`, `SUBMITTED`, `DISPUTED`, or `AMENDED`, else
        `ERR_UNCERTIFIED_WRAPS_EXIST` (HTTP 409) — the books must be closed
        before the show is."

        "Every `RESERVE` line that was `COMMITTED` becomes the terminal `SPENT`,
        and the reserve release is booked."

        Design: Corner/cross_cutting_complexity_layers/refused_settlement_writes_no_partial_cascade
        """
        world = fixtures.running_world(api)
        fixtures.with_reserve_line(world, 20_000_000)
        fixtures.with_issued_closing_notice(world)
        wrap_id = fixtures.new_wrap(world, week_ending_date="2026-08-01")
        fixtures.submit_wrap(world, wrap_id)

        validate_error(
            fixtures.settle_closing_notice(world, 5_000_000),
            ApiErrorId.UNCERTIFIED_WRAPS_EXIST,
            409,
        )

        line = get_success_data(
            api.get_budget_line(world.reserve_line_id or "", COMPTROLLER_HEADERS), 200
        )
        assert line["commitment_status"] == "COMMITTED"
        assert line["version"] == 2

        notice = get_success_data(
            api.get_closing_notice(world.closing_notice_id or "", COMPTROLLER_HEADERS),
            200,
        )
        assert notice["status"] == "ISSUED"
        # PRD 3.9 commits only `closing_costs_cents` to reading null before
        # settlement: "that field reads null on any notice not yet settled".
        # The refused settlement is proved to have booked nothing by the
        # unchanged reserve line, the unchanged ledger and the unchanged axis.
        assert notice["settled_by_user_id"] is None
        assert notice["closing_costs_cents"] is None

        production = world.production()
        assert production["operating_status"] == "CLOSING_NOTICE"
        assert production["budget_committed_cents"] == 20_000_000
        assert production["recouped_amount_cents"] == 0
        assert production["version"] == 9


class TestCumulativeDistributionCeiling:
    """Declarations accumulate, and the headroom walks down to exactly zero."""

    def test_two_declarations_exhaust_the_balance_and_the_next_cent_is_refused(
        self, api: ApiClient
    ):
        """28,250,000 goes out in two declarations; the 28,250,001st cent cannot.

        "`distributed_total_cents` is the sum of `total_amount_cents` over the
        production's distributions whose `status` is `DECLARED` or `PAID`, and
        `distributable_cash_cents` is `recouped_amount_cents` less
        `distributed_total_cents`, floored at 0."

        Design: Corner/cross_cutting_complexity_layers/cumulative_distribution_ceiling_decrements_to_zero
        """
        world = fixtures.certified_week_world(api)
        assert world.production()["distributable_cash_cents"] == 28_250_000

        get_success_data(fixtures.declare_distribution(world, 18_249_999), 201)
        after_first = world.production()
        assert after_first["distributed_total_cents"] == 18_249_999
        assert after_first["distributable_cash_cents"] == 10_000_001
        assert after_first["version"] == 9

        get_success_data(fixtures.declare_distribution(world, 10_000_001), 201)
        after_second = world.production()
        assert after_second["distributed_total_cents"] == 28_250_000
        assert after_second["distributable_cash_cents"] == 0
        assert after_second["version"] == 10

        validate_error(
            fixtures.declare_distribution(world, 1),
            ApiErrorId.DISTRIBUTION_EXCEEDS_DISTRIBUTABLE,
            422,
        )

        account = fixtures.sole_account(world)
        assert account["declared_distribution_cents"] == 28_250_000
        assert account["distributions_paid_cents"] == 0


class TestCascadeImmediacy:
    """The cascade is inside the request, so the causing response already shows it."""

    def test_the_certify_response_and_the_next_reads_already_carry_the_ledger(
        self, api: ApiClient
    ):
        """No retry is needed: the settled figures and the empty split are immediate.

        "No client ever tells the system what a production's
        `recouped_amount_cents` is; the client certifies a wrap, and the system
        re-derives the ledger. Each cascade is applied within the same request,
        immediately, before the response is built — there is no eventual
        consistency and no deferred reconciliation."

        Design: Corner/consistency_model/certification_cascade_is_visible_inside_the_same_response
        """
        world = fixtures.running_world(api)
        fixtures.with_submitted_standard_week(world)
        wrap_id = world.wrap_id or ""

        certified = get_success_data(
            api.certify_weekly_wrap(wrap_id, COMPTROLLER_HEADERS), 200
        )
        assert certified["status"] == "CERTIFIED"
        assert certified["royalty_basis_applied"] == "FIXED_GROSS"
        assert certified["royalty_pool_cents"] == 0
        assert certified["weekly_operating_profit_cents"] == 28_250_000

        production = world.production()
        assert production["recouped_amount_cents"] == 28_250_000
        assert production["recoupment_pct"] == 0.2354
        assert production["distributable_cash_cents"] == 28_250_000
        assert production["recoupment_status"] == "UNRECOUPED"
        assert production["version"] == 8

        _, meta = validate_paginated(
            api.list_royalty_allocations(COMPTROLLER_HEADERS, {"wrap_id": wrap_id})
        )
        assert meta["total_count"] == 0

        report = get_success_data(
            api.get_recoupment_report(world.production_id, COMPTROLLER_HEADERS), 200
        )
        assert report["cash_basis_recouped_cents"] == 28_250_000
        assert report["deferred_royalty_cents"] == 0
