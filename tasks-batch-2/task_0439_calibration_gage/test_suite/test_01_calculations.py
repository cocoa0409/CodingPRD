"""Calculation tests: dual-variant analytics, combinatorial formulas, and the
derived scheduling/deviation fields produced at finalize.

Difficulty queue: dual_variant_calc, combinatorial_formula.
Corner queue: calculations section + derived_field_reconciliation.
"""
from test_helpers import validate_success
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    TECH, QE, MET,
    create_standard,
    create_instrument,
    finalize_passing_event,
    finalize_failing_event,
    get_only_impact,
    current_version,
    setup_analyzed_study,
    GRR_UNACCEPTABLE_MATRIX,
    GRR_ZERO_VARIATION_MATRIX,
)


# ===========================================================================
# Difficulty / dual_variant_calc / drift_trend_lsq_vs_endpoint_diverge
# ===========================================================================
def _build_three_event_drift_instrument():
    """Three PASSED events at epochs 5, 7, 15 with as_found deviations 0.00, 0.02,
    0.03 on a single instrument (nominal 25.0, tol +/-0.05, interval 100)."""
    std = create_standard(name="GB-Master", nist_test_number="NIST-1")
    inst = create_instrument(asset_tag="INST-DRIFT", criticality="MAJOR")
    inst_id = inst["id"]
    finalize_passing_event(inst_id, std["id"], inst["version"],
                           scheduled_epoch=5, as_found_value=25.00)
    finalize_passing_event(inst_id, std["id"], current_version(inst_id),
                           scheduled_epoch=7, as_found_value=25.02)
    finalize_passing_event(inst_id, std["id"], current_version(inst_id),
                           scheduled_epoch=15, as_found_value=25.03)
    return inst_id


def test_drift_trend_lsq_slope_and_breach(api):
    """PRD §3.8: "the slope is the count of points times the sum of the products of
    paired coordinates, minus the product of the sum of horizontal coordinates and
    the sum of vertical coordinates, all divided by the count of points times the
    sum of squared horizontal coordinates minus the square of the sum of horizontal
    coordinates."
    PRD §3.8: "the `projected_breach_epoch` is the smallest integer epoch strictly
    greater than the last point's epoch at which the last point's deviation plus the
    slope times the elapsed epochs would exceed the instrument's tolerance
    half-band, where the half-band is the larger of `tolerance_plus` and
    `tolerance_minus`."

    Design: Difficulty/dual_variant_calc/drift_trend_lsq_vs_endpoint_diverge
    """
    inst_id = _build_three_event_drift_instrument()
    data = validate_success(api.drift_trend(inst_id, QE, params={"method": "LSQ"}))
    assert data["slope"] == 0.0025, f"expected LSQ slope 0.0025, got {data['slope']}"
    assert data["projected_breach_epoch"] == 24, \
        f"expected LSQ projected_breach_epoch 24, got {data['projected_breach_epoch']}"


def test_drift_trend_endpoint_slope_and_breach_diverge(api):
    """PRD §3.8: "The endpoint method (requested as ENDPOINT) instead takes the
    slope from only the first and last points: the last point's deviation minus the
    first point's deviation, divided by the last point's epoch minus the first
    point's epoch."
    PRD §3.8: "the `projected_breach_epoch` is the smallest integer epoch strictly
    greater than the last point's epoch at which the last point's deviation plus the
    slope times the elapsed epochs would exceed the instrument's tolerance
    half-band, where the half-band is the larger of `tolerance_plus` and
    `tolerance_minus`."

    Identical event data yields a different slope/breach than LSQ, proving the
    dual-variant divergence (ENDPOINT 0.003/22 vs LSQ 0.0025/24).

    Design: Difficulty/dual_variant_calc/drift_trend_lsq_vs_endpoint_diverge
    """
    inst_id = _build_three_event_drift_instrument()
    lsq = validate_success(api.drift_trend(inst_id, QE, params={"method": "LSQ"}))
    ep = validate_success(api.drift_trend(inst_id, QE, params={"method": "ENDPOINT"}))
    assert ep["slope"] == 0.003, f"expected ENDPOINT slope 0.003, got {ep['slope']}"
    assert ep["projected_breach_epoch"] == 22, \
        f"expected ENDPOINT projected_breach_epoch 22, got {ep['projected_breach_epoch']}"
    assert ep["slope"] != lsq["slope"], \
        "ENDPOINT and LSQ slopes must differ on identical event data"


# ===========================================================================
# Difficulty / dual_variant_calc / recall_exposure_conservative_vs_measured_diverge
# ===========================================================================
def _build_oot_with_five_products():
    """PASSED event at epoch 10 (prior good cal), FAILED event at epoch 30 (trigger)
    → impact window [10,30]; five products at measured_epoch 8,10,12,30,31."""
    std = create_standard(name="GB-2", nist_test_number="NIST-2")
    inst = create_instrument(asset_tag="INST-OOT", criticality="CRITICAL")
    inst_id = inst["id"]
    finalize_passing_event(inst_id, std["id"], inst["version"],
                           scheduled_epoch=10, as_found_value=25.00)
    finalize_failing_event(inst_id, std["id"], current_version(inst_id),
                           scheduled_epoch=30, as_found_value=25.20)
    impact = get_only_impact(inst_id)
    for serial, epoch in [("S08", 8), ("S10", 10), ("S12", 12), ("S30", 30), ("S31", 31)]:
        validate_success(api_client.add_affected_product(
            impact["id"], {"product_serial": serial, "measured_epoch": epoch}, QE), 201)
    return impact["id"]


def test_recall_exposure_conservative_count(api):
    """PRD §3.5: "The conservative basis (the default, and the one persisted on
    recall) counts all affected products whose `measured_epoch` lies in that closed
    window."

    Window [10,30]: products at 10, 12, 30 are in the closed window → 3.

    Design: Difficulty/dual_variant_calc/recall_exposure_conservative_vs_measured_diverge
    """
    impact_id = _build_oot_with_five_products()
    data = validate_success(api.get_exposure(impact_id, QE))
    assert data["exposure_count"] == 3, \
        f"expected conservative exposure_count 3, got {data['exposure_count']}"


def test_recall_exposure_measured_count_diverges(api):
    """PRD §3.5: "The measured basis counts only affected products whose
    `measured_epoch` is strictly greater than `prior_calibration_epoch` and at most
    the suspect-window end — a half-open window that excludes any product measured
    exactly at the prior good calibration, on the reasoning that such a product was
    conforming."
    PRD §3.5: "The measured count is therefore always at most the conservative
    count."

    Half-open (10,30]: products at 12, 30 → 2 (the 10 boundary product is excluded).

    Design: Difficulty/dual_variant_calc/recall_exposure_conservative_vs_measured_diverge
    """
    impact_id = _build_oot_with_five_products()
    cons = validate_success(api.get_exposure(impact_id, QE))
    meas = validate_success(api.get_exposure(impact_id, QE, params={"basis": "MEASURED"}))
    assert meas["exposure_count"] == 2, \
        f"expected measured exposure_count 2, got {meas['exposure_count']}"
    assert meas["exposure_count"] != cons["exposure_count"], \
        "measured and conservative counts must differ for this product set"


# ===========================================================================
# Difficulty / combinatorial_formula / tur_three_input_nonlinear_branch
# ===========================================================================
def test_tur_below_minimum_forces_fail_despite_in_tolerance(api):
    """PRD §3.4: "otherwise `tur` is the tolerance band width divided by twice the
    standard's `uncertainty`, reported to 2 decimal places round-half-up."
    PRD §3.4: "if `tur` is below 4.0 and the base outcome is not already `FAIL`, the
    result is forced to `FAIL`, because the measurement system cannot resolve the
    tolerance well enough to certify the instrument."

    Band 0.10, standard uncertainty 0.02 → tur 2.5 < 4.0; the single point reads on
    nominal (as_found passes), but the result is forced to FAIL.

    Design: Difficulty/combinatorial_formula/tur_three_input_nonlinear_branch
    """
    std = create_standard(name="GB-LowTUR", nist_test_number="NIST-3", uncertainty=0.02)
    inst = create_instrument(asset_tag="INST-TUR", criticality="MAJOR")
    ev = validate_success(api.create_event(
        inst["id"],
        {"standard_id": std["id"], "scheduled_epoch": 5,
         "expected_instrument_version": inst["version"]}, TECH), 201)
    validate_success(api.add_measurement_point(
        ev["id"],
        {"point_label": "P1", "nominal": 25.0, "tol_plus": 0.05, "tol_minus": 0.05,
         "as_found_value": 25.00}, TECH), 201)
    validate_success(api.start_event(ev["id"], TECH))
    data = validate_success(api.finalize_event(ev["id"], TECH))
    assert data["tur"] == 2.5, f"expected tur 2.5, got {data['tur']}"
    assert data["as_found_in_tolerance"] is True, "as_found should be in tolerance"
    assert data["result"] == "FAIL", f"expected result FAIL, got {data['result']}"
    assert data["status"] == "FAILED", f"expected status FAILED, got {data['status']}"


def test_tur_above_minimum_keeps_base_pass(api):
    """PRD §3.4: "otherwise `tur` is the tolerance band width divided by twice the
    standard's `uncertainty`, reported to 2 decimal places round-half-up."
    PRD §3.4: "otherwise the result is the base outcome. The computed `result` is
    one of `PASS`, `CONDITIONAL`, or `FAIL`."

    Band 0.10, standard uncertainty 0.001 → tur 50.0 >= 4.0; the same on-nominal
    in-tolerance reading is NOT downgraded — result stays PASS. This pins the
    three-input branch: only tur < 4.0 forces the FAIL.

    Design: Difficulty/combinatorial_formula/tur_three_input_nonlinear_branch
    """
    std = create_standard(name="GB-HiTUR", nist_test_number="NIST-3b", uncertainty=0.001)
    inst = create_instrument(asset_tag="INST-TUR2", criticality="MAJOR")
    ev = validate_success(api.create_event(
        inst["id"],
        {"standard_id": std["id"], "scheduled_epoch": 5,
         "expected_instrument_version": inst["version"]}, TECH), 201)
    validate_success(api.add_measurement_point(
        ev["id"],
        {"point_label": "P1", "nominal": 25.0, "tol_plus": 0.05, "tol_minus": 0.05,
         "as_found_value": 25.00}, TECH), 201)
    validate_success(api.start_event(ev["id"], TECH))
    data = validate_success(api.finalize_event(ev["id"], TECH))
    assert data["tur"] == 50.0, f"expected tur 50.0, got {data['tur']}"
    assert data["result"] == "PASS", f"expected result PASS, got {data['result']}"
    assert data["status"] == "PASSED", f"expected status PASSED, got {data['status']}"


# ===========================================================================
# Difficulty / combinatorial_formula / gage_rr_nested_rounding_order_pinned
# ===========================================================================
def test_gage_rr_pct_grr_nested_rounding_unacceptable(api):
    """PRD §3.7: "The percentage `pct_grr` is one hundred times the quantity six
    times `grr` divided by `process_tolerance`, rounded half-up to 2 decimal
    places."
    PRD §3.7: "`UNACCEPTABLE` when `pct_grr` is greater than 30.00."

    A 2x2x2 matrix carrying full precision through EV/AV/GRR yields pct_grr 32.27.

    Design: Difficulty/combinatorial_formula/gage_rr_nested_rounding_order_pinned
    """
    inst = create_instrument(asset_tag="INST-GRR", nominal_value=5.0,
                             tolerance_plus=1.0, tolerance_minus=1.0, criticality="MAJOR")
    study = setup_analyzed_study(inst["id"], inst["version"],
                                 matrix=GRR_UNACCEPTABLE_MATRIX)
    data = validate_success(api.get_study(study["id"], QE))
    assert data["pct_grr"] == 32.27, f"expected pct_grr 32.27, got {data['pct_grr']}"
    assert data["acceptability"] == "UNACCEPTABLE", \
        f"expected acceptability UNACCEPTABLE, got {data['acceptability']}"
    assert data["status"] == "ANALYZED", f"expected status ANALYZED, got {data['status']}"


def test_gage_rr_pct_grr_marginal_tier_via_process_tolerance(api):
    """PRD §3.7: "The percentage `pct_grr` is one hundred times the quantity six
    times `grr` divided by `process_tolerance`, rounded half-up to 2 decimal
    places."
    PRD §3.7: "`MARGINAL` when `pct_grr` is greater than 10.00 and at most 30.00".

    The same trial matrix with process_tolerance 20.0 (vs 10.0) yields pct_grr
    16.13, landing in the MARGINAL tier — the nested rounding chain divides by the
    denominator only at the final %GRR.

    Design: Difficulty/combinatorial_formula/gage_rr_nested_rounding_order_pinned
    """
    inst = create_instrument(asset_tag="INST-GRRM", nominal_value=5.0,
                             tolerance_plus=1.0, tolerance_minus=1.0, criticality="MAJOR")
    study = setup_analyzed_study(inst["id"], inst["version"],
                                 matrix=GRR_UNACCEPTABLE_MATRIX, process_tolerance=20.0)
    data = validate_success(api.get_study(study["id"], QE))
    assert data["pct_grr"] == 16.13, f"expected pct_grr 16.13, got {data['pct_grr']}"
    assert data["acceptability"] == "MARGINAL", \
        f"expected acceptability MARGINAL, got {data['acceptability']}"


# ===========================================================================
# Corner / calculations / corner_max_abs_deviation_aggregation
# ===========================================================================
def test_max_abs_deviation_is_largest_point_deviation(api):
    """PRD §3.4: "It computes `max_abs_deviation` as the largest value, over the
    event's measurement points, of the absolute difference between a point's
    `as_found_value` and its `nominal`, reported to 6 decimal places round-half-up."

    Two points deviating 0.04 and 0.03 → max_abs_deviation 0.04.

    Design: Corner/calculations/corner_max_abs_deviation_aggregation
    """
    std = create_standard(name="S-MAD", nist_test_number="NIST-MAD")
    inst = create_instrument(asset_tag="INST-MAD", criticality="MAJOR")
    ev = validate_success(api.create_event(
        inst["id"],
        {"standard_id": std["id"], "scheduled_epoch": 5,
         "expected_instrument_version": inst["version"]}, TECH), 201)
    validate_success(api.add_measurement_point(
        ev["id"], {"point_label": "P1", "nominal": 25.0, "tol_plus": 0.05,
                   "tol_minus": 0.05, "as_found_value": 25.04}, TECH), 201)
    validate_success(api.add_measurement_point(
        ev["id"], {"point_label": "P2", "nominal": 25.0, "tol_plus": 0.05,
                   "tol_minus": 0.05, "as_found_value": 24.97}, TECH), 201)
    validate_success(api.start_event(ev["id"], TECH))
    data = validate_success(api.finalize_event(ev["id"], TECH))
    assert data["max_abs_deviation"] == 0.04, \
        f"expected max_abs_deviation 0.04, got {data['max_abs_deviation']}"
    assert data["result"] == "PASS", f"expected result PASS, got {data['result']}"


# ===========================================================================
# Corner / calculations / corner_gage_rr_acceptable_zero_variation
# ===========================================================================
def test_gage_rr_zero_variation_acceptable_and_accept(api):
    """PRD §3.7: "`ACCEPTABLE` when `pct_grr` is at most 10.00".
    PRD §3.7: "Accepting an `ANALYZED` study moves it to `ACCEPTED` (terminal) and
    requires that its `acceptability` not be `UNACCEPTABLE`".

    Identical repeats and identical operator means → pct_grr 0.0, ACCEPTABLE, accepts.

    Design: Corner/calculations/corner_gage_rr_acceptable_zero_variation
    """
    inst = create_instrument(asset_tag="INST-GRA", nominal_value=5.0,
                             tolerance_plus=1.0, tolerance_minus=1.0, criticality="MAJOR")
    study = setup_analyzed_study(inst["id"], inst["version"],
                                 matrix=GRR_ZERO_VARIATION_MATRIX)
    analyzed = validate_success(api.get_study(study["id"], QE))
    assert analyzed["pct_grr"] == 0.0, f"expected pct_grr 0.0, got {analyzed['pct_grr']}"
    assert analyzed["acceptability"] == "ACCEPTABLE", \
        f"expected ACCEPTABLE, got {analyzed['acceptability']}"
    accepted = validate_success(api.accept_study(study["id"], QE))
    assert accepted["status"] == "ACCEPTED", \
        f"expected status ACCEPTED, got {accepted['status']}"


# ===========================================================================
# Corner / cross_cutting_complexity_layers / corner_derived_next_due_recompute_on_recalibration
# ===========================================================================
def test_next_due_epoch_recomputed_on_later_recalibration(api):
    """PRD §3.4: "`last_calibration_epoch` is set to the greatest `scheduled_epoch`
    among the instrument's events whose result is `PASS` or `CONDITIONAL`, breaking
    ties toward the earlier `created_at`."
    PRD §3.4: "`next_due_epoch` is set to that `last_calibration_epoch` plus the
    instrument's `calibration_interval_epochs`."

    Interval 10; first PASS at epoch 5, second PASS at epoch 40 → next_due 50 (not
    the stale 15).

    Design: Corner/cross_cutting_complexity_layers/corner_derived_next_due_recompute_on_recalibration
    """
    std = create_standard(name="S-DR", nist_test_number="NIST-DR")
    inst = create_instrument(asset_tag="INST-DR", criticality="MAJOR",
                             calibration_interval_epochs=10)
    inst_id = inst["id"]
    finalize_passing_event(inst_id, std["id"], inst["version"],
                           scheduled_epoch=5, as_found_value=25.00)
    finalize_passing_event(inst_id, std["id"], current_version(inst_id),
                           scheduled_epoch=40, as_found_value=25.00)
    data = validate_success(api.get_instrument(inst_id, QE))
    assert data["last_calibration_epoch"] == 40, \
        f"expected last_calibration_epoch 40, got {data['last_calibration_epoch']}"
    assert data["next_due_epoch"] == 50, \
        f"expected next_due_epoch 50, got {data['next_due_epoch']}"
