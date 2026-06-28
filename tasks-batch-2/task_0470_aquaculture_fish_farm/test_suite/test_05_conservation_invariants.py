"""Conservation invariants: grading splits conserve total fish count; sales
reserve/release cycles conserve lot weight (total == available + reserved +
shipped at every step).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    setup_planned_grading_two_tanks,
    create_product_lot,
    create_sales_order,
    add_line,
    get_lot,
    assert_lot_weight_conservation,
)

FM = TEST_USERS["farm_manager_headers"]
FT = TEST_USERS["farm_technician_headers"]
SA = TEST_USERS["sales_agent_headers"]


# ===========================================================================
# Rule 9 — compensating_invariant :: grading_split_conserves_fish_count
# ===========================================================================
def test_grading_commit_consumes_source_to_zero_and_marks_harvested():
    """PRD §3.5: "The source cohort is consumed: its fish_count is set to 0 and
    its lifecycle_status is set to HARVESTED."
    PRD §3.5: "On a successful commit, the system creates one child cohort per
    planned_splits entry - each child taking its fish_count from the split, its
    current_tank_id from the split's target_tank_id, and its parent_cohort_id set
    to the source."

    Design: Difficulty/compensating_invariant/grading_split_conserves_fish_count
    """
    cohort, _ta, _tb, grading = setup_planned_grading_two_tanks(
        source_fish_count=1000, split_a=600, split_b=400)
    get_success_data(
        api_client.commit_grading_event(
            grading["id"], {"expected_source_cohort_version": cohort["version"]}, FT
        )
    )
    source_after = validate_success(api_client.get_cohort(cohort["id"], FT))
    assert source_after["fish_count"] == 0, \
        f"source fish_count must be 0 after commit, got {source_after['fish_count']}"
    assert source_after["lifecycle_status"] == "HARVESTED", \
        f"source must be HARVESTED, got {source_after['lifecycle_status']}"


def test_grading_split_conserves_total_fish_count():
    """PRD §2.10: "The first governs fish counts during grading: when a cohort is
    split, the sum of the child cohorts' fish counts always equals the source
    cohort's fish count immediately before the split - no fish are created or
    destroyed."
    PRD §3.5: "The fish-count conservation invariant holds: the sum of the
    children's fish counts equals the source's fish count immediately before the
    split."

    Design: Difficulty/compensating_invariant/grading_split_conserves_fish_count
    """
    cohort, _ta, _tb, grading = setup_planned_grading_two_tanks(
        source_fish_count=1000, split_a=600, split_b=400)
    committed = validate_success(
        api_client.commit_grading_event(
            grading["id"], {"expected_source_cohort_version": cohort["version"]}, FT
        )
    )
    child_ids = committed["child_cohort_ids"]
    assert len(child_ids) == 2, f"expected 2 child cohorts, got {len(child_ids)}"
    counts = sorted(
        validate_success(api_client.get_cohort(cid, FT))["fish_count"]
        for cid in child_ids
    )
    assert counts == [400, 600], f"expected child counts [400, 600], got {counts}"
    assert sum(counts) == 1000, \
        f"children must conserve pre-split 1000 fish, got {sum(counts)}"


# ===========================================================================
# Rule 9 — compensating_invariant :: sales_reserve_release_conserves_lot_weight
# ===========================================================================
def _confirm_partial_reservation(lot_total=50.0, reserve=30.0):
    lot, _species, _tank = create_product_lot(lot_total, price_per_kg=10.0)
    order = create_sales_order(discount_tier="NONE")
    add_line(order["id"], lot["id"], reserve)
    lot_now = get_lot(lot["id"])
    get_success_data(
        api_client.confirm_sales_order(
            order["id"], {"expected_lot_version": lot_now["version"]}, SA
        )
    )
    return lot["id"], order["id"]


def test_confirm_preserves_total_weight_conservation():
    """PRD §2.10: "The second governs product weight: for every product lot, the
    lot's total weight always equals the sum of its available, reserved, and
    shipped weight."
    PRD §3.10: "Throughout, the lot's available_weight_kg equals its
    total_weight_kg minus its reserved_weight_kg minus its shipped_weight_kg, and
    the conservation invariant holds that the total equals available plus reserved
    plus shipped."

    Design: Difficulty/compensating_invariant/sales_reserve_release_conserves_lot_weight
    """
    lot_id, _order_id = _confirm_partial_reservation(lot_total=50.0, reserve=30.0)
    lot = get_lot(lot_id)
    assert lot["total_weight_kg"] == pytest.approx(50.00, abs=0.01)
    assert lot["reserved_weight_kg"] == pytest.approx(30.00, abs=0.01)
    assert lot["available_weight_kg"] == pytest.approx(20.00, abs=0.01)
    assert_lot_weight_conservation(lot)


def test_reserve_then_cancel_restores_weight_conservation_end_to_end():
    """PRD §3.10: "the second hop, caused by the first, releases each line's
    reserved weight by decreasing the referenced lot's reserved_weight_kg by the
    line's weight_kg and recomputing the lot's available_weight_kg upward."
    PRD §3.10: "The weight-conservation invariant is restored, and the lots'
    versions and the order's version increment."

    Design: Difficulty/compensating_invariant/sales_reserve_release_conserves_lot_weight
    """
    lot_id, order_id = _confirm_partial_reservation(lot_total=50.0, reserve=30.0)
    get_success_data(api_client.cancel_sales_order(order_id, SA))
    lot = get_lot(lot_id)
    assert lot["total_weight_kg"] == pytest.approx(50.00, abs=0.01)
    assert lot["reserved_weight_kg"] == pytest.approx(0.00, abs=0.01)
    assert lot["available_weight_kg"] == pytest.approx(50.00, abs=0.01)
    assert_lot_weight_conservation(lot)
