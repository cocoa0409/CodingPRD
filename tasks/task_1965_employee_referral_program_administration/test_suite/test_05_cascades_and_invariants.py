"""Cascade and invariant tests (PRD §3.2, §3.5, §3.6, §3.7)."""
from test_helpers import (
    validate_success,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_employee_headers,
    create_employee,
    create_active_policy,
    create_active_campaign,
    submit_referral,
    setup_program,
    setup_verified_tax_profile,
    advance_referral_to_offer,
    hire_referral,
    create_hired_referral,
    get_campaign,
    get_referral,
    get_employee,
    get_batch,
    get_milestone,
    get_hire_milestone,
    get_retention_milestone,
    create_open_batch,
    add_milestone_to_batch,
    remove_milestone_from_batch,
    set_clock,
    ops_evaluate,
    raise_abuse_case,
    confirm_abuse_case,
    assert_campaign_invariant,
    create_referral_payload,
    api_client,
)


class TestRetentionEarnExhaustsCampaign:
    def _setup_exact_budget_campaign(self, api):
        program = setup_program(
            req_overrides={"level": "SENIOR", "hard_to_fill": True, "req_number": "REQ-SR-1",
                           "title": "Sr Engineer"},
        )
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        camp = create_active_campaign(
            program["req"]["id"], budget_cents=200000, name="exact budget",
            window_start="2026-07-01T00:00:00Z", window_end="2027-06-30T00:00:00Z",
        )
        ref = submit_referral(emp["id"], program["req"]["id"], candidate_email="ca@x.com",
                              candidate_full_name="C A")
        advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
        hire_referral(ref["id"], program["hm"]["id"])
        return program, emp, camp, ref

    def test_retention_earn_converts_share_and_exhausts_campaign(self, api):
        """PRD §3.5: "any referral still `HIRED` whose `retention_due_at` has been reached
        and whose candidate is not `DEPARTED` moves to `COMPLETED`: the `RETENTION`
        milestone transitions from `PENDING` to `EARNED` with `earned_at` stamped, the
        retention uplift share (the referral's `campaign_uplift_cents` minus the hire
        share) moves from campaign `reserved_cents` to `spent_cents` — auto-exhausting the
        campaign if `spent_cents` reaches `budget_cents`".
        PRD §3.2: "When `spent_cents` reaches exactly `budget_cents` after a milestone
        earn converts reserved uplift, the campaign automatically moves from `ACTIVE` to
        `EXHAUSTED`".

        Sweep at retention_due (2027-01-28) earns the retention, converts the remaining
        140000 uplift share, and flips the campaign to EXHAUSTED.

        Design: Difficulty/transitive_cascade/retention_earn_exhausts_campaign
        """
        program, emp, camp, ref = self._setup_exact_budget_campaign(api)
        set_clock("2027-01-28T00:00:00Z")
        sweep = ops_evaluate()
        assert sweep["retention_earned"] == 1

        ref_now = get_referral(ref["id"])
        assert ref_now["status"] == "COMPLETED"

        camp_now = get_campaign(camp["id"])
        assert camp_now["spent_cents"] == 200000, (
            f"60000 hire share + 140000 retention share = 200000, got {camp_now['spent_cents']}"
        )
        assert camp_now["reserved_cents"] == 0
        assert camp_now["remaining_cents"] == 0
        assert camp_now["status"] == "EXHAUSTED"

    def test_retention_earn_milestone_amounts(self, api):
        """PRD §3.4: "the `RETENTION` milestone is created in `PENDING` with an
        `amount_cents` equal to the gross total minus the hire amount".
        PRD §3.5: "the `RETENTION` milestone transitions from `PENDING` to `EARNED` with
        `earned_at` stamped".

        The SENIOR+campaign gross is 500000; RETENTION is 350000 and flips to EARNED by
        the sweep.

        Design: Difficulty/transitive_cascade/retention_earn_exhausts_campaign
        """
        program, emp, camp, ref = self._setup_exact_budget_campaign(api)
        ms_ret = get_retention_milestone(ref["id"])
        assert ms_ret["status"] == "PENDING"
        assert ms_ret["amount_cents"] == 350000

        set_clock("2027-01-28T00:00:00Z")
        ops_evaluate()

        ms_after = get_milestone(ms_ret["id"])
        assert ms_after["status"] == "EARNED"
        assert ms_after["amount_cents"] == 350000


class TestAbuseConfirmForfeitsBatchedMilestone:
    def _setup_batched_milestone_with_case(self, api):
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        setup_verified_tax_profile(emp["id"])
        ref = submit_referral(emp["id"], program["req"]["id"], candidate_email="ca@x.com",
                              candidate_full_name="C A")
        advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
        hire_referral(ref["id"], program["hm"]["id"])
        ms_hire = get_hire_milestone(ref["id"])
        pp = TEST_USERS["payroll_processor_headers"]
        get_success_data(api.approve_milestone(ms_hire["id"], pp))
        batch = create_open_batch()
        add_milestone_to_batch(batch["id"], ms_hire["id"], batch["version"])
        case = raise_abuse_case(emp["id"], "RESUME_FARM", referral_id=ref["id"])
        return program, emp, ref, ms_hire, batch, case

    def test_confirm_forfeits_referral_milestone_and_recomputes_batch(self, api):
        """PRD §3.7: "if the case names a `referral_id` whose referral is still
        non-terminal — in any state from `SUBMITTED` through `HIRED` — that referral
        cascades to `FORFEITED` with `last_decision_reason` `ABUSE_CONFIRMED`: its
        milestones in `PENDING`, `EARNED`, `APPROVED`, or `BATCHED` move to `FORFEITED`
        (a `BATCHED` milestone first detaching from its batch with totals recomputing and
        the batch `version` incrementing)".

        Confirming the case forfeits the referral, forfeits+detaches the BATCHED
        milestone, and recomputes the batch totals to zero.

        Design: Difficulty/transitive_cascade/abuse_confirm_forfeits_batched_milestone
        """
        program, emp, ref, ms_hire, batch, case = self._setup_batched_milestone_with_case(api)
        confirm_abuse_case(case["id"], resolution_note="confirmed farm")

        ref_now = get_referral(ref["id"])
        assert ref_now["status"] == "FORFEITED"
        assert ref_now["last_decision_reason"] == "ABUSE_CONFIRMED"

        ms_now = get_milestone(ms_hire["id"])
        assert ms_now["status"] == "FORFEITED"
        assert ms_now.get("payroll_batch_id") is None

        batch_now = get_batch(batch["id"])
        assert batch_now["total_gross_cents"] == 0
        assert batch_now["milestone_count"] == 0
        # version: create=1, add=2, cascade detach=3
        assert batch_now["version"] == 3, f"expected batch version 3, got {batch_now['version']}"

        # PENDING retention milestone also forfeited
        ms_ret = get_retention_milestone(ref["id"])
        assert ms_ret["status"] == "FORFEITED"

    def test_confirm_records_strike_and_risk_score(self, api):
        """PRD §3.7: "Confirming a case stamps `confirmed_at` with the logical clock,
        records `decided_by_user_id`, accepts an optional `resolution_note`, and unleashes
        the full cascade: the employee's `fraud_strikes` increases by one; their
        `risk_score` is recomputed (below) and the employee becomes `referral_suspended`
        if the score reaches at least 100". "Each case carries a computed `risk_weight`:
        40 for `SELF_REFERRAL`, 25 for `VELOCITY`, 35 for `DUPLICATE_RING`, 50 for
        `RESUME_FARM`, and 20 for `MANUAL`."

        One RESUME_FARM confirmation yields fraud_strikes 1 and risk_score 50.

        Design: Difficulty/transitive_cascade/abuse_confirm_forfeits_batched_milestone
        """
        program, emp, ref, ms_hire, batch, case = self._setup_batched_milestone_with_case(api)
        confirm_abuse_case(case["id"], resolution_note="confirmed farm")

        emp_now = get_employee(emp["id"])
        assert emp_now["fraud_strikes"] == 1
        assert emp_now["risk_score"] == 50


class TestCampaignBudgetConservationThroughLifecycle:
    def _setup(self, api):
        program = setup_program(
            req_overrides={"level": "SENIOR", "hard_to_fill": True, "req_number": "REQ-SR-1",
                           "title": "Sr Engineer"},
        )
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        camp = create_active_campaign(
            program["req"]["id"], budget_cents=200000, name="conserve",
            window_start="2026-07-01T00:00:00Z", window_end="2027-06-30T00:00:00Z",
        )
        ref = submit_referral(emp["id"], program["req"]["id"], candidate_email="ca@x.com",
                              candidate_full_name="C A")
        return program, emp, camp, ref

    def test_campaign_budget_conservation_checkpoints(self, api):
        """PRD §3.2: "A pinned invariant holds at all times: reserved plus spent plus
        remaining always equals `budget_cents`, and all three are non-negative."
        PRD §3.3: "Attachment also reserves budget: the campaign's `reserved_cents`
        increases by the referral's `campaign_uplift_cents`".
        PRD §3.4: "If a campaign is attached, the hire uplift share — the referral's
        `campaign_uplift_cents` multiplied by `hire_pct` and divided by 100, rounded
        half-up, with the retention uplift share defined as the remainder of
        `campaign_uplift_cents` after the hire share — moves from the campaign's
        `reserved_cents` into its `spent_cents`".

        Checkpoints: after submit 200000/0/0; after hire 140000/60000/0; after the
        retention sweep 0/200000/0 (EXHAUSTED).

        Design: Difficulty/compensating_invariant/campaign_budget_conservation_through_lifecycle
        """
        program, emp, camp, ref = self._setup(api)
        c1 = get_campaign(camp["id"])
        assert (c1["reserved_cents"], c1["spent_cents"], c1["remaining_cents"]) == (200000, 0, 0)
        assert_campaign_invariant(c1)

        advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
        hire_referral(ref["id"], program["hm"]["id"])
        c2 = get_campaign(camp["id"])
        assert (c2["reserved_cents"], c2["spent_cents"], c2["remaining_cents"]) == (140000, 60000, 0)
        assert_campaign_invariant(c2)

        set_clock("2027-01-28T00:00:00Z")
        ops_evaluate()
        c3 = get_campaign(camp["id"])
        assert (c3["reserved_cents"], c3["spent_cents"], c3["remaining_cents"]) == (0, 200000, 0)
        assert c3["status"] == "EXHAUSTED"
        assert_campaign_invariant(c3)

    def test_campaign_budget_restored_after_milestone_forfeiture(self, api):
        """PRD §3.6: "a `PayrollProcessor` or `ComplianceOfficer` may forfeit a milestone
        in `EARNED` or `APPROVED` status by supplying a `reason`, moving it to `FORFEITED`
        and releasing the corresponding earned campaign share from the attached campaign's
        `spent_cents`."
        PRD §3.2: "when a later forfeit or clawback release pushes `spent_cents` back below
        `budget_cents`, the campaign automatically returns from `EXHAUSTED` to `ACTIVE`."

        After both EARNED milestones are forfeited the counters are fully restored
        (0/0/200000) and the campaign flips EXHAUSTED -> ACTIVE. (The abuse-confirm
        cascade is not available here: per PRD §3.7 it fires only while the referral
        is "still non-terminal — in any state from `SUBMITTED` through `HIRED`", and
        the retention sweep has moved this referral to COMPLETED.)

        Design: Difficulty/compensating_invariant/campaign_budget_conservation_through_lifecycle
        """
        program, emp, camp, ref = self._setup(api)
        advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
        hire_referral(ref["id"], program["hm"]["id"])
        set_clock("2027-01-28T00:00:00Z")
        ops_evaluate()
        c3 = get_campaign(camp["id"])
        assert c3["status"] == "EXHAUSTED"
        assert (c3["reserved_cents"], c3["spent_cents"], c3["remaining_cents"]) == (0, 200000, 0)

        co = TEST_USERS["compliance_officer_headers"]
        hire_ms = get_hire_milestone(ref["id"])
        ret_ms = get_retention_milestone(ref["id"])

        # Forfeiting the HIRE milestone releases the hire share (60000) from spent,
        # which already flips the campaign back below budget.
        get_success_data(api.forfeit_milestone(hire_ms["id"], {"reason": "compliance clawback"}, co))
        c4 = get_campaign(camp["id"])
        assert (c4["reserved_cents"], c4["spent_cents"], c4["remaining_cents"]) == (0, 140000, 60000)
        assert c4["status"] == "ACTIVE", (
            f"campaign must return EXHAUSTED -> ACTIVE when spent drops below budget, got {c4['status']}"
        )

        get_success_data(api.forfeit_milestone(ret_ms["id"], {"reason": "compliance clawback"}, co))
        c5 = get_campaign(camp["id"])
        assert (c5["reserved_cents"], c5["spent_cents"], c5["remaining_cents"]) == (0, 0, 200000)
        assert c5["status"] == "ACTIVE"
        assert_campaign_invariant(c5)


class TestPayrollBatchTotalConservation:
    def _setup_two_approved_milestones(self, api):
        program = setup_program(req_overrides={"openings": 5})
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        setup_verified_tax_profile(emp["id"])
        refs = []
        for email, name in (("c1@x.com", "C One"), ("c2@x.com", "C Two")):
            ref = submit_referral(emp["id"], program["req"]["id"], candidate_email=email,
                                  candidate_full_name=name)
            advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
            hire_referral(ref["id"], program["hm"]["id"])
            refs.append(ref)
        ms1 = get_hire_milestone(refs[0]["id"])
        ms2 = get_hire_milestone(refs[1]["id"])
        pp = TEST_USERS["payroll_processor_headers"]
        get_success_data(api.approve_milestone(ms1["id"], pp))
        get_success_data(api.approve_milestone(ms2["id"], pp))
        batch = create_open_batch()
        return program, emp, refs, ms1, ms2, batch

    def test_batch_totals_through_add_and_remove(self, api):
        """PRD §3.6: "`total_gross_cents` is the sum of `amount_cents` over attached
        `BATCHED` milestones minus the `amount_cents` of attached `CLAWED_BACK` recovery
        lines; `total_withholding_cents` sums `withholding_cents` over the attached
        `BATCHED` milestones; `total_net_cents` is gross minus withholding; and
        `milestone_count` counts all attached lines, payout and recovery alike." and
        "Removing a milestone — again guarded by `expected_payroll_batch_version` —
        returns a `BATCHED` milestone to `APPROVED` and clears its `payroll_batch_id`".

        Two 45000 lines give gross 90000 / withholding 19800 / net 70200; removing one
        halves it.

        Design: Difficulty/compensating_invariant/payroll_batch_total_conservation_through_add_remove_cancel
        """
        program, emp, refs, ms1, ms2, batch = self._setup_two_approved_milestones(api)
        b1 = add_milestone_to_batch(batch["id"], ms1["id"], batch["version"])
        assert b1["total_gross_cents"] == 45000

        b2 = add_milestone_to_batch(batch["id"], ms2["id"], b1["version"])
        assert b2["total_gross_cents"] == 90000
        assert b2["total_withholding_cents"] == 19800
        assert b2["total_net_cents"] == 70200
        assert b2["milestone_count"] == 2

        b3 = remove_milestone_from_batch(batch["id"], ms1["id"], b2["version"])
        assert b3["total_gross_cents"] == 45000
        assert b3["milestone_count"] == 1
        assert b3["total_net_cents"] == b3["total_gross_cents"] - b3["total_withholding_cents"]

        ms1_now = get_milestone(ms1["id"])
        assert ms1_now["status"] == "APPROVED"
        assert ms1_now.get("payroll_batch_id") is None

    def test_batch_cancel_zeroes_totals_and_returns_milestones(self, api):
        """PRD §3.6: "A batch that is still `OPEN` may instead be cancelled by the
        `PayrollProcessor`: every attached `BATCHED` milestone returns to `APPROVED`
        detached".

        After cancel the batch is CANCELLED with zero totals and the milestone returns to
        APPROVED.

        Design: Difficulty/compensating_invariant/payroll_batch_total_conservation_through_add_remove_cancel
        """
        program, emp, refs, ms1, ms2, batch = self._setup_two_approved_milestones(api)
        b1 = add_milestone_to_batch(batch["id"], ms1["id"], batch["version"])
        b2 = add_milestone_to_batch(batch["id"], ms2["id"], b1["version"])
        assert b2["total_gross_cents"] == 90000

        pp = TEST_USERS["payroll_processor_headers"]
        get_success_data(api.cancel_payroll_batch(batch["id"], pp))
        b_now = get_batch(batch["id"])
        assert b_now["status"] == "CANCELLED"
        assert b_now["total_gross_cents"] == 0
        assert b_now["milestone_count"] == 0

        ms2_now = get_milestone(ms2["id"])
        assert ms2_now["status"] == "APPROVED"
