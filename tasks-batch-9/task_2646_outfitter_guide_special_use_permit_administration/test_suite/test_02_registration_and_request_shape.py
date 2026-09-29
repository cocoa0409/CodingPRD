"""Registering the program's records and policing the shape of a request.

Covers the stored registration read-back, the twelve per-collection existence
errors, the required-field rejection, and the declared input defaults.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_identity_fields,
    create_use_area,
    create_outfitter,
    guide_payload,
    outfitter_payload,
    permit_application_payload,
    set_clock,
    use_area_payload,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
    TEST_USERS,
    make_outfitter_representative_headers,
)

ADMIN = TEST_USERS["program_administrator_headers"]
SPECIALIST = TEST_USERS["permit_specialist_headers"]
OFFICER = TEST_USERS["authorized_officer_headers"]


def test_outfitter_read_returns_the_stored_registration_and_its_derived_zeroes():
    """PRD §3.1: "A prospective holder enters the system as an `Outfitter`, registered by a
    `PermitSpecialist` or a `ProgramAdministrator` with its `legal_name`, its `ein` — exactly
    nine digits, and unique across all outfitters, a collision being an `ERR_INVALID_REQUEST`
    — and its `contact_email` for permit correspondence."
    PRD §3.1: "A new outfitter starts in `status` `APPLICANT` with `prior_permit_count` and
    `active_permit_count` both 0."
    PRD §2.4: "Most records additionally carry `updated_at`, in the same timestamp format,
    and `version`, an integer that begins at 1 when the record is created and increases by
    exactly 1 on every mutation of that record."

    Design: Corner/entities/outfitter_retrieval_returns_the_stored_registration
    """
    set_clock()
    outfitter = create_outfitter(prequalification_insurance_verified=True)

    read = validate_success(
        api_client.get_outfitter(
            outfitter["id"], make_outfitter_representative_headers(outfitter["id"])
        )
    )
    assert read["id"] == outfitter["id"]
    assert read["legal_name"] == "Alpine Outfitters LLC"
    assert read["ein"] == "410000001"
    assert read["contact_email"] == "ops@alpine.example"
    assert read["prequalification_insurance_verified"] is True
    assert read["status"] == "APPLICANT"
    assert read["prior_permit_count"] == 0
    assert read["active_permit_count"] == 0
    assert_identity_fields(read)
    assert read["version"] == 1
    assert read["created_at"] == read["updated_at"], (
        "a row that has never been written twice keeps its creation stamp"
    )


def test_each_collection_answers_an_unknown_id_with_its_own_not_found_error():
    """PRD §2.10: "In both kinds, path parameters are resolved left to right before anything
    in the body is examined, and each unresolved segment has its own error:
    `ERR_USE_AREA_NOT_FOUND`, `ERR_OUTFITTER_NOT_FOUND`, `ERR_NEEDS_ASSESSMENT_NOT_FOUND`,
    `ERR_PROSPECTUS_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`,
    `ERR_OPERATING_PLAN_NOT_FOUND`, `ERR_GUIDE_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`,
    `ERR_USE_REPORT_NOT_FOUND`, `ERR_FEE_ASSESSMENT_NOT_FOUND` and
    `ERR_NONCOMPLIANCE_ACTION_NOT_FOUND`, each returning HTTP 404."
    PRD §2.5: "**Existence** — every referenced record resolves."

    Design: Corner/entities/every_collection_lookup_with_an_unknown_uuid_returns_not_found
    """
    set_clock()
    outfitter = create_outfitter()
    holder = make_outfitter_representative_headers(outfitter["id"])
    missing = NON_EXISTENT_UUID

    validate_error(
        api_client.get_allocation_summary(missing, SPECIALIST),
        ApiErrorId.ERR_USE_AREA_NOT_FOUND,
    )
    validate_error(
        api_client.get_outfitter(missing, SPECIALIST),
        ApiErrorId.ERR_OUTFITTER_NOT_FOUND,
    )
    validate_error(
        api_client.publish_needs_assessment(missing, OFFICER),
        ApiErrorId.ERR_NEEDS_ASSESSMENT_NOT_FOUND,
    )
    validate_error(
        api_client.get_prospectus(missing, SPECIALIST),
        ApiErrorId.ERR_PROSPECTUS_NOT_FOUND,
    )
    validate_error(
        api_client.get_permit_application(missing, SPECIALIST),
        ApiErrorId.ERR_APPLICATION_NOT_FOUND,
    )
    validate_error(
        api_client.get_permit(missing, SPECIALIST),
        ApiErrorId.ERR_PERMIT_NOT_FOUND,
    )
    validate_error(
        api_client.submit_operating_plan(missing, holder),
        ApiErrorId.ERR_OPERATING_PLAN_NOT_FOUND,
    )
    validate_error(
        api_client.get_guide(missing, SPECIALIST),
        ApiErrorId.ERR_GUIDE_NOT_FOUND,
    )
    validate_error(
        api_client.revoke_guide_authorization(
            missing, {"revocation_reason_code": "HOLDER_REQUEST"}, holder
        ),
        ApiErrorId.ERR_AUTHORIZATION_NOT_FOUND,
    )
    validate_error(
        api_client.get_trip_use_report(missing, SPECIALIST),
        ApiErrorId.ERR_USE_REPORT_NOT_FOUND,
    )
    validate_error(
        api_client.finalize_fee_assessment(missing, SPECIALIST),
        ApiErrorId.ERR_FEE_ASSESSMENT_NOT_FOUND,
    )
    validate_error(
        api_client.appeal_noncompliance_action(
            missing,
            {"appeal_basis": "The cited provision does not apply to this operation."},
            holder,
        ),
        ApiErrorId.ERR_NONCOMPLIANCE_ACTION_NOT_FOUND,
    )


def test_body_borne_references_are_resolved_in_the_declared_field_order():
    """PRD §2.5: "Path parameters are resolved left to right as they appear in the URL, and
    only then are ids carried in the request body resolved, in the order the body fields are
    listed for that endpoint."
    PRD §2.10: "Body-borne references produce the same errors: an unresolvable `use_area_id`,
    `outfitter_id`, `needs_assessment_id`, `prospectus_id`, `application_id`, `guide_id`,
    `predecessor_permit_id`, `incoming_outfitter_id` or `supersedes_report_id` is a 404
    against the entity it names, and is reported only after every path segment has resolved."

    Design: Corner/entities/every_collection_lookup_with_an_unknown_uuid_returns_not_found
    """
    set_clock()
    outfitter = create_outfitter()

    validate_error(
        api_client.create_permit_application(
            permit_application_payload(outfitter["id"], NON_EXISTENT_UUID), SPECIALIST
        ),
        ApiErrorId.ERR_USE_AREA_NOT_FOUND,
    )

    validate_error(
        api_client.create_permit_application(
            permit_application_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID), SPECIALIST
        ),
        ApiErrorId.ERR_OUTFITTER_NOT_FOUND,
    )

    rows, meta = validate_paginated(api_client.list_permit_applications(SPECIALIST))
    assert rows == []
    assert meta["total_count"] == 0, "a rejected request writes nothing at all"


def test_dropping_a_non_optional_input_is_rejected_and_persists_nothing():
    """PRD §2.5: "**Request shape** — every required field present and non-null, every enum
    value a declared member, every integer in range, every date well formed and every date
    pair correctly ordered (`ERR_INVALID_REQUEST`, 400)."
    PRD §3.1: "Two further inputs are optional: `reserved_admin_service_days`, which defaults
    to 0 and must be at least 0 and strictly less than `total_allocated_service_days`, and
    `min_liability_coverage_cents`, the minimum per-occurrence general liability limit a
    permit in this area must carry, which defaults to 100000000 cents — one million dollars."
    PRD §2.4: "A request that is rejected writes nothing at all: no field changes, no
    `updated_at` refresh and no `version` increment"

    Design: Corner/entities/creation_with_a_missing_required_input_field_is_rejected
    """
    set_clock()
    area = create_use_area()
    outfitter = create_outfitter()
    holder = make_outfitter_representative_headers(outfitter["id"])

    no_ceiling = use_area_payload(area_code="BRW-09", name="No Ceiling Area")
    del no_ceiling["total_allocated_service_days"]
    del no_ceiling["reserved_admin_service_days"]
    del no_ceiling["min_liability_coverage_cents"]
    validate_error(
        api_client.create_use_area(no_ceiling, ADMIN), ApiErrorId.ERR_INVALID_REQUEST
    )

    no_window = use_area_payload(area_code="BRW-10", name="No Window Area")
    del no_window["season_open_date"]
    validate_error(
        api_client.create_use_area(no_window, ADMIN), ApiErrorId.ERR_INVALID_REQUEST
    )

    no_days = permit_application_payload(outfitter["id"], area["id"])
    del no_days["requested_service_days"]
    validate_error(
        api_client.create_permit_application(no_days, SPECIALIST),
        ApiErrorId.ERR_INVALID_REQUEST,
    )

    no_expiry = guide_payload()
    del no_expiry["first_aid_expires_on"]
    validate_error(
        api_client.create_guide(outfitter["id"], no_expiry, holder),
        ApiErrorId.ERR_INVALID_REQUEST,
    )

    areas, area_meta = validate_paginated(api_client.list_use_areas(ADMIN))
    assert area_meta["total_count"] == 1, "a 400 leaves no partial row behind"
    assert [row["area_code"] for row in areas] == ["BRW-01"]

    guides, guide_meta = validate_paginated(
        api_client.list_guides(outfitter["id"], SPECIALIST)
    )
    assert guide_meta["total_count"] == 0
    assert guides == []

    apps, app_meta = validate_paginated(api_client.list_permit_applications(SPECIALIST))
    assert app_meta["total_count"] == 0
    assert apps == []


def test_omitted_optional_inputs_take_their_declared_defaults_and_feed_the_arithmetic():
    """PRD §3.1: "Two further inputs are optional: `reserved_admin_service_days`, which
    defaults to 0 and must be at least 0 and strictly less than
    `total_allocated_service_days`, and `min_liability_coverage_cents`, the minimum
    per-occurrence general liability limit a permit in this area must carry, which defaults
    to 100000000 cents — one million dollars."
    PRD §3.1: "The optional `prequalification_insurance_verified` flag defaults to false."
    PRD §3.1: "and optionally `seasons_experience`, the number of completed guided seasons,
    which defaults to 0."
    PRD §3.1: "An optional `min_qualifying_score` sets the eligibility bar and defaults to
    60.0."
    PRD §3.1: "An experience bonus adds one point for every three completed seasons,
    discarding any remainder, and is never worth more than 2 points."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_declared_defaults
    """
    set_clock()

    bare_area = use_area_payload()
    del bare_area["reserved_admin_service_days"]
    del bare_area["min_liability_coverage_cents"]
    area = validate_success(api_client.create_use_area(bare_area, ADMIN), 201)
    assert area["reserved_admin_service_days"] == 0
    assert area["min_liability_coverage_cents"] == 100_000_000
    assert area["committed_service_days"] == 0
    assert area["pending_service_days"] == 0
    assert area["available_service_days"] == 1000, (
        "with nothing reserved the allocatable total is the full grant"
    )
    assert area["demand_ratio"] == 0.0
    assert area["allocation_posture"] == "OPEN"

    bare_outfitter = outfitter_payload()
    del bare_outfitter["prequalification_insurance_verified"]
    outfitter = validate_success(
        api_client.create_outfitter(bare_outfitter, SPECIALIST), 201
    )
    assert outfitter["prequalification_insurance_verified"] is False, (
        "the flag defaults to false, not to null"
    )

    bare_guide = guide_payload()
    del bare_guide["seasons_experience"]
    guide = validate_success(
        api_client.create_guide(
            outfitter["id"],
            bare_guide,
            make_outfitter_representative_headers(outfitter["id"]),
        ),
        201,
    )
    assert guide["seasons_experience"] == 0
    assert guide["status"] == "PENDING_QUALIFICATION"
    assert guide["base_client_capacity"] == 8, (
        "a LEAD holding WFR earns min(8, 8); the defaulted zero seasons add no bonus"
    )

    assessment = validate_success(
        api_client.create_needs_assessment(
            area["id"],
            {
                "assessment_year": 2027,
                "public_need_finding": "NEED_EXISTS",
                "determined_capacity_service_days": 900,
                "allocated_service_days": 0,
            },
            SPECIALIST,
        ),
        201,
    )
    validate_success(api_client.publish_needs_assessment(assessment["id"], OFFICER))

    prospectus = validate_success(
        api_client.create_prospectus(
            {
                "use_area_id": area["id"],
                "needs_assessment_id": assessment["id"],
                "offered_service_days": 300,
                "submission_deadline_date": "2027-03-01",
            },
            SPECIALIST,
        ),
        201,
    )
    assert prospectus["min_qualifying_score"] == 60.0
    assert prospectus["status"] == "OPEN"
    assert prospectus["responsive_application_count"] == 0
