"""Rule dual_variant_calc — one record, two deliberately diverging numbers.

Three entity domains are covered: the QcValidationReport's strict versus
advisory quality score, the AddressPoint's provisional versus certified
confidence score, and the Jurisdiction/CoverageCell instantaneous versus
forward-window coverage counters.
"""

from test_helpers import (
    CLOCK_STARTUP_INPUT,
    assert_address_point,
    assert_cell_assignment,
    assert_coverage_status_shape,
    assert_jurisdiction,
    assert_qc_report,
    assert_road_centerline,
    assert_score_equals,
    assert_service_type_order,
)
from test_helpers import fixtures as fx


# ===========================================================================
# Instance qc_strict_vs_advisory_quality_score_diverge
# ===========================================================================
def test_jurisdiction_scan_strict_quality_score_is_seventy_seven_point_zero_six(api):
    """The strict variant on the worked eight-defect jurisdiction scan lands on 77.06.

    The `quality_score` is therefore 37.58 plus 23.85 plus 15.63, which is 77.06 — whereas summing the unrounded products first would have produced 77.05.

    Design: Difficulty/dual_variant_calc/qc_strict_vs_advisory_quality_score_diverge
    """
    fx.set_clock(api, CLOCK_STARTUP_INPUT)
    jurisdiction = fx.setup_jurisdiction(api)
    j_id = jurisdiction["id"]
    cell = fx.setup_coverage_cell(api, j_id, "C001")
    road = fx.setup_road(api, j_id, primary_name="N Maple St")
    point = fx.setup_address_point(
        api,
        road["id"],
        cell["id"],
        house_number=100,
        side="LEFT",
        source="FIELD",
        postal_city="LOVELAND",
        geometry_verified=False,
    )
    assert_address_point(point, status="PENDING", confidence_basis="PROVISIONAL")
    assert_score_equals(point["confidence_score"], 71.00, "confidence_score")

    report = fx.setup_jurisdiction_scoped_report(api, j_id)
    assert_qc_report(
        report,
        scope="JURISDICTION",
        status="GENERATED",
        defect_count=8,
        blocking_defect_count=5,
        warning_defect_count=3,
        info_defect_count=0,
    )
    assert_score_equals(report["quality_score"], 77.06, "quality_score")

    reread = fx.read_report(api, report["id"])
    assert_score_equals(reread["quality_score"], 77.06, "quality_score")


def test_jurisdiction_scan_advisory_variant_rises_to_eighty_one_point_two_six(api):
    """The advisory variant counts only the five BLOCKING rows and diverges by 4.20.

    In the same report the advisory variant counts only the five `BLOCKING` findings and rises to 81.26, which is the divergence between the two variants.

    Design: Difficulty/dual_variant_calc/qc_strict_vs_advisory_quality_score_diverge
    """
    fx.set_clock(api, CLOCK_STARTUP_INPUT)
    jurisdiction = fx.setup_jurisdiction(api)
    j_id = jurisdiction["id"]
    cell = fx.setup_coverage_cell(api, j_id, "C001")
    road = fx.setup_road(api, j_id, primary_name="N Maple St")
    fx.setup_address_point(
        api,
        road["id"],
        cell["id"],
        house_number=100,
        side="LEFT",
        source="FIELD",
        postal_city="LOVELAND",
        geometry_verified=False,
    )

    report = fx.setup_jurisdiction_scoped_report(api, j_id)
    assert_score_equals(
        report["advisory_quality_score"], 81.26, "advisory_quality_score"
    )
    assert_score_equals(report["quality_score"], 77.06, "quality_score")
    assert report["quality_score"] != report["advisory_quality_score"], (
        "the strict and advisory variants must diverge on this report"
    )
    assert (
        round(report["advisory_quality_score"] - report["quality_score"], 2) == 4.20
    ), "the advisory variant sits 4.20 above the strict variant"


def test_quality_tier_c_is_read_from_the_strict_score_never_the_advisory_one(api):
    """Tier C follows the strict 77.06; the advisory 81.26 would have said B.

    The report's `quality_tier` is read from `quality_score` — the strict variant — and never from `advisory_quality_score`.

    Design: Difficulty/dual_variant_calc/qc_strict_vs_advisory_quality_score_diverge
    """
    fx.set_clock(api, CLOCK_STARTUP_INPUT)
    jurisdiction = fx.setup_jurisdiction(api)
    j_id = jurisdiction["id"]
    cell = fx.setup_coverage_cell(api, j_id, "C001")
    road = fx.setup_road(api, j_id, primary_name="N Maple St")
    fx.setup_address_point(
        api,
        road["id"],
        cell["id"],
        house_number=100,
        side="LEFT",
        source="FIELD",
        postal_city="LOVELAND",
        geometry_verified=False,
    )

    report = fx.setup_jurisdiction_scoped_report(api, j_id)
    assert_qc_report(report, quality_tier="C", status="GENERATED")
    assert_score_equals(report["quality_score"], 77.06, "quality_score")
    assert_score_equals(
        report["advisory_quality_score"], 81.26, "advisory_quality_score"
    )
    assert report["quality_tier"] == "C", (
        "reading the tier from the advisory 81.26 would have selected B"
    )


# ===========================================================================
# Instance address_confidence_provisional_vs_certified_diverge
# ===========================================================================
def test_certification_writes_certified_confidence_of_seventy_six_on_a_contested_road(api):
    """The certified variant subtracts the 20-point open-discrepancy penalty: 96 becomes 76.00.

    Its raw value uses all of the same terms as the provisional variant and then adds two more: a bonus of 10 when the point's coverage cell has zero gap pairs at the logical clock instant — that is, when all three service types are covered there — and a penalty of 20 when the point's centerline has an `open_discrepancy_case_count` greater than zero.

    Design: Difficulty/dual_variant_calc/address_confidence_provisional_vs_certified_diverge
    """
    fx.set_clock(api, CLOCK_STARTUP_INPUT)
    jurisdiction = fx.setup_jurisdiction(api)
    j_id = jurisdiction["id"]
    cell = fx.setup_coverage_cell(api, j_id, "C001")
    law = fx.setup_agency(api, j_id, "LAW")
    fire = fx.setup_agency(api, j_id, "FIRE")

    road = fx.setup_road(api, j_id, primary_name="N MAPLE STREET")
    road_id = road["id"]
    point = fx.setup_address_point(
        api,
        road_id,
        cell["id"],
        house_number=100,
        side="LEFT",
        source="PARCEL",
        postal_city="FORT COLLINS",
        geometry_verified=True,
    )
    fx.validate_road(api, road_id)
    fx.publish_road(api, road_id)
    activated = fx.activate_point(api, point["id"])
    assert_score_equals(activated["confidence_score"], 96.00, "confidence_score")

    case = fx.setup_discrepancy_case(
        api,
        road_id,
        law["id"],
        fire["id"],
        description="Sheriff dispatch signage reads N MAPLE AVE",
    )
    assert case["status"] == "OPEN", "a new case lands in OPEN status"
    frozen_road = fx.read_road(api, road_id)
    assert_road_centerline(frozen_road, open_discrepancy_case_count=1)

    report = fx.setup_road_scoped_report(api, road_id)
    assert_qc_report(report, scope="ROAD", status="GENERATED", defect_count=0)
    assert_score_equals(report["quality_score"], 100.00, "quality_score")

    certified = fx.certify_report(api, report["id"])
    assert_qc_report(certified, status="CERTIFIED")

    stamped = fx.read_point(api, point["id"])
    assert_address_point(stamped, confidence_basis="CERTIFIED")
    assert_score_equals(
        stamped["certified_confidence_score"], 76.00, "certified_confidence_score"
    )


def test_provisional_confidence_score_stays_ninety_six_after_certification(api):
    """Both numbers live on the point at once, so the 20-point delta stays inspectable.

    It writes `certified_confidence_score`, sets `confidence_basis` to `CERTIFIED`, and deliberately leaves the provisional `confidence_score` untouched so that the delta between the two remains inspectable.

    Design: Difficulty/dual_variant_calc/address_confidence_provisional_vs_certified_diverge
    """
    fx.set_clock(api, CLOCK_STARTUP_INPUT)
    jurisdiction = fx.setup_jurisdiction(api)
    j_id = jurisdiction["id"]
    cell = fx.setup_coverage_cell(api, j_id, "C001")
    law = fx.setup_agency(api, j_id, "LAW")
    fire = fx.setup_agency(api, j_id, "FIRE")

    road = fx.setup_road(api, j_id, primary_name="N MAPLE STREET")
    road_id = road["id"]
    point = fx.setup_address_point(
        api,
        road_id,
        cell["id"],
        house_number=100,
        side="LEFT",
        source="PARCEL",
        postal_city="FORT COLLINS",
        geometry_verified=True,
    )
    fx.validate_road(api, road_id)
    fx.publish_road(api, road_id)
    fx.activate_point(api, point["id"])
    fx.setup_discrepancy_case(
        api,
        road_id,
        law["id"],
        fire["id"],
        description="Sheriff dispatch signage reads N MAPLE AVE",
    )

    report = fx.setup_road_scoped_report(api, road_id)
    fx.certify_report(api, report["id"])

    stamped = fx.read_point(api, point["id"])
    assert_score_equals(stamped["confidence_score"], 96.00, "confidence_score")
    assert_score_equals(
        stamped["certified_confidence_score"], 76.00, "certified_confidence_score"
    )
    assert stamped["certified_confidence_score"] != stamped["confidence_score"], (
        "the certified variant must diverge from the provisional one"
    )


# ===========================================================================
# Instance jurisdiction_instantaneous_vs_forward_gap_counters_diverge
# ===========================================================================
def test_instantaneous_gap_pair_count_is_zero_while_forward_gap_pair_count_is_one(api):
    """All three types cover the instant, but the LAW claim dies inside the horizon.

    Instead give the `LAW` assignment an `effective_end` ten days out with no successor and the two disagree — `gap_pair_count` stays at 0 because the assignment covers this instant, while `forward_gap_pair_count` becomes 1 — and only the forward number blocks a dispatch release.

    Design: Difficulty/dual_variant_calc/jurisdiction_instantaneous_vs_forward_gap_counters_diverge
    """
    fx.set_clock(api, CLOCK_STARTUP_INPUT)
    jurisdiction = fx.setup_jurisdiction(api)
    j_id = jurisdiction["id"]
    cell = fx.setup_coverage_cell(api, j_id, "C001")
    cell_id = cell["id"]

    law = fx.setup_agency(api, j_id, "LAW")
    fire = fx.setup_agency(api, j_id, "FIRE")
    ems = fx.setup_agency(api, j_id, "EMS")

    law_built = fx.setup_active_boundary_on_cell(
        api,
        law["id"],
        cell_id,
        claim_overrides={"effective_end": "2026-08-11T00:00:00Z"},
    )
    fx.setup_active_boundary_on_cell(api, fire["id"], cell_id)
    fx.setup_active_boundary_on_cell(api, ems["id"], cell_id)

    live = fx.read_jurisdiction(api, j_id)
    assert_jurisdiction(
        live,
        cell_count=1,
        covered_cell_count=1,
        gap_pair_count=0,
        forward_gap_pair_count=1,
    )
    assert live["gap_pair_count"] != live["forward_gap_pair_count"], (
        "the instantaneous and forward-window counters must diverge here"
    )

    law_assignment = fx.read_cell_assignment(api, law_built["assignment_id"])
    assert_cell_assignment(law_assignment, status="ACTIVE", service_type="LAW")


def test_forward_window_view_reports_a_law_forward_gap_over_the_thirty_day_horizon(api):
    """The clipped-and-merged LAW union stops on 2026-08-11, short of the horizon.

    For each cell-and-service-type pair, the `ACTIVE` assignments' half-open windows are clipped to that thirty-day horizon and merged, and the pair counts as a **forward gap** when the merged union does not cover the whole horizon.

    Design: Difficulty/dual_variant_calc/jurisdiction_instantaneous_vs_forward_gap_counters_diverge
    """
    fx.set_clock(api, CLOCK_STARTUP_INPUT)
    jurisdiction = fx.setup_jurisdiction(api)
    j_id = jurisdiction["id"]
    cell = fx.setup_coverage_cell(api, j_id, "C001")
    cell_id = cell["id"]

    law = fx.setup_agency(api, j_id, "LAW")
    fire = fx.setup_agency(api, j_id, "FIRE")
    ems = fx.setup_agency(api, j_id, "EMS")

    fx.setup_active_boundary_on_cell(
        api,
        law["id"],
        cell_id,
        claim_overrides={"effective_end": "2026-08-11T00:00:00Z"},
    )
    fx.setup_active_boundary_on_cell(api, fire["id"], cell_id)
    fx.setup_active_boundary_on_cell(api, ems["id"], cell_id)

    status = fx.read_coverage_status(api, cell_id)
    assert_coverage_status_shape(status)
    assert status["forward_gap_service_types"] == ["LAW"], (
        "only LAW loses its cover inside the thirty-day horizon"
    )
    assert status["gap_service_types"] == [], (
        "nothing is uncovered at the logical clock instant"
    )

    live = fx.read_jurisdiction(api, j_id)
    assert_jurisdiction(live, gap_pair_count=0, forward_gap_pair_count=1)


def test_coverage_status_arrays_are_emitted_in_the_ordered_law_fire_ems_sequence(api):
    """The computed read exposes both views side by side in the fixed service-type order.

    The three service types form an **ordered** constant, `LAW` then `FIRE` then `EMS`, and every one of those four arrays is produced by filtering that sequence in that order.

    Design: Difficulty/dual_variant_calc/jurisdiction_instantaneous_vs_forward_gap_counters_diverge
    """
    fx.set_clock(api, CLOCK_STARTUP_INPUT)
    jurisdiction = fx.setup_jurisdiction(api)
    j_id = jurisdiction["id"]
    cell = fx.setup_coverage_cell(api, j_id, "C001")
    cell_id = cell["id"]

    law = fx.setup_agency(api, j_id, "LAW")
    fire = fx.setup_agency(api, j_id, "FIRE")
    ems = fx.setup_agency(api, j_id, "EMS")

    fx.setup_active_boundary_on_cell(
        api,
        law["id"],
        cell_id,
        claim_overrides={"effective_end": "2026-08-11T00:00:00Z"},
    )
    fx.setup_active_boundary_on_cell(api, fire["id"], cell_id)
    fx.setup_active_boundary_on_cell(api, ems["id"], cell_id)

    status = fx.read_coverage_status(api, cell_id)
    assert_coverage_status_shape(status)
    assert status["covered_service_types"] == ["LAW", "FIRE", "EMS"], (
        "all three types respond on this cell at the current instant"
    )
    assert_service_type_order(status["covered_service_types"], "covered_service_types")
    assert status["responding_assignment_count"] == 3, (
        "three ACTIVE assignments answer on this cell now"
    )
    assert status["proposed_conflict_service_types"] == [], (
        "no pending claim intersects an existing one"
    )

    live_cell = fx.read_cell(api, cell_id)
    assert live_cell["active_assignment_count"] == 3, (
        "active_assignment_count sums the ACTIVE assignments across service types"
    )
