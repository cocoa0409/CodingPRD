"""Stale-read protection and the fixed order in which a request is refused."""

import pytest

from test_helpers import (
    ApiErrorId,
    create_active_contractor,
    create_approved_site_evaluation,
    create_approved_system_design,
    create_parcel,
    create_system_design_payload,
    create_transfer_inspection_payload,
    create_well,
    draw_design_from_evaluation,
    refresh_parcel,
    refresh_site_evaluation,
    refresh_system_design,
    setup_operating_parcel,
    setup_permitted_parcel,
    unique_apn,
    unique_license_number,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_replayed_site_evaluation_version_is_a_stale_read(api, applicant_headers, design_professional_headers):
    """PRD §2.7: "Drawing a system design must carry
    `expected_site_evaluation_version`, a non-optional field holding the `version` of
    the cited site evaluation as the client last observed it. If that number does not
    equal the evaluation's current `version`, the creation is rejected with
    `ERR_STALE_SITE_EVALUATION_VERSION` and HTTP 412."
    PRD §2.7: "A successful draw itself advances the evaluation's `version` by 1, so two
    designs drawn back to back from one evaluation require the second client to re-read
    the evaluation first."

    Design: Corner/cross_cutting_layers/corner_stale_site_evaluation_version_on_design_create_is_rejected
    """
    parcel = create_parcel(
        api, headers=applicant_headers, apn=unique_apn("0856-L1"), site_address="76 Stale Street"
    )
    evaluation = create_approved_site_evaluation(api, parcel["id"])
    observed_version = evaluation["version"]

    first = validate_success(
        api.create_system_design(
            create_system_design_payload(evaluation["id"], observed_version),
            design_professional_headers,
        ),
        201,
    )

    replayed = api.create_system_design(
        create_system_design_payload(
            evaluation["id"],
            observed_version,
            system_type="MOUND",
            drainfield_x_ft=160,
            drainfield_y_ft=0,
        ),
        design_professional_headers,
    )
    validate_error(replayed, ApiErrorId.ERR_STALE_SITE_EVALUATION_VERSION.value, 412)

    refreshed_version = refresh_site_evaluation(api, evaluation["id"])["version"]
    second = validate_success(
        api.create_system_design(
            create_system_design_payload(
                evaluation["id"],
                refreshed_version,
                system_type="MOUND",
                drainfield_x_ft=160,
                drainfield_y_ft=0,
            ),
            design_professional_headers,
        ),
        201,
    )
    assert second["system_type"] == "MOUND"

    _, meta = validate_paginated(
        api.list_evaluation_system_designs(evaluation["id"], design_professional_headers)
    )
    assert meta["total_count"] == 2
    assert first["id"] != second["id"]


def test_parcel_version_advanced_by_a_payment_invalidates_a_transfer_request(api, applicant_headers):
    """PRD §2.7: "Requesting a transfer inspection must carry `expected_parcel_version`,
    a non-optional field holding the `version` of the cited parcel as the client last
    observed it. A mismatch against the parcel's current `version` is rejected with
    `ERR_STALE_PARCEL_VERSION` and HTTP 412."
    PRD §2.7: "A successful request advances the parcel's `version` by 1."

    Design: Corner/cross_cutting_layers/corner_stale_parcel_version_on_transfer_request_is_rejected
    """
    ctx = setup_operating_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-L2"),
        site_address="77 Version Vale",
    )
    stale_version = refresh_parcel(api, ctx["parcel_id"], applicant_headers)["version"]
    after_payment = validate_success(
        api.record_fee_payment(ctx["parcel_id"], {"amount_cents": 73018}, applicant_headers), 200
    )
    fresh_version = after_payment["version"]
    assert fresh_version > stale_version

    stale_request = api.create_transfer_inspection(
        create_transfer_inspection_payload(
            ctx["parcel_id"],
            ctx["operating_permit_id"],
            stale_version,
            requested_on="2026-05-03T00:00:00Z",
            buyer_name="Buyer Eleven",
            seller_name="Seller Eleven",
            inspection_mode="DESK_REVIEW",
        ),
        applicant_headers,
    )
    validate_error(stale_request, ApiErrorId.ERR_STALE_PARCEL_VERSION.value, 412)

    _, meta = validate_paginated(
        api.list_transfer_inspections(applicant_headers, params={"parcel_id": ctx["parcel_id"]})
    )
    assert meta["total_count"] == 0, "a stale request creates no row"

    accepted = validate_success(
        api.create_transfer_inspection(
            create_transfer_inspection_payload(
                ctx["parcel_id"],
                ctx["operating_permit_id"],
                fresh_version,
                requested_on="2026-05-03T00:00:00Z",
                buyer_name="Buyer Eleven",
                seller_name="Seller Eleven",
                inspection_mode="DESK_REVIEW",
            ),
            applicant_headers,
        ),
        201,
    )
    assert accepted["status"] == "REQUESTED"
    assert refresh_parcel(api, ctx["parcel_id"], applicant_headers)["version"] > fresh_version


def test_design_state_gate_is_reported_before_the_hydraulic_cap(api, applicant_headers, design_professional_headers, health_officer_headers):
    """PRD §3.5: "The cited design must be `APPROVED`, else `ERR_DESIGN_NOT_APPROVED` —
    which also excludes a design already carrying a live permit, since that design would
    be `PERMITTED`."
    PRD §2.6: "Then the cross-entity state gates run (HTTP 409 throughout): a design
    submit requires its cited site evaluation to be `APPROVED`
    (`ERR_SITE_EVALUATION_NOT_APPROVED`); a construction permit requires its cited design
    to be `APPROVED` (`ERR_DESIGN_NOT_APPROVED`); an operating permit requires its cited
    construction permit to be `COMPLETED` (`ERR_CONSTRUCTION_NOT_COMPLETED`); a transfer
    certification requires its cited operating permit to be `ACTIVE`, and a repair-order
    issue requires its cited operating permit to be `ACTIVE` or `SUSPENDED`
    (`ERR_OPERATING_PERMIT_NOT_ACTIVE`); and recording an inspection result requires the
    permit's contractor to have an `effective_status` of `ACTIVE`
    (`ERR_CONTRACTOR_NOT_ACTIVE`)."

    Design: Difficulty/priority_pair_validation_conflict/design_not_approved_state_gate_outranks_parcel_flow_cap_fiscal_gate
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-PP1"),
        site_address="10 Tiny Lot",
        lot_size_sqft=4000,
    )
    assert parcel["max_design_flow_gpd"] == 200

    evaluation = create_approved_site_evaluation(api, parcel["id"])
    design = draw_design_from_evaluation(api, evaluation["id"])
    validate_success(api.submit_system_design(design["id"], design_professional_headers), 200)
    assert refresh_system_design(api, design["id"])["status"] == "UNDER_REVIEW"
    assert design["design_flow_gpd"] == 360

    contractor = create_active_contractor(
        api, license_number=unique_license_number("LIC-0856-G")
    )
    refused = api.create_construction_permit(
        {
            "system_design_id": design["id"],
            "contractor_id": contractor["id"],
            "valid_from": "2026-05-01T00:00:00Z",
            "valid_until": "2027-05-01T00:00:00Z",
        },
        health_officer_headers,
    )
    validate_error(refused, ApiErrorId.ERR_DESIGN_NOT_APPROVED.value, 409)


def test_hydraulic_cap_surfaces_once_the_design_state_gate_is_satisfied(
    api, applicant_headers, design_professional_headers, ehs_reviewer_headers, health_officer_headers
):
    """PRD §3.5: "The **hydraulic headroom** rule compares the parcel's current
    `permitted_design_flow_gpd` plus the new design's `design_flow_gpd` against the
    parcel's `max_design_flow_gpd`; if the sum would exceed the allowance the issue is
    refused. A sum exactly equal to the allowance is permitted."
    PRD §2.6: "and a parcel's aggregate hydraulic capacity must not be exceeded
    (`ERR_DESIGN_FLOW_EXCEEDS_PARCEL_CAP`, on construction-permit issue)."

    Design: Difficulty/priority_pair_validation_conflict/design_not_approved_state_gate_outranks_parcel_flow_cap_fiscal_gate
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-PP1B"),
        site_address="10 Tiny Lot",
        lot_size_sqft=4000,
    )
    evaluation = create_approved_site_evaluation(api, parcel["id"])
    design = draw_design_from_evaluation(api, evaluation["id"])
    validate_success(api.submit_system_design(design["id"], design_professional_headers), 200)
    contractor = create_active_contractor(
        api, license_number=unique_license_number("LIC-0856-G")
    )
    validate_error(
        api.create_construction_permit(
            {
                "system_design_id": design["id"],
                "contractor_id": contractor["id"],
                "valid_from": "2026-05-01T00:00:00Z",
                "valid_until": "2027-05-01T00:00:00Z",
            },
            health_officer_headers,
        ),
        ApiErrorId.ERR_DESIGN_NOT_APPROVED.value,
        409,
    )

    validate_success(
        api.review_system_design(design["id"], {"decision": "APPROVE"}, ehs_reviewer_headers), 200
    )
    refused = api.create_construction_permit(
        {
            "system_design_id": design["id"],
            "contractor_id": contractor["id"],
            "valid_from": "2026-05-01T00:00:00Z",
            "valid_until": "2027-05-01T00:00:00Z",
        },
        health_officer_headers,
    )
    validate_error(refused, ApiErrorId.ERR_DESIGN_FLOW_EXCEEDS_PARCEL_CAP.value, 422)

    parcel_now = refresh_parcel(api, parcel["id"])
    assert parcel_now["max_design_flow_gpd"] == 200
    assert parcel_now["permitted_design_flow_gpd"] == 0
    assert parcel_now["fees_assessed_cents"] == 0


def test_setback_safety_gate_outranks_the_parcel_window_conflict(api, applicant_headers, health_officer_headers):
    """PRD §2.6: "**Checks 13, 14 and 15 — engineering safety**, all HTTP 422. Soil
    suitability (`ERR_SOIL_UNSUITABLE`) guards the site-evaluation review decision and
    the system-design review decision. Well setback (`ERR_SETBACK_VIOLATION`) guards
    three operations: design submit, design review and construction-permit issue."
    PRD §3.5: "The design's `setback_status` must not be `VARIANCE_REQUIRED` or
    `VARIANCE_DENIED`, else `ERR_SETBACK_VIOLATION`."

    Design: Difficulty/priority_pair_validation_conflict/setback_safety_gate_outranks_parcel_window_temporal_gate_on_permit_issue
    """
    ctx = setup_permitted_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-PP2"),
        site_address="11 Setback Street",
        water_source="PRIVATE_WELL",
        drainfield_x_ft=400,
        drainfield_y_ft=0,
        permit_valid_from="2026-06-01T00:00:00Z",
        permit_valid_until="2026-12-01T00:00:00Z",
    )
    second_design = create_approved_system_design(
        api, ctx["site_evaluation_id"], drainfield_x_ft=150, drainfield_y_ft=0
    )
    create_well(
        api,
        ctx["parcel_id"],
        headers=applicant_headers,
        location_x_ft=100,
        location_y_ft=0,
        depth_ft=140,
    )

    refused = api.create_construction_permit(
        {
            "system_design_id": second_design["id"],
            "contractor_id": ctx["contractor_id"],
            "valid_from": "2026-09-01T00:00:00Z",
            "valid_until": "2027-03-01T00:00:00Z",
        },
        health_officer_headers,
    )
    validate_error(refused, ApiErrorId.ERR_SETBACK_VIOLATION.value, 422)
    assert refused.json()["data"]["error_id"] != ApiErrorId.ERR_PERMIT_WINDOW_CONFLICT.value


def test_recording_a_well_rederives_approved_designs_but_not_permitted_ones(api, applicant_headers):
    """PRD §3.2: "The moment a well is recorded, every system design on that parcel whose
    status is `DRAFT`, `UNDER_REVIEW`, `REVISIONS_REQUIRED` or `APPROVED` has its
    `nearest_well_distance_ft`, `required_setback_ft` and `setback_status` re-derived
    from scratch."
    PRD §3.2: "Designs already in `PERMITTED` or `SUPERSEDED` are left untouched."

    Design: Difficulty/priority_pair_validation_conflict/setback_safety_gate_outranks_parcel_window_temporal_gate_on_permit_issue
    """
    ctx = setup_permitted_parcel(
        api,
        applicant_headers=applicant_headers,
        apn=unique_apn("0856-PP2B"),
        site_address="11 Setback Street",
        water_source="PRIVATE_WELL",
        drainfield_x_ft=400,
        drainfield_y_ft=0,
        permit_valid_from="2026-06-01T00:00:00Z",
        permit_valid_until="2026-12-01T00:00:00Z",
    )
    second_design = create_approved_system_design(
        api, ctx["site_evaluation_id"], drainfield_x_ft=150, drainfield_y_ft=0
    )
    assert second_design["setback_status"] == "NOT_APPLICABLE"

    create_well(
        api,
        ctx["parcel_id"],
        headers=applicant_headers,
        location_x_ft=100,
        location_y_ft=0,
        depth_ft=140,
    )

    redrawn = refresh_system_design(api, second_design["id"])
    assert redrawn["nearest_well_distance_ft"] == pytest.approx(50.0)
    assert redrawn["required_setback_ft"] == pytest.approx(100.0)
    assert redrawn["setback_status"] == "VARIANCE_REQUIRED"

    permitted = refresh_system_design(api, ctx["system_design_id"])
    assert permitted["status"] == "PERMITTED"
    assert permitted["setback_status"] == "NOT_APPLICABLE", (
        "a PERMITTED design is left untouched by the arrival of a new well"
    )
    assert refresh_parcel(api, ctx["parcel_id"])["permitted_design_flow_gpd"] == 360
