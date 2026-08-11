"""Exit plans, the settlement waterfall, termination, and remaining state-machine
error family (PRD §2.11, §3.2, §3.4, §3.6, §3.8)."""
from test_helpers import (
    ApiErrorId,
    begin_due_diligence,
    countersign,
    create_active_bundle,
    create_approved_bundle,
    create_approved_disbursement,
    create_approved_exit_plan,
    create_exit_plan_payload,
    create_findings_review,
    create_received_donation,
    create_submitted_disbursement,
    get_agreement,
    get_fund,
    get_project,
    make_applicant_headers,
    make_compliance_officer_headers,
    make_finance_officer_headers,
    make_project_lead_headers,
    make_sponsor_admin_headers,
    open_review,
    propose_exit_plan,
    review_decision_payload,
    sign_exit_plan,
    signoff_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestExitPlanGating:
    def test_second_exit_plan_rejected(self, api):
        """PRD §3.8: "a project may have at most one non-terminal plan — any plan in
        `PROPOSED`, `DUE_DILIGENCE`, or `APPROVED` blocks another create with
        `ERR_ACTIVE_EXIT_PLAN_EXISTS` (HTTP 409)."

        Design: Corner/validations/v_second_exit_plan_rejected
        """
        bundle = create_active_bundle("user_c_v13", project_name="XP", contact_email="xp@x.org")
        pid = bundle["project_id"]
        propose_exit_plan(pid, successor_entity_name="X", successor_ein="11-1111111")
        resp = api.create_exit_plan(
            pid,
            create_exit_plan_payload(successor_entity_name="Y", successor_ein="22-2222222",
                                     reason="r2"),
            make_project_lead_headers(pid))
        validate_error(resp, ApiErrorId.ERR_ACTIVE_EXIT_PLAN_EXISTS)

    def test_due_diligence_blocked_by_open_review(self, api):
        """PRD §3.8: "no review of the project may sit in `OPEN` or `ESCALATED`
        (`ERR_OPEN_COMPLIANCE_BLOCKS_EXIT` — note that a `FINDINGS_ISSUED` review does
        not block, because its open findings are priced into the reserve bucket at
        execution)"

        Design: Difficulty/cross_entity_state_dependency/exit_due_diligence_blocked_by_open_review
        """
        bundle = create_active_bundle("user_app_s", project_name="Tau", contact_email="t2@x.org")
        pid = bundle["project_id"]
        open_review(pid, review_type="SCHEDULED")
        plan = propose_exit_plan(pid, successor_entity_name="SpinCo",
                                 successor_ein="98-7654321", reason="independence")
        resp = api.begin_due_diligence(plan["id"], make_sponsor_admin_headers())
        validate_error(resp, ApiErrorId.ERR_OPEN_COMPLIANCE_BLOCKS_EXIT)

    def test_due_diligence_allowed_after_review_close(self, api):
        """PRD §3.8: "no review of the project may sit in `OPEN` or `ESCALATED`
        (`ERR_OPEN_COMPLIANCE_BLOCKS_EXIT` — note that a `FINDINGS_ISSUED` review does
        not block, because its open findings are priced into the reserve bucket at
        execution)"
        PRD §3.6: "Closure is allowed from `OPEN` only while `findings_count` is zero,
        and from `REMEDIATED` without condition"

        Design: Difficulty/cross_entity_state_dependency/exit_due_diligence_blocked_by_open_review
        """
        bundle = create_active_bundle("user_app_s2", project_name="Tau2",
                                      contact_email="t2b@x.org")
        pid = bundle["project_id"]
        review = open_review(pid, review_type="SCHEDULED")
        plan = propose_exit_plan(pid, successor_entity_name="SpinCo",
                                 successor_ein="98-7654321", reason="independence")
        validate_error(api.begin_due_diligence(plan["id"], make_sponsor_admin_headers()),
                       ApiErrorId.ERR_OPEN_COMPLIANCE_BLOCKS_EXIT)

        validate_success(api.close_review(review["id"], make_compliance_officer_headers()))
        entered = begin_due_diligence(plan["id"])
        assert entered["status"] == "DUE_DILIGENCE"


class TestExitSignoffForkJoin:
    def test_exit_signoff_fork_join(self, api):
        """PRD §3.8: "A party already present in `signoffs` is rejected with
        `ERR_SIGNOFF_PARTY_REPEATED`; a signer whose `X-User-ID` already appears as any
        entry's `signer_user_id` is rejected with `ERR_SIGNER_REUSED` — the three
        signers must be pairwise distinct users. Each accepted signoff appends an entry
        recording `party`, `signer_user_id`, and `signed_at`; the plan remains
        `DUE_DILIGENCE` through the first two, and the third distinct party joins the
        fork, moving the plan to `APPROVED`."

        Design: Corner/state_machines/sm_exit_signoff_fork_join
        """
        bundle = create_active_bundle("user_c_sj", project_name="SJ", contact_email="sj@x.org")
        pid = bundle["project_id"]
        plan = propose_exit_plan(pid, successor_entity_name="X", successor_ein="11-1111111")
        begin_due_diligence(plan["id"])

        s1 = sign_exit_plan(plan["id"], pid, "SPONSOR_BOARD", "user_sa_1")
        assert s1["status"] == "DUE_DILIGENCE", "first signoff does not complete the join"

        e1 = api.signoff_exit_plan(plan["id"], signoff_payload(party="SPONSOR_BOARD"),
                                   make_sponsor_admin_headers("user_sa_2"))
        validate_error(e1, ApiErrorId.ERR_SIGNOFF_PARTY_REPEATED)

        e2 = api.signoff_exit_plan(plan["id"], signoff_payload(party="SUCCESSOR_REP"),
                                   make_sponsor_admin_headers("user_sa_1"))
        validate_error(e2, ApiErrorId.ERR_SIGNER_REUSED)

        s2 = sign_exit_plan(plan["id"], pid, "PROJECT_LEAD", pid)
        assert s2["status"] == "DUE_DILIGENCE", "two distinct parties collected"

        s3 = sign_exit_plan(plan["id"], pid, "SUCCESSOR_REP", "user_sa_2")
        assert s3["status"] == "APPROVED", "the third distinct party fires the join"


class TestExitWaterfall:
    def _setup_min_branch_scenario(self, api, applicant_id, name, email):
        """COMPREHENSIVE project: received 1,087,000 (fee 86,960; available 1,000,040);
        disbursement 200,040 APPROVED_FOR_PAYMENT; review with 2 open findings;
        exit plan APPROVED."""
        bundle = create_active_bundle(applicant_id, project_name=name,
                                      budget_estimate_cents=900000000, contact_email=email)
        pid = bundle["project_id"]
        create_received_donation(pid, 1087000)
        create_approved_disbursement(pid, 200040, purpose="settled obligation",
                                     payee_name="Builders", spend_date="2026-06-10")
        create_findings_review(pid, 2, "HIGH")
        plan = create_approved_exit_plan(pid, successor_entity_name="Indie Corp",
                                         successor_ein="12-3456789", reason="spin off")
        return bundle, pid, plan

    def test_exit_waterfall_min_fee_branch_buckets(self, api):
        """PRD §3.8: "Bucket three, `exit_fee_cents`, is the greater of 50,000 cents
        and two percent of the base rounded half up to whole cents. Bucket four,
        `transfer_cents`, is the base minus the exit fee"
        PRD §3.8: "The four buckets always sum to exactly G — the waterfall permits no
        drift."
        G = 800,000 available + 200,040 committed = 1,000,040; base = 300,000; the
        percent branch computes 6,000 so the 50,000 minimum binds.

        Design: Difficulty/combinatorial_formula/exit_waterfall_evaluation_order_pinned
        """
        bundle, pid, plan = self._setup_min_branch_scenario(api, "user_app_g", "Eta", "h@x.org")
        executed = validate_success(api.execute_exit_plan(plan["id"],
                                                          make_sponsor_admin_headers()))
        assert executed["committed_payout_cents"] == 200040, "bucket 1: committed obligations"
        assert executed["reserve_cents"] == 500000, "bucket 2: 2 open findings x 250,000"
        assert executed["exit_fee_cents"] == 50000, "bucket 3: max(50,000, 6,000) minimum binds"
        assert executed["transfer_cents"] == 250000, "bucket 4: base 300,000 - fee 50,000"
        total = (executed["committed_payout_cents"] + executed["reserve_cents"]
                 + executed["exit_fee_cents"] + executed["transfer_cents"])
        assert total == 1000040, "buckets sum to exactly G (available + committed)"

    def test_exit_execute_settles_entities(self, api):
        """PRD §3.8: "The bucket-one requests are paid with `exit_settled` marked true
        — it is false on every ordinary payment"
        PRD §3.8: "The fund closes (its available balance lands at exactly zero, the
        reserve remaining held in `reserved_cents`), the agreement moves from `ACTIVE`
        to `SUPERSEDED_BY_INDEPENDENCE`, and the project moves from `ACTIVE` to
        `SPUN_OFF`, with the plan itself reaching `COMPLETED`."

        Design: Difficulty/combinatorial_formula/exit_waterfall_evaluation_order_pinned
        """
        bundle, pid, plan = self._setup_min_branch_scenario(api, "user_app_g2", "Eta2",
                                                            "h2@x.org")
        executed = validate_success(api.execute_exit_plan(plan["id"],
                                                          make_sponsor_admin_headers()))
        assert executed["status"] == "COMPLETED"

        assert get_project(pid)["status"] == "SPUN_OFF"
        assert get_agreement(bundle["agreement_id"])["status"] == "SUPERSEDED_BY_INDEPENDENCE"
        fund = get_fund(bundle["fund_account_id"])
        assert fund["status"] == "CLOSED"
        assert fund["available_cents"] == 0, "the waterfall settles the fund to zero available"
        assert fund["reserved_cents"] == 500000, "the reserve remains held"

        disbursements, _ = validate_paginated(
            api.list_disbursements(make_sponsor_admin_headers(),
                                   params={"project_id": pid}))
        assert len(disbursements) == 1
        assert disbursements[0]["status"] == "PAID"
        assert disbursements[0]["exit_settled"] is True

    def test_exit_fee_percent_branch_above_min(self, api):
        """PRD §3.8: "Bucket three, `exit_fee_cents`, is the greater of 50,000 cents
        and two percent of the base rounded half up to whole cents."
        Received 5,400,000 (fee 432,000; available 4,968,000); no findings and no
        commitments: base 4,968,000 -> fee 99,360 (percent branch) -> transfer
        4,868,640.

        Design: Corner/calculations/c_exit_fee_percent_branch_above_min
        """
        bundle = create_active_bundle("user_c_f9", project_name="F9",
                                      budget_estimate_cents=900000000, contact_email="f9@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 5400000)
        plan = create_approved_exit_plan(pid, successor_entity_name="X",
                                         successor_ein="11-1111111", reason="r")
        executed = validate_success(api.execute_exit_plan(plan["id"],
                                                          make_sponsor_admin_headers()))
        assert executed["reserve_cents"] == 0
        assert executed["committed_payout_cents"] == 0
        assert executed["exit_fee_cents"] == 99360, "two percent of the base exceeds the minimum"
        assert executed["transfer_cents"] == 4868640
        assert (executed["committed_payout_cents"] + executed["reserve_cents"]
                + executed["exit_fee_cents"] + executed["transfer_cents"]) == 4968000

    def test_exit_execute_insolvent_rejected(self, api):
        """PRD §3.8: "The base is G minus bucket one minus bucket two; a negative base
        rejects the execution with `ERR_EXIT_INSOLVENT` (HTTP 422)."
        G = 2,000 available + 90,000 committed = 92,000; reserve 250,000 (1 open
        finding) -> base -248,000.

        Design: Corner/validations/v_exit_execute_insolvent_rejected
        """
        bundle = create_active_bundle("user_c_v16", project_name="XI", contact_email="xi@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 100000)
        approved = create_approved_disbursement(pid, 90000, purpose="obligation",
                                                spend_date="2026-06-01")
        create_findings_review(pid, 1, "HIGH")
        plan = create_approved_exit_plan(pid, successor_entity_name="X",
                                         successor_ein="11-1111111", reason="r")
        resp = api.execute_exit_plan(plan["id"], make_sponsor_admin_headers())
        validate_error(resp, ApiErrorId.ERR_EXIT_INSOLVENT)

        plan_after = validate_success(api.get_exit_plan(plan["id"], make_sponsor_admin_headers()))
        assert plan_after["status"] == "APPROVED", "rejected execute leaves the plan APPROVED"
        fund = get_fund(bundle["fund_account_id"])
        assert fund["available_cents"] == 2000
        assert fund["committed_cents"] == 90000
        dr_after = validate_success(api.get_disbursement(approved["id"],
                                                         make_sponsor_admin_headers()))
        assert dr_after["status"] == "APPROVED_FOR_PAYMENT"


class TestTermination:
    def test_terminate_with_funds_rejected(self, api):
        """PRD §3.8: "a `SponsorAdmin` winds a project down with a `reason`, from
        either `ACTIVE` or `SUSPENDED`, but only when the fund's `available_cents`,
        `committed_cents`, and `reserved_cents` are all exactly zero — otherwise
        `ERR_FUNDS_REMAIN`."

        Design: Corner/validations/v_terminate_with_funds_rejected
        """
        bundle = create_active_bundle("user_c_v6", project_name="TF", contact_email="tf@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 100000)
        resp = api.terminate_project(pid, {"reason": "wind down"},
                                     make_sponsor_admin_headers())
        validate_error(resp, ApiErrorId.ERR_FUNDS_REMAIN)
        assert get_project(pid)["status"] == "ACTIVE"


class TestStateMachineErrorFamily:
    def test_state_machine_family(self, api):
        """PRD §2.11: "Seventh, state-machine guards: the target resource must be in a
        from-state of the requested transition, else the per-machine state error"
        PRD §3.2: "only an agreement in `PENDING_COUNTERSIGN` accepts a countersignature
        (any other state is rejected with `ERR_AGREEMENT_NOT_ACTIVE`)"
        PRD §3.8: "a `SponsorAdmin` winds a project down with a `reason`, from either
        `ACTIVE` or `SUSPENDED`"
        PRD §3.6: "the review moves from `OPEN` to `FINDINGS_ISSUED`"
        PRD §3.8: signoff collection proceeds while "the plan remains `DUE_DILIGENCE`"
        PRD §3.4: "High-value requests then face a `SponsorAdmin` decision from
        `PENDING_SPONSOR`"

        Design: Corner/errors/err_state_machine_family
        """
        bundle = create_approved_bundle("user_c_r1", project_name="ES", contact_email="es@x.org")
        pid = bundle["project_id"]
        agid = bundle["agreement_id"]

        # Terminate a PROPOSED project: from-states are ACTIVE or SUSPENDED only.
        e_proj = api.terminate_project(pid, {"reason": "too early"},
                                       make_sponsor_admin_headers())
        validate_error(e_proj, ApiErrorId.ERR_PROJECT_NOT_ACTIVE)

        # Countersign twice: the second call targets an ACTIVE agreement.
        countersign(agid, bundle["applicant_id"])
        e_agr = api.countersign_agreement(agid, make_applicant_headers(bundle["applicant_id"]))
        validate_error(e_agr, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

        # Issue findings on a CLOSED review (OPEN is the only from-state).
        review = open_review(pid, review_type="SCHEDULED")
        validate_success(api.close_review(review["id"], make_compliance_officer_headers()))
        e_rev = api.issue_findings(review["id"], {"findings_count": 1, "severity_max": "LOW"},
                                   make_compliance_officer_headers())
        validate_error(e_rev, ApiErrorId.ERR_REVIEW_STATE_INVALID)

        # Signoff on a PROPOSED exit plan (DUE_DILIGENCE is the from-state).
        plan = propose_exit_plan(pid, successor_entity_name="X", successor_ein="11-1111111")
        e_exit = api.signoff_exit_plan(plan["id"], signoff_payload(party="SPONSOR_BOARD"),
                                       make_sponsor_admin_headers())
        validate_error(e_exit, ApiErrorId.ERR_EXIT_STATE_INVALID)

        # Sponsor-approve a merely SUBMITTED request (PENDING_SPONSOR is the from-state).
        create_received_donation(pid, 100000)
        submitted = create_submitted_disbursement(pid, 5000)
        e_disb = api.sponsor_approve_disbursement(
            submitted["id"], review_decision_payload(decision="APPROVE"),
            make_sponsor_admin_headers())
        validate_error(e_disb, ApiErrorId.ERR_DISBURSEMENT_STATE_INVALID)
