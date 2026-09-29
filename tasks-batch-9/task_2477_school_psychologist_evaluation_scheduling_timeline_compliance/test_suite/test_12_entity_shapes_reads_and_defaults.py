"""Entity persistence, declared defaults, computed fields and body foreign keys."""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    AssessmentStatus,
    CaseloadStatus,
    CredentialType,
    GradeBand,
    OrderStatus,
    PsychologistStatus,
    ReferralStatus,
    ReferralType,
    api_client,
    assert_assessment_instrument,
    assert_protocol_order,
    assert_psychologist,
    assert_referral,
    assert_school,
    fixtures,
    is_valid_uuid,
    protocol_order_payload,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["district_admin_headers"]
SUPERVISOR = TEST_USERS["psych_services_supervisor_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]

UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


def test_registering_a_building_persists_every_supplied_field():
    """The created row echoes the payload and opens with the four system fields.

    "Operations that bring a new, independently addressable record into existence return `201 Created`: registering a building, a psychologist or an instrument, assigning a licence seat, placing a protocol order, filing a referral, claiming a timeline exclusion, booking an interpreter session, and proposing an eligibility meeting."

    Design: Corner/entities/school_create_returns_persisted_building
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")

    response = api_client.create_school(
        {
            "name": "Aspen Elementary",
            "building_code": "AS20",
            "grade_band": "ELEMENTARY",
            "concurrent_meeting_capacity": 3,
            "enrollment_count": 500,
        },
        ADMIN,
    )

    school = validate_success(response, 201)
    assert_school(school)
    assert school["name"] == "Aspen Elementary"
    assert school["building_code"] == "AS20"
    assert school["grade_band"] == GradeBand.ELEMENTARY.value
    assert school["concurrent_meeting_capacity"] == 3
    assert school["enrollment_count"] == 500
    # The identifier is the bare UUID, and nothing has mutated the row yet.
    assert is_valid_uuid(school["id"])
    assert school["version"] == 1
    assert school["created_at"] == school["updated_at"]


def test_reading_a_building_back_returns_the_stored_row():
    """A read hands back the same row and is not itself a mutation.

    "**`version`** (integer): a monotonically increasing integer that increments by one on every mutation of the record."

    Design: Corner/entities/school_get_returns_stored_row
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    created = fixtures.create_school(
        name="Birchwood Middle",
        building_code="BR21",
        grade_band="MIDDLE",
        concurrent_meeting_capacity=2,
        enrollment_count=610,
    )

    fetched = validate_success(api_client.get_school(created["id"], SUPERVISOR))

    assert_school(fetched)
    assert fetched["id"] == created["id"]
    assert fetched["name"] == "Birchwood Middle"
    assert fetched["building_code"] == "BR21"
    assert fetched["grade_band"] == GradeBand.MIDDLE.value
    assert fetched["concurrent_meeting_capacity"] == 2
    assert fetched["enrollment_count"] == 610
    assert fetched["version"] == 1


def test_referral_list_reports_total_count_and_has_more_across_pages():
    """Page one carries two of three rows and reports the third as remaining.

    "`total_count` reports the number of records matching the filters before pagination is applied, and `has_more` reports whether any matching record remains beyond the current page."

    Design: Corner/entities/referral_list_pagination_total_count_and_has_more
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Cypress High",
        building_code="CY22",
        grade_band="HIGH",
        concurrent_meeting_capacity=2,
        enrollment_count=1200,
    )
    for student in ("STU-01", "STU-02", "STU-03"):
        fixtures.create_referral(school["id"], student_local_id=student)

    first_page, first_meta = validate_paginated(
        api_client.list_referrals(INTAKE, {"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    second_page, second_meta = validate_paginated(
        api_client.list_referrals(INTAKE, {"limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    all_rows, all_meta = validate_paginated(api_client.list_referrals(INTAKE))
    assert len(all_rows) == 3
    assert all_meta["total_count"] == 3
    assert all_meta["has_more"] is False


def test_evaluation_list_filters_by_psychologist_and_assessment_status():
    """Each declared filter narrows the list to the rows that match it.

    "Evaluations are listable filtered by `referral_id`, `psychologist_id`, `prior_evaluation_id`, `testing_instrument_id`, `report_drafted_by_psychologist_id`, `assessment_status` and `compliance_status`."

    Design: Corner/entities/evaluation_list_filter_by_psychologist_and_status
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Dogwood Elementary",
        building_code="DW23",
        grade_band="ELEMENTARY",
        concurrent_meeting_capacity=2,
        enrollment_count=380,
    )
    first_psychologist = fixtures.create_psychologist(
        [school["id"]],
        full_name="Tara Voss",
        employee_number="E-2001",
        credential_type="SSP",
    )
    second_psychologist = fixtures.create_psychologist(
        [school["id"]],
        full_name="Uri Bell",
        employee_number="E-2002",
        credential_type="SSP",
    )
    _, first_evaluation = fixtures.consented_referral(
        school["id"], student_local_id="STU-04"
    )
    fixtures.assign_evaluator(first_evaluation["id"], first_psychologist["id"])
    _, second_evaluation = fixtures.consented_referral(
        school["id"], student_local_id="STU-05"
    )
    fixtures.assign_evaluator(second_evaluation["id"], second_psychologist["id"])
    _, unassigned_evaluation = fixtures.consented_referral(
        school["id"], student_local_id="STU-06"
    )

    owned_and_assigned, _ = validate_paginated(
        api_client.list_evaluations(
            SUPERVISOR,
            {
                "psychologist_id": first_psychologist["id"],
                "assessment_status": AssessmentStatus.ASSIGNED.value,
            },
        )
    )
    assert [row["id"] for row in owned_and_assigned] == [first_evaluation["id"]]

    still_pending, _ = validate_paginated(
        api_client.list_evaluations(
            SUPERVISOR,
            {"assessment_status": AssessmentStatus.PENDING_ASSIGNMENT.value},
        )
    )
    assert [row["id"] for row in still_pending] == [unassigned_evaluation["id"]]

    second_owner_rows, _ = validate_paginated(
        api_client.list_evaluations(
            SUPERVISOR, {"psychologist_id": second_psychologist["id"]}
        )
    )
    assert [row["id"] for row in second_owner_rows] == [second_evaluation["id"]]

    _, unfiltered_meta = validate_paginated(api_client.list_evaluations(SUPERVISOR))
    assert unfiltered_meta["total_count"] == 3


def test_an_unknown_id_reports_the_code_of_the_collection_it_was_addressed_in():
    """The same missing identifier yields a different 404 per addressed record type.

    "Each missing identifier has its own code: `ERR_SCHOOL_NOT_FOUND`, `ERR_PSYCHOLOGIST_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`, `ERR_INSTRUMENT_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_EXCLUSION_NOT_FOUND`, `ERR_MEETING_NOT_FOUND` and `ERR_BREACH_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/entities/evaluation_get_unknown_id_returns_evaluation_not_found
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")

    validate_error(
        api_client.get_evaluation(UNKNOWN_ID, SUPERVISOR),
        ApiErrorId.ERR_EVALUATION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.get_eligibility_meeting(UNKNOWN_ID, INTAKE),
        ApiErrorId.ERR_MEETING_NOT_FOUND.value,
        404,
    )


def test_a_psychologist_registered_without_building_coverage_is_rejected():
    """Building coverage is required, so its absence is a shape failure.

    "Building coverage is declared as `assigned_school_ids`, a non-empty array of building identifiers — a genuine many-to-many membership set rather than a single reference — and every element must resolve to an existing building at write time, otherwise the registration fails with `ERR_PSYCHOLOGIST_NOT_FOUND` if the acting identifier is at fault or `ERR_SCHOOL_NOT_FOUND` for an unresolvable building element."

    Design: Corner/entities/psychologist_create_missing_required_field_rejected
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Elmhurst Middle",
        building_code="EH24",
        grade_band="MIDDLE",
        concurrent_meeting_capacity=2,
        enrollment_count=520,
    )

    response = api_client.create_psychologist(
        {
            "full_name": "Yuri Blake",
            "employee_number": "E-2003",
            "credential_type": "SSP",
        },
        ADMIN,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    # The very same registration succeeds once the coverage array is supplied.
    retry = api_client.create_psychologist(
        {
            "full_name": "Yuri Blake",
            "employee_number": "E-2003",
            "credential_type": "SSP",
            "assigned_school_ids": [school["id"]],
        },
        ADMIN,
    )
    created = validate_success(retry, 201)
    assert_psychologist(created)
    assert created["assigned_school_ids"] == [school["id"]]


def test_a_minimal_referral_picks_up_every_declared_default():
    """The four optional intake fields default rather than arriving null.

    "`primary_language` is the ISO 639-1 code of the family's primary language and defaults to `en`."

    "A filed referral opens in `INTAKE_RECEIVED` status with `consent_received_at`, `active_evaluation_id`, `last_consent_event_type`, `parent_signature_reference` and `waiver_reason` all null."

    Design: Corner/entities/referral_create_applies_declared_defaults
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Fernbank Elementary",
        building_code="FB25",
        grade_band="ELEMENTARY",
        concurrent_meeting_capacity=2,
        enrollment_count=410,
    )

    response = api_client.create_referral(
        {
            "school_id": school["id"],
            "student_local_id": "STU-07",
            "referral_type": "INITIAL",
            "requested_domains": ["COGNITIVE"],
        },
        INTAKE,
    )

    referral = validate_success(response, 201)
    assert_referral(referral)
    assert referral["primary_language"] == "en"
    assert referral["interpreter_required"] is False
    assert referral["bilingual_evaluation_required"] is False
    assert referral["intervention_team_summary"] == ""
    assert referral["status"] == ReferralStatus.INTAKE_RECEIVED.value
    assert referral["consent_received_at"] is None
    assert referral["active_evaluation_id"] is None
    assert referral["last_consent_event_type"] is None
    assert referral["parent_signature_reference"] is None
    assert referral["waiver_reason"] is None
    assert referral["version"] == 1


def test_a_new_psychologist_opens_with_the_default_capacity_and_a_zero_caseload():
    """Registration writes the whole derived side of the record deterministically.

    "Registration initialises the derived side of the record deterministically: `status` becomes `ACTIVE`, `open_case_points` becomes 0, `caseload_status` becomes `BALANCED`, and both `pressure_index_assigned_basis` and `pressure_index_clock_weighted` become `0.00`."

    Design: Corner/entities/psychologist_create_applies_capacity_and_computed_zero_state
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Glenrose High",
        building_code="GR26",
        grade_band="HIGH",
        concurrent_meeting_capacity=2,
        enrollment_count=900,
    )

    response = api_client.create_psychologist(
        {
            "full_name": "Wren Case",
            "employee_number": "E-2004",
            "credential_type": "PHD",
            "assigned_school_ids": [school["id"]],
        },
        ADMIN,
    )

    psychologist = validate_success(response, 201)
    assert_psychologist(psychologist)
    assert psychologist["credential_type"] == CredentialType.PHD.value
    assert psychologist["weekly_capacity_points"] == 20
    assert psychologist["languages_certified"] == ["en"]
    assert psychologist["status"] == PsychologistStatus.ACTIVE.value
    assert psychologist["open_case_points"] == 0
    assert psychologist["caseload_status"] == CaseloadStatus.BALANCED.value
    assert psychologist["pressure_index_assigned_basis"] == 0.00
    assert psychologist["pressure_index_clock_weighted"] == 0.00


def test_client_supplied_money_on_a_protocol_order_is_ignored():
    """Every money field is priced by the server from the instrument's list price.

    "Second, `unit_price_cents` is the instrument's `protocol_unit_cost_cents` multiplied by that tier multiplier, rounded half up to a whole cent — this is the first of the three independent roundings."

    Design: Corner/entities/protocol_order_computed_costs_ignored_input_from_client
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    instrument = fixtures.create_instrument(
        name="Vineland-3",
        instrument_code="VIN3",
        protocol_stock_count=0,
        protocol_units_per_administration=1,
        protocol_unit_cost_cents=2000,
        license_seat_total=1,
        license_expires_on="2027-06-30",
        supported_language_editions=["en"],
    )

    payload = protocol_order_payload(instrument["id"], 5, rush_flag=False)
    payload["unit_price_cents"] = 1
    payload["total_cost_cents"] = 1
    response = api_client.create_protocol_order(payload, SUPERVISOR)

    order = validate_success(response, 201)
    assert_protocol_order(order)
    assert order["unit_price_cents"] == 2000
    assert order["base_cents"] == 10000
    assert order["contract_discount_cents"] == 700
    assert order["rush_surcharge_cents"] == 0
    assert order["handling_fee_cents"] == 1250
    assert order["total_cost_cents"] == 10550
    assert order["auto_approved"] is True
    assert order["status"] == OrderStatus.APPROVED.value
    assert order["decided_by_user_id"] is None

    # Ordering booklets never credits the shelf; only receipt does.
    assert_assessment_instrument(fixtures.get_instrument(instrument["id"]))
    assert fixtures.get_instrument(instrument["id"])["protocol_stock_count"] == 0


def test_client_supplied_system_fields_on_a_referral_are_discarded():
    """The consent-stream fields open null however the client filled them in.

    "A filed referral opens in `INTAKE_RECEIVED` status with `consent_received_at`, `active_evaluation_id`, `last_consent_event_type`, `parent_signature_reference` and `waiver_reason` all null."

    Design: Corner/entities/referral_create_system_fields_ignored_input
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Hollybrook Middle",
        building_code="HB27",
        grade_band="MIDDLE",
        concurrent_meeting_capacity=2,
        enrollment_count=470,
    )

    response = api_client.create_referral(
        {
            "school_id": school["id"],
            "student_local_id": "STU-08",
            "referral_type": "INITIAL",
            "requested_domains": ["COGNITIVE"],
            "status": "COMPLETED",
            "active_evaluation_id": UNKNOWN_ID,
            "consent_received_at": "2020-01-01T00:00:00Z",
            "version": 99,
        },
        INTAKE,
    )

    referral = validate_success(response, 201)
    assert_referral(referral)
    assert referral["status"] == ReferralStatus.INTAKE_RECEIVED.value
    assert referral["active_evaluation_id"] is None
    assert referral["consent_received_at"] is None
    assert referral["version"] == 1
    assert referral["id"] != UNKNOWN_ID


def test_a_repeated_requested_domain_is_rejected_rather_than_de_duplicated():
    """The domain set must be duplicate-free, so a repeat is a shape failure.

    "The intervention team's assessment request arrives as `requested_domains`, a non-empty, duplicate-free subset of the four assessment domains `COGNITIVE`, `ACADEMIC`, `SOCIAL_EMOTIONAL` and `ADAPTIVE`, and their prior work arrives as free-text `intervention_team_summary`, which defaults to the empty string."

    Design: Corner/entities/referral_duplicate_requested_domain_rejected
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Ironwood High",
        building_code="IW28",
        grade_band="HIGH",
        concurrent_meeting_capacity=2,
        enrollment_count=870,
    )

    def file_referral(domains):
        return api_client.create_referral(
            {
                "school_id": school["id"],
                "student_local_id": "STU-09",
                "referral_type": "INITIAL",
                "requested_domains": domains,
            },
            INTAKE,
        )

    validate_error(
        file_referral(["COGNITIVE", "COGNITIVE"]),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )
    validate_error(file_referral([]), ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    accepted = validate_success(file_referral(["COGNITIVE", "ACADEMIC"]), 201)
    assert_referral(accepted)
    assert accepted["requested_domains"] == ["COGNITIVE", "ACADEMIC"]


def test_a_reevaluation_referral_must_name_the_evaluation_it_re_examines():
    """The self-reference is required exactly when the type is REEVALUATION.

    "Supplying that reference on an `INITIAL` referral, or omitting it on a `REEVALUATION`, is a shape violation and is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/reevaluation_referral_without_prior_evaluation_rejected
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Juniper Elementary",
        building_code="JN29",
        grade_band="ELEMENTARY",
        concurrent_meeting_capacity=2,
        enrollment_count=330,
    )
    _, prior_evaluation = fixtures.consented_referral(
        school["id"], student_local_id="STU-10"
    )

    def file_referral(**extra):
        payload = {
            "school_id": school["id"],
            "student_local_id": "STU-10",
            "requested_domains": ["COGNITIVE"],
        }
        payload.update(extra)
        return api_client.create_referral(payload, INTAKE)

    validate_error(
        file_referral(referral_type="REEVALUATION"),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )
    validate_error(
        file_referral(
            referral_type="INITIAL", prior_evaluation_id=prior_evaluation["id"]
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        422,
    )

    accepted = validate_success(
        file_referral(
            referral_type="REEVALUATION", prior_evaluation_id=prior_evaluation["id"]
        ),
        201,
    )
    assert_referral(accepted)
    assert accepted["referral_type"] == ReferralType.REEVALUATION.value
    assert accepted["prior_evaluation_id"] == prior_evaluation["id"]


def test_a_referral_naming_an_unknown_building_is_a_not_found():
    """A body foreign key that resolves to nothing is a 404, not a shape error.

    "Foreign keys supplied in a request body are held to the same standard and resolve after the path identifiers."

    Design: Corner/entities/referral_create_unknown_school_returns_school_not_found
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")

    response = api_client.create_referral(
        {
            "school_id": UNKNOWN_ID,
            "student_local_id": "STU-11",
            "referral_type": "INITIAL",
            "requested_domains": ["COGNITIVE"],
        },
        INTAKE,
    )

    validate_error(response, ApiErrorId.ERR_SCHOOL_NOT_FOUND.value, 404)
    _, meta = validate_paginated(api_client.list_referrals(INTAKE))
    assert meta["total_count"] == 0


def test_every_element_of_the_building_coverage_array_must_resolve():
    """One good building plus one unknown building still fails the whole write.

    "A referral's `school_id` and `prior_evaluation_id`, every element of a psychologist's `assigned_school_ids`, a protocol order's `instrument_id`, a licence seat's `psychologist_id`, the `evaluation_id` on an exclusion claim, an interpreter session or an eligibility meeting, the `school_id` on an eligibility meeting, the `psychologist_id` supplied to an assignment, and the `instrument_id` supplied at testing-start must all resolve to live records, otherwise the corresponding 404 code is returned."

    Design: Corner/entities/psychologist_assigned_school_array_element_must_resolve
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Kestrel Middle",
        building_code="KS30",
        grade_band="MIDDLE",
        concurrent_meeting_capacity=2,
        enrollment_count=500,
    )

    def register(coverage):
        return api_client.create_psychologist(
            {
                "full_name": "Xan Poole",
                "employee_number": "E-2005",
                "credential_type": "SSP",
                "assigned_school_ids": coverage,
            },
            ADMIN,
        )

    validate_error(
        register([school["id"], UNKNOWN_ID]),
        ApiErrorId.ERR_SCHOOL_NOT_FOUND.value,
        404,
    )
    # An empty membership set is a different failure mode from an unresolved element.
    validate_error(register([]), ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    created = validate_success(register([school["id"]]), 201)
    assert_psychologist(created)
    assert created["assigned_school_ids"] == [school["id"]]
