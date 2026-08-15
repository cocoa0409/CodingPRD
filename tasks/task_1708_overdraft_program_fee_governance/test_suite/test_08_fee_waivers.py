"""Fee waiver requests (PRD §3.6): allocation and rounding, authority-band
routing, auto-apply, approval/denial guards, escalation, and the
deny-appeal cycle."""
from test_helpers import (
    ApiErrorId,
    authorize,
    get_account,
    get_fee,
    get_waiver_request,
    list_fees,
    list_waiver_items,
    make_opted_in_account,
    make_posted_fee_scenario,
    make_program,
    open_batch,
    run_posting_day,
    seal_batch,
    set_clock,
    settle_batch,
    submit_waiver,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    COMPLIANCE,
    MANAGER,
    TELLER,
    TELLER_3,
)
from test_helpers.test_users import (
    make_account_holder_headers,
    make_supervisor_headers,
)


class TestWaiverPercentRoundingPerItemThenSum:
    def _setup(self):
        """OVERDRAFT fee 3625 POSTED and SUSTAINED fee 2451 POSTED on one
        account (sustained threshold 1), ledger -6976."""
        program = make_program(
            name="OD-B", fee_amount_cents=3625, daily_fee_cap_cents=100000,
            max_daily_fees_count=10, de_minimis_threshold_cents=100,
            sustained_overdraft_days_threshold=1,
            sustained_overdraft_fee_cents=2451, steering_fee_count_threshold=99)
        account, _ = make_opted_in_account(program["id"], holder_name="Holder B",
                                           channel="PHONE")
        run_posting_day(program["id"], "2026-08-03", account["id"],
                        [("CREDIT_DEPOSIT", 100)], settle=True)
        run_posting_day(program["id"], "2026-08-04", account["id"],
                        [("DEBIT_ONE_TIME", 1000)], settle=True)
        overdraft = list_fees(account_id=account["id"], fee_type="OVERDRAFT")[0]
        sustained = list_fees(account_id=account["id"], fee_type="SUSTAINED")[0]
        return program, account, overdraft, sustained

    def test_percent_waiver_rounds_half_up_per_item_then_sums(self, api):
        """PRD §3.6: "Under `PERCENT_BPS`, each item's allocation is its
        `outstanding_cents` multiplied by `percent_bps` and divided by 10000,
        rounded half up **per item first**, with the total formed by summing
        the rounded per-item amounts — rounding after summing can differ by a
        cent and is forbidden."
        PRD §3.6: "When a staff member — a `Teller`, `Supervisor`, or `Manager`
        — submits a request whose total sits at or below the teller cap, the
        request is auto-approved and born `APPLIED`: the allocations are
        applied immediately, exactly as at approval time."

        Design: Difficulty/combinatorial_formula/waiver_percent_rounding_per_item_then_sum
        """
        _, account, overdraft, sustained = self._setup()
        request = submit_waiver(
            account["id"], [overdraft["id"], sustained["id"]],
            kind="PERCENT_BPS", percent_bps=5000, reason_code="GOODWILL",
            headers=make_supervisor_headers("sup-9"))
        # round_half_up(3625*5000/10000)=1813; round_half_up(2451*5000/10000)
        # =1226; per-item-then-sum = 3039 (sum-then-round would give 3038).
        assert request["status"] == "APPLIED"  # 3039 <= teller cap, staff
        assert request["computed_total_cents"] == 3039

        item1 = list_waiver_items(fee_id=overdraft["id"])[0]
        item2 = list_waiver_items(fee_id=sustained["id"])[0]
        assert item1["waived_cents"] == 1813
        assert item2["waived_cents"] == 1226

    def test_partial_percent_waiver_leaves_fees_posted_and_credits_ledger(self, api):
        """PRD §3.6: "any fee whose `outstanding_cents` thereby reaches zero
        flips to `WAIVED` — partial waivers leave a fee in its current status
        with a reduced `outstanding_cents`, and only a zero outstanding
        produces `WAIVED`."
        PRD §3.6: "The account's ledger is credited by the total waived amount,
        `lifetime_fees_waived_cents` grows by the same total".

        Design: Difficulty/combinatorial_formula/waiver_percent_rounding_per_item_then_sum
        """
        _, account, overdraft, sustained = self._setup()
        submit_waiver(account["id"], [overdraft["id"], sustained["id"]],
                      kind="PERCENT_BPS", percent_bps=5000,
                      reason_code="GOODWILL",
                      headers=make_supervisor_headers("sup-9"))

        fee1 = get_fee(overdraft["id"])
        fee2 = get_fee(sustained["id"])
        assert fee1["outstanding_cents"] == 1812  # 3625 - 1813
        assert fee1["status"] == "POSTED"
        assert fee2["outstanding_cents"] == 1225  # 2451 - 1226
        assert fee2["status"] == "POSTED"

        after = get_account(account["id"])
        assert after["ledger_balance_cents"] == -3937  # -6976 + 3039 credited
        assert after["lifetime_fees_waived_cents"] == 3039


class TestWaiverRequestDenyAppealCycle:
    def _setup(self):
        """Two POSTED fees of 3500 each on one account, ledger -9400; a FULL
        request (computed 7000) submitted by a teller."""
        program = make_program(name="OD-W", daily_fee_cap_cents=100000,
                               max_daily_fees_count=10)
        account, _ = make_opted_in_account(program["id"], holder_name="Holder W")
        run_posting_day(program["id"], "2026-08-03", account["id"],
                        [("CREDIT_DEPOSIT", 100)], settle=True)
        run_posting_day(program["id"], "2026-08-04", account["id"],
                        [("DEBIT_ONE_TIME", 2000), ("DEBIT_ONE_TIME", 500)],
                        settle=True, clock_times=["2026-08-04T09:00:00Z",
                                                  "2026-08-04T09:01:00Z"])
        fees = list_fees(account_id=account["id"])
        assert len(fees) == 2
        request = submit_waiver(account["id"], [f["id"] for f in fees],
                                kind="FULL", reason_code="HARDSHIP",
                                headers=TELLER)
        return account, fees, request

    def test_deny_appeal_cycle_walks_up_the_bands(self, api):
        """PRD §3.6: "Denying a `PENDING_SUPERVISOR` request — available to
        `Supervisor`, `Manager`, or `ComplianceOfficer` — moves it to `DENIED`
        with `denied_band` set to `SUPERVISOR`; denying a `PENDING_MANAGER`
        request — `Manager` or `ComplianceOfficer` — moves it to `DENIED` with
        `denied_band` `MANAGER`".
        PRD §3.6: "an `AccountHolder`, `Teller`, `Supervisor`, or `Manager` may
        appeal a `DENIED` request, and the destination depends on where it died
        — a request whose `denied_band` is `SUPERVISOR` re-enters at
        `PENDING_MANAGER`, while one whose `denied_band` is `MANAGER` re-enters
        at `PENDING_COMPLIANCE`."

        Design: Difficulty/non_linear_state_machine/waiver_request_deny_appeal_cycle
        """
        _, _, request = self._setup()
        # 5000 < 7000 <= 20000: supervisor band.
        assert request["status"] == "PENDING_SUPERVISOR"
        assert request["computed_total_cents"] == 7000

        denied1 = validate_success(api.deny_fee_waiver_request(
            request["id"], make_supervisor_headers("sup-1")))
        assert denied1["status"] == "DENIED"
        assert denied1["denied_band"] == "SUPERVISOR"

        appealed1 = validate_success(
            api.appeal_fee_waiver_request(request["id"], TELLER))
        assert appealed1["status"] == "PENDING_MANAGER"

        denied2 = validate_success(
            api.deny_fee_waiver_request(request["id"], MANAGER))
        assert denied2["status"] == "DENIED"
        assert denied2["denied_band"] == "MANAGER"

        appealed2 = validate_success(
            api.appeal_fee_waiver_request(request["id"], TELLER))
        assert appealed2["status"] == "PENDING_COMPLIANCE"

    def test_compliance_approval_applies_full_waiver(self, api):
        """PRD §3.6: "On approval the allocation is recomputed against current
        outstanding amounts using the same pinned ordering, each item's
        `waived_cents` is written, each fee's `waived_cents` grows by its
        allocation, and any fee whose `outstanding_cents` thereby reaches zero
        flips to `WAIVED`".
        PRD §3.6: "The account's ledger is credited by the total waived amount,
        `lifetime_fees_waived_cents` grows by the same total,
        `decided_by_user_id` is set to the approver, and the request becomes
        `APPLIED`."

        Design: Difficulty/non_linear_state_machine/waiver_request_deny_appeal_cycle
        """
        account, fees, request = self._setup()
        validate_success(api.deny_fee_waiver_request(
            request["id"], make_supervisor_headers("sup-1")))
        validate_success(api.appeal_fee_waiver_request(request["id"], TELLER))
        validate_success(api.deny_fee_waiver_request(request["id"], MANAGER))
        validate_success(api.appeal_fee_waiver_request(request["id"], TELLER))
        applied = validate_success(
            api.approve_fee_waiver_request(request["id"], COMPLIANCE))
        assert applied["status"] == "APPLIED"

        after = get_account(account["id"])
        assert after["ledger_balance_cents"] == -2400  # -9400 + 7000 credited
        assert after["lifetime_fees_waived_cents"] == 7000
        for fee in fees:
            assert get_fee(fee["id"])["status"] == "WAIVED"


class TestFeeAssessThenWaiveConservesNetPosition:
    def _setup(self):
        """Funded to 10000 (Mon). Tue: debits 4000 and 7000 sealed; one
        OVERDRAFT fee of 3500 ASSESSED (working -1000)."""
        program = make_program(name="OD-I1")
        account, _ = make_opted_in_account(program["id"], holder_name="Holder I1")
        run_posting_day(program["id"], "2026-08-03", account["id"],
                        [("CREDIT_DEPOSIT", 10000)], settle=True)
        batch = open_batch(program["id"], "2026-08-04")
        set_clock("2026-08-04T09:00:00Z")
        authorize(account["id"], "DEBIT_ONE_TIME", 4000)
        set_clock("2026-08-04T09:01:00Z")
        authorize(account["id"], "DEBIT_ONE_TIME", 7000)
        seal_batch(batch["id"])
        fee = list_fees(account_id=account["id"])[0]
        return account, batch, fee

    def test_assess_posts_fee_and_debits_ledger_at_settle(self, api):
        """PRD §3.5: "Settlement first moves every `ASSESSED` fee created by
        the seal to `POSTED`, stamping `posted_date` with the batch's business
        date and debiting each fee's amount from its account's
        `ledger_balance_cents`".
        PRD §3.2: "`lifetime_fees_assessed_cents` accumulates the `amount_cents`
        of every fee ever assessed against the account".

        Design: Difficulty/compensating_invariant/fee_assess_then_waive_conserves_net_position
        """
        account, batch, _ = self._setup()
        settle_batch(batch["id"])
        after = get_account(account["id"])
        # -1000 items ledger - 3500 fee at settle.
        assert after["ledger_balance_cents"] == -4500
        assert after["lifetime_fees_assessed_cents"] == 3500
        assert after["lifetime_fees_waived_cents"] == 0
        # Net position: -4500 + 3500 - 0 == -1000 (items-only truth).
        assert (after["ledger_balance_cents"]
                + after["lifetime_fees_assessed_cents"]
                - after["lifetime_fees_waived_cents"]) == -1000

    def test_full_waiver_restores_the_net_position(self, api):
        """PRD §3.6: "When a staff member — a `Teller`, `Supervisor`, or
        `Manager` — submits a request whose total sits at or below the teller
        cap, the request is auto-approved and born `APPLIED`: the allocations
        are applied immediately, exactly as at approval time."
        PRD §3.6: "The account's ledger is credited by the total waived amount,
        `lifetime_fees_waived_cents` grows by the same total".

        Design: Difficulty/compensating_invariant/fee_assess_then_waive_conserves_net_position
        """
        account, batch, fee = self._setup()
        settle_batch(batch["id"])
        request = submit_waiver(account["id"], [fee["id"]], kind="FULL",
                                reason_code="BANK_ERROR", headers=TELLER_3)
        assert request["status"] == "APPLIED"  # staff, 3500 <= teller cap

        after = get_account(account["id"])
        assert after["ledger_balance_cents"] == -1000
        assert after["lifetime_fees_assessed_cents"] == 3500
        assert after["lifetime_fees_waived_cents"] == 3500
        # The assess+waive pair leaves the net position unchanged.
        assert (after["ledger_balance_cents"]
                + after["lifetime_fees_assessed_cents"]
                - after["lifetime_fees_waived_cents"]) == -1000
        assert get_fee(fee["id"])["status"] == "WAIVED"


class TestApproveAppliedRequestRejected:
    def test_applied_is_terminal_for_approve(self, api):
        """PRD §3.6: "any fee whose `outstanding_cents` thereby reaches zero
        flips to `WAIVED` — partial waivers leave a fee in its current status
        with a reduced `outstanding_cents`, and only a zero outstanding
        produces `WAIVED`."
        PRD §3.6: "The account's ledger is credited by the total waived amount,
        `lifetime_fees_waived_cents` grows by the same total,
        `decided_by_user_id` is set to the approver, and the request becomes
        `APPLIED`."
        PRD §2.10: "seventh, state-machine validity of the requested transition
        and waivability of listed fees (`ERR_INVALID_STATE_TRANSITION`,
        `ERR_FEE_NOT_WAIVABLE`)".

        Design: Corner/state_machines/approve_applied_request_returns_invalid_state
        """
        ctx = make_posted_fee_scenario()
        account, fee = ctx["account"], ctx["fee"]
        request = submit_waiver(account["id"], [fee["id"]], kind="FULL",
                                reason_code="BANK_ERROR", headers=TELLER)
        assert request["status"] == "APPLIED"
        assert get_fee(fee["id"])["status"] == "WAIVED"

        resp = api.approve_fee_waiver_request(
            request["id"], make_supervisor_headers("sup-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_fee(fee["id"])["status"] == "WAIVED"


class TestAppealDeniedFinalIsTerminal:
    def test_no_appeal_from_compliance_stage_denial(self, api):
        """PRD §3.6: "`DENIED_FINAL` is terminal: there is no appeal from a
        compliance-stage denial, and attempting any action against it is an
        invalid state transition."
        PRD §3.6: "denying a `PENDING_COMPLIANCE` request — `ComplianceOfficer`
        only — moves it to `DENIED_FINAL` with `denied_band` `COMPLIANCE`."

        Design: Corner/state_machines/appeal_denied_final_is_terminal
        """
        ctx = make_posted_fee_scenario(
            program_overrides={"fee_amount_cents": 120000,
                               "daily_fee_cap_cents": 1000000,
                               "max_daily_fees_count": 10},
            debit_amount_cents=1000)
        account, fee = ctx["account"], ctx["fee"]
        request = submit_waiver(account["id"], [fee["id"]], kind="FULL",
                                reason_code="HARDSHIP", headers=TELLER)
        # 120000 > manager cap: compliance band.
        assert request["status"] == "PENDING_COMPLIANCE"

        denied = validate_success(
            api.deny_fee_waiver_request(request["id"], COMPLIANCE))
        assert denied["status"] == "DENIED_FINAL"

        resp = api.appeal_fee_waiver_request(request["id"], TELLER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestWaiverFixedAmountExceedsOutstanding:
    def test_amount_over_listed_outstanding_rejected(self, api):
        """PRD §3.6: "For `FIXED_AMOUNT`, the `amount_cents` must additionally
        be positive and must not exceed the sum of the listed fees' outstanding
        amounts at submit; violating either bound is rejected with
        `ERR_WAIVER_AMOUNT_INVALID` (HTTP 422)."

        Design: Corner/validations/waiver_fixed_amount_exceeds_outstanding_rejected
        """
        ctx = make_posted_fee_scenario()
        account, fee = ctx["account"], ctx["fee"]
        resp = api.create_fee_waiver_request(
            {"account_id": account["id"], "fee_ids": [fee["id"]],
             "kind": "FIXED_AMOUNT", "amount_cents": 9999,
             "reason_code": "GOODWILL"}, TELLER)
        validate_error(resp, ApiErrorId.ERR_WAIVER_AMOUNT_INVALID)


class TestSupervisorApproveManagerBandRejected:
    def test_supervisor_over_authority_then_manager_applies(self, api):
        """PRD §3.6: "a `PENDING_MANAGER` request only by a `Manager` or
        `ComplianceOfficer` — a `Supervisor` attempting it fails with
        `ERR_WAIVER_EXCEEDS_AUTHORITY`".
        PRD §3.6: "The account's ledger is credited by the total waived amount,
        `lifetime_fees_waived_cents` grows by the same total".

        Design: Corner/validations/supervisor_approve_manager_band_rejected
        """
        ctx = make_posted_fee_scenario(
            program_overrides={"fee_amount_cents": 50000,
                               "daily_fee_cap_cents": 1000000,
                               "max_daily_fees_count": 10},
            debit_amount_cents=1000)
        account, fee = ctx["account"], ctx["fee"]
        request = submit_waiver(account["id"], [fee["id"]], kind="FULL",
                                reason_code="HARDSHIP", headers=TELLER)
        # 20000 < 50000 <= 100000: manager band.
        assert request["status"] == "PENDING_MANAGER"

        resp = api.approve_fee_waiver_request(
            request["id"], make_supervisor_headers("sup-1"))
        validate_error(resp, ApiErrorId.ERR_WAIVER_EXCEEDS_AUTHORITY)

        applied = validate_success(
            api.approve_fee_waiver_request(request["id"], MANAGER))
        assert applied["status"] == "APPLIED"
        # -51000 + 50000 credited.
        assert get_account(account["id"])["ledger_balance_cents"] == -1000


class TestSelfApprovalForbidden:
    def test_creator_cannot_approve_own_request(self, api):
        """PRD §2.9: "A fee waiver request records `created_by_user_id` and
        `created_by_role` at submission, and no subsequent approval or denial
        may be performed by the same user: an approver or denier whose
        `X-User-ID` equals the request's `created_by_user_id` is rejected with
        `ERR_SELF_APPROVAL_FORBIDDEN`."

        Design: Corner/validations/self_approval_forbidden
        """
        ctx = make_posted_fee_scenario(
            program_overrides={"fee_amount_cents": 7000,
                               "daily_fee_cap_cents": 1000000,
                               "max_daily_fees_count": 10},
            debit_amount_cents=1000)
        account, fee = ctx["account"], ctx["fee"]
        request = submit_waiver(account["id"], [fee["id"]], kind="FULL",
                                reason_code="BANK_ERROR",
                                headers=make_supervisor_headers("sup-7"))
        # Staff creator but 7000 > teller cap.
        assert request["status"] == "PENDING_SUPERVISOR"

        resp = api.approve_fee_waiver_request(
            request["id"], make_supervisor_headers("sup-7"))
        validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)

        applied = validate_success(api.approve_fee_waiver_request(
            request["id"], make_supervisor_headers("sup-8")))
        assert applied["status"] == "APPLIED"


class TestFeeStateChangedAtApproveRejected:
    def test_second_request_fails_after_first_waives_the_fee(self, api):
        """PRD §3.6: "every listed fee must still be `ASSESSED` or `POSTED` at
        that moment — if another request has already waived one, the approval
        is rejected with `ERR_FEE_STATE_CHANGED`."
        PRD §3.6: "An `AccountHolder`-created request never auto-approves; even
        a one-dollar holder request routes to `PENDING_SUPERVISOR` at minimum."

        Design: Corner/validations/fee_state_changed_at_approve_rejected
        """
        ctx = make_posted_fee_scenario()
        account, fee = ctx["account"], ctx["fee"]
        holder = make_account_holder_headers(account["id"])
        r1 = submit_waiver(account["id"], [fee["id"]], kind="FULL",
                           reason_code="FIRST_TIME", headers=holder)
        r2 = submit_waiver(account["id"], [fee["id"]], kind="FULL",
                           reason_code="HARDSHIP", headers=holder)
        assert r1["status"] == "PENDING_SUPERVISOR"
        assert r2["status"] == "PENDING_SUPERVISOR"

        applied = validate_success(api.approve_fee_waiver_request(
            r1["id"], make_supervisor_headers("sup-1")))
        assert applied["status"] == "APPLIED"

        resp = api.approve_fee_waiver_request(
            r2["id"], make_supervisor_headers("sup-2"))
        validate_error(resp, ApiErrorId.ERR_FEE_STATE_CHANGED)
        # R2 survives, still actionable after re-scoping.
        assert get_waiver_request(r2["id"])["status"] == "PENDING_SUPERVISOR"


class TestEscalateMovesRequestUpOneBand:
    def test_escalate_sup_to_mgr_requires_manager_approval(self, api):
        """PRD §3.6: "Escalation lifts a pending request one band —
        `PENDING_SUPERVISOR` to `PENDING_MANAGER`, available to a `Supervisor`
        or `Manager`, and `PENDING_MANAGER` to `PENDING_COMPLIANCE`, available
        to a `Manager`."
        PRD §3.6: "a `PENDING_MANAGER` request only by a `Manager` or
        `ComplianceOfficer` — a `Supervisor` attempting it fails with
        `ERR_WAIVER_EXCEEDS_AUTHORITY`".

        Design: Corner/endpoints/escalate_moves_request_up_one_band
        """
        ctx = make_posted_fee_scenario(
            program_overrides={"fee_amount_cents": 7000,
                               "daily_fee_cap_cents": 1000000,
                               "max_daily_fees_count": 10},
            debit_amount_cents=1000)
        account, fee = ctx["account"], ctx["fee"]
        request = submit_waiver(account["id"], [fee["id"]], kind="FULL",
                                reason_code="HARDSHIP", headers=TELLER)
        assert request["status"] == "PENDING_SUPERVISOR"

        escalated = validate_success(api.escalate_fee_waiver_request(
            request["id"], make_supervisor_headers("sup-1")))
        assert escalated["status"] == "PENDING_MANAGER"

        # Supervisor band no longer covers the escalated request.
        resp = api.approve_fee_waiver_request(
            request["id"], make_supervisor_headers("sup-2"))
        validate_error(resp, ApiErrorId.ERR_WAIVER_EXCEEDS_AUTHORITY)

        applied = validate_success(
            api.approve_fee_waiver_request(request["id"], MANAGER))
        assert applied["status"] == "APPLIED"
