"""Session booking gates: STUDIO half-open overlap, REMOTE buffer boundary,
the overlap-vs-inactive priority pair, engineer-inactive, invalid window, and
suspended-show booking. Covers difficulty rules resource_temporal_overlap
(studio), boundary_precision_check (remote buffer), priority_pair_validation_conflict
(temporal vs constraint), plus corner errors/validations instances.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    make_producer_eng_headers,
    make_platform_admin_headers,
    ApiErrorId,
    create_show_with_active_contract,
    create_engineer,
    create_episode,
    create_session_payload,
    book_session,
    set_clock,
)

ADMIN = make_platform_admin_headers()


class TestStudioOverlap:
    def test_overlapping_studio_session_rejected(self, api):
        """PRD §3.3: "For a STUDIO booking, the window must not overlap any non-CANCELLED
        STUDIO session already held by the same engineer. Overlap is judged on the
        half-open interval, so two windows that merely touch at an endpoint — one ending
        exactly where the next begins — are allowed; any true overlap is rejected with
        ERR_SESSION_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/studio_session_half_open_overlap_touch_allowed
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        engineer = create_engineer(name="Eng G")
        eng = make_producer_eng_headers(engineer["id"])
        ep1 = create_episode(show["id"], contract["id"], planned_track_count=1, title="G1")
        ep3 = create_episode(show["id"], contract["id"], planned_track_count=1, title="G3")
        book_session(ep1["id"], engineer["id"],
                     "2026-03-05T10:00:00Z", "2026-03-05T12:00:00Z")

        resp = api_client.create_session(create_session_payload(
            ep3["id"], engineer["id"],
            "2026-03-05T11:00:00Z", "2026-03-05T11:30:00Z", capture_mode="STUDIO"), eng)
        validate_error(resp, ApiErrorId.ERR_SESSION_OVERLAP.value)

    def test_touching_studio_session_allowed(self, api):
        """PRD §3.3: "two windows that merely touch at an endpoint — one ending exactly
        where the next begins — are allowed; any true overlap is rejected with
        ERR_SESSION_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/studio_session_half_open_overlap_touch_allowed
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        engineer = create_engineer(name="Eng G2")
        eng = make_producer_eng_headers(engineer["id"])
        ep1 = create_episode(show["id"], contract["id"], planned_track_count=1, title="G1")
        ep2 = create_episode(show["id"], contract["id"], planned_track_count=1, title="G2")
        book_session(ep1["id"], engineer["id"],
                     "2026-03-05T10:00:00Z", "2026-03-05T12:00:00Z")

        touch = validate_success(api_client.create_session(create_session_payload(
            ep2["id"], engineer["id"],
            "2026-03-05T12:00:00Z", "2026-03-05T13:00:00Z", capture_mode="STUDIO"), eng),
            expected_status=201)
        assert touch["status"] == "BOOKED", "touch at endpoint allowed (no buffer)"


class TestRemoteBuffer:
    def test_remote_gap_exactly_buffer_allowed(self, api):
        """PRD §3.3: "For a REMOTE booking, the new window must be separated from every
        non-CANCELLED REMOTE session of the same engineer by at least that engineer's
        remote_buffer_minutes: the start of the later session must be at or after the end
        of the earlier session plus the buffer. A gap exactly equal to the buffer is
        allowed; a smaller gap is rejected with ERR_REMOTE_BUFFER_VIOLATION."

        Design: Difficulty/boundary_precision_check/remote_buffer_exact_gap_allowed_zero_violation
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        engineer = create_engineer(name="Eng H", remote_buffer_minutes=30)
        eng = make_producer_eng_headers(engineer["id"])
        ep1 = create_episode(show["id"], contract["id"], planned_track_count=1, title="R1")
        ep2 = create_episode(show["id"], contract["id"], planned_track_count=1, title="R2")
        book_session(ep1["id"], engineer["id"],
                     "2026-03-04T10:00:00Z", "2026-03-04T11:00:00Z", capture_mode="REMOTE")

        # Earlier ends 11:00; later starts 11:30 == 11:00 + 30min buffer -> allowed.
        ok = validate_success(api_client.create_session(create_session_payload(
            ep2["id"], engineer["id"],
            "2026-03-04T11:30:00Z", "2026-03-04T12:30:00Z", capture_mode="REMOTE"), eng),
            expected_status=201)
        assert ok["status"] == "BOOKED", "gap == buffer is allowed"

    def test_remote_gap_below_buffer_rejected(self, api):
        """PRD §3.3: "A gap exactly equal to the buffer is allowed; a smaller gap is
        rejected with ERR_REMOTE_BUFFER_VIOLATION."

        Design: Difficulty/boundary_precision_check/remote_buffer_exact_gap_allowed_zero_violation
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        engineer = create_engineer(name="Eng H2", remote_buffer_minutes=30)
        eng = make_producer_eng_headers(engineer["id"])
        ep1 = create_episode(show["id"], contract["id"], planned_track_count=1, title="R1")
        ep2 = create_episode(show["id"], contract["id"], planned_track_count=1, title="R2")
        book_session(ep1["id"], engineer["id"],
                     "2026-03-04T10:00:00Z", "2026-03-04T11:00:00Z", capture_mode="REMOTE")

        # Earlier ends 11:00; later starts 11:29 -> 29-minute gap < 30 buffer -> reject.
        resp = api_client.create_session(create_session_payload(
            ep2["id"], engineer["id"],
            "2026-03-04T11:29:00Z", "2026-03-04T12:29:00Z", capture_mode="REMOTE"), eng)
        validate_error(resp, ApiErrorId.ERR_REMOTE_BUFFER_VIOLATION.value)


class TestOverlapVsInactivePriority:
    def test_overlap_wins_over_engineer_inactive(self, api):
        """PRD §3.3: "The owning show must be ACTIVE, or the booking fails with
        ERR_SHOW_NOT_ACTIVE. The chosen engineer must be active, or the booking fails with
        ERR_ENGINEER_INACTIVE. And the window must respect the engineer's capacity"
        PRD §2.8: "Among the state-and-business layer, transition legality is checked
        before concurrency and before the domain-specific business gates."

        The active engineer's overlapping window competes between the priority-24
        temporal overlap rule and the priority-29 inactive rule; the lower-priority
        temporal rule must win, returning ERR_SESSION_OVERLAP.

        Design: Difficulty/priority_pair_validation_conflict/temporal_overlap_vs_constraint_engineer_inactive_on_session
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        engineer = create_engineer(name="Eng Active")  # active=true
        eng = make_producer_eng_headers(engineer["id"])
        ep_prior = create_episode(show["id"], contract["id"], planned_track_count=1,
                                  title="Prior")
        ep_new = create_episode(show["id"], contract["id"], planned_track_count=1,
                                title="New")
        # Existing STUDIO booking [10:00,12:00) on the active engineer.
        book_session(ep_prior["id"], engineer["id"],
                     "2026-03-03T10:00:00Z", "2026-03-03T12:00:00Z")

        # New STUDIO window [11:00,13:00) overlaps the existing booking.
        resp = api_client.create_session(create_session_payload(
            ep_new["id"], engineer["id"],
            "2026-03-03T11:00:00Z", "2026-03-03T13:00:00Z", capture_mode="STUDIO"), eng)
        validate_error(resp, ApiErrorId.ERR_SESSION_OVERLAP.value)

    def test_inactive_engineer_alone_returns_inactive(self, api):
        """PRD §3.3: "The chosen engineer must be active, or the booking fails with
        ERR_ENGINEER_INACTIVE."

        Design: Difficulty/priority_pair_validation_conflict/temporal_overlap_vs_constraint_engineer_inactive_on_session
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        inactive = create_engineer(name="Eng Inactive", active=False)
        eng = make_producer_eng_headers(inactive["id"])
        episode = create_episode(show["id"], contract["id"], planned_track_count=1)
        # No overlap exists for the inactive engineer; the inactive rule fires alone.
        resp = api_client.create_session(create_session_payload(
            episode["id"], inactive["id"],
            "2026-03-03T10:00:00Z", "2026-03-03T12:00:00Z", capture_mode="STUDIO"), eng)
        validate_error(resp, ApiErrorId.ERR_ENGINEER_INACTIVE.value)


class TestBookingValidations:
    def test_inactive_engineer_booking_rejected(self, api):
        """PRD §3.3: "an optional active flag (defaulting to true) controlling whether the
        engineer accepts new bookings ... The chosen engineer must be active, or the
        booking fails with ERR_ENGINEER_INACTIVE."

        Design: Corner/errors/error_engineer_inactive_on_booking
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        engineer = create_engineer(name="Eng Off", active=False)
        eng = make_producer_eng_headers(engineer["id"])
        episode = create_episode(show["id"], contract["id"], planned_track_count=1)
        resp = api_client.create_session(create_session_payload(
            episode["id"], engineer["id"],
            "2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z", capture_mode="STUDIO"), eng)
        validate_error(resp, ApiErrorId.ERR_ENGINEER_INACTIVE.value)

    def test_session_end_not_after_start_rejected(self, api):
        """PRD §2.8: "a session's scheduled window must have its scheduled_end_utc strictly
        after its scheduled_start_utc ... either violation is rejected with
        ERR_INVALID_WINDOW."

        Design: Corner/validations/session_window_end_not_after_start_returns_invalid_window
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        engineer = create_engineer(name="Eng Wn")
        eng = make_producer_eng_headers(engineer["id"])
        episode = create_episode(show["id"], contract["id"], planned_track_count=1)
        resp = api_client.create_session(create_session_payload(
            episode["id"], engineer["id"],
            "2026-03-05T10:00:00Z", "2026-03-05T10:00:00Z", capture_mode="STUDIO"), eng)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)

    def test_book_session_on_suspended_show_rejected(self, api):
        """PRD §2.5: "Booking a session requires the owning show to be ACTIVE; a booking
        against a non-ACTIVE show is likewise rejected with ERR_SHOW_NOT_ACTIVE."
        PRD §3.1: "removing the last ACTIVE contract leaves no active contract, the posture
        typically falls to SUSPENDED."

        Design: Corner/validations/book_session_on_suspended_show_returns_show_not_active
        """
        show, contract = create_show_with_active_contract(
            tier="STANDARD", engagement_type="PER_EPISODE")
        engineer = create_engineer(name="Eng Sus")
        eng = make_producer_eng_headers(engineer["id"])
        episode = create_episode(show["id"], contract["id"], planned_track_count=1)
        # Terminate the only ACTIVE contract -> posture SUSPENDED.
        get_success_data(api_client.terminate_contract(
            contract["id"], {"expected_engagementcontract_version": contract["version"]},
            ADMIN))
        suspended = get_success_data(api_client.get_show(show["id"], ADMIN))
        assert suspended["production_posture"] == "SUSPENDED"

        resp = api_client.create_session(create_session_payload(
            episode["id"], engineer["id"],
            "2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z", capture_mode="STUDIO"), eng)
        validate_error(resp, ApiErrorId.ERR_SHOW_NOT_ACTIVE.value)
