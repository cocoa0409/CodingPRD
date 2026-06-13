"""Effectiveness target-threshold boundaries and the empty-set guard.

Difficulty queue: boundary_precision_check.
"""
import pytest

from test_helpers import (
    validate_success,
    TEST_USERS,
    setup_draft_recall_with_lot, classify_recall,
    setup_recall_with_recovery, record_effectiveness_check,
)

COORD = TEST_USERS["recall_coordinator_headers"]


# ===========================================================================
# boundary_precision_check — effectiveness PASS at exact >= target boundary
# ===========================================================================
def test_effectiveness_check_pass_at_exact_class_i_target(api):
    """PRD §3.11: "the check derives a `target_pct` from the recall's
    classification — 90 for `CLASS_I`, 60 for `CLASS_II`, and 30 for
    `CLASS_III`". PRD §3.11: "Its `outcome` is `PASS` when `measured_pct` is
    greater than or equal to `target_pct`, using an inclusive boundary, and
    `FAIL` otherwise."

    Design: Difficulty/boundary_precision_check/effectiveness_pass_at_exact_target_boundary
    """
    # CLASS_I (SERIOUS + injury): 10 affected units, 9 returned -> 90.00%.
    _p, _l, recall, _units = setup_recall_with_recovery(
        num_units=10,
        num_returned=9,
        product_overrides={"regulator": "CPSC", "unit_list_price_cents": 20000},
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": True},
        sale_price_cents=20000,
    )
    eff = validate_success(api.get_recall_effectiveness(recall["id"], COORD), 200)
    assert eff["effectiveness_pct"] == pytest.approx(90.00, abs=0.001), eff["effectiveness_pct"]
    check = record_effectiveness_check(recall["id"])
    assert check["measured_pct"] == pytest.approx(90.00, abs=0.001), check["measured_pct"]
    assert check["target_pct"] == 90, check["target_pct"]
    assert check["outcome"] == "PASS", check["outcome"]


def test_effectiveness_check_fail_below_class_i_target(api):
    """PRD §3.11: "Its `outcome` is `PASS` when `measured_pct` is greater than or
    equal to `target_pct`, using an inclusive boundary, and `FAIL` otherwise."
    PRD §3.11: "the check derives a `target_pct` from the recall's
    classification — 90 for `CLASS_I`".

    Design: Difficulty/boundary_precision_check/effectiveness_pass_at_exact_target_boundary
    """
    # CLASS_I: 10 affected units, 8 returned -> 80.00% < 90 target -> FAIL.
    _p, _l, recall, _units = setup_recall_with_recovery(
        num_units=10,
        num_returned=8,
        product_overrides={"regulator": "CPSC", "unit_list_price_cents": 20000},
        recall_overrides={"hazard_severity": "SERIOUS", "injury_reported": True},
        sale_price_cents=20000,
    )
    check = record_effectiveness_check(recall["id"])
    assert check["measured_pct"] == pytest.approx(80.00, abs=0.001), check["measured_pct"]
    assert check["target_pct"] == 90, check["target_pct"]
    assert check["outcome"] == "FAIL", check["outcome"]


# ===========================================================================
# boundary_precision_check — zero affected units -> effectiveness 0 (no div error)
# ===========================================================================
def test_zero_affected_units_yields_zero_effectiveness(api):
    """PRD §3.11: "Step three computes the rate: when `affected_unit_count` is
    zero, `effectiveness_pct` is 0".

    Design: Difficulty/boundary_precision_check/zero_affected_units_effectiveness_is_zero
    """
    # CLASS_III recall on a lot with ZERO registered units.
    _p, _l, recall = setup_draft_recall_with_lot(
        recall_overrides={"hazard_severity": "MINOR"}
    )
    classify_recall(recall["id"], COORD)
    data = validate_success(api.get_recall_effectiveness(recall["id"], COORD), 200)
    assert data["affected_unit_count"] == 0, data["affected_unit_count"]
    assert data["effectiveness_pct"] == 0, data["effectiveness_pct"]


def test_zero_affected_units_recall_get_reports_zero(api):
    """PRD §3.11: "Step one counts the affected universe: `affected_unit_count`
    is the number of units whose `affected` flag is true." PRD §3.11: "when
    `affected_unit_count` is zero, `effectiveness_pct` is 0".

    Design: Difficulty/boundary_precision_check/zero_affected_units_effectiveness_is_zero
    """
    _p, _l, recall = setup_draft_recall_with_lot(
        recall_overrides={"hazard_severity": "MINOR"}
    )
    classify_recall(recall["id"], COORD)
    data = validate_success(api.get_recall(recall["id"], COORD), 200)
    assert data["affected_unit_count"] == 0, data["affected_unit_count"]
    assert data["effectiveness_pct"] == 0, data["effectiveness_pct"]
