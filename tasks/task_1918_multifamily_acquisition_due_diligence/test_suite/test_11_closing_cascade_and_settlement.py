"""Closing execution cascade, phase gates, termination compensation, and the
post-closing settlement lifecycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_approved_employee_decision,
    add_assumed_low_risk_policy,
    add_assumed_service_contract,
    create_adjustment_payload,
    create_employee_decision_payload,
    create_kicked_off_acquisition,
    create_service_contract_payload,
    generate_approved_statement,
    get_acquisition,
    get_success_data,
    make_underwriting_manager_headers,
    setup_pre_closing,
    setup_closed_acquisition,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
UM1 = TEST_USERS["underwriting_manager_headers"]
UM2 = make_underwriting_manager_headers("um-2")
UM3 = make_underwriting_manager_headers("um-3")
HR1 = TEST_USERS["hr_partner_headers"]
VM1 = TEST_USERS["vendor_manager_headers"]
EO1 = TEST_USERS["escrow_officer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]

CLOSING_CLOCK = "2026-09-12T00:00:00Z"


class TestExecuteClosingCascadeDepth4:
    def test_execute_closing_cascade_depth4(self, api):
        """PRD §3.1: "A successful closing stamps `closing_executed_at` from
        the logical clock and fires a cascade in a fixed order. First, every
        deposit entry in `ESCROW_QUEUED` moves to `TRANSFERRED`. Second,
        because those entries moved, the `DEPOSIT_TRANSFER` generated line on
        the `FINAL_CLOSING` statement is regenerated as the sum of
        `verified_amount_cents` plus `accrued_interest_cents` over all
        `TRANSFERRED` entries. Third, because that line changed, the
        statement's `total_buyer_credits_cents`, `total_seller_credits_cents`,
        and `net_amount_cents` recompute, and the acquisition's
        `net_proration_cents` re-derives from the statement. In parallel with
        the deposit chain, every service contract in `ASSUMED` moves to
        `TRANSFERRED` and every insurance policy in `ASSUMED` moves to
        `TRANSFERRED`."

        Design: Difficulty/transitive_cascade/execute_closing_cascade_depth4
        """
        # Fully advanced acquisition with an ASSUMED contract (300000/mo
        # prepaid to 2026-12-31) and an ASSUMED LOW policy (1200000/yr prepaid
        # to 2027-03-31); the FINAL statement is generated while the deposit is
        # still RECONCILED, so no DEPOSIT_TRANSFER line exists yet.
        ctx = setup_pre_closing(queue_deposit=False)
        acq_id = ctx["acq"]["id"]
        sc = add_assumed_service_contract(acq_id, prepaid_through_date="2026-12-31T00:00:00Z")
        pol = add_assumed_low_risk_policy(acq_id)
        stmt_f = generate_approved_statement(acq_id, "FINAL_CLOSING")
        # Baseline: RENT 93708 + TAX 1391781 buyer; PREPAID 1084930 + 657600 seller.
        assert stmt_f["total_buyer_credits_cents"] == 1_485_489
        assert stmt_f["net_amount_cents"] == -257_041
        get_success_data(api.queue_deposit_escrow(ctx["deposit"]["id"], EO1))
        get_success_data(api.set_clock(CLOSING_CLOCK, ADMIN))

        closed = validate_success(api.execute_closing(acq_id, UM1))
        assert closed["status"] == "CLOSED"
        assert closed["closing_executed_at"] == CLOSING_CLOCK

        # Hop 1: queued deposit + ASSUMED contract + ASSUMED policy transfer.
        deps, _ = validate_paginated(
            api.list_lease_deposits(ctx["lease"]["id"], EO1))
        assert deps[0]["status"] == "TRANSFERRED"
        assert get_success_data(api.get_service_contract(sc["id"], VM1))["status"] == "TRANSFERRED"
        assert get_success_data(api.get_insurance_policy(pol["id"], UM1))["status"] == "TRANSFERRED"

        # Hop 2: the DEPOSIT_TRANSFER line now exists with 153090 cents.
        lines, _ = validate_paginated(api.list_statement_lines(stmt_f["id"], UM1))
        dep_line = next(l for l in lines if l["line_type"] == "DEPOSIT_TRANSFER")
        assert dep_line["amount_cents"] == 153_090, "150000 + 3090"

        # Hop 3: statement totals recomputed.
        stmt_now = get_success_data(api.get_proration_statement(stmt_f["id"], UM1))
        assert stmt_now["total_buyer_credits_cents"] == 1_638_579
        assert stmt_now["net_amount_cents"] == -103_951

        # Hop 4: the acquisition net re-derives from the statement.
        acq_now = get_acquisition(acq_id)
        assert acq_now["net_proration_cents"] == -103_951

    def test_closing_cascade_regenerates_deposit_line_and_totals(self, api):
        """PRD §3.8: "Then a single deposit-transfer line of type
        `DEPOSIT_TRANSFER` and direction `CREDIT_BUYER`, summing
        `verified_amount_cents` plus `accrued_interest_cents` over every
        deposit ledger entry in `ESCROW_QUEUED` or `TRANSFERRED`."
        PRD §3.8: "The acquisition's `net_proration_cents` is the sum of
        `net_amount_cents` over its statements in `APPROVED` or `SETTLED`
        status — drafts, reviewed, and superseded statements are excluded — and
        is zero when no such statement exists."

        Design: Difficulty/transitive_cascade/execute_closing_cascade_depth4
        """
        ctx = setup_pre_closing(queue_deposit=False)
        acq_id = ctx["acq"]["id"]
        add_assumed_service_contract(acq_id, prepaid_through_date="2026-12-31T00:00:00Z")
        add_assumed_low_risk_policy(acq_id)
        stmt_f = generate_approved_statement(acq_id, "FINAL_CLOSING")
        pre_net = stmt_f["net_amount_cents"]
        pre_buyer = stmt_f["total_buyer_credits_cents"]

        get_success_data(api.queue_deposit_escrow(ctx["deposit"]["id"], EO1))
        get_success_data(api.set_clock(CLOSING_CLOCK, ADMIN))
        get_success_data(api.execute_closing(acq_id, UM1))

        lines, _ = validate_paginated(api.list_statement_lines(stmt_f["id"], UM1))
        dep_lines = [l for l in lines if l["line_type"] == "DEPOSIT_TRANSFER"]
        assert len(dep_lines) == 1 and dep_lines[0]["amount_cents"] == 153_090

        stmt_now = get_success_data(api.get_proration_statement(stmt_f["id"], UM1))
        assert stmt_now["total_buyer_credits_cents"] - pre_buyer == 153_090, (
            "the regenerated line raises buyer credits by the deposit transfer"
        )
        assert stmt_now["net_amount_cents"] == pre_net + 153_090
        assert get_acquisition(acq_id)["net_proration_cents"] == -103_951


class TestExecuteClosingRequiresDepositsQueued:
    def test_execute_closing_requires_deposits_queued(self, api):
        """PRD §3.1: "Executing closing moves `PRE_CLOSING` to `CLOSED` and is
        the heaviest gate in the system, checked in the order given: a
        `FINAL_CLOSING` statement in `APPROVED` status must exist (else
        `ERR_NO_APPROVED_FINAL_STATEMENT`); every deposit ledger entry must be
        `ESCROW_QUEUED` or `TRANSFERRED` (else `ERR_DEPOSITS_NOT_QUEUED`); no
        employee decision may remain `PROPOSED` (else
        `ERR_OPEN_DECISIONS_REMAIN`); and no service contract may remain
        `IDENTIFIED` or `UNDER_REVIEW` (else
        `ERR_OPEN_SERVICE_CONTRACTS_REMAIN`)."

        Design: Difficulty/cross_entity_state_dependency/execute_closing_requires_deposits_queued
        """
        ctx = setup_pre_closing(queue_deposit=False)
        acq_id = ctx["acq"]["id"]
        generate_approved_statement(acq_id, "FINAL_CLOSING")
        get_success_data(api.set_clock(CLOSING_CLOCK, ADMIN))

        resp = api.execute_closing(acq_id, UM1)
        validate_error(resp, ApiErrorId.ERR_DEPOSITS_NOT_QUEUED, 409)

        queued = get_success_data(api.queue_deposit_escrow(ctx["deposit"]["id"], EO1))
        assert queued["status"] == "ESCROW_QUEUED"
        closed = validate_success(api.execute_closing(acq_id, UM1))
        assert closed["status"] == "CLOSED"

        deps, _ = validate_paginated(
            api.list_lease_deposits(ctx["lease"]["id"], EO1))
        assert deps[0]["status"] == "TRANSFERRED", "the cascade transfers it"

    def test_queueing_unlocks_the_closing_transition(self, api):
        """PRD §3.10: "Once the acquisition reaches `PRE_CLOSING` — queueing
        earlier is rejected with `ERR_ACQUISITION_NOT_PRE_CLOSING` — an
        `EscrowOfficer` queues each reconciled entry for escrow, moving it to
        `ESCROW_QUEUED`. At closing, queued entries transfer per the §3.1
        cascade, each newly `TRANSFERRED` entry feeding the regenerated
        deposit-transfer line on the final statement."

        Design: Difficulty/cross_entity_state_dependency/execute_closing_requires_deposits_queued
        """
        ctx = setup_pre_closing(queue_deposit=False)
        acq_id = ctx["acq"]["id"]
        generate_approved_statement(acq_id, "FINAL_CLOSING")
        get_success_data(api.set_clock(CLOSING_CLOCK, ADMIN))

        # Deposit still RECONCILED: the transition is gated.
        resp = api.execute_closing(acq_id, UM1)
        validate_error(resp, ApiErrorId.ERR_DEPOSITS_NOT_QUEUED, 409)
        assert get_acquisition(acq_id)["status"] == "PRE_CLOSING"

        get_success_data(api.queue_deposit_escrow(ctx["deposit"]["id"], EO1))
        closed = get_success_data(api.execute_closing(acq_id, UM1))
        assert closed["status"] == "CLOSED"


class TestAdjustmentForkJoinDivergentAmounts:
    def test_adjustment_fork_join_divergent_amounts(self, api):
        """PRD §3.12: "From `EVIDENCED` the adjustment forks. Acceptance by an
        `UnderwritingManager` moves it to `ACCEPTED`. Dispute with a `reason`
        moves it to `DISPUTED`, from which resolution supplies an agreed
        `resolved_amount_cents` and lands it `RESOLVED`. The fork joins at
        application: applying an `ACCEPTED` adjustment posts its
        `amount_cents`; applying a `RESOLVED` one posts its
        `resolved_amount_cents` instead. Application lands the adjustment in
        the terminal `APPLIED` state and posts to the true-up ledger: if no
        `POST_CLOSING_TRUEUP` statement in `DRAFT` exists for the acquisition,
        one is created with its `day_count_method` copied from the
        `FINAL_CLOSING` statement, and an `ADJUSTMENT`-type line with
        `source_ref_type` `ADJUSTMENT` is appended carrying the posted amount,
        after which the statement's totals recompute."

        Design: Difficulty/non_linear_state_machine/adjustment_fork_join_divergent_amounts
        """
        ctx = setup_closed_acquisition()
        acq_id = ctx["acq"]["id"]

        # Branch 1: ASSERTED -> EVIDENCED -> ACCEPTED -> APPLIED posts amount_cents.
        adj1 = get_success_data(api.create_adjustment(
            create_adjustment_payload(acq_id, amount_cents=500_000), ANALYST), 201)
        get_success_data(api.evidence_adjustment(
            adj1["id"], {"evidence_note": "vendor invoice"}, ANALYST))
        get_success_data(api.accept_adjustment(adj1["id"], UM1))
        applied1 = validate_success(api.apply_adjustment(adj1["id"], UM1))
        assert applied1["status"] == "APPLIED"

        # Branch 2: ASSERTED -> EVIDENCED -> DISPUTED -> RESOLVED -> APPLIED
        # posts resolved_amount_cents (300000), not the asserted 700000.
        adj2 = get_success_data(api.create_adjustment(
            create_adjustment_payload(acq_id, amount_cents=700_000), ANALYST), 201)
        get_success_data(api.evidence_adjustment(
            adj2["id"], {"evidence_note": "utility true-up"}, ANALYST))
        get_success_data(api.dispute_adjustment(adj2["id"], "seller contests", UM1))
        get_success_data(api.resolve_adjustment(adj2["id"], 300_000, UM1))
        applied2 = validate_success(api.apply_adjustment(adj2["id"], UM1))
        assert applied2["status"] == "APPLIED"

        stmts, _ = validate_paginated(api.list_proration_statements(
            UM1, params={"acquisition_id": acq_id,
                         "statement_type": "POST_CLOSING_TRUEUP"}))
        assert len(stmts) == 1
        trueup = stmts[0]
        assert trueup["status"] == "DRAFT", "auto-created true-up opens DRAFT"
        assert trueup["day_count_method"] == "ACTUAL_365", (
            "copied from the FINAL_CLOSING statement"
        )

        lines, _ = validate_paginated(api.list_statement_lines(trueup["id"], UM1))
        amounts = sorted(l["amount_cents"] for l in lines)
        assert amounts == [300_000, 500_000], (
            "ACCEPTED posts amount_cents; RESOLVED posts resolved_amount_cents"
        )
        trueup_now = get_success_data(api.get_proration_statement(trueup["id"], UM1))
        assert trueup_now["total_buyer_credits_cents"] == 800_000
        assert trueup_now["net_amount_cents"] == 800_000

    def test_resolved_branch_posts_resolved_amount_not_asserted(self, api):
        """PRD §3.12: "Evidence, supplied by an analyst as an `evidence_note`
        together with an optional corrected `amount_cents`, moves the
        adjustment to `EVIDENCED`. When the corrected amount is supplied it
        replaces the asserted amount before any cap check runs."
        PRD §3.12: "Dispute with a `reason` moves it to `DISPUTED`, from which
        resolution supplies an agreed `resolved_amount_cents` and lands it
        `RESOLVED`. The fork joins at application: applying an `ACCEPTED`
        adjustment posts its `amount_cents`; applying a `RESOLVED` one posts
        its `resolved_amount_cents` instead."

        Design: Difficulty/non_linear_state_machine/adjustment_fork_join_divergent_amounts
        """
        ctx = setup_closed_acquisition()
        acq_id = ctx["acq"]["id"]

        adj = get_success_data(api.create_adjustment(
            create_adjustment_payload(acq_id, amount_cents=700_000), ANALYST), 201)
        get_success_data(api.evidence_adjustment(
            adj["id"], {"evidence_note": "utility true-up"}, ANALYST))
        get_success_data(api.dispute_adjustment(adj["id"], "seller contests", UM1))
        resolved = get_success_data(api.resolve_adjustment(adj["id"], 300_000, UM1))
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolved_amount_cents"] == 300_000

        get_success_data(api.apply_adjustment(adj["id"], UM1))
        stmts, _ = validate_paginated(api.list_proration_statements(
            UM1, params={"acquisition_id": acq_id,
                         "statement_type": "POST_CLOSING_TRUEUP"}))
        lines, _ = validate_paginated(
            api.list_statement_lines(stmts[0]["id"], UM1))
        assert len(lines) == 1
        assert lines[0]["amount_cents"] == 300_000
        assert lines[0]["line_type"] == "ADJUSTMENT"
        assert lines[0]["source_ref_type"] == "ADJUSTMENT"
        assert lines[0]["source_ref_id"] == adj["id"]


class TestExecuteClosingPreconditionGauntlet:
    def test_execute_closing_precondition_gauntlet(self, api):
        """PRD §3.1: "Executing closing moves `PRE_CLOSING` to `CLOSED` and is
        the heaviest gate in the system, checked in the order given: a
        `FINAL_CLOSING` statement in `APPROVED` status must exist (else
        `ERR_NO_APPROVED_FINAL_STATEMENT`); every deposit ledger entry must be
        `ESCROW_QUEUED` or `TRANSFERRED` (else `ERR_DEPOSITS_NOT_QUEUED`); no
        employee decision may remain `PROPOSED` (else
        `ERR_OPEN_DECISIONS_REMAIN`); and no service contract may remain
        `IDENTIFIED` or `UNDER_REVIEW` (else
        `ERR_OPEN_SERVICE_CONTRACTS_REMAIN`)."
        PRD §3.8: "Only `FINAL_CLOSING` and `POST_CLOSING_TRUEUP` statements
        are settlable — settling a `DRAFT_CLOSING` is rejected with
        `ERR_STATEMENT_NOT_SETTLABLE` — and the acquisition must be `CLOSED`
        (else `ERR_ACQUISITION_NOT_CLOSED`)."

        Design: Corner/state_machines/execute_closing_precondition_gauntlet
        """
        ctx = setup_pre_closing(queue_deposit=False)
        acq_id = ctx["acq"]["id"]
        # Extra open items: one PROPOSED decision, one UNDER_REVIEW contract.
        dec = get_success_data(api.create_employee_decision(
            create_employee_decision_payload(acq_id, employee_ref="emp-5",
                                             position="PORTER",
                                             hire_date="2024-06-01T00:00:00Z",
                                             accrued_pto_hours=10),
            HR1), 201)
        sc = get_success_data(api.create_service_contract(
            create_service_contract_payload(
                acq_id, vendor_name="CleanCo", service_type="LANDSCAPING",
                monthly_cost_cents=120000, cancellation_penalty_cents=50000),
            VM1), 201)
        get_success_data(api.begin_review_service_contract(sc["id"], VM1))

        # A DRAFT_CLOSING cannot settle (only FINAL/TRUEUP are settlable).
        resp0 = api.settle_statement(ctx["stmt_draft"]["id"], EO1)
        validate_error(resp0, ApiErrorId.ERR_STATEMENT_NOT_SETTLABLE, 409)

        # Gate 1: no APPROVED FINAL_CLOSING exists yet.
        resp1 = api.execute_closing(acq_id, UM1)
        validate_error(resp1, ApiErrorId.ERR_NO_APPROVED_FINAL_STATEMENT, 409)

        stmt_f = generate_approved_statement(acq_id, "FINAL_CLOSING")
        # A FINAL statement cannot settle while the acquisition is PRE_CLOSING.
        resp2 = api.settle_statement(stmt_f["id"], EO1)
        validate_error(resp2, ApiErrorId.ERR_ACQUISITION_NOT_CLOSED, 409)

        # Gate 2: deposit still RECONCILED.
        resp3 = api.execute_closing(acq_id, UM1)
        validate_error(resp3, ApiErrorId.ERR_DEPOSITS_NOT_QUEUED, 409)
        get_success_data(api.queue_deposit_escrow(ctx["deposit"]["id"], EO1))

        # Gate 3: decision still PROPOSED.
        resp4 = api.execute_closing(acq_id, UM1)
        validate_error(resp4, ApiErrorId.ERR_OPEN_DECISIONS_REMAIN, 409)
        get_success_data(api.reject_employee_decision(dec["id"], UM1, reason="keep"))

        # Gate 4: contract still UNDER_REVIEW.
        resp5 = api.execute_closing(acq_id, UM1)
        validate_error(resp5, ApiErrorId.ERR_OPEN_SERVICE_CONTRACTS_REMAIN, 409)
        get_success_data(api.assume_service_contract(sc["id"], VM1))

        get_success_data(api.set_clock(CLOSING_CLOCK, ADMIN))
        closed = validate_success(api.execute_closing(acq_id, UM1))
        assert closed["status"] == "CLOSED"


class TestTerminateFromPreClosing:
    def test_terminate_from_pre_closing_compensates_decisions_and_contracts(self, api):
        """PRD §3.1: "Termination is available from `DRAFT`, `IN_DILIGENCE`,
        `DILIGENCE_COMPLETE`, or `PRE_CLOSING` and lands in the terminal
        `TERMINATED` state. From any of the four phases, every employee
        decision in `APPROVED` or `NOTIFIED` is rescinded to `RESCINDED`,
        removing its contribution to `payroll_accrual_cents`. Terminating from
        `PRE_CLOSING` additionally unwinds the deal's vendor posture: every
        service contract in `ASSUMED` or `NOTICE_SENT` is force-moved to
        `CANCELLED_EFFECTIVE`."

        Design: Corner/state_machines/terminate_from_pre_closing_compensates_decisions_and_contracts
        """
        ctx = setup_pre_closing()
        acq_id = ctx["acq"]["id"]
        # Note: the acquisition passed complete-diligence BEFORE the decision
        # was added; employee approve requires IN_DILIGENCE, so the decision is
        # added and approved while the acquisition is still in diligence in a
        # fresh scenario below. Here we verify the PRE_CLOSING unwind path.
        sc = add_assumed_service_contract(acq_id)
        acq_now = get_acquisition(acq_id)
        assert acq_now["status"] == "PRE_CLOSING"

        terminated = validate_success(api.terminate_acquisition(acq_id, UM1))
        assert terminated["status"] == "TERMINATED"
        assert get_success_data(api.get_service_contract(sc["id"], VM1))["status"] == (
            "CANCELLED_EFFECTIVE"
        )

    def test_terminate_rescinds_approved_decisions_and_zeroes_accrual(self, api):
        """PRD §3.1: "Termination is available from `DRAFT`, `IN_DILIGENCE`,
        `DILIGENCE_COMPLETE`, or `PRE_CLOSING` and lands in the terminal
        `TERMINATED` state. From any of the four phases, every employee
        decision in `APPROVED` or `NOTIFIED` is rescinded to `RESCINDED`,
        removing its contribution to `payroll_accrual_cents`."
        PRD §3.11: "Rescission by the HR partner — or automatically when the
        acquisition terminates — moves an `APPROVED` or `NOTIFIED` decision to
        `RESCINDED` and removes its payroll-accrual contribution as
        compensation, though the computed `severance_cents` and
        `pto_payout_cents` remain on the record for audit."

        Design: Corner/state_machines/terminate_from_pre_closing_compensates_decisions_and_contracts
        """
        # IN_DILIGENCE path: approve a TERMINATE decision (accrual 400000),
        # then terminate.
        acq = create_kicked_off_acquisition(property_name="Abort Deal")
        dec = add_approved_employee_decision(acq["id"], employee_ref="emp-6",
                                             position="MAINTENANCE_TECH")
        assert get_acquisition(acq["id"])["payroll_accrual_cents"] == 400_000

        terminated = validate_success(api.terminate_acquisition(acq["id"], UM1))
        assert terminated["status"] == "TERMINATED"
        dec_now = get_success_data(api.get_employee_decision(dec["id"], HR1))
        assert dec_now["status"] == "RESCINDED"
        assert get_acquisition(acq["id"])["payroll_accrual_cents"] == 0


class TestPostClosingSettlementLifecycle:
    def test_post_closing_settlement_lifecycle(self, api):
        """PRD §3.1: "Settlement moves `CLOSED` to `SETTLED` and belongs to the
        `EscrowOfficer`. It requires four conditions: the logical clock must be
        strictly later than `closing_executed_at` plus `true_up_window_days`
        days (settling earlier is `ERR_TRUE_UP_WINDOW_OPEN`); the
        `FINAL_CLOSING` statement must be `SETTLED` (else
        `ERR_FINAL_STATEMENT_NOT_SETTLED`); every `POST_CLOSING_TRUEUP`
        statement that exists must be `SETTLED` (else
        `ERR_TRUEUP_STATEMENT_NOT_SETTLED`); and no post-closing adjustment may
        sit in any non-terminal status among `ASSERTED`, `EVIDENCED`,
        `ACCEPTED`, `DISPUTED`, or `RESOLVED` (else
        `ERR_OPEN_ADJUSTMENTS_REMAIN`)."
        PRD §3.12: "Assertion requires the acquisition to be `CLOSED` (else
        `ERR_ACQUISITION_NOT_CLOSED`) and requires the logical clock to be on
        or before `closing_executed_at` plus `true_up_window_days` days — an
        assertion after the window is rejected with
        `ERR_TRUE_UP_WINDOW_EXPIRED`."
        PRD §3.12: "Evidencing a collection-loss adjustment whose amount
        exceeds that cap is rejected with `ERR_ADJUSTMENT_EXCEEDS_CLAIMABLE`
        (HTTP 422); the evidence step accepts the two collection inputs
        `pre_closing_arrears_cents` and `collections_applied_cents` alongside
        the note."
        PRD §3.12: "the claimable cap is the lesser of
        `pre_closing_arrears_cents` (the tenant arrears existing at closing)
        and `collections_applied_cents` (the post-closing collections applied
        to those arrears)."

        Design: Corner/validations/post_closing_settlement_lifecycle
        """
        ctx = setup_closed_acquisition()
        acq_id = ctx["acq"]["id"]
        stmt_f = ctx["stmt_final"]

        # Settle while the true-up window is open (clock at closing day).
        resp1 = api.settle_acquisition(acq_id, EO1)
        validate_error(resp1, ApiErrorId.ERR_TRUE_UP_WINDOW_OPEN, 409)

        # True-up window: 90 days after 2026-09-12 -> deadline 2026-12-11.
        get_success_data(api.set_clock("2026-12-11T00:00:00Z", ADMIN))
        adj1 = get_success_data(api.create_adjustment(
            create_adjustment_payload(acq_id, adjustment_type="COLLECTION_LOSS",
                                      amount_cents=500_000), ANALYST), 201)
        assert adj1["status"] == "ASSERTED", "the deadline day is inclusive"
        adj2 = get_success_data(api.create_adjustment(
            create_adjustment_payload(acq_id, adjustment_type="COLLECTION_LOSS",
                                      amount_cents=700_001), ANALYST), 201)

        # One day past the window: assertion is rejected.
        get_success_data(api.set_clock("2026-12-12T00:00:00Z", ADMIN))
        resp2 = api.create_adjustment(
            create_adjustment_payload(acq_id, amount_cents=250_000), ANALYST)
        validate_error(resp2, ApiErrorId.ERR_TRUE_UP_WINDOW_EXPIRED, 409)

        # Settle blocked while FINAL is APPROVED (not SETTLED).
        resp3 = api.settle_acquisition(acq_id, EO1)
        validate_error(resp3, ApiErrorId.ERR_FINAL_STATEMENT_NOT_SETTLED, 409)

        get_success_data(api.settle_statement(stmt_f["id"], EO1))

        # Settle blocked while adjustments sit non-terminal.
        resp4 = api.settle_acquisition(acq_id, EO1)
        validate_error(resp4, ApiErrorId.ERR_OPEN_ADJUSTMENTS_REMAIN, 409)

        # COLLECTION_LOSS cap: min(800000 arrears, 500000 collections) = 500000.
        ev1 = validate_success(api.evidence_adjustment(
            adj1["id"], {"evidence_note": "resident ledger",
                         "pre_closing_arrears_cents": 800_000,
                         "collections_applied_cents": 500_000}, ANALYST))
        assert ev1["status"] == "EVIDENCED", "the cap is inclusive at 500000"

        resp5 = api.evidence_adjustment(
            adj2["id"], {"evidence_note": "overclaimed",
                         "pre_closing_arrears_cents": 800_000,
                         "collections_applied_cents": 500_000}, ANALYST)
        validate_error(resp5, ApiErrorId.ERR_ADJUSTMENT_EXCEEDS_CLAIMABLE, 422)

        # Corrected amount replaces the asserted amount BEFORE the cap check.
        ev2 = validate_success(api.evidence_adjustment(
            adj2["id"], {"evidence_note": "corrected claim",
                         "amount_cents": 500_000,
                         "pre_closing_arrears_cents": 800_000,
                         "collections_applied_cents": 500_000}, ANALYST))
        assert ev2["status"] == "EVIDENCED"

        get_success_data(api.accept_adjustment(adj1["id"], UM1))
        get_success_data(api.apply_adjustment(adj1["id"], UM1))
        get_success_data(api.accept_adjustment(adj2["id"], UM1))
        get_success_data(api.apply_adjustment(adj2["id"], UM1))

        stmts, _ = validate_paginated(api.list_proration_statements(
            UM1, params={"acquisition_id": acq_id,
                         "statement_type": "POST_CLOSING_TRUEUP"}))
        trueup = stmts[0]
        lines, _ = validate_paginated(api.list_statement_lines(trueup["id"], UM1))
        assert sorted(l["amount_cents"] for l in lines) == [500_000, 500_000]

        # Settle blocked while the true-up is still DRAFT.
        resp6 = api.settle_acquisition(acq_id, EO1)
        validate_error(resp6, ApiErrorId.ERR_TRUEUP_STATEMENT_NOT_SETTLED, 409)

        get_success_data(api.submit_statement_review(trueup["id"], UM2))
        get_success_data(api.approve_statement(trueup["id"], UM3))
        get_success_data(api.settle_statement(trueup["id"], EO1))

        settled = validate_success(api.settle_acquisition(acq_id, EO1))
        assert settled["status"] == "SETTLED"
        # net = FINAL (93708 + 1391781 + 153090) + true-up 1000000.
        assert settled["net_proration_cents"] == 2_638_579
