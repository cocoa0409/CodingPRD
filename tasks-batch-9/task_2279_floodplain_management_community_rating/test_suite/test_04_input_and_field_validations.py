"""Field-level, arithmetic-bound and documentation-completeness validations.

Every test builds its own entities from scratch through PRD-declared endpoints
and trips exactly one rule, so the expected error identifier is unambiguous.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_property,
    analyze_area,
    delineate_area,
    designate_area,
    make_property_owner_headers,
    open_cycle,
    read_area,
    read_certificate,
    read_permit,
    read_structure,
    record_delivery,
    setup_approved_permit,
    setup_filed_certificate,
    setup_issued_permit,
    setup_outreach_in_progress,
    setup_parcel,
    setup_permit_under_review,
    validate_error,
)

_ADMIN = TEST_USERS["administrator_headers"]


# ==========================================================================
# Elevation adequacy
# ==========================================================================

def test_permit_approval_one_tenth_below_the_requirement_is_rejected(api):
    """PRD §3.4: "The elevation gate requires `proposed_lowest_floor_elevation_ft` to be at
    least `required_lowest_floor_elevation_ft`; a shortfall is `ERR_ELEVATION_BELOW_REQUIRED`."

    PRD §3.4: "The base, the freeboard, and the bump are added together and the credit is
    subtracted, and that single sum is rounded half-up to one decimal place."

    Design: Corner/validations/permit_approval_one_tenth_below_the_requirement_is_rejected
    """
    scenario = setup_permit_under_review(
        permit_overrides={
            "project_type": "NEW_CONSTRUCTION",
            "declared_project_cost_usd": 20_000.00,
            "proposed_lowest_floor_elevation_ft": 13.4,
        },
        community_overrides={"freeboard_ft": 1.5},
    )
    permit = scenario["permit"]
    assert permit["required_lowest_floor_elevation_ft"] == pytest.approx(13.5, abs=0.01)

    resp = api.review_permit(permit["id"], {"decision": "APPROVE"}, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_ELEVATION_BELOW_REQUIRED)

    after = read_permit(permit["id"])
    assert after["status"] == "UNDER_REVIEW"
    assert after["required_lowest_floor_elevation_ft"] == pytest.approx(13.5, abs=0.01)
    assert after["revision_round"] == 0


def test_certificate_acceptance_with_a_negative_margin_is_rejected(api):
    """PRD §3.5: "Acceptance additionally requires that the certificate's `structure_id`
    still equals its permit's `structure_id` and that `freeboard_margin_ft` be at least 0.0
    feet; a negative margin is rejected with `ERR_ELEVATION_BELOW_REQUIRED`."

    PRD §3.5: "The permit's current `required_lowest_floor_elevation_ft` is then subtracted
    from that already-rounded normalized value, and the difference is rounded half-up to one
    decimal place again to yield `freeboard_margin_ft`."

    Design: Corner/validations/certificate_acceptance_with_a_negative_margin_is_rejected
    """
    scenario = setup_filed_certificate(
        certificate_overrides={
            "certificate_type": "FINISHED_CONSTRUCTION",
            "datum": "NAVD88",
            "measured_lowest_floor_ft": 13.4,
            "measured_bfe_ft": 12.0,
            "surveyor_license_no": "TX-5511",
        },
        permit_overrides={
            "project_type": "NEW_CONSTRUCTION",
            "declared_project_cost_usd": 20_000.00,
            "proposed_lowest_floor_elevation_ft": 20.0,
        },
        community_overrides={"freeboard_ft": 1.5},
    )
    certificate = scenario["certificate"]
    assert certificate["freeboard_margin_ft"] == pytest.approx(-0.1, abs=0.01)

    resp = api.review_certificate(certificate["id"], {"decision": "ACCEPT"}, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_ELEVATION_BELOW_REQUIRED)

    after = read_certificate(certificate["id"])
    assert after["status"] == "SUBMITTED"
    assert after["freeboard_margin_ft"] == pytest.approx(-0.1, abs=0.01)
    assert after["accepted_at"] is None

    structure = read_structure(scenario["structure"]["id"])
    assert structure["lowest_floor_elevation_ft"] is None
    assert structure["compliance_status"] == "PENDING_CERTIFICATE"


# ==========================================================================
# Documentation completeness
# ==========================================================================

def test_permit_closeout_without_a_finished_certificate_is_rejected(api):
    """PRD §3.4: "Closeout is refused unless the permit is `ISSUED`
    (`ERR_PERMIT_NOT_ISSUED`) and requires an `ElevationCertificate` filed against this
    permit whose `certificate_type` is `FINISHED_CONSTRUCTION` and whose `status` is
    `ACCEPTED`; without one, the closeout fails with `ERR_FINISHED_CERTIFICATE_REQUIRED`."

    Design: Corner/validations/permit_closeout_without_a_finished_certificate_is_rejected
    """
    scenario = setup_issued_permit(
        permit_overrides={
            "project_type": "IMPROVEMENT",
            "declared_project_cost_usd": 30_000.00,
            "proposed_lowest_floor_elevation_ft": 20.0,
        },
        community_overrides={"freeboard_ft": 1.5},
    )
    permit = scenario["permit"]

    resp = api.close_permit(permit["id"], _ADMIN)
    validate_error(resp, ApiErrorId.ERR_FINISHED_CERTIFICATE_REQUIRED)

    assert read_permit(permit["id"])["status"] == "ISSUED"

    structure = read_structure(scenario["structure"]["id"])
    assert float(structure["cumulative_counted_cost_usd"]) == 0
    assert structure["anchor_record_id"] is None


def test_finished_certificate_without_a_surveyor_license_is_rejected(api):
    """PRD §3.5: "The `surveyor_license_no` is optional for the first two certificate types
    but mandatory for `FINISHED_CONSTRUCTION`; a finished-construction filing or amendment
    without it is rejected with `ERR_SURVEYOR_LICENSE_REQUIRED`."

    Design: Corner/validations/finished_certificate_without_a_surveyor_license_is_rejected
    """
    scenario = setup_issued_permit(
        permit_overrides={
            "project_type": "NEW_CONSTRUCTION",
            "declared_project_cost_usd": 20_000.00,
            "proposed_lowest_floor_elevation_ft": 20.0,
        },
        community_overrides={"freeboard_ft": 1.5},
    )
    owner_headers = make_property_owner_headers(scenario["property"]["id"])

    resp = api.file_certificate(
        {
            "permit_id": scenario["permit"]["id"],
            "structure_id": scenario["structure"]["id"],
            "certificate_type": "FINISHED_CONSTRUCTION",
            "datum": "NAVD88",
            "measured_lowest_floor_ft": 14.0,
            "measured_bfe_ft": 12.0,
        },
        owner_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SURVEYOR_LICENSE_REQUIRED)

    assert read_permit(scenario["permit"]["id"])["status"] == "ISSUED"
    assert read_structure(scenario["structure"]["id"])["lowest_floor_elevation_ft"] is None


def test_certificate_against_an_approved_but_unissued_permit_is_rejected(api):
    """PRD §3.5: "A certificate may only be filed against a permit whose `status` is
    `ISSUED`; otherwise the filing is rejected with `ERR_PERMIT_NOT_ISSUED`."

    Design: Corner/validations/certificate_against_an_approved_but_unissued_permit_is_rejected
    """
    scenario = setup_approved_permit(
        permit_overrides={
            "project_type": "NEW_CONSTRUCTION",
            "declared_project_cost_usd": 20_000.00,
            "proposed_lowest_floor_elevation_ft": 20.0,
        },
        community_overrides={"freeboard_ft": 1.5},
    )
    owner_headers = make_property_owner_headers(scenario["property"]["id"])

    resp = api.file_certificate(
        {
            "permit_id": scenario["permit"]["id"],
            "structure_id": scenario["structure"]["id"],
            "certificate_type": "FINISHED_CONSTRUCTION",
            "datum": "NAVD88",
            "measured_lowest_floor_ft": 14.0,
            "measured_bfe_ft": 12.0,
            "surveyor_license_no": "TX-5511",
        },
        owner_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ISSUED)

    after = read_permit(scenario["permit"]["id"])
    assert after["status"] == "APPROVED"
    assert after["issued_at"] is None


# ==========================================================================
# Outreach arithmetic
# ==========================================================================

def test_outreach_target_below_the_analyzed_count_is_rejected(api):
    """PRD §3.9: "And the supplied `target_property_count`, the certified mailing-list size,
    must be at least the area's analyzed `property_count`, else
    `ERR_OUTREACH_TARGET_BELOW_ANALYZED`."

    PRD §3.9: "`property_count` is then recounted as the number of properties linked by this
    analysis and `rl_property_count` as the number of those linked properties whose
    `repetitive_loss_status` is anything other than `NONE`, `analysis_status` becomes
    `ANALYZED`, and `analyzed_at` is stamped with the current logical clock."

    Design: Corner/validations/outreach_target_below_the_analyzed_count_is_rejected
    """
    scenario = setup_parcel(
        community_overrides={"freeboard_ft": 1.5},
        property_overrides={"mapped_area_code": "RLA-1", "parcel_id": "P-0001"},
    )
    add_property(
        scenario["community"]["id"],
        scenario["panel"]["id"],
        parcel_id="P-0002",
        mapped_area_code="RLA-1",
        owner_name="B Owner",
        owner_email="b@example.com",
    )

    area = delineate_area(scenario["community"]["id"], area_code="RLA-1")
    analyze_area(area["id"])
    area = designate_area(area["id"])
    assert area["property_count"] == 2

    cycle = open_cycle(scenario["community"]["id"], cycle_year=2026)

    resp = api.launch_outreach(
        area["id"], {"crs_cycle_id": cycle["id"], "target_property_count": 1}, _ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_OUTREACH_TARGET_BELOW_ANALYZED)

    after = read_area(area["id"])
    assert after["property_count"] == 2
    assert after["outreach_status"] == "NOT_STARTED"
    assert after["target_property_count"] == 0
    assert after["status"] == "DESIGNATED"


def test_delivery_increment_beyond_the_target_is_rejected(api):
    """PRD §3.9: "The increment is added to `delivered_count`, and a total that would exceed
    `target_property_count` is rejected with `ERR_DELIVERY_EXCEEDS_TARGET`."

    PRD §3.9: "`coverage_pct` is then recomputed as 0.00 when `target_property_count` is 0,
    and otherwise as `delivered_count` divided by `target_property_count`, multiplied by 100,
    rounded half-up to two decimal places."

    Design: Corner/validations/delivery_increment_beyond_the_target_is_rejected
    """
    scenario = setup_outreach_in_progress(
        target_property_count=3,
        area_overrides={"area_code": "RLA-1"},
        community_overrides={"freeboard_ft": 1.5},
        property_overrides={"mapped_area_code": "RLA-1"},
    )
    area_id = scenario["area"]["id"]

    after_first = record_delivery(area_id, 2)
    assert after_first["delivered_count"] == 2
    assert float(after_first["coverage_pct"]) == pytest.approx(66.67, abs=0.01)

    resp = api.record_outreach_delivery(area_id, {"delivered_increment": 2}, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_EXCEEDS_TARGET)

    after = read_area(area_id)
    assert after["delivered_count"] == 2
    assert float(after["coverage_pct"]) == pytest.approx(66.67, abs=0.01)
    assert after["outreach_status"] == "IN_PROGRESS"
