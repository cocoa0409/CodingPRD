"""504/IEP accommodation review queue: the MORE_INFO cycle, approval binding +
pool movement + minutes recompute, eligibility / bindability / capacity /
schedule gates (PRD §3.4, §3.5)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    make_candidate_headers,
    fixtures, factories,
)

REVIEWER = TEST_USERS["accommodation_reviewer_headers"]


class TestReviewCycle:
    def test_more_info_cycle_back_to_review_then_approve(self, api):
        """PRD §3.4: "From UNDER_REVIEW the reviewer may request more
        documentation, supplying a reviewer_note and moving the request to
        MORE_INFO_NEEDED; from MORE_INFO_NEEDED the candidate resubmits to send the
        request back to UNDER_REVIEW, and this MORE_INFO_NEEDED → UNDER_REVIEW
        cycle may repeat." PRD §3.5: "Approving an accommodation request is only
        possible from UNDER_REVIEW and only when several binding conditions hold
        together."

        Design: Difficulty/non_linear_state_machine/accommodation_more_info_cycle_back_to_review
        """
        center, candidate, session, reg, acc = fixtures.create_accommodation_under_review(
            "EXTENDED_TIME_50", "PLAN_504",
        )
        # request-info -> MORE_INFO_NEEDED
        mi = validate_success(api.request_info_accommodation(
            acc["id"], factories.request_info_payload("Need current evaluation"), REVIEWER))
        assert mi["status"] == "MORE_INFO_NEEDED"
        # resubmit -> back to UNDER_REVIEW (cycle edge)
        ur = validate_success(api.resubmit_accommodation(acc["id"], make_candidate_headers(candidate["id"])))
        assert ur["status"] == "UNDER_REVIEW"
        # approve from the re-entered UNDER_REVIEW
        approved = validate_success(api.approve_accommodation(acc["id"], REVIEWER))
        assert approved["status"] == "APPROVED"
        reg_after = get_success_data(api.get_registration(reg["id"], TEST_USERS["candidate_headers"]))
        assert reg_after["seat_kind"] == "ACCOMMODATED"

    def test_more_info_cycle_status_progression(self, api):
        """PRD §3.4: "From UNDER_REVIEW the reviewer may request more
        documentation, supplying a reviewer_note and moving the request to
        MORE_INFO_NEEDED; from MORE_INFO_NEEDED the candidate resubmits to send the
        request back to UNDER_REVIEW, and this MORE_INFO_NEEDED → UNDER_REVIEW
        cycle may repeat."

        Design: Difficulty/non_linear_state_machine/accommodation_more_info_cycle_back_to_review
        """
        center, candidate, session, reg, acc = fixtures.create_accommodation_under_review(
            "EXTENDED_TIME_50", "PLAN_504",
        )
        validate_success(api.request_info_accommodation(
            acc["id"], factories.request_info_payload("Docs please"), REVIEWER))
        ur = validate_success(api.resubmit_accommodation(acc["id"], make_candidate_headers(candidate["id"])))
        assert ur["status"] == "UNDER_REVIEW", "cycle returns the request to review"


class TestApprovalCascade:
    def test_approve_binds_seat_and_recomputes_minutes_extended_100(self, api):
        """PRD §3.5: "It binds the registration to this request by setting the
        registration's accommodation_request_id to this request's id and flipping
        seat_kind to ACCOMMODATED." PRD §3.5: "It moves the seat between pools on
        the host session — reducing standard_seats_reserved by one and raising
        accommodated_seats_reserved by one — and increments the session version."
        PRD §3.5: "EXTENDED_TIME_100 multiplies it by 2.0, while SEPARATE_ROOM and
        BREAKS_ONLY leave the base unchanged at a multiplier of 1.0."

        Design: Difficulty/transitive_cascade/accommodation_approve_binds_seat_and_recomputes_minutes_depth2
        """
        center, candidate, session, reg, acc = fixtures.create_accommodation_under_review(
            "EXTENDED_TIME_100", "IEP",
        )
        validate_success(api.approve_accommodation(acc["id"], REVIEWER))
        reg_after = get_success_data(api.get_registration(reg["id"], TEST_USERS["candidate_headers"]))
        assert reg_after["seat_kind"] == "ACCOMMODATED"
        assert reg_after["allotted_minutes"] == 268, "134 * 2.0 = 268"
        sess_after = get_success_data(api.get_test_session(session["id"], TEST_USERS["candidate_headers"]))
        assert sess_after["standard_seats_reserved"] == 0
        assert sess_after["accommodated_seats_reserved"] == 1

    def test_approve_binds_request_id_and_recomputes_minutes_act(self, api):
        """PRD §3.5: "It binds the registration to this request by setting the
        registration's accommodation_request_id to this request's id and flipping
        seat_kind to ACCOMMODATED." PRD §3.5: "And it recomputes the registration's
        allotted_minutes from the approved accommodation, a depth-two cascade onto
        the bound registration." PRD §3.5: "The granted-minutes computation starts
        from a base minute count fixed by the session's exam_type: 134 minutes for
        SAT, 175 minutes for ACT, and 180 minutes for AP."

        Design: Difficulty/transitive_cascade/accommodation_approve_binds_seat_and_recomputes_minutes_depth2
        """
        center, candidate, session, reg, acc = fixtures.create_accommodation_under_review(
            "EXTENDED_TIME_100", "IEP",
            session_overrides={"exam_type": "ACT"},
        )
        validate_success(api.approve_accommodation(acc["id"], REVIEWER))
        reg_after = get_success_data(api.get_registration(reg["id"], TEST_USERS["candidate_headers"]))
        assert reg_after["accommodation_request_id"] == acc["id"], "registration bound to the request"
        assert reg_after["seat_kind"] == "ACCOMMODATED"
        assert reg_after["allotted_minutes"] == 350, "175 * 2.0 = 350 (depth-2 minutes recompute)"

    def test_approve_recomputes_minutes_extended_50_sat(self, api):
        """PRD §3.5: "The granted-minutes computation starts from a base minute
        count fixed by the session's exam_type: 134 minutes for SAT, 175 minutes
        for ACT, and 180 minutes for AP." PRD §3.5: "EXTENDED_TIME_50 multiplies
        the base by 1.5, EXTENDED_TIME_100 multiplies it by 2.0, while
        SEPARATE_ROOM and BREAKS_ONLY leave the base unchanged at a multiplier of
        1.0."

        Design: Corner/calculations/allotted_minutes_extended_time_50_sat
        """
        center, candidate, session, reg, acc = fixtures.create_accommodation_under_review(
            "EXTENDED_TIME_50", "PLAN_504",
        )
        validate_success(api.approve_accommodation(acc["id"], REVIEWER))
        reg_after = get_success_data(api.get_registration(reg["id"], TEST_USERS["candidate_headers"]))
        assert reg_after["allotted_minutes"] == 201, "floor(134 * 1.5) = 201"


class TestCheckInCrossEntity:
    def test_checkin_succeeds_with_approved_accommodation_and_match_id(self, api):
        """PRD §3.3: "Second, if the registration's seat_kind is ACCOMMODATED, its
        bound accommodation request must have reached status APPROVED." PRD §3.3:
        "there must already exist an identity verification for this registration
        whose outcome is MATCH; a check-in attempted without such a passing
        verification on file is rejected with ERR_ID_VERIFICATION_FAILED."

        Design: Difficulty/cross_entity_state_dependency/checkin_requires_approved_accommodation_when_accommodated
        """
        center, candidate, session, reg, acc = fixtures.create_approved_accommodation(
            "SEPARATE_ROOM", "PLAN_504",
        )
        # Confirm then verify ID then check in.
        fixtures.confirm_registration(reg["id"], candidate["id"])
        fixtures.record_id_verification(reg["id"], "Ada", "Lovelace", "CA")
        checked = validate_success(api.check_in_registration(reg["id"], TEST_USERS["test_center_admin_headers"]))
        assert checked["lifecycle_status"] == "CHECKED_IN"
        assert checked["seat_kind"] == "ACCOMMODATED"

    def test_accommodated_checkin_path_reaches_checked_in(self, api):
        """PRD §3.3: "On test day the center operator checks a candidate in,
        advancing the registration from CONFIRMED to CHECKED_IN."

        Design: Difficulty/cross_entity_state_dependency/checkin_requires_approved_accommodation_when_accommodated
        """
        center, candidate, session, reg, acc = fixtures.create_approved_accommodation(
            "EXTENDED_TIME_50", "IEP",
        )
        fixtures.confirm_registration(reg["id"], candidate["id"])
        fixtures.record_id_verification(reg["id"], "Ada", "Lovelace", "CA")
        checked = validate_success(api.check_in_registration(reg["id"], TEST_USERS["test_center_admin_headers"]))
        assert checked["lifecycle_status"] == "CHECKED_IN"


class TestScheduleAndCapacityGates:
    def test_accommodated_schedule_rest_buffer_conflict(self, api):
        """PRD §3.5: "The required gap is measured from the earlier sitting's
        window_end_utc to the later sitting's window_start_utc, and that gap must
        be at least 3 hours. A gap of less than 3 hours — including windows that
        overlap or that sit exactly back to back — is rejected with
        ERR_CANDIDATE_SCHEDULE_CONFLICT at the moment the approval would make the
        second sitting accommodated."

        Design: Difficulty/resource_temporal_overlap/candidate_accommodated_schedule_rest_buffer_conflict
        """
        center = fixtures.create_center()
        candidate = fixtures.create_candidate(legal_first_name="Ivy", legal_last_name="Stone",
                                              has_active_504_iep=True)
        cid = candidate["id"]
        s1 = fixtures.create_session(center["id"], exam_type="SAT", test_date="2026-09-01",
                                     window_start_utc="2026-09-01T08:00:00.000Z",
                                     window_end_utc="2026-09-01T12:00:00.000Z")
        s2 = fixtures.create_session(center["id"], exam_type="ACT", test_date="2026-09-01",
                                     window_start_utc="2026-09-01T12:00:00.000Z",
                                     window_end_utc="2026-09-01T16:00:00.000Z", base_fee_cents=7000)
        reg1 = fixtures.create_registration(s1["id"], cid, s1["version"])
        reg2 = fixtures.create_registration(s2["id"], cid, s2["version"])
        acc1 = get_success_data(api.create_accommodation_request(
            factories.create_accommodation_request_payload(cid, reg1["id"], "EXTENDED_TIME_100", "IEP"),
            make_candidate_headers(cid)))
        validate_success(api.begin_review_accommodation(acc1["id"], REVIEWER))
        validate_success(api.approve_accommodation(acc1["id"], REVIEWER))
        acc2 = get_success_data(api.create_accommodation_request(
            factories.create_accommodation_request_payload(cid, reg2["id"], "EXTENDED_TIME_100", "IEP"),
            make_candidate_headers(cid)))
        validate_success(api.begin_review_accommodation(acc2["id"], REVIEWER))
        # Gap between s1 end (12:00) and s2 start (12:00) is 0h < 3h buffer.
        resp = api.approve_accommodation(acc2["id"], REVIEWER)
        validate_error(resp, ApiErrorId.ERR_CANDIDATE_SCHEDULE_CONFLICT.value)

    def test_accommodated_schedule_exactly_3h_gap_allowed(self, api):
        """PRD §3.5: "The required gap is measured from the earlier sitting's
        window_end_utc to the later sitting's window_start_utc, and that gap must
        be at least 3 hours." PRD §3.5: "It moves the seat between pools on the
        host session — reducing standard_seats_reserved by one and raising
        accommodated_seats_reserved by one — and increments the session version."

        Design: Difficulty/resource_temporal_overlap/candidate_accommodated_schedule_rest_buffer_conflict
        """
        # Earlier window ends 12:00, later starts 15:00 -> exactly 3h gap, which
        # satisfies the "at least 3 hours" rule, so the second approval succeeds.
        center = fixtures.create_center()
        candidate = fixtures.create_candidate(legal_first_name="Ivy", legal_last_name="Stone",
                                              has_active_504_iep=True)
        cid = candidate["id"]
        s1 = fixtures.create_session(center["id"], exam_type="SAT", test_date="2026-09-01",
                                     window_start_utc="2026-09-01T08:00:00.000Z",
                                     window_end_utc="2026-09-01T12:00:00.000Z")
        s2 = fixtures.create_session(center["id"], exam_type="ACT", test_date="2026-09-01",
                                     window_start_utc="2026-09-01T15:00:00.000Z",
                                     window_end_utc="2026-09-01T19:00:00.000Z", base_fee_cents=7000)
        reg1 = fixtures.create_registration(s1["id"], cid, s1["version"])
        reg2 = fixtures.create_registration(s2["id"], cid, s2["version"])
        acc1 = get_success_data(api.create_accommodation_request(
            factories.create_accommodation_request_payload(cid, reg1["id"], "EXTENDED_TIME_100", "IEP"),
            make_candidate_headers(cid)))
        validate_success(api.begin_review_accommodation(acc1["id"], REVIEWER))
        validate_success(api.approve_accommodation(acc1["id"], REVIEWER))
        acc2 = get_success_data(api.create_accommodation_request(
            factories.create_accommodation_request_payload(cid, reg2["id"], "EXTENDED_TIME_100", "IEP"),
            make_candidate_headers(cid)))
        validate_success(api.begin_review_accommodation(acc2["id"], REVIEWER))
        approved2 = validate_success(api.approve_accommodation(acc2["id"], REVIEWER))
        assert approved2["status"] == "APPROVED", "exactly 3h gap meets the buffer"

    def test_accommodated_pool_full_blocks_approval(self, api):
        """PRD §3.5: "The accommodated pool must have room: the session's
        accommodated_seats_reserved must be below the center's
        room_capacity_accommodated, otherwise the approval cannot move the seat
        and is rejected with ERR_ACCOMMODATED_FULL."

        Design: Corner/validations/accommodated_pool_full_blocks_approval
        """
        center = fixtures.create_center(name="Acc Center", room_capacity_standard=50,
                                       room_capacity_accommodated=1)
        cand1 = fixtures.create_candidate(legal_first_name="Acc", legal_last_name="One",
                                         has_active_504_iep=True)
        cand2 = fixtures.create_candidate(legal_first_name="Acc", legal_last_name="Two",
                                         has_active_504_iep=True)
        session = fixtures.create_session(center["id"])
        reg1 = fixtures.create_registration(session["id"], cand1["id"], session["version"])
        sess_after_1 = get_success_data(api.get_test_session(session["id"], TEST_USERS["candidate_headers"]))
        reg2 = fixtures.create_registration(session["id"], cand2["id"], sess_after_1["version"])
        acc1 = get_success_data(api.create_accommodation_request(
            factories.create_accommodation_request_payload(cand1["id"], reg1["id"], "SEPARATE_ROOM", "PLAN_504"),
            make_candidate_headers(cand1["id"])))
        validate_success(api.begin_review_accommodation(acc1["id"], REVIEWER))
        validate_success(api.approve_accommodation(acc1["id"], REVIEWER))  # fills the only accommodated seat
        acc2 = get_success_data(api.create_accommodation_request(
            factories.create_accommodation_request_payload(cand2["id"], reg2["id"], "SEPARATE_ROOM", "IEP"),
            make_candidate_headers(cand2["id"])))
        validate_success(api.begin_review_accommodation(acc2["id"], REVIEWER))
        resp = api.approve_accommodation(acc2["id"], REVIEWER)
        validate_error(resp, ApiErrorId.ERR_ACCOMMODATED_FULL.value)

    def test_approve_on_checked_in_registration_not_bindable(self, api):
        """PRD §3.5: "The target registration must still be bindable — not yet
        CHECKED_IN, with its lifecycle status being RESERVED or CONFIRMED, and
        owned by the requesting candidate; a target that is already checked in or
        that belongs to a different candidate is rejected with
        ERR_ACCOMMODATION_NOT_BINDABLE."

        Design: Corner/validations/approve_accommodation_on_checked_in_not_bindable
        """
        center, candidate, session, reg = fixtures.create_checked_in_registration(
            candidate_overrides={"has_active_504_iep": True},
        )
        cid = candidate["id"]
        acc = get_success_data(api.create_accommodation_request(
            factories.create_accommodation_request_payload(cid, reg["id"], "EXTENDED_TIME_50", "PLAN_504"),
            make_candidate_headers(cid)))
        validate_success(api.begin_review_accommodation(acc["id"], REVIEWER))
        resp = api.approve_accommodation(acc["id"], REVIEWER)
        validate_error(resp, ApiErrorId.ERR_ACCOMMODATION_NOT_BINDABLE.value)


class TestEligibilityAndTerminal:
    def test_begin_review_rejected_when_504_flag_defaulted_false(self, api):
        """PRD §3.2: "A candidate may also declare has_active_504_iep, a boolean
        that defaults to false when omitted and that gates all accommodation
        eligibility downstream." PRD §3.4: "A candidate without an active 504 plan
        or IEP cannot have a request opened, and the attempt is rejected with
        ERR_NOT_504_IEP_ELIGIBLE."

        Design: Corner/entities/candidate_default_504_flag_false_when_omitted
        """
        center, candidate, session, reg = fixtures.create_reserved_registration(
            candidate_overrides={"legal_first_name": "Noa", "legal_last_name": "Plan"},
        )
        cid = candidate["id"]
        assert candidate["has_active_504_iep"] is False, "flag defaulted false when omitted"
        acc = get_success_data(api.create_accommodation_request(
            factories.create_accommodation_request_payload(cid, reg["id"], "EXTENDED_TIME_50", "PLAN_504"),
            make_candidate_headers(cid)))
        resp = api.begin_review_accommodation(acc["id"], REVIEWER)
        validate_error(resp, ApiErrorId.ERR_NOT_504_IEP_ELIGIBLE.value)

    def test_deny_on_approved_terminal_invalid_state(self, api):
        """PRD §3.4: "Both deny and approve are permitted only from UNDER_REVIEW."
        PRD §3.4: "Each of these transitions is allowed only from its stated source
        status; an attempt from any other status is rejected with
        ERR_INVALID_STATE."

        Design: Corner/state_machines/deny_from_terminal_approved_locked
        """
        center, candidate, session, reg, acc = fixtures.create_approved_accommodation(
            "EXTENDED_TIME_50", "PLAN_504",
        )
        assert acc["status"] == "APPROVED"
        resp = api.deny_accommodation(acc["id"], factories.deny_payload("too late"), REVIEWER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
