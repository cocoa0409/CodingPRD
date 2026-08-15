"""Submission validation corner tests (PRD §3.3, §2.10)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    make_employee_headers,
    make_recruiter_headers,
    make_hiring_manager_headers,
    create_employee,
    create_open_requisition,
    create_active_policy,
    create_candidate,
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
    list_employee_abuse_cases,
    set_clock,
    ops_evaluate,
    create_referral_payload,
    build_user_headers,
    api_client,
)


class TestUnknownRole:
    def test_unknown_role_returns_unauthenticated(self, api):
        """PRD §2.1: "A request with missing headers, or whose `X-User-Role` value is
        not one of these seven, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unknown_role_returns_unauthenticated
        """
        resp = api.list_employees(build_user_headers("wiz-1", "Wizard"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestExistenceBeatsReferential:
    def test_existence_beats_referential_on_submit(self, api):
        """PRD §2.10: "6. **Existence** — path-templated resources exist, validated
        left-to-right per §2.9; otherwise `ERR_NOT_FOUND`." and "Only after this generic
        pipeline do endpoint-specific business rules run".
        PRD §3.3: "The candidate must be referable: `cooldown_until` must be null or
        already reached, and `global_status` must not be `HIRED` — a candidate currently
        hired through the program is permanently blocked from new referrals. Violations
        are rejected with `ERR_CANDIDATE_IN_COOLDOWN` (HTTP 422)."

        A submission naming a nonexistent requisition AND a cooling-down candidate
        returns 404 ERR_NOT_FOUND.

        Design: Corner/validations/existence_beats_referential_on_submit
        """
        create_active_policy()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        cand = create_candidate(
            full_name="Cool Cand", email="cool@x.com",
            prior_application_at="2026-03-01T00:00:00Z",
        )
        resp = api.create_referral(
            {
                "referrer_id": emp["id"],
                "job_requisition_id": NON_EXISTENT_UUID,
                "candidate_id": cand["id"],
            },
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestHireDateInFuture:
    def test_hire_date_in_future_rejected(self, api):
        """PRD §3.4: "It carries the actual `hire_date`, which must be at or before the
        logical now — a future start date is rejected with `ERR_HIRE_DATE_IN_FUTURE`".

        hire_date one day beyond the logical clock is rejected; the referral stays
        OFFER_EXTENDED and no milestones exist.

        Design: Corner/validations/hire_date_in_future_rejected
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        ref = submit_referral(emp["id"], program["req"]["id"], candidate_email="c1@x.com",
                              candidate_full_name="C One")
        advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])

        hm_h = make_hiring_manager_headers(program["hm"]["id"])
        resp = api.hire_referral(ref["id"], {"hire_date": "2026-08-02T00:00:00Z"}, hm_h)
        validate_error(resp, ApiErrorId.ERR_HIRE_DATE_IN_FUTURE)

        ref_now = get_referral(ref["id"])
        assert ref_now["status"] == "OFFER_EXTENDED"
        pp = TEST_USERS["payroll_processor_headers"]
        milestones = get_success_data(api.list_referral_milestones(ref["id"], pp))
        assert milestones == []


class TestDuplicateReferral:
    def test_duplicate_referral_same_candidate_same_req_rejected(self, api):
        """PRD §3.3: "No duplicate: no other referral may exist for the same
        `candidate_id` and the same `job_requisition_id` in any non-terminal status;
        otherwise `ERR_DUPLICATE_REFERRAL` (HTTP 409)."
        PRD §3.3: "when their last non-terminal referral reaches a terminal outcome,
        the system returns them to `AVAILABLE`, stamps `last_terminal_outcome_at` with
        the logical clock, and recomputes their `cooldown_until`" and "at the exact
        instant of `cooldown_until` the referral is allowed."

        The second live submission is rejected; after the first is withdrawn the pair is
        accepted again once the candidate's fresh six-month cooldown is reached.

        Design: Corner/validations/duplicate_referral_same_candidate_same_req_rejected
        """
        create_active_policy()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        req = create_open_requisition()
        resp1 = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=req["id"], candidate_email="c1@x.com",
                candidate_full_name="C One",
            ),
            make_employee_headers(emp["id"]),
        )
        ref1 = validate_success(resp1, 201)

        resp_dup = api.create_referral(
            {
                "referrer_id": emp["id"], "job_requisition_id": req["id"],
                "candidate_id": ref1["candidate_id"],
            },
            make_employee_headers(emp["id"]),
        )
        validate_error(resp_dup, ApiErrorId.ERR_DUPLICATE_REFERRAL)

        get_success_data(api.withdraw_referral(ref1["id"], make_employee_headers(emp["id"])))
        # The withdrawal stamps last_terminal_outcome_at = 2026-08-01, so the candidate
        # is referable again exactly at cooldown_until (2026-08-01 + 6 months).
        set_clock("2027-02-01T00:00:00Z")
        resp2 = api.create_referral(
            {
                "referrer_id": emp["id"], "job_requisition_id": req["id"],
                "candidate_id": ref1["candidate_id"],
            },
            make_employee_headers(emp["id"]),
        )
        data2 = validate_success(resp2, 201)
        assert data2["status"] == "SUBMITTED", (
            "the duplicate rule only considers non-terminal referrals"
        )


class TestReferrerExcluded:
    def test_referrer_excluded_manager_same_department(self, api):
        """PRD §3.3: "Referrer exclusions: a referrer whose `is_recruiter` flag is true
        may not refer into a requisition whose `department` equals their own, and a
        referrer whose `job_level` is `MANAGER`, `DIRECTOR`, or `EXECUTIVE` may not
        refer into their own department either. Violations are rejected with
        `ERR_REFERRER_EXCLUDED` (HTTP 422)."

        A MANAGER referring into their own department is excluded; the same manager
        referring cross-department is accepted.

        Design: Corner/validations/referrer_excluded_manager_same_department
        """
        create_active_policy()
        mgr = create_employee(
            employee_number="E106", full_name="Mgr M", email="mgr@corp.com", job_level="MANAGER",
        )
        req_eng = create_open_requisition(req_number="REQ-ENG", title="Eng role",
                                          department="ENGINEERING")
        req_prd = create_open_requisition(req_number="REQ-PRD", title="Prod role",
                                          department="PRODUCT")

        resp = api.create_referral(
            create_referral_payload(
                referrer_id=mgr["id"], job_requisition_id=req_eng["id"],
                candidate_email="c1@x.com", candidate_full_name="C One",
            ),
            make_employee_headers(mgr["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERRER_EXCLUDED)

        ok = api.create_referral(
            create_referral_payload(
                referrer_id=mgr["id"], job_requisition_id=req_prd["id"],
                candidate_email="c2@x.com", candidate_full_name="C Two",
            ),
            make_employee_headers(mgr["id"]),
        )
        data = validate_success(ok, 201)
        assert data["status"] == "SUBMITTED"

    def test_recruiter_excluded_referring_into_own_department(self, api):
        """PRD §3.3: "a referrer whose `is_recruiter` flag is true may not refer into a
        requisition whose `department` equals their own, and a referrer whose `job_level` is
        `MANAGER`, `DIRECTOR`, or `EXECUTIVE` may not refer into their own department
        either. Violations are rejected with `ERR_REFERRER_EXCLUDED` (HTTP 422)."

        A TALENT recruiter referring into a TALENT requisition is excluded.

        Design: Corner/validations/recruiter_excluded_referring_into_own_department
        """
        create_active_policy()
        rec = create_employee(
            employee_number="E900", full_name="Rec Ru", email="rec@corp.com",
            department="TALENT", is_recruiter=True,
        )
        req_ta = create_open_requisition(req_number="REQ-TA", title="Recruiter role",
                                         department="TALENT")
        resp = api.create_referral(
            create_referral_payload(
                referrer_id=rec["id"], job_requisition_id=req_ta["id"],
                candidate_email="c1@x.com", candidate_full_name="C One",
            ),
            make_employee_headers(rec["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERRER_EXCLUDED)


class TestRoleNotReferralEligible:
    def test_role_not_referral_eligible_rejected(self, api):
        """PRD §3.3: "The requisition's `referral_eligible` must be true; otherwise
        `ERR_ROLE_NOT_REFERRAL_ELIGIBLE` (HTTP 422)."
        PRD §3.2: "whether the requisition is `referral_eligible` (default true)".

        A referral_eligible=false requisition rejects even a fully eligible referrer.

        Design: Corner/validations/role_not_referral_eligible_rejected
        """
        create_active_policy()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        req = create_open_requisition(
            req_number="REQ-X", title="Confidential role", department="PRODUCT",
            referral_eligible=False,
        )
        resp = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=req["id"],
                candidate_email="c1@x.com", candidate_full_name="C One",
            ),
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ROLE_NOT_REFERRAL_ELIGIBLE)


class TestSubmitWithoutActivePolicy:
    def test_submit_without_active_policy_returns_no_active_policy(self, api):
        """PRD §3.3: "10. An `ACTIVE` policy version must exist to pin; otherwise
        `ERR_NO_ACTIVE_POLICY` (HTTP 422)."

        With zero policies the submission fails after all person/role checks pass.

        Design: Corner/validations/submit_without_active_policy_returns_no_active_policy
        """
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        req = create_open_requisition()
        resp = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=req["id"],
                candidate_email="c1@x.com", candidate_full_name="C One",
            ),
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_POLICY)

        ta = TEST_USERS["talent_admin_headers"]
        rows, _ = validate_paginated(api.list_referrals(ta, params={"referrer_id": emp["id"]}))
        assert rows == []


class TestSelfReferral:
    def test_self_referral_rejected_and_auto_case_raised(self, api):
        """PRD §3.3: "The candidate's `normalized_email` must differ from the referrer's
        normalized `email`. A self-referral is rejected with `ERR_SELF_REFERRAL`
        (HTTP 422), *and* — even though the submission fails — the system automatically
        raises an abuse case of `case_type` `SELF_REFERRAL` with `raised_by_user_id` set
        to the literal string `system`, naming the referrer."
        PRD §3.3: "the system matches on the candidate's `normalized_email` — computed
        as the email lowercased and trimmed".

        ' ANNA@corp.com ' normalizes to the referrer's own email: rejected, one
        system-raised case, no referral row.

        Design: Corner/validations/self_referral_rejected_and_auto_case_raised
        """
        create_active_policy()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        req = create_open_requisition()
        resp = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=req["id"],
                candidate_email=" ANNA@corp.com ", candidate_full_name="Ann A",
            ),
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SELF_REFERRAL)

        cases = list_employee_abuse_cases(emp["id"])
        assert len(cases) == 1
        assert cases[0]["case_type"] == "SELF_REFERRAL"
        assert cases[0]["raised_by_user_id"] == "system"
        assert cases[0]["status"] == "OPEN"

        ta = TEST_USERS["talent_admin_headers"]
        rows, _ = validate_paginated(api.list_referrals(ta, params={"referrer_id": emp["id"]}))
        assert rows == []


class TestCandidateHiredBlocksPermanently:
    def test_candidate_hired_blocks_new_referral_permanently(self, api):
        """PRD §3.3: "`global_status` must not be `HIRED` — a candidate currently hired
        through the program is permanently blocked from new referrals. Violations are
        rejected with `ERR_CANDIDATE_IN_COOLDOWN` (HTTP 422)."

        A hired candidate cannot be re-referred to a different requisition.

        Design: Corner/validations/candidate_hired_blocks_new_referral_permanently
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
        ref1 = validate_success(resp, 201)
        cand_id = ref1["candidate_id"]
        advance_referral_to_offer(ref1["id"], program["rec"]["id"], program["hm"]["id"])
        hire_referral(ref1["id"], program["hm"]["id"])

        req2 = create_open_requisition(req_number="REQ-2", title="Role 2")
        resp2 = api.create_referral(
            {
                "referrer_id": emp["id"], "job_requisition_id": req2["id"],
                "candidate_id": cand_id,
            },
            make_employee_headers(emp["id"]),
        )
        validate_error(resp2, ApiErrorId.ERR_CANDIDATE_IN_COOLDOWN)


class TestSodRaiserCannotConfirm:
    def test_sod_raiser_cannot_confirm_own_case(self, api):
        """PRD §3.7: "Both verdicts enforce segregation of duties: the deciding
        officer's `X-User-ID` must differ from the case's `raised_by_user_id`, otherwise
        the attempt is rejected with `ERR_SOD_VIOLATION` (HTTP 403) — no one decides a
        case they raised."

        The raiser cannot confirm; a different officer can.

        Design: Corner/validations/sod_raiser_cannot_confirm_own_case
        """
        emp = create_employee(employee_number="E102", full_name="Shady S", email="shady@corp.com")
        co1 = build_user_headers("co-1", "ComplianceOfficer")
        resp = api.create_abuse_case(
            {"employee_id": emp["id"], "case_type": "MANUAL"}, co1
        )
        case = validate_success(resp, 201)

        resp_self = api.confirm_abuse_case(case["id"], co1)
        validate_error(resp_self, ApiErrorId.ERR_SOD_VIOLATION)

        co2 = build_user_headers("co-2", "ComplianceOfficer")
        data = get_success_data(api.confirm_abuse_case(case["id"], co2))
        assert data["status"] == "CONFIRMED"
        assert data["decided_by_user_id"] == "co-2"


class TestAnnualCapExceededAtApprove:
    def test_annual_cap_exceeded_at_approve(self, api):
        """PRD §3.6: "first the annual cap — the referrer's `annual_committed_cents`
        plus this milestone's `amount_cents` must not exceed the `annual_cap_cents` of
        the referral's pinned policy, otherwise `ERR_ANNUAL_CAP_EXCEEDED` (HTTP 422)".
        PRD §3.5: "The `annual_committed_cents` accumulator is the same computation over
        the narrower lens of `APPROVED`, `BATCHED`, and `PAID`" — counting only
        milestones "whose `earned_at` falls inside the current calendar year".

        Two 100000-gross referrals quoted before any milestone existed: both HIRE 30000
        approved (committed 60000); the first 70000 retention approve breaches the
        100000 cap. The hires are dated 2026-01-01 so the retention is due 2026-06-30
        and the whole scenario stays inside the 2026 accumulator window.

        Design: Corner/validations/annual_cap_exceeded_at_approve
        """
        program = setup_program(policy_overrides={"annual_cap_cents": 100000},
                                req_overrides={"openings": 5})
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        setup_verified_tax_profile(emp["id"])

        refs = []
        for email, name in (("c1@x.com", "C One"), ("c2@x.com", "C Two")):
            ref = submit_referral(emp["id"], program["req"]["id"], candidate_email=email,
                                  candidate_full_name=name)
            refs.append(ref)
        for ref in refs:
            advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
            hire_referral(ref["id"], program["hm"]["id"], hire_date="2026-01-01T00:00:00Z")

        pp = TEST_USERS["payroll_processor_headers"]
        ms1h = get_hire_milestone(refs[0]["id"])
        ms2h = get_hire_milestone(refs[1]["id"])
        get_success_data(api.approve_milestone(ms1h["id"], pp))
        get_success_data(api.approve_milestone(ms2h["id"], pp))

        # Retention due 2026-06-30 is already reached at the current clock; the sweep
        # earns both retention milestones inside calendar year 2026.
        ops_evaluate()
        ms1r = get_retention_milestone(refs[0]["id"])
        assert ms1r["status"] == "EARNED"
        assert ms1r["amount_cents"] == 70000

        resp = api.approve_milestone(ms1r["id"], pp)
        validate_error(resp, ApiErrorId.ERR_ANNUAL_CAP_EXCEEDED)

        ms_now = get_milestone(ms1r["id"])
        assert ms_now["status"] == "EARNED"
        emp_now = get_employee(emp["id"])
        assert emp_now["annual_committed_cents"] == 60000
