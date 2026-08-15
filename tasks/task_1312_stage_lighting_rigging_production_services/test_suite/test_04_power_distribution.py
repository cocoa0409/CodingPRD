"""Power distribution planning: the pinned sizing evaluation order, generator
tier boundaries, house service limits, phase imbalance, and the state-over-
safety validation priority on approval."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    setup_planning_production, create_power_plan, get_power_plan,
    submit_power_plan,
)

PM = TEST_USERS["production_manager_headers"]
SI = TEST_USERS["safety_inspector_headers"]


class TestPowerSizingPinnedOrder:
    def test_power_sizing_pinned_evaluation_order(self, api):
        """PRD §3.4: "First, the subtotal is the sum of the three phase wattages. Second, the feeder loss is the subtotal multiplied by 0.03 for every 100 meters of the run — precisely, the subtotal times 0.03 times the `feeder_length_m` divided by 100. Third, `total_load_watts` is the subtotal plus the feeder loss, stored at 2 decimal places, rounded half-up. Fourth, the supply branch. On the generator branch (`generator_required` true), `required_kva` is the loss-inclusive `total_load_watts` divided by the product of a 0.9 power factor, a 0.8 derating factor, and 1000 — stored at 2 decimal places, rounded half-up — and `selected_generator_tier_kva` is the smallest tier from the rental fleet's 45, 60, 100, 150, 200, 300, and 400 kVA tiers that is greater than or equal to the requirement; a requirement exceeding the largest 400 kVA tier fails submission with `ERR_GENERATOR_CAPACITY_EXCEEDED` (HTTP 422)."

        Design: Difficulty/combinatorial_formula/power_sizing_pinned_evaluation_order
        """
        ctx = setup_planning_production()
        plan = create_power_plan(ctx["production"]["id"], feeder_length_m=200,
                                 generator_required=True)
        data = submit_power_plan(plan["id"])
        assert data["status"] == "SUBMITTED"
        # 30000 + 30000 x 0.03 x 2 = 31800.00; 31800 / 720 = 44.17 kVA -> tier 45.
        assert data["total_load_watts"] == pytest.approx(31800.00, abs=0.005)
        assert data["required_kva"] == pytest.approx(44.17, abs=0.005)
        assert data["selected_generator_tier_kva"] == 45
        assert data["max_phase_imbalance_pct"] == pytest.approx(0.0000, abs=0.00005)

    def test_house_branch_computes_total_but_never_kva(self, api):
        """PRD §3.4: "Until the plan is first submitted, the computed fields `total_load_watts`, `required_kva`, `selected_generator_tier_kva`, and `max_phase_imbalance_pct` are null; `required_kva` and `selected_generator_tier_kva` remain null permanently on house-powered plans."

        Design: Difficulty/combinatorial_formula/power_sizing_pinned_evaluation_order
        """
        ctx = setup_planning_production()
        plan = create_power_plan(ctx["production"]["id"], feeder_length_m=100,
                                 generator_required=False)
        data = submit_power_plan(plan["id"])
        assert data["status"] == "SUBMITTED"
        # 30000 + 30000 x 0.03 x 1 = 30900.00 on the house branch.
        assert data["total_load_watts"] == pytest.approx(30900.00, abs=0.005)
        assert data.get("required_kva") is None
        assert data.get("selected_generator_tier_kva") is None


class TestGeneratorTierBoundary:
    def test_generator_tier_boundary_45kva(self, api):
        """PRD §3.4: "On the generator branch (`generator_required` true), `required_kva` is the loss-inclusive `total_load_watts` divided by the product of a 0.9 power factor, a 0.8 derating factor, and 1000 — stored at 2 decimal places, rounded half-up — and `selected_generator_tier_kva` is the smallest tier from the rental fleet's 45, 60, 100, 150, 200, 300, and 400 kVA tiers that is greater than or equal to the requirement; a requirement exceeding the largest 400 kVA tier fails submission with `ERR_GENERATOR_CAPACITY_EXCEEDED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/generator_tier_boundary_45kva
        """
        ctx = setup_planning_production()
        # 32400 W -> required_kva exactly 45.00 (loading exactly 80% of a 45 kVA tier).
        plan1 = create_power_plan(ctx["production"]["id"], phase_l1_watts=10800,
                                  phase_l2_watts=10800, phase_l3_watts=10800,
                                  feeder_length_m=0, generator_required=True)
        data = submit_power_plan(plan1["id"])
        assert data["status"] == "SUBMITTED"
        assert data["required_kva"] == pytest.approx(45.00, abs=0.005)
        assert data["selected_generator_tier_kva"] == 45
        # 32500 W -> 45.14 kVA -> next tier up.
        plan2 = create_power_plan(ctx["production"]["id"], phase_l1_watts=10840,
                                  phase_l2_watts=10830, phase_l3_watts=10830,
                                  feeder_length_m=0, generator_required=True)
        data = submit_power_plan(plan2["id"])
        assert data["required_kva"] == pytest.approx(45.14, abs=0.005)
        assert data["selected_generator_tier_kva"] == 60

    def test_generator_largest_tier_boundary_400kva(self, api):
        """PRD §3.4: "a requirement exceeding the largest 400 kVA tier fails submission with `ERR_GENERATOR_CAPACITY_EXCEEDED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/generator_tier_boundary_45kva
        """
        ctx = setup_planning_production()
        # 288000 W -> required_kva exactly 400.00 -> tier 400 passes (>= rule).
        plan1 = create_power_plan(ctx["production"]["id"], phase_l1_watts=96000,
                                  phase_l2_watts=96000, phase_l3_watts=96000,
                                  feeder_length_m=0, generator_required=True)
        data = submit_power_plan(plan1["id"])
        assert data["status"] == "SUBMITTED"
        assert data["required_kva"] == pytest.approx(400.00, abs=0.005)
        assert data["selected_generator_tier_kva"] == 400
        # 288100 W -> 400.14 kVA exceeds the largest tier.
        plan2 = create_power_plan(ctx["production"]["id"], phase_l1_watts=96034,
                                  phase_l2_watts=96033, phase_l3_watts=96033,
                                  feeder_length_m=0, generator_required=True)
        resp = api.transition_power_plan(plan2["id"], {"to": "SUBMITTED"}, PM)
        validate_error(resp, ApiErrorId.ERR_GENERATOR_CAPACITY_EXCEEDED)


class TestGeneratorCapacityExceeded:
    def test_generator_capacity_exceeded(self, api):
        """PRD §3.4: "a requirement exceeding the largest 400 kVA tier fails submission with `ERR_GENERATOR_CAPACITY_EXCEEDED` (HTTP 422)."
        PRD §3.4: "The computed values persist only when every check passes; a failed submission leaves the plan in `DRAFT` with its computed fields untouched."

        Design: Corner/errors/generator_capacity_exceeded
        """
        ctx = setup_planning_production()
        plan = create_power_plan(ctx["production"]["id"], phase_l1_watts=200000,
                                 phase_l2_watts=200000, phase_l3_watts=200000,
                                 feeder_length_m=0, generator_required=True)
        resp = api.transition_power_plan(plan["id"], {"to": "SUBMITTED"}, PM)
        validate_error(resp, ApiErrorId.ERR_GENERATOR_CAPACITY_EXCEEDED)
        after = get_power_plan(plan["id"])
        assert after["status"] == "DRAFT"
        assert after.get("total_load_watts") is None
        assert after.get("required_kva") is None
        assert after.get("selected_generator_tier_kva") is None


class TestHousePowerOverload:
    def test_house_power_overload(self, api):
        """PRD §3.4: "On the house branch (`generator_required` false), each phase's wattage must not exceed the venue's `house_power_amps_per_phase` multiplied by 208 volts; any phase above that service limit fails with `ERR_HOUSE_POWER_OVERLOAD` (HTTP 422)."
        PRD §3.4: "Per the validation pipeline, the supply-branch capacity failures surface before the imbalance failure when both apply."

        Design: Corner/errors/house_power_overload
        """
        ctx = setup_planning_production()  # 200 A x 208 V = 41600 W per phase
        # 42000 W on L1 exceeds the service limit (and the 100 W phases are also
        # wildly imbalanced; the capacity verdict surfaces first per the pipeline).
        plan1 = create_power_plan(ctx["production"]["id"], phase_l1_watts=42000,
                                  phase_l2_watts=100, phase_l3_watts=100,
                                  feeder_length_m=0, generator_required=False)
        resp = api.transition_power_plan(plan1["id"], {"to": "SUBMITTED"}, PM)
        validate_error(resp, ApiErrorId.ERR_HOUSE_POWER_OVERLOAD)
        # 41600 W exactly passes the house check; imbalance (41600-36200)/41600 = 0.1298 <= 0.15.
        plan2 = create_power_plan(ctx["production"]["id"], phase_l1_watts=41600,
                                  phase_l2_watts=36200, phase_l3_watts=36200,
                                  feeder_length_m=0, generator_required=False)
        data = submit_power_plan(plan2["id"])
        assert data["status"] == "SUBMITTED"
        assert data["max_phase_imbalance_pct"] == pytest.approx(0.1298, abs=0.00005)


class TestStateOverSafetyOnApprove:
    def test_state_over_safety_on_power_plan_approve(self, api):
        """PRD §2.6: "Every write request is evaluated against a fixed pipeline of check categories, and a request that fails an earlier category reports that error without ever reaching a later one." (category 8, declared-transition gates, precedes category 10, structural and capacity limits).
        PRD §3.4: "Fifth, after the supply branch clears, the imbalance check: `max_phase_imbalance_pct` is the spread between the largest and smallest phase loads divided by the largest phase load, stored at 4 decimal places rounded half-up — defined as 0 when all three phases carry zero — and an imbalance strictly greater than 0.15 fails with `ERR_PHASE_IMBALANCE` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/state_over_safety_on_power_plan_approve
        """
        ctx = setup_planning_production()
        plan = create_power_plan(ctx["production"]["id"], phase_l1_watts=40000,
                                 phase_l2_watts=40000, phase_l3_watts=30000,
                                 feeder_length_m=0, generator_required=False)
        # The imbalanced submit fails, leaving the plan DRAFT and still imbalanced.
        resp = api.transition_power_plan(plan["id"], {"to": "SUBMITTED"}, PM)
        validate_error(resp, ApiErrorId.ERR_PHASE_IMBALANCE)
        assert get_power_plan(plan["id"])["status"] == "DRAFT"
        # Approving a DRAFT plan is not a declared transition: the state gate reports first.
        resp = api.transition_power_plan(plan["id"], {"to": "APPROVED"}, SI)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_approve_draft_balanced_plan_is_state_error_then_succeeds(self, api):
        """PRD §2.6: "the requested `to` must be a declared transition from the entity's current state for this actor, and child-creation endpoints require their parent to be in the correct state (`ERR_INVALID_STATE`, HTTP 409)."
        PRD §3.4: "Approving a plan (`SUBMITTED` → `APPROVED`) requires the production to still be `PLANNING` (otherwise `ERR_INVALID_STATE`), supersedes any other `APPROVED` power plan of the same production (moving it to `SUPERSEDED`), and recomputes the production's posture."

        Design: Difficulty/priority_pair_validation_conflict/state_over_safety_on_power_plan_approve
        """
        ctx = setup_planning_production()
        plan = create_power_plan(ctx["production"]["id"])
        resp = api.transition_power_plan(plan["id"], {"to": "APPROVED"}, SI)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        submit_power_plan(plan["id"])
        data = validate_success(api.transition_power_plan(plan["id"], {"to": "APPROVED"}, SI))
        assert data["status"] == "APPROVED"
