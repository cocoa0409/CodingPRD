"""State-machine cycle and transition tests (PRD §3.4, §3.2)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_employee_headers,
    make_recruiter_headers,
    make_hiring_manager_headers,
    create_employee,
    create_open_requisition,
    create_active_policy,
    submit_referral,
    setup_program,
    advance_referral_to_offer,
    hire_referral,
    get_referral,
    create_referral_payload,
    api_client,
)


class TestReferralInfoRequestCycle:
    def test_info_request_cycle_loops_and_records_events(self, api):
        """PRD §3.4: "During review the recruiter may bounce the referral to `NEEDS_INFO`
        (event `REQUEST_INFO`) with an optional `note`, and the referral returns to
        `UNDER_REVIEW` when information is provided (event `PROVIDE_INFO`) — a step open
        to the recruiter, and also to the `Employee`-role referrer acting on their own
        referral. The `UNDER_REVIEW`–`NEEDS_INFO` cycle may repeat an unlimited number of
        times."

        Two full loop laps complete and the event log records each lap in order.

        Design: Difficulty/non_linear_state_machine/referral_info_request_cycle
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        rec_id = program["rec"]["id"]
        ref = submit_referral(emp["id"], program["req"]["id"], candidate_email="ca@x.com")
        rec_h = make_recruiter_headers(rec_id)

        get_success_data(api.review_referral(ref["id"], rec_h))
        # lap 1: REQUEST_INFO by recruiter, PROVIDE_INFO by the referrer (Employee)
        get_success_data(api.request_info_referral(ref["id"], rec_h, {"note": "need resume"}))
        get_success_data(
            api.provide_info_referral(ref["id"], make_employee_headers(emp["id"]), {"note": "attached"})
        )
        # lap 2: both steps by the recruiter
        get_success_data(api.request_info_referral(ref["id"], rec_h))
        get_success_data(api.provide_info_referral(ref["id"], rec_h))
        data = get_success_data(api.qualify_referral(ref["id"], rec_h))
        assert data["status"] == "QUALIFIED"

        events = get_success_data(api.list_referral_events(ref["id"], rec_h))
        assert [e["event_type"] for e in events] == [
            "SUBMIT", "REVIEW", "REQUEST_INFO", "PROVIDE_INFO",
            "REQUEST_INFO", "PROVIDE_INFO", "QUALIFY",
        ], f"event sequence mismatch: {[e['event_type'] for e in events]}"

    def test_info_request_cycle_second_request_info_from_under_review(self, api):
        """PRD §3.4: "The `UNDER_REVIEW`–`NEEDS_INFO` cycle may repeat an unlimited
        number of times."

        The second REQUEST_INFO succeeds from UNDER_REVIEW after the first lap — proving
        the cycle re-entered rather than terminating.

        Design: Difficulty/non_linear_state_machine/referral_info_request_cycle
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        rec_id = program["rec"]["id"]
        ref = submit_referral(emp["id"], program["req"]["id"], candidate_email="ca@x.com")
        rec_h = make_recruiter_headers(rec_id)

        get_success_data(api.review_referral(ref["id"], rec_h))
        d1 = get_success_data(api.request_info_referral(ref["id"], rec_h))
        assert d1["status"] == "NEEDS_INFO"
        d2 = get_success_data(api.provide_info_referral(ref["id"], rec_h))
        assert d2["status"] == "UNDER_REVIEW"
        d3 = get_success_data(api.request_info_referral(ref["id"], rec_h))
        assert d3["status"] == "NEEDS_INFO", "second REQUEST_INFO must succeed from UNDER_REVIEW"


class TestRequisitionPauseResumeCycle:
    def test_pause_blocks_and_resume_reenables_submission(self, api):
        """PRD §3.2: "an open requisition may be paused and later resumed, and the
        `OPEN`–`PAUSED` cycle may repeat an unlimited number of times."
        PRD §3.3: "1. The requisition must be in `OPEN`; any other status is rejected with
        `ERR_REQUISITION_NOT_OPEN` (HTTP 409)."

        A submission against a PAUSED requisition is rejected; after resume the same
        submission succeeds.

        Design: Difficulty/non_linear_state_machine/requisition_pause_resume_cycle
        """
        create_active_policy()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        req = create_open_requisition()
        ta = TEST_USERS["talent_admin_headers"]
        get_success_data(api.pause_requisition(req["id"], ta))

        resp = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=req["id"], candidate_email="c1@x.com",
                candidate_full_name="C One",
            ),
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REQUISITION_NOT_OPEN)

        data = get_success_data(api.resume_requisition(req["id"], ta))
        assert data["status"] == "OPEN"

        ok = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=req["id"], candidate_email="c1@x.com",
                candidate_full_name="C One",
            ),
            make_employee_headers(emp["id"]),
        )
        ok_data = validate_success(ok, 201)
        assert ok_data["status"] == "SUBMITTED"

    def test_pause_resume_cycle_open_referral_count(self, api):
        """PRD §3.2: "The derived `open_referral_count` reports how many of the
        requisition's referrals are currently non-terminal."
        PRD §3.3: "1. The requisition must be in `OPEN`; any other status is rejected with
        `ERR_REQUISITION_NOT_OPEN` (HTTP 409)."

        After the pause/reject/resume/accept cycle, exactly one non-terminal referral
        exists against the requisition.

        Design: Difficulty/non_linear_state_machine/requisition_pause_resume_cycle
        """
        create_active_policy()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        req = create_open_requisition()
        ta = TEST_USERS["talent_admin_headers"]
        get_success_data(api.pause_requisition(req["id"], ta))

        resp = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=req["id"], candidate_email="c1@x.com",
                candidate_full_name="C One",
            ),
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REQUISITION_NOT_OPEN)

        get_success_data(api.resume_requisition(req["id"], ta))
        ok = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=req["id"], candidate_email="c1@x.com",
                candidate_full_name="C One",
            ),
            make_employee_headers(emp["id"]),
        )
        validate_success(ok, 201)

        req_now = get_success_data(api.get_requisition(req["id"], ta))
        assert req_now["open_referral_count"] == 1, (
            f"expected 1 open referral, got {req_now['open_referral_count']}"
        )


class TestOfferDeclinedLoop:
    def test_offer_declined_loops_back_to_interviewing(self, api):
        """PRD §3.4: "When an offer is declined, the referral loops from `OFFER_EXTENDED`
        back to `INTERVIEWING` (event `OFFER_DECLINED`), a cycle that may repeat an
        unlimited number of times".

        offer-declined moves OFFER_EXTENDED back to INTERVIEWING and a re-advance to
        OFFER_EXTENDED succeeds from there.

        Design: Difficulty/non_linear_state_machine/offer_declined_interviewing_loop
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        ref = submit_referral(emp["id"], program["req"]["id"], candidate_email="ca@x.com")
        advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
        hm_h = make_hiring_manager_headers(program["hm"]["id"])

        declined = get_success_data(api.offer_declined_referral(ref["id"], hm_h))
        assert declined["status"] == "INTERVIEWING", (
            f"offer-declined must loop back to INTERVIEWING, got {declined['status']}"
        )

        reoffered = get_success_data(
            api.advance_referral(ref["id"], {"to_state": "OFFER_EXTENDED"}, hm_h)
        )
        assert reoffered["status"] == "OFFER_EXTENDED"

    def test_offer_declined_loop_no_milestones_until_hire(self, api):
        """PRD §3.4: "Two bonus milestones are created from the referral's
        `bonus_total_cents` under the pinned split" — as an effect of the hire action
        ("The hire action belongs to the `HiringManager` and moves `OFFER_EXTENDED` to
        `HIRED`."). "When an offer is declined, the referral loops from `OFFER_EXTENDED`
        back to `INTERVIEWING` (event `OFFER_DECLINED`)".
        PRD §3.2: "`tier_ic_cents` 150000"; "`hire_pct` 30".

        No milestones exist after the declined loop; exactly two (HIRE 45000 EARNED,
        RETENTION 105000 PENDING) exist after the eventual hire.

        Design: Difficulty/non_linear_state_machine/offer_declined_interviewing_loop
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        ref = submit_referral(emp["id"], program["req"]["id"], candidate_email="ca@x.com")
        advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
        hm_h = make_hiring_manager_headers(program["hm"]["id"])
        pp = TEST_USERS["payroll_processor_headers"]

        get_success_data(api.offer_declined_referral(ref["id"], hm_h))
        mid_loop = get_success_data(api.list_referral_milestones(ref["id"], pp))
        assert mid_loop == [], f"no milestones may exist before hire, got {mid_loop}"

        get_success_data(api.advance_referral(ref["id"], {"to_state": "OFFER_EXTENDED"}, hm_h))
        hired = hire_referral(ref["id"], program["hm"]["id"])
        assert hired["status"] == "HIRED"

        milestones = get_success_data(api.list_referral_milestones(ref["id"], pp))
        assert len(milestones) == 2, f"expected exactly 2 milestones, got {len(milestones)}"
        by_kind = {m["kind"]: m for m in milestones}
        assert by_kind["HIRE"]["amount_cents"] == 45000
        assert by_kind["HIRE"]["status"] == "EARNED"
        assert by_kind["RETENTION"]["amount_cents"] == 105000
        assert by_kind["RETENTION"]["status"] == "PENDING"


class TestReferralSubmitGatedByRequisitionState:
    def test_draft_requisition_rejects_submission(self, api):
        """PRD §3.3: "1. The requisition must be in `OPEN`; any other status is rejected
        with `ERR_REQUISITION_NOT_OPEN` (HTTP 409)."
        PRD §3.2: "A requisition starts in `DRAFT`."

        Submission against a DRAFT requisition is rejected.

        Design: Difficulty/cross_entity_state_dependency/referral_submit_gated_by_requisition_state
        """
        create_active_policy()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        ta = TEST_USERS["talent_admin_headers"]
        req = get_success_data(
            api.create_requisition(
                {"req_number": "REQ-D-1", "title": "Draft role", "department": "ENGINEERING", "level": "IC"},
                ta,
            )
        )
        resp = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=req["id"], candidate_email="c1@x.com",
                candidate_full_name="C One",
            ),
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REQUISITION_NOT_OPEN)

    def test_paused_then_resumed_requisition_reenables_submission(self, api):
        """PRD §3.3: "1. The requisition must be in `OPEN`; any other status is rejected
        with `ERR_REQUISITION_NOT_OPEN` (HTTP 409)."
        PRD §3.2: "an open requisition may be paused and later resumed".

        PAUSED rejects with the same error; after resume the submission succeeds.

        Design: Difficulty/cross_entity_state_dependency/referral_submit_gated_by_requisition_state
        """
        create_active_policy()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        req = create_open_requisition()
        ta = TEST_USERS["talent_admin_headers"]
        get_success_data(api.pause_requisition(req["id"], ta))

        resp = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=req["id"], candidate_email="c2@x.com",
                candidate_full_name="C Two",
            ),
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REQUISITION_NOT_OPEN)

        get_success_data(api.resume_requisition(req["id"], ta))
        ok = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=req["id"], candidate_email="c2@x.com",
                candidate_full_name="C Two",
            ),
            make_employee_headers(emp["id"]),
        )
        data = validate_success(ok, 201)
        assert data["status"] == "SUBMITTED"
