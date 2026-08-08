"""Sizing the drainfield and clearing the wells: design flow, area and setback."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_drainfield_within_clamp,
    assert_system_design,
    condemn_parcel_well,
    create_active_contractor,
    create_approved_site_evaluation,
    create_parcel,
    create_well,
    draw_design_from_evaluation,
    issue_construction_permit,
    refresh_parcel,
    refresh_site_evaluation,
    refresh_system_design,
    refresh_well,
    set_clock,
    unique_apn,
    unique_license_number,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_certified_rate_sizes_the_drainfield_not_the_preliminary_mean(
    api, applicant_headers, design_professional_headers
):
    """PRD §3.4: "Start with the design flow and divide it by the cited evaluation's
    `soil_loading_rate_gpd_per_sqft`; if that loading rate is null the design cannot be
    sized at all and the soil-suitability refusal applies."
    PRD §3.3: "The certified figure is the only one the soil loading tier and the
    departmental approval gate are permitted to read; the mean is never used for
    sizing."

    Design: Difficulty/dual_variant_calc/perc_rate_preliminary_mean_vs_certified_slowest_hole_select_different_loading_tiers
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-DV1B"),
        site_address="1 Perc Road",
        water_source="PRIVATE_WELL",
    )
    evaluation = create_approved_site_evaluation(
        api,
        parcel["id"],
        holes=[
            {"drop_inches": 6, "elapsed_minutes": 60, "presoak_ok": True},
            {"drop_inches": 6, "elapsed_minutes": 66, "presoak_ok": True},
            {"drop_inches": 6, "elapsed_minutes": 132, "presoak_ok": True},
        ],
        review_note="Soil profile accepted",
    )

    design = validate_success(
        api.create_system_design(
            {
                "site_evaluation_id": evaluation["id"],
                "expected_site_evaluation_version": evaluation["version"],
                "system_type": "CONVENTIONAL",
                "bedrooms": 3,
                "tank_capacity_gal": 1000,
                "drainfield_x_ft": 150,
                "drainfield_y_ft": 0,
            },
            design_professional_headers,
        ),
        201,
    )
    assert design["design_flow_gpd"] == 360
    assert design["required_drainfield_sqft"] == 600, (
        "360 gpd over the certified 0.60 tier is 600 sqft"
    )
    assert design["required_drainfield_sqft"] != 450, (
        "450 is the answer the preliminary mean would have produced and must not appear"
    )
    assert_drainfield_within_clamp(design)


def test_drainfield_area_applies_technology_and_shallow_soil_multipliers_in_order(api, applicant_headers):
    """PRD §3.4: "Multiply the quotient by the technology multiplier for the chosen
    `system_type`: 1.00 for `CONVENTIONAL`, 1.25 for `MOUND`, 0.75 for `ATU` and 0.85
    for `DRIP`. Multiply that product by the shallow-soil penalty, which is 1.20 when
    the evaluation's `depth_to_limiting_layer_in` is strictly less than 36 inches and
    1.00 otherwise."
    PRD §3.4: "The three steps happen in exactly that order — divide by the loading
    rate, then apply the technology multiplier, then apply the shallow-soil penalty —
    and in exact decimal arithmetic per §2.8."

    Design: Difficulty/combinatorial_formula/drainfield_area_four_input_nonlinear_with_shallow_penalty_and_clamp
    """
    parcel = create_parcel(
        api, headers=applicant_headers, apn=unique_apn("0856-CF1"), site_address="3 Mound Way"
    )
    evaluation = create_approved_site_evaluation(
        api,
        parcel["id"],
        holes=[{"drop_inches": 6, "elapsed_minutes": 72, "presoak_ok": True}],
        soil_group="CLAY_LOAM",
        depth_to_limiting_layer_in=30,
    )
    design = draw_design_from_evaluation(
        api,
        evaluation["id"],
        system_type="MOUND",
        bedrooms=4,
        tank_capacity_gal=1250,
        drainfield_x_ft=200,
        drainfield_y_ft=0,
    )

    assert design["required_drainfield_sqft"] == 900, (
        "480 / 0.80 is 600, times the 1.25 MOUND factor is 750, times the 1.20 shallow "
        "penalty is 900"
    )
    assert_drainfield_within_clamp(design)
    assert_system_design(design)


def test_drainfield_sizing_reads_the_tier_flow_and_setback_posture_together(api, applicant_headers):
    """PRD §3.3: "Above 5 and at or below 15, it loads at 0.80."
    PRD §3.4: "`design_flow_gpd` is the bedroom count, floored at a minimum of 2
    billable bedrooms, multiplied by 120 gallons per day per bedroom."
    PRD §3.4: "When the parcel carries no qualifying well, `nearest_well_distance_ft`
    is null and `setback_status` is `NOT_APPLICABLE`."

    Design: Difficulty/combinatorial_formula/drainfield_area_four_input_nonlinear_with_shallow_penalty_and_clamp
    """
    parcel = create_parcel(
        api, headers=applicant_headers, apn=unique_apn("0856-CF1B"), site_address="3 Mound Way"
    )
    evaluation = create_approved_site_evaluation(
        api,
        parcel["id"],
        holes=[{"drop_inches": 6, "elapsed_minutes": 72, "presoak_ok": True}],
        soil_group="CLAY_LOAM",
        depth_to_limiting_layer_in=30,
    )
    assert evaluation["certified_perc_rate_min_per_in"] == pytest.approx(12.0)
    assert evaluation["soil_loading_rate_gpd_per_sqft"] == pytest.approx(0.8)

    design = draw_design_from_evaluation(
        api,
        evaluation["id"],
        system_type="MOUND",
        bedrooms=4,
        tank_capacity_gal=1250,
        drainfield_x_ft=200,
        drainfield_y_ft=0,
    )
    assert design["design_flow_gpd"] == 480
    assert design["setback_status"] == "NOT_APPLICABLE"
    assert design["nearest_well_distance_ft"] is None


def test_design_flow_floors_a_one_bedroom_dwelling_at_two_bedrooms(api, applicant_headers):
    """PRD §3.4: "`design_flow_gpd` is the bedroom count, floored at a minimum of 2
    billable bedrooms, multiplied by 120 gallons per day per bedroom. A one-bedroom
    cottage is therefore sized as though it had two bedrooms, at 240 gallons per day;
    a four-bedroom house is sized at 480."

    Design: Corner/calculations/corner_design_flow_floors_at_two_bedrooms_for_a_one_bedroom_dwelling
    """
    parcel = create_parcel(
        api, headers=applicant_headers, apn=unique_apn("0856-C1"), site_address="45 Studio Street"
    )
    evaluation = create_approved_site_evaluation(api, parcel["id"])
    design = draw_design_from_evaluation(api, evaluation["id"], bedrooms=1)

    assert design["design_flow_gpd"] == 240, "the one-bedroom cottage bills as two bedrooms"
    assert design["required_drainfield_sqft"] == 400, "240 gpd over the 0.60 tier"


def test_sandy_soil_adds_a_setback_surcharge_to_every_technology(api, applicant_headers):
    """PRD §3.4: "The `required_setback_ft` is a base figure keyed on the technology —
    100 feet for `CONVENTIONAL`, 100 for `MOUND`, 75 for `ATU` and 75 for `DRIP` — plus
    a surcharge of 25 feet when the cited evaluation's `soil_group` is `SANDY`, because
    sand transmits effluent laterally."
    PRD §3.4: "If that nearest distance is at or above `required_setback_ft` the posture
    is `COMPLIANT`; the comparison is inclusive, so a well sitting exactly on the
    required separation clears. If it falls short, the posture is `VARIANCE_REQUIRED`."

    Design: Corner/calculations/corner_sandy_soil_adds_twenty_five_foot_setback_surcharge_to_every_system_type
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-C4"),
        site_address="49 Sand Spit",
        water_source="PRIVATE_WELL",
    )
    create_well(api, parcel["id"], headers=applicant_headers, depth_ft=100)
    evaluation = create_approved_site_evaluation(
        api,
        parcel["id"],
        holes=[{"drop_inches": 6, "elapsed_minutes": 24, "presoak_ok": True}],
        soil_group="SANDY",
    )
    assert evaluation["soil_loading_rate_gpd_per_sqft"] == pytest.approx(1.2)

    drip = draw_design_from_evaluation(
        api, evaluation["id"], system_type="DRIP", drainfield_x_ft=90, drainfield_y_ft=0
    )
    conventional = draw_design_from_evaluation(
        api, evaluation["id"], system_type="CONVENTIONAL", drainfield_x_ft=130, drainfield_y_ft=0
    )

    assert drip["required_setback_ft"] == pytest.approx(100.0), "75 base plus the 25 sandy surcharge"
    assert drip["nearest_well_distance_ft"] == pytest.approx(90.0)
    assert drip["setback_status"] == "VARIANCE_REQUIRED"
    assert drip["required_drainfield_sqft"] == 255

    assert conventional["required_setback_ft"] == pytest.approx(125.0)
    assert conventional["nearest_well_distance_ft"] == pytest.approx(130.0)
    assert conventional["setback_status"] == "COMPLIANT"


def test_monitoring_wells_are_ignored_by_the_setback_rule(api, applicant_headers, records_clerk_headers):
    """PRD §3.4: "Only wells on the design's parcel whose `well_type` is `DOMESTIC` or
    `IRRIGATION` qualify; `MONITORING` wells are ignored by this rule entirely."
    PRD §3.4: "the register computes the straight-line site-plan distance from the
    drainfield centroid to each qualifying well head — the square root of the sum of the
    squared east-west and squared north-south coordinate differences — rounds each
    distance half up to two decimal places, and takes the smallest as
    `nearest_well_distance_ft`."

    Design: Corner/calculations/corner_monitoring_wells_are_excluded_from_the_setback_candidate_set
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-C5"),
        site_address="50 Monitor Mews",
        water_source="PRIVATE_WELL",
    )
    create_well(
        api,
        parcel["id"],
        headers=applicant_headers,
        well_type="MONITORING",
        location_x_ft=10,
        location_y_ft=0,
        depth_ft=40,
    )
    create_well(
        api,
        parcel["id"],
        headers=applicant_headers,
        well_type="DOMESTIC",
        location_x_ft=200,
        location_y_ft=0,
        depth_ft=120,
    )
    evaluation = create_approved_site_evaluation(api, parcel["id"])
    design = draw_design_from_evaluation(
        api, evaluation["id"], drainfield_x_ft=0, drainfield_y_ft=0
    )

    assert design["nearest_well_distance_ft"] == pytest.approx(200.0), (
        "the 10 ft monitoring well is outside the candidate set"
    )
    assert design["setback_status"] == "COMPLIANT"

    _, meta = validate_paginated(api.list_parcel_wells(parcel["id"], records_clerk_headers))
    assert meta["total_count"] == 2


def test_drainfield_area_is_clamped_at_four_thousand_square_feet(api, applicant_headers):
    """PRD §3.4: "Round the result *up* to the next whole square foot, and only then
    clamp it: never below 150 square feet and never above 4000. The clamp is applied
    last, after both multipliers."
    PRD §3.3: "Above 60 and at or below 120, at 0.20."

    Design: Corner/calculations/corner_drainfield_area_max_clamp_binds_at_four_thousand_sqft
    """
    parcel = create_parcel(
        api, headers=applicant_headers, apn=unique_apn("0856-C6"), site_address="51 Clamp Close"
    )
    evaluation = create_approved_site_evaluation(
        api,
        parcel["id"],
        holes=[{"drop_inches": 6, "elapsed_minutes": 450, "presoak_ok": True}],
        soil_group="CLAY_LOAM",
        depth_to_limiting_layer_in=24,
    )
    assert evaluation["certified_perc_rate_min_per_in"] == pytest.approx(75.0)
    assert evaluation["soil_loading_rate_gpd_per_sqft"] == pytest.approx(0.2)

    design = draw_design_from_evaluation(
        api,
        evaluation["id"],
        system_type="MOUND",
        bedrooms=8,
        tank_capacity_gal=2000,
        drainfield_x_ft=300,
        drainfield_y_ft=0,
    )
    assert design["design_flow_gpd"] == 960
    assert design["required_drainfield_sqft"] == 4000, (
        "the raw 7200 sqft is cut to the 4000 sqft ceiling only after both multipliers"
    )


def test_setback_exactly_on_the_required_separation_is_compliant(api, applicant_headers):
    """PRD §3.4: "If that nearest distance is at or above `required_setback_ft` the
    posture is `COMPLIANT`; the comparison is inclusive, so a well sitting exactly on
    the required separation clears. If it falls short, the posture is
    `VARIANCE_REQUIRED`."

    Design: Difficulty/boundary_precision_check/setback_distance_exactly_equal_to_requirement_is_compliant_half_foot_short_is_not
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-BP2"),
        site_address="13 Separation Road",
        water_source="PRIVATE_WELL",
    )
    create_well(api, parcel["id"], headers=applicant_headers, depth_ft=120)
    evaluation = create_approved_site_evaluation(api, parcel["id"], soil_group="LOAMY")

    design = draw_design_from_evaluation(
        api, evaluation["id"], drainfield_x_ft=100, drainfield_y_ft=0
    )
    assert design["nearest_well_distance_ft"] == pytest.approx(100.0)
    assert design["required_setback_ft"] == pytest.approx(100.0)
    assert design["setback_status"] == "COMPLIANT"


def test_setback_half_a_foot_short_requires_a_variance(api, applicant_headers):
    """PRD §3.4: "If it falls short, the posture is `VARIANCE_REQUIRED`."
    PRD §3.4: "The `required_setback_ft` is a base figure keyed on the technology — 100
    feet for `CONVENTIONAL`, 100 for `MOUND`, 75 for `ATU` and 75 for `DRIP` — plus a
    surcharge of 25 feet when the cited evaluation's `soil_group` is `SANDY`, because
    sand transmits effluent laterally."

    Design: Difficulty/boundary_precision_check/setback_distance_exactly_equal_to_requirement_is_compliant_half_foot_short_is_not
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-BP2B"),
        site_address="13 Separation Road",
        water_source="PRIVATE_WELL",
    )
    create_well(api, parcel["id"], headers=applicant_headers, depth_ft=120)
    evaluation = create_approved_site_evaluation(api, parcel["id"], soil_group="LOAMY")

    design = draw_design_from_evaluation(
        api, evaluation["id"], drainfield_x_ft=99.5, drainfield_y_ft=0
    )
    assert design["nearest_well_distance_ft"] == pytest.approx(99.5)
    assert design["required_setback_ft"] == pytest.approx(100.0)
    assert design["setback_status"] == "VARIANCE_REQUIRED"


def test_design_revision_loop_reenters_review_and_records_the_approver_only_at_the_end(
    api, applicant_headers, design_professional_headers, ehs_reviewer_headers
):
    """PRD §3.4: "Requesting revisions moves `UNDER_REVIEW → REVISIONS_REQUIRED` with no
    preconditions and changes nothing but the status, `updated_at` and `version` — the
    design keeps its computed sizing until the next submission recomputes it."
    PRD §3.4: "Approval stores the reviewer's `X-User-ID` into `review_ehs_user_id`;
    this single field is the anchor of the segregation-of-duties control described in
    §3.6."
    PRD §3.4: "On success the register recomputes `design_flow_gpd`,
    `required_drainfield_sqft`, `nearest_well_distance_ft`, `required_setback_ft` and
    `setback_status`, and increments `revision_round` by 1."

    Design: Corner/state_machines/corner_system_design_request_revisions_then_resubmit_reenters_under_review
    """
    parcel = create_parcel(
        api, headers=applicant_headers, apn=unique_apn("0856-S5"), site_address="36 Revision Row"
    )
    evaluation = create_approved_site_evaluation(api, parcel["id"])
    design = draw_design_from_evaluation(api, evaluation["id"], system_type="ATU")
    assert design["review_ehs_user_id"] is None
    assert design["revision_round"] == 0

    validate_success(api.submit_system_design(design["id"], design_professional_headers), 200)
    sent_back = validate_success(
        api.review_system_design(
            design["id"], {"decision": "REQUEST_REVISIONS"}, ehs_reviewer_headers
        ),
        200,
    )
    assert sent_back["status"] == "REVISIONS_REQUIRED"
    assert sent_back["review_ehs_user_id"] is None

    validate_success(api.submit_system_design(design["id"], design_professional_headers), 200)
    approved = validate_success(
        api.review_system_design(design["id"], {"decision": "APPROVE"}, ehs_reviewer_headers), 200
    )

    assert approved["status"] == "APPROVED"
    assert approved["revision_round"] == 2
    assert approved["review_ehs_user_id"] == "u-ehs-review"
    assert approved["required_drainfield_sqft"] == 450, "360 gpd over 0.60 times the 0.75 ATU factor"


def test_granted_variance_is_sticky_and_adds_the_variance_fee_line(
    api, applicant_headers, design_professional_headers, ehs_reviewer_headers, health_officer_headers
):
    """PRD §3.4: "Granting moves the posture `VARIANCE_REQUIRED → VARIANCE_GRANTED` and
    adds a variance line item to the eventual construction-permit fee."
    PRD §3.4: "A variance verdict, once recorded, is **sticky**. Neither an ordinary
    resubmission of the design nor any other recomputation moves `setback_status` away
    from `VARIANCE_GRANTED` or `VARIANCE_DENIED`; the recomputation on submit re-derives
    distance and required separation but leaves a granted or denied verdict standing."
    PRD §3.5: "The fourth is a variance charge of 15000 cents, applied only when the
    design's `setback_status` is `VARIANCE_GRANTED` at the instant of issue, and zero
    otherwise."

    Design: Corner/state_machines/corner_setback_variance_grant_unblocks_design_approval_and_adds_permit_fee_line
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-S6"),
        site_address="37 Variance Vale",
        water_source="PRIVATE_WELL",
    )
    create_well(api, parcel["id"], headers=applicant_headers, depth_ft=110)
    evaluation = create_approved_site_evaluation(api, parcel["id"])
    design = draw_design_from_evaluation(
        api, evaluation["id"], drainfield_x_ft=80, drainfield_y_ft=0
    )
    contractor = create_active_contractor(
        api, license_number=unique_license_number("LIC-0856-P"), business_name="Variance Septic"
    )

    assert design["nearest_well_distance_ft"] == pytest.approx(80.0)
    assert design["required_setback_ft"] == pytest.approx(100.0)
    assert design["setback_status"] == "VARIANCE_REQUIRED"

    granted = validate_success(
        api.variance_decision(design["id"], {"decision": "GRANT"}, health_officer_headers), 200
    )
    assert granted["setback_status"] == "VARIANCE_GRANTED"

    submitted = validate_success(
        api.submit_system_design(design["id"], design_professional_headers), 200
    )
    assert submitted["setback_status"] == "VARIANCE_GRANTED", "the submit must not reset the verdict"

    validate_success(
        api.review_system_design(design["id"], {"decision": "APPROVE"}, ehs_reviewer_headers), 200
    )
    permit = issue_construction_permit(api, design["id"], contractor["id"])

    assert refresh_system_design(api, design["id"])["status"] == "PERMITTED"
    assert permit["fee_cents"] == 89031, "73018 plus the 16013-cent loaded variance line"
    assert refresh_parcel(api, parcel["id"])["fees_assessed_cents"] == 89031


def test_denied_variance_returns_an_under_review_design_to_revisions(
    api, applicant_headers, design_professional_headers, health_officer_headers
):
    """PRD §3.4: "Denying moves it `VARIANCE_REQUIRED → VARIANCE_DENIED`, which is
    terminal for that dimension, and carries one further consequence: if the design
    happened to be `UNDER_REVIEW` at that moment, it is also returned `UNDER_REVIEW →
    REVISIONS_REQUIRED`, since the reviewer can no longer approve it."
    PRD §3.4: "and the design's `setback_status` must not be `VARIANCE_DENIED`, else
    `ERR_SETBACK_VIOLATION`."

    Design: Corner/state_machines/corner_setback_variance_denial_pushes_under_review_design_back_to_revisions
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-S7"),
        site_address="38 Denial Drive",
        water_source="PRIVATE_WELL",
    )
    create_well(api, parcel["id"], headers=applicant_headers, depth_ft=110)
    evaluation = create_approved_site_evaluation(api, parcel["id"])
    design = draw_design_from_evaluation(
        api, evaluation["id"], drainfield_x_ft=80, drainfield_y_ft=0
    )
    validate_success(api.submit_system_design(design["id"], design_professional_headers), 200)

    denied = validate_success(
        api.variance_decision(design["id"], {"decision": "DENY"}, health_officer_headers), 200
    )
    assert denied["setback_status"] == "VARIANCE_DENIED"
    assert denied["status"] == "REVISIONS_REQUIRED"

    refused = api.submit_system_design(design["id"], design_professional_headers)
    validate_error(refused, ApiErrorId.ERR_SETBACK_VIOLATION.value, 422)
    assert refresh_system_design(api, design["id"])["revision_round"] == 1


def test_water_quality_hold_bars_a_grant_but_not_a_denial(api, applicant_headers, health_officer_headers):
    """PRD §3.4: "A grant is additionally barred while the parcel's
    `water_quality_flag` is true — the department will not relax a well separation on a
    parcel whose groundwater is already suspect — and that refusal is
    `ERR_WATER_QUALITY_HOLD`."
    PRD §3.4: "A denial is not subject to the water-quality bar."

    Design: Corner/validations/corner_water_quality_hold_blocks_setback_variance_grant
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-V5"),
        site_address="58 Hold Hill",
        water_source="PRIVATE_WELL",
    )
    well = create_well(api, parcel["id"], headers=applicant_headers, depth_ft=110)
    condemn_parcel_well(api, well["id"])
    evaluation = create_approved_site_evaluation(api, parcel["id"])
    design = draw_design_from_evaluation(
        api, evaluation["id"], drainfield_x_ft=80, drainfield_y_ft=0
    )

    assert refresh_well(api, well["id"])["advisory_status"] == "CONDEMNED"
    assert refresh_parcel(api, parcel["id"])["water_quality_flag"] is True

    refused = api.variance_decision(design["id"], {"decision": "GRANT"}, health_officer_headers)
    validate_error(refused, ApiErrorId.ERR_WATER_QUALITY_HOLD.value, 422)
    assert refresh_system_design(api, design["id"])["setback_status"] == "VARIANCE_REQUIRED"

    denied = validate_success(
        api.variance_decision(design["id"], {"decision": "DENY"}, health_officer_headers), 200
    )
    assert denied["setback_status"] == "VARIANCE_DENIED"


def test_lapsed_site_evaluation_blocks_a_design_submit(api, applicant_headers, design_professional_headers):
    """PRD §3.4: "Three preconditions guard the submission: the cited evaluation's status
    must be `APPROVED`, else `ERR_SITE_EVALUATION_NOT_APPROVED`; the logical clock must
    stand at or before that evaluation's `valid_until`, else
    `ERR_SITE_EVALUATION_EXPIRED`; and the design's `setback_status` must not be
    `VARIANCE_DENIED`, else `ERR_SETBACK_VIOLATION`."
    PRD §3.3: "A design may cite this evaluation only while the logical clock stands at
    or before `valid_until`."

    Design: Corner/validations/corner_expired_site_evaluation_blocks_design_submit
    """
    parcel = create_parcel(
        api, headers=applicant_headers, apn=unique_apn("0856-V4"), site_address="57 Stale Site"
    )
    evaluation = create_approved_site_evaluation(api, parcel["id"])
    design = draw_design_from_evaluation(api, evaluation["id"])
    set_clock(api, "2031-05-01T00:00:00Z")

    refused = api.submit_system_design(design["id"], design_professional_headers)
    validate_error(refused, ApiErrorId.ERR_SITE_EVALUATION_EXPIRED.value, 409)

    evaluation_now = refresh_site_evaluation(api, evaluation["id"])
    assert evaluation_now["valid_until"] == "2031-04-15T00:00:00.000Z"
    assert evaluation_now["status"] == "APPROVED"

    design_now = refresh_system_design(api, design["id"])
    assert design_now["status"] == "DRAFT"
    assert design_now["revision_round"] == 0
