"""Placement state machine, cross-entity cascades, and conserved-quantity invariants.

Queue A — difficulty rules: non_linear_state_machine, transitive_cascade,
compensating_invariant.
"""
from test_helpers import (
    get_success_data, validate_success,
    setup_workers, open_case_with_child, create_licensed_home, place_child,
    setup_placed_child, set_clock,
    schedule_and_hold_hearing, advance_to_permanency_planning,
)


# =========================================================================
# Rule 3 — non_linear_state_machine / placement_disruption_cycle_then_replace
# =========================================================================
def test_disrupt_then_replace_returns_child_to_placed(api):
    """PRD §3.7: "A `REMOVED` child is not adrift — the caseworker re-places them into a new home by the ordinary placement-create operation, which returns the child to `PLACED`; because the case is already `IN_PLACEMENT`, this re-placement does not move `removal_date`."
    PRD §3.7: "the placement moves from `ACTIVE` to `DISRUPTED`, its `end_at` is set to the current clock, the child moves to `REMOVED` with `current_placement_id` cleared".

    Design: Difficulty/non_linear_state_machine/placement_disruption_cycle_then_replace
    """
    w = setup_workers()
    case, child, h1, plc1 = setup_placed_child(w)
    h2 = create_licensed_home(w, bed_capacity=1, max_age_years=18)

    disrupted = validate_success(api.disrupt_placement(plc1["id"], w.caseworker))
    assert disrupted["status"] == "DISRUPTED"

    plc2 = validate_success(api.create_placement(
        {"child_id": child["id"], "foster_home_id": h2["id"],
         "expected_foster_home_version": h2["version"]}, w.caseworker), expected_status=201)
    assert plc2["status"] == "ACTIVE"

    final_child = validate_success(api.get_child(child["id"], w.caseworker))
    assert final_child["status"] == "PLACED"
    assert final_child["current_placement_id"] == plc2["id"]


def test_disrupt_sets_child_removed_and_clears_placement(api):
    """PRD §3.7: "the child moves to `REMOVED` with `current_placement_id` cleared, the home's `active_placement_count` is decremented by one, and the `version` of placement, child, and home are each bumped."

    Design: Difficulty/non_linear_state_machine/placement_disruption_cycle_then_replace
    """
    w = setup_workers()
    case, child, home, placement = setup_placed_child(w)

    disrupted = validate_success(api.disrupt_placement(placement["id"], w.caseworker))
    assert disrupted["status"] == "DISRUPTED"

    child_after = validate_success(api.get_child(child["id"], w.caseworker))
    assert child_after["status"] == "REMOVED"
    assert child_after["current_placement_id"] is None


# =========================================================================
# Rule 3 — non_linear_state_machine / case_permanency_branching_fork_adoption
# =========================================================================
def test_case_closes_adopted_branch(api):
    """PRD §3.9: "Adoption close** (`CLOSED_ADOPTED`): permitted when `permanency_goal` is `ADOPTION` and a `TPR` hearing on the case has been `HELD` with ruling `TERMINATE_RIGHTS`."
    PRD §3.9: "the case moves to its terminal `CLOSED_*` state and its `version` is bumped, and the child is driven to `PERMANENT".

    Design: Difficulty/non_linear_state_machine/case_permanency_branching_fork_adoption
    """
    w = setup_workers()
    case, child, home, placement = setup_placed_child(w)
    # Flip goal to ADOPTION via a HELD PERMANENCY hearing, advance to planning.
    advance_to_permanency_planning(w, case["id"], ruling="CHANGE_GOAL_ADOPTION")
    # HELD TPR with TERMINATE_RIGHTS, then end the placement adopted.
    schedule_and_hold_hearing(w, case["id"], "TPR", "TERMINATE_RIGHTS",
                              scheduled_at="2026-01-01T05:00:00Z")
    get_success_data(api.end_adopted(placement["id"], w.caseworker))

    closed = validate_success(api.close_case(case["id"], w.caseworker))
    assert closed["status"] == "CLOSED_ADOPTED"
    assert closed["permanency_goal"] == "ADOPTION"

    child_after = validate_success(api.get_child(child["id"], w.caseworker))
    assert child_after["status"] == "PERMANENT"


def test_change_goal_adoption_ruling_sets_case_goal(api):
    """PRD §3.9: "A ruling of `CHANGE_GOAL_ADOPTION` has a cross-entity effect: it sets the case's `permanency_goal` to `ADOPTION`."

    Design: Difficulty/non_linear_state_machine/case_permanency_branching_fork_adoption
    """
    w = setup_workers()
    case, child, home, placement = setup_placed_child(w)
    schedule_and_hold_hearing(w, case["id"], "PERMANENCY", "CHANGE_GOAL_ADOPTION",
                              scheduled_at="2026-01-01T01:00:00Z")
    case_after = validate_success(api.get_case(case["id"], w.caseworker))
    assert case_after["permanency_goal"] == "ADOPTION"


# =========================================================================
# Rule 4 — transitive_cascade / suspend_home_cascade_depth3
# =========================================================================
def test_suspend_home_disrupts_placement_and_removes_child(api):
    """PRD §3.7: "When a `LICENSED` home is **suspended**, every one of its `ACTIVE` placements is transitioned to `DISRUPTED`, each affected child is set to `REMOVED` with their `current_placement_id` cleared, the home's `active_placement_count` is zeroed, and the home's `version` is bumped."

    Design: Difficulty/transitive_cascade/suspend_home_cascade_depth3
    """
    w = setup_workers()
    case, child, home, placement = setup_placed_child(w, bed_capacity=2)

    suspended = validate_success(api.suspend_home(home["id"], w.licensing))
    assert suspended["license_status"] == "SUSPENDED"
    assert suspended["active_placement_count"] == 0

    plc_after = validate_success(api.get_placement(placement["id"], w.caseworker))
    assert plc_after["status"] == "DISRUPTED"
    child_after = validate_success(api.get_child(child["id"], w.caseworker))
    assert child_after["status"] == "REMOVED"
    assert child_after["current_placement_id"] is None


def test_suspend_home_zeroes_active_placement_count(api):
    """PRD §3.7: "the home's `active_placement_count` is zeroed".
    PRD §3.4: "A `LICENSED` home may be **suspended** by its licensing authority".

    Design: Difficulty/transitive_cascade/suspend_home_cascade_depth3
    """
    w = setup_workers()
    case, child, home, placement = setup_placed_child(w, bed_capacity=2)
    suspended = validate_success(api.suspend_home(home["id"], w.licensing))
    assert suspended["active_placement_count"] == 0
    assert suspended["license_status"] == "SUSPENDED"


# =========================================================================
# Rule 4 — transitive_cascade / open_case_cascade_depth2_first_placement
# =========================================================================
def test_first_placement_advances_case_and_anchors_removal_date(api):
    """PRD §3.5: "if this is the **first** placement for the child on this case — the moment of removal into care — the case transitions from `OPEN` to `IN_PLACEMENT`, the case's `removal_date` is set to the current clock (anchoring the federal permanency clock; it is set only if still null), and the case's `version` is bumped."

    Design: Difficulty/transitive_cascade/open_case_cascade_depth2_first_placement
    """
    w = setup_workers()
    set_clock("2026-03-10T00:00:00Z")
    case, child = open_case_with_child(w)
    home = create_licensed_home(w, bed_capacity=1, max_age_years=18)
    placement = place_child(w, child["id"], home["id"], home["version"])
    assert placement["status"] == "ACTIVE"

    child_after = validate_success(api.get_child(child["id"], w.caseworker))
    assert child_after["status"] == "PLACED"
    case_after = validate_success(api.get_case(case["id"], w.caseworker))
    assert case_after["status"] == "IN_PLACEMENT"
    assert case_after["removal_date"] == "2026-03-10T00:00:00.000Z"
    assert case_after["months_in_care"] == 0


def test_first_placement_sets_child_placed(api):
    """PRD §3.5: "The child transitions from `IN_HOME` to `PLACED`, the child's `current_placement_id` is set to the new placement's `id`, and the child's `version` is bumped."

    Design: Difficulty/transitive_cascade/open_case_cascade_depth2_first_placement
    """
    w = setup_workers()
    case, child, home, placement = setup_placed_child(w)
    child_after = validate_success(api.get_child(child["id"], w.caseworker))
    assert child_after["status"] == "PLACED"
    assert child_after["current_placement_id"] == placement["id"]


# =========================================================================
# Rule 9 — compensating_invariant / bed_count_conserved_after_place_then_disrupt
# =========================================================================
def test_bed_count_conserved_after_place_then_disrupt(api):
    """PRD §3.5: "the home's `active_placement_count` is incremented and the home's `version` is bumped".
    PRD §3.7: "the home's `active_placement_count` is decremented by one".
    place (0->1) then disrupt (1->0) leaves active_placement_count at its pre-place value.

    Design: Difficulty/compensating_invariant/bed_count_conserved_after_place_then_disrupt
    """
    w = setup_workers()
    case, child, home, placement = setup_placed_child(w, bed_capacity=2)
    home_after_place = validate_success(api.get_foster_home(home["id"], w.caseworker))
    assert home_after_place["active_placement_count"] == 1

    disrupted = validate_success(api.disrupt_placement(placement["id"], w.caseworker))
    assert disrupted["status"] == "DISRUPTED"

    home_after = validate_success(api.get_foster_home(home["id"], w.caseworker))
    assert home_after["active_placement_count"] == 0, "bed occupancy must return to 0"


def test_disrupt_marks_child_removed_invariant(api):
    """PRD §3.7: "the child moves to `REMOVED` with `current_placement_id` cleared".

    Design: Difficulty/compensating_invariant/bed_count_conserved_after_place_then_disrupt
    """
    w = setup_workers()
    case, child, home, placement = setup_placed_child(w, bed_capacity=2)
    disrupted = validate_success(api.disrupt_placement(placement["id"], w.caseworker))
    assert disrupted["status"] == "DISRUPTED"
    child_after = validate_success(api.get_child(child["id"], w.caseworker))
    assert child_after["status"] == "REMOVED"
