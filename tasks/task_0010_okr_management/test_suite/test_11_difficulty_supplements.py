"""Supplementary tests so every difficulty-design instance has at least TWO dedicated tests.

Each test in this file carries a `# difficulty: <rule_id>/<instance>` tag in its docstring
that supplements existing coverage in test_02–test_10.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, NON_EXISTENT_UUID,
    self_submit_payload, manager_submit_payload, calibrate_payload,
    create_value_change_payload,
    create_co_owner_payload, create_access_grant_payload,
    setup_org, create_open_cycle, create_cycle, create_objective,
    add_numeric_kr, publish_objective,
    post_value_change,
    setup_objective_with_two_active_krs,
    setup_three_level_hierarchy,
    setup_locked_cycle_with_two_objectives_and_link,
    setup_active_individual_objective,
    setup_confidential_objective,
    create_user, make_employee_headers,
)


# ---------------------------------------------------------------------------
# Supplemental: combinatorial_formula/objective_progress_round_per_kr_then_sum
# ---------------------------------------------------------------------------

class TestRoundOrderSecondInstance:
    """# difficulty: combinatorial_formula/objective_progress_round_per_kr_then_sum"""

    def test_round_order_difference_proves_per_kr_first_path(self, api):
        """PRD §3.4: "The order is deliberate: rounding each contributing term before the weighted sum, rather than rounding only at the end, prevents last-decimal divergence between independently computed roll-ups."

        Claim: with KR1 raw=1/3, KR2 raw=2/7, weights 0.4/0.6 — the sum-then-round answer
        is 0.3048 and the per-KR-first answer is 0.3047. The PRD-faithful answer is 0.3047.
        This test independently asserts that the answer matches the per-KR-first formula and
        differs from the sum-then-round formula, by computing both and checking each.
        # difficulty: combinatorial_formula/objective_progress_round_per_kr_then_sum
        """
        s = setup_objective_with_two_active_krs(weights=(0.4, 0.6), targets=(3, 7))
        post_value_change(s["kr1"]["id"], s["org"]["employee_user"]["id"], 1)
        post_value_change(s["kr2"]["id"], s["org"]["employee_user"]["id"], 2)
        obj = validate_success(api.get_objective(s["objective"]["id"], s["org"]["admin_headers"]))
        prog = float(obj["progress"])
        # Per-KR-first compute
        per_kr_first = round(round(1/3, 4) * 0.4 + round(2/7, 4) * 0.6, 4)
        sum_then_round = round((1/3) * 0.4 + (2/7) * 0.6, 4)
        assert per_kr_first == pytest.approx(0.3047, abs=1e-9)
        assert sum_then_round == pytest.approx(0.3048, abs=1e-9)
        assert prog == pytest.approx(per_kr_first, abs=1e-6)
        assert prog != pytest.approx(sum_then_round, abs=1e-6)


# ---------------------------------------------------------------------------
# Supplemental: transitive_cascade/progress_rollup_three_levels
# ---------------------------------------------------------------------------

class TestThreeLevelCascadeSecondInstance:
    """# difficulty: transitive_cascade/progress_rollup_three_levels"""

    def test_three_level_cascade_zero_to_full_progress_propagation(self, api):
        """PRD §3.4: "When a `ProgressUpdate` is appended to a key result, the key result's score is recomputed, the parent objective's progress is recomputed, and any objective above that one (via `parent_objective_id`) is recomputed in turn until the root is reached."

        Claim: same 3-level setup; updating KR to current=100 (raw=1.0) makes leaf, parent,
        grandparent progress all 1.0000 (different cascade end-state from the 50% case).
        # difficulty: transitive_cascade/progress_rollup_three_levels
        """
        s = setup_three_level_hierarchy()
        post_value_change(s["kr_l"]["id"], s["team_user"]["id"], 100)
        admin = s["org"]["admin_headers"]
        leaf = validate_success(api.get_objective(s["leaf"]["id"], admin))
        parent = validate_success(api.get_objective(s["parent"]["id"], admin))
        grandparent = validate_success(api.get_objective(s["grandparent"]["id"], admin))
        assert float(leaf["progress"]) == pytest.approx(1.0000, abs=1e-6)
        assert float(parent["progress"]) == pytest.approx(1.0000, abs=1e-6)
        assert float(grandparent["progress"]) == pytest.approx(1.0000, abs=1e-6)


# ---------------------------------------------------------------------------
# Supplemental: transitive_cascade/cycle_archive_cascade_to_links
# ---------------------------------------------------------------------------

class TestCycleArchiveCascadeSecondInstance:
    """# difficulty: transitive_cascade/cycle_archive_cascade_to_links"""

    def test_cycle_archive_terminal_status_propagation(self, api, admin_headers):
        """PRD §3.1: "Archiving a cycle advances it from `LOCKED` to `ARCHIVED`; the archive cascade transitions every objective in the cycle to `ARCHIVED`".

        Claim (second instance): independent assertion that, after archive, the cycle and
        both objectives reach terminal ARCHIVED status (rather than being left in LOCKED).
        # difficulty: transitive_cascade/cycle_archive_cascade_to_links
        """
        s = setup_locked_cycle_with_two_objectives_and_link()
        api.archive_cycle(s["cycle"]["id"], admin_headers)
        cycle = validate_success(api.get_cycle(s["cycle"]["id"], admin_headers))
        a = validate_success(api.get_objective(s["objective_a"]["id"], admin_headers))
        b = validate_success(api.get_objective(s["objective_b"]["id"], admin_headers))
        assert cycle["status"] == "ARCHIVED"
        assert a["status"] == "ARCHIVED"
        assert b["status"] == "ARCHIVED"


# ---------------------------------------------------------------------------
# Supplemental: priority_pair_validation_conflict/existence_vs_state_objective_create
# ---------------------------------------------------------------------------

class TestExistenceVsStateSecondInstance:
    """# difficulty: priority_pair_validation_conflict/existence_vs_state_objective_create"""

    def test_existence_cycle_not_found_wins_over_state(self, api):
        """PRD §2.6: "Each existence failure surfaces its own 404 error before any state or business check runs."
        PRD §2.6 priority 2: "A missing cycle in the path or body raises `ERR_CYCLE_NOT_FOUND`".

        Claim (second instance): an unknown cycle_id (existence) AND an owner who is fine
        (so state would never be the only blocker) — existence still wins. We use
        ERR_CYCLE_NOT_FOUND because cycle is required and an unknown id triggers existence
        before any state/business check could run.
        # difficulty: priority_pair_validation_conflict/existence_vs_state_objective_create
        """
        org = setup_org()
        payload = {
            "cycle_id": NON_EXISTENT_UUID,  # existence: ERR_CYCLE_NOT_FOUND
            "level": "INDIVIDUAL",
            "department_id": org["department"]["id"],
            "owner_user_id": org["employee_user"]["id"],
            "title": "t",
            "weight": 1.0,
        }
        resp = api.create_objective(payload, org["admin_headers"])
        # PRD priority 2 (existence) wins; state would have been priority 4
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Supplemental: priority_pair_validation_conflict/state_vs_business_constraint_progress_update
# ---------------------------------------------------------------------------

class TestStateVsBusinessConstraintSecondInstance:
    """# difficulty: priority_pair_validation_conflict/state_vs_business_constraint_progress_update"""

    def test_business_constraint_surfaces_when_state_passes(self, api):
        """PRD §2.6 priority 5: "**Business referential and structural rules.**...progress out of range (`ERR_PROGRESS_OUT_OF_RANGE`)".

        Claim (second instance): when the state precondition passes (objective is ACTIVE),
        the business_constraint check surfaces and ERR_PROGRESS_OUT_OF_RANGE wins.
        This complements the first test, which proves state pre-empts business.
        # difficulty: priority_pair_validation_conflict/state_vs_business_constraint_progress_update
        """
        s = setup_active_individual_objective(num_krs=1, kr_kind="NUMERIC")
        kr = s["krs"][0]
        # State now passes (objective ACTIVE); only business fails
        payload = create_value_change_payload(200)  # out of [0,100]
        resp = api.post_progress(kr["id"], payload, s["org"]["employee_headers"])
        validate_error(resp, ApiErrorId.ERR_PROGRESS_OUT_OF_RANGE.value)


# ---------------------------------------------------------------------------
# Supplemental: compensating_invariant/co_owner_add_remove_weight_sum_invariant
# ---------------------------------------------------------------------------

class TestCoOwnerWeightSumSecondInstance:
    """# difficulty: compensating_invariant/co_owner_add_remove_weight_sum_invariant"""

    def test_two_add_two_remove_co_owners_returns_to_zero(self, api):
        """PRD §3.6: "Removing a co-owner advances the row to `REMOVED`. The list view of co-owners returns the active set."

        Claim (second instance): start at 0; add two co-owners (sum 0.0 → 0.6); remove both
        (sum 0.6 → 0.0). Conserved quantity exactly equal across baseline and post-compensating.
        # difficulty: compensating_invariant/co_owner_add_remove_weight_sum_invariant
        """
        s = setup_active_individual_objective()
        org = s["org"]
        co1 = create_user(org["department"]["id"], role_type="EMPLOYEE",
                          manager_id=org["manager_user"]["id"])
        co2 = create_user(org["department"]["id"], role_type="EMPLOYEE",
                          manager_id=org["manager_user"]["id"])
        owner_headers = org["employee_headers"]

        baseline = validate_success(api.list_co_owners(s["objective"]["id"], owner_headers))
        baseline_rows = baseline if isinstance(baseline, list) else []
        baseline_sum = sum(float(r["contribution_weight"]) for r in baseline_rows if r["status"] == "ACTIVE")
        assert baseline_sum == pytest.approx(0.0, abs=1e-9)

        # Forward: add two
        api.add_co_owner(s["objective"]["id"], create_co_owner_payload(co1["id"], 0.3), owner_headers)
        api.add_co_owner(s["objective"]["id"], create_co_owner_payload(co2["id"], 0.3), owner_headers)
        mid = validate_success(api.list_co_owners(s["objective"]["id"], owner_headers))
        mid_rows = mid if isinstance(mid, list) else []
        mid_active = [r for r in mid_rows if r["status"] == "ACTIVE"]
        mid_sum = sum(float(r["contribution_weight"]) for r in mid_active)
        assert len(mid_active) == 2
        assert mid_sum == pytest.approx(0.6, abs=1e-6)

        # Compensating: remove both
        api.remove_co_owner(s["objective"]["id"], co1["id"], owner_headers)
        api.remove_co_owner(s["objective"]["id"], co2["id"], owner_headers)
        end = validate_success(api.list_co_owners(s["objective"]["id"], owner_headers))
        end_rows = end if isinstance(end, list) else []
        end_active = [r for r in end_rows if r["status"] == "ACTIVE"]
        end_sum = sum(float(r["contribution_weight"]) for r in end_active)
        assert len(end_active) == 0
        assert end_sum == pytest.approx(baseline_sum, abs=1e-9)


# ---------------------------------------------------------------------------
# Supplemental: compensating_invariant/access_grant_grant_revoke_count_invariant
# ---------------------------------------------------------------------------

class TestAccessGrantCountSecondInstance:
    """# difficulty: compensating_invariant/access_grant_grant_revoke_count_invariant"""

    def test_two_grants_two_revokes_active_count_returns_to_zero(self, api):
        """PRD §3.8: "The list view returns active grants only".

        Claim (second instance): baseline 0; grant two readers (count 0 → 2); revoke both
        (count 2 → 0). Active count returns to 0.
        # difficulty: compensating_invariant/access_grant_grant_revoke_count_invariant
        """
        s = setup_confidential_objective()
        org = s["org"]
        owner_headers = org["employee_headers"]
        reader1 = create_user(org["department"]["id"], role_type="EMPLOYEE",
                              manager_id=org["manager_user"]["id"])
        reader2 = create_user(org["department"]["id"], role_type="EMPLOYEE",
                              manager_id=org["manager_user"]["id"])

        baseline = validate_success(api.list_access_grants(s["objective"]["id"], owner_headers))
        baseline_rows = baseline if isinstance(baseline, list) else []
        assert len(baseline_rows) == 0

        # Forward
        api.create_access_grant(s["objective"]["id"], create_access_grant_payload(reader1["id"]), owner_headers)
        api.create_access_grant(s["objective"]["id"], create_access_grant_payload(reader2["id"]), owner_headers)
        mid = validate_success(api.list_access_grants(s["objective"]["id"], owner_headers))
        mid_rows = mid if isinstance(mid, list) else []
        assert len(mid_rows) == 2

        # Compensating
        api.revoke_access_grant(s["objective"]["id"], reader1["id"], owner_headers)
        api.revoke_access_grant(s["objective"]["id"], reader2["id"], owner_headers)
        end = validate_success(api.list_access_grants(s["objective"]["id"], owner_headers))
        end_rows = end if isinstance(end, list) else []
        assert len(end_rows) == 0
