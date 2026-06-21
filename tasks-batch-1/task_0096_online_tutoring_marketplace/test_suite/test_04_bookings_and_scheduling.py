"""Booking creation, calendar conflicts, reschedule/cancel/no-show flows,
session delivery and confirmation.

Covers the tutor half-open zero-buffer overlap, the student closed buffered
overlap, the Session parallel-dimension confirm, the booking-validation
priority pairs, and the booking lifecycle corners.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    consume_trial_slot,
    create_booking,
    create_student,
    create_verified_tutor,
    deliver_booking,
    make_parent_headers,
    propose_and_approve_tag,
    create_funded_parent,
    create_subject,
    set_clock,
    setup_marketplace,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["trust_officer_headers"]


class TestTutorCalendarOverlap:
    def test_overlapping_booking_on_same_tutor_rejected(self, api):
        """PRD §3.5: "the new booking's half-open interval, running from
        `scheduled_start` up to but not including `scheduled_start` plus
        `planned_minutes`, must not overlap the interval of any of that tutor's
        other non-cancelled bookings ... a true overlap is rejected with
        `ERR_TUTOR_TIME_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/tutor_calendar_half_open_overlap
        """
        mk = setup_marketplace(base_hourly_rate_cents=6000)
        student_a = mk["student"]
        student_b = create_student(mk["parent"]["id"], display_name="KidB")
        # Existing booking 10:00-11:00 (student A).
        create_booking(mk, "2026-06-02T10:00:00Z", planned_minutes=60, student_id=student_a["id"])
        # New booking 10:30-11:30 (student B) overlaps the open interval -> conflict.
        resp = api.create_booking(
            {
                "parent_account_id": mk["parent"]["id"],
                "student_id": student_b["id"],
                "tutor_id": mk["tutor"]["id"],
                "subject_id": mk["subject"]["id"],
                "scheduled_start": "2026-06-02T10:30:00Z",
                "planned_minutes": 60,
            },
            mk["parent_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_TUTOR_TIME_CONFLICT.value)

    def test_adjacent_booking_end_to_start_allowed(self, api):
        """PRD §3.5: "this overlap test uses a zero-minute buffer, so two bookings
        that merely touch end-to-start do not conflict".

        Design: Difficulty/resource_temporal_overlap/tutor_calendar_half_open_overlap
        """
        mk = setup_marketplace(base_hourly_rate_cents=6000)
        student_a = mk["student"]
        student_b = create_student(mk["parent"]["id"], display_name="KidB")
        create_booking(mk, "2026-06-02T10:00:00Z", planned_minutes=60, student_id=student_a["id"])
        # New booking starts exactly at 11:00 (the first's end) -> allowed.
        resp = api.create_booking(
            {
                "parent_account_id": mk["parent"]["id"],
                "student_id": student_b["id"],
                "tutor_id": mk["tutor"]["id"],
                "subject_id": mk["subject"]["id"],
                "scheduled_start": "2026-06-02T11:00:00Z",
                "planned_minutes": 60,
            },
            mk["parent_headers"],
        )
        booking = validate_success(resp, 201)
        assert booking["status"] == "SCHEDULED"


class TestStudentCalendarOverlap:
    def test_student_booking_within_buffer_rejected(self, api):
        """PRD §3.5: "the two conflict when the new booking starts before the
        existing booking's end plus fifteen minutes and the existing booking
        starts before the new booking's end plus fifteen minutes; such a clash is
        rejected with `ERR_STUDENT_TIME_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/student_calendar_buffered_overlap
        """
        set_clock("2026-06-01T00:00:00Z")
        from test_helpers import create_active_policy
        create_active_policy()
        subject = create_subject()
        tutor_a, _ = create_verified_tutor(subject["id"])
        propose_and_approve_tag(tutor_a["id"], subject["id"])
        tutor_b, _ = create_verified_tutor(subject["id"])
        propose_and_approve_tag(tutor_b["id"], subject["id"])
        parent = create_funded_parent(100000)
        p_headers = make_parent_headers(parent["id"])
        student = create_student(parent["id"])

        # Booking 10:00-10:30 on tutor A.
        validate_success(
            api.create_booking(
                {
                    "parent_account_id": parent["id"], "student_id": student["id"],
                    "tutor_id": tutor_a["id"], "subject_id": subject["id"],
                    "scheduled_start": "2026-06-02T10:00:00Z", "planned_minutes": 30,
                },
                p_headers,
            ),
            201,
        )
        # New booking 10:40-11:10 on tutor B: 10:40 < 10:30 + 15min -> conflict.
        resp = api.create_booking(
            {
                "parent_account_id": parent["id"], "student_id": student["id"],
                "tutor_id": tutor_b["id"], "subject_id": subject["id"],
                "scheduled_start": "2026-06-02T10:40:00Z", "planned_minutes": 30,
            },
            p_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STUDENT_TIME_CONFLICT.value)

    def test_student_booking_at_buffer_edge_allowed(self, api):
        """PRD §3.5: "the two conflict when the new booking starts before the
        existing booking's end plus fifteen minutes and the existing booking
        starts before the new booking's end plus fifteen minutes".

        Design: Difficulty/resource_temporal_overlap/student_calendar_buffered_overlap
        """
        set_clock("2026-06-01T00:00:00Z")
        from test_helpers import create_active_policy
        create_active_policy()
        subject = create_subject()
        tutor_a, _ = create_verified_tutor(subject["id"])
        propose_and_approve_tag(tutor_a["id"], subject["id"])
        tutor_b, _ = create_verified_tutor(subject["id"])
        propose_and_approve_tag(tutor_b["id"], subject["id"])
        parent = create_funded_parent(100000)
        p_headers = make_parent_headers(parent["id"])
        student = create_student(parent["id"])

        # Booking 10:00-10:30 on tutor A.
        validate_success(
            api.create_booking(
                {
                    "parent_account_id": parent["id"], "student_id": student["id"],
                    "tutor_id": tutor_a["id"], "subject_id": subject["id"],
                    "scheduled_start": "2026-06-02T10:00:00Z", "planned_minutes": 30,
                },
                p_headers,
            ),
            201,
        )
        # New booking starts exactly at 10:45 == end (10:30) + 15min buffer:
        # start_b < end_a + 15 -> 10:45 < 10:45 is false -> allowed.
        resp = api.create_booking(
            {
                "parent_account_id": parent["id"], "student_id": student["id"],
                "tutor_id": tutor_b["id"], "subject_id": subject["id"],
                "scheduled_start": "2026-06-02T10:45:00Z", "planned_minutes": 30,
            },
            p_headers,
        )
        booking = validate_success(resp, 201)
        assert booking["status"] == "SCHEDULED"


class TestSessionParallelDimensions:
    def test_confirm_advances_both_delivery_and_settlement_axes(self, api):
        """PRD §3.7: "Confirming the delivery moves the session's `delivery_status`
        from `REPORTED` to `CONFIRMED` and triggers settlement: a `Settlement` is
        created, the booking advances from `DELIVERED` to `SETTLED`, the session's
        `settlement_status` becomes `SETTLED`".
        PRD §3.7: "Delivery supplies the `actual_minutes` ... and creates a
        `Session` that records its `booking_id` ... opens in `delivery_status` of
        `REPORTED` and `settlement_status` of `DELIVERED`".

        Design: Difficulty/non_linear_state_machine/session_parallel_settlement_and_delivery_dimensions
        """
        mk = setup_marketplace(base_hourly_rate_cents=6000)
        booking = create_booking(mk, "2026-06-02T10:00:00Z", planned_minutes=30)
        session = deliver_booking(mk, booking["id"], 30, "2026-06-02T11:00:00Z")
        assert session["delivery_status"] == "REPORTED"
        assert session["settlement_status"] == "DELIVERED"

        confirmed = validate_success(api.confirm_session(session["id"], mk["parent_headers"]))
        assert confirmed["delivery_status"] == "CONFIRMED"
        assert confirmed["settlement_status"] == "SETTLED"

    def test_dispute_advances_delivery_axis_only(self, api):
        """PRD §3.7: "Disputing the delivery instead moves the session's
        `delivery_status` from `REPORTED` to `DISPUTED` while leaving
        `settlement_status` at `DELIVERED`".

        Design: Difficulty/non_linear_state_machine/session_parallel_settlement_and_delivery_dimensions
        """
        mk = setup_marketplace(base_hourly_rate_cents=6000)
        booking = create_booking(mk, "2026-06-02T10:00:00Z", planned_minutes=30)
        session = deliver_booking(mk, booking["id"], 30, "2026-06-02T11:00:00Z")
        assert session["delivery_status"] == "REPORTED"
        assert session["settlement_status"] == "DELIVERED"
        # Disputing advances only the delivery axis; the settlement axis is held.
        disputed = validate_success(api.dispute_session(session["id"], mk["parent_headers"]))
        assert disputed["delivery_status"] == "DISPUTED"
        assert disputed["settlement_status"] == "DELIVERED"


class TestBookingValidationPriority:
    def test_not_found_beats_invalid_state_on_confirm(self, api):
        """PRD §4: "Validation across an endpoint is evaluated in a fixed priority
        order: header presence first, then role authorization, then resource
        ownership, then existence of path ids, then existence of body foreign keys,
        then state-machine applicability".

        Design: Difficulty/priority_pair_validation_conflict/not_found_beats_invalid_state_on_confirm
        """
        set_clock("2026-06-01T00:00:00Z")
        parent = create_funded_parent(0)
        p_headers = make_parent_headers(parent["id"])
        resp = api.confirm_session("00000000-0000-4000-8000-000000000000", p_headers)
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_FOUND.value)

    def test_dispute_unknown_session_returns_not_found_before_state(self, api):
        """PRD §4: "header presence first, then role authorization, then resource
        ownership, then existence of path ids, then existence of body foreign keys,
        then state-machine applicability".
        PRD §2.5: "a missing session `ERR_SESSION_NOT_FOUND`".

        Design: Difficulty/priority_pair_validation_conflict/not_found_beats_invalid_state_on_confirm
        """
        set_clock("2026-06-01T00:00:00Z")
        parent = create_funded_parent(0)
        p_headers = make_parent_headers(parent["id"])
        # The path-existence check (priority 4) fires before any state check.
        resp = api.dispute_session("00000000-0000-4000-8000-000000000000", p_headers)
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_FOUND.value)

    def test_subject_not_approved_beats_insufficient_balance(self, api):
        """PRD §3.5: "there must be an `APPROVED` subject tag for the chosen tutor
        and subject, and the tutor must be `VERIFIED`; otherwise the booking is
        rejected with `ERR_TUTOR_SUBJECT_NOT_APPROVED`."
        PRD §4: "then the domain-specific business rules in their listed order."

        Design: Difficulty/priority_pair_validation_conflict/subject_not_approved_beats_insufficient_balance_on_booking
        """
        set_clock("2026-06-01T00:00:00Z")
        subject = create_subject()
        tutor, _ = create_verified_tutor(subject["id"], base_hourly_rate_cents=6000)
        # No APPROVED tag for the tutor/subject. Parent has ZERO balance.
        parent = create_funded_parent(0)
        p_headers = make_parent_headers(parent["id"])
        student = create_student(parent["id"])
        resp = api.create_booking(
            {
                "parent_account_id": parent["id"], "student_id": student["id"],
                "tutor_id": tutor["id"], "subject_id": subject["id"],
                "scheduled_start": "2026-06-02T10:00:00Z", "planned_minutes": 60,
            },
            p_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TUTOR_SUBJECT_NOT_APPROVED.value)

    def test_revoked_tag_booking_beats_insufficient_balance(self, api):
        """PRD §3.5: "there must be an `APPROVED` subject tag for the chosen tutor
        and subject ... otherwise the booking is rejected with
        `ERR_TUTOR_SUBJECT_NOT_APPROVED`."
        PRD §3.3: "Revoking an `APPROVED` tag moves it to `REVOKED` ... and blocks
        future bookings on that tutor-and-subject pair".

        Design: Difficulty/priority_pair_validation_conflict/subject_not_approved_beats_insufficient_balance_on_booking
        """
        set_clock("2026-06-01T00:00:00Z")
        subject = create_subject()
        tutor, _ = create_verified_tutor(subject["id"], base_hourly_rate_cents=6000)
        tag = propose_and_approve_tag(tutor["id"], subject["id"])
        validate_success(api.revoke_subject_tag(tag["id"], OFFICER))  # tag now REVOKED
        parent = create_funded_parent(0)  # empty wallet
        p_headers = make_parent_headers(parent["id"])
        student = create_student(parent["id"])
        resp = api.create_booking(
            {
                "parent_account_id": parent["id"], "student_id": student["id"],
                "tutor_id": tutor["id"], "subject_id": subject["id"],
                "scheduled_start": "2026-06-02T10:00:00Z", "planned_minutes": 60,
            },
            p_headers,
        )
        # Referential (no APPROVED tag) is reported, not the fiscal shortfall.
        validate_error(resp, ApiErrorId.ERR_TUTOR_SUBJECT_NOT_APPROVED.value)


class TestBookingLifecycleCorners:
    def test_cancel_after_lesson_time_rejected(self, api):
        """PRD §3.6: "Cancellation is permitted while the booking is `SCHEDULED` or
        `RESCHEDULE_REQUESTED` and while the current clock is still earlier than
        `scheduled_start`".

        Design: Corner/state_machines/cancel_after_lesson_time_rejected_invalid_state
        """
        mk = setup_marketplace(base_hourly_rate_cents=6000)
        booking = create_booking(mk, "2026-06-02T10:00:00Z", planned_minutes=30)
        set_clock("2026-06-02T11:00:00Z")  # clock now past scheduled_start
        resp = api.cancel_booking(booking["id"], mk["parent_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        booking_after = validate_success(api.get_booking(booking["id"], mk["parent_headers"]))
        assert booking_after["status"] == "SCHEDULED"

    def test_no_show_releases_hold_and_penalizes_reliability(self, api):
        """PRD §3.6: "Marking a no-show is allowed only when the booking is
        `SCHEDULED` and the current clock is at or past `scheduled_start`; it moves
        the booking to `NO_SHOW`, releases the parent's wallet hold, and applies an
        acute reliability penalty to the tutor".
        PRD §3.10: "the system subtracts an acute penalty equal to 8 times the
        tutor's no-show count".

        Design: Corner/state_machines/no_show_releases_hold_and_penalizes_reliability
        """
        mk = setup_marketplace(base_hourly_rate_cents=6000, wallet_cents=100000)
        # One confirmed trial session establishes reliability from one confirmed session.
        trial_booking = create_booking(mk, "2026-06-02T08:00:00Z", planned_minutes=30)
        trial_session = deliver_booking(mk, trial_booking["id"], 30, "2026-06-02T09:00:00Z")
        validate_success(api.confirm_session(trial_session["id"], mk["parent_headers"]))
        # Second booking will be a no-show.
        ns_booking = create_booking(mk, "2026-06-03T10:00:00Z", planned_minutes=60)
        set_clock("2026-06-03T11:00:00Z")
        no_show = validate_success(api.mark_no_show(ns_booking["id"], mk["tutor_headers"]))
        assert no_show["status"] == "NO_SHOW"

        parent = validate_success(api.get_parent_account(mk["parent"]["id"], mk["parent_headers"]))
        assert parent["held_balance_cents"] == 0
        tutor = validate_success(api.get_tutor(mk["tutor"]["id"], mk["parent_headers"]))
        # chronic = 100 * 1 / (1 + 1) = 50; minus 8 no-show penalty = 42.0.
        assert tutor["reliability_score"] == 42.0

    def test_reschedule_request_then_confirm_updates_start(self, api):
        """PRD §3.6: "the request supplies a `proposed_start` and moves the booking
        from `SCHEDULED` to `RESCHEDULE_REQUESTED`, incrementing `reschedule_count`."
        PRD §3.6: "The tutor then confirms the reschedule, which supplies the
        `proposed_start`, moves the booking from `RESCHEDULE_REQUESTED` back to
        `SCHEDULED`, updates `scheduled_start` to the proposed instant, recomputes
        `hold_amount_cents`".

        Design: Corner/state_machines/reschedule_request_then_confirm_updates_start_and_rehold
        """
        mk = setup_marketplace(base_hourly_rate_cents=6000)
        # Burn the (student, tutor) trial slot first so the booking under test is a
        # *standard* booking: PRD §3.5 caps trial holds at trial_max_billed_minutes
        # (30), which would mask the standard quoted_rate * planned_minutes / 60
        # rehold this test exercises.
        consume_trial_slot(mk)
        booking = create_booking(mk, "2026-06-02T10:00:00Z", planned_minutes=60)
        requested = validate_success(
            api.request_reschedule(booking["id"], {"proposed_start": "2026-06-04T10:00:00Z"}, mk["parent_headers"])
        )
        assert requested["status"] == "RESCHEDULE_REQUESTED"
        assert requested["reschedule_count"] == 1

        confirmed = validate_success(
            api.confirm_reschedule(booking["id"], {"proposed_start": "2026-06-04T10:00:00Z"}, mk["tutor_headers"])
        )
        assert confirmed["status"] == "SCHEDULED"
        # PRD §3.6 pins the *instant* scheduled_start is updated to, not its
        # serialization (the system may render UTC instants with or without the
        # three fractional digits used for created_at/updated_at). Compare the
        # parsed instant so the assertion tracks the PRD-stated rule.
        from datetime import datetime, timezone

        def _instant(s: str) -> datetime:
            s = s.replace("Z", "+00:00")
            return datetime.fromisoformat(s).astimezone(timezone.utc)

        assert _instant(confirmed["scheduled_start"]) == _instant("2026-06-04T10:00:00Z")
        assert confirmed["hold_amount_cents"] == 6000

    def test_dispute_keeps_settlement_open_no_settlement(self, api):
        """PRD §3.7: "Disputing the delivery instead moves the session's
        `delivery_status` from `REPORTED` to `DISPUTED` while leaving
        `settlement_status` at `DELIVERED`; this opens a refund-eligible window
        without auto-settling the session."

        Design: Corner/state_machines/session_dispute_keeps_settlement_open
        """
        mk = setup_marketplace(base_hourly_rate_cents=6000)
        booking = create_booking(mk, "2026-06-02T10:00:00Z", planned_minutes=30)
        session = deliver_booking(mk, booking["id"], 30, "2026-06-02T11:00:00Z")
        disputed = validate_success(api.dispute_session(session["id"], mk["parent_headers"]))
        assert disputed["delivery_status"] == "DISPUTED"
        assert disputed["settlement_status"] == "DELIVERED"
        tutor = validate_success(api.get_tutor(mk["tutor"]["id"], mk["parent_headers"]))
        assert tutor["payout_balance_cents"] == 0

    def test_list_bookings_pagination_envelope(self, api):
        """PRD §2.3: "The `meta` block of a list response carries the pagination
        fields `limit`, `offset`, `total_count` (the total number of rows matching
        the filter, ignoring pagination), and `has_more` (true when rows remain
        beyond the current page)."

        Design: Corner/endpoints/list_bookings_pagination_envelope
        """
        mk = setup_marketplace(base_hourly_rate_cents=6000)
        create_booking(mk, "2026-06-02T10:00:00Z", planned_minutes=30)
        create_booking(mk, "2026-06-02T12:00:00Z", planned_minutes=30)
        resp = api.list_bookings(mk["parent_headers"], params={"parent_account_id": mk["parent"]["id"], "limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
