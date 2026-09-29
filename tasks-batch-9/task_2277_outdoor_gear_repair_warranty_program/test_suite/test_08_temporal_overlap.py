"""Interval semantics on two different resources (PRD §3.1, §3.8, §2.11).

Work blocks book technician bench time on a HALF-OPEN interval, so a block that
starts exactly when another ends is adjacency; surge windows declare seasonal
capacity on a CLOSED-INCLUSIVE date interval, so two windows that merely share
one endpoint date already overlap. Each class pins both the accepted and the
refused side of one convention.
"""

from test_helpers import (
    ERR_SURGE_WINDOW_OVERLAP,
    ERR_TECHNICIAN_WINDOW_CONFLICT,
    assert_multiplier,
    assert_row_ids,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

# Pinned bench intervals on the 2026-06-16 UTC calendar date (PRD §3.8).
BLOCK_FIRST_START = "2026-06-16T09:00:00Z"
BLOCK_FIRST_END = "2026-06-16T11:00:00Z"
BLOCK_ADJACENT_START = "2026-06-16T11:00:00Z"
BLOCK_ADJACENT_END = "2026-06-16T12:00:00Z"
BLOCK_STRADDLING_START = "2026-06-16T10:30:00Z"
BLOCK_STRADDLING_END = "2026-06-16T11:30:00Z"

# Pinned surge calendar dates on the centre (PRD §3.1).
SEP_WINDOW_START = "2026-09-01T00:00:00Z"
SEP_WINDOW_END = "2026-09-30T00:00:00Z"
SHARED_ENDPOINT_START = "2026-09-30T00:00:00Z"
SHARED_ENDPOINT_END = "2026-10-15T00:00:00Z"
OCT_WINDOW_START = "2026-10-01T00:00:00Z"
OCT_WINDOW_END = "2026-10-15T00:00:00Z"


def _block_payload(order_id, technician_id, start_at, end_at):
    return {
        "repair_order_id": order_id,
        "work_type": "FABRIC",
        "start_at": start_at,
        "end_at": end_at,
        "technician_id": technician_id,
    }


class TestTechnicianHalfOpenBlockInterval:
    """Half-open bench intervals: adjacency accepted, straddle refused."""

    def test_block_starting_when_previous_ends_is_adjacency_and_is_scheduled(
        self, open_order, api, agent_headers
    ):
        """A block booked 11:00-12:00 behind a 09:00-11:00 block is accepted.

        "the interval is half-open, so a block ending exactly when another begins is adjacency and not overlap"
        "Two blocks overlap when the existing block's `start_at` is strictly before the requested `end_at` **and** the requested `start_at` is strictly before the existing block's `end_at`."
        "the block's `duration_minutes` is the whole number of minutes between `start_at` and `end_at`, its `status` is `SCHEDULED`, its `actual_minutes` is null, the assigned technician's `scheduled_minutes_open` increases by `duration_minutes`"

        Design: Difficulty/resource_temporal_overlap/technician_half_open_adjacent_block_allowed_overlap_rejected
        """
        scenario = open_order.scenario
        technician_id = open_order.technician_id

        first = get_success_data(
            api.create_work_block(
                _block_payload(
                    open_order.order_id,
                    technician_id,
                    BLOCK_FIRST_START,
                    BLOCK_FIRST_END,
                ),
                agent_headers,
            ),
            201,
        )
        assert first["status"] == "SCHEDULED", first
        assert first["duration_minutes"] == 120, first
        assert scenario.read_technician(technician_id)["scheduled_minutes_open"] == 120

        adjacent_response = api.create_work_block(
            _block_payload(
                open_order.order_id,
                technician_id,
                BLOCK_ADJACENT_START,
                BLOCK_ADJACENT_END,
            ),
            agent_headers,
        )
        adjacent = validate_success(adjacent_response, 201)

        assert adjacent["technician_id"] == technician_id, adjacent
        assert adjacent["status"] == "SCHEDULED", adjacent
        assert adjacent["duration_minutes"] == 60, adjacent
        assert adjacent["actual_minutes"] is None, adjacent
        assert adjacent["start_at"].startswith("2026-06-16T11:00:00"), adjacent

        # The adjacent booking is a real reservation of bench time: 120 + 60.
        technician = scenario.read_technician(technician_id)
        assert technician["scheduled_minutes_open"] == 180, technician

        rows, _meta = validate_paginated(
            api.list_work_blocks(
                agent_headers, technician_id=technician_id, status="SCHEDULED"
            )
        )
        assert_row_ids(rows, [first["id"], adjacent["id"]])

    def test_block_straddling_an_existing_interval_is_refused_without_side_effects(
        self, open_order, api, agent_headers
    ):
        """A 10:30-11:30 block over the 09:00-11:00 interior is refused.

        "must have no block already in `status` `SCHEDULED` overlapping the requested half-open interval — a conflict is refused with `ERR_TECHNICIAN_WINDOW_CONFLICT`"
        "Two blocks overlap when the existing block's `start_at` is strictly before the requested `end_at` **and** the requested `start_at` is strictly before the existing block's `end_at`."
        "Technician minutes are a conserved quantity: every minute added to `scheduled_minutes_open` when a block is booked is given back exactly once, whether by cancellation or by completion."

        Design: Difficulty/resource_temporal_overlap/technician_half_open_adjacent_block_allowed_overlap_rejected
        """
        scenario = open_order.scenario
        technician_id = open_order.technician_id

        first = get_success_data(
            api.create_work_block(
                _block_payload(
                    open_order.order_id,
                    technician_id,
                    BLOCK_FIRST_START,
                    BLOCK_FIRST_END,
                ),
                agent_headers,
            ),
            201,
        )
        adjacent = get_success_data(
            api.create_work_block(
                _block_payload(
                    open_order.order_id,
                    technician_id,
                    BLOCK_ADJACENT_START,
                    BLOCK_ADJACENT_END,
                ),
                agent_headers,
            ),
            201,
        )
        assert scenario.read_technician(technician_id)["scheduled_minutes_open"] == 180

        conflict_response = api.create_work_block(
            _block_payload(
                open_order.order_id,
                technician_id,
                BLOCK_STRADDLING_START,
                BLOCK_STRADDLING_END,
            ),
            agent_headers,
        )
        validate_error(conflict_response, ERR_TECHNICIAN_WINDOW_CONFLICT)

        rows, meta = validate_paginated(
            api.list_work_blocks(
                agent_headers, technician_id=technician_id, status="SCHEDULED"
            )
        )
        assert meta["total_count"] == 2, meta
        assert_row_ids(rows, [first["id"], adjacent["id"]])

        technician = scenario.read_technician(technician_id)
        assert technician["scheduled_minutes_open"] == 180, technician


class TestSurgeWindowClosedInclusiveInterval:
    """Closed-inclusive surge dates: shared endpoint refused, day-after accepted."""

    def test_window_starting_on_the_incumbents_last_day_is_refused(
        self, scenario, api, admin_headers
    ):
        """A window opening 2026-09-30 against a 09-01..09-30 window is refused.

        "a `start_date` that is the first covered instant and an `end_date` that is the last covered instant — the interval is closed on both ends"
        "Because the interval is closed, two windows that merely share a single endpoint date already overlap, and a create that would do so against an existing `ACTIVE` window of the same centre is refused with `ERR_SURGE_WINDOW_OVERLAP`"
        "A new active surge window must not overlap an existing active window of the same centre on closed-inclusive semantics, else `ERR_SURGE_WINDOW_OVERLAP`"

        Design: Difficulty/resource_temporal_overlap/surge_window_shared_endpoint_date_rejected_disjoint_accepted
        """
        scenario.set_clock()
        center = scenario.center()
        september = scenario.surge_window(
            center["id"],
            label="September shoulder surge",
            start_date=SEP_WINDOW_START,
            end_date=SEP_WINDOW_END,
            multiplier=1.25,
        )
        assert september["status"] == "ACTIVE", september

        overlap_response = api.create_surge_window(
            center["id"],
            {
                "label": "Fall overlap attempt",
                "start_date": SHARED_ENDPOINT_START,
                "end_date": SHARED_ENDPOINT_END,
                "multiplier": 1.60,
            },
            admin_headers,
        )
        validate_error(overlap_response, ERR_SURGE_WINDOW_OVERLAP)

        rows, meta = validate_paginated(
            api.list_surge_windows(center["id"], admin_headers, status="ACTIVE")
        )
        assert meta["total_count"] == 1, meta
        assert_row_ids(rows, [september["id"]])

    def test_window_starting_the_day_after_is_disjoint_and_accepted(
        self, scenario, api, admin_headers
    ):
        """A 2026-10-01..10-15 window behind a 09-01..09-30 window is accepted.

        "Because the interval is closed, two windows that merely share a single endpoint date already overlap, and a create that would do so against an existing `ACTIVE` window of the same centre is refused with `ERR_SURGE_WINDOW_OVERLAP`"
        "Its `status` begins as `ACTIVE` and becomes `RETIRED` once a queue-review observes that its `end_date` has fallen behind the logical clock."
        "Every accepted window recomputes the centre's `current_surge_multiplier`."
        "among the centre's surge windows whose `status` is `ACTIVE` and whose `start_date` is at or before the logical clock instant and whose `end_date` is at or after it — the window is inclusive at both ends — the largest `multiplier` is taken, or 1.00 when no such window exists"

        Design: Difficulty/resource_temporal_overlap/surge_window_shared_endpoint_date_rejected_disjoint_accepted
        """
        scenario.set_clock()
        center = scenario.center()
        september = scenario.surge_window(
            center["id"],
            label="September shoulder surge",
            start_date=SEP_WINDOW_START,
            end_date=SEP_WINDOW_END,
            multiplier=1.25,
        )

        october_response = api.create_surge_window(
            center["id"],
            {
                "label": "October surge",
                "start_date": OCT_WINDOW_START,
                "end_date": OCT_WINDOW_END,
                "multiplier": 1.60,
            },
            admin_headers,
        )
        october = validate_success(october_response, 201)

        assert october["status"] == "ACTIVE", october
        assert_multiplier(october["multiplier"], 1.60)

        rows, meta = validate_paginated(
            api.list_surge_windows(center["id"], admin_headers, status="ACTIVE")
        )
        assert meta["total_count"] == 2, meta
        assert_row_ids(rows, [september["id"], october["id"]])

        # Neither window covers the 2026-06-15 logical clock, and the queue is
        # empty, so the centre's live multiplier stays at the 1.00 floor.
        center_row = scenario.read_center(center["id"])
        assert_multiplier(center_row["current_surge_multiplier"], 1.00)
