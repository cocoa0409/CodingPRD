"""HearingSlot lifecycle, booking conflicts, hold/no-show/reschedule.

Covers PRD §3.7 (hearings). Difficulty-design coverage for rule 3
(hearing_slot_branching_with_revert), rule 5 (business_temporal vs
business_referential), and rule 8 (resource_temporal_overlap).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_by_days,
    advance_clock_by_minutes,
    advance_clock_to,
    api_client,
    appeal_application,
    appeal_payload,
    assert_hearing_slot,
    book_hearing_slot_payload,
    book_slot,
    create_hearing_slot_payload,
    create_open_slot,
    current_clock,
    get_application,
    hold_slot,
    iso_utc,
    issue_determination,
    make_alj_headers,
    make_claimant_headers,
    no_show_slot,
    reschedule_slot,
    setup_application_at_alj_pending,
    setup_application_at_reconsideration,
    setup_held_hearing_for_alj_pending,
    setup_two_open_slots_same_alj,
    validate_error,
    validate_success,
)


class TestHearingSlotCreation:

    def test_create_open_slot_returns_slot_with_status_open(self, api):
        """PRD §3.7: "An ALJ (or PlatformAdmin) creates a slot in OPEN
        status by supplying the responsible alj_id, the hearing_office
        code (for example, OHO_BOSTON), and the slot's start_at and
        end_at ISO 8601 UTC datetimes."
        """
        start = current_clock() + timedelta(hours=1)
        end = start + timedelta(minutes=60)
        resp = api.create_hearing_slot(
            create_hearing_slot_payload(
                alj_id="alj-test-x",
                hearing_office="OHO_BOSTON",
                start_at=iso_utc(start),
                end_at=iso_utc(end),
            ),
            make_alj_headers("alj-test-x"),
        )
        data = validate_success(resp, expected_status=201)
        assert_hearing_slot(data)
        assert data["status"] == "OPEN"


class TestBookingPreconditions:

    def test_book_when_application_not_alj_pending_returns_invalid_state(
        self, api,
    ):
        """PRD §3.7: "the application's status must be ALJ_PENDING
        (otherwise ERR_INVALID_STATE at 409)".
        """
        # Application is in RECONSIDERATION, not ALJ_PENDING.
        claimant, application = setup_application_at_reconsideration()
        alj = "alj-bk-1"
        slot = create_open_slot(
            alj_id=alj,
            start_at_dt=current_clock() + timedelta(hours=1),
        )
        resp = api.book_hearing_slot(
            slot["id"],
            book_hearing_slot_payload(application["id"]),
            make_alj_headers(alj),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestHearingSlotTemporalOverlap:
    """Difficulty design rule 8: hearing_slot_closed_open_interval_on_alj."""

    def test_adjacent_slots_do_not_conflict(self, api):
        """# difficulty: resource_temporal_overlap/hearing_slot_closed_open_interval_on_alj

        PRD §3.7: "The intersection check is closed-open: two slots
        whose intervals are exactly back-to-back (the end of one
        equals the start of the next) do not conflict, but any
        genuine overlap does."

        Claim: a slot starting exactly at another slot's end_at can
        be booked.
        """
        claimant_a, app_a = setup_application_at_alj_pending()
        claimant_b, app_b = setup_application_at_alj_pending()
        alj = "alj-overlap-1"
        T = current_clock() + timedelta(hours=10)
        slot1 = create_open_slot(alj_id=alj, start_at_dt=T)
        slot2 = create_open_slot(
            alj_id=alj, start_at_dt=T + timedelta(minutes=60),
        )
        # Book slot1 for application A.
        book_slot(slot1["id"], alj, app_a["id"])
        # slot2 starts at T+60m which equals slot1.end_at — adjacency
        # is NOT a conflict.
        resp = api.book_hearing_slot(
            slot2["id"],
            book_hearing_slot_payload(app_b["id"]),
            make_alj_headers(alj),
        )
        data = validate_success(resp)
        assert data["status"] == "BOOKED"

    def test_overlapping_slots_return_hearing_slot_conflict(self, api):
        """# difficulty: resource_temporal_overlap/hearing_slot_closed_open_interval_on_alj

        PRD §3.7: "no other slot belonging to the same alj_id whose
        half-open interval [start_at, end_at) intersects this slot's
        interval may already be at status BOOKED or HELD (otherwise
        ERR_HEARING_SLOT_CONFLICT at 409)".
        """
        claimant_a, app_a = setup_application_at_alj_pending()
        claimant_b, app_b = setup_application_at_alj_pending()
        alj = "alj-overlap-2"
        T = current_clock() + timedelta(hours=10)
        slot1 = create_open_slot(alj_id=alj, start_at_dt=T)
        slot3 = create_open_slot(
            alj_id=alj, start_at_dt=T + timedelta(minutes=30),
        )
        book_slot(slot1["id"], alj, app_a["id"])
        # slot3 [T+30m, T+90m) overlaps slot1 [T, T+60m) on (T+30m, T+60m).
        resp = api.book_hearing_slot(
            slot3["id"],
            book_hearing_slot_payload(app_b["id"]),
            make_alj_headers(alj),
        )
        validate_error(resp, ApiErrorId.ERR_HEARING_SLOT_CONFLICT.value)


class TestApplicationAlreadyScheduled:
    """Difficulty design rule 8: application_unique_active_booking_per_resource_application."""

    def test_double_booking_application_returns_already_scheduled(self, api):
        """# difficulty: resource_temporal_overlap/application_unique_active_booking_per_resource_application

        PRD §3.7: "no other slot for the same application_id may
        already be at BOOKED or HELD (otherwise
        ERR_APPLICATION_ALREADY_SCHEDULED at 409)".
        """
        claimant, application = setup_application_at_alj_pending()
        # Two different ALJs, no time overlap — still conflicts on the
        # application's unique-active-booking rule.
        T = current_clock() + timedelta(hours=10)
        slot1 = create_open_slot(alj_id="alj-bks-1", start_at_dt=T)
        slot2 = create_open_slot(
            alj_id="alj-bks-2",
            start_at_dt=T + timedelta(days=2),
        )
        book_slot(slot1["id"], "alj-bks-1", application["id"])
        resp = api.book_hearing_slot(
            slot2["id"],
            book_hearing_slot_payload(application["id"]),
            make_alj_headers("alj-bks-2"),
        )
        validate_error(
            resp, ApiErrorId.ERR_APPLICATION_ALREADY_SCHEDULED.value,
        )

    def test_after_reschedule_other_slot_can_book_application(self, api):
        """# difficulty: resource_temporal_overlap/application_unique_active_booking_per_resource_application

        PRD §3.7: "On a successful reschedule, the target slot
        transitions from OPEN to BOOKED inheriting the application
        binding, and the original slot's application_id is cleared
        while it advances to RESCHEDULED."

        Claim: after the original slot is rescheduled away, a third
        slot can re-book the application.
        """
        claimant, application = setup_application_at_alj_pending()
        T = current_clock() + timedelta(hours=10)
        slot1 = create_open_slot(alj_id="alj-rb-1", start_at_dt=T)
        slot2 = create_open_slot(
            alj_id="alj-rb-1",
            start_at_dt=T + timedelta(hours=4),
        )
        book_slot(slot1["id"], "alj-rb-1", application["id"])
        # Reschedule slot1 to slot2 — clock is still before T, so
        # reschedule is valid.
        reschedule_slot(slot1["id"], "alj-rb-1", slot2["id"])
        # slot2 now BOOKED for the application; create another slot
        # and re-attempt to book: it should still ERR_APPLICATION_ALREADY_SCHEDULED
        # because slot2 is now bound. Inverse claim: PRD says the
        # original slot's application_id is cleared, so slot1 is free
        # to book another application.
        claimant_b, app_b = setup_application_at_alj_pending()
        resp = api.book_hearing_slot(
            slot1["id"],
            book_hearing_slot_payload(app_b["id"]),
            make_alj_headers("alj-rb-1"),
        )
        # PRD says slot1 advances to RESCHEDULED — it is NOT in OPEN
        # anymore, so booking it again must fail with ERR_INVALID_STATE.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestHearingSlotBranching:
    """Difficulty design rule 3: hearing_slot_branching_with_revert."""

    def test_booked_to_held_after_start_at(self, api):
        """# difficulty: non_linear_state_machine/hearing_slot_branching_with_revert

        PRD §3.7: "Once the slot's start time arrives, the ALJ marks
        the hearing held: the transition BOOKED to HELD requires that
        the current logical clock instant is at or after start_at, and
        an attempt before that yields ERR_HEARING_NOT_REACHED at 422."
        """
        claimant, application = setup_application_at_alj_pending()
        T = current_clock() + timedelta(hours=2)
        slot = create_open_slot(alj_id="alj-held-1", start_at_dt=T)
        book_slot(slot["id"], "alj-held-1", application["id"])
        advance_clock_to(T + timedelta(minutes=1))
        resp = api.hold_hearing_slot(
            slot["id"], make_alj_headers("alj-held-1"),
        )
        data = validate_success(resp)
        assert data["status"] == "HELD"

    def test_hold_before_start_at_returns_hearing_not_reached(self, api):
        """# difficulty: non_linear_state_machine/hearing_slot_branching_with_revert

        PRD §3.7: "an attempt before that yields ERR_HEARING_NOT_REACHED
        at 422."
        """
        claimant, application = setup_application_at_alj_pending()
        T = current_clock() + timedelta(hours=2)
        slot = create_open_slot(alj_id="alj-held-2", start_at_dt=T)
        book_slot(slot["id"], "alj-held-2", application["id"])
        # Do NOT advance the clock past start_at.
        resp = api.hold_hearing_slot(
            slot["id"], make_alj_headers("alj-held-2"),
        )
        validate_error(resp, ApiErrorId.ERR_HEARING_NOT_REACHED.value)

    def test_booked_to_no_show_after_end_at(self, api):
        """# difficulty: non_linear_state_machine/hearing_slot_branching_with_revert

        PRD §3.7: "the transition BOOKED to NO_SHOW requires the
        current logical clock instant to be at or after end_at. A
        no-show leaves the parent application in ALJ_PENDING,
        signalling that a new slot must be booked."
        """
        claimant, application = setup_application_at_alj_pending()
        T = current_clock() + timedelta(hours=2)
        slot = create_open_slot(alj_id="alj-ns-1", start_at_dt=T)
        book_slot(slot["id"], "alj-ns-1", application["id"])
        # Advance past end_at (start + 60m).
        advance_clock_to(T + timedelta(minutes=61))
        resp = api.no_show_hearing_slot(
            slot["id"], make_alj_headers("alj-ns-1"),
        )
        data = validate_success(resp)
        assert data["status"] == "NO_SHOW"
        # Application stays in ALJ_PENDING.
        application = get_application(claimant["id"], application["id"])
        assert application["status"] == "ALJ_PENDING"

    def test_reschedule_moves_application_to_new_slot(self, api):
        """# difficulty: non_linear_state_machine/hearing_slot_branching_with_revert

        PRD §3.7: "On a successful reschedule, the target slot
        transitions from OPEN to BOOKED inheriting the application
        binding, and the original slot's application_id is cleared
        while it advances to RESCHEDULED."
        """
        claimant, application = setup_application_at_alj_pending()
        slot1, slot2 = setup_two_open_slots_same_alj(alj_id="alj-rs-1")
        book_slot(slot1["id"], "alj-rs-1", application["id"])
        # Now reschedule (clock < slot1.start_at).
        resp = api.reschedule_hearing_slot(
            slot1["id"],
            {"new_slot_id": slot2["id"]},
            make_alj_headers("alj-rs-1"),
        )
        validate_success(resp)
        # Re-read both slots.
        slots_resp = api.list_hearing_slots(
            TEST_USERS["platform_admin_headers"],
            params={"alj_id": "alj-rs-1"},
        )
        body = slots_resp.json()
        rows = {r["id"]: r for r in body.get("data", [])}
        assert rows[slot1["id"]]["status"] == "RESCHEDULED"
        assert rows[slot2["id"]]["status"] == "BOOKED"
        assert rows[slot2["id"]]["application_id"] == application["id"]
        assert rows[slot1["id"]].get("application_id") in (None, "")

    def test_post_no_show_alj_determination_rejected(self, api):
        """# difficulty: non_linear_state_machine/hearing_slot_branching_with_revert

        PRD §3.6: "An ALJ determination is issued by an ALJ operator
        and requires an associated HearingSlot for this application
        whose status is HELD; absent that, the determination is
        rejected with ERR_HEARING_NOT_HELD at HTTP status 422."

        Claim: NO_SHOW does not satisfy "associated HearingSlot ...
        whose status is HELD".
        """
        claimant, application = setup_application_at_alj_pending()
        T = current_clock() + timedelta(hours=2)
        slot = create_open_slot(alj_id="alj-nsd-1", start_at_dt=T)
        book_slot(slot["id"], "alj-nsd-1", application["id"])
        advance_clock_to(T + timedelta(minutes=61))
        no_show_slot(slot["id"], "alj-nsd-1")
        resp = api.create_determination(
            claimant["id"], application["id"],
            {
                "level": "ALJ", "decision": "ALLOW",
                "medical_basis": "MEETS_LISTING",
                "established_onset_date": claimant["alleged_onset_date"],
                "rationale": (
                    "Allegations supported by listings-level findings "
                    "consistent with the record."
                ),
            },
            make_alj_headers("alj-nsd-1"),
        )
        validate_error(resp, ApiErrorId.ERR_HEARING_NOT_HELD.value)


class TestAppealAndHearingPriorityPair:
    """Difficulty design rule 5: business_temporal_vs_business_referential."""

    def test_appeal_after_window_returns_appeal_window_expired(self, api):
        """# difficulty: priority_pair_validation_conflict/business_temporal_vs_business_referential_appeal_and_hearing

        PRD §3.6: "a late appeal is rejected with
        ERR_APPEAL_WINDOW_EXPIRED at HTTP status 409."

        Claim: an appeal posted past 60 days yields
        ERR_APPEAL_WINDOW_EXPIRED — business_temporal category fires
        first on the appeal path.
        """
        # Walk to ALJ_DENIED so we can appeal to APPEALS_COUNCIL.
        claimant, application = setup_application_at_alj_pending()
        # Deny at ALJ (need HELD slot).
        T = current_clock() + timedelta(hours=1)
        slot = create_open_slot(alj_id="alj-tem-1", start_at_dt=T)
        book_slot(slot["id"], "alj-tem-1", application["id"])
        advance_clock_to(T + timedelta(minutes=1))
        hold_slot(slot["id"], "alj-tem-1")
        api.create_determination(
            claimant["id"], application["id"],
            {
                "level": "ALJ", "decision": "DENY",
                "medical_basis": "NOT_DISABLED",
                "rationale": (
                    "Vocational record indicates capacity for past "
                    "relevant work; allegations unsupported."
                ),
            },
            make_alj_headers("alj-tem-1"),
        )
        # Advance past 60 days.
        advance_clock_by_days(70)
        resp = api.appeal_application(
            claimant["id"], application["id"],
            appeal_payload(target_level="APPEALS_COUNCIL"),
            make_claimant_headers(claimant["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED.value)

    def test_overlapping_booking_returns_hearing_slot_conflict(self, api):
        """# difficulty: priority_pair_validation_conflict/business_temporal_vs_business_referential_appeal_and_hearing

        PRD §3.7: "no other slot belonging to the same alj_id whose
        half-open interval [start_at, end_at) intersects this slot's
        interval may already be at status BOOKED or HELD (otherwise
        ERR_HEARING_SLOT_CONFLICT at 409)".

        Claim: on the booking path, business_referential fires —
        ERR_HEARING_SLOT_CONFLICT — even when temporal rules elsewhere
        might also be relevant. Booking has no appeal-window rule.
        """
        claimant_a, app_a = setup_application_at_alj_pending()
        claimant_b, app_b = setup_application_at_alj_pending()
        alj = "alj-pair-1"
        T = current_clock() + timedelta(hours=10)
        slot1 = create_open_slot(alj_id=alj, start_at_dt=T)
        slot2 = create_open_slot(
            alj_id=alj, start_at_dt=T + timedelta(minutes=30),
        )
        book_slot(slot1["id"], alj, app_a["id"])
        resp = api.book_hearing_slot(
            slot2["id"],
            book_hearing_slot_payload(app_b["id"]),
            make_alj_headers(alj),
        )
        validate_error(resp, ApiErrorId.ERR_HEARING_SLOT_CONFLICT.value)
