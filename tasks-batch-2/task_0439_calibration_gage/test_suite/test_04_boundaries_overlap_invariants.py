"""Numeric/cardinality boundaries, interval (window) semantics, and conserved
quantities.

Difficulty queue: boundary_precision_check, resource_temporal_overlap,
compensating_invariant.
"""
import pytest

from test_helpers import validate_success, validate_error
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    TECH, QE, MET,
    create_standard,
    create_instrument,
    open_event,
    add_point,
    finalize_passing_event,
    finalize_failing_event,
    create_collecting_study,
    get_only_impact,
    current_version,
    setup_quarantined_instrument,
)
from test_helpers.test_users import (
    make_quality_engineer_headers,
    make_technician_headers,
)


# ===========================================================================
# Difficulty / boundary_precision_check / point_pass_closed_upper_boundary
# ===========================================================================
@pytest.mark.parametrize("as_found_value,expected_pass", [
    (25.04, True),    # below the upper bound
    (25.05, True),    # exactly at the closed upper boundary
    (25.06, False),   # just above the upper bound
])
def test_measurement_point_closed_upper_boundary(api, as_found_value, expected_pass):
    """PRD §3.3: "`as_found_pass` is true exactly when the as-found reading is at
    least the nominal minus the lower tolerance and at most the nominal plus the
    upper tolerance".

    Closed interval: 25.05 (= nominal 25.0 + tol_plus 0.05) PASSES; 25.06 fails.

    Design: Difficulty/boundary_precision_check/point_pass_closed_upper_boundary
    """
    std = create_standard(name="GB-B1", nist_test_number="NIST-10")
    inst = create_instrument(asset_tag="INST-B1", criticality="MINOR")
    ev = open_event(inst["id"], std["id"], inst["version"], scheduled_epoch=5)
    data = validate_success(api.add_measurement_point(
        ev["id"], {"point_label": "PB", "nominal": 25.0, "tol_plus": 0.05,
                   "tol_minus": 0.05, "as_found_value": as_found_value}, TECH), 201)
    assert data["as_found_pass"] is expected_pass, \
        f"value {as_found_value}: expected as_found_pass {expected_pass}, got {data['as_found_pass']}"


@pytest.mark.parametrize("as_found_value,expected_pass", [
    (24.96, True),    # above the lower bound
    (24.95, True),    # exactly at the closed lower boundary (nominal - tol_minus)
    (24.94, False),   # just below the lower bound
])
def test_measurement_point_closed_lower_boundary(api, as_found_value, expected_pass):
    """PRD §3.3: "`as_found_pass` is true exactly when the as-found reading is at
    least the nominal minus the lower tolerance and at most the nominal plus the
    upper tolerance".

    Closed interval: 24.95 (= nominal 25.0 - tol_minus 0.05) PASSES; 24.94 fails.

    Design: Difficulty/boundary_precision_check/point_pass_closed_upper_boundary
    """
    std = create_standard(name="GB-B1L", nist_test_number="NIST-10L")
    inst = create_instrument(asset_tag="INST-B1L", criticality="MINOR")
    ev = open_event(inst["id"], std["id"], inst["version"], scheduled_epoch=5)
    data = validate_success(api.add_measurement_point(
        ev["id"], {"point_label": "PBL", "nominal": 25.0, "tol_plus": 0.05,
                   "tol_minus": 0.05, "as_found_value": as_found_value}, TECH), 201)
    assert data["as_found_pass"] is expected_pass, \
        f"value {as_found_value}: expected as_found_pass {expected_pass}, got {data['as_found_pass']}"


# ===========================================================================
# Difficulty / boundary_precision_check / trial_matrix_empty_cell_count_boundary
# ===========================================================================
def test_analyze_incomplete_trial_matrix_rejected(api):
    """PRD §3.7: "Analyzing it moves `COLLECTING` to `ANALYZED` and requires the
    trial matrix to be exactly complete — precisely the product of `operator_count`,
    `part_count`, and `trial_count` trial rows, one per cell, with no gaps and no
    duplicates (otherwise `ERR_INCOMPLETE_TRIAL_MATRIX`)".

    A 2x2x2 study (8 cells) with only 7 populated fails analyze.

    Design: Difficulty/boundary_precision_check/trial_matrix_empty_cell_count_boundary
    """
    inst = create_instrument(asset_tag="INST-B2", nominal_value=5.0,
                             tolerance_plus=1.0, tolerance_minus=1.0, criticality="MINOR")
    study = create_collecting_study(inst["id"], inst["version"])
    seven_cells = [
        (1, 1, 1, 2.0), (1, 1, 2, 2.1), (1, 2, 1, 3.0), (1, 2, 2, 3.0),
        (2, 1, 1, 2.2), (2, 1, 2, 2.0), (2, 2, 1, 3.1),
    ]
    for o, p, t, val in seven_cells:
        validate_success(api.add_trial(
            study["id"],
            {"operator_index": o, "part_index": p, "trial_index": t, "measured_value": val},
            TECH), 201)
    validate_error(api.analyze_study(study["id"], QE),
                   ApiErrorId.ERR_INCOMPLETE_TRIAL_MATRIX.value)


def test_analyze_exactly_complete_trial_matrix_succeeds(api):
    """PRD §3.7: "Analyzing it moves `COLLECTING` to `ANALYZED` and requires the
    trial matrix to be exactly complete — precisely the product of `operator_count`,
    `part_count`, and `trial_count` trial rows, one per cell, with no gaps and no
    duplicates (otherwise `ERR_INCOMPLETE_TRIAL_MATRIX`)".

    The cardinality boundary from below: exactly 8/8 cells (2x2x2) analyzes
    successfully to ANALYZED.

    Design: Difficulty/boundary_precision_check/trial_matrix_empty_cell_count_boundary
    """
    inst = create_instrument(asset_tag="INST-B2C", nominal_value=5.0,
                             tolerance_plus=1.0, tolerance_minus=1.0, criticality="MINOR")
    study = create_collecting_study(inst["id"], inst["version"])
    eight_cells = [
        (1, 1, 1, 2.0), (1, 1, 2, 2.1), (1, 2, 1, 3.0), (1, 2, 2, 3.0),
        (2, 1, 1, 2.2), (2, 1, 2, 2.0), (2, 2, 1, 3.1), (2, 2, 2, 3.2),
    ]
    for o, p, t, val in eight_cells:
        validate_success(api.add_trial(
            study["id"],
            {"operator_index": o, "part_index": p, "trial_index": t, "measured_value": val},
            TECH), 201)
    data = validate_success(api.analyze_study(study["id"], QE))
    assert data["status"] == "ANALYZED", \
        f"expected ANALYZED with a complete 8/8 matrix, got {data['status']}"


# ===========================================================================
# Difficulty / resource_temporal_overlap / suspect_window_closed_inclusion
# ===========================================================================
def test_affected_product_at_window_end_is_in_window(api):
    """PRD §3.5: "computes `in_suspect_window`, which is true exactly when
    `measured_epoch` is at least `suspect_window_start_epoch` and at most
    `suspect_window_end_epoch` (a closed interval)."

    Window [10,30]; a product measured exactly at end-epoch 30 is in window.

    Design: Difficulty/resource_temporal_overlap/suspect_window_closed_inclusion
    """
    std = create_standard(name="GB-TO1", nist_test_number="NIST-13")
    inst = create_instrument(asset_tag="INST-TO1", criticality="CRITICAL")
    finalize_passing_event(inst["id"], std["id"], inst["version"],
                           scheduled_epoch=10, as_found_value=25.00)
    finalize_failing_event(inst["id"], std["id"], current_version(inst["id"]),
                           scheduled_epoch=30, as_found_value=25.40)
    impact = get_only_impact(inst["id"])
    data = validate_success(api.add_affected_product(
        impact["id"], {"product_serial": "EDGE-30", "measured_epoch": 30}, QE), 201)
    assert data["in_suspect_window"] is True, \
        "product measured at the closed end-epoch 30 must be in the suspect window"


def test_affected_product_just_past_window_end_is_out(api):
    """PRD §3.5: "computes `in_suspect_window`, which is true exactly when
    `measured_epoch` is at least `suspect_window_start_epoch` and at most
    `suspect_window_end_epoch` (a closed interval)."

    Window [10,30]; a product measured at epoch 31 (one past the closed end) is NOT
    in window — the complementary side of the closed-interval boundary.

    Design: Difficulty/resource_temporal_overlap/suspect_window_closed_inclusion
    """
    std = create_standard(name="GB-TO1b", nist_test_number="NIST-13b")
    inst = create_instrument(asset_tag="INST-TO1b", criticality="CRITICAL")
    finalize_passing_event(inst["id"], std["id"], inst["version"],
                           scheduled_epoch=10, as_found_value=25.00)
    finalize_failing_event(inst["id"], std["id"], current_version(inst["id"]),
                           scheduled_epoch=30, as_found_value=25.40)
    impact = get_only_impact(inst["id"])
    data = validate_success(api.add_affected_product(
        impact["id"], {"product_serial": "PAST-31", "measured_epoch": 31}, QE), 201)
    assert data["in_suspect_window"] is False, \
        "product measured at epoch 31 (past the closed end 30) must be out of window"


# ===========================================================================
# Difficulty / resource_temporal_overlap / overdue_sweep_strict_less_than_window
# ===========================================================================
def test_overdue_fires_only_strictly_past_due_epoch(api):
    """PRD §3.4: "an instrument is overdue exactly when `next_due_epoch` is not null
    and is strictly less than the clock's `current_epoch`."
    PRD §3.8: "The sweep visits every `ACTIVE` instrument whose `calibration_status`
    is `IN_TOLERANCE` and whose `next_due_epoch` is non-null and strictly less than
    the new `current_epoch`, and moves each such instrument's `calibration_status`
    to `OVERDUE`".

    Calibrated at epoch 5, interval 10 → next_due 15. At clock 15 the instrument is
    still IN_TOLERANCE; at clock 16 it becomes OVERDUE.

    Design: Difficulty/resource_temporal_overlap/overdue_sweep_strict_less_than_window
    """
    std = create_standard(name="GB-TO2", nist_test_number="NIST-14")
    validate_success(api.advance_clock({"by_epochs": 5}, QE))
    inst = create_instrument(asset_tag="INST-TO2", criticality="MAJOR",
                             calibration_interval_epochs=10)
    finalize_passing_event(inst["id"], std["id"], inst["version"],
                           scheduled_epoch=5, as_found_value=25.00)
    # Clock currently at 5; advance to exactly 15 (next_due).
    validate_success(api.advance_clock({"by_epochs": 10}, QE))
    at_due = validate_success(api.get_instrument(inst["id"], QE))
    assert at_due["next_due_epoch"] == 15, \
        f"expected next_due_epoch 15, got {at_due['next_due_epoch']}"
    assert at_due["calibration_status"] == "IN_TOLERANCE", \
        f"at clock 15 (== next_due) expected IN_TOLERANCE, got {at_due['calibration_status']}"
    # Advance one more epoch to 16 (strictly past due).
    validate_success(api.advance_clock({"by_epochs": 1}, QE))
    after = validate_success(api.get_instrument(inst["id"], QE))
    assert after["calibration_status"] == "OVERDUE", \
        f"at clock 16 (> next_due) expected OVERDUE, got {after['calibration_status']}"


def test_sweep_leaves_not_yet_due_instrument_in_tolerance(api):
    """PRD §3.8: "The sweep visits every `ACTIVE` instrument whose
    `calibration_status` is `IN_TOLERANCE` and whose `next_due_epoch` is non-null and
    strictly less than the new `current_epoch`, and moves each such instrument's
    `calibration_status` to `OVERDUE`".

    Calibrated at epoch 5, interval 100 → next_due 105. After advancing the clock to
    10 (well before due), the sweep leaves the instrument IN_TOLERANCE.

    Design: Difficulty/resource_temporal_overlap/overdue_sweep_strict_less_than_window
    """
    std = create_standard(name="GB-TO3", nist_test_number="NIST-14b")
    validate_success(api.advance_clock({"by_epochs": 5}, QE))
    inst = create_instrument(asset_tag="INST-TO3", criticality="MAJOR",
                             calibration_interval_epochs=100)
    finalize_passing_event(inst["id"], std["id"], inst["version"],
                           scheduled_epoch=5, as_found_value=25.00)
    validate_success(api.advance_clock({"by_epochs": 5}, QE))  # clock now 10
    data = validate_success(api.get_instrument(inst["id"], QE))
    assert data["next_due_epoch"] == 105, \
        f"expected next_due_epoch 105, got {data['next_due_epoch']}"
    assert data["calibration_status"] == "IN_TOLERANCE", \
        f"a not-yet-due instrument must stay IN_TOLERANCE, got {data['calibration_status']}"


# ===========================================================================
# Difficulty / compensating_invariant / open_oot_count_conserved_on_cancel
# ===========================================================================
def test_open_oot_count_restored_after_impact_cancel(api):
    """PRD §3.5: "Finally, an `OPEN` impact may be cancelled to `CANCELLED`
    (terminal), but only from `OPEN` (otherwise `ERR_INVALID_STATE`) and only when
    no affected product has already reached `RECALLED` (otherwise
    `ERR_RECALL_ALREADY_ISSUED`); cancelling also decrements the instrument's
    `open_oot_count` by one and increments the impact's version."

    FAIL finalize raises open_oot_count to 1; cancelling the impact restores it to 0.

    Design: Difficulty/compensating_invariant/open_oot_count_conserved_on_cancel
    """
    inst, std, failed, impact = setup_quarantined_instrument(
        asset_tag="INST-CI1", criticality="CRITICAL")
    cancelled = validate_success(api.cancel_impact(impact["id"], QE))
    assert cancelled["status"] == "CANCELLED", \
        f"expected CANCELLED, got {cancelled['status']}"
    inst_after = validate_success(api.get_instrument(inst["id"], QE))
    assert inst_after["open_oot_count"] == 0, \
        f"expected open_oot_count restored to 0, got {inst_after['open_oot_count']}"


def test_open_oot_count_is_one_while_impact_open(api):
    """PRD §3.4: "an `OutOfToleranceImpact` is auto-created in `OPEN` ...
    `open_oot_count` is increased by one".

    The forward (+1) leg of the conserved quantity: while the auto-created impact is
    still OPEN, the instrument's open_oot_count reads 1.

    Design: Difficulty/compensating_invariant/open_oot_count_conserved_on_cancel
    """
    inst, std, failed, impact = setup_quarantined_instrument(
        asset_tag="INST-CI1b", criticality="CRITICAL")
    inst_after = validate_success(api.get_instrument(inst["id"], QE))
    assert inst_after["open_oot_count"] == 1, \
        f"expected open_oot_count 1 while impact OPEN, got {inst_after['open_oot_count']}"
    assert impact["status"] == "OPEN", f"expected impact OPEN, got {impact['status']}"


# ===========================================================================
# Difficulty / compensating_invariant / affected_product_count_conserved_on_clear_disposition
# ===========================================================================
def test_use_as_is_disposition_clears_products_without_recall(api):
    """PRD §3.5: "On attach, the server sets `affected_product_count` up by one".
    PRD §3.5: "A `USE_AS_IS`, `REWORK`, or `SCRAP` disposition instead moves every
    `FLAGGED` affected product to `CLEARED`."

    Two attached products keep affected_product_count at 2, recalled_product_count
    stays 0 (no recall), and both products become CLEARED.

    Design: Difficulty/compensating_invariant/affected_product_count_conserved_on_clear_disposition
    """
    qe1 = make_quality_engineer_headers("qe-1")
    qe2 = make_quality_engineer_headers("qe-2")
    tech = make_technician_headers("tech-9")
    std = create_standard(name="GB-CI2", nist_test_number="NIST-16")
    inst = create_instrument(asset_tag="INST-CI2", criticality="CRITICAL", headers=qe1)
    finalize_failing_event(inst["id"], std["id"], inst["version"],
                           scheduled_epoch=5, as_found_value=25.40, tech_headers=tech)
    impact = get_only_impact(inst["id"], headers=qe1)
    for serial, epoch in [("U-A", 2), ("U-B", 4)]:
        validate_success(api.add_affected_product(
            impact["id"], {"product_serial": serial, "measured_epoch": epoch}, qe1), 201)
    validate_success(api.investigate_impact(impact["id"], qe2))
    data = validate_success(api.disposition_impact(
        impact["id"], {"disposition": "USE_AS_IS"}, qe2))
    assert data["affected_product_count"] == 2, \
        f"expected affected_product_count 2 (unchanged), got {data['affected_product_count']}"
    assert data["recalled_product_count"] == 0, \
        f"expected recalled_product_count 0 on USE_AS_IS, got {data['recalled_product_count']}"
    products = validate_success(api.list_affected_products(impact["id"], qe1))
    assert all(p["status"] == "CLEARED" for p in products), \
        f"expected all products CLEARED, got {[p['status'] for p in products]}"


def test_rework_disposition_also_clears_products_without_recall(api):
    """PRD §3.5: "A `USE_AS_IS`, `REWORK`, or `SCRAP` disposition instead moves every
    `FLAGGED` affected product to `CLEARED`."
    PRD §3.5: "On attach, the server sets `affected_product_count` up by one".

    A REWORK disposition (another non-recall branch) keeps affected_product_count at
    2 and recalled_product_count at 0, and clears both products — the same conserved
    quantity holds across the non-recall branches.

    Design: Difficulty/compensating_invariant/affected_product_count_conserved_on_clear_disposition
    """
    qe1 = make_quality_engineer_headers("qe-1")
    qe2 = make_quality_engineer_headers("qe-2")
    tech = make_technician_headers("tech-9")
    std = create_standard(name="GB-CI2b", nist_test_number="NIST-16b")
    inst = create_instrument(asset_tag="INST-CI2b", criticality="CRITICAL", headers=qe1)
    finalize_failing_event(inst["id"], std["id"], inst["version"],
                           scheduled_epoch=5, as_found_value=25.40, tech_headers=tech)
    impact = get_only_impact(inst["id"], headers=qe1)
    for serial, epoch in [("R-A", 2), ("R-B", 4)]:
        validate_success(api.add_affected_product(
            impact["id"], {"product_serial": serial, "measured_epoch": epoch}, qe1), 201)
    validate_success(api.investigate_impact(impact["id"], qe2))
    data = validate_success(api.disposition_impact(
        impact["id"], {"disposition": "REWORK"}, qe2))
    assert data["affected_product_count"] == 2, \
        f"expected affected_product_count 2 (unchanged), got {data['affected_product_count']}"
    assert data["recalled_product_count"] == 0, \
        f"expected recalled_product_count 0 on REWORK, got {data['recalled_product_count']}"
    products = validate_success(api.list_affected_products(impact["id"], qe1))
    assert all(p["status"] == "CLEARED" for p in products), \
        f"expected all products CLEARED, got {[p['status'] for p in products]}"
