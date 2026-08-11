"""Grant pipeline: award variants, capacity boundary, priority pairing,
fund conservation, expiry sweep, resubmission cycle, window/RBAC gates."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_employer,
    create_approved_assessment,
    create_signed_agreement,
    create_venue_for_mode,
    create_cohort_under,
    create_session_on,
    create_instructor,
    propose_and_confirm,
    enroll_participants,
    create_grant_program,
    create_grant_application_for_cohort,
    submit_and_review,
    approve_application,
    setup_launchable_cohort,
    setup_launched_cohort,
    close_session_attendance,
    launch_cohort,
    assert_program_fund_invariant,
    api_client,
    TEST_USERS,
    make_employer_contact_headers,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["admin_headers"]
CRED = TEST_USERS["credential_officer_headers"]
GRANT = TEST_USERS["grant_officer_headers"]
BILL = TEST_USERS["billing_clerk_headers"]


def _approved_application(api, program_id, cohort_id, requested_cents):
    gap = create_grant_application_for_cohort(cohort_id, program_id, requested_cents)
    submit_and_review(gap["id"])
    return approve_application(gap["id"])


class TestGrantProvisionalVsFinal:
    def _full_fixture(self, api):
        """20-enrollee 5-session cohort; 17 completers after delivery."""
        gp = create_grant_program(
            code="GP-26", name="State Training Grant FY26",
            appropriation_cents=10000000, max_share_pct=0.5,
            cap_per_trainee_cents=50000,
            application_window_end="2026-06-30T23:59:59Z", claim_deadline_days=60,
        )
        sessions = [("2026-06-%02dT09:00:00Z" % (1 + i),
                     "2026-06-%02dT11:00:00Z" % (1 + i)) for i in range(5)]
        ctx = setup_launched_cohort(
            num_participants=20, min_enrollment=15,
            sessions=sessions,
            agreement_overrides={
                "pricing_model": "PER_PARTICIPANT", "delivery_mode": "ON_SITE",
                "est_participant_count": 20, "est_delivery_hours": 10,
                "target_start_date": "2026-06-01T00:00:00Z", "max_cohorts": 3,
                "cohort_start_date": "2026-06-01T00:00:00Z",
                "cohort_end_date": "2026-06-05T00:00:00Z",
            },
            curriculum_modules=[{"code": "WLD-1", "hours": 10,
                                 "required_credential_codes": ["CNC", "OSHA30"]}],
            instructor_overrides={
                "full_name": "Ira Instructor",
                "credentials": [{"code": "CNC", "expires_on": "2027-01-01"},
                                {"code": "OSHA30", "expires_on": "2027-01-01"}],
                "hourly_rate_cents": 8000,
            },
            venue_overrides={"name": "Beta Shop Floor", "capacity": 40},
            participant_prefix="E",
        )
        gap = create_grant_application_for_cohort(ctx["cohort"]["id"], gp["id"], 500000)
        submit_and_review(gap["id"])
        return gp, ctx, gap

    def test_provisional_award_at_approval(self, api):
        """PRD §3.3: "`provisional_award_cents` is the smallest of three
        figures — the application's own `requested_cents`, the whole-cent
        floor of the agreement's `quoted_total_cents` multiplied by the
        program's `max_share_pct`, and the program's `cap_per_trainee_cents`
        multiplied by the cohort's `enrolled_count`."

        Design: Difficulty/dual_variant_calc/grant_reimbursement_provisional_vs_final
        """
        _, ctx, gap = self._full_fixture(api)
        approved = approve_application(gap["id"])
        # min(500000, floor(1025000*0.5)=512500, 20*50000) == 500000
        assert approved["provisional_award_cents"] == 500000, (
            f"expected provisional 500000, got {approved['provisional_award_cents']}"
        )

    def test_final_award_diverges_from_provisional(self, api):
        """PRD §3.3: "`final_award_cents` is the smallest of the
        `requested_cents`, the whole-cent floor of the cohort's `FINAL`
        invoice gross multiplied by `max_share_pct` — where the relevant
        invoice is the cohort's `FINAL`-variant invoice in `DRAFT`, `ISSUED`,
        or `PAID`, and the gross term counts as zero when no such invoice
        exists — and `cap_per_trainee_cents` multiplied by the cohort's
        `completer_count`."
        PRD §3.3: "Because the final basis uses delivered results, it diverges
        from the provisional award whenever participants dropped or sessions
        were cancelled."

        Design: Difficulty/dual_variant_calc/grant_reimbursement_provisional_vs_final
        """
        _, ctx, gap = self._full_fixture(api)
        approved = approve_application(gap["id"])
        prov = approved["provisional_award_cents"]

        ins = ctx["instructor"]["id"]
        # 19 attendees per session: E01..E17 full 2h; E18/E19 1.4h; E20 absent
        entries = [{"external_employee_ref": f"E{i:02d}", "attended_hours": 2}
                   for i in range(1, 18)]
        entries += [{"external_employee_ref": "E18", "attended_hours": 1.4},
                    {"external_employee_ref": "E19", "attended_hours": 1.4}]
        for sid in ctx["session_ids"]:
            close_session_attendance(sid, ins, entries)

        coh = get_success_data(api_client.get_cohort(ctx["cohort"]["id"], COORD))
        assert coh["completer_count"] == 17  # E18/E19 at 70% DROPPED; E20 NO_SHOW

        inv = validate_success(
            api_client.create_invoice(coh["id"], {"variant": "FINAL"}, BILL), 201
        )
        # 5 lines x (round(2*8000*1.15)=18400 + 19*7500=142500) = 804500
        assert inv["gross_cents"] == 804500, (
            f"expected FINAL gross 804500, got {inv['gross_cents']}"
        )

        validate_success(api_client.issue_credentials(coh["id"], CRED))
        claimed = validate_success(api_client.claim_grant_application(gap["id"], COORD))
        # min(500000, floor(804500*0.5)=402250, 17*50000=850000) == 402250
        assert claimed["final_award_cents"] == 402250, (
            f"expected final 402250, got {claimed['final_award_cents']}"
        )
        assert prov != claimed["final_award_cents"]


class TestGrantApprovalBoundary:
    def test_three_way_min_tie_awards_full_amount(self, api):
        """PRD §3.3: "`provisional_award_cents` is the smallest of three
        figures". "If that award exceeds the program's `available_cents`,
        approval fails with `ERR_GRANT_CAPACITY_EXCEEDED`" — an award equal to
        the available figure does not exceed it.

        Design: Difficulty/boundary_precision_check/grant_approve_award_exact_cap_boundary
        """
        gp = create_grant_program(code="GP-B", appropriation_cents=1000000,
                                  cap_per_trainee_cents=100000)
        emp = create_employer(legal_name="Xi Ltd", industry_code="562111",
                              contact_email="hr@xi.example")
        na = create_approved_assessment(emp["id"])
        ven = create_venue_for_mode("ON_CAMPUS", name="Free Lab", capacity=30,
                                    hourly_cost_cents=0)
        agr = create_signed_agreement(
            emp["id"], na["id"], pricing_model="PER_PARTICIPANT",
            delivery_mode="ON_CAMPUS", est_participant_count=20,
            est_delivery_hours=10, target_start_date="2026-06-15T00:00:00Z",
            max_cohorts=2, campus_venue_id=ven["id"],
        )
        # 450000+400000 tuition + 150000 materials + 0 venue = 1000000
        assert agr["quoted_total_cents"] == 1000000
        coh = create_cohort_under(agr["id"], delivery_mode="ON_CAMPUS",
                                  min_enrollment=1, venue_id=ven["id"],
                                  end_date="2026-06-19T00:00:00Z")
        enroll_participants(coh["id"], ["X01", "X02", "X03", "X04", "X05"])

        gap = create_grant_application_for_cohort(coh["id"], gp["id"], 500000)
        submit_and_review(gap["id"])
        approved = approve_application(gap["id"])
        # min(500000, floor(1000000*0.5)=500000, 5*100000=500000) == 500000
        assert approved["provisional_award_cents"] == 500000
        assert approved["reserved_cents"] == 500000
        prog = get_success_data(api_client.get_grant_program(gp["id"], GRANT))
        assert prog["available_cents"] == 500000
        assert prog["reserved_cents"] == 500000
        assert_program_fund_invariant(prog)

    def test_requested_below_share_and_cap_binds(self, api):
        """PRD §3.3: "`provisional_award_cents` is the smallest of three
        figures — the application's own `requested_cents`, the whole-cent
        floor of the agreement's `quoted_total_cents` multiplied by the
        program's `max_share_pct`, and the program's `cap_per_trainee_cents`
        multiplied by the cohort's `enrolled_count`."

        Design: Difficulty/boundary_precision_check/grant_approve_award_exact_cap_boundary
        """
        gp = create_grant_program(code="GP-B2", appropriation_cents=1000000,
                                  cap_per_trainee_cents=100000)
        emp = create_employer(legal_name="Xi Two", industry_code="562112",
                              contact_email="hr@xi2.example")
        na = create_approved_assessment(emp["id"])
        ven = create_venue_for_mode("ON_CAMPUS", name="Free Lab 2", capacity=30,
                                    hourly_cost_cents=0)
        agr = create_signed_agreement(
            emp["id"], na["id"], pricing_model="PER_PARTICIPANT",
            delivery_mode="ON_CAMPUS", est_participant_count=20,
            est_delivery_hours=10, target_start_date="2026-06-15T00:00:00Z",
            max_cohorts=2, campus_venue_id=ven["id"],
        )
        coh = create_cohort_under(agr["id"], delivery_mode="ON_CAMPUS",
                                  min_enrollment=1, venue_id=ven["id"],
                                  end_date="2026-06-19T00:00:00Z")
        enroll_participants(coh["id"], ["X01", "X02", "X03", "X04", "X05"])
        # One cent under the three-way tie: requested binds alone.
        gap = create_grant_application_for_cohort(coh["id"], gp["id"], 499999)
        submit_and_review(gap["id"])
        approved = approve_application(gap["id"])
        assert approved["provisional_award_cents"] == 499999
        assert approved["reserved_cents"] == 499999


class TestGrantClaimGate:
    def _delivered_with_approved_grant(self, api):
        gp = create_grant_program(code="GP-D", appropriation_cents=5000000)
        ctx = setup_launchable_cohort(
            num_participants=1, min_enrollment=1,
            sessions=[("2026-06-15T09:00:00Z", "2026-06-15T11:00:00Z")],
            agreement_overrides={"pricing_model": "FLAT_COHORT",
                                 "est_participant_count": 1,
                                 "est_delivery_hours": 2},
            participant_prefix="T",
        )
        gap = create_grant_application_for_cohort(ctx["cohort"]["id"], gp["id"], 10000)
        submit_and_review(gap["id"])
        approve_application(gap["id"])
        launch_cohort(ctx["cohort"]["id"])
        close_session_attendance(ctx["session_ids"][0], ctx["instructor"]["id"],
                                 [{"external_employee_ref": "T01", "attended_hours": 2}])
        ctx["cohort"] = get_success_data(api_client.get_cohort(ctx["cohort"]["id"], COORD))
        assert ctx["cohort"]["delivery_status"] == "DELIVERED"
        return ctx, gap

    def test_claim_before_credentialing_rejected(self, api):
        """PRD §3.3: "A `WorkforceCoordinator` may claim only once the cohort
        has reached `CREDENTIALED` (otherwise `ERR_COHORT_NOT_CREDENTIALED`)".

        Design: Difficulty/cross_entity_state_dependency/grant_claim_requires_cohort_credentialed
        """
        ctx, gap = self._delivered_with_approved_grant(api)
        resp = api_client.claim_grant_application(gap["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_COHORT_NOT_CREDENTIALED)

    def test_claim_after_credentialing_succeeds_with_final_award(self, api):
        """PRD §3.3: "`final_award_cents` is the smallest of the
        `requested_cents`, the whole-cent floor of the cohort's `FINAL`
        invoice gross multiplied by `max_share_pct` — where the relevant
        invoice is the cohort's `FINAL`-variant invoice in `DRAFT`, `ISSUED`,
        or `PAID`, and the gross term counts as zero when no such invoice
        exists — and `cap_per_trainee_cents` multiplied by the cohort's
        `completer_count`."

        Design: Difficulty/cross_entity_state_dependency/grant_claim_requires_cohort_credentialed
        """
        ctx, gap = self._delivered_with_approved_grant(api)
        coh_id = ctx["cohort"]["id"]
        validate_success(api_client.issue_credentials(coh_id, CRED))
        inv = validate_success(api_client.create_invoice(coh_id, {"variant": "FINAL"}, BILL), 201)
        # round(2*9000*1.15)=20700 + 1*7500 = 28200
        assert inv["gross_cents"] == 28200
        claimed = validate_success(api_client.claim_grant_application(gap["id"], COORD))
        assert claimed["status"] == "CLAIMED"
        # min(10000, floor(28200*0.5)=14100, 1*50000) == 10000
        assert claimed["final_award_cents"] == 10000


class TestGrantResubmitCycle:
    def test_returned_resubmit_review_cycle(self, api):
        """PRD §3.3: "Submission — from `DRAFT`, and again from `RETURNED` for
        resubmission"; "from there may return it for changes — optionally with
        `notes` — which cycles it to `RETURNED` for another submission round."

        Design: Difficulty/non_linear_state_machine/grant_application_returned_resubmit_cycle
        """
        gp = create_grant_program(code="GP-R", appropriation_cents=5000000)
        ctx = setup_launched_cohort(
            num_participants=1, min_enrollment=1,
            sessions=[("2026-06-15T09:00:00Z", "2026-06-15T11:00:00Z")],
            participant_prefix="R",
        )
        gap = create_grant_application_for_cohort(ctx["cohort"]["id"], gp["id"], 100000)
        submit_and_review(gap["id"])

        returned = validate_success(api_client.return_grant_application(gap["id"], GRANT))
        assert returned["status"] == "RETURNED"
        resubmitted = validate_success(api_client.submit_grant_application(gap["id"], COORD))
        assert resubmitted["status"] == "SUBMITTED"
        review2 = validate_success(api_client.start_review_grant_application(gap["id"], GRANT))
        assert review2["status"] == "UNDER_REVIEW"

    def test_resubmission_refreshes_submitted_at(self, api):
        """PRD §3.3: "each submission stamps `submitted_at` with the latest
        submission time and lands the application in `SUBMITTED`" — including
        the resubmission that closes the RETURNED -> SUBMITTED cycle.

        Design: Difficulty/non_linear_state_machine/grant_application_returned_resubmit_cycle
        """
        gp = create_grant_program(code="GP-R2", appropriation_cents=5000000)
        ctx = setup_launched_cohort(
            num_participants=1, min_enrollment=1,
            sessions=[("2026-06-15T09:00:00Z", "2026-06-15T11:00:00Z")],
            participant_prefix="R",
        )
        gap = create_grant_application_for_cohort(ctx["cohort"]["id"], gp["id"], 100000)
        first = validate_success(api_client.submit_grant_application(gap["id"], COORD))
        validate_success(api_client.start_review_grant_application(gap["id"], GRANT))
        validate_success(api_client.return_grant_application(gap["id"], GRANT))
        validate_success(api_client.set_clock({"to_iso8601": "2026-05-02T00:00:00Z"}, ADMIN))
        second = validate_success(api_client.submit_grant_application(gap["id"], COORD))
        assert second["status"] == "SUBMITTED"
        assert second["submitted_at"] != first["submitted_at"]


class TestGrantFundConservation:
    def test_approve_then_expiry_restores_ledger(self, api):
        """PRD §2.10: "These definitions imply a standing invariant —
        available plus reserved plus committed plus reimbursed always equals
        the appropriation — so an approval followed by its compensating
        release (a withdrawal or an expiry) leaves the four-figure tuple
        unchanged." PRD §3.9: "The grant-expiry sweep moves an `APPROVED`
        application whose `claim_by` has passed to the terminal `EXPIRED`,
        releasing its reservation".

        Design: Difficulty/compensating_invariant/grant_program_fund_conservation
        """
        gp = create_grant_program(code="GP-F", appropriation_cents=10000000,
                                  claim_deadline_days=60)
        # Application A: quoted 1025000 (n=20 PER_PARTICIPANT ON_SITE), 10 enrolled
        empA = create_employer(legal_name="Chi A", industry_code="332999",
                               contact_email="a@chi.example")
        naA = create_approved_assessment(empA["id"])
        agrA = create_signed_agreement(empA["id"], naA["id"],
                                       pricing_model="PER_PARTICIPANT",
                                       delivery_mode="ON_SITE",
                                       est_participant_count=20,
                                       est_delivery_hours=10,
                                       target_start_date="2026-06-01T00:00:00Z")
        cohA = create_cohort_under(agrA["id"], min_enrollment=1,
                                   start_date="2026-06-01T00:00:00Z",
                                   end_date="2026-06-05T00:00:00Z")
        enroll_participants(cohA["id"], [f"A{i:02d}" for i in range(1, 11)])
        gapA = create_grant_application_for_cohort(cohA["id"], gp["id"], 500000)
        submit_and_review(gapA["id"])
        approve_application(gapA["id"])  # min(500000, 512500, 500000) = 500000

        # Application B: FLAT_COHORT n=2 -> quoted 505000; 2 enrolled
        empB = create_employer(legal_name="Chi B", industry_code="333998",
                               contact_email="b@chi.example")
        naB = create_approved_assessment(empB["id"])
        agrB = create_signed_agreement(empB["id"], naB["id"], pricing_model="FLAT_COHORT",
                                       est_participant_count=2, est_delivery_hours=2,
                                       target_start_date="2026-06-01T00:00:00Z")
        cohB = create_cohort_under(agrB["id"], min_enrollment=1,
                                   start_date="2026-06-01T00:00:00Z",
                                   end_date="2026-06-01T00:00:00Z")
        enroll_participants(cohB["id"], ["B01", "B02"])
        gapB = create_grant_application_for_cohort(cohB["id"], gp["id"], 80000)
        submit_and_review(gapB["id"])
        approve_application(gapB["id"])  # min(80000, 252500, 100000) = 80000

        mid = get_success_data(api_client.get_grant_program(gp["id"], GRANT))
        assert mid["available_cents"] == 9420000
        assert mid["reserved_cents"] == 580000
        assert mid["committed_cents"] == 0
        assert mid["reimbursed_cents"] == 0
        assert_program_fund_invariant(mid)

        # claim_by = 2026-05-01 + 60d = 2026-06-30; sweep past it
        validate_success(api_client.set_clock({"to_iso8601": "2026-07-15T00:00:00Z"}, ADMIN))
        a_after = get_success_data(api_client.get_grant_application(gapA["id"], GRANT))
        b_after = get_success_data(api_client.get_grant_application(gapB["id"], GRANT))
        assert a_after["status"] == "EXPIRED"
        assert b_after["status"] == "EXPIRED"

        post = get_success_data(api_client.get_grant_program(gp["id"], GRANT))
        assert post["available_cents"] == 10000000
        assert post["reserved_cents"] == 0
        assert post["committed_cents"] == 0
        assert post["reimbursed_cents"] == 0
        assert_program_fund_invariant(post)

    def test_approve_claim_markpaid_conserves_funds(self, api):
        """PRD §2.10: "available plus reserved plus committed plus reimbursed
        always equals the appropriation" across approve (reserve), claim
        (convert), and mark_paid (disburse). PRD §3.3: "the program's
        committed figure decreases by the application's committed amount and
        its reimbursed figure increases by the same amount".

        Design: Difficulty/compensating_invariant/grant_program_fund_conservation
        """
        gp = create_grant_program(code="GP-F2", appropriation_cents=10000000)
        ctx = setup_launchable_cohort(
            num_participants=1, min_enrollment=1,
            sessions=[("2026-06-15T09:00:00Z", "2026-06-15T11:00:00Z")],
        )
        gap = create_grant_application_for_cohort(ctx["cohort"]["id"], gp["id"], 10000)
        submit_and_review(gap["id"])
        approved = approve_application(gap["id"])
        after_approve = get_success_data(api_client.get_grant_program(gp["id"], GRANT))
        assert_program_fund_invariant(after_approve)
        assert after_approve["reserved_cents"] == approved["provisional_award_cents"]

        launch_cohort(ctx["cohort"]["id"])
        close_session_attendance(ctx["session_ids"][0], ctx["instructor"]["id"],
                                 [{"external_employee_ref": "P01", "attended_hours": 2}])
        validate_success(api_client.issue_credentials(ctx["cohort"]["id"], CRED))
        validate_success(api_client.create_invoice(ctx["cohort"]["id"], {"variant": "FINAL"}, BILL), 201)
        claimed = validate_success(api_client.claim_grant_application(gap["id"], COORD))
        after_claim = get_success_data(api_client.get_grant_program(gp["id"], GRANT))
        assert_program_fund_invariant(after_claim)
        assert after_claim["committed_cents"] == claimed["final_award_cents"]
        assert after_claim["reserved_cents"] == 0

        validate_success(api_client.mark_paid_grant_application(gap["id"], GRANT))
        after_paid = get_success_data(api_client.get_grant_program(gp["id"], GRANT))
        assert_program_fund_invariant(after_paid)
        assert after_paid["reimbursed_cents"] == claimed["final_award_cents"]
        assert after_paid["committed_cents"] == 0


class TestStateVsFiscalPriority:
    def test_withdrawn_application_approve_reports_state_error(self, api):
        """PRD §2.8: "Incoming requests are validated in a fixed priority
        order, and the first failing check produces the error response", with
        item 5 generic state legality ordered before item 11 fiscal capacity.
        PRD §3.3: "A `GrantOfficer` approving an application under review
        first checks that the cohort has not been `CANCELLED` (otherwise
        `ERR_INVALID_STATE`)".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_grant_approve
        """
        gp = create_grant_program(code="GP-X", appropriation_cents=100000)
        # First application reserves the full appropriation.
        emp1 = create_employer(legal_name="Lambda One", industry_code="115111",
                               contact_email="hr@lambda.example")
        na1 = create_approved_assessment(emp1["id"])
        agr1 = create_signed_agreement(emp1["id"], na1["id"],
                                       pricing_model="PER_PARTICIPANT",
                                       est_participant_count=10, est_delivery_hours=2,
                                       target_start_date="2026-06-15T00:00:00Z",
                                       max_cohorts=1)
        coh1 = create_cohort_under(agr1["id"], min_enrollment=1)
        enroll_participants(coh1["id"], ["F01", "F02"])
        gap1 = create_grant_application_for_cohort(coh1["id"], gp["id"], 100000)
        submit_and_review(gap1["id"])
        approved1 = approve_application(gap1["id"])
        assert approved1["provisional_award_cents"] == 100000

        # Second application under review; then cascade-withdrawn.
        emp2 = create_employer(legal_name="Mu Two", industry_code="115112",
                               contact_email="hr@mu.example")
        na2 = create_approved_assessment(emp2["id"])
        agr2 = create_signed_agreement(emp2["id"], na2["id"], pricing_model="FLAT_COHORT",
                                       est_participant_count=5, est_delivery_hours=2,
                                       max_cohorts=1)
        coh2 = create_cohort_under(agr2["id"], min_enrollment=1)
        gap2 = create_grant_application_for_cohort(coh2["id"], gp["id"], 50000)
        submit_and_review(gap2["id"])
        validate_success(api_client.cancel_training_agreement(agr2["id"], COORD))
        withdrawn = get_success_data(api_client.get_grant_application(gap2["id"], GRANT))
        assert withdrawn["status"] == "WITHDRAWN"

        resp = api_client.approve_grant_application(gap2["id"], GRANT)
        # State violation (priority 5) beats fiscal capacity (priority 11).
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_approve_on_cancelled_cohort_rejected_with_invalid_state(self, api):
        """PRD §3.3: "A `GrantOfficer` approving an application under review
        first checks that the cohort has not been `CANCELLED` (otherwise
        `ERR_INVALID_STATE`)" — the state gate fires even with ample program
        funds available.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_grant_approve
        """
        gp = create_grant_program(code="GP-X2", appropriation_cents=10000000)
        emp = create_employer(legal_name="Mu Three", industry_code="115113",
                              contact_email="hr@mu3.example")
        na = create_approved_assessment(emp["id"])
        agr = create_signed_agreement(emp["id"], na["id"], pricing_model="FLAT_COHORT",
                                      est_participant_count=5, est_delivery_hours=2,
                                      max_cohorts=1)
        coh = create_cohort_under(agr["id"], min_enrollment=1)
        gap = create_grant_application_for_cohort(coh["id"], gp["id"], 50000)
        submit_and_review(gap["id"])
        validate_success(api_client.cancel_training_agreement(agr["id"], COORD))
        resp = api_client.approve_grant_application(gap["id"], GRANT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestGrantProgramLifecycle:
    def test_suspend_reopen_cycle(self, api):
        """PRD §3.3: "The same administrator may suspend a program (`OPEN` to
        `SUSPENDED`), reopen it (`SUSPENDED` back to `OPEN`)".

        Design: Corner/state_machines/grant_program_suspend_reopen_cycle
        """
        gp = create_grant_program(code="GP-CYC")
        suspended = validate_success(api_client.suspend_grant_program(gp["id"], ADMIN))
        assert suspended["status"] == "SUSPENDED"
        reopened = validate_success(api_client.reopen_grant_program(gp["id"], ADMIN))
        assert reopened["status"] == "OPEN"


class TestGrantWindowClosed:
    def test_submit_after_window_end_rejected(self, api):
        """PRD §3.3: "Submission — from `DRAFT`, and again from `RETURNED` for
        resubmission — requires the program to be `OPEN` (otherwise
        `ERR_GRANT_PROGRAM_NOT_OPEN`) and the current time to be no later than
        the program's `application_window_end` (otherwise
        `ERR_GRANT_WINDOW_CLOSED`)".

        Design: Corner/validations/grant_submit_after_window_closed_rejected
        """
        gp = create_grant_program(code="GP-W")
        ctx = setup_launchable_cohort(
            num_participants=0, min_enrollment=1, sessions=[],
            agreement_overrides={"pricing_model": "FLAT_COHORT",
                                 "target_start_date": "2026-08-15T00:00:00Z"},
        )
        gap = create_grant_application_for_cohort(ctx["cohort"]["id"], gp["id"], 10000)
        validate_success(api_client.set_clock({"to_iso8601": "2026-07-01T00:00:00Z"}, ADMIN))
        resp = api_client.submit_grant_application(gap["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_GRANT_WINDOW_CLOSED)


class TestGrantRbac:
    def test_coordinator_cannot_approve(self, api):
        """PRD §2.1: "`GrantOfficer` is the state grant counterpart: it
        reviews, returns, approves, and denies applications and marks
        reimbursements paid."
        PRD §2.1: "Once the headers are accepted, the caller's role must be
        listed among the roles authorized for the target endpoint, and any
        entity-backed ownership rule must hold; a failure here is rejected
        with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/coordinator_cannot_approve_grant_returns_403
        """
        gp = create_grant_program(code="GP-RB")
        ctx = setup_launchable_cohort(num_participants=0, min_enrollment=1, sessions=[])
        gap = create_grant_application_for_cohort(ctx["cohort"]["id"], gp["id"], 10000)
        submit_and_review(gap["id"])
        resp = api_client.approve_grant_application(gap["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        cur = get_success_data(api_client.get_grant_application(gap["id"], GRANT))
        assert cur["status"] == "UNDER_REVIEW"


class TestGrantExpirySweep:
    def test_approved_application_expires_and_releases_reservation(self, api):
        """PRD §3.9: "The grant-expiry sweep moves an `APPROVED` application
        whose `claim_by` has passed to the terminal `EXPIRED`, releasing its
        reservation: the program's reserved figure decreases by the
        application's `reserved_cents`, the available figure increases by the
        same amount, and the application's `reserved_cents` is zeroed."

        Design: Corner/cross_cutting_layers/grant_application_expiry_sweep_releases_reservation
        """
        gp = create_grant_program(code="GP-EX", appropriation_cents=1000000,
                                  application_window_end="2026-12-31T23:59:59Z",
                                  claim_deadline_days=60)
        ctx = setup_launchable_cohort(num_participants=2, min_enrollment=1, sessions=[])
        gap = create_grant_application_for_cohort(ctx["cohort"]["id"], gp["id"], 200000)
        submit_and_review(gap["id"])
        approved = approve_application(gap["id"])
        # min(200000, floor(505000*0.5)=252500, 2*50000=100000): cap binds
        assert approved["provisional_award_cents"] == 100000

        validate_success(api_client.set_clock({"to_iso8601": "2026-07-01T00:00:01Z"}, ADMIN))
        app_after = get_success_data(api_client.get_grant_application(gap["id"], GRANT))
        assert app_after["status"] == "EXPIRED"
        assert app_after["reserved_cents"] == 0
        prog_after = get_success_data(api_client.get_grant_program(gp["id"], GRANT))
        assert prog_after["available_cents"] == 1000000
        assert prog_after["reserved_cents"] == 0
