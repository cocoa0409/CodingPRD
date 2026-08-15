"""Crane slot booking: buffered half-open intervals, slot-in-past, crane OCC."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_crane,
    book_slot,
    cancel_slot,
    set_clock,
    create_crane_slot_payload,
    setup_crane_with_booked_slot,
    crane_fresh,
    get_success_data,
)

PM = TEST_USERS["plant_manager_headers"]
PP = TEST_USERS["production_planner_headers"]


class TestCraneBufferExact30Minutes:
    def test_exactly_30_minutes_after_accepted_29_rejected(self, api):
        """PRD §3.6: "Exactly 30 minutes of gap is acceptable — a slot starting
        precisely 30 minutes after another ends is accepted, while 29 minutes is
        rejected"."

        Design: Difficulty/boundary_precision_check/crane_buffer_exact_30_minutes
        """
        ns = setup_crane_with_booked_slot()  # BOOKED 10:00-12:00 on 2026-08-12
        version_before = crane_fresh(ns.crane["id"])["version"]
        s2 = book_slot(ns.crane["id"], "BUILD_PICK", "2026-08-12T12:30:00Z", "2026-08-12T14:00:00Z")
        assert s2["status"] == "BOOKED", "a start exactly 30 minutes after the end is accepted"
        resp = api.create_crane_slot(
            create_crane_slot_payload(ns.crane["id"], "BUILD_PICK", "2026-08-12T12:29:00Z",
                                      "2026-08-12T13:30:00Z",
                                      crane_fresh(ns.crane["id"])["version"]),
            PP,
        )
        validate_error(resp, ApiErrorId.ERR_CRANE_SLOT_OVERLAP)
        assert crane_fresh(ns.crane["id"])["version"] == version_before + 1, \
            "a rejected booking is no mutation and must not bump the crane's version"

    def test_exactly_30_minutes_before_accepted_29_rejected(self, api):
        """PRD §3.6: "a new slot is rejected with `ERR_CRANE_SLOT_OVERLAP` (HTTP 409)
        unless, for every existing slot on that crane in `BOOKED` or `COMPLETED`, the
        new slot's `start_at` is at or after the existing slot's `end_at` plus 30
        minutes, or the new slot's `end_at` is at or before the existing slot's
        `start_at` minus 30 minutes."

        Design: Difficulty/boundary_precision_check/crane_buffer_exact_30_minutes
        """
        ns = setup_crane_with_booked_slot()  # BOOKED 10:00-12:00 on 2026-08-12
        s4 = book_slot(ns.crane["id"], "BUILD_PICK", "2026-08-12T08:00:00Z", "2026-08-12T09:30:00Z")
        assert s4["status"] == "BOOKED", "an end exactly 30 minutes before the start is accepted"
        resp = api.create_crane_slot(
            create_crane_slot_payload(ns.crane["id"], "BUILD_PICK", "2026-08-12T07:00:00Z",
                                      "2026-08-12T09:31:00Z",
                                      crane_fresh(ns.crane["id"])["version"]),
            PP,
        )
        validate_error(resp, ApiErrorId.ERR_CRANE_SLOT_OVERLAP)


class TestCraneSlotPairwiseBufferRule:
    def test_intersecting_slot_rejected(self, api):
        """PRD §3.6: "Under the overlap rule, slots occupy half-open intervals — the
        start inclusive, the end exclusive — with a mandatory 30-minute buffer on the
        same crane: a new slot is rejected with `ERR_CRANE_SLOT_OVERLAP` (HTTP 409)
        unless, for every existing slot on that crane in `BOOKED` or `COMPLETED`, the
        new slot's `start_at` is at or after the existing slot's `end_at` plus 30
        minutes, or the new slot's `end_at` is at or before the existing slot's
        `start_at` minus 30 minutes."

        Design: Difficulty/resource_temporal_overlap/crane_slot_pairwise_buffer_rule
        """
        ns = setup_crane_with_booked_slot({"crane_code": "CR-C", "capacity_lbs": 8000,
                                           "crane_class": "STANDARD", "hourly_rate_cents": 15000})
        resp = api.create_crane_slot(
            create_crane_slot_payload(ns.crane["id"], "BUILD_PICK", "2026-08-12T11:00:00Z",
                                      "2026-08-12T13:00:00Z",
                                      crane_fresh(ns.crane["id"])["version"]),
            PP,
        )
        validate_error(resp, ApiErrorId.ERR_CRANE_SLOT_OVERLAP)

    def test_cancelled_slot_frees_interval(self, api):
        """PRD §3.6: "`CANCELLED` slots occupy nothing" and "cancelling frees the
        interval, and later overlap checks ignore it".

        Design: Difficulty/resource_temporal_overlap/crane_slot_pairwise_buffer_rule
        """
        ns = setup_crane_with_booked_slot({"crane_code": "CR-C", "capacity_lbs": 8000,
                                           "crane_class": "STANDARD", "hourly_rate_cents": 15000})
        cancel_slot(ns.slot["id"])
        s2 = book_slot(ns.crane["id"], "BUILD_PICK", "2026-08-12T11:00:00Z", "2026-08-12T13:00:00Z")
        assert s2["status"] == "BOOKED", "the identical interval is free once the blocker is cancelled"
        cancelled = get_success_data(api.get_crane_slot(ns.slot["id"], PP))
        assert cancelled["status"] == "CANCELLED"


class TestClockDefaultAndSlotInPast:
    def test_clock_default_and_slot_in_past_boundary(self, api):
        """PRD §2.5: "Before any call to the clock-setting capability, the logical
        clock reads exactly 2026-08-01T00:00:00Z — the startup default — and it never
        falls back to wall-clock time." PRD §3.6: "the slot's `start_at` must be on or
        after the current logical clock, else `ERR_SLOT_IN_PAST`."

        Design: Corner/validations/clock_default_and_slot_in_past_boundary
        """
        crane = make_crane(crane_code="CR-C", capacity_lbs=8000, crane_class="STANDARD",
                           hourly_rate_cents=15000)
        # No clock call has happened: 2026-07-31 is in the past relative to the
        # 2026-08-01T00:00:00Z startup default.
        resp1 = api.create_crane_slot(
            create_crane_slot_payload(crane["id"], "BUILD_PICK", "2026-07-31T10:00:00Z",
                                      "2026-07-31T12:00:00Z", crane["version"]), PP)
        validate_error(resp1, ApiErrorId.ERR_SLOT_IN_PAST)
        # start_at exactly equal to the clock satisfies "on or after".
        s1 = book_slot(crane["id"], "BUILD_PICK", "2026-08-01T00:00:00Z", "2026-08-01T02:00:00Z")
        assert s1["status"] == "BOOKED"
        set_clock("2026-08-05T00:00:00Z")
        resp2 = api.create_crane_slot(
            create_crane_slot_payload(crane["id"], "BUILD_PICK", "2026-08-04T10:00:00Z",
                                      "2026-08-04T12:00:00Z", crane_fresh(crane["id"])["version"]),
            PP)
        validate_error(resp2, ApiErrorId.ERR_SLOT_IN_PAST)


class TestCraneSlotOcc:
    def test_stale_crane_version_rejected(self, api):
        """PRD §2.6: "`POST /plant/crane-slots` requires `expected_crane_version`
        matching the target crane's current `version`; a mismatch is rejected with
        `ERR_STALE_CRANE_VERSION` (HTTP 412). A non-overlapping slot would
        legitimately succeed on the updated crane, so the stale-view booking is
        rejected purely on the version."

        Design: Corner/cross_cutting_complexity_layers/occ_crane_slot_stale_version
        """
        crane = make_crane(crane_code="CR-C", capacity_lbs=8000, crane_class="STANDARD",
                           hourly_rate_cents=15000)
        stale_version = crane["version"]
        book_slot(crane["id"], "BUILD_PICK", "2026-08-12T10:00:00Z", "2026-08-12T12:00:00Z")
        assert crane_fresh(crane["id"])["version"] > stale_version, \
            "a successful booking increments the crane's version"
        # Non-overlapping interval, rejected purely on the stale version.
        resp = api.create_crane_slot(
            create_crane_slot_payload(crane["id"], "BUILD_PICK", "2026-08-13T10:00:00Z",
                                      "2026-08-13T12:00:00Z", stale_version), PP)
        validate_error(resp, ApiErrorId.ERR_STALE_CRANE_VERSION)
