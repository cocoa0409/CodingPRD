"""The calendar is checked twice, under two deliberately different conventions.

A device is booked on half-open intervals stretched by a cleaning allowance, so
studies that merely touch may follow one another.  A technologist is counted on
closed intervals with no allowance at all, so studies that merely touch conflict.
The same pair of timestamps can therefore clear one gate and fail the other.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_DEVICE_WINDOW_CONFLICT,
    ERR_TECHNOLOGIST_WINDOW_CONFLICT,
)
from test_helpers.assertions import assert_page


def _one_live_study_on_a_single_spirometer(api):
    """SPIRO-1 occupied from 09:00 to 09:30, and a second order waiting at READY."""
    lab = fx.build_lab(api)
    first = fx.build_scheduled_session(api, lab)
    waiting = fx.build_ready_order(api, lab)
    return lab, first, waiting


def _attempt_window(api, lab, order, device_id, start, end, tech_headers=None):
    return api.create_test_session(
        f.test_session_payload(order["id"], device_id, start, end),
        tech_headers or lab.tech1,
    )


class TestDeviceOccupancyWindow:
    """The instrument's booked interval is extended by its turnaround allowance."""

    def test_a_window_starting_inside_the_turnaround_allowance_is_refused(self, api):
        """09:45 falls inside the 09:30 study's buffered occupancy of the instrument.

        PRD 3.5: "The **device occupancy** gate treats the requested window as
        the half-open interval from `scheduled_start_at` up to but not including
        `scheduled_end_at`, extends its end by a 20-minute turnaround allowance
        for cleaning and warm-up, and compares it against the identically
        extended window of every other study on the same device whose
        `session_status` is `SCHEDULED` or `IN_PROGRESS`."

        Design: Difficulty/resource_temporal_overlap/device_half_open_window_plus_turnaround_buffer_rejects_overlap_allows_adjacency
        """
        lab, first, waiting = _one_live_study_on_a_single_spirometer(api)

        refused = _attempt_window(
            api, lab, waiting, lab.device_id,
            "2026-08-03T09:45:00Z", "2026-08-03T10:15:00Z",
        )

        validate_error(refused, ERR_DEVICE_WINDOW_CONFLICT)
        still_ready = validate_success(api.get_test_order(waiting["id"], lab.doc1))
        assert still_ready["status"] == "READY"
        _, meta = validate_paginated(
            api.list_test_sessions(lab.tech1, device_id=lab.device_id)
        )
        assert_page(meta, total_count=1, has_more=False)
        untouched = validate_success(api.get_test_session(first["id"], lab.tech1))
        assert untouched["session_status"] == "SCHEDULED"

    def test_a_window_starting_exactly_where_the_allowance_ends_is_accepted(self, api):
        """09:50 touches the buffered end of the 09:00 study and is legal.

        PRD 3.5: "Overlap is `ERR_DEVICE_WINDOW_CONFLICT`; intervals that merely
        touch — one study's extended end landing exactly on another's start — are
        accepted, because the turnaround allowance has already done its work."

        Design: Difficulty/resource_temporal_overlap/device_half_open_window_plus_turnaround_buffer_rejects_overlap_allows_adjacency
        """
        lab, first, waiting = _one_live_study_on_a_single_spirometer(api)
        validate_error(
            _attempt_window(
                api, lab, waiting, lab.device_id,
                "2026-08-03T09:45:00Z", "2026-08-03T10:15:00Z",
            ),
            ERR_DEVICE_WINDOW_CONFLICT,
        )

        adjacent = validate_success(
            _attempt_window(
                api, lab, waiting, lab.device_id,
                "2026-08-03T09:50:00Z", "2026-08-03T10:20:00Z",
            ),
            expected_status=201,
        )

        assert adjacent["session_status"] == "SCHEDULED"
        _, meta = validate_paginated(
            api.list_test_sessions(lab.tech1, device_id=lab.device_id)
        )
        assert_page(meta, total_count=2, has_more=False)
        for order_id in (first["order_id"], waiting["id"]):
            order = validate_success(api.get_test_order(order_id, lab.doc1))
            assert order["status"] == "IN_TESTING"


def _technologist_holding_two_overlapping_studies(api):
    """T-001 booked on two instruments at once, with a third instrument idle."""
    lab = fx.build_lab(
        api, device_codes=("SPIRO-1", "SPIRO-2", "SPIRO-3"), second_technologist=True
    )
    fx.build_scheduled_session(api, lab)
    fx.build_scheduled_session(
        api,
        lab,
        device_id=lab.device_ids[1],
        scheduled_start_at="2026-08-03T09:15:00Z",
        scheduled_end_at="2026-08-03T09:45:00Z",
    )
    third = fx.build_ready_order(api, lab)
    return lab, third


class TestTechnologistWorkloadWindow:
    """A person is counted on closed intervals, so touching endpoints collide."""

    def test_a_window_touching_an_existing_study_reaches_capacity_and_is_refused(self, api):
        """09:30 touches the 09:00 study, so the intersecting count is exactly two.

        PRD 3.5: "The **technologist workload** gate treats the requested window
        as the closed interval from `scheduled_start_at` through
        `scheduled_end_at` inclusive, applies no turnaround extension, and counts
        the acting technologist's other `SCHEDULED` or `IN_PROGRESS` studies
        whose closed intervals intersect it."

        Design: Difficulty/resource_temporal_overlap/technologist_closed_window_capacity_two_rejects_touching_third_session
        """
        lab, third = _technologist_holding_two_overlapping_studies(api)

        refused = _attempt_window(
            api, lab, third, lab.device_ids[2],
            "2026-08-03T09:30:00Z", "2026-08-03T10:00:00Z",
        )

        body = validate_error(refused, ERR_TECHNOLOGIST_WINDOW_CONFLICT)
        assert body["error_id"] != ERR_DEVICE_WINDOW_CONFLICT, (
            "the third instrument is idle, so the instrument calendar is clear"
        )
        still_ready = validate_success(api.get_test_order(third["id"], lab.doc1))
        assert still_ready["status"] == "READY"

    def test_the_identical_window_is_accepted_for_an_unbooked_technologist(self, api):
        """Capacity is per person, so a colleague may take the very same window.

        PRD 3.5: "The count must be strictly below 2, and exceeding it reports
        `ERR_TECHNOLOGIST_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/technologist_closed_window_capacity_two_rejects_touching_third_session
        """
        lab, third = _technologist_holding_two_overlapping_studies(api)
        validate_error(
            _attempt_window(
                api, lab, third, lab.device_ids[2],
                "2026-08-03T09:30:00Z", "2026-08-03T10:00:00Z",
            ),
            ERR_TECHNOLOGIST_WINDOW_CONFLICT,
        )

        booked = validate_success(
            _attempt_window(
                api, lab, third, lab.device_ids[2],
                "2026-08-03T09:30:00Z", "2026-08-03T10:00:00Z",
                tech_headers=lab.roster.tech2,
            ),
            expected_status=201,
        )

        assert booked["technologist_staff_id"] == lab.roster.tech2_id
        assert booked["session_status"] == "SCHEDULED"
        _, busy = validate_paginated(
            api.list_test_sessions(lab.tech1, technologist_staff_id=lab.tech1_id)
        )
        assert_page(busy, total_count=2, has_more=False)
        _, colleague = validate_paginated(
            api.list_test_sessions(lab.tech1, technologist_staff_id=lab.roster.tech2_id)
        )
        assert_page(colleague, total_count=1, has_more=False)
        in_testing = validate_success(api.get_test_order(third["id"], lab.doc1))
        assert in_testing["status"] == "IN_TESTING"
