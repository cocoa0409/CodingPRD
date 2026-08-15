"""Difficulty: compensating_invariant — approve/cancel and approve/retire
pairs leave the conserved quantity unchanged."""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    ApiErrorId,
    create_category, create_risk, create_assessed_risk,
    create_active_control, create_proposed_mapping, approve_mapping,
    retire_mapping, create_proposed_plan, approve_plan, cancel_plan,
    get_risk,
    assert_risk_budget_invariant,
    make_risk_owner_headers, make_risk_manager_headers,
    make_control_owner_headers,
    USER_RISK_OWNER, USER_RISK_MANAGER, USER_CONTROL_OWNER,
)


class TestTreatmentBudgetApproveCancelConservation:
    """Difficulty instance: budget cents are conserved across
    approve-then-cancel."""

    def _build(self):
        cat = create_category(name="CI1")
        risk = create_assessed_risk(
            category_id=cat["id"], likelihood=3, impact=3,
            treatment_budget_cents=1_000_000,
        )
        plan = create_proposed_plan(risk["id"], budget_cents=300_000)
        return risk, plan

    def test_approve_then_reserved_is_updated(self):
        """PRD §3.5: "On approval the plan's `budget_cents` is added to the
        risk's `reserved_treatment_cents`".
        PRD §3.5: "its `available_treatment_cents` is `treatment_budget_cents`
        minus that reservation".

        Design: Difficulty/compensating_invariant/treatment_budget_approve_cancel_conservation
        """
        risk, plan = self._build()
        approve_plan(plan["id"])
        after = get_risk(risk["id"])
        assert after["reserved_treatment_cents"] == 300_000
        assert after["available_treatment_cents"] == 700_000
        assert_risk_budget_invariant(after)

    def test_compensating_cancel_restores_budget(self):
        """PRD §3.5: "an approval followed by its compensating cancellation
        leaves `reserved_treatment_cents` and `available_treatment_cents`
        exactly unchanged."

        Design: Difficulty/compensating_invariant/treatment_budget_approve_cancel_conservation
        """
        risk, plan = self._build()
        approve_plan(plan["id"])
        cancel_plan(plan["id"])
        after = get_risk(risk["id"])
        assert after["reserved_treatment_cents"] == 0
        assert after["available_treatment_cents"] == 1_000_000
        # The plan itself lands in CANCELLED
        plan_after = validate_success(
            api_client.get_treatment_plan(
                plan["id"], make_risk_manager_headers(USER_RISK_MANAGER),
            ), 200,
        )
        assert plan_after["status"] == "CANCELLED"


class TestControlMappedCountConservation:
    """Difficulty instance: control.mapped_active_count is conserved across
    approve-then-retire."""

    def _build(self):
        cat = create_category(name="CI2")
        risk = create_assessed_risk(
            category_id=cat["id"], likelihood=2, impact=4,
        )
        ctl = create_active_control(name="KC", effectiveness_pct=0.5,
                                     max_mapped_risks=3)
        m = create_proposed_mapping(risk["id"], ctl["id"], coverage_weight=0.5)
        return risk, ctl, m

    def test_approve_increments_mapped_active_count(self):
        """PRD §3.3: "Approving a mapping moves it `PROPOSED` → `ACTIVE`,
        increments `mapped_active_count` by 1".

        Design: Difficulty/compensating_invariant/control_mapped_count_create_retire_conservation
        """
        _, ctl, m = self._build()
        approve_mapping(m["id"])
        got = validate_success(
            api_client.get_control(
                ctl["id"], make_control_owner_headers(USER_CONTROL_OWNER),
            ), 200,
        )
        assert got["mapped_active_count"] == 1

    def test_approve_then_retire_conserves_count(self):
        """PRD §3.3: "An approval followed by the retirement of the same
        mapping leaves the control's `mapped_active_count` exactly unchanged."

        Design: Difficulty/compensating_invariant/control_mapped_count_create_retire_conservation
        """
        risk, ctl, m = self._build()
        approve_mapping(m["id"])
        retire_mapping(m["id"])
        got = validate_success(
            api_client.get_control(
                ctl["id"], make_control_owner_headers(USER_CONTROL_OWNER),
            ), 200,
        )
        assert got["mapped_active_count"] == 0
        # And no ACTIVE mapping remains under this control
        list_res = api_client.list_control_mappings(
            ctl["id"], make_control_owner_headers(USER_CONTROL_OWNER),
        )
        mappings = validate_success(list_res, 200)
        assert all(mm["status"] != "ACTIVE" for mm in mappings)
