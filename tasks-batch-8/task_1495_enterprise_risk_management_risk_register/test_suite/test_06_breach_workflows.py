"""Breach workflows and plan completion:
- corner/errors breach-resolution-premature and acceptance-cap-exceeded
- corner/endpoints plan_complete_requires_all_actions_done
- difficulty cross_entity_state_dependency (mapping_approve_requires_control_active,
  risk_monitor_requires_no_open_breach)
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_category, create_risk,
    create_assessed_risk, create_residual_assessed_risk,
    create_active_control, create_active_mapping, create_proposed_mapping,
    approve_mapping, create_approved_appetite,
    create_proposed_plan, approve_plan, create_approved_plan,
    create_in_progress_plan, add_action, done_action, cancel_plan,
    create_inherent_assessment, create_residual_assessment,
    get_risk, get_risk_version,
    make_risk_owner_headers, make_risk_manager_headers,
    make_control_owner_headers,
    USER_RISK_OWNER, USER_RISK_MANAGER, USER_RISK_MANAGER_2, USER_CONTROL_OWNER,
)


class TestBreachResolutionPremature:
    """Corner: breach_resolution_premature_rejected."""

    def _build_open_breach(self):
        """Category with APPROVED appetite tolerance 5 cap 20;
        risk inherent 20 (L4 I5), no controls → RESIDUAL gives residual 20;
        20 >= 5 → breach OPEN; acknowledge → ACKNOWLEDGED."""
        cat = create_category(name="BPR")
        create_approved_appetite(cat["id"], tolerance_score=5,
                                    acceptance_cap_score=20)
        risk = create_assessed_risk(
            category_id=cat["id"], likelihood=4, impact=5,
        )
        create_residual_assessment(risk["id"])
        breaches = validate_success(
            api_client.list_risk_tolerance_breaches(
                risk["id"], make_risk_owner_headers(USER_RISK_OWNER),
            ), 200,
        )
        bid = breaches[0]["id"]
        api_client.acknowledge_breach(
            bid, make_risk_owner_headers(USER_RISK_OWNER),
        )
        return risk, bid

    def test_resolve_with_residual_at_or_above_tolerance_rejected(self):
        """PRD §3.4: "Resolving a breach, moving `ACKNOWLEDGED` → `RESOLVED`,
        likewise belongs to that owner and additionally requires the risk's
        `residual_score` at resolve time to be strictly below the linked
        statement's `tolerance_score`; a premature resolution is rejected
        with `ERR_BREACH_RESOLUTION_PREMATURE`."

        Design: Corner/errors/breach_resolution_premature_rejected
        """
        risk, bid = self._build_open_breach()
        res = api_client.resolve_breach(
            bid, make_risk_owner_headers(USER_RISK_OWNER),
        )
        validate_error(res, ApiErrorId.ERR_BREACH_RESOLUTION_PREMATURE.value)

    def test_premature_resolve_leaves_breach_acknowledged(self):
        """PRD §3.4: "Resolving a breach, moving `ACKNOWLEDGED` → `RESOLVED`".

        Design: Corner/errors/breach_resolution_premature_rejected
        """
        risk, bid = self._build_open_breach()
        api_client.resolve_breach(bid, make_risk_owner_headers(USER_RISK_OWNER))
        got = validate_success(
            api_client.get_tolerance_breach(
                bid, make_risk_owner_headers(USER_RISK_OWNER),
            ), 200,
        )
        assert got["status"] == "ACKNOWLEDGED"


class TestBreachAcceptanceCapExceeded:
    def test_accept_above_cap_rejected(self):
        """PRD §3.4: "Accepting a breach, moving `ACKNOWLEDGED` → `ACCEPTED`,
        is a `RiskManager` decision guarded by the acceptance cap: the risk's
        `residual_score` must be at most the linked statement's
        `acceptance_cap_score`, or the acceptance is rejected with
        `ERR_ACCEPTANCE_CAP_EXCEEDED`."

        Design: Corner/errors/breach_acceptance_cap_exceeded_rejected
        """
        cat = create_category(name="CAPX")
        create_approved_appetite(cat["id"], tolerance_score=5,
                                    acceptance_cap_score=20)
        # inherent 25 (L5 I5), no controls → residual 25 > cap 20
        risk = create_assessed_risk(
            category_id=cat["id"], likelihood=5, impact=5,
        )
        create_residual_assessment(risk["id"])
        breaches = validate_success(
            api_client.list_risk_tolerance_breaches(
                risk["id"], make_risk_owner_headers(USER_RISK_OWNER),
            ), 200,
        )
        bid = breaches[0]["id"]
        api_client.acknowledge_breach(
            bid, make_risk_owner_headers(USER_RISK_OWNER),
        )
        res = api_client.accept_breach(
            bid,
            {"rationale": "too hot", "review_by": "2026-12-31T00:00:00Z"},
            make_risk_manager_headers(USER_RISK_MANAGER),
        )
        validate_error(res, ApiErrorId.ERR_ACCEPTANCE_CAP_EXCEEDED.value)


class TestPlanCompleteRequiresAllActionsDone:
    """Corner: plan_complete_requires_all_actions_done."""

    def _build_plan_with_two_actions(self):
        risk = create_residual_assessed_risk(treatment_budget_cents=100_000)
        plan = create_in_progress_plan(risk["id"], budget_cents=40_000)
        a1 = add_action(plan["id"], "a1")
        a2 = add_action(plan["id"], "a2")
        done_action(a1["id"])
        return risk, plan, a1, a2

    def test_complete_with_pending_action_rejected(self):
        """PRD §3.5: "Completing moves `IN_PROGRESS` → `COMPLETED` and
        requires the plan to have at least one action with every action in
        `DONE` status; otherwise the completion is rejected with
        `ERR_INCOMPLETE_ACTIONS`."

        Design: Corner/endpoints/plan_complete_requires_all_actions_done
        """
        _, plan, _, _ = self._build_plan_with_two_actions()
        res = api_client.complete_treatment_plan(
            plan["id"], make_risk_owner_headers(USER_RISK_OWNER),
        )
        validate_error(res, ApiErrorId.ERR_INCOMPLETE_ACTIONS.value)

    def test_complete_after_all_done_succeeds_and_releases_budget(self):
        """PRD §3.5: "Completion releases the reservation and increments the
        risk's `version`."
        PRD §3.5: "an approval followed by its compensating cancellation
        leaves `reserved_treatment_cents` and `available_treatment_cents`
        exactly unchanged."

        Design: Corner/endpoints/plan_complete_requires_all_actions_done
        """
        risk, plan, _, a2 = self._build_plan_with_two_actions()
        done_action(a2["id"])
        res = api_client.complete_treatment_plan(
            plan["id"], make_risk_owner_headers(USER_RISK_OWNER),
        )
        completed = validate_success(res, 200)
        assert completed["status"] == "COMPLETED"
        after = get_risk(risk["id"])
        assert after["reserved_treatment_cents"] == 0


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency
# ---------------------------------------------------------------------------

class TestMappingApproveRequiresControlActive:
    """Two tests for instance mapping_approve_requires_control_active."""

    def test_approve_with_proposed_control_rejected(self):
        """PRD §3.3: "the control must be `ACTIVE`
        (`ERR_CONTROL_NOT_ACTIVE`)".

        Design: Difficulty/cross_entity_state_dependency/mapping_approve_requires_control_active
        """
        risk = create_assessed_risk(likelihood=3, impact=3)
        # Control created but never activated → PROPOSED
        ctl_res = api_client.create_control(
            {"name": "KC", "effectiveness_pct": 0.5},
            make_control_owner_headers(USER_CONTROL_OWNER),
        )
        ctl = validate_success(ctl_res, 201)
        m = create_proposed_mapping(risk["id"], ctl["id"], coverage_weight=0.5)
        res = api_client.approve_mapping(
            m["id"], make_risk_manager_headers(USER_RISK_MANAGER),
        )
        validate_error(res, ApiErrorId.ERR_CONTROL_NOT_ACTIVE.value)

    def test_approve_succeeds_after_control_activated(self):
        """PRD §3.3: "Activation moves it `PROPOSED` → `ACTIVE`".
        PRD §3.3: "Approving a mapping moves it `PROPOSED` → `ACTIVE`".

        Design: Difficulty/cross_entity_state_dependency/mapping_approve_requires_control_active
        """
        risk = create_assessed_risk(likelihood=3, impact=3)
        ctl_res = api_client.create_control(
            {"name": "KC", "effectiveness_pct": 0.5},
            make_control_owner_headers(USER_CONTROL_OWNER),
        )
        ctl = validate_success(ctl_res, 201)
        m = create_proposed_mapping(risk["id"], ctl["id"], coverage_weight=0.5)
        # Activate the control first
        api_client.activate_control(
            ctl["id"], make_control_owner_headers(USER_CONTROL_OWNER),
        )
        res = api_client.approve_mapping(
            m["id"], make_risk_manager_headers(USER_RISK_MANAGER),
        )
        assert validate_success(res, 200)["status"] == "ACTIVE"


class TestRiskMonitorRequiresNoOpenBreach:
    """Two tests for instance risk_monitor_requires_no_open_breach."""

    def _build_treatment_risk_with_breach(self):
        """Category with APPROVED appetite tolerance 9 cap 20;
        risk inherent 20, one ACTIVE mapping contribution 0.60 (residual 8),
        plan APPROVED, risk TREATMENT; then control retired → mapping retired →
        residual recomputed to 20 → breach OPEN."""
        cat = create_category(name="CTOL")
        create_approved_appetite(cat["id"], tolerance_score=9,
                                    acceptance_cap_score=20)
        risk = create_assessed_risk(
            category_id=cat["id"], likelihood=4, impact=5,
            treatment_budget_cents=500_000,
        )
        kg = create_active_control(name="KG", effectiveness_pct=0.6)
        create_active_mapping(risk["id"], kg["id"], coverage_weight=1.0)
        # RESIDUAL: contribution 0.60 → discount 0.60 → ceil(20*0.40) = 8
        create_residual_assessment(risk["id"])
        plan = create_approved_plan(risk["id"], budget_cents=100_000)
        api_client.enter_treatment(
            risk["id"], make_risk_owner_headers(USER_RISK_OWNER),
        )
        # Retire the control → mapping retires → residual recomputed
        api_client.retire_control(
            kg["id"], make_control_owner_headers(USER_CONTROL_OWNER),
        )
        breaches = validate_success(
            api_client.list_risk_tolerance_breaches(
                risk["id"], make_risk_manager_headers(USER_RISK_MANAGER),
            ), 200,
        )
        return risk, plan, breaches[0]

    def test_monitor_blocked_while_breach_open(self):
        """PRD §3.2: "Moving to monitoring, `TREATMENT` → `MONITORING`,
        requires that no tolerance breach for the risk is `OPEN` or
        `ACKNOWLEDGED` (`ERR_OPEN_BREACH_BLOCKING`)".

        Design: Difficulty/cross_entity_state_dependency/risk_monitor_requires_no_open_breach
        """
        risk, _, breach = self._build_treatment_risk_with_breach()
        assert breach["status"] == "OPEN"
        res = api_client.monitor_risk(
            risk["id"], make_risk_owner_headers(USER_RISK_OWNER),
        )
        validate_error(res, ApiErrorId.ERR_OPEN_BREACH_BLOCKING.value)

    def test_monitor_blocked_while_breach_acknowledged(self):
        """PRD §3.2: "Moving to monitoring, `TREATMENT` → `MONITORING`,
        requires that no tolerance breach for the risk is `OPEN` or
        `ACKNOWLEDGED` (`ERR_OPEN_BREACH_BLOCKING`)" — ACKNOWLEDGED also
        blocks.

        Design: Difficulty/cross_entity_state_dependency/risk_monitor_requires_no_open_breach
        """
        risk, _, breach = self._build_treatment_risk_with_breach()
        api_client.acknowledge_breach(
            breach["id"], make_risk_owner_headers(USER_RISK_OWNER),
        )
        res = api_client.monitor_risk(
            risk["id"], make_risk_owner_headers(USER_RISK_OWNER),
        )
        validate_error(res, ApiErrorId.ERR_OPEN_BREACH_BLOCKING.value)
