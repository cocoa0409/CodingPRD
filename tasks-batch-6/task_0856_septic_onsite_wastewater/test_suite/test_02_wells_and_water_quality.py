"""Wells, laboratory samples and the four-step groundwater advisory cascade."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_water_sample,
    assert_well,
    create_parcel,
    create_well,
    create_well_payload,
    post_water_sample,
    refresh_operating_permit,
    refresh_parcel,
    refresh_well,
    set_clock,
    setup_operating_parcel,
    unique_apn,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_well_type_outside_the_declared_set_is_malformed(api, applicant_headers):
    """PRD §3.2: "A well is recorded on a parcel by an `Applicant` or a
    `DesignProfessional`, who supply the `parcel_id` it sits on, its `well_type` —
    `DOMESTIC`, `IRRIGATION` or `MONITORING` — its site-plan position as
    `location_x_ft` east-west and `location_y_ft` north-south in feet, and its total
    drilled `depth_ft`, which must be at least 1 foot."
    PRD §2.6: "Any violation is `ERR_INVALID_REQUEST` (HTTP 400), and it applies to
    every operation."

    Design: Corner/entities/corner_create_well_with_invalid_enum_well_type_is_rejected
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-E6"),
        site_address="27 Enum Road",
        lot_size_sqft=20000,
        water_source="PRIVATE_WELL",
    )
    response = api.create_well(
        create_well_payload(parcel["id"], well_type="OBSERVATION", depth_ft=100),
        applicant_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_well_under_an_unknown_parcel_reports_the_parcel_missing(api, applicant_headers):
    """PRD §2.6: "Every foreign key supplied in a request body must resolve to an
    existing row, reported with the same 404 family — `ERR_PARCEL_NOT_FOUND`,
    `ERR_SITE_EVALUATION_NOT_FOUND`, `ERR_SYSTEM_DESIGN_NOT_FOUND`,
    `ERR_CONTRACTOR_NOT_FOUND`, `ERR_CONSTRUCTION_PERMIT_NOT_FOUND` or
    `ERR_OPERATING_PERMIT_NOT_FOUND`."

    Design: Corner/entities/corner_create_well_under_unknown_parcel_returns_not_found
    """
    response = api.create_well(
        create_well_payload(NON_EXISTENT_UUID, depth_ft=100), applicant_headers
    )
    validate_error(response, ApiErrorId.ERR_PARCEL_NOT_FOUND.value, 404)


def test_water_sample_is_immutable_evidence_with_a_server_computed_verdict(
    api, applicant_headers, ehs_field_headers, records_clerk_headers
):
    """PRD §3.2: "Samples are evidence and are never revised; each one is stored with
    an `id` and a `created_at` and nothing else in the way of housekeeping."
    PRD §2.4: "Every persisted record is identified by `id`, a server-minted UUID
    carrying no type prefix and no client-supplied component."

    Design: Corner/entities/corner_water_sample_is_append_only_extra_field_input_ignored
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-E7"),
        site_address="28 Sample Street",
        lot_size_sqft=20000,
        water_source="PRIVATE_WELL",
    )
    well = create_well(
        api, parcel["id"], headers=applicant_headers, location_x_ft=10, location_y_ft=10, depth_ft=100
    )

    response = api.create_water_sample(
        well["id"],
        {
            "collected_at": "2026-05-01T06:00:00Z",
            "nitrate_mg_l": 1.2,
            "coliform_present": False,
        },
        ehs_field_headers,
    )
    sample = validate_success(response, 201)
    assert_water_sample(sample)

    assert sample["result"] == "PASS"
    assert sample["exceedance_reasons"] == []
    assert sample["collected_at"] == "2026-05-01T06:00:00.000Z"
    assert "updated_at" not in sample
    assert "version" not in sample

    _, meta = validate_paginated(api.list_water_samples(well["id"], records_clerk_headers))
    assert meta["total_count"] == 1


def test_nitrate_one_tenth_below_the_contaminant_level_passes(api, applicant_headers, ehs_field_headers):
    """PRD §3.2: "Otherwise, if `nitrate_mg_l` is at or above the maximum contaminant
    level of 10.0 milligrams per litre the result is `EXCEEDANCE`. Otherwise the result
    is `PASS`. The comparison against the contaminant level is inclusive: a reading of
    exactly 10.0 is an `EXCEEDANCE`, while 9.9 is a `PASS`."
    PRD §3.2: "A new well always starts with `advisory_status` of `CLEAR` and with
    `last_sample_collected_at` null."

    Design: Difficulty/boundary_precision_check/nitrate_exactly_at_mcl_is_exceedance_while_one_tenth_below_passes
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-BP1"),
        site_address="12 Aquifer Avenue",
        water_source="PRIVATE_WELL",
    )
    well = create_well(api, parcel["id"], headers=applicant_headers, depth_ft=120)

    sample = validate_success(
        api.create_water_sample(
            well["id"],
            {
                "collected_at": "2026-05-01T08:00:00Z",
                "nitrate_mg_l": 9.9,
                "coliform_present": False,
            },
            ehs_field_headers,
        ),
        201,
    )
    assert sample["result"] == "PASS"
    assert sample["exceedance_reasons"] == []

    assert refresh_well(api, well["id"])["advisory_status"] == "CLEAR"
    assert refresh_parcel(api, parcel["id"])["water_quality_flag"] is False


def test_nitrate_exactly_at_the_contaminant_level_raises_an_advisory(api, applicant_headers, ehs_field_headers):
    """PRD §3.2: "The comparison against the contaminant level is inclusive: a reading
    of exactly 10.0 is an `EXCEEDANCE`, while 9.9 is a `PASS`."
    PRD §3.2: "the nitrate code appears whenever `nitrate_mg_l` is at or above 10.0."
    PRD §3.1: "A parcel scores 40 points when its `water_quality_flag` is true."
    PRD §3.1: "A total of 60 points or more makes the tier `HIGH`; a total of 25 points
    or more, but under 60, makes it `ELEVATED`; anything below 25 leaves it `LOW`."

    Design: Difficulty/boundary_precision_check/nitrate_exactly_at_mcl_is_exceedance_while_one_tenth_below_passes
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-BP1B"),
        site_address="12 Aquifer Avenue",
        water_source="PRIVATE_WELL",
    )
    clear_well = create_well(api, parcel["id"], headers=applicant_headers, depth_ft=120)
    tested_well = create_well(
        api, parcel["id"], headers=applicant_headers, location_x_ft=0, location_y_ft=300, depth_ft=130
    )

    post_water_sample(
        api,
        clear_well["id"],
        headers=ehs_field_headers,
        collected_at="2026-05-01T08:00:00Z",
        nitrate_mg_l=9.9,
        coliform_present=False,
    )
    sample = validate_success(
        api.create_water_sample(
            tested_well["id"],
            {
                "collected_at": "2026-05-01T09:00:00Z",
                "nitrate_mg_l": 10.0,
                "coliform_present": False,
            },
            ehs_field_headers,
        ),
        201,
    )

    assert sample["result"] == "EXCEEDANCE"
    assert sample["exceedance_reasons"] == ["NITRATE_MCL_EXCEEDED"]
    assert refresh_well(api, tested_well["id"])["advisory_status"] == "ADVISORY"
    assert refresh_well(api, clear_well["id"])["advisory_status"] == "CLEAR"

    parcel_now = refresh_parcel(api, parcel["id"])
    assert parcel_now["water_quality_flag"] is True
    assert parcel_now["risk_tier"] == "ELEVATED"


def test_clean_resample_lifts_the_advisory_and_clears_the_parcel_flag(api, applicant_headers, ehs_field_headers, records_clerk_headers):
    """PRD §3.2: "A clean resample lifts an advisory: an `ADVISORY` well that receives
    a `PASS` returns `ADVISORY → CLEAR`."
    PRD §3.2: "and a well returning to `CLEAR` causes the flag to be re-derived across
    *all* the parcel's wells, so it only falls to false when no well on the parcel
    remains under advisory or condemnation, with `risk_tier` re-derived either way."

    Design: Corner/state_machines/corner_clean_resample_clears_well_advisory_and_parcel_water_quality_flag
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-S11"),
        site_address="42 Resample Road",
        water_source="PRIVATE_WELL",
    )
    well = create_well(api, parcel["id"], headers=applicant_headers, depth_ft=110)

    post_water_sample(
        api,
        well["id"],
        headers=ehs_field_headers,
        collected_at="2026-05-01T06:00:00Z",
        nitrate_mg_l=12.0,
        coliform_present=False,
    )
    assert refresh_well(api, well["id"])["advisory_status"] == "ADVISORY"
    after_first = refresh_parcel(api, parcel["id"])
    assert after_first["water_quality_flag"] is True
    assert after_first["risk_tier"] == "ELEVATED"

    clean = post_water_sample(
        api,
        well["id"],
        headers=ehs_field_headers,
        collected_at="2026-05-01T07:00:00Z",
        nitrate_mg_l=1.0,
        coliform_present=False,
    )
    assert clean["result"] == "PASS"

    well_now = refresh_well(api, well["id"])
    assert well_now["advisory_status"] == "CLEAR"
    assert well_now["last_sample_collected_at"] == "2026-05-01T07:00:00.000Z"
    assert_well(well_now)

    parcel_now = refresh_parcel(api, parcel["id"])
    assert parcel_now["water_quality_flag"] is False
    assert parcel_now["risk_tier"] == "LOW"

    _, meta = validate_paginated(api.list_water_samples(well["id"], records_clerk_headers))
    assert meta["total_count"] == 2


def test_cascade_is_settled_before_the_creating_response_is_written(api, applicant_headers, ehs_field_headers, records_clerk_headers):
    """PRD §2.9: "Cascades propagate transitively and are completed within the
    triggering request."
    PRD §3.2: "If `coliform_present` is true the result is `UNSAFE`, whatever the
    nitrate reading."
    PRD §3.2: "A `CLEAR` well that receives an `UNSAFE` moves `CLEAR → CONDEMNED`, and
    an `ADVISORY` well that receives an `UNSAFE` moves `ADVISORY → CONDEMNED`."

    Design: Corner/consistency_model/corner_cascade_results_are_visible_in_the_same_request_that_caused_them
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-M1"),
        site_address="79 Immediate Way",
        water_source="PRIVATE_WELL",
    )
    well = create_well(api, parcel["id"], headers=applicant_headers, depth_ft=110)

    sample = validate_success(
        api.create_water_sample(
            well["id"],
            {
                "collected_at": "2026-05-01T06:00:00Z",
                "nitrate_mg_l": 11.0,
                "coliform_present": True,
            },
            ehs_field_headers,
        ),
        201,
    )
    assert sample["result"] == "UNSAFE", "the verdict is present in the creation response"
    assert sample["exceedance_reasons"] == ["COLIFORM_DETECTED", "NITRATE_MCL_EXCEEDED"]

    well_now = validate_success(api.get_well(well["id"], records_clerk_headers), 200)
    assert well_now["advisory_status"] == "CONDEMNED"

    parcel_now = validate_success(api.get_parcel(parcel["id"], records_clerk_headers), 200)
    assert parcel_now["water_quality_flag"] is True
    assert parcel_now["transfer_hold"] is True
    assert parcel_now["risk_tier"] == "ELEVATED"


def test_unsafe_sample_condemns_the_well_and_flags_the_parcel(api, applicant_headers, ehs_field_headers):
    """PRD §3.2: "If `coliform_present` is true the result is `UNSAFE`, whatever the
    nitrate reading."
    PRD §3.2: "Step two is the parcel: a well entering `ADVISORY` or `CONDEMNED` sets
    the parcel's `water_quality_flag` to true and re-derives `risk_tier`; a well
    entering `CONDEMNED` additionally sets `transfer_hold` to true"
    PRD §3.2: "Posting a sample also stamps the well's `last_sample_collected_at` with
    the sample's `collected_at` and moves the well's advisory posture."

    Design: Difficulty/transitive_cascade/unsafe_water_sample_cascades_well_to_parcel_to_monitoring_to_pumping_compliance
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-TC1"),
        site_address="8 Nitrate Ridge",
        water_source="PRIVATE_WELL",
    )
    well = create_well(api, parcel["id"], headers=applicant_headers, depth_ft=120)
    setup_operating_parcel(api, existing_parcel=parcel, applicant_headers=applicant_headers)
    set_clock(api, "2027-09-01T00:00:00Z")

    sample = validate_success(
        api.create_water_sample(
            well["id"],
            {
                "collected_at": "2027-09-01T00:00:00Z",
                "nitrate_mg_l": 2.5,
                "coliform_present": True,
            },
            ehs_field_headers,
        ),
        201,
    )
    assert sample["result"] == "UNSAFE"
    assert sample["exceedance_reasons"] == ["COLIFORM_DETECTED"]

    well_now = refresh_well(api, well["id"])
    assert well_now["advisory_status"] == "CONDEMNED"
    assert well_now["last_sample_collected_at"] == "2027-09-01T00:00:00.000Z"

    parcel_now = refresh_parcel(api, parcel["id"])
    assert parcel_now["water_quality_flag"] is True
    assert parcel_now["risk_tier"] == "ELEVATED"


def test_condemned_well_halves_the_pumping_interval_and_moves_compliance(api, applicant_headers, ehs_field_headers):
    """PRD §3.2: "Step three reaches the operating permits: once the parcel's flag has
    become true, every operating permit on that parcel whose `status` is `ACTIVE` has
    `monitoring_required` set to true, which halves its `pumping_interval_months` and
    pulls its `next_pumping_due_on` earlier."
    PRD §3.2: "Step four follows from that: because the deadline moved, each affected
    permit has its `compliance_status` re-derived, which may carry it from `COMPLIANT`
    to `DUE_SOON` or, if the newly-shortened deadline has already passed, straight from
    `COMPLIANT` to `DELINQUENT`."
    PRD §3.7: "A change along one dimension never rewrites the other: administratively
    suspending a permit leaves its compliance posture untouched, and a pump-out that
    restores compliance does not reinstate a suspended permit."

    Design: Difficulty/transitive_cascade/unsafe_water_sample_cascades_well_to_parcel_to_monitoring_to_pumping_compliance
    """
    parcel = create_parcel(
        api,
        headers=applicant_headers,
        apn=unique_apn("0856-TC1B"),
        site_address="8 Nitrate Ridge",
        water_source="PRIVATE_WELL",
    )
    well = create_well(api, parcel["id"], headers=applicant_headers, depth_ft=120)
    ctx = setup_operating_parcel(api, existing_parcel=parcel, applicant_headers=applicant_headers)

    before = refresh_operating_permit(api, ctx["operating_permit_id"])
    assert before["pumping_interval_months"] == 36
    assert before["next_pumping_due_on"] == "2029-05-01T00:00:00.000Z"
    assert before["monitoring_required"] is False

    set_clock(api, "2027-09-01T00:00:00Z")
    assert refresh_operating_permit(api, ctx["operating_permit_id"])["compliance_status"] == "COMPLIANT"

    post_water_sample(
        api,
        well["id"],
        headers=ehs_field_headers,
        collected_at="2027-09-01T00:00:00Z",
        nitrate_mg_l=2.5,
        coliform_present=True,
    )

    permit = refresh_operating_permit(api, ctx["operating_permit_id"])
    assert permit["monitoring_required"] is True
    assert permit["pumping_interval_months"] == 18, "36 months halved by the monitoring obligation"
    assert permit["next_pumping_due_on"] == "2027-11-01T00:00:00.000Z"
    assert permit["compliance_status"] == "DUE_SOON"
    assert permit["status"] == "ACTIVE", "the administrative dimension is untouched"
