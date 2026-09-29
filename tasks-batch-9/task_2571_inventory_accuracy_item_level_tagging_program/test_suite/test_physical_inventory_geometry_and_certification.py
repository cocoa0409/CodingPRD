"""
The closed-interval physical-inventory blackout and the certification gate.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_PHYSICAL_INVENTORY_BLACKOUT_CONFLICT,
    ERR_SHRINK_PERIOD_STILL_OPEN,
)
from test_helpers.assertions import assert_clock_instant
from test_helpers.test_users import CONTROLLER, SUPERVISOR


def _schedule(api, store_id, counter_firm_id, start_date, end_date):
    return api.create_physical_inventory(
        f.physical_inventory_payload(
            store_id,
            counter_firm_id,
            scheduled_start_date=start_date,
            scheduled_end_date=end_date,
        ),
        CONTROLLER,
    )


class TestBlackoutInterval:
    def test_a_request_touching_the_padded_upper_end_collides(self, api):
        """
        The padded interval is inclusive on both ends.

        "Pinned: an existing inventory scheduled 2026-09-10 through 2026-09-12
        blacks out 2026-09-07 through 2026-09-15, so a request for 2026-09-15
        through 2026-09-16 collides because 2026-09-15 is on or before 2026-09-15,
        while a request for 2026-09-16 through 2026-09-17 is accepted because
        2026-09-16 is after 2026-09-15."

        Design: Difficulty/resource_temporal_overlap/physical_inventory_closed_interval_blackout_buffer
        """
        world = fx.physical_inventory_world(api, with_period=False)

        validate_error(
            _schedule(
                api,
                world["store_id"],
                world["counter_firm_id"],
                "2026-09-15",
                "2026-09-16",
            ),
            ERR_PHYSICAL_INVENTORY_BLACKOUT_CONFLICT,
            409,
        )

        rows, meta = validate_paginated(api.list_physical_inventories(CONTROLLER))
        assert meta["total_count"] == 1

    def test_a_request_one_day_past_the_padded_upper_end_is_accepted(self, api):
        """
        Clearing the padding by one day clears the blackout.

        "Each such inventory projects a blackout interval running from its
        `scheduled_start_date` minus 3 calendar days through its
        `scheduled_end_date` plus 3 calendar days, and both ends of that padded
        interval are **inclusive**."

        Design: Difficulty/resource_temporal_overlap/physical_inventory_closed_interval_blackout_buffer
        """
        world = fx.physical_inventory_world(api, with_period=False)

        accepted = validate_success(
            _schedule(
                api,
                world["store_id"],
                world["counter_firm_id"],
                "2026-09-16",
                "2026-09-17",
            ),
            201,
        )
        assert accepted["status"] == "PLANNED"
        assert accepted["recount_round"] == 0
        assert accepted["line_count"] == 0
        assert accepted["certified_at"] is None

    def test_the_padded_lower_end_behaves_the_same_way(self, api):
        """
        The collision test is symmetric.

        "The requested interval, also inclusive at both ends, collides when the
        requested `scheduled_start_date` is on or before the existing blackout's
        upper end **and** the requested `scheduled_end_date` is on or after the
        existing blackout's lower end."

        Design: Difficulty/resource_temporal_overlap/physical_inventory_closed_interval_blackout_buffer
        """
        world = fx.physical_inventory_world(api, with_period=False)

        validate_error(
            _schedule(
                api,
                world["store_id"],
                world["counter_firm_id"],
                "2026-09-06",
                "2026-09-07",
            ),
            ERR_PHYSICAL_INVENTORY_BLACKOUT_CONFLICT,
            409,
        )

        accepted = validate_success(
            _schedule(
                api,
                world["store_id"],
                world["counter_firm_id"],
                "2026-09-05",
                "2026-09-06",
            ),
            201,
        )
        assert accepted["scheduled_end_date"] == "2026-09-06"

    def test_abandoning_the_existing_inventory_releases_the_interval(self, api):
        """
        An abandoned inventory stops projecting a blackout.

        "Separately, a `ShrinkController` or `SystemAdmin` may abandon a `PLANNED`
        inventory, optionally with a `note`, moving it to the terminal `ABANDONED`;
        that releases the store's blackout interval so a new inventory may be
        scheduled over the same dates."

        Design: Difficulty/resource_temporal_overlap/physical_inventory_closed_interval_blackout_buffer
        """
        world = fx.physical_inventory_world(api, with_period=False)
        validate_error(
            _schedule(
                api,
                world["store_id"],
                world["counter_firm_id"],
                "2026-09-15",
                "2026-09-16",
            ),
            ERR_PHYSICAL_INVENTORY_BLACKOUT_CONFLICT,
            409,
        )

        abandoned = validate_success(
            api.abandon_physical_inventory(world["physical_inventory_id"], CONTROLLER)
        )
        assert abandoned["status"] == "ABANDONED"

        accepted = validate_success(
            _schedule(
                api,
                world["store_id"],
                world["counter_firm_id"],
                "2026-09-15",
                "2026-09-16",
            ),
            201,
        )
        assert accepted["status"] == "PLANNED"


class TestCertificationRequiresASettledPeriod:
    @staticmethod
    def _reconciled(api):
        world = fx.physical_inventory_world(api, baseline=100, with_period=True)
        started = validate_success(
            api.start_physical_inventory(world["physical_inventory_id"], CONTROLLER)
        )
        assert started["status"] == "COUNTING"

        line = validate_success(
            api.create_physical_inventory_line(
                world["physical_inventory_id"],
                f.physical_line_payload(world["item_id"], 100, started["version"]),
                CONTROLLER,
            ),
            201,
        )
        assert line["book_units_snapshot"] == 100
        assert line["book_value_snapshot_cents"] == 123400
        assert line["variance_units"] == 0
        assert line["variance_value_cents"] == 0

        completed = validate_success(
            api.complete_pass(world["physical_inventory_id"], CONTROLLER)
        )
        assert completed["status"] == "FIRST_PASS_COMPLETE"
        assert completed["book_value_cents"] == 123400
        assert completed["counted_value_cents"] == 123400
        assert completed["net_variance_cents"] == 0
        assert completed["net_variance_bps"] == 0

        reconciled = validate_success(
            api.reconcile_physical_inventory(world["physical_inventory_id"], CONTROLLER)
        )
        assert reconciled["status"] == "RECONCILING"
        world["reconciled"] = reconciled
        return world

    def test_a_zero_variance_reconcile_mints_no_adjustments(self, api):
        """
        Only non-zero lines mint an adjustment.

        "For every non-superseded line of the current pass whose `variance_units` is
        not zero, walking those lines in ascending line-creation order, an
        adjustment is minted against the stock position for that store and SKU with
        `delta_units` equal to the line's `variance_units`, `reason_code`
        `PHYSICAL_RECONCILIATION`, `investigation_id` null, `approval_state`
        `NOT_REQUIRED` and `posting_state` `POSTED` — posted immediately and exempt
        from the authority ladder as §3.7 states."

        Design: Difficulty/cross_entity_state_dependency/physical_certify_requires_shrink_period_not_open
        """
        world = self._reconciled(api)

        rows, meta = validate_paginated(api.list_adjustments(SUPERVISOR))
        assert rows == []
        assert meta["total_count"] == 0

        position = fx.read_position(api, world["position_id"])
        assert position["on_hand_units"] == 100
        assert position["book_value_cents"] == 123400

    def test_certifying_against_an_open_period_is_refused(self, api):
        """
        Certification asserts that the shrink figures are settled.

        "The shrink period covering `scheduled_end_date` must **not** be in `OPEN`
        status, otherwise `ERR_SHRINK_PERIOD_STILL_OPEN`: certification asserts that
        the shrink figures are settled, so it may only follow a provisional or final
        close."

        Design: Difficulty/cross_entity_state_dependency/physical_certify_requires_shrink_period_not_open
        """
        world = self._reconciled(api)
        assert (
            validate_success(
                api.get_shrink_period(world["shrink_period_id"], CONTROLLER)
            )["status"]
            == "OPEN"
        )

        validate_error(
            api.certify_physical_inventory(world["physical_inventory_id"], CONTROLLER),
            ERR_SHRINK_PERIOD_STILL_OPEN,
            409,
        )

        stalled = fx.read_physical_inventory(api, world["physical_inventory_id"])
        assert stalled["status"] == "RECONCILING"
        assert stalled["certified_at"] is None

    def test_a_provisional_close_releases_the_certification(
        self, api, clock_at_default
    ):
        """
        After a provisional close the same request certifies.

        "A `ShrinkController` certifies a `RECONCILING` inventory, moving it to the
        terminal `CERTIFIED` and stamping `certified_at` with the current
        logical-clock instant."

        Design: Difficulty/cross_entity_state_dependency/physical_certify_requires_shrink_period_not_open
        """
        world = self._reconciled(api)
        validate_error(
            api.certify_physical_inventory(world["physical_inventory_id"], CONTROLLER),
            ERR_SHRINK_PERIOD_STILL_OPEN,
            409,
        )

        closed = validate_success(
            api.provisional_close_shrink_period(world["shrink_period_id"], CONTROLLER)
        )
        assert closed["status"] == "PROVISIONAL_CLOSED"

        certified = validate_success(
            api.certify_physical_inventory(world["physical_inventory_id"], CONTROLLER)
        )
        assert certified["status"] == "CERTIFIED"
        assert_clock_instant(certified["certified_at"], clock_at_default)
