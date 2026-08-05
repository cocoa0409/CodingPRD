"""Delinquency sweep, the enforcement cascade, grace boundary, and enforcement lifts."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    clerk_headers, supervisor_headers, admin_headers,
    setup_defaulted_case, setup_enforcement_actions,
    api_client,
)


class TestPlanDefaultReinstateCycle:
    def test_reinstate_returns_plan_to_active_and_case_current(self, api):
        """PRD §3.2: "a CollectionsSupervisor may reinstate it, moving it from DEFAULTED
        back to ACTIVE. ... it resets missed_payment_count to zero, sets next_due_date
        to the current clock date plus the same 30-day due interval, and resets the
        case's delinquency_status back to CURRENT."

        Design: Difficulty/non_linear_state_machine/plan_default_then_reinstate_cycle
        """
        case, obl, plan, sweep = setup_defaulted_case(case_number="C-CYCLE")

        reinstated = validate_success(api.reinstate_payment_plan(plan["id"], supervisor_headers()))
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["missed_payment_count"] == 0

        case_after = validate_success(api.get_case(case["id"], clerk_headers()))
        assert case_after["delinquency_status"] == "CURRENT"

    def test_default_leg_marks_plan_defaulted_and_case_delinquent(self, api):
        """PRD §3.9: "When a plan defaults, it transitions from ACTIVE to DEFAULTED and a
        cascade fires. The plan's missed_payment_count increases by one. The case's
        delinquency_status flips to DELINQUENT."

        Design: Difficulty/non_linear_state_machine/plan_default_then_reinstate_cycle
        """
        case, obl, plan, sweep = setup_defaulted_case(case_number="C-CYCLE2")

        plan_after = validate_success(api.get_payment_plan(plan["id"], clerk_headers()))
        case_after = validate_success(api.get_case(case["id"], clerk_headers()))
        assert plan_after["status"] == "DEFAULTED"
        assert plan_after["missed_payment_count"] == 1
        assert case_after["delinquency_status"] == "DELINQUENT"


class TestDelinquencyEnforcementCascade:
    def test_default_dockets_civil_judgment_and_license_hold(self, api):
        """PRD §3.9: "An Enforcement Action of type CIVIL_JUDGMENT is docketed for the
        case ... That civil judgment in turn triggers a second enforcement action of
        type LICENSE_HOLD ... Both enforcement actions are created directly by this
        cascade — never by a client body — and both begin in status ACTIVE."

        Design: Difficulty/transitive_cascade/delinquency_cascade_plan_case_judgment_hold
        """
        case, plan, actions = setup_enforcement_actions(case_number="C-CASCADE3")

        plan_after = validate_success(api.get_payment_plan(plan["id"], clerk_headers()))
        case_after = validate_success(api.get_case(case["id"], clerk_headers()))
        assert plan_after["status"] == "DEFAULTED"
        assert case_after["delinquency_status"] == "DELINQUENT"

        assert len(actions) == 2, f"expected exactly two enforcement actions, got {actions}"
        assert {a["type"] for a in actions} == {"CIVIL_JUDGMENT", "LICENSE_HOLD"}
        assert all(a["status"] == "ACTIVE" for a in actions)

    def test_civil_judgment_captures_balance_license_hold_zero(self, api):
        """PRD §3.9: "An Enforcement Action of type CIVIL_JUDGMENT is docketed for the
        case, with its amount_cents capturing the case's balance_cents at the moment of
        docketing. That civil judgment in turn triggers a second enforcement action of
        type LICENSE_HOLD, whose amount_cents is zero."

        Design: Difficulty/transitive_cascade/delinquency_cascade_plan_case_judgment_hold
        """
        case, plan, actions = setup_enforcement_actions(
            case_number="C-CASCADE3B", assessed_amount_cents=100000,
        )
        by_type = {a["type"]: a for a in actions}
        assert by_type["CIVIL_JUDGMENT"]["amount_cents"] == 100000
        assert by_type["LICENSE_HOLD"]["amount_cents"] == 0


class TestDelinquencyGraceBoundary:
    def test_exactly_thirty_days_past_due_defaults(self, api):
        """PRD §3.9: "computes the days past due as the floored number of days between
        the current logical-clock time and the plan's next_due_date. A plan whose days
        past due is at least the 30-day grace window defaults."

        Design: Difficulty/boundary_precision_check/delinquency_grace_exactly_30_days
        """
        case, obl, plan, sweep = setup_defaulted_case(
            case_number="C-BND-DELQ", sweep_clock="2026-07-31T00:00:00Z",
        )
        plan_after = validate_success(api.get_payment_plan(plan["id"], clerk_headers()))
        assert plan_after["status"] == "DEFAULTED"
        assert plan["id"] in sweep["defaulted_plan_ids"]

    def test_twenty_nine_days_past_due_does_not_default(self, api):
        """PRD §3.9: "A plan whose days past due is at least the 30-day grace window
        defaults. The sweep reports the identifiers of the plans it defaulted as
        defaulted_plan_ids."

        Design: Difficulty/boundary_precision_check/delinquency_grace_exactly_30_days
        """
        case, obl, plan, sweep = setup_defaulted_case(
            case_number="C-BND-DELQ29", sweep_clock="2026-07-30T00:00:00Z",
        )
        plan_after = validate_success(api.get_payment_plan(plan["id"], clerk_headers()))
        assert plan_after["status"] == "ACTIVE", "29 days past due is below the 30-day grace"
        assert plan["id"] not in sweep["defaulted_plan_ids"]


class TestEnforcementLiftRequiresCaseCurrent:
    def test_lift_rejected_while_case_delinquent(self, api):
        """PRD §3.9: "A CollectionsSupervisor lifts an enforcement action ... but only
        once the case is no longer delinquent: lifting requires the case's
        delinquency_status to be CURRENT, and otherwise fails with
        ERR_CASE_STILL_DELINQUENT."

        Design: Difficulty/cross_entity_state_dependency/enforcement_lift_requires_case_current
        """
        case, plan, actions = setup_enforcement_actions(case_number="C-STILL-DELQ")
        action = actions[0]

        resp = api.lift_enforcement_action(action["id"], supervisor_headers())
        validate_error(resp, ApiErrorId.ERR_CASE_STILL_DELINQUENT.value, expected_status=409)

        case_after = validate_success(api.get_case(case["id"], clerk_headers()))
        assert case_after["delinquency_status"] == "DELINQUENT"

    def test_lift_succeeds_after_reinstatement_clears_delinquency(self, api):
        """PRD §3.9: "In practice this means the supervisor must first reinstate the
        defaulted plan (§3.2), which resets the case to CURRENT, before the holds against
        the case can be lifted. A lifted action moves to status LIFTED."

        Design: Difficulty/cross_entity_state_dependency/enforcement_lift_requires_case_current
        """
        case, plan, actions = setup_enforcement_actions(case_number="C-LIFTOK")
        action = actions[0]
        validate_success(api.reinstate_payment_plan(plan["id"], supervisor_headers()))

        lifted = validate_success(api.lift_enforcement_action(action["id"], supervisor_headers()))
        assert lifted["status"] == "LIFTED"
