"""TestCenter, TestCenterCapacity, and venue time-conflict tests.

Covers PRD §3.2 — TestCenter creation, capacity allocation, the
TestCenter time-conflict rule, and the materialised ledger invariants
from PRD §2.8.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_capacity_invariant,
    assert_test_center,
    assert_test_center_capacity,
    create_capacity,
    create_test_center,
    create_test_event,
    validate_error,
    validate_success,
)


class TestCenterCreation:
    def test_create_center_initial_status_active(self, api):
        """PRD §3.2: "The center begins in `ACTIVE` status (it may also
        be `SUSPENDED`)."

        Claim: a newly created TestCenter has status ACTIVE.
        """
        center = create_test_center()
        assert_test_center(center)
        assert center["status"] == "ACTIVE", (
            "PRD §3.2: TestCenter begins in ACTIVE status"
        )


class TestCapacityCreation:
    def test_initial_counters_reflect_empty_ledger(self, api):
        """PRD §3.2: "At creation the four computed counters are
        initialised: `confirmed_seats_used` is 0,
        `accommodation_seats_used` is 0, `standby_seats_pending` is 0,
        and `available_seats` equals `total_capacity`."

        Claim: a fresh capacity row has all counters at the documented
        initial values.
        """
        event = create_test_event()
        center = create_test_center()
        capacity = create_capacity(
            event["id"], center["id"],
            total_capacity=8, accommodation_capacity=2,
        )
        assert_test_center_capacity(capacity)
        assert capacity["total_capacity"] == 8
        assert capacity["accommodation_capacity"] == 2
        assert capacity["confirmed_seats_used"] == 0
        assert capacity["accommodation_seats_used"] == 0
        assert capacity["standby_seats_pending"] == 0
        assert capacity["available_seats"] == 8
        assert_capacity_invariant(capacity)


# ===========================================================================
# TestCenter time-conflict (closed interval, no buffer)
# ===========================================================================
class TestCenterTimeConflict:
    def test_overlapping_event_at_same_center_rejected(self, api):
        """PRD §3.2: "A `TestCenter` cannot host two different
        `TestEvent`s whose scheduled sessions overlap in the same
        four-hour test-session window. When a `Registrar` allocates
        capacity, the system checks whether the candidate
        `TestEvent`'s window from `test_date` through `test_date + 4
        hours` (closed interval, no buffer) overlaps any other event's
        window already bound to the same `TestCenter`; if it does, the
        allocation is rejected with `ERR_TEST_CENTER_TIME_CONFLICT`."

        Claim: a second capacity allocation for an overlapping event at
        the same center returns ERR_TEST_CENTER_TIME_CONFLICT.
        """
        center = create_test_center()
        e1 = create_test_event(
            test_date="2026-06-08T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
        )
        create_capacity(e1["id"], center["id"], total_capacity=10, accommodation_capacity=2)

        # Overlapping window: e2 starts at 12:00, e1 window 09–13.
        e2 = create_test_event(
            test_date="2026-06-08T12:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
        )
        from test_helpers import create_capacity_payload
        res = api.create_test_center_capacity(
            e2["id"],
            create_capacity_payload(
                test_center_id=center["id"],
                total_capacity=5, accommodation_capacity=0,
            ),
            TEST_USERS["registrar_headers"],
        )
        validate_error(res, ApiErrorId.ERR_TEST_CENTER_TIME_CONFLICT.value)

    def test_non_overlapping_event_at_same_center_allowed(self, api):
        """PRD §3.2: same-center booking is rejected only when the
        windows actually overlap.

        Claim: a second event at the same center, starting after the
        first event's 4-hour session has ended, is allowed.
        """
        center = create_test_center()
        e1 = create_test_event(
            test_date="2026-06-08T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
        )
        create_capacity(e1["id"], center["id"], total_capacity=10, accommodation_capacity=2)
        e2 = create_test_event(
            test_date="2026-06-08T13:30:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
        )
        capacity = create_capacity(
            e2["id"], center["id"], total_capacity=5, accommodation_capacity=0,
        )
        # Successful allocation — invariant must hold.
        assert_capacity_invariant(capacity)
