"""PIP lifecycle claims: initial state, extension cycle, terminal lockdown,
single-active-plan invariant, withdrawal invariants, and auto-activation."""
import pytest

from test_helpers import (
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    setup_cast,
    add_employee,
    setup_concern_and_template,
    create_draft_pip,
    create_and_issue_pip,
    setup_issued_pip,
    setup_active_pip,
    setup_pip_ready_for_outcome,
    propose_outcome,
    approve_outcome,
    get_pip,
    get_employee,
    get_goals,
    set_clock,
    create_check_in_payload,
    make_hrbp_headers,
    make_director_headers,
)


class TestPipInitialState:
    def test_new_pip_is_draft(self, api):
        """PRD §3.3: "and the plan opens in `DRAFT`."
        PRD §3.6: "an `EXTENSION` requires the plan's `extension_count` — the count
        of extension cycles already consumed, starting at zero".

        Design: Corner/state_machines/pip_initial_state_is_draft
        """
        cast = setup_cast()
        concern, template = setup_concern_and_template(cast)
        pip = create_draft_pip(cast, concern["id"], template["id"])
        assert pip["status"] == "DRAFT"
        assert pip["extension_count"] == 0
        assert pip["version"] == 1


class TestPipExtensionCycle:
    def _setup_extended_pip(self, api):
        """ACTIVE PIP with an APPROVED EXTENSION; returns (ctx, proposer, director)."""
        cast = setup_cast()
        issuer = cast["hrbp_id"]
        proposer = add_employee(
            cast["ou_id"], "Proposer HRBP", "h1@x.com", job_level=7
        )
        director = add_employee(
            cast["ou_id"], "Director", "d@x.com", job_level=9
        )
        ctx = setup_issued_pip(cast=cast)
        resp = api.create_check_in(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
            create_check_in_payload(scheduled_for="2026-08-11T00:00:00Z"),
            make_hrbp_headers(issuer),
        )
        ctx["check_in_id"] = get_success_data(resp)["id"]
        # Plan auto-activates once clock reaches start_date and a check-in exists.
        set_clock(ctx["ou_id"], "2026-09-01T00:00:00Z")  # past end_date
        resp = propose_outcome(ctx, "EXTENSION", proposer_hrbp_id=proposer["id"],
                               rationale="Progress observed but not yet at bar; recommend extension.")
        decision = validate_success(resp, expected_status=201)
        resp = approve_outcome(ctx, decision["id"], director_id=director["id"])
        validate_success(resp)
        ctx["proposer_id"] = proposer["id"]
        ctx["director_id"] = director["id"]
        return ctx

    def test_approved_extension_cycles_back_to_active(self, api):
        """PRD §3.6: "An approved `EXTENSION` moves the plan through `EXTENDED` — a
        transient marker under which the plan immediately re-enters `ACTIVE` for the
        extension window — pushing `end_date` out by half the template's duration
        rounded down to whole days and incrementing `extension_count`".

        Design: Difficulty/non_linear_state_machine/pip_extended_cycles_back_to_active
        """
        ctx = self._setup_extended_pip(api)
        pip = get_pip(ctx)
        assert pip["status"] == "ACTIVE", (
            f"extension must cycle EXTENDED -> ACTIVE, got {pip['status']}"
        )
        assert pip["extension_count"] == 1
        # 30-day template: extended end = 2026-08-31 + floor(30/2)=15 days.
        assert pip["end_date"] == "2026-09-15T00:00:00Z", (
            f"extended end_date must be 2026-09-15T00:00:00Z, got {pip['end_date']}"
        )

    def test_second_extension_proposal_rejected(self, api):
        """PRD §3.6: "an `EXTENSION` requires the plan's `extension_count` — the
        count of extension cycles already consumed, starting at zero — to still be
        below its single allowance of one (`ERR_EXTENSION_LIMIT_EXCEEDED`)".

        Design: Difficulty/non_linear_state_machine/pip_extended_cycles_back_to_active
        """
        ctx = self._setup_extended_pip(api)
        set_clock(ctx["ou_id"], "2026-09-16T00:00:00Z")  # past extended end_date
        resp = propose_outcome(
            ctx, "EXTENSION", proposer_hrbp_id=ctx["proposer_id"],
            rationale="Attempting a second extension beyond the single allowance.",
        )
        validate_error(resp, ApiErrorId.ERR_EXTENSION_LIMIT_EXCEEDED)


class TestPipTerminalLockdown:
    def _setup_closed_success_pip(self, api):
        ctx = setup_active_pip()
        # Meet the single goal (target 2) so SUCCESS passes the 0.80 guard.
        goals = get_goals(ctx)
        from test_helpers import submit_and_adjudicate_evidence, hold_check_in
        submit_and_adjudicate_evidence(
            ctx, ctx["check_in_id"], goals[0]["id"], observed_value=2
        )
        hold_check_in(ctx, ctx["check_in_id"], notes="Goal met early; sustaining trajectory.")
        set_clock(ctx["ou_id"], "2026-09-01T00:00:00Z")
        proposer = add_employee(ctx["ou_id"], "Proposer", "h1@x.com", job_level=7)
        resp = propose_outcome(ctx, "SUCCESS", proposer_hrbp_id=proposer["id"],
                               rationale="Attainment at 1.0 across all goals on the plan.")
        decision = validate_success(resp, expected_status=201)
        ctx["proposer_id"] = proposer["id"]
        resp = approve_outcome(ctx, decision["id"])
        validate_success(resp)
        set_clock(ctx["ou_id"], "2026-09-07T00:00:00Z")  # rebuttal window lapses
        return ctx

    def test_withdraw_on_closed_success_pip_rejected(self, api):
        """PRD §3.3: "Withdrawal is the early exit, available to the plan's issuing
        HRBP while the plan is `ISSUED` or `ACTIVE` — any other state fails
        `ERR_INVALID_STATE`".

        Design: Corner/state_machines/pip_terminal_lockdown_closed_success_no_further_transitions
        """
        ctx = self._setup_closed_success_pip(api)
        resp = api.withdraw_pip(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
            make_hrbp_headers(ctx["hrbp_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_issue_on_closed_success_pip_rejected(self, api):
        """PRD §3.3: "the plan must be `DRAFT` (`ERR_INVALID_STATE`)" for issuance.

        Design: Corner/state_machines/pip_terminal_lockdown_closed_success_no_further_transitions
        """
        ctx = self._setup_closed_success_pip(api)
        pip = get_pip(ctx)
        assert pip["status"] == "CLOSED_SUCCESS"
        resp = api.issue_pip(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
            {"expected_pip_version": pip["version"]},
            make_hrbp_headers(ctx["hrbp_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSingleActivePipInvariant:
    def test_second_pip_blocked_while_first_in_flight(self, api):
        """PRD §3.3: "The employee must be `ACTIVE` (`ERR_EMPLOYEE_NOT_ACTIVE`) and
        must not already carry a plan in `ISSUED`, `ACTIVE`, or `EXTENDED` — the
        single-active-plan invariant, enforced as `ERR_ACTIVE_PIP_EXISTS`."

        Design: Difficulty/resource_temporal_overlap/employee_inflight_pip_state_occupation_blocks_second_pip
        """
        cast = setup_cast()
        # Two independent ACCEPTED concerns (each backed by its own entry pair).
        q_entries = []
        v_entries = []
        from test_helpers import create_coaching_entries, create_and_accept_concern
        q_entries = create_coaching_entries(cast, count=2, category="QUALITY")
        concern1 = create_and_accept_concern(cast, q_entries, category="QUALITY",
                                             summary="Quality below bar for level")
        v_entries = create_coaching_entries(cast, count=2, category="VELOCITY")
        concern2 = create_and_accept_concern(cast, v_entries, category="VELOCITY",
                                             summary="Velocity below bar for level")
        from test_helpers import create_and_publish_template
        template = create_and_publish_template(cast)
        pip1 = create_and_issue_pip(cast, concern1["id"], template["id"])

        resp = api.create_pip(
            cast["ou_id"], cast["emp_id"],
            {"concern_id": concern2["id"], "template_id": template["id"],
             "start_date": "2026-09-01T00:00:00Z"},
            make_hrbp_headers(cast["hrbp_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ACTIVE_PIP_EXISTS)
        emp = get_employee(cast)
        assert emp["active_pip_id"] == pip1["id"]

    def test_second_pip_allowed_after_first_withdrawn(self, api):
        """PRD §3.3: "Withdrawal closes the plan as `CLOSED_WITHDRAWN`, stamps
        `closed_at`, clears the employee's `active_pip_id`" — after which the
        single-active-plan invariant no longer blocks a fresh plan.

        Design: Difficulty/resource_temporal_overlap/employee_inflight_pip_state_occupation_blocks_second_pip
        """
        cast = setup_cast()
        from test_helpers import create_coaching_entries, create_and_accept_concern, create_and_publish_template
        q_entries = create_coaching_entries(cast, count=2, category="QUALITY")
        concern1 = create_and_accept_concern(cast, q_entries, category="QUALITY",
                                             summary="Quality below bar for level")
        v_entries = create_coaching_entries(cast, count=2, category="VELOCITY")
        concern2 = create_and_accept_concern(cast, v_entries, category="VELOCITY",
                                             summary="Velocity below bar for level")
        template = create_and_publish_template(cast)
        pip1 = create_and_issue_pip(cast, concern1["id"], template["id"])
        validate_success(api.withdraw_pip(
            cast["ou_id"], cast["emp_id"], pip1["id"],
            make_hrbp_headers(cast["hrbp_id"]),
        ))
        resp = api.create_pip(
            cast["ou_id"], cast["emp_id"],
            {"concern_id": concern2["id"], "template_id": template["id"],
             "start_date": "2026-09-01T00:00:00Z"},
            make_hrbp_headers(cast["hrbp_id"]),
        )
        pip2 = validate_success(resp, expected_status=201)
        assert pip2["status"] == "DRAFT"


class TestWithdrawalInvariants:
    def test_goal_weight_sum_conserved_across_issue_and_withdraw(self, api):
        """PRD §3.3: "the weights across a plan always summing to 100".
        PRD §3.3: "Withdrawal closes the plan as `CLOSED_WITHDRAWN`".

        Design: Difficulty/compensating_invariant/pip_goal_weight_sum_conserved_across_create_withdraw
        """
        cast = setup_cast()
        concern, template = setup_concern_and_template(
            cast,
            goal_blueprints=[
                {"metric_key": "defects", "target_value": 2, "unit": "count", "weight": 40},
                {"metric_key": "review_turnaround_hours", "target_value": 24, "unit": "hours", "weight": 35},
                {"metric_key": "postmortem_count", "target_value": 3, "unit": "count", "weight": 25},
            ],
        )
        pip = create_and_issue_pip(cast, concern["id"], template["id"])
        ctx = {**cast, "pip_id": pip["id"]}
        goals_after_issue = get_goals(ctx)
        assert len(goals_after_issue) == 3
        assert sum(g["weight"] for g in goals_after_issue) == 100

        validate_success(api.withdraw_pip(
            cast["ou_id"], cast["emp_id"], pip["id"],
            make_hrbp_headers(cast["hrbp_id"]),
        ))
        pip_after = get_pip(ctx)
        assert pip_after["status"] == "CLOSED_WITHDRAWN"
        goals_after_withdraw = get_goals(ctx)
        assert len(goals_after_withdraw) == 3, "goal rows must survive withdrawal"
        assert sum(g["weight"] for g in goals_after_withdraw) == 100

    def test_active_pip_id_returns_to_null_after_withdraw(self, api):
        """PRD §3.3: "the employee's `active_pip_id` is set to the plan" (issuance)
        and "Withdrawal closes the plan as `CLOSED_WITHDRAWN`, stamps `closed_at`,
        clears the employee's `active_pip_id`".

        Design: Difficulty/compensating_invariant/employee_active_pip_id_conserved_across_issue_then_close
        """
        cast = setup_cast()
        concern, template = setup_concern_and_template(cast)
        emp_pre = get_employee(cast)
        assert emp_pre.get("active_pip_id") is None

        pip = create_and_issue_pip(cast, concern["id"], template["id"])
        emp_mid = get_employee(cast)
        assert emp_mid["active_pip_id"] == pip["id"]

        validate_success(api.withdraw_pip(
            cast["ou_id"], cast["emp_id"], pip["id"],
            make_hrbp_headers(cast["hrbp_id"]),
        ))
        emp_post = get_employee(cast)
        assert emp_post.get("active_pip_id") is None, (
            "active_pip_id must return to null after withdrawal"
        )


class TestPipAutoActivation:
    def test_pip_auto_activates_when_clock_reaches_start_date(self, api):
        """PRD §3.3: "Activation requires no further action. Once the clock reaches
        `start_date` and at least one check-in stands `SCHEDULED` for the plan, the
        plan moves `ISSUED` → `ACTIVE` on its own."

        Design: Corner/cross_cutting_complexity_layers/scheduled_action_pip_auto_activates_at_start_date
        """
        ctx = setup_issued_pip(start_date="2026-08-05T00:00:00Z")
        resp = api.create_check_in(
            ctx["ou_id"], ctx["emp_id"], ctx["pip_id"],
            create_check_in_payload(scheduled_for="2026-08-15T00:00:00Z"),
            make_hrbp_headers(ctx["hrbp_id"]),
        )
        validate_success(resp, expected_status=201)
        before = get_pip(ctx)
        assert before["status"] == "ISSUED"  # clock still at 2026-08-01

        set_clock(ctx["ou_id"], "2026-08-05T00:00:01Z")
        after = get_pip(ctx)
        assert after["status"] == "ACTIVE", (
            f"plan must auto-activate once clock passes start_date, got {after['status']}"
        )
