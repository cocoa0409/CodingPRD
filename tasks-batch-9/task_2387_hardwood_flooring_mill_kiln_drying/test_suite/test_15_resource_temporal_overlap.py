"""Two resources with deliberately different interval semantics: kiln chambers
are exclusive over a closed interval that includes the cooldown buffer, while
prefinish lines share half-open windows under one aggregate capacity."""

import pytest

from test_helpers import (
    create_kiln_charge_payload,
    create_prefinish_run_payload,
    setup_mill_configuration,
    setup_scheduled_prefinish_run,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    OPERATOR,
    SCHEDULER,
    create_chamber,
    create_charge,
)

OVERLAPPING_WINDOW = {
    "window_start_utc": "2026-08-20T13:00:00.000Z",
    "window_end_utc": "2026-08-20T14:00:00.000Z",
}
BACK_TO_BACK_WINDOW = {
    "window_start_utc": "2026-08-20T14:00:00.000Z",
    "window_end_utc": "2026-08-20T22:00:00.000Z",
}


class TestChamberClosedOccupancyInterval:
    """A charge holds its chamber through the cooldown buffer, and the interval
    is closed at both ends."""

    def test_a_charge_starting_exactly_at_the_block_instant_collides(self, api):
        """PRD 2.9: "A kiln chamber holds at most one charge over any instant, and a
        charge continues to hold its chamber through a **cooldown buffer of 6 hours**
        after its planned end."

        PRD 2.9: "A charge's occupancy interval therefore runs from
        `planned_start_utc` to `blocked_until_utc` and is **closed at both ends**: two
        occupancy intervals that merely touch at an endpoint are in conflict."

        PRD 2.9: "Where an existing window is blocked until a given instant, a
        candidate starting exactly at that instant conflicts, and a candidate starting
        one hour later does not."

        Design: Difficulty/resource_temporal_overlap/chamber_closed_interval_includes_cooldown_buffer
        """
        ctx = setup_mill_configuration(api)
        charge_a = create_charge(api, ctx["schedule"], ctx["chamber"])
        assert charge_a["planned_end_utc"] == "2026-08-16T01:00:00.000Z"
        assert charge_a["blocked_until_utc"] == "2026-08-16T07:00:00.000Z"

        touching = api.create_kiln_charge(
            create_kiln_charge_payload(
                ctx["schedule"]["id"],
                ctx["chamber"]["id"],
                planned_start_utc="2026-08-16T07:00:00.000Z",
            ),
            OPERATOR,
        )
        validate_error(touching, "ERR_CHAMBER_WINDOW_CONFLICT", expected_status=409)

        clear = validate_success(
            api.create_kiln_charge(
                create_kiln_charge_payload(
                    ctx["schedule"]["id"],
                    ctx["chamber"]["id"],
                    planned_start_utc="2026-08-16T08:00:00.000Z",
                ),
                OPERATOR,
            ),
            expected_status=201,
        )
        assert clear["planned_start_utc"] == "2026-08-16T08:00:00.000Z"
        assert clear["planned_end_utc"] == "2026-08-27T09:00:00.000Z"
        assert clear["blocked_until_utc"] == "2026-08-27T15:00:00.000Z"

    def test_the_exclusion_is_per_chamber_and_not_a_global_calendar(self, api):
        """PRD 2.9: "The existing charges considered are those on the same
        `kiln_chamber_id` whose status is `SCHEDULED`, `LOADED`, `DRYING`,
        `CONDITIONING`, `REDRY` or `RELEASED` — a `DISPLACED` or `CLOSED` charge holds
        no window."

        PRD 3.3: "Charges may be listed filtered by `drying_schedule_id`,
        `kiln_chamber_id` or `status`."

        Design: Difficulty/resource_temporal_overlap/chamber_closed_interval_includes_cooldown_buffer
        """
        ctx = setup_mill_configuration(api)
        create_charge(api, ctx["schedule"], ctx["chamber"])
        validate_success(
            api.create_kiln_charge(
                create_kiln_charge_payload(
                    ctx["schedule"]["id"],
                    ctx["chamber"]["id"],
                    planned_start_utc="2026-08-16T08:00:00.000Z",
                ),
                OPERATOR,
            ),
            expected_status=201,
        )

        second_chamber = create_chamber(api, chamber_code="K2")
        twin = validate_success(
            api.create_kiln_charge(
                create_kiln_charge_payload(
                    ctx["schedule"]["id"],
                    second_chamber["id"],
                    planned_start_utc="2026-08-05T00:00:00.000Z",
                ),
                OPERATOR,
            ),
            expected_status=201,
        )
        assert twin["kiln_chamber_id"] == second_chamber["id"]

        _rows, meta = validate_paginated(
            api.list_kiln_charges(ADMIN, params={"kiln_chamber_id": ctx["chamber"]["id"]})
        )
        assert meta["total_count"] == 2


class TestPrefinishHalfOpenAggregateCapacity:
    """Adjacent windows do not interact; overlapping ones share one ceiling."""

    def _line_with_two_runs(self, api):
        ctx = setup_scheduled_prefinish_run(api)
        ctx["prefinish_run_b"] = validate_success(
            api.create_prefinish_run(
                create_prefinish_run_payload(
                    ctx["prefinish_line"]["id"],
                    ctx["lot"]["id"],
                    scheduled_linear_feet=5000,
                    **BACK_TO_BACK_WINDOW,
                ),
                SCHEDULER,
            ),
            expected_status=201,
        )
        return ctx

    def test_back_to_back_windows_leave_room_to_fill_the_line_exactly(self, api):
        """PRD 2.9: "Prefinish windows are **half-open**, running from
        `window_start_utc` inclusive to `window_end_utc` exclusive, so two back-to-back
        windows with zero gap do **not** overlap."

        PRD 3.8: "On a line with a capacity of 9000 linear feet already carrying a
        run from 06:00 to 14:00 at 5000 linear feet, a candidate from 13:00 to 14:00 at
        4000 linear feet totals exactly 9000 and is accepted, the same candidate at
        4001 is refused, and a candidate from 14:00 to 22:00 at 5000 linear feet does
        not overlap at all and is accepted."

        PRD 3.8: "The square footage passing through the line is
        `scheduled_linear_feet` multiplied by the lot's `actual_milled_width_in` and
        divided by 12, and `coating_liters` is that square footage multiplied by 0.012
        litres per square foot and by the line's number of `coating_passes`, rounded
        half up to two decimal places once at the very end — the square footage is not
        pre-rounded."

        Design: Difficulty/resource_temporal_overlap/prefinish_half_open_windows_share_aggregate_capacity
        """
        ctx = self._line_with_two_runs(api)
        assert ctx["prefinish_run"]["coating_liters"] == pytest.approx(47.85, abs=0.01)
        assert ctx["prefinish_run_b"]["status"] == "SCHEDULED"

        filling = validate_success(
            api.create_prefinish_run(
                create_prefinish_run_payload(
                    ctx["prefinish_line"]["id"],
                    ctx["lot"]["id"],
                    scheduled_linear_feet=4000,
                    stain_code="WALNUT",
                    **OVERLAPPING_WINDOW,
                ),
                SCHEDULER,
            ),
            expected_status=201,
        )
        assert filling["scheduled_linear_feet"] == 4000
        assert filling["coating_liters"] == pytest.approx(38.28, abs=0.01)

    def test_one_further_linear_foot_in_the_same_overlap_is_refused(self, api):
        """PRD 3.8: "The runs that matter are those on the same prefinish line whose
        status is `SCHEDULED`, `HELD` or `RUNNING` and whose half-open window intersects
        the candidate's."

        PRD 3.8: "Their `scheduled_linear_feet` are totalled, the candidate's own
        footage is added, and the result must be at most the line's
        `daily_capacity_linear_feet`, or the request is refused with
        `ERR_PREFINISH_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/prefinish_half_open_windows_share_aggregate_capacity
        """
        ctx = self._line_with_two_runs(api)
        validate_success(
            api.create_prefinish_run(
                create_prefinish_run_payload(
                    ctx["prefinish_line"]["id"],
                    ctx["lot"]["id"],
                    scheduled_linear_feet=4000,
                    stain_code="WALNUT",
                    **OVERLAPPING_WINDOW,
                ),
                SCHEDULER,
            ),
            expected_status=201,
        )

        response = api.create_prefinish_run(
            create_prefinish_run_payload(
                ctx["prefinish_line"]["id"],
                ctx["lot"]["id"],
                scheduled_linear_feet=1,
                stain_code="WALNUT",
                **OVERLAPPING_WINDOW,
            ),
            SCHEDULER,
        )
        validate_error(response, "ERR_PREFINISH_CAPACITY_EXCEEDED", expected_status=422)

        _rows, meta = validate_paginated(
            api.list_prefinish_runs(
                SCHEDULER, params={"prefinish_line_id": ctx["prefinish_line"]["id"]}
            )
        )
        assert meta["total_count"] == 3
