"""Referral pipeline transition and cascade corner tests (PRD §3.4, §3.2, §3.1)."""
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
    build_user_headers,
    create_employee,
    create_open_requisition,
    create_active_policy,
    submit_referral,
    setup_program,
    setup_verified_tax_profile,
    advance_referral_to_offer,
    hire_referral,
    get_referral,
    get_employee,
    get_milestone,
    get_hire_milestone,
    get_retention_milestone,
    create_open_batch,
    set_clock,
    ops_evaluate,
    raise_abuse_case,
    confirm_abuse_case,
    create_referral_payload,
    api_client,
    assert_instant_eq,
    get_batch,
)


class TestAdvanceFromSubmitted:
    def test_referral_advance_from_submitted_returns_invalid_state(self, api):
        """PRD §3.4: "from `QUALIFIED` to `SCREENING` and from `SCREENING` to
        `INTERVIEWING` at the hand of a `Recruiter`" — advancement targets the immediate
        next stage from the pipeline, never from SUBMITTED.
        PRD §2.10: "if the resource is in a non-terminal state that simply does not offer
        the requested transition, the rejection is `ERR_INVALID_STATE` (HTTP 409)."
        PRD §2.11: "Events are created as a side effect of the transitions described in
        §3".

        advance to SCREENING from SUBMITTED fails; status and event log unchanged.

        Design: Corner/state_machines/referral_advance_from_submitted_returns_invalid_state
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        ref = submit_referral(emp["id"], program["req"]["id"], candidate_email="c1@x.com",
                              candidate_full_name="C One")
        rec_h = make_recruiter_headers(program["rec"]["id"])

        resp = api.advance_referral(ref["id"], {"to_state": "SCREENING"}, rec_h)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        ref_now = get_referral(ref["id"])
        assert ref_now["status"] == "SUBMITTED"
        events = get_success_data(api.list_referral_events(ref["id"], rec_h))
        assert len(events) == 1 and events[0]["event_type"] == "SUBMIT"


class TestWithdrawFromCompleted:
    def test_referral_withdraw_from_completed_returns_already_terminal(self, api):
        """PRD §2.10: "If the resource is already in a terminal state, every transition
        attempt is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409)".
        PRD §3.5: "any referral still `HIRED` whose `retention_due_at` has been reached
        and whose candidate is not `DEPARTED` moves to `COMPLETED`".
        PRD §3.4: "The referrer themselves may withdraw at any point before hire".

        Withdraw from COMPLETED is rejected and the status is unchanged.

        Design: Corner/state_machines/referral_withdraw_from_completed_returns_already_terminal
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        ref = submit_referral(emp["id"], program["req"]["id"], candidate_email="c1@x.com",
                              candidate_full_name="C One")
        advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
        hire_referral(ref["id"], program["hm"]["id"])
        set_clock("2027-01-28T00:00:00Z")
        ops_evaluate()

        ref_now = get_referral(ref["id"])
        assert ref_now["status"] == "COMPLETED", f"precondition: COMPLETED, got {ref_now['status']}"

        resp = api.withdraw_referral(ref["id"], make_employee_headers(emp["id"]))
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)

        ref_after = get_referral(ref["id"])
        assert ref_after["status"] == "COMPLETED"


class TestMilestoneDoubleApprove:
    def test_milestone_double_approve_returns_invalid_state(self, api):
        """PRD §3.6: "An earned milestone becomes spendable only after a
        `PayrollProcessor` approves it, moving it from `EARNED` to `APPROVED`."
        PRD §2.10: "if the resource is in a non-terminal state that simply does not offer
        the requested transition, the rejection is `ERR_INVALID_STATE` (HTTP 409)."
        PRD §3.6: "On success the milestone's withholding is computed and *locked* at
        that instant".

        The second approve of the same milestone fails; the locked withholding stands.

        Design: Corner/state_machines/milestone_double_approve_returns_invalid_state
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        setup_verified_tax_profile(emp["id"])
        ref = submit_referral(emp["id"], program["req"]["id"], candidate_email="c1@x.com",
                              candidate_full_name="C One")
        advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
        hire_referral(ref["id"], program["hm"]["id"])
        ms = get_hire_milestone(ref["id"])

        pp = TEST_USERS["payroll_processor_headers"]
        first = get_success_data(api.approve_milestone(ms["id"], pp))
        assert first["status"] == "APPROVED"

        resp = api.approve_milestone(ms["id"], pp)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        ms_now = get_milestone(ms["id"])
        assert ms_now["status"] == "APPROVED"
        assert ms_now["withholding_cents"] == 9900


class TestBatchAddAfterSeal:
    def test_batch_add_after_seal_returns_batch_not_open(self, api):
        """PRD §3.6: "The batch must be `OPEN` — milestone add and milestone remove on
        any non-`OPEN` batch are rejected with `ERR_BATCH_NOT_OPEN` (HTTP 409)" and "A
        `PayrollProcessor` seals an `OPEN` batch (moving it to `SEALED`, after which no
        further milestone add or remove is allowed)".

        Adding to a SEALED batch is rejected and the milestone stays APPROVED.

        Design: Corner/state_machines/batch_add_after_seal_returns_batch_not_open
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        setup_verified_tax_profile(emp["id"])
        ref = submit_referral(emp["id"], program["req"]["id"], candidate_email="c1@x.com",
                              candidate_full_name="C One")
        advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
        hire_referral(ref["id"], program["hm"]["id"])
        ms = get_hire_milestone(ref["id"])
        pp = TEST_USERS["payroll_processor_headers"]
        get_success_data(api.approve_milestone(ms["id"], pp))
        batch = create_open_batch()
        get_success_data(api.seal_payroll_batch(batch["id"], pp))

        # Per PRD §2.7 a stale version is reported before the batch-open check, so
        # the batch's current (post-seal) version must be supplied to exercise
        # ERR_BATCH_NOT_OPEN.
        sealed_version = get_batch(batch["id"])["version"]
        resp = api.add_milestone_to_batch(
            batch["id"],
            {"milestone_id": ms["id"], "expected_payroll_batch_version": sealed_version},
            pp,
        )
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_OPEN)

        ms_now = get_milestone(ms["id"])
        assert ms_now["status"] == "APPROVED"
        assert ms_now.get("payroll_batch_id") is None


class TestAbuseCaseDoubleDecide:
    def test_abuse_case_double_decide_returns_already_terminal(self, api):
        """PRD §3.7: "`CONFIRMED` and `DISMISSED` are terminal."
        PRD §2.10: "If the resource is already in a terminal state, every transition
        attempt is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409)."
        PRD §3.7: "the employee's `fraud_strikes` increases by one".

        A second confirm — even by a different officer — is rejected; the strike count
        stays at one.

        Design: Corner/state_machines/abuse_case_double_decide_returns_already_terminal
        """
        emp = create_employee(employee_number="E102", full_name="Shady S", email="shady@corp.com")
        case = raise_abuse_case(emp["id"], "MANUAL")
        confirm_abuse_case(case["id"])  # default officer co-9

        resp = api.confirm_abuse_case(case["id"], build_user_headers("co-8", "ComplianceOfficer"))
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)

        emp_now = get_employee(emp["id"])
        assert emp_now["fraud_strikes"] == 1


class TestHireSideEffects:
    def test_hire_side_effects_fill_requisition_and_candidate(self, api):
        """PRD §3.4: "The candidate moves from `IN_PROCESS` to `HIRED`, and their
        `hired_via_referral_id` is set to this referral." and "The requisition's
        `filled_count` increases by one; if it thereby equals `openings`, the requisition
        moves from `OPEN` to `FILLED` with the sibling `NOT_SELECTED` cascade and
        reservation releases described in §3.2" and PRD §3.2: "the requisition
        automatically transitions from `OPEN` to `FILLED`, records the just-hired
        candidate in `filled_by_candidate_id`" and "The referral's `retention_due_at` and
        `clawback_until` are computed from the pinned policy: the retention due date is
        `hire_date` plus the policy's `retention_days`, and the clawback deadline is that
        due date plus the policy's `clawback_days`."
        PRD §3.2: "`retention_days` 180, `clawback_days` 90" and "the number of `openings`
        (default one, and always at least one — a request with fewer is rejected with
        `ERR_INVALID_REQUEST`)".

        All hire side effects land: candidate HIRED, requisition FILLED, dates computed,
        two milestones created.

        Design: Corner/state_machines/hire_side_effects_fill_requisition_and_candidate
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        resp = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=program["req"]["id"],
                candidate_email="c1@x.com", candidate_full_name="C One",
            ),
            make_employee_headers(emp["id"]),
        )
        ref = validate_success(resp, 201)
        cand_id = ref["candidate_id"]
        advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
        hired = hire_referral(ref["id"], program["hm"]["id"])
        assert hired["status"] == "HIRED"
        assert_instant_eq(hired["retention_due_at"], "2027-01-28T00:00:00Z")
        assert_instant_eq(hired["clawback_until"], "2027-04-28T00:00:00Z")

        rec_h = make_recruiter_headers(program["rec"]["id"])
        cand = get_success_data(api.get_candidate(cand_id, rec_h))
        assert cand["global_status"] == "HIRED"
        assert cand["hired_via_referral_id"] == ref["id"]

        ta = TEST_USERS["talent_admin_headers"]
        req_now = get_success_data(api.get_requisition(program["req"]["id"], ta))
        assert req_now["status"] == "FILLED"
        assert req_now["filled_count"] == 1
        assert req_now["filled_by_candidate_id"] == cand_id

        pp = TEST_USERS["payroll_processor_headers"]
        milestones = get_success_data(api.list_referral_milestones(ref["id"], pp))
        by_kind = {m["kind"]: m for m in milestones}
        assert by_kind["HIRE"]["amount_cents"] == 45000
        assert by_kind["HIRE"]["status"] == "EARNED"
        assert by_kind["RETENTION"]["amount_cents"] == 105000
        assert by_kind["RETENTION"]["status"] == "PENDING"


class TestSiblingReferralAutoNotSelected:
    def test_sibling_referral_auto_not_selected_on_fill(self, api):
        """PRD §3.2: "when a hire raises `filled_count` to equal `openings`, the
        requisition automatically transitions from `OPEN` to `FILLED`, records the
        just-hired candidate in `filled_by_candidate_id`, and every *other* non-terminal
        referral for the requisition moves to `NOT_SELECTED` with `last_decision_reason`
        `REQ_FILLED`".
        PRD §3.3/3.1: "when their last non-terminal referral reaches a terminal outcome,
        the system returns them to `AVAILABLE`, stamps `last_terminal_outcome_at` with
        the logical clock, and recomputes their `cooldown_until`."

        Hiring referral A auto-NOT_SELECTs sibling referral B; B's candidate returns to
        AVAILABLE.

        Design: Corner/state_machines/sibling_referral_auto_not_selected_on_fill
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        ref_a = submit_referral(emp["id"], program["req"]["id"], candidate_email="c1@x.com",
                                candidate_full_name="C One")
        resp_b = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=program["req"]["id"],
                candidate_email="c2@x.com", candidate_full_name="C Two",
            ),
            make_employee_headers(emp["id"]),
        )
        ref_b = validate_success(resp_b, 201)
        cand_b = ref_b["candidate_id"]

        advance_referral_to_offer(ref_a["id"], program["rec"]["id"], program["hm"]["id"])
        rec_h = make_recruiter_headers(program["rec"]["id"])
        get_success_data(api.review_referral(ref_b["id"], rec_h))
        get_success_data(api.qualify_referral(ref_b["id"], rec_h))

        hire_referral(ref_a["id"], program["hm"]["id"])

        ref_a_now = get_referral(ref_a["id"])
        assert ref_a_now["status"] == "HIRED"
        ref_b_now = get_referral(ref_b["id"])
        assert ref_b_now["status"] == "NOT_SELECTED"
        assert ref_b_now["last_decision_reason"] == "REQ_FILLED"

        cand_b_now = get_success_data(api.get_candidate(cand_b, rec_h))
        assert cand_b_now["global_status"] == "AVAILABLE"
        assert cand_b_now["last_terminal_outcome_at"] is not None
        assert cand_b_now["cooldown_until"] is not None


class TestRequisitionCancelCascade:
    def test_requisition_cancel_cascades_not_selected(self, api):
        """PRD §3.2: "cancelling an `OPEN` or `PAUSED` requisition moves every one of
        its non-terminal referrals to `NOT_SELECTED` with `last_decision_reason` set to
        `REQ_CANCELLED` and releases each referral's remaining campaign reservation".

        An in-flight referral becomes NOT_SELECTED/REQ_CANCELLED; an already-WITHDRAWN
        referral is untouched.

        Design: Corner/state_machines/requisition_cancel_cascades_not_selected
        """
        create_active_policy()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        req = create_open_requisition(openings=5)
        ref_a = submit_referral(emp["id"], req["id"], candidate_email="c1@x.com",
                                candidate_full_name="C One")
        ref_b = submit_referral(emp["id"], req["id"], candidate_email="c2@x.com",
                                candidate_full_name="C Two")
        get_success_data(api.withdraw_referral(ref_b["id"], make_employee_headers(emp["id"])))

        ta = TEST_USERS["talent_admin_headers"]
        data = get_success_data(api.cancel_requisition(req["id"], ta))
        assert data["status"] == "CANCELLED"

        ref_a_now = get_referral(ref_a["id"])
        assert ref_a_now["status"] == "NOT_SELECTED"
        assert ref_a_now["last_decision_reason"] == "REQ_CANCELLED"

        ref_b_now = get_referral(ref_b["id"])
        assert ref_b_now["status"] == "WITHDRAWN", "terminal rows untouched by the cascade"


class TestEmployeeTerminateForfeits:
    def test_employee_terminate_forfeits_unpaid_milestones(self, api):
        """PRD §3.1: "Termination stamps `terminated_at` with the logical clock and
        immediately forfeits the employee's unpaid bonus earnings: every bonus milestone
        attached to referrals where this employee is the `referrer_id`, while in the
        `EARNED`, `APPROVED`, or `BATCHED` state, transitions to `FORFEITED`. Milestones
        still `PENDING` (for example an unearned retention milestone) are not touched by
        termination, and milestones already `PAID` stay paid — money already disbursed is
        recovered only through the clawback path of §3.5, never by termination."

        Wait — the design instance asserts BOTH milestones FORFEITED, but PRD says PENDING
        is NOT touched. Asserting per PRD: HIRE (EARNED) forfeited; the referral stays
        HIRED.

        Design: Corner/state_machines/employee_terminate_forfeits_unpaid_milestones
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        ref = submit_referral(emp["id"], program["req"]["id"], candidate_email="c1@x.com",
                              candidate_full_name="C One")
        advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
        hire_referral(ref["id"], program["hm"]["id"])

        pa = TEST_USERS["platform_admin_headers"]
        data = get_success_data(api.terminate_employee(emp["id"], pa))
        assert data["employment_status"] == "TERMINATED"
        assert data.get("terminated_at") is not None

        pp = TEST_USERS["payroll_processor_headers"]
        milestones = get_success_data(api.list_referral_milestones(ref["id"], pp))
        by_kind = {m["kind"]: m for m in milestones}
        assert by_kind["HIRE"]["status"] == "FORFEITED", (
            "EARNED milestone must be forfeited on termination"
        )

        ref_now = get_referral(ref["id"])
        assert ref_now["status"] == "HIRED", "termination does not rewrite hiring history"


class TestRejectReasonFork:
    def test_referral_reject_reason_maps_to_distinct_terminals(self, api):
        """PRD §3.4: "rejection requires a `reason_code` of `DUPLICATE`,
        `PRIOR_CANDIDATE`, or `OTHER`, moving the referral to `REJECTED_DUPLICATE`,
        `REJECTED_PRIOR_CANDIDATE`, or `REJECTED_OTHER` respectively, recording the same
        value in `last_decision_reason`".

        Each reason_code selects its terminal and is recorded.

        Design: Corner/state_machines/referral_reject_reason_maps_to_distinct_terminals
        """
        program = setup_program(req_overrides={"openings": 5})
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        rec_h = make_recruiter_headers(program["rec"]["id"])

        expected = {
            "DUPLICATE": "REJECTED_DUPLICATE",
            "PRIOR_CANDIDATE": "REJECTED_PRIOR_CANDIDATE",
            "OTHER": "REJECTED_OTHER",
        }
        for i, (reason, terminal) in enumerate(expected.items(), start=1):
            ref = submit_referral(emp["id"], program["req"]["id"],
                                  candidate_email=f"c{i}@x.com", candidate_full_name=f"C {i}")
            get_success_data(api.review_referral(ref["id"], rec_h))
            data = get_success_data(api.reject_referral(ref["id"], {"reason_code": reason}, rec_h))
            assert data["status"] == terminal, f"{reason}: expected {terminal}, got {data['status']}"
            assert data["last_decision_reason"] == reason
