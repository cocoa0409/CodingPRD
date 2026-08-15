"""Reimbursement claims: fee cap, fiscal-year ceiling, budget guard at
payment, claim/certification staleness, revoke cascade, and the committed-pool
conservation invariant (PRD §3.3, §3.6, §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_claim,
    create_budget_line,
    create_claim,
    create_nurse,
    create_reimbursement_claim_payload,
    get_budget_line,
    get_nurse,
    list_bonuses,
    make_nurse_headers,
    make_program_admin_headers,
    pay_claim,
    run_ops_cycle,
    set_clock,
    setup_nurse_with_cert_and_bonus,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
PAYROLL = TEST_USERS["payroll_officer_headers"]


class TestClaimCreation:
    def test_claim_exceeds_exam_fee(self, api):
        """PRD §3.3: "Against a registered certification, the nurse files an
        exam-fee reimbursement claim naming the `certification_id` and a
        `claimed_amount_cents` that must be positive and may not exceed what
        remains of the certification's `exam_fee_cents` after amounts already
        approved or paid against that same certification; excess claims are
        rejected with `ERR_CLAIM_EXCEEDS_FEE` (HTTP 422)."

        Design: Corner/validations/claim_exceeds_exam_fee
        """
        ctx = setup_nurse_with_cert_and_bonus(
            employee_code="RN-CF1", exam_fee_cents=40000, with_budget_line=False
        )
        resp = api.create_reimbursement_claim(
            create_reimbursement_claim_payload(
                certification_id=ctx["certification"]["id"],
                claimed_amount_cents=50000,
            ),
            make_nurse_headers(ctx["nurse"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CLAIM_EXCEEDS_FEE, 422)


class TestReimbursementCap:
    def test_partial_approval_and_cap_exhaustion(self, api):
        """PRD §3.3: "The per-nurse fiscal-year ceiling is 150,000 cents
        ($1,500.00): the amounts already approved or paid on the nurse's claims
        in the same fiscal year are summed, the remainder under the ceiling is
        what room is left, and the claim's `approved_amount_cents` is set to
        the claimed amount or that remaining room, whichever is smaller, never
        below zero. When no room remains at all, approval is rejected with
        `ERR_REIMBURSEMENT_CAP_EXHAUSTED` (HTTP 402)..."

        Design: Corner/calculations/reimbursement_cap_partial_approval_arithmetic
        """
        set_clock("2026-08-01T00:00:00Z")
        create_budget_line("MED-2E", 2027, 9000000)
        nurse = create_nurse(employee_code="RN-RC2", full_name="Rc Two",
                             hire_date="2021-01-01T00:00:00Z")
        cert = None
        from test_helpers import create_certification  # local alias for clarity
        cert = create_certification(
            nurse["id"], track="SPECIALTY", exam_fee_cents=200000,
            obtained_on="2026-07-01T00:00:00Z", expires_on="2031-07-01T00:00:00Z",
        )
        nurse_headers = make_nurse_headers(nurse["id"])
        claim1 = validate_success(
            api.create_reimbursement_claim(
                create_reimbursement_claim_payload(
                    certification_id=cert["id"], claimed_amount_cents=120000
                ),
                nurse_headers,
            ),
            201,
        )
        approved1 = approve_claim(claim1["id"])
        assert approved1["approved_amount_cents"] == 120000

        claim2 = validate_success(
            api.create_reimbursement_claim(
                create_reimbursement_claim_payload(
                    certification_id=cert["id"], claimed_amount_cents=60000
                ),
                nurse_headers,
            ),
            201,
        )
        approved2 = approve_claim(claim2["id"])
        assert approved2["approved_amount_cents"] == 30000, (
            "second claim partially approved to the remaining 30000 under the "
            f"150000 ceiling, got {approved2['approved_amount_cents']}"
        )

        claim3 = validate_success(
            api.create_reimbursement_claim(
                create_reimbursement_claim_payload(
                    certification_id=cert["id"], claimed_amount_cents=10000
                ),
                nurse_headers,
            ),
            201,
        )
        resp = api.approve_reimbursement_claim(claim3["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_REIMBURSEMENT_CAP_EXHAUSTED, 402)


class TestClaimLifecycle:
    def test_claim_denied_terminal_no_approve(self, api):
        """PRD §3.3: "Denial instead requires a `denial_reason` and moves the
        claim to `DENIED`, a terminal state that frees nothing and commits
        nothing."
        PRD §2.8: "Next, the target resource must be in a state from which the
        requested transition exists, else `ERR_INVALID_STATE` (HTTP 409)..."

        Design: Corner/state_machines/claim_denied_terminal_no_approve
        """
        ctx = setup_nurse_with_cert_and_bonus(
            employee_code="RN-CL1", with_budget_line=False
        )
        claim = create_claim(ctx["certification"]["id"], ctx["nurse"]["id"], 30000)
        denied = validate_success(
            api.deny_reimbursement_claim(
                claim["id"], {"denial_reason": "late filing"}, ADMIN
            )
        )
        assert denied["status"] == "DENIED"
        resp = api.approve_reimbursement_claim(claim["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestBudgetGuardAtPayment:
    def test_pay_without_budget_headroom_fails(self, api):
        """PRD §3.3: "A failing guard rejects the payment with
        `ERR_BUDGET_EXCEEDED` (HTTP 402)."

        Design: Corner/validations/pay_without_budget_guard_fails
        """
        set_clock("2026-08-01T00:00:00Z")
        create_budget_line("MED-2E", 2027, 1)
        nurse = create_nurse(employee_code="RN-BG1", full_name="Bg One",
                             hire_date="2021-01-01T00:00:00Z")
        from test_helpers import create_certification
        cert = create_certification(nurse["id"], track="BASIC")
        claim = create_claim(cert["id"], nurse["id"], 30000)
        approve_claim(claim["id"])
        resp = api.pay_reimbursement_claim(claim["id"], PAYROLL)
        validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED, 402)


class TestStateBeatsFiscalOnPay:
    def _denied_claim_with_tiny_budget(self, api):
        """Claim in DENIED on a unit whose budget line (1 cent) would fail any
        payment guard."""
        set_clock("2026-08-01T00:00:00Z")
        create_budget_line("ICU-4W", 2027, 1)
        nurse = create_nurse(employee_code="RN-F", full_name="Nurse F",
                             hire_date="2021-01-01T00:00:00Z", home_unit="ICU-4W")
        from test_helpers import create_certification
        cert = create_certification(
            nurse["id"], track="SPECIALTY", exam_fee_cents=100000,
            obtained_on="2026-07-01T00:00:00Z", expires_on="2031-07-01T00:00:00Z",
        )
        claim = create_claim(cert["id"], nurse["id"], 50000)
        validate_success(
            api.deny_reimbursement_claim(
                claim["id"], {"denial_reason": "duplicate receipt"}, ADMIN
            )
        )
        return claim

    def test_pay_on_denied_claim_surfaces_invalid_state(self, api):
        """PRD §2.8: "Next, the target resource must be in a state from which
        the requested transition exists, else `ERR_INVALID_STATE` (HTTP 409)"
        PRD §2.8: "Business rules run last, and where several guard one
        operation they run in this pinned order..."

        The state rule (HTTP 409) therefore precedes the unit budget guard, a
        business rule, even though the 1-cent budget line would also fail.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_claim_pay
        """
        claim = self._denied_claim_with_tiny_budget(api)
        resp = api.pay_reimbursement_claim(claim["id"], PAYROLL)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_pay_on_submitted_claim_surfaces_invalid_state(self, api):
        """PRD §2.8: "Next, the target resource must be in a state from which
        the requested transition exists, else `ERR_INVALID_STATE` (HTTP 409)"
        PRD §2.8: "Business rules run last, and where several guard one
        operation they run in this pinned order..."
        PRD §3.3: "A successful payment moves the claim `APPROVED` to `PAID`
        and recomputes the budget commitment, since paid claims leave the
        committed pool."

        A claim still in SUBMITTED (never approved) has no pay transition; the
        state check must surface before the budget guard even though the 1-cent
        budget line would also fail.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_claim_pay
        """
        set_clock("2026-08-01T00:00:00Z")
        create_budget_line("ICU-4W", 2027, 1)
        nurse = create_nurse(employee_code="RN-F2", full_name="Nurse F2",
                             hire_date="2021-01-01T00:00:00Z", home_unit="ICU-4W")
        from test_helpers import create_certification
        cert = create_certification(nurse["id"], track="BASIC")
        claim = create_claim(cert["id"], nurse["id"], 30000)
        resp = api.pay_reimbursement_claim(claim["id"], PAYROLL)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestClaimApprovalStaleness:
    def _nurse_with_claim(self, api, expires_on="2026-08-10T00:00:00Z"):
        nurse = create_nurse(employee_code="RN-E", full_name="Nurse E",
                             hire_date="2021-01-01T00:00:00Z")
        from test_helpers import create_certification
        cert = create_certification(
            nurse["id"], track="BASIC", exam_fee_cents=40000,
            obtained_on="2023-08-01T00:00:00Z", expires_on=expires_on,
        )
        claim = create_claim(cert["id"], nurse["id"], 30000)
        return nurse, cert, claim

    def test_approve_rejected_after_certification_lapsed(self, api):
        """PRD §3.3: "The certification must still be `CURRENT` at decision
        time — a certification that has lapsed or been revoked between claim
        filing and approval makes the approval fail with `ERR_STALE_REFERENCE`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/claim_approve_gated_by_certification_current
        """
        set_clock("2026-08-01T00:00:00Z")
        _, cert, claim = self._nurse_with_claim(api)
        set_clock("2026-08-11T00:00:00Z")
        run_ops_cycle()
        assert get_certification_status(api, cert["id"]) == "LAPSED"
        resp = api.approve_reimbursement_claim(claim["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_REFERENCE, 409)

    def test_approve_rejected_after_certification_revoked(self, api):
        """PRD §3.3: "The certification must still be `CURRENT` at decision
        time — a certification that has lapsed or been revoked between claim
        filing and approval makes the approval fail with `ERR_STALE_REFERENCE`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/claim_approve_gated_by_certification_current
        """
        set_clock("2026-08-01T00:00:00Z")
        _, cert, claim = self._nurse_with_claim(api, expires_on="2031-08-10T00:00:00Z")
        validate_success(api.revoke_certification(cert["id"], ADMIN))
        resp = api.approve_reimbursement_claim(claim["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_REFERENCE, 409)


def get_certification_status(api, cert_id) -> str:
    from test_helpers import get_certification
    return get_certification(cert_id)["status"]


class TestClaimApproverSegregation:
    def test_claim_approver_is_claimant_sod(self, api):
        """PRD §3.3: "The approving administrator may not be the claiming
        nurse; a same-person approval is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/claim_approver_is_claimant_sod
        """
        ctx = setup_nurse_with_cert_and_bonus(
            employee_code="RN-SOD2", with_budget_line=False
        )
        claim = create_claim(ctx["certification"]["id"], ctx["nurse"]["id"], 30000)
        resp = api.approve_reimbursement_claim(
            claim["id"], make_program_admin_headers(ctx["nurse"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 422)


class TestCommittedPoolConservation:
    def _setup_paid_bonus_then_claim(self, api):
        """Unit committed pool returns to zero after the accrued bonus is paid,
        then a 90000 claim is filed."""
        set_clock("2026-08-01T00:00:00Z")
        ctx = setup_nurse_with_cert_and_bonus(
            employee_code="RN-U", home_unit="ICU-4W", track="SPECIALTY",
            exam_fee_cents=120000, obtained_on="2026-07-01T00:00:00Z",
            expires_on="2031-07-01T00:00:00Z", allocated_cents=9000000,
        )
        validate_success(api.pay_certification_bonus(ctx["bonus"]["id"], PAYROLL))
        claim = create_claim(ctx["certification"]["id"], ctx["nurse"]["id"], 90000)
        ctx["claim"] = claim
        return ctx

    def test_approve_adds_exactly_approved_amount_to_committed(self, api):
        """PRD §3.6: "It annualizes the active differentials — twelve months
        of each unit nurse's level-keyed monthly differential, summed over
        nurses whose `differential_status` is `ACTIVE` — then adds the
        approved-but-unpaid reimbursement claims of the line's fiscal year and
        the accrued-but-unpaid bonuses created within that fiscal year. Paid
        claims and paid bonuses have left the committed pool, and clawed-back
        or terminated items are excluded."

        Design: Difficulty/compensating_invariant/claim_approve_pay_conserves_unit_committed_pool
        """
        ctx = self._setup_paid_bonus_then_claim(api)
        line_id = ctx["budget_line"]["id"]
        committed0 = get_budget_line(line_id)["committed_cents"]
        assert committed0 == 0, (
            f"paid bonus must leave the committed pool, got {committed0}"
        )
        approved = approve_claim(ctx["claim"]["id"])
        assert approved["approved_amount_cents"] == 90000
        committed1 = get_budget_line(line_id)["committed_cents"]
        assert committed1 == 90000, (
            f"approval must add exactly the approved amount, got {committed1}"
        )

    def test_pay_removes_same_amount_conserving_pool(self, api):
        """PRD §3.3: "A successful payment moves the claim `APPROVED` to
        `PAID` and recomputes the budget commitment, since paid claims leave
        the committed pool."

        Design: Difficulty/compensating_invariant/claim_approve_pay_conserves_unit_committed_pool
        """
        ctx = self._setup_paid_bonus_then_claim(api)
        line_id = ctx["budget_line"]["id"]
        approve_claim(ctx["claim"]["id"])
        assert get_budget_line(line_id)["committed_cents"] == 90000
        paid = pay_claim(ctx["claim"]["id"])
        assert paid["status"] == "PAID"
        committed2 = get_budget_line(line_id)["committed_cents"]
        assert committed2 == 0, (
            f"approve+pay pair must conserve the pool at zero net drift, got {committed2}"
        )


class TestRevokeCascade:
    def _setup_paid_bonus(self, api):
        set_clock("2026-08-01T00:00:00Z")
        ctx = setup_nurse_with_cert_and_bonus(
            employee_code="RN-RC", home_unit="ICU-4W", track="SPECIALTY",
            exam_fee_cents=100000, hire_date="2021-08-01T00:00:00Z",
            obtained_on="2026-07-01T00:00:00Z", expires_on="2031-07-01T00:00:00Z",
            allocated_cents=9000000,
        )
        validate_success(api.pay_certification_bonus(ctx["bonus"]["id"], PAYROLL))
        return ctx

    def test_revoke_claws_back_paid_bonus(self, api):
        """PRD §3.3: "A `ProgramAdmin` may instead revoke a `CURRENT`
        certification outright; revocation claws back every bonus on that
        certification that is in `PAID` status and was paid within the trailing
        twelve months, flipping each to `CLAWED_BACK`, recomputes the holder's
        unit budget commitment as the clawback releases the commitment, and
        recomputes the holder's retention risk."

        Design: Difficulty/transitive_cascade/revoke_cascade_cert_to_bonus_to_budget_to_risk
        """
        ctx = self._setup_paid_bonus(api)
        line_id = ctx["budget_line"]["id"]
        committed_pre = get_budget_line(line_id)["committed_cents"]
        assert committed_pre == 0
        revoked = validate_success(
            api.revoke_certification(ctx["certification"]["id"], ADMIN)
        )
        assert revoked["status"] == "REVOKED"
        bonus = list_bonuses(ctx["certification"]["id"])[0]
        assert bonus["status"] == "CLAWED_BACK", (
            f"paid bonus within trailing 12 months must be clawed back, got {bonus['status']}"
        )
        committed_post = get_budget_line(line_id)["committed_cents"]
        assert committed_post == 0, (
            "paid-then-clawed-back must net to zero drift in the committed pool"
        )

    def test_revoke_recomputes_retention_risk(self, api):
        """PRD §3.7: "...each bonus clawed back in the trailing 24 months adds
        5..." and "The score decays with time and jumps with events, evaluated
        in a pinned order — decay first, then event bumps, then clamping.
        Decay measures whole years since the nurse's last advancement decision
        (or since `hire_date` if the nurse has never advanced) and subtracts
        ten points per whole year from the previous score, never below zero."

        Nurse hired 2021-08-01, clock 2026-08-01: previous score 0 decays to
        max(0, 0 - 40) = 0; a single clawback bump lands exactly +5.

        Design: Difficulty/transitive_cascade/revoke_cascade_cert_to_bonus_to_budget_to_risk
        """
        ctx = self._setup_paid_bonus(api)
        assert get_nurse(ctx["nurse"]["id"])["retention_risk_score"] == 0
        validate_success(api.revoke_certification(ctx["certification"]["id"], ADMIN))
        risk = get_nurse(ctx["nurse"]["id"])["retention_risk_score"]
        assert risk == 5, f"single clawback bump must yield risk 5, got {risk}"
