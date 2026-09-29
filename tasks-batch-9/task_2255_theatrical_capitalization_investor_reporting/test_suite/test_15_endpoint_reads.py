"""
The endpoint surface: computed reads, filtered listings, links and actions.

These walk the endpoints whose whole job is to report or to link — the pure
read that recomputes and persists nothing, the listings and their filters, the
booking that joins a show to a house, and the two writes whose response body is
the documented outcome.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    COMPTROLLER_HEADERS,
    GM_HEADERS,
    UNKNOWN_UUID,
    ApiClient,
    ApiErrorId,
    factories,
    fixtures,
)


class TestRecoupmentReportRead:
    """The published report recomputes both bases and agrees with the ledger."""

    def test_the_report_and_the_production_row_tell_the_same_story(
        self, api: ApiClient
    ):
        """One certified week of 28,250,000 shows on both bases and on the row.

        "Both bases are published side by side for investor reporting. The
        recoupment report names its `production_id` and the
        `capitalization_target_cents` against which everything is measured, then
        reports `cash_basis_recouped_cents` and `cash_basis_recoupment_pct`
        alongside `accrual_basis_recouped_cents` and
        `accrual_basis_recoupment_pct`, together with the `deferred_royalty_cents`
        subtracted and the `subsidiary_rights_receivable_cents` added to get from
        one to the other, plus the current `recoupment_status` and
        `distributable_cash_cents`."

        Design: Corner/endpoints/computed_read_recoupment_report_agrees_with_the_production_row
        """
        world = fixtures.certified_week_world(api)

        report = get_success_data(
            api.get_recoupment_report(world.production_id, COMPTROLLER_HEADERS), 200
        )
        assert report["production_id"] == world.production_id
        assert report["capitalization_target_cents"] == 120_000_000
        assert report["cash_basis_recouped_cents"] == 28_250_000
        assert report["cash_basis_recoupment_pct"] == 0.2354
        # No deferred guarantees and no RECORDED licensing rows, so the accrual
        # basis has nothing to subtract and nothing to add.
        assert report["accrual_basis_recouped_cents"] == 28_250_000
        assert report["accrual_basis_recoupment_pct"] == 0.2354
        assert report["deferred_royalty_cents"] == 0
        assert report["subsidiary_rights_receivable_cents"] == 0
        assert report["recoupment_status"] == "UNRECOUPED"
        assert report["distributable_cash_cents"] == 28_250_000

        production = world.production()
        assert production["recouped_amount_cents"] == 28_250_000
        assert production["recoupment_pct"] == 0.2354
        assert production["recoupment_status"] == "UNRECOUPED"
        assert production["distributable_cash_cents"] == 28_250_000


class TestWeeklyWrapListing:
    """Three weeks of one show page and filter on status and pinned budget."""

    def test_the_listing_filters_on_status_and_on_the_pinned_budget(
        self, api: ApiClient
    ):
        """Two remain DRAFT, one is SUBMITTED, and all three share one budget.

        "Wraps can be listed and filtered by `production_id`, by
        `operating_budget_id`, and by `status`."

        Design: Corner/endpoints/weekly_wrap_listing_filters_by_status_and_by_pinned_budget
        """
        world = fixtures.running_world(api)
        world.set_clock("2026-09-14")

        wrap_ids = [
            fixtures.new_wrap(world, week_ending_date=week_ending)
            for week_ending in ("2026-08-30", "2026-09-06", "2026-09-13")
        ]
        submitted = fixtures.submit_wrap(world, wrap_ids[1])
        assert submitted["status"] == "SUBMITTED"

        all_rows, all_meta = validate_paginated(
            api.list_weekly_wraps(GM_HEADERS, {"production_id": world.production_id})
        )
        assert len(all_rows) == 3
        assert all_meta["total_count"] == 3
        assert all_meta["has_more"] is False
        assert all_meta["limit"] == 10
        assert all_meta["offset"] == 0

        draft_rows, draft_meta = validate_paginated(
            api.list_weekly_wraps(
                GM_HEADERS,
                {"production_id": world.production_id, "status": "DRAFT"},
            )
        )
        assert draft_meta["total_count"] == 2
        assert {row["id"] for row in draft_rows} == {wrap_ids[0], wrap_ids[2]}

        budget_rows, budget_meta = validate_paginated(
            api.list_weekly_wraps(
                GM_HEADERS,
                {
                    "operating_budget_id": world.operating_budget_id,
                    "limit": 2,
                    "offset": 0,
                },
            )
        )
        assert len(budget_rows) == 2
        assert budget_meta["total_count"] == 3
        assert budget_meta["has_more"] is True

        submitted_rows, submitted_meta = validate_paginated(
            api.list_weekly_wraps(
                GM_HEADERS,
                {"production_id": world.production_id, "status": "SUBMITTED"},
            )
        )
        assert submitted_meta["total_count"] == 1
        assert submitted_rows[0]["id"] == wrap_ids[1]
        assert submitted_rows[0]["submitted_by_user_id"] == fixtures.SUBMITTER_USER_ID


class TestTheatreEngagementLink:
    """The booking joins one existing show to one existing house."""

    def test_the_booking_resolves_both_ends_and_is_findable_by_house(
        self, api: ApiClient
    ):
        """An unknown house is refused, and the house filter finds the one booking.

        "Occupations of a house are booked as engagements. A `GeneralManager`
        books one by supplying the `production_id` of the show taking the house,
        the `theatre_id` of the house being occupied, an `engagement_type` of
        `REHEARSAL`, `TECH`, or `PERFORMANCE_RUN`, and the inclusive first and
        last occupied calendar days as `start_date` and `end_date`."

        Design: Corner/endpoints/theatre_engagement_links_an_existing_production_to_an_existing_theatre
        """
        world = fixtures.base_world(api)

        created = get_success_data(
            api.create_theatre_engagement(
                factories.engagement_payload(
                    world.production_id,
                    world.theatre_id,
                    "2026-09-01",
                    "2026-12-31",
                    engagement_type="PERFORMANCE_RUN",
                ),
                GM_HEADERS,
            ),
            201,
        )
        assert created["production_id"] == world.production_id
        assert created["theatre_id"] == world.theatre_id
        assert created["engagement_type"] == "PERFORMANCE_RUN"
        assert created["start_date"] == "2026-09-01"
        assert created["end_date"] == "2026-12-31"

        validate_error(
            api.create_theatre_engagement(
                factories.engagement_payload(
                    world.production_id,
                    UNKNOWN_UUID,
                    "2027-01-15",
                    "2027-01-20",
                    engagement_type="REHEARSAL",
                ),
                GM_HEADERS,
            ),
            ApiErrorId.THEATRE_NOT_FOUND,
        )

        house_rows, house_meta = validate_paginated(
            api.list_theatre_engagements(GM_HEADERS, {"theatre_id": world.theatre_id})
        )
        assert house_meta["total_count"] == 1
        assert house_rows[0]["id"] == created["id"]

        rehearsal_rows, rehearsal_meta = validate_paginated(
            api.list_theatre_engagements(
                GM_HEADERS,
                {
                    "production_id": world.production_id,
                    "engagement_type": "REHEARSAL",
                },
            )
        )
        assert rehearsal_rows == []
        assert rehearsal_meta["total_count"] == 0


class TestCapitalizeAction:
    """Releasing escrow is the one write that empties the escrow balance."""

    def test_release_moves_the_whole_balance_and_closes_the_syndication_axis(
        self, api: ApiClient
    ):
        """120,000,000 leaves escrow, the axis reaches its terminal state.

        "A `Comptroller` releases it once the axis reads `FULLY_SUBSCRIBED`, which
        sets `released_capital_cents` equal to `capital_raised_cents`, drives
        `escrow_balance_cents` to 0, and advances the syndication axis
        `FULLY_SUBSCRIBED → CAPITALIZED`, the terminal state on that axis."

        Design: Corner/endpoints/capitalize_action_releases_capital_and_zeroes_escrow
        """
        world = fixtures.base_world(api)
        fixtures.with_accepted_subscription(world)

        before = world.production()
        assert before["offering_status"] == "FULLY_SUBSCRIBED"
        assert before["capital_raised_cents"] == 120_000_000
        assert before["escrow_balance_cents"] == 120_000_000
        assert before["released_capital_cents"] == 0
        assert before["version"] == 3

        released = fixtures.capitalize(world)
        assert released["offering_status"] == "CAPITALIZED"
        assert released["released_capital_cents"] == 120_000_000
        assert released["escrow_balance_cents"] == 0
        assert released["capital_raised_cents"] == 120_000_000
        assert released["operating_status"] == "PRE_PRODUCTION"
        assert released["recoupment_status"] == "UNRECOUPED"
        assert released["version"] == 4

        rows, meta = validate_paginated(
            api.list_investor_accounts(
                COMPTROLLER_HEADERS, {"production_id": world.production_id}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["basis"] == "RECOUPMENT_RETURN"
        assert rows[0]["ownership_pct"] == 1.0


class TestAmendAction:
    """Amendment overwrites the fields it is handed and leaves the rest alone."""

    def test_restating_one_figure_leaves_the_other_three_reported_numbers(
        self, api: ApiClient
    ):
        """Only the running expenses move, and the royalty base re-derives from them.

        "Amendment accepts any subset of `performances`, `gross_receipts_cents`,
        `paid_attendance`, and `running_expenses_cents`, overwrites the supplied
        fields, and re-derives `capacity_gross_cents`, `paid_capacity_pct`,
        `variable_cost_cents`, `adjusted_gross_cents` and `royalty_base_cents`
        provisionally."

        Design: Corner/endpoints/amend_overwrites_only_the_supplied_fields
        """
        world = fixtures.running_world(api)
        fixtures.with_submitted_standard_week(world)
        wrap_id = world.wrap_id or ""

        disputed = get_success_data(
            api.dispute_weekly_wrap(
                wrap_id,
                factories.dispute_payload("Running expenses overstated by the house"),
                COMPTROLLER_HEADERS,
            ),
            200,
        )
        assert disputed["status"] == "DISPUTED"
        assert disputed["version"] == 3

        amended = get_success_data(
            api.amend_weekly_wrap(
                wrap_id,
                factories.amend_payload(running_expenses_cents=30_000_000),
                GM_HEADERS,
            ),
            200,
        )
        assert amended["status"] == "AMENDED"
        assert amended["version"] == 4
        assert amended["running_expenses_cents"] == 30_000_000

        # The three figures never mentioned in the amendment body are untouched.
        assert amended["performances"] == 8
        assert amended["gross_receipts_cents"] == 65_000_000
        assert amended["paid_attendance"] == 8_200

        assert amended["capacity_gross_cents"] == 191_040_000
        assert amended["paid_capacity_pct"] == 0.8542
        assert amended["variable_cost_cents"] == 3_250_000
        assert amended["adjusted_gross_cents"] == 61_750_000
        assert amended["royalty_base_cents"] == 31_750_000

        assert amended["submitted_by_user_id"] is None
        assert amended["operating_budget_id"] == world.operating_budget_id
        assert amended["operating_budget_version_pinned"] == 2
        assert amended["dispute_note"] == "Running expenses overstated by the house"
        assert amended["certified_by_user_id"] is None
