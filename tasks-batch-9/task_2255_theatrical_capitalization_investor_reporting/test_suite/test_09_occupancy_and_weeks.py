"""
Two occupancy calendars: houses with changeover buffers, and performance weeks.

Both are tested at the exact date where the interval arithmetic flips, and both
are tested for the exclusion that lets a second row occupy the same slot.
"""

from typing import Tuple

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
    World,
    assert_engagement_common_fields,
    factories,
    fixtures,
)


class TestTheatreEngagementBuffer:
    """The house's changeover buffer widens every existing span on both sides."""

    def _two_houses(self, api: ApiClient) -> Tuple[str, str, str, str, str]:
        theatre_a = fixtures.new_theatre(
            api, name="Belasco House", seat_count=1200, top_ticket_price_cents=19900
        )
        production_a = fixtures.new_production(
            api, theatre_a, title="The Ledger", offering_entity_type="LP"
        )["id"]
        theatre_b = fixtures.new_theatre(
            api, name="Cort Annex", seat_count=900, top_ticket_price_cents=14900
        )
        production_b = fixtures.new_production(
            api,
            theatre_b,
            title="The Understudy",
            offering_entity_type="LLC",
            capitalization_target_cents=90_000_000,
            reserve_target_cents=1_500_000,
        )["id"]
        first = get_success_data(
            api.create_theatre_engagement(
                factories.engagement_payload(
                    production_a, theatre_a, "2026-09-01", "2026-09-30"
                ),
                GM_HEADERS,
            ),
            201,
        )
        return theatre_a, production_a, theatre_b, production_b, first["id"]

    def test_three_dark_days_are_required_and_two_are_not_enough(
        self, api: ApiClient
    ):
        """October 3rd leaves two dark days and is refused; the 4th leaves three.

        "Take the existing engagement's inclusive span from its `start_date` to
        its `end_date` and widen it by the house's `changeover_buffer_days` at
        each end; if the new engagement's inclusive span touches that widened
        span at any point, the booking is rejected with
        `ERR_THEATRE_ENGAGEMENT_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/theatre_engagement_buffered_closed_interval_collision
        """
        theatre_a, production_a, _, _, _ = self._two_houses(api)

        refused = api.create_theatre_engagement(
            factories.engagement_payload(
                production_a, theatre_a, "2026-10-03", "2026-11-30"
            ),
            GM_HEADERS,
        )
        validate_error(refused, ApiErrorId.THEATRE_ENGAGEMENT_OVERLAP)

        accepted = get_success_data(
            api.create_theatre_engagement(
                factories.engagement_payload(
                    production_a, theatre_a, "2026-10-04", "2026-11-30"
                ),
                GM_HEADERS,
            ),
            201,
        )
        assert accepted["start_date"] == "2026-10-04"
        assert accepted["theatre_id"] == theatre_a

        _, meta = validate_paginated(
            api.list_theatre_engagements(GM_HEADERS, {"theatre_id": theatre_a})
        )
        assert meta["total_count"] == 2

    def test_the_same_window_is_free_in_a_different_house(self, api: ApiClient):
        """The refused window is booked without complaint one house over.

        "Collisions are checked against the house, not the production, and the
        check honours the changeover buffer on both sides."

        Design: Difficulty/resource_temporal_overlap/theatre_engagement_buffered_closed_interval_collision
        """
        theatre_a, production_a, theatre_b, production_b, first_id = self._two_houses(
            api
        )
        validate_error(
            api.create_theatre_engagement(
                factories.engagement_payload(
                    production_a, theatre_a, "2026-10-03", "2026-11-30"
                ),
                GM_HEADERS,
            ),
            ApiErrorId.THEATRE_ENGAGEMENT_OVERLAP,
        )

        elsewhere = get_success_data(
            api.create_theatre_engagement(
                factories.engagement_payload(
                    production_b, theatre_b, "2026-10-03", "2026-11-30"
                ),
                GM_HEADERS,
            ),
            201,
        )
        assert elsewhere["theatre_id"] == theatre_b

        _, meta_a = validate_paginated(
            api.list_theatre_engagements(GM_HEADERS, {"theatre_id": theatre_a})
        )
        _, meta_b = validate_paginated(
            api.list_theatre_engagements(GM_HEADERS, {"theatre_id": theatre_b})
        )
        assert meta_a["total_count"] == 1
        assert meta_b["total_count"] == 1

        booking = get_success_data(api.get_theatre_engagement(first_id, GM_HEADERS), 200)
        assert_engagement_common_fields(booking)


class TestPerformanceWeekAdjacency:
    """Weeks are half-open, so seven days apart is adjacency and six is a collision."""

    def _certified_first_week(self, api: ApiClient) -> World:
        world = fixtures.ledger_world(api, pool_basis=True)
        fixtures.with_submitted_standard_week(world)
        fixtures.certify_wrap(world, world.wrap_id or "")
        world.set_clock("2026-09-14")
        return world

    def test_the_next_week_ending_seven_days_later_is_admissible(
        self, api: ApiClient
    ):
        """2026-09-13 abuts 2026-09-06 without intersecting it.

        "A wrap occupies the half-open interval running from seven days before
        its `week_ending_date` up to but not including the `week_ending_date`
        itself."

        Design: Difficulty/resource_temporal_overlap/weekly_wrap_half_open_week_adjacency_versus_overlap
        """
        world = self._certified_first_week(api)

        adjacent_id = fixtures.new_wrap(
            world,
            week_ending_date="2026-09-13",
            gross_receipts_cents=50_000_000,
            paid_attendance=6_500,
        )
        adjacent = get_success_data(api.get_weekly_wrap(adjacent_id, GM_HEADERS), 200)

        assert adjacent["status"] == "DRAFT"
        assert adjacent["adjusted_gross_cents"] == 47_500_000
        assert adjacent["royalty_base_cents"] == 14_000_000

    def test_a_week_ending_six_days_later_collides(self, api: ApiClient):
        """2026-09-12 is fewer than seven days from 2026-09-06 and is refused.

        "If a new wrap's interval intersects the interval of any other wrap of
        the same production that is not `VOID`, the create is rejected with
        `ERR_WRAP_WEEK_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/weekly_wrap_half_open_week_adjacency_versus_overlap
        """
        world = self._certified_first_week(api)
        fixtures.new_wrap(
            world,
            week_ending_date="2026-09-13",
            gross_receipts_cents=50_000_000,
            paid_attendance=6_500,
        )

        refused = api.create_weekly_wrap(
            factories.standard_week_payload(
                world.production_id,
                week_ending_date="2026-09-12",
                gross_receipts_cents=50_000_000,
                paid_attendance=6_500,
            ),
            GM_HEADERS,
        )
        validate_error(refused, ApiErrorId.WRAP_WEEK_OVERLAP)

        _, meta = validate_paginated(
            api.list_weekly_wraps(GM_HEADERS, {"production_id": world.production_id})
        )
        assert meta["total_count"] == 2


class TestVoidedWeekIsReReportable:
    """A voided wrap leaves the week's slot empty again."""

    def _certified_then_blocked(self, api: ApiClient) -> World:
        world = fixtures.ledger_world(api, pool_basis=True)
        fixtures.with_submitted_standard_week(world)
        fixtures.certify_wrap(world, world.wrap_id or "")
        assert world.production()["recouped_amount_cents"] == 18_362_500

        refused = api.create_weekly_wrap(
            factories.standard_week_payload(
                world.production_id, running_expenses_cents=28_250_000
            ),
            GM_HEADERS,
        )
        validate_error(refused, ApiErrorId.WRAP_WEEK_OVERLAP)
        return world

    def test_the_week_cannot_be_re_reported_until_the_first_wrap_is_voided(
        self, api: ApiClient
    ):
        """The same week ending date is blocked, then freed by the void.

        "Equivalently, two non-`VOID` wraps of the same production collide
        whenever their `week_ending_date` values are fewer than seven calendar
        days apart; voided wraps are excluded from the check, so a week can be
        re-reported after its original wrap has been voided."

        Design: Difficulty/resource_temporal_overlap/voided_wrap_frees_its_week_for_a_replacement
        """
        world = self._certified_then_blocked(api)

        voided = get_success_data(
            api.void_weekly_wrap(
                world.wrap_id or "", factories.void_payload(), COMPTROLLER_HEADERS
            ),
            200,
        )
        assert voided["status"] == "VOID"
        assert world.production()["recouped_amount_cents"] == 0
        assert world.production()["recoupment_pct"] == 0.0000

        replacement_id = fixtures.new_wrap(world, running_expenses_cents=28_250_000)
        assert (
            get_success_data(api.get_weekly_wrap(replacement_id, GM_HEADERS), 200)[
                "week_ending_date"
            ]
            == "2026-09-06"
        )

    def test_the_replacement_settles_on_its_own_figures_alone(self, api: ApiClient):
        """The corrected week recoups 21,775,000, not the sum of both attempts.

        "First, the `weekly_operating_profit_cents` of every wrap of the
        production whose `status` is `CERTIFIED` — wraps in `DRAFT`, `SUBMITTED`,
        `DISPUTED`, `AMENDED` or `VOID` contribute nothing."

        Design: Difficulty/resource_temporal_overlap/voided_wrap_frees_its_week_for_a_replacement
        """
        world = self._certified_then_blocked(api)
        get_success_data(
            api.void_weekly_wrap(
                world.wrap_id or "", factories.void_payload(), COMPTROLLER_HEADERS
            ),
            200,
        )

        replacement_id = fixtures.new_wrap(world, running_expenses_cents=28_250_000)
        fixtures.submit_wrap(world, replacement_id)
        replacement = fixtures.certify_wrap(world, replacement_id)

        assert replacement["royalty_base_cents"] == 33_500_000
        assert replacement["royalty_pool_cents"] == 11_725_000
        assert replacement["weekly_operating_profit_cents"] == 21_775_000
        assert world.production()["recouped_amount_cents"] == 21_775_000

        rows, meta = validate_paginated(
            api.list_weekly_wraps(GM_HEADERS, {"production_id": world.production_id})
        )
        assert meta["total_count"] == 2
        statuses = sorted(row["status"] for row in rows)
        assert statuses == ["CERTIFIED", "VOID"]
