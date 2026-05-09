"""Key result mutation, progress posting, and KR.score formula (PRD §3.3)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_value_change_payload, create_milestone_toggle_payload,
    setup_org, create_open_cycle, create_objective,
    add_numeric_kr, add_percentage_kr, add_milestone_kr,
    publish_objective, post_value_change,
    setup_active_individual_objective,
    make_employee_headers,
)


# ---------------------------------------------------------------------------
# KR creation and weight-sum re-check on add/delete
# ---------------------------------------------------------------------------

class TestKRWeightSumOnActive:
    def test_add_kr_to_active_objective_makes_weight_sum_invalid(self, api):
        """PRD §3.3: "the aggregate sum of `KeyResult.weight` across the active key results of an objective is checked at publish time against the tolerance described in §2.5, and is rechecked when key results are added or deleted while the objective is `ACTIVE`."

        Claim: ACTIVE objective with KR weight=1.0; add another KR weight=0.5 → sum=1.5 → ERR_KR_WEIGHTS_INVALID.
        """
        s = setup_active_individual_objective(num_krs=1, kr_kind="NUMERIC")
        # ACTIVE with one KR weight=1.0. Add another weight=0.5
        from test_helpers import create_numeric_kr_payload
        payload = create_numeric_kr_payload(start_value=0, target_value=100, weight=0.5)
        owner_headers = s["org"]["employee_headers"]
        resp = api.create_key_result(s["objective"]["id"], payload, owner_headers)
        validate_error(resp, ApiErrorId.ERR_KR_WEIGHTS_INVALID.value)


# ---------------------------------------------------------------------------
# Progress: type matching, range, and parent state gates
# ---------------------------------------------------------------------------

class TestProgressGates:
    def test_progress_on_draft_objective_returns_err_objective_not_active(self, api):
        """PRD §3.3: "the parent objective must be in `ACTIVE` status (`ERR_OBJECTIVE_NOT_ACTIVE`)".

        Claim: parent is DRAFT → POST progress → ERR_OBJECTIVE_NOT_ACTIVE.
        # difficulty: cross_entity_state_dependency/kr_progress_requires_objective_active
        """
        org = setup_org()
        cycle = create_open_cycle(cycle_code="2026-Q1-PG")
        objective = create_objective(cycle["id"], org["employee_user"]["id"], level="INDIVIDUAL",
                                     department_id=org["department"]["id"])
        kr = add_numeric_kr(objective["id"], org["employee_user"]["id"], 0, 100, 1.0)
        # objective still DRAFT
        payload = create_value_change_payload(50)
        resp = api.post_progress(kr["id"], payload, org["employee_headers"])
        validate_error(resp, ApiErrorId.ERR_OBJECTIVE_NOT_ACTIVE.value)

    def test_progress_after_publish_succeeds_with_same_payload(self, api):
        """PRD §3.3: "the parent objective must be in `ACTIVE` status".

        Claim: same KR; publish parent; same progress payload now succeeds.
        # difficulty: cross_entity_state_dependency/kr_progress_requires_objective_active
        """
        org = setup_org()
        cycle = create_open_cycle(cycle_code="2026-Q1-PA")
        objective = create_objective(cycle["id"], org["employee_user"]["id"], level="INDIVIDUAL",
                                     department_id=org["department"]["id"])
        kr = add_numeric_kr(objective["id"], org["employee_user"]["id"], 0, 100, 1.0)
        payload = create_value_change_payload(50)
        # First: rejected
        resp1 = api.post_progress(kr["id"], payload, org["employee_headers"])
        validate_error(resp1, ApiErrorId.ERR_OBJECTIVE_NOT_ACTIVE.value)
        # Publish
        publish_objective(objective["id"], org["employee_user"]["id"])
        # Retry: succeeds
        resp2 = api.post_progress(kr["id"], payload, org["employee_headers"])
        validate_success(resp2, expected_status=201)

    def test_progress_value_above_target_rejected_for_numeric(self, api):
        """PRD §3.3: "Out-of-range values are rejected with `ERR_PROGRESS_OUT_OF_RANGE`."
        PRD §3.3: "when `target_value` is greater than `start_value`, `new_value` must lie in the closed interval from `start_value` through `target_value`".

        Claim: NUMERIC start=0 target=100; new_value=150 → ERR_PROGRESS_OUT_OF_RANGE.
        # difficulty: combinatorial_formula/kr_score_branched_clamp_three_inputs
        """
        s = setup_active_individual_objective(num_krs=1, kr_kind="NUMERIC")
        payload = create_value_change_payload(150)
        resp = api.post_progress(s["krs"][0]["id"], payload, s["org"]["employee_headers"])
        validate_error(resp, ApiErrorId.ERR_PROGRESS_OUT_OF_RANGE.value)

    def test_milestone_toggle_on_numeric_kr_returns_err_kr_type_mismatch(self, api):
        """PRD §3.3: "Mismatches between `update_type` and `KeyResult.measurement_type` are rejected with `ERR_KR_TYPE_MISMATCH`."
        """
        s = setup_active_individual_objective(num_krs=1, kr_kind="NUMERIC")
        payload = create_milestone_toggle_payload(0, True)
        resp = api.post_progress(s["krs"][0]["id"], payload, s["org"]["employee_headers"])
        validate_error(resp, ApiErrorId.ERR_KR_TYPE_MISMATCH.value)

    def test_value_change_on_milestone_kr_returns_err_kr_type_mismatch(self, api):
        """PRD §3.3: "Mismatches between `update_type` and `KeyResult.measurement_type` are rejected with `ERR_KR_TYPE_MISMATCH`."
        """
        s = setup_active_individual_objective(num_krs=1, kr_kind="MILESTONE")
        payload = create_value_change_payload(0.5)
        resp = api.post_progress(s["krs"][0]["id"], payload, s["org"]["employee_headers"])
        validate_error(resp, ApiErrorId.ERR_KR_TYPE_MISMATCH.value)


# ---------------------------------------------------------------------------
# Difficulty-design: priority_pair state vs business_constraint
# ---------------------------------------------------------------------------

class TestPriorityStateVsBusiness:
    """# difficulty: priority_pair_validation_conflict/state_vs_business_constraint_progress_update"""

    def test_state_objective_not_active_wins_over_progress_out_of_range(self, api):
        """PRD §2.6: "**State preconditions.** Cycle in correct status (`ERR_CYCLE_NOT_OPEN`); objective in correct status (`ERR_OBJECTIVE_NOT_ACTIVE`)" runs before "**Business referential and structural rules.**...progress out of range (`ERR_PROGRESS_OUT_OF_RANGE`)".

        Claim: parent DRAFT (state would fail) AND new_value=200 out of range (business would fail) →
        ERR_OBJECTIVE_NOT_ACTIVE wins.
        # difficulty: priority_pair_validation_conflict/state_vs_business_constraint_progress_update
        """
        org = setup_org()
        cycle = create_open_cycle(cycle_code="2026-Q1-PR")
        objective = create_objective(cycle["id"], org["employee_user"]["id"], level="INDIVIDUAL",
                                     department_id=org["department"]["id"])
        kr = add_numeric_kr(objective["id"], org["employee_user"]["id"], 0, 100, 1.0)
        # Both fail simultaneously: objective is DRAFT AND new_value=200 is out of [0,100]
        payload = create_value_change_payload(200)
        resp = api.post_progress(kr["id"], payload, org["employee_headers"])
        validate_error(resp, ApiErrorId.ERR_OBJECTIVE_NOT_ACTIVE.value)
        body = resp.json()
        assert body["data"]["error_id"] != ApiErrorId.ERR_PROGRESS_OUT_OF_RANGE.value


# ---------------------------------------------------------------------------
# Difficulty-design: combinatorial_formula/kr_score_branched_clamp_three_inputs
# ---------------------------------------------------------------------------

class TestKRScoreBranchedClampThreeInputs:
    """# difficulty: combinatorial_formula/kr_score_branched_clamp_three_inputs"""

    def test_numeric_score_at_target_equals_one(self, api):
        """PRD §3.3: "the raw fraction is `current_value` minus `start_value`, divided by the quantity `target_value` minus `start_value`".

        Claim: NUMERIC start=0 target=100 current=100 → score=1.0000.
        # difficulty: combinatorial_formula/kr_score_branched_clamp_three_inputs
        """
        s = setup_active_individual_objective(num_krs=1, kr_kind="NUMERIC")
        post_value_change(s["krs"][0]["id"], s["org"]["employee_user"]["id"], 100)
        kr = validate_success(api.get_key_result(s["krs"][0]["id"], s["org"]["admin_headers"]))
        assert float(kr["score"]) == pytest.approx(1.0000, abs=1e-6)

    def test_percentage_score_with_nonzero_start_baseline(self, api):
        """PRD §3.3: "`NUMERIC` and `PERCENTAGE` key results carry a `start_value` (the baseline), a `target_value` (the goal), and a `current_value`".
        PRD §3.3: "the raw fraction is `current_value` minus `start_value`, divided by the quantity `target_value` minus `start_value`".

        Claim: PERCENTAGE start=0.2 target=0.8 current=0.5 → score=(0.5-0.2)/(0.8-0.2)=0.5000.
        # difficulty: combinatorial_formula/kr_score_branched_clamp_three_inputs
        """
        org = setup_org()
        cycle = create_open_cycle(cycle_code="2026-Q1-PB")
        objective = create_objective(cycle["id"], org["employee_user"]["id"], level="INDIVIDUAL",
                                     department_id=org["department"]["id"])
        kr = add_percentage_kr(objective["id"], org["employee_user"]["id"],
                               start_value=0.2, target_value=0.8, weight=1.0)
        publish_objective(objective["id"], org["employee_user"]["id"])
        post_value_change(kr["id"], org["employee_user"]["id"], 0.5)
        kr_after = validate_success(api.get_key_result(kr["id"], org["admin_headers"]))
        assert float(kr_after["score"]) == pytest.approx(0.5000, abs=1e-6)

    def test_milestone_score_two_of_three_completed(self, api):
        """PRD §3.3: "For `MILESTONE` key results, the raw fraction is the count of milestones whose `completed` is true divided by the total number of milestones in the array".
        PRD §2.5: "rounded **half up** (i.e., a midpoint rounds away from zero)".

        Claim: 2 of 3 milestones completed → round(2/3, 4) = 0.6667.
        # difficulty: combinatorial_formula/kr_score_branched_clamp_three_inputs
        """
        org = setup_org()
        cycle = create_open_cycle(cycle_code="2026-Q1-MS")
        objective = create_objective(cycle["id"], org["employee_user"]["id"], level="INDIVIDUAL",
                                     department_id=org["department"]["id"])
        kr = add_milestone_kr(
            objective["id"], org["employee_user"]["id"],
            milestones=[
                {"label": "a", "completed": False},
                {"label": "b", "completed": False},
                {"label": "c", "completed": False},
            ],
            weight=1.0,
        )
        publish_objective(objective["id"], org["employee_user"]["id"])
        # Toggle milestones 0 and 1 to completed
        api.post_progress(
            kr["id"], create_milestone_toggle_payload(0, True),
            org["employee_headers"],
        )
        api.post_progress(
            kr["id"], create_milestone_toggle_payload(1, True),
            org["employee_headers"],
        )
        kr_after = validate_success(api.get_key_result(kr["id"], org["admin_headers"]))
        assert float(kr_after["score"]) == pytest.approx(0.6667, abs=1e-6)


# ---------------------------------------------------------------------------
# Score clamp + 4dp rounding
# ---------------------------------------------------------------------------

class TestScoreClampAndRounding:
    def test_kr_score_in_range_zero_one(self, api):
        """PRD §2.5: "any computed value below 0 is replaced by 0, and any computed value above 1 is replaced by 1."

        Claim: NUMERIC start=0 target=100 current=0 → score=0.0000.
        """
        s = setup_active_individual_objective(num_krs=1, kr_kind="NUMERIC")
        kr = validate_success(api.get_key_result(s["krs"][0]["id"], s["org"]["admin_headers"]))
        # Initial score is 0
        assert float(kr["score"]) == pytest.approx(0.0, abs=1e-6)
