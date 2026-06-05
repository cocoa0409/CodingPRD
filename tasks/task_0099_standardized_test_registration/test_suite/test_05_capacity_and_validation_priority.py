"""Capacity gates, validation-priority conflicts, the AP per-line fee settlement,
session-window overlap, and registration OCC (PRD §2.6, §2.9, §3.1, §3.3)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    make_candidate_headers,
    fixtures, factories,
)


class TestSessionFullBoundary:
    def test_second_registration_on_capacity_one_session_full(self, api):
        """PRD §3.3: "If the standard pool is already at capacity —
        standard_seats_reserved has reached room_capacity_standard, leaving no room
        for one more — the reservation is rejected with ERR_SESSION_FULL, and the
        candidate's recourse is to join standby instead."

        Design: Difficulty/boundary_precision_check/standard_pool_zero_free_seats_forces_session_full
        """
        center = fixtures.create_center(name="Tiny Center", state_code="NY",
                                       room_capacity_standard=1, room_capacity_accommodated=1)
        cand_a = fixtures.create_candidate(legal_first_name="First", legal_last_name="Taker",
                                          home_state_code="NY", id_document_state_code="NY")
        cand_b = fixtures.create_candidate(legal_first_name="Second", legal_last_name="Taker",
                                          home_state_code="NY", id_document_state_code="NY")
        session = fixtures.create_session(center["id"])
        reg_a = fixtures.create_registration(session["id"], cand_a["id"], session["version"])
        sess_after = get_success_data(api.get_test_session(session["id"], TEST_USERS["candidate_headers"]))
        resp = api.create_registration(
            factories.create_registration_payload(session["id"], cand_b["id"], sess_after["version"]),
            make_candidate_headers(cand_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_FULL.value)

    def test_registration_with_one_free_seat_below_capacity_succeeds(self, api):
        """PRD §3.3: "If the standard pool is already at capacity —
        standard_seats_reserved has reached room_capacity_standard, leaving no room
        for one more — the reservation is rejected with ERR_SESSION_FULL, and the
        candidate's recourse is to join standby instead."

        Design: Difficulty/boundary_precision_check/standard_pool_zero_free_seats_forces_session_full
        """
        # Capacity 2, one seat already taken -> one free seat (boundary just below
        # capacity): the second reservation must succeed, not be rejected as full.
        center = fixtures.create_center(name="Two Seater", state_code="NY",
                                       room_capacity_standard=2, room_capacity_accommodated=1)
        cand_a = fixtures.create_candidate(legal_first_name="First", legal_last_name="Taker",
                                          home_state_code="NY", id_document_state_code="NY")
        cand_b = fixtures.create_candidate(legal_first_name="Second", legal_last_name="Taker",
                                          home_state_code="NY", id_document_state_code="NY")
        session = fixtures.create_session(center["id"])
        fixtures.create_registration(session["id"], cand_a["id"], session["version"])
        sess_after = get_success_data(api.get_test_session(session["id"], TEST_USERS["candidate_headers"]))
        assert sess_after["standard_seats_reserved"] == 1, "one of two seats taken"
        resp = api.create_registration(
            factories.create_registration_payload(session["id"], cand_b["id"], sess_after["version"]),
            make_candidate_headers(cand_b["id"]),
        )
        reg_b = validate_success(resp, 201)
        assert reg_b["lifecycle_status"] == "RESERVED"

    def test_register_on_closed_session_rejected(self, api):
        """PRD §3.3: "A session whose registration_status is CLOSED cannot accept
        new registrations and is rejected with ERR_SESSION_CLOSED."

        Design: Corner/validations/register_on_closed_session_rejected
        """
        fixtures.set_clock("2026-06-01T00:00:00.000Z")
        center = fixtures.create_center(room_capacity_standard=5, room_capacity_accommodated=5)
        cand = fixtures.create_candidate(legal_first_name="Late", legal_last_name="Comer")
        session = fixtures.create_session(center["id"])
        fixtures.set_clock("2026-09-02T00:00:00.000Z")
        closed = get_success_data(api.close_test_session(session["id"], TEST_USERS["test_center_admin_headers"]))
        resp = api.create_registration(
            factories.create_registration_payload(session["id"], cand["id"], closed["version"]),
            make_candidate_headers(cand["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_CLOSED.value)


class TestValidationPriorityConflict:
    def test_double_cancel_state_check_beats_refund_window(self, api):
        """PRD §2.6: "then the state-validity check for the requested transition
        (ERR_INVALID_STATE), and only then the domain-specific business rules that
        follow." PRD §3.7: "a cancel attempted from any other lifecycle state is
        rejected with ERR_INVALID_STATE."

        Design: Difficulty/priority_pair_validation_conflict/cancel_terminal_state_beats_refund_window_state_vs_fiscal
        """
        fixtures.set_clock("2026-06-01T00:00:00.000Z")
        center, candidate, session, reg = fixtures.create_reserved_registration()
        cid = candidate["id"]
        validate_success(api.cancel_registration(reg["id"], make_candidate_headers(cid)))  # now CANCELLED
        fixtures.set_clock("2026-09-02T00:00:00.000Z")  # also past test_date (refund window closed)
        resp = api.cancel_registration(reg["id"], make_candidate_headers(cid))
        # State invalidity (priority 6) wins over the fiscal refund-window check (priority 15).
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_double_cancel_state_check_fires_even_in_open_refund_window(self, api):
        """PRD §2.6: "then the state-validity check for the requested transition
        (ERR_INVALID_STATE), and only then the domain-specific business rules that
        follow." PRD §3.7: "a cancel attempted from any other lifecycle state is
        rejected with ERR_INVALID_STATE."

        Design: Difficulty/priority_pair_validation_conflict/cancel_terminal_state_beats_refund_window_state_vs_fiscal
        """
        # First cancel lands in FULL tier (refund window wide open); the second
        # cancel must still fail on the state check, not a refund-window error,
        # confirming the state priority precedes the fiscal tier in every case.
        fixtures.set_clock("2026-01-01T00:00:00.000Z")  # far before test_date
        center, candidate, session, reg = fixtures.create_reserved_registration()
        cid = candidate["id"]
        first = validate_success(api.cancel_registration(reg["id"], make_candidate_headers(cid)))
        assert first["refund_tier"] == "FULL", "refund window open on the first cancel"
        resp = api.cancel_registration(reg["id"], make_candidate_headers(cid))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_checkin_id_failure_beats_capacity(self, api):
        """PRD §2.6: "Concretely, where they coincide on one operation,
        accommodation eligibility, identity-verification gating, bindability,
        window-overlap, candidate schedule separation, and session-closed checks
        are evaluated ahead of the standard-pool and accommodated-pool capacity
        checks, which in turn precede the refund-window check." PRD §3.3: "a
        check-in attempted without such a passing verification on file is rejected
        with ERR_ID_VERIFICATION_FAILED."

        Design: Difficulty/priority_pair_validation_conflict/id_verification_failed_beats_capacity_safety_vs_fiscal
        """
        center = fixtures.create_center(name="Tiny Center", state_code="NY",
                                       room_capacity_standard=1, room_capacity_accommodated=1)
        cand = fixtures.create_candidate(legal_first_name="Nora", legal_last_name="Real",
                                        home_state_code="NY", id_document_state_code="CA")
        session = fixtures.create_session(center["id"])
        reg = fixtures.create_registration(session["id"], cand["id"], session["version"])
        fixtures.confirm_registration(reg["id"], cand["id"])
        # Only a MISMATCH verification on file (wrong name).
        fixtures.record_id_verification(reg["id"], "Wrong", "Name", "CA")
        resp = api.check_in_registration(reg["id"], TEST_USERS["test_center_admin_headers"])
        # Safety (priority 8) fires; the full standard pool (priority 13) is never reached.
        validate_error(resp, ApiErrorId.ERR_ID_VERIFICATION_FAILED.value)

    def test_checkin_with_no_verification_on_full_session_fails_on_safety(self, api):
        """PRD §3.3: "there must already exist an identity verification for this
        registration whose outcome is MATCH; a check-in attempted without such a
        passing verification on file is rejected with ERR_ID_VERIFICATION_FAILED."
        PRD §2.6: "Concretely, where they coincide on one operation, accommodation
        eligibility, identity-verification gating, bindability, window-overlap,
        candidate schedule separation, and session-closed checks are evaluated
        ahead of the standard-pool and accommodated-pool capacity checks, which in
        turn precede the refund-window check."

        Design: Difficulty/priority_pair_validation_conflict/id_verification_failed_beats_capacity_safety_vs_fiscal
        """
        # Capacity-1 session full (the candidate's own seat), but NO IDVerification
        # at all on file. Check-in must surface the safety failure, not capacity.
        center = fixtures.create_center(name="Tiny Center", state_code="NY",
                                       room_capacity_standard=1, room_capacity_accommodated=1)
        cand = fixtures.create_candidate(legal_first_name="Una", legal_last_name="Verified",
                                        home_state_code="NY", id_document_state_code="NY")
        session = fixtures.create_session(center["id"])
        reg = fixtures.create_registration(session["id"], cand["id"], session["version"])
        fixtures.confirm_registration(reg["id"], cand["id"])
        resp = api.check_in_registration(reg["id"], TEST_USERS["test_center_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_ID_VERIFICATION_FAILED.value)


class TestAPFeeSettlement:
    def test_single_line_fee_reduction_rounds_half_up_per_line(self, api):
        """PRD §3.3: "for each line item, the captured amount is its base_fee_cents
        multiplied by one minus the fee_reduction_pct, and that per-line product is
        rounded half up to a whole cent." PRD §3.3: "A single-seat registration
        that is not an AP bundle is simply one line item under the same rule."

        Design: Difficulty/combinatorial_formula/ap_fee_per_line_round_then_sum_diverges_from_sum_then_round
        """
        # One SAT line item, base 10001, reduction 0.5: round_half_up(10001*0.5)=5001.
        center = fixtures.create_center()
        cand = fixtures.create_candidate()
        session = fixtures.create_session(center["id"], exam_type="SAT", base_fee_cents=10001)
        resp = api.create_registration(
            factories.create_registration_payload(session["id"], cand["id"], session["version"],
                                                  fee_reduction_pct=0.5),
            make_candidate_headers(cand["id"]),
        )
        reg = validate_success(resp, 201)
        assert reg["amount_paid_cents"] == 5001, "round_half_up(10001 * 0.5)"


class TestSessionWindowOverlap:
    def test_overlapping_window_same_center_same_date_rejected(self, api):
        """PRD §3.1: "the system forbids scheduling two sessions whose windows
        overlap at the same center on the same date; an overlapping create is
        rejected with ERR_SESSION_WINDOW_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/session_window_overlap_same_center_same_date_half_open
        """
        center = fixtures.create_center()
        fixtures.create_session(center["id"], exam_type="SAT", test_date="2026-09-01",
                                window_start_utc="2026-09-01T13:00:00.000Z",
                                window_end_utc="2026-09-01T17:00:00.000Z")
        resp = api.create_test_session(
            factories.create_test_session_payload(center["id"], exam_type="ACT", test_date="2026-09-01",
                                                  window_start_utc="2026-09-01T16:00:00.000Z",
                                                  window_end_utc="2026-09-01T20:00:00.000Z",
                                                  base_fee_cents=7000),
            TEST_USERS["test_center_admin_headers"],
        )
        # 16:00 < 17:00 overlaps the half-open [13:00, 17:00).
        validate_error(resp, ApiErrorId.ERR_SESSION_WINDOW_OVERLAP.value)

    def test_back_to_back_window_allowed(self, api):
        """PRD §3.1: "Because the window is half-open, two sessions that merely
        touch at a shared boundary instant do not overlap and are both allowed."

        Design: Difficulty/resource_temporal_overlap/session_window_overlap_same_center_same_date_half_open
        """
        center = fixtures.create_center()
        fixtures.create_session(center["id"], exam_type="SAT", test_date="2026-09-01",
                                window_start_utc="2026-09-01T13:00:00.000Z",
                                window_end_utc="2026-09-01T17:00:00.000Z")
        resp = api.create_test_session(
            factories.create_test_session_payload(center["id"], exam_type="ACT", test_date="2026-09-01",
                                                  window_start_utc="2026-09-01T17:00:00.000Z",
                                                  window_end_utc="2026-09-01T21:00:00.000Z",
                                                  base_fee_cents=7000),
            TEST_USERS["test_center_admin_headers"],
        )
        created = validate_success(resp, 201)
        assert created["window_start_utc"] == "2026-09-01T17:00:00.000Z"


class TestRegistrationOCC:
    def test_register_correct_version_succeeds_and_increments(self, api):
        """PRD §2.7: "Every operation that takes or releases a seat adjusts the
        matching counter by exactly one and increments the session's version by
        one, so that the counters and the version always move together."

        Design: Corner/cross_cutting_complexity_layers/occ_register_correct_version_succeeds_version_increments
        """
        center = fixtures.create_center(room_capacity_standard=5, room_capacity_accommodated=5)
        cand = fixtures.create_candidate()
        session = fixtures.create_session(center["id"])
        assert session["version"] == 1
        resp = api.create_registration(
            factories.create_registration_payload(session["id"], cand["id"], session["version"]),
            make_candidate_headers(cand["id"]),
        )
        validate_success(resp, 201)
        sess_after = get_success_data(api.get_test_session(session["id"], TEST_USERS["candidate_headers"]))
        assert sess_after["version"] == 2

    def test_register_stale_version_rejected(self, api):
        """PRD §2.9: "If the session's current version has advanced since then —
        because an intervening registration or a standby promotion already took the
        seat the client meant to take and bumped the version — the create is
        rejected with ERR_STALE_SESSION_VERSION (HTTP 412) rather than silently
        overbooking the session."

        Design: Corner/cross_cutting_complexity_layers/occ_register_stale_version_rejected_after_intervening_register
        """
        center = fixtures.create_center(room_capacity_standard=5, room_capacity_accommodated=5)
        cand_a = fixtures.create_candidate(legal_first_name="First", legal_last_name="Taker")
        cand_b = fixtures.create_candidate(legal_first_name="Second", legal_last_name="Taker")
        session = fixtures.create_session(center["id"])
        stale_version = session["version"]
        fixtures.create_registration(session["id"], cand_a["id"], stale_version)  # advances to v2
        resp = api.create_registration(
            factories.create_registration_payload(session["id"], cand_b["id"], stale_version),
            make_candidate_headers(cand_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_SESSION_VERSION.value)
