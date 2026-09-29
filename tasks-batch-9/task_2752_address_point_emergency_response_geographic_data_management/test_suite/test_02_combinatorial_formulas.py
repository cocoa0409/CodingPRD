"""Rule combinatorial_formula — three different composition modes.

Mode (b) nested rounding order on the quality score, mode (c) an evaluation
order that pins the waiver-penalty tier to the base score, and mode (a) five
interacting confidence inputs whose sum is collapsed by the SCORE_MAX clamp.
"""

from test_helpers import (
    CLOCK_STARTUP_INPUT,
    assert_address_point,
    assert_jurisdiction,
    assert_qc_defect,
    assert_qc_report,
    assert_score_equals,
)
from test_helpers import fixtures as fx


# ===========================================================================
# Instance qc_quality_score_per_category_rounding_order
# ===========================================================================
def test_quality_score_rounds_each_category_before_summing_to_ninety_six_point_two_one(api):
    """ADDRESS 44.325 and BOUNDARY 21.875 must each round first; summing first gives 96.20.

    The per-category round-then-sum ordering is normative and is observably different from summing first and rounding once.

    Design: Difficulty/combinatorial_formula/qc_quality_score_per_category_rounding_order
    """
    fx.set_clock(api, CLOCK_STARTUP_INPUT)
    jurisdiction = fx.setup_jurisdiction(api)
    j_id = jurisdiction["id"]
    cell = fx.setup_coverage_cell(api, j_id, "C001")
    cell_id = cell["id"]

    law = fx.setup_agency(api, j_id, "LAW")
    fire = fx.setup_agency(api, j_id, "FIRE")
    fx.setup_active_boundary_on_cell(api, law["id"], cell_id)
    fx.setup_active_boundary_on_cell(api, fire["id"], cell_id)

    road = fx.setup_road(api, j_id, primary_name="N MAPLE STREET")
    road_id = road["id"]
    fx.validate_road(api, road_id)
    point = fx.setup_address_point(
        api,
        road_id,
        cell_id,
        house_number=100,
        side="LEFT",
        source="POSTAL",
        postal_city="FORT COLLINS",
        geometry_verified=True,
    )
    assert_address_point(point, status="PENDING", source="POSTAL")
    assert_score_equals(point["confidence_score"], 66.00, "confidence_score")

    live = fx.read_jurisdiction(api, j_id)
    assert_jurisdiction(live, gap_pair_count=1)

    report = fx.setup_jurisdiction_scoped_report(api, j_id)
    assert_qc_report(
        report,
        scope="JURISDICTION",
        status="GENERATED",
        defect_count=2,
        blocking_defect_count=1,
        warning_defect_count=0,
        info_defect_count=1,
    )
    assert_score_equals(report["quality_score"], 96.21, "quality_score")
    assert report["quality_score"] != 96.20, (
        "96.20 is the sum-then-round error the per-category ordering rules out"
    )


def test_rounded_categories_give_an_advisory_score_of_ninety_six_point_eight_eight(api):
    """The same two-defect scan scores tier A yet is refused provisioning on the open blocker.

    The `is_provisioning_eligible` flag is true when `provisioning_eligibility_score` is greater than or equal to 90.00 — the threshold is inclusive — **and** `open_blocking_defect_count` is zero.

    Design: Difficulty/combinatorial_formula/qc_quality_score_per_category_rounding_order
    """
    fx.set_clock(api, CLOCK_STARTUP_INPUT)
    jurisdiction = fx.setup_jurisdiction(api)
    j_id = jurisdiction["id"]
    cell = fx.setup_coverage_cell(api, j_id, "C001")
    cell_id = cell["id"]

    law = fx.setup_agency(api, j_id, "LAW")
    fire = fx.setup_agency(api, j_id, "FIRE")
    fx.setup_active_boundary_on_cell(api, law["id"], cell_id)
    fx.setup_active_boundary_on_cell(api, fire["id"], cell_id)

    road = fx.setup_road(api, j_id, primary_name="N MAPLE STREET")
    road_id = road["id"]
    fx.validate_road(api, road_id)
    fx.setup_address_point(
        api,
        road_id,
        cell_id,
        house_number=100,
        side="LEFT",
        source="POSTAL",
        postal_city="FORT COLLINS",
        geometry_verified=True,
    )

    report = fx.setup_jurisdiction_scoped_report(api, j_id)
    assert_qc_report(report, quality_tier="A", is_provisioning_eligible=False)
    assert_score_equals(
        report["advisory_quality_score"], 96.88, "advisory_quality_score"
    )
    assert_score_equals(report["quality_score"], 96.21, "quality_score")
    assert_score_equals(
        report["provisioning_eligibility_score"],
        96.21,
        "provisioning_eligibility_score",
    )
    assert report["open_blocking_defect_count"] == 1, (
        "the single BOUNDARY coverage gap is still open"
    )


# ===========================================================================
# Instance provisioning_eligibility_tier_pinned_to_base_score
# ===========================================================================
def _build_five_point_road_scoped_report(api):
    """Jurisdiction + cell + VALIDATED road + five points, then a ROAD-scoped scan.

    The scan finds 1 BLOCKING, 2 WARNING and 2 INFO ADDRESS defects, so the
    strict base is 89.43 at tier B before any waiver is applied.
    """
    jurisdiction = fx.setup_jurisdiction(api)
    j_id = jurisdiction["id"]
    cell = fx.setup_coverage_cell(api, j_id, "C001")
    cell_id = cell["id"]
    road = fx.setup_road(api, j_id, primary_name="N MAPLE STREET")
    road_id = road["id"]
    fx.validate_road(api, road_id)

    p1 = fx.setup_address_point(
        api, road_id, cell_id, house_number=100, side="LEFT", source="POSTAL",
        postal_city="FORT COLLINS", geometry_verified=True,
    )
    p2 = fx.setup_address_point(
        api, road_id, cell_id, house_number=102, side="LEFT", source="POSTAL",
        postal_city="FORT COLLINS", geometry_verified=True,
    )
    p3 = fx.setup_address_point(
        api, road_id, cell_id, house_number=104, side="LEFT", source="PARCEL",
        postal_city="LOVELAND", geometry_verified=True,
    )
    p4 = fx.setup_address_point(
        api, road_id, cell_id, house_number=106, side="LEFT", source="FIELD",
        postal_city="FORT COLLINS", geometry_verified=False,
    )
    p5 = fx.setup_unit_point(
        api, road_id, cell_id, p4["id"], unit_id="1", house_number=106,
        source="FIELD", geometry_verified=True, omit=["unit_type"],
    )
    report = fx.setup_road_scoped_report(api, road_id)
    return {
        "j_id": j_id,
        "road_id": road_id,
        "points": [p1, p2, p3, p4, p5],
        "report": report,
        "report_id": report["id"],
    }


def test_waiving_the_blocking_defect_raises_the_strict_base_to_ninety_five_point_zero_five(api):
    """The waived finding leaves the open deduction base, lifting 89.43 to 95.05 and tier B to A.

    Note also the two-directional movement that waiving produces: a waiver always **raises** the strict base, because the waived defect leaves the open deduction base, and then **lowers** the eligibility score by the tier rate.

    Design: Difficulty/combinatorial_formula/provisioning_eligibility_tier_pinned_to_base_score
    """
    fx.set_clock(api, CLOCK_STARTUP_INPUT)
    built = _build_five_point_road_scoped_report(api)
    p1, _p2, p3, p4, p5 = built["points"]

    assert_score_equals(p1["confidence_score"], 66.00, "confidence_score")
    assert_score_equals(p3["confidence_score"], 83.00, "confidence_score")
    assert_score_equals(p4["confidence_score"], 89.00, "confidence_score")
    assert_score_equals(p5["confidence_score"], 95.00, "confidence_score")

    before = built["report"]
    assert_qc_report(before, quality_tier="B", defect_count=5, status="GENERATED")
    assert_score_equals(before["quality_score"], 89.43, "quality_score")

    blocking = fx.list_defects(
        api, built["report_id"], {"severity": "BLOCKING", "limit": 100}
    )
    assert len(blocking) == 1, "exactly one BLOCKING ADDRESS defect was emitted"
    waived = fx.waive_defect(
        api,
        blocking[0]["id"],
        waiver_reason="Field crew geometry survey scheduled for the next cycle",
    )
    assert_qc_defect(waived, status="WAIVED")

    after = fx.read_report(api, built["report_id"])
    assert_qc_report(
        after,
        quality_tier="A",
        open_blocking_defect_count=0,
        waived_blocking_count=1,
    )
    assert_score_equals(after["quality_score"], 95.05, "quality_score")


def test_provisioning_eligibility_applies_the_tier_pinned_to_the_base_score(api):
    """Tier A's rate of 1.0 yields 94.05; re-deriving tier B from 94.05 would give 92.55.

    Because the tier is pinned to the base, the `A` rate applies even though the result itself falls in the `B` band; re-deriving the tier from 94.05 would have selected `B` and its rate of 2.5, yielding 92.55 instead.

    Design: Difficulty/combinatorial_formula/provisioning_eligibility_tier_pinned_to_base_score
    """
    fx.set_clock(api, CLOCK_STARTUP_INPUT)
    built = _build_five_point_road_scoped_report(api)

    blocking = fx.list_defects(
        api, built["report_id"], {"severity": "BLOCKING", "limit": 100}
    )
    fx.waive_defect(
        api,
        blocking[0]["id"],
        waiver_reason="Field crew geometry survey scheduled for the next cycle",
    )

    after = fx.read_report(api, built["report_id"])
    assert_qc_report(after, quality_tier="A", is_provisioning_eligible=True)
    assert_score_equals(after["quality_score"], 95.05, "quality_score")
    assert_score_equals(
        after["provisioning_eligibility_score"],
        94.05,
        "provisioning_eligibility_score",
    )
    assert after["provisioning_eligibility_score"] != 92.55, (
        "92.55 is the re-derived-tier error the pinning rule rules out"
    )


def test_advisory_score_keeps_counting_the_waived_blocking_finding_at_full_weight(api):
    """The advisory variant is unmoved by the waiver and stays at 94.38.

    The **advisory** variant writes `advisory_quality_score` and differs in two ways at once: its deduction base is restricted to `BLOCKING` defects only, since `WARNING` and `INFO` findings are advisory noise the analyst is permitted to publish over, and it counts waived defects at full weight, because a waiver is an accepted risk rather than a repaired defect and the advisory view is meant to keep showing it.

    Design: Difficulty/combinatorial_formula/provisioning_eligibility_tier_pinned_to_base_score
    """
    fx.set_clock(api, CLOCK_STARTUP_INPUT)
    built = _build_five_point_road_scoped_report(api)
    assert_score_equals(
        built["report"]["advisory_quality_score"], 94.38, "advisory_quality_score"
    )

    blocking = fx.list_defects(
        api, built["report_id"], {"severity": "BLOCKING", "limit": 100}
    )
    fx.waive_defect(
        api,
        blocking[0]["id"],
        waiver_reason="Field crew geometry survey scheduled for the next cycle",
    )

    after = fx.read_report(api, built["report_id"])
    assert_score_equals(
        after["advisory_quality_score"], 94.38, "advisory_quality_score"
    )
    assert_score_equals(after["quality_score"], 95.05, "quality_score")


# ===========================================================================
# Instance address_confidence_clamped_multi_factor
# ===========================================================================
def test_certified_confidence_clamps_to_one_hundred_on_a_fully_covered_cell(api):
    """Five confidence terms plus the coverage bonus raise the raw to 106, which clamps.

    Certified on a fully covered cell it would raise to 106, which clamps to 100.00 — so the certified variant diverges by 4.00, not by the 10.00 the bonus suggests.

    Design: Difficulty/combinatorial_formula/address_confidence_clamped_multi_factor
    """
    fx.set_clock(api, CLOCK_STARTUP_INPUT)
    jurisdiction = fx.setup_jurisdiction(api)
    j_id = jurisdiction["id"]
    cell = fx.setup_coverage_cell(api, j_id, "C001")
    cell_id = cell["id"]
    fx.setup_full_coverage(api, j_id, cell_id)

    live = fx.read_jurisdiction(api, j_id)
    assert_jurisdiction(live, gap_pair_count=0, covered_cell_count=1)

    road = fx.setup_road(api, j_id, primary_name="N MAPLE STREET")
    road_id = road["id"]
    point = fx.setup_address_point(
        api,
        road_id,
        cell_id,
        house_number=100,
        side="LEFT",
        source="PARCEL",
        postal_city="FORT COLLINS",
        geometry_verified=True,
    )
    fx.validate_road(api, road_id)
    fx.publish_road(api, road_id)
    activated = fx.activate_point(api, point["id"])
    assert_address_point(activated, status="ACTIVE", confidence_basis="PROVISIONAL")
    assert_score_equals(activated["confidence_score"], 96.00, "confidence_score")

    report = fx.setup_road_scoped_report(api, road_id)
    assert_qc_report(report, scope="ROAD", defect_count=0, status="GENERATED")
    assert_score_equals(report["quality_score"], 100.00, "quality_score")

    certified = fx.certify_report(api, report["id"])
    assert_qc_report(certified, status="CERTIFIED")

    stamped = fx.read_point(api, point["id"])
    assert_address_point(stamped, confidence_basis="CERTIFIED")
    assert_score_equals(
        stamped["certified_confidence_score"], 100.00, "certified_confidence_score"
    )


def test_provisional_to_certified_delta_is_four_rather_than_the_naive_ten(api):
    """The clamp is what stops the two variants being a constant offset apart.

    A `PARCEL`-sourced, geometry-verified, postal-matching base point on a `PUBLISHED` road scores 70 plus 12 plus 8 plus 6 with no penalty, giving a provisional 96.00.

    Design: Difficulty/combinatorial_formula/address_confidence_clamped_multi_factor
    """
    fx.set_clock(api, CLOCK_STARTUP_INPUT)
    jurisdiction = fx.setup_jurisdiction(api)
    j_id = jurisdiction["id"]
    cell = fx.setup_coverage_cell(api, j_id, "C001")
    cell_id = cell["id"]
    fx.setup_full_coverage(api, j_id, cell_id)

    road = fx.setup_road(api, j_id, primary_name="N MAPLE STREET")
    road_id = road["id"]
    point = fx.setup_address_point(
        api,
        road_id,
        cell_id,
        house_number=100,
        side="LEFT",
        source="PARCEL",
        postal_city="FORT COLLINS",
        geometry_verified=True,
    )
    fx.validate_road(api, road_id)
    fx.publish_road(api, road_id)
    fx.activate_point(api, point["id"])

    report = fx.setup_road_scoped_report(api, road_id)
    fx.certify_report(api, report["id"])

    stamped = fx.read_point(api, point["id"])
    assert_score_equals(stamped["confidence_score"], 96.00, "confidence_score")
    assert_score_equals(
        stamped["certified_confidence_score"], 100.00, "certified_confidence_score"
    )
    assert (
        round(stamped["certified_confidence_score"] - stamped["confidence_score"], 2)
        == 4.00
    ), "the clamp collapses the 10-point coverage bonus into a 4.00 delta"

    road_after = fx.read_road(api, road_id)
    assert road_after["open_discrepancy_case_count"] == 0, (
        "no open case, so the certified variant applies no discrepancy penalty"
    )
