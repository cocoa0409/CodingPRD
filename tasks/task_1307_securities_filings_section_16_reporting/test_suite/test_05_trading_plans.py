"""Rule 10b5-1 trading plans: cooling-off computation, lifecycle cycles,
window-overlap exclusivity, and insider RBAC (PRD §2.1, §3.6)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId,
    make_compliance_officer_headers, make_reporting_insider_headers,
    make_equity_plan_admin_headers,
    create_issuer, create_reporting_person, create_active_person,
    create_trading_plan, plan_action, setup_adopted_plan, setup_active_plan,
    get_plan, set_clock, ingest_transaction,
)


class TestCoolingOffComputation:
    def _setup_officer_plan(self, api):
        """Officer plan approved 2026-08-03 against earnings date 2026-12-15."""
        issuer = create_issuer(next_earnings_filing_date="2026-12-15")
        person = create_reporting_person(issuer["id"], is_officer=True)
        set_clock("2026-08-03T09:00:00Z")
        plan = create_trading_plan(person["id"], plan_name="Plan A",
                                   first_trade_date="2026-09-01",
                                   expiration_date="2027-03-01")
        plan_action(plan["id"], "SUBMIT_ADOPTION", person_id=person["id"])
        return person, plan

    def test_approval_stamps_adoption_date_and_adopts(self, api):
        """PRD §3.6: "Approval stamps `adoption_date` with the logical clock
        date and computes `cooling_off_end_date`, which is frozen from that
        moment onward."
        PRD §3.6: "A `ComplianceOfficer` then approves or rejects it."

        Design: Difficulty/combinatorial_formula/cooling_off_nested_min_max_with_cap
        """
        person, plan = self._setup_officer_plan(api)
        resp = api.plan_transition(plan["id"], {"action": "APPROVE"},
                                   make_compliance_officer_headers())
        data = validate_success(resp, 200)
        assert data["status"] == "ADOPTED", (
            f"Expected ADOPTED, got {data['status']}")
        assert data["adoption_date"] == "2026-08-03", (
            f"adoption_date must be the logical clock date 2026-08-03, "
            f"got {data['adoption_date']}")

    def test_cooling_off_nested_min_max_binds_at_cap(self, api):
        """PRD §3.6: "The base end is `adoption_date` plus 90 calendar days.
        When the plan's reporting person is flagged as an officer (`is_officer`)
        or a director (`is_director`), an earnings-based end is computed by
        advancing the issuer's `next_earnings_filing_date` by two business days
        using the same business-day routine as filing deadlines; the extended
        end is the later of the base end and the earnings-based end, and
        `cooling_off_end_date` becomes the earlier of that extended end and
        `adoption_date` plus 120 calendar days."

        Design: Difficulty/combinatorial_formula/cooling_off_nested_min_max_with_cap
        """
        person, plan = self._setup_officer_plan(api)
        resp = api.plan_transition(plan["id"], {"action": "APPROVE"},
                                   make_compliance_officer_headers())
        data = validate_success(resp, 200)
        # base_end = 2026-08-03 + 90d = 2026-11-01;
        # earnings_end = 2026-12-15 (Tue) + 2 business days = 2026-12-17;
        # extended = max(2026-11-01, 2026-12-17) = 2026-12-17;
        # cap = 2026-08-03 + 120d = 2026-12-01; min binds at the cap.
        assert data["cooling_off_end_date"] == "2026-12-01", (
            f"Expected cooling_off_end_date 2026-12-01 (cap binds), "
            f"got {data['cooling_off_end_date']}")


class TestSuspendReinstateCycle:
    def _setup_active_plan_with_earnings_extension(self, api):
        """Officer plan approved 2026-08-03 (cooling-off ends 2026-11-03:
        base 2026-11-01, earnings 2026-10-30 (Fri) + 2 business days =
        2026-11-03, cap 2026-12-01) and activated exactly on 2026-11-03."""
        issuer = create_issuer(next_earnings_filing_date="2026-10-30")
        person = create_reporting_person(issuer["id"], is_officer=True)
        plan = setup_active_plan(
            issuer["id"], person["id"],
            approve_at="2026-08-03T09:00:00Z",
            activate_at="2026-11-03T09:00:00Z",
            first_trade_date="2026-09-01", expiration_date="2027-03-01")
        return plan

    def test_active_suspend_reinstate_cycle(self, api):
        """PRD §3.6: "From `ACTIVE`, a compliance hold suspends the plan
        (`SUSPEND` moves `ACTIVE` to `SUSPENDED`), and a later `REINSTATE` moves
        `SUSPENDED` back to `ACTIVE`"

        Design: Difficulty/non_linear_state_machine/trading_plan_suspend_reinstate_cycle
        """
        plan = self._setup_active_plan_with_earnings_extension(api)
        assert plan["status"] == "ACTIVE", (
            f"Plan must reach ACTIVE, got {plan['status']}")
        suspended = plan_action(plan["id"], "SUSPEND")
        assert suspended["status"] == "SUSPENDED", (
            f"First leg of the cycle must yield SUSPENDED, "
            f"got {suspended['status']}")
        reinstated = plan_action(plan["id"], "REINSTATE")
        assert reinstated["status"] == "ACTIVE", (
            f"Cycle must close back to ACTIVE, got {reinstated['status']}")

    def test_active_suspend_reinstate_repeated_cycle(self, api):
        """PRD §3.6: "From `ACTIVE`, a compliance hold suspends the plan
        (`SUSPEND` moves `ACTIVE` to `SUSPENDED`), and a later `REINSTATE`
        moves `SUSPENDED` back to `ACTIVE`"
        PRD §3.6: "Termination (`TERMINATE`) is available to a
        `ComplianceOfficer` or to the owning insider from `ADOPTED`, `ACTIVE`,
        or `SUSPENDED`, stamps `termination_date` with the logical clock date,
        and lands in the terminal `TERMINATED` state; from any other source
        state it fails with `ERR_PLAN_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/trading_plan_suspend_reinstate_cycle
        """
        plan = self._setup_active_plan_with_earnings_extension(api)
        # The cycle is repeatable: a second hold closes back to ACTIVE again.
        plan_action(plan["id"], "SUSPEND")
        plan_action(plan["id"], "REINSTATE")
        second_suspension = plan_action(plan["id"], "SUSPEND")
        assert second_suspension["status"] == "SUSPENDED"
        second_reinstate = plan_action(plan["id"], "REINSTATE")
        assert second_reinstate["status"] == "ACTIVE", (
            f"Second circuit must close to ACTIVE, "
            f"got {second_reinstate['status']}")

    def test_suspend_reinstate_conserves_cooling_off_end_date(self, api):
        """PRD §3.6: "both actions must leave `cooling_off_end_date` unchanged,
        so a hold never resets the cooling-off clock."
        PRD §3.6: "Approval stamps `adoption_date` with the logical clock date
        and computes `cooling_off_end_date`, which is frozen from that moment
        onward."

        Design: Difficulty/compensating_invariant/suspend_reinstate_cooling_off_conservation
        """
        issuer = create_issuer(next_earnings_filing_date="2026-10-30")
        person = create_reporting_person(issuer["id"], is_officer=True)
        plan = setup_adopted_plan(
            issuer["id"], person["id"], approve_at="2026-08-03T09:00:00Z",
            first_trade_date="2026-09-01", expiration_date="2027-03-01")
        assert plan["cooling_off_end_date"] == "2026-11-03", (
            f"Expected cooling_off_end_date 2026-11-03 at approval, "
            f"got {plan['cooling_off_end_date']}")
        set_clock("2026-11-03T09:00:00Z")
        plan_action(plan["id"], "ACTIVATE")
        suspended = plan_action(plan["id"], "SUSPEND")
        assert suspended["cooling_off_end_date"] == "2026-11-03", (
            "Suspension must not reset cooling-off")
        reinstated = plan_action(plan["id"], "REINSTATE")
        assert reinstated["cooling_off_end_date"] == "2026-11-03", (
            "Reinstatement must not reset cooling-off")
        assert reinstated["status"] == "ACTIVE"

    def test_suspend_hold_does_not_reopen_cooling_off(self, api):
        """PRD §3.6: "both actions must leave `cooling_off_end_date` unchanged,
        so a hold never resets the cooling-off clock."
        PRD §3.6: "Activation (`ACTIVATE`) moves an `ADOPTED` plan to `ACTIVE`
        once the logical clock date has reached `cooling_off_end_date` —
        equality satisfies the rule"

        Design: Difficulty/compensating_invariant/suspend_reinstate_cooling_off_conservation
        """
        issuer = create_issuer(next_earnings_filing_date="2026-10-30")
        person = create_reporting_person(issuer["id"], is_officer=True)
        plan = setup_adopted_plan(
            issuer["id"], person["id"], approve_at="2026-08-03T09:00:00Z",
            first_trade_date="2026-09-01", expiration_date="2027-03-01")
        pinned = plan["cooling_off_end_date"]
        set_clock("2026-11-03T09:00:00Z")
        plan_action(plan["id"], "ACTIVATE")
        plan_action(plan["id"], "SUSPEND")
        # After reinstatement the pinned date persists on a fresh read and the
        # plan trades as ACTIVE again (no new cooling-off wait was imposed).
        reinstated = plan_action(plan["id"], "REINSTATE")
        assert reinstated["status"] == "ACTIVE"
        persisted = get_plan(plan["id"])
        assert persisted["cooling_off_end_date"] == pinned, (
            f"cooling_off_end_date must persist at {pinned} across the "
            f"hold/reinstate pair, got {persisted['cooling_off_end_date']}")


class TestPlanWindowOverlap:
    def _setup_plan_a_adopted(self, api):
        issuer = create_issuer(next_earnings_filing_date="2026-10-30")
        person = create_reporting_person(issuer["id"], is_officer=True)
        set_clock("2026-08-03T09:00:00Z")
        plan_a = setup_adopted_plan(
            issuer["id"], person["id"], first_trade_date="2026-09-01",
            expiration_date="2026-12-01", plan_name="Plan A")
        return person, plan_a

    def test_adjacent_half_open_window_approved(self, api):
        """PRD §3.6: "no other plan of the same `reporting_person_id` in
        `ADOPTED`, `ACTIVE`, or `SUSPENDED` status may have a window
        intersecting this plan's window, where two windows intersect exactly
        when the first plan's `first_trade_date` falls before the second plan's
        `expiration_date` and the second plan's `first_trade_date` falls before
        the first plan's `expiration_date`; an intersecting approval is rejected
        with `ERR_PLAN_WINDOW_OVERLAP`."
        PRD §3.6: "a `first_trade_date`, and an `expiration_date`, which
        together describe a half-open trading window that runs from
        `first_trade_date` up to but not including `expiration_date`"

        Design: Difficulty/resource_temporal_overlap/plan_windows_half_open_overlap
        """
        person, plan_a = self._setup_plan_a_adopted(api)
        # Plan B starts exactly at A's exclusive end: [12-01, 03-01) does not
        # intersect [09-01, 12-01) under half-open semantics.
        plan_b = create_trading_plan(person["id"], plan_name="Plan B",
                                     first_trade_date="2026-12-01",
                                     expiration_date="2027-03-01")
        plan_action(plan_b["id"], "SUBMIT_ADOPTION", person_id=person["id"])
        resp = api.plan_transition(plan_b["id"], {"action": "APPROVE"},
                                   make_compliance_officer_headers())
        data = validate_success(resp, 200)
        assert data["status"] == "ADOPTED", (
            f"Adjacent half-open window must be approved, got {data['status']}")

    def test_overlapping_window_rejected(self, api):
        """PRD §3.6: "an intersecting approval is rejected with
        `ERR_PLAN_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/plan_windows_half_open_overlap
        """
        person, plan_a = self._setup_plan_a_adopted(api)
        # Plan C starts 2026-11-30, strictly inside A's window [09-01, 12-01).
        plan_c = create_trading_plan(person["id"], plan_name="Plan C",
                                     first_trade_date="2026-11-30",
                                     expiration_date="2027-02-28")
        plan_action(plan_c["id"], "SUBMIT_ADOPTION", person_id=person["id"])
        resp = api.plan_transition(plan_c["id"], {"action": "APPROVE"},
                                   make_compliance_officer_headers())
        validate_error(resp, ApiErrorId.ERR_PLAN_WINDOW_OVERLAP)


class TestPlanLifecycleGuards:
    def test_terminated_plan_rejects_activate(self, api):
        """PRD §3.6: "Termination (`TERMINATE`) is available to a
        `ComplianceOfficer` or to the owning insider from `ADOPTED`, `ACTIVE`,
        or `SUSPENDED`, stamps `termination_date` with the logical clock date,
        and lands in the terminal `TERMINATED` state; from any other source
        state it fails with `ERR_PLAN_INVALID_STATE`."

        Design: Corner/state_machines/terminated_plan_rejects_activate
        """
        issuer = create_issuer()
        person = create_reporting_person(issuer["id"], full_name="Dana Owner",
                                         person_cik="0001000002",
                                         is_ten_pct_owner=True)
        set_clock("2026-08-03T09:00:00Z")
        plan = setup_adopted_plan(issuer["id"], person["id"],
                                  first_trade_date="2026-11-01",
                                  expiration_date="2027-03-01")
        plan_action(plan["id"], "TERMINATE")
        resp = api.plan_transition(plan["id"], {"action": "ACTIVATE"},
                                   make_compliance_officer_headers())
        validate_error(resp, ApiErrorId.ERR_PLAN_INVALID_STATE)

    def test_activate_before_cooling_off_rejected(self, api):
        """PRD §3.6: "Activation (`ACTIVATE`) moves an `ADOPTED` plan to
        `ACTIVE` once the logical clock date has reached
        `cooling_off_end_date` — equality satisfies the rule — and attempting
        activation earlier fails with `ERR_COOLING_OFF_NOT_SATISFIED`."

        Design: Corner/validations/activate_before_cooling_off_rejected
        """
        issuer = create_issuer(next_earnings_filing_date="2026-10-30")
        person = create_reporting_person(issuer["id"], is_officer=True)
        plan = setup_adopted_plan(issuer["id"], person["id"],
                                  approve_at="2026-08-03T09:00:00Z",
                                  first_trade_date="2026-09-01",
                                  expiration_date="2027-03-01")
        # cooling_off_end_date is 2026-11-03; one day earlier must fail.
        set_clock("2026-11-02T09:00:00Z")
        resp = api.plan_transition(plan["id"], {"action": "ACTIVATE"},
                                   make_compliance_officer_headers())
        validate_error(resp, ApiErrorId.ERR_COOLING_OFF_NOT_SATISFIED)

    def test_plan_not_active_blocks_plan_trade(self, api):
        """PRD §3.3: "when a `plan_id` is set, the referenced plan must be
        `ACTIVE` (`ERR_PLAN_NOT_ACTIVE` — this catches trades under plans still
        cooling off in `ADOPTED` or parked in `SUSPENDED`)"

        Design: Corner/validations/plan_not_active_blocks_plan_trade
        """
        issuer = create_issuer()
        person = create_active_person(issuer["id"],
                                      designate_at="2026-08-03T09:00:00Z",
                                      full_name="Dana Owner",
                                      person_cik="0001000002",
                                      is_ten_pct_owner=True)
        plan = setup_adopted_plan(issuer["id"], person["id"],
                                  first_trade_date="2026-11-01",
                                  expiration_date="2027-03-01")
        # Plan is ADOPTED (still cooling off); the trade carries its plan_id.
        txn = ingest_transaction(person["id"], transaction_date="2026-08-03",
                                 shares=100, price_per_share=10.00,
                                 plan_id=plan["id"])
        resp = api.confirm_transaction(
            txn["id"], make_compliance_officer_headers("co_1"))
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE)

    def test_plan_person_mismatch_on_confirm(self, api):
        """PRD §3.3: "and finally a plan-affiliated transaction's plan must
        belong to the same reporting person as the transaction
        (`ERR_PLAN_PERSON_MISMATCH`)."
        PRD §3.6: "Trades under a plan carry its `plan_id` at intake, and their
        confirmation requires the plan to be `ACTIVE` at that moment
        (`ERR_PLAN_NOT_ACTIVE`) and to belong to the transacting person
        (`ERR_PLAN_PERSON_MISMATCH`)."

        Design: Corner/validations/plan_person_mismatch_on_confirm
        """
        issuer = create_issuer()
        p1 = create_active_person(issuer["id"], full_name="Dana Officer",
                                  person_cik="0001000001")
        p2 = create_active_person(issuer["id"], full_name="Eve Owner",
                                  person_cik="0001000002",
                                  is_ten_pct_owner=True)
        # P2's plan: approved at the default clock 2026-08-01 (cooling-off ends
        # 2026-10-30 for a pure 10% owner), activated at 2026-11-01.
        plan2 = setup_active_plan(issuer["id"], p2["id"],
                                  approve_at="2026-08-01T09:00:00Z",
                                  activate_at="2026-11-01T09:00:00Z",
                                  first_trade_date="2026-11-01",
                                  expiration_date="2027-03-01")
        txn = ingest_transaction(p1["id"], transaction_date="2026-08-01",
                                 shares=100, price_per_share=10.00,
                                 plan_id=plan2["id"])
        resp = api.confirm_transaction(
            txn["id"], make_compliance_officer_headers("co_1"))
        validate_error(resp, ApiErrorId.ERR_PLAN_PERSON_MISMATCH)


class TestPlanRbac:
    def test_insider_cannot_approve_own_plan(self, api):
        """PRD §3.6: "A `ComplianceOfficer` then approves or rejects it."
        PRD §2.1: "Invoking an operation one's role does not permit is rejected
        with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/insider_cannot_approve_own_plan
        """
        issuer = create_issuer()
        person = create_reporting_person(issuer["id"], full_name="Dana Owner",
                                         person_cik="0001000002",
                                         is_ten_pct_owner=True)
        plan = create_trading_plan(person["id"], plan_name="Plan A",
                                   first_trade_date="2026-11-01",
                                   expiration_date="2027-03-01")
        plan_action(plan["id"], "SUBMIT_ADOPTION", person_id=person["id"])
        resp = api.plan_transition(
            plan["id"], {"action": "APPROVE"},
            make_reporting_insider_headers(person["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert get_plan(plan["id"])["status"] == "PENDING_APPROVAL", (
            "Plan must remain PENDING_APPROVAL after a forbidden APPROVE")

    def test_insider_cannot_create_plan_for_other_person(self, api):
        """PRD §3.6: "A `ReportingInsider` drafts a Rule 10b5-1 plan for
        themself — the body's `reporting_person_id` must equal the caller's
        `X-User-ID`, failing with `ERR_FORBIDDEN_ROLE` otherwise"
        PRD §2.1: "When `X-User-Role` is `ReportingInsider`, `X-User-ID` is the
        `id` of the acting `ReportingPerson`; ownership checks on any resource
        that references a `ReportingPerson` compare the resource's
        `reporting_person_id` field to `X-User-ID`, and a mismatch is rejected
        with `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/insider_cannot_create_plan_for_other_person
        """
        issuer = create_issuer()
        p1 = create_reporting_person(issuer["id"], full_name="Dana Owner",
                                     person_cik="0001000002",
                                     is_ten_pct_owner=True)
        p2 = create_reporting_person(issuer["id"], full_name="Eve Owner",
                                     person_cik="0001000003",
                                     is_ten_pct_owner=True)
        resp = api.create_trading_plan(
            {"reporting_person_id": p2["id"], "plan_name": "Plan X",
             "first_trade_date": "2026-11-01", "expiration_date": "2027-03-01"},
            make_reporting_insider_headers(p1["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
