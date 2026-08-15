"""Cost transfers: lifecycle cycle, retroactive countersign, segregation of
duties, money conservation, and transferability guards (PRD §3.3)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, TEST_USERS,
    create_cost_transfer_payload, post_expenditure, post_salary_expenditure,
    setup_transfer_pair, create_submitted_transfer,
    setup_sponsor_pi, create_active_award, setup_salary_award,
    ApiErrorId,
)

SPO = TEST_USERS["spo_headers"]
GC = TEST_USERS["coordinator_headers"]          # X-User-ID gc-1
GA = TEST_USERS["accountant_headers"]           # X-User-ID ga-1
GA2 = TEST_USERS["accountant_2_headers"]        # X-User-ID ga-2
GA9 = TEST_USERS["accountant_9_headers"]        # X-User-ID ga-9
ADMIN = TEST_USERS["system_admin_headers"]


class TestCostTransferDenyReviseResubmitCycle:
    """Difficulty instance: the SUBMITTED -> DENIED -> DRAFT -> SUBMITTED ->
    APPROVED loop."""

    def test_cycle_states_and_no_early_ledger_effects(self, api):
        """PRD §3.3: "a denied transfer returns to `DRAFT` via revise —
        clearing `deny_reason` and optionally replacing `justification` —
        ready to submit again."

        Design: Difficulty/non_linear_state_machine/cost_transfer_deny_revise_resubmit_cycle
        """
        (_sp, _pi, aw_s, l_s, aw_t, l_t, e) = setup_transfer_pair()
        tr = create_submitted_transfer(e, aw_t, l_t)
        denied = validate_success(api.deny_cost_transfer(
            tr["id"], {"deny_reason": "insufficient documentation provided"}, GA), 200)
        assert denied["status"] == "DENIED"
        revised = validate_success(api.revise_cost_transfer(
            tr["id"], {"justification": "move travel charge to correct award per PO"},
            GC), 200)
        assert revised["status"] == "DRAFT"
        resubmitted = validate_success(api.submit_cost_transfer(tr["id"], {}, GC), 200)
        assert resubmitted["status"] == "SUBMITTED"
        # Ledger effects have not fired yet: source still POSTED, target line 0.
        src = validate_success(api.get_expenditure(e["id"], GA), 200)
        assert src["status"] == "POSTED"
        line_t = validate_success(api.get_budget_line(l_t["id"], GA), 200)
        assert line_t["spent_cents"] == 0

    def test_ledger_effects_fire_on_final_approve(self, api):
        """PRD §3.3: "First the source expenditure transitions `POSTED →
        TRANSFERRED_OUT` and its line is credited by the amount."
        PRD §3.3: "Second the system creates a mirror expenditure on the target
        award: same `amount_cents`, status `POSTED`, `transferred_from_id`
        pointing back to the source, same expenditure type and category,
        `cash_disbursed` copied, `transaction_date` copied, and `posted_at` set
        to now."

        Design: Difficulty/non_linear_state_machine/cost_transfer_deny_revise_resubmit_cycle
        """
        (_sp, _pi, aw_s, l_s, aw_t, l_t, e) = setup_transfer_pair()
        tr = create_submitted_transfer(e, aw_t, l_t)
        api.deny_cost_transfer(tr["id"], {"deny_reason": "insufficient documentation provided"}, GA)
        api.revise_cost_transfer(tr["id"], {"justification": "move travel charge to correct award per PO"}, GC)
        api.submit_cost_transfer(tr["id"], {}, GC)
        approved = validate_success(api.approve_cost_transfer(tr["id"], GA), 200)
        assert approved["status"] == "APPROVED"
        src = validate_success(api.get_expenditure(e["id"], GA), 200)
        assert src["status"] == "TRANSFERRED_OUT"
        mirrors = validate_success(api.list_expenditures(
            GA, params={"transferred_from_id": e["id"]}), 200)
        assert mirrors[0]["amount_cents"] == 100_000
        assert mirrors[0]["status"] == "POSTED"


class TestRetroactiveTransferConditionalCountersign:
    """Corner endpoints instance: approve routes retroactive transfers to
    PENDING_COUNTERSIGN; only countersign applies the ledger effects."""

    def _setup(self, api):
        (_sp, _pi, aw_s, l_s, aw_t, l_t, e) = setup_transfer_pair(
            source_number="RT-001", target_number="RT-002")
        tr = get_success_data(api.create_cost_transfer(
            create_cost_transfer_payload(
                e["id"], aw_t["id"], l_t["id"],
                justification="late discovery of mischarged travel cost"), GC))
        get_success_data(api.set_clock({"to_iso8601": "2026-10-31T00:00:00Z"}, ADMIN))
        submitted = validate_success(api.submit_cost_transfer(
            tr["id"],
            {"enhanced_justification": "error discovered during annual audit; "
             "charge originates from subrecipient misallocation documented in INV-7"},
            GC), 200)
        return l_t, submitted

    def test_approve_routes_retroactive_to_countersign_without_effects(self, api):
        """PRD §3.3: "A retroactive transfer instead moves `SUBMITTED →
        PENDING_COUNTERSIGN`, recording `approved_by_user_id` but applying no
        ledger effects yet; a `SponsoredProgramsOfficer` must then countersign
        — re-checking that the target posture is not `FROZEN` and the target
        line still fits — to move `PENDING_COUNTERSIGN → APPROVED` and apply
        the effects, stamping `countersigned_by_user_id`."

        Design: Corner/endpoints/retroactive_transfer_conditional_countersign
        """
        l_t, submitted = self._setup(api)
        assert submitted["is_retroactive"] is True
        assert submitted["days_since_posting"] == 91
        routed = validate_success(api.approve_cost_transfer(submitted["id"], GA), 200)
        assert routed["status"] == "PENDING_COUNTERSIGN"
        line_t = validate_success(api.get_budget_line(l_t["id"], GA), 200)
        assert line_t["spent_cents"] == 0

    def test_countersign_applies_ledger_effects(self, api):
        """PRD §3.3: "a `SponsoredProgramsOfficer` must then countersign —
        re-checking that the target posture is not `FROZEN` and the target line
        still fits — to move `PENDING_COUNTERSIGN → APPROVED` and apply the
        effects, stamping `countersigned_by_user_id`."

        Design: Corner/endpoints/retroactive_transfer_conditional_countersign
        """
        l_t, submitted = self._setup(api)
        api.approve_cost_transfer(submitted["id"], GA)
        approved = validate_success(api.countersign_cost_transfer(submitted["id"], SPO), 200)
        assert approved["status"] == "APPROVED"
        line_t = validate_success(api.get_budget_line(l_t["id"], GA), 200)
        assert line_t["spent_cents"] == 100_000


class TestRetroactiveSubmitJustificationBoundary:
    """Corner errors instance: 90-day timeliness boundary + enhanced
    justification requirement."""

    def _setup(self, api):
        (_sp, _pi, aw_s, l_s, aw_t, l_t, e1) = setup_transfer_pair(
            source_number="RJ-001", target_number="RJ-002",
            source_posted_amount=50_000)
        e2 = post_expenditure(aw_s["id"], l_s["id"], amount_cents=50_000,
                              transaction_date="2026-03-02T00:00:00Z",
                              cash_disbursed=True)
        t1 = get_success_data(api.create_cost_transfer(
            create_cost_transfer_payload(
                e1["id"], aw_t["id"], l_t["id"],
                justification="timely transfer at the day-90 boundary"), GC))
        t2 = get_success_data(api.create_cost_transfer(
            create_cost_transfer_payload(
                e2["id"], aw_t["id"], l_t["id"],
                justification="late transfer missing its enhanced text"), GC))
        return t1, t2

    def test_exactly_90_days_is_timely(self, api):
        """PRD §3.3: "On submit the system computes `days_since_posting` as
        whole days from the source's `posted_at` to the logical clock, and sets
        `is_retroactive` true exactly when that count exceeds 90 — a transfer
        submitted precisely 90 days after posting is timely."

        Design: Corner/errors/retroactive_submit_without_enhanced_justification_rejected
        """
        t1, _t2 = self._setup(api)
        get_success_data(api.set_clock({"to_iso8601": "2026-10-30T00:00:00Z"}, ADMIN))
        submitted = validate_success(api.submit_cost_transfer(t1["id"], {}, GC), 200)
        assert submitted["days_since_posting"] == 90
        assert submitted["is_retroactive"] is False

    def test_day_91_without_enhanced_justification_rejected(self, api):
        """PRD §3.3: "A retroactive transfer must carry an
        `enhanced_justification` of at least 50 characters
        (`ERR_ENHANCED_JUSTIFICATION_REQUIRED`)."

        Design: Corner/errors/retroactive_submit_without_enhanced_justification_rejected
        """
        _t1, t2 = self._setup(api)
        get_success_data(api.set_clock({"to_iso8601": "2026-10-30T00:00:00Z"}, ADMIN))
        get_success_data(api.set_clock({"to_iso8601": "2026-10-31T00:00:00Z"}, ADMIN))
        res = api.submit_cost_transfer(t2["id"], {}, GC)
        validate_error(res, ApiErrorId.ERR_ENHANCED_JUSTIFICATION_REQUIRED.value)


class TestSegregationOfDutiesBeatsFiscal:
    """Difficulty instance: SoD (compliance) beats fiscal on transfer approve."""

    def _setup(self, api):
        (_sp, _pi, aw_s, l_s, aw_t, l_t, e) = setup_transfer_pair(
            source_number="S3-001", target_number="T3-001")
        # Spend 60000 on the target line so only 40000 headroom remains.
        post_expenditure(aw_t["id"], l_t["id"], amount_cents=60_000,
                         cash_disbursed=True)
        tr = get_success_data(api.create_cost_transfer(
            create_cost_transfer_payload(
                e["id"], aw_t["id"], l_t["id"],
                justification="reallocate travel to the correct award"), GA))
        get_success_data(api.submit_cost_transfer(tr["id"], {}, GA))
        return tr

    def test_self_approval_rejected_segregation_of_duties(self, api):
        """PRD §3.3: "Approval enforces segregation of duties: the approving
        accountant's `X-User-ID` must differ from `submitted_by_user_id`
        (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403)."
        PRD §2.7: "(8) compliance and safety rules (allowability, segregation
        of duties, ...)" come before "(12) fiscal ceilings and floors...".

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_fiscal_on_transfer_approve
        """
        tr = self._setup(api)
        res = api.approve_cost_transfer(tr["id"], GA)   # ga-1 == submitter
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_other_approver_surfaces_fiscal_failure(self, api):
        """PRD §3.3: "the target line must fit — its `spent_cents` plus the
        transferred amount must not exceed `authorized_cents`
        (`ERR_BUDGET_LINE_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_fiscal_on_transfer_approve
        """
        tr = self._setup(api)
        api.approve_cost_transfer(tr["id"], GA)         # SoD failure, no mutation
        res = api.approve_cost_transfer(tr["id"], GA2)  # ga-2 != submitter
        validate_error(res, ApiErrorId.ERR_BUDGET_LINE_EXCEEDED.value)
        tr_after = validate_success(api.get_cost_transfer(tr["id"], GA), 200)
        assert tr_after["status"] == "SUBMITTED"


class TestCostTransferMoneyConservation:
    """Difficulty instance: direct-money conservation across the pair."""

    def _setup(self, api):
        (_sp, _pi, aw_s, l_s, aw_t, l_t, e) = setup_transfer_pair(
            source_number="S4-001", target_number="T4-001")
        tr = create_submitted_transfer(e, aw_t, l_t)
        return aw_s, l_s, aw_t, l_t, e, tr

    def test_line_spending_conserved_across_transfer(self, api):
        """PRD §2.8: "a cost transfer never creates or destroys direct cost:
        for a transfer of amount A from source award S to target award G, the
        sum of `spent_cents` over all budget lines of S plus the sum over all
        lines of G is identical before and after approval — the source line is
        credited by A and the target line is debited by A."

        Design: Difficulty/compensating_invariant/cost_transfer_money_conservation
        """
        aw_s, l_s, aw_t, l_t, e, tr = self._setup(api)
        s_before = validate_success(api.get_budget_line(l_s["id"], GA), 200)["spent_cents"]
        t_before = validate_success(api.get_budget_line(l_t["id"], GA), 200)["spent_cents"]
        validate_success(api.approve_cost_transfer(tr["id"], GA), 200)
        s_after = validate_success(api.get_budget_line(l_s["id"], GA), 200)["spent_cents"]
        t_after = validate_success(api.get_budget_line(l_t["id"], GA), 200)["spent_cents"]
        assert s_before + t_before == s_after + t_after == 100_000
        assert s_after == 0 and t_after == 100_000

    def test_mirror_and_target_aggregates_rederived(self, api):
        """PRD §3.3: "Third the target line is debited."
        PRD §3.3: "Fourth both awards recompute their MTDC, F&A accrual, and
        draw pools — the source award's totals fall, the target's rise, and the
        combined sum of line spending across the two awards is bit-identical
        before and after."

        Design: Difficulty/compensating_invariant/cost_transfer_money_conservation
        """
        aw_s, l_s, aw_t, l_t, e, tr = self._setup(api)
        validate_success(api.approve_cost_transfer(tr["id"], GA), 200)
        mirrors = validate_success(api.list_expenditures(
            GA, params={"transferred_from_id": e["id"]}), 200)
        assert mirrors[0]["amount_cents"] == 100_000
        assert mirrors[0]["mtdc_eligible_cents"] == 100_000
        target = validate_success(api.get_award(aw_t["id"], GA), 200)
        assert target["mtdc_spent_cents"] == 100_000
        assert target["f_and_a_accrued_cents"] == 50_000


class TestTransferabilityGuards:
    def test_transfer_target_same_award_rejected(self, api):
        """PRD §3.3: "the target award must differ from the source
        expenditure's award (`ERR_TRANSFER_TARGET_SAME_AS_SOURCE`); and the
        target line's category must match the source line's category
        (`ERR_CATEGORY_TYPE_MISMATCH`)."

        Design: Corner/errors/transfer_target_same_award_rejected
        """
        (_sp, _pi, aw_s, l_s, _aw_t, _l_t, e) = setup_transfer_pair(
            source_number="TS-001")
        res = api.create_cost_transfer(
            create_cost_transfer_payload(
                e["id"], aw_s["id"], l_s["id"],
                justification="attempted same-award transfer here"), GC)
        validate_error(res, ApiErrorId.ERR_TRANSFER_TARGET_SAME_AS_SOURCE.value)

    def test_salary_and_cost_share_not_transferable(self, api):
        """PRD §3.3: "The source must be `POSTED` and must not be a salary
        charge (`ERR_SALARY_NOT_TRANSFERABLE` — salary corrections route
        through payroll and effort, not transfers) nor a cost-share entry
        (`ERR_COST_SHARE_NOT_TRANSFERABLE`); the target award must differ from
        the source expenditure's award (`ERR_TRANSFER_TARGET_SAME_AS_SOURCE`);
        and the target line's category must match the source line's category
        (`ERR_CATEGORY_TYPE_MISMATCH`)."

        Design: Corner/errors/salary_and_cost_share_not_transferable
        """
        sponsor, person, aw_s, sal, _fr = setup_salary_award(
            "NT-001", salary_line=1_000_000, fringe_line=300_000,
            obligated=1_950_000, committed_effort_pct=25.0,
            is_key_personnel=False)
        # Add a TRAVEL line and a cost-share posting on the source award.
        from test_helpers import make_budget_line
        award_number_t = "NT-002"
        aw_t, lt = create_active_award(
            sponsor["id"], person["id"], award_number_t,
            [{"category": "TRAVEL", "authorized_cents": 100_000}], 150_000)
        es = post_salary_expenditure(aw_s["id"], sal["id"], person["id"],
                                     25.0, 1, "2026-03-01T00:00:00Z")
        # TRAVEL line on the source award for the cost-share posting.
        # (Source award has no TRAVEL line loaded; load happened while
        # PENDING_SETUP — instead create the cost-share on a fresh award pair.)
        # Use a separate pair where the source has a TRAVEL line:
        (_sp2, _pi2, aw_s2, l_s2, aw_t2, l_t2, _e) = setup_transfer_pair(
            source_number="NT-003", target_number="NT-004",
            source_travel=200_000, target_travel=100_000,
            source_obligated=300_000, target_obligated=150_000)
        ec = post_expenditure(aw_s2["id"], l_s2["id"], amount_cents=30_000,
                              is_cost_share=True)
        res1 = api.create_cost_transfer(
            create_cost_transfer_payload(
                es["id"], aw_t["id"], lt["TRAVEL"]["id"],
                justification="attempted salary transfer is refused"), GC)
        validate_error(res1, ApiErrorId.ERR_SALARY_NOT_TRANSFERABLE.value)
        res2 = api.create_cost_transfer(
            create_cost_transfer_payload(
                ec["id"], aw_t2["id"], l_t2["id"],
                justification="attempted cost-share transfer refused"), GC)
        validate_error(res2, ApiErrorId.ERR_COST_SHARE_NOT_TRANSFERABLE.value)


class TestTransferTerminalLockdown:
    def test_approve_from_approved_terminal_lockdown(self, api):
        """PRD §3.3: "Actions attempted from the wrong state return
        `ERR_TRANSFER_NOT_ACTIONABLE`."

        Design: Corner/state_machines/transfer_approve_from_approved_terminal_lockdown
        """
        (_sp, _pi, aw_s, l_s, aw_t, l_t, e) = setup_transfer_pair(
            source_number="SM-003A", target_number="SM-003B")
        tr = create_submitted_transfer(e, aw_t, l_t)
        validate_success(api.approve_cost_transfer(tr["id"], GA), 200)
        res = api.approve_cost_transfer(tr["id"], GA2)
        validate_error(res, ApiErrorId.ERR_TRANSFER_NOT_ACTIONABLE.value)
        line_t = validate_success(api.get_budget_line(l_t["id"], GA), 200)
        assert line_t["spent_cents"] == 100_000   # effects fired exactly once


class TestCountersignRole:
    def test_countersign_requires_spo_not_accountant(self, api):
        """PRD §3.3: "a `SponsoredProgramsOfficer` must then countersign —
        re-checking that the target posture is not `FROZEN` and the target line
        still fits — to move `PENDING_COUNTERSIGN → APPROVED` and apply the
        effects, stamping `countersigned_by_user_id`."
        PRD §2.1: "Once authenticated, the role is checked against the
        endpoint's authorized-role list; a role not permitted on the endpoint
        is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/countersign_requires_spo_not_accountant
        """
        (_sp, _pi, aw_s, l_s, aw_t, l_t, e) = setup_transfer_pair(
            source_number="RB-903A", target_number="RB-903B")
        tr = get_success_data(api.create_cost_transfer(
            create_cost_transfer_payload(
                e["id"], aw_t["id"], l_t["id"],
                justification="late discovery of mischarged travel cost"), GC))
        get_success_data(api.set_clock({"to_iso8601": "2026-10-31T00:00:00Z"}, ADMIN))
        get_success_data(api.submit_cost_transfer(
            tr["id"],
            {"enhanced_justification": "error discovered during annual audit; "
             "charge originates from subrecipient misallocation documented in INV-7"},
            GC))
        routed = validate_success(api.approve_cost_transfer(tr["id"], GA), 200)
        assert routed["status"] == "PENDING_COUNTERSIGN"
        res = api.countersign_cost_transfer(tr["id"], GA2)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
