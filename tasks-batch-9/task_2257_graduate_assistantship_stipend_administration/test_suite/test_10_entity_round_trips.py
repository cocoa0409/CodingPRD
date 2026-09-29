"""Creation, retrieval and rejection behaviour of the eleven collections.

These cases pin the shape of a stored row: the declared defaults that fill in for
omitted optional inputs, the system-managed fields the server mints for itself,
the per-collection 404 identity, and the derived fields that ignore whatever the
client tried to supply for them.
"""
from test_helpers import (
    ApiErrorId,
    CLOCK_STARTUP_DATE,
    DEPT_ADMIN,
    GRANT_ACCOUNTANT,
    GS_ADMIN,
    NON_EXISTENT_UUID,
    academic_term_payload,
    api_client,
    appointment_payload,
    assert_academic_term,
    assert_department,
    assert_envelope_meta,
    assert_funding_source,
    assert_graduate_student,
    assert_page_meta,
    build_term_frame,
    department_payload,
    funding_source_payload,
    is_valid_uuid,
    make_department,
    make_funding_source,
    make_student,
    make_term,
    pay_period_payload,
    read_student,
    read_term,
    stipend_policy_payload,
    student_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_new_term_is_stored_in_planning_with_an_empty_calendar():
    """Creation answers 201 and a follow-up read returns the same stored values.

    PRD: "Configuration begins with an `AcademicTerm`, created by a
    `GradSchoolAdmin` in the `PLANNING` state." PRD: "A newly created term has
    `pay_period_count` of 0 and both `locked_at` and `closed_at` null."

    Design: Corner/entities/term_creation_and_retrieval_round_trip
    """
    created = validate_success(api_client.create_academic_term(
        academic_term_payload(), GS_ADMIN
    ), expected_status=201)

    assert_academic_term(created)
    assert created["status"] == "PLANNING"
    assert created["pay_period_count"] == 0
    assert created["locked_at"] is None
    assert created["closed_at"] is None
    assert created["term_code"] == "FALL2026"
    assert created["proration_method"] == "CALENDAR_DAY"
    assert created["tax_calendar_year"] == 2026

    fetched = read_term(created["id"])
    assert fetched["id"] == created["id"]
    assert fetched["term_start"] == "2026-09-01"
    assert fetched["term_end"] == "2026-12-31"
    assert fetched["session_type"] == "IN_SESSION"
    assert fetched["remission_drop_deadline"] == "2026-09-15"
    assert fetched["version"] == 1


def test_a_freshly_registered_student_reads_back_with_zeroed_aggregates():
    """The four aggregates and the standing fields are stored, not absent.

    PRD: "The `sap_status` — satisfactory academic progress — starts at
    `SATISFACTORY` and may later be `PROBATION` or `UNSATISFACTORY`." PRD: "Four
    aggregates start at 0: `total_effort_pct`, the aggregate percentage effort
    over the student's counted appointments; `assigned_hours_per_week`, that
    aggregate expressed in weekly hours; `tuition_benefit_ytd_cents`, the sum of
    `benefit_cents` over the student's `FINAL` tax assessments in the current
    `tax_calendar_year`; and `taxable_tuition_benefit_ytd_cents`, the
    corresponding sum of `taxable_cents`."

    Design: Corner/entities/student_retrieval_returns_zeroed_aggregates
    """
    student = make_student(
        student_number="GS-1001", full_name="Ada Vance",
        degree_level="DOCTORAL", is_international=False, cumulative_gpa=3.60,
        enrolled_credit_hours=9,
    )

    fetched = read_student(student["id"])

    assert_graduate_student(fetched)
    assert fetched["total_effort_pct"] == 0
    assert float(fetched["assigned_hours_per_week"]) == 0.0
    assert fetched["tuition_benefit_ytd_cents"] == 0
    assert fetched["taxable_tuition_benefit_ytd_cents"] == 0
    assert fetched["sap_status"] == "SATISFACTORY"
    assert fetched["enrolled_credit_hours"] == 9


def test_paging_the_funding_source_list_reports_the_total_and_the_remainder():
    """Two pages of two and one cover three rows without repeating any of them.

    PRD: "The `limit` parameter caps the number of rows returned; it defaults to
    10 when omitted, with a minimum accepted value of 1 and a maximum of 100."
    PRD: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, alongside
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/entities/funding_source_listing_returns_pagination_envelope
    """
    department = make_department(code="CHEM", name="Chemistry")
    for code, source_type, amount, remission in (
        ("NSF-A", "GRANT", 5000000, True),
        ("DEPT-B", "DEPARTMENTAL_BUDGET", 3000000, True),
        ("FELL-C", "FELLOWSHIP", 1000000, False),
    ):
        make_funding_source(
            department["id"], source_code=code, source_type=source_type,
            authorized_amount_cents=amount, allows_tuition_remission=remission,
        )

    first_page, first_meta = validate_paginated(api_client.list_funding_sources(
        GRANT_ACCOUNTANT, {"limit": 2, "offset": 0}
    ))
    second_page, second_meta = validate_paginated(api_client.list_funding_sources(
        GRANT_ACCOUNTANT, {"limit": 2, "offset": 2}
    ))

    assert_page_meta(first_meta, limit=2, offset=0, total_count=3, has_more=True)
    assert len(first_page) == 2
    assert_page_meta(second_meta, limit=2, offset=2, total_count=3,
                     has_more=False)
    assert len(second_page) == 1

    ids = [row["id"] for row in first_page] + [row["id"] for row in second_page]
    assert len(set(ids)) == 3, "the two pages together hold each source once"
    for row in first_page + second_page:
        assert_funding_source(row)


def test_each_collection_answers_an_unknown_id_with_its_own_not_found_error():
    """The same missing identifier yields nine distinct 404 identities.

    PRD: "**Path existence** — every identifier segment in the path resolves,
    left to right, to an existing row. The error is the one belonging to the
    addressed collection: `ERR_TERM_NOT_FOUND`, `ERR_DEPARTMENT_NOT_FOUND`,
    `ERR_STUDENT_NOT_FOUND`, `ERR_FUNDING_SOURCE_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`,
    `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_RENEWAL_DECISION_NOT_FOUND`, or
    `ERR_ASSESSMENT_NOT_FOUND`, each with HTTP 404."

    Design: Corner/entities/unknown_path_ids_return_entity_specific_not_found
    """
    reads = [
        (api_client.get_academic_term, ApiErrorId.ERR_TERM_NOT_FOUND),
        (api_client.get_department, ApiErrorId.ERR_DEPARTMENT_NOT_FOUND),
        (api_client.get_student, ApiErrorId.ERR_STUDENT_NOT_FOUND),
        (api_client.get_funding_source, ApiErrorId.ERR_FUNDING_SOURCE_NOT_FOUND),
        (api_client.get_appointment, ApiErrorId.ERR_APPOINTMENT_NOT_FOUND),
        (api_client.get_funding_allocation, ApiErrorId.ERR_ALLOCATION_NOT_FOUND),
        (api_client.get_stipend_disbursement,
         ApiErrorId.ERR_DISBURSEMENT_NOT_FOUND),
        (api_client.get_renewal_decision,
         ApiErrorId.ERR_RENEWAL_DECISION_NOT_FOUND),
        (api_client.get_tax_assessment, ApiErrorId.ERR_ASSESSMENT_NOT_FOUND),
    ]

    seen = []
    for read, expected in reads:
        body = validate_error(
            read(NON_EXISTENT_UUID, GS_ADMIN), expected.value, 404
        )
        seen.append(body["error_id"])

    assert seen == [expected.value for _, expected in reads], (
        "each addressed collection reports its own not-found error"
    )
    assert len(set(seen)) == 9, "no two collections share a not-found error id"


def test_registering_a_student_without_a_degree_level_is_rejected():
    """`degree_level` has no declared default, so omitting it is malformed.

    PRD: "A `GraduateStudent` is registered with a registrar `student_number`
    unique across all students, a `full_name`, a `degree_level` of `MASTERS` or
    `DOCTORAL`, the boolean `is_international` flag that marks a non-immigrant
    visa holder subject to hour restrictions, and a `cumulative_gpa` between 0.00
    and 4.00 carried to two decimal places." PRD: "**Request shape** — required
    fields present, enum values within their declared sets, dates formatted as
    ISO 8601 calendar dates".

    Design: Corner/entities/student_creation_missing_required_degree_level_rejected
    """
    payload = student_payload(student_number="GS-1002", full_name="No Degree",
                             cumulative_gpa=3.10)
    payload.pop("degree_level")
    payload.pop("enrolled_credit_hours")

    response = api_client.create_student(payload, GS_ADMIN)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    rows, meta = validate_paginated(api_client.list_funding_sources(
        GRANT_ACCOUNTANT, {"limit": 10, "offset": 0}
    ))
    assert rows == [] and meta["total_count"] == 0, (
        "the rejected registration created nothing anywhere"
    )


def test_omitted_optional_inputs_fall_back_to_their_declared_defaults():
    """Eight optional fields land on the exact values the contract names.

    PRD: "It also carries `non_renewal_notice_days`, the number of days before an
    appointment's `end_date` by which a non-renewal notice must be issued; it
    defaults to 60 and must lie between 1 and 180." PRD: "Three inputs are
    optional: `visa_type`, one of `F1`, `J1` or `NONE` and defaulting to `NONE`;
    `enrolled_credit_hours` between 0 and 24 and defaulting to 0, which is read
    at appointment submission time to size the tuition remission; and
    `external_weekly_hours` between 0.0 and 40.0 to one decimal place and
    defaulting to 0, which counts non-assistantship university employment against
    the international hour ceiling." PRD: "The `effort_cap_pct` starts at 75 and
    may be between 1 and 100 thereafter". PRD: "Three further settings have
    defaults and may be omitted: `insurance_min_effort_pct`, the minimum
    appointment effort percentage for insurance eligibility, defaults to 50 and
    must lie between 1 and 100; `min_insurance_duration_days`, the minimum
    inclusive appointment duration in days for insurance eligibility, defaults to
    90 and must be at least 1; and `tuition_tax_exempt_cap_cents`, the
    per-calendar-year tuition-benefit amount shielded from imputed income,
    defaults to 525000". PRD: "`grant_effort_cap_pct`, the maximum effort
    percentage a single appointment may draw from the source, defaulting to 100".
    PRD: "A new source is `ACTIVE`, has `committed_amount_cents` and
    `expended_amount_cents` of 0, `available_amount_cents` equal to
    `authorized_amount_cents`, and `suspension_reason` null."

    Design: Corner/entities/department_and_student_omitted_optionals_use_declared_defaults
    """
    term = make_term()

    department = validate_success(api_client.create_department(
        department_payload(), GS_ADMIN
    ), expected_status=201)
    assert department["non_renewal_notice_days"] == 60

    student_body = student_payload(
        student_number="GS-1003", full_name="Default Dana",
        cumulative_gpa=3.40,
    )
    student_body.pop("enrolled_credit_hours")
    student = validate_success(
        api_client.create_student(student_body, GS_ADMIN), expected_status=201
    )
    assert student["effort_cap_pct"] == 75
    assert student["visa_type"] == "NONE"
    assert float(student["external_weekly_hours"]) == 0.0
    assert student["enrolled_credit_hours"] == 0
    assert student["cap_override_by_user_id"] is None
    assert student["cap_override_justification"] is None

    policy = validate_success(api_client.create_stipend_policy(
        stipend_policy_payload(term["id"], term_insurance_premium_cents=600000),
        GS_ADMIN,
    ), expected_status=201)
    assert policy["insurance_min_effort_pct"] == 50
    assert policy["min_insurance_duration_days"] == 90
    assert policy["tuition_tax_exempt_cap_cents"] == 525000

    source_body = funding_source_payload(department["id"])
    source = validate_success(
        api_client.create_funding_source(source_body, GRANT_ACCOUNTANT),
        expected_status=201,
    )
    assert source["grant_effort_cap_pct"] == 100
    assert source["auto_reinstate_threshold_cents"] == 0
    assert source["sponsor_code"] is None
    assert source["status"] == "ACTIVE"
    assert source["committed_amount_cents"] == 0
    assert source["expended_amount_cents"] == 0
    assert source["available_amount_cents"] == 5000000


def test_client_supplied_effort_and_money_fields_on_an_appointment_are_discarded():
    """The effort profile is derived, and the cents fields stay at 0 until submission.

    PRD: "The `weekly_hours` field is `effort_pct` divided by 100, multiplied by
    the 40 hours of a full-time week, rounded half up to one decimal place. The
    `duration_days` field is the count of whole days from `start_date` to
    `end_date` counting both endpoints — the difference in days plus one." PRD:
    "And `tuition_remission_pct` is selected from `effort_pct` by band: 0 when
    `effort_pct` is below 25; 50 when `effort_pct` is at least 25 and below 50;
    75 when `effort_pct` is at least 50 and below 75; and 100 when `effort_pct`
    is at least 75." PRD: "leaves every cents-valued computed field at 0 until
    submission: `projected_pay_period_count`, `total_stipend_cents`,
    `tuition_remission_cents`, `insurance_subsidy_cents`,
    `employee_premium_cents` and `net_term_stipend_cents`."

    Design: Corner/entities/appointment_computed_money_fields_input_ignored
    """
    frame = build_term_frame(
        pay_periods=[(1, "2026-09-01", "2027-01-01", "2027-01-05")]
    )
    student = make_student(student_number="GS-1004")

    body = appointment_payload(
        student["id"], frame["department_id"], frame["term_id"], effort_pct=60,
        weekly_hours=40.0, tuition_remission_pct=100,
        total_stipend_cents=9999999, duration_days=1,
    )
    created = validate_success(
        api_client.create_appointment(body, DEPT_ADMIN), expected_status=201
    )

    assert float(created["weekly_hours"]) == 24.0, "60 percent of 40 hours"
    assert created["duration_days"] == 122, (
        "2026-09-01 through 2026-12-31 inclusive"
    )
    assert created["tuition_remission_pct"] == 75
    assert created["insurance_eligible"] is True
    assert created["projected_pay_period_count"] == 0
    assert created["total_stipend_cents"] == 0
    assert created["tuition_remission_cents"] == 0
    assert created["insurance_subsidy_cents"] == 0
    assert created["employee_premium_cents"] == 0
    assert created["net_term_stipend_cents"] == 0


def test_a_client_supplied_id_and_version_on_a_department_are_ignored():
    """Identity is minted by the server and the row starts its life at version 1.

    PRD: "`id` (string): a server-minted UUID. It carries no type prefix of any
    kind." PRD: "`version` (integer): an integer that starts at 1 on creation and
    increments by one on every mutation, including mutations performed by a
    server-driven cascade." PRD: "`created_at` (string): an ISO 8601 timestamp in
    UTC with three fractional digits, recording the logical-clock instant at
    which the row was created."

    Design: Corner/entities/system_fields_generated_and_client_input_ignored
    """
    smuggled_id = "00000000-0000-0000-0000-0000000000aa"
    response = api_client.create_department({
        "code": "PHYS", "name": "Physics",
        "id": smuggled_id, "version": 77, "created_at": "2000-01-01T00:00:00Z",
    }, GS_ADMIN)
    created = validate_success(response, expected_status=201)

    assert_department(created)
    assert is_valid_uuid(created["id"])
    assert created["id"] != smuggled_id
    assert created["version"] == 1
    assert created["created_at"] != "2000-01-01T00:00:00Z"
    assert created["created_at"].startswith(CLOCK_STARTUP_DATE), (
        "created_at records the logical-clock instant, which starts at 2026-08-01"
    )
    assert_envelope_meta(response.json()["meta"])

    fetched = validate_success(
        api_client.get_department(created["id"], GS_ADMIN)
    )
    assert fetched["id"] == created["id"]
    assert fetched["code"] == "PHYS"


def test_out_of_domain_enums_and_a_reversed_term_window_are_each_rejected():
    """Three independently malformed term payloads all fail request-shape checks.

    PRD: "The `session_type` is either `IN_SESSION`, meaning an instructional
    session during which international hour restrictions bite, or `BREAK`,
    meaning a between-terms period during which they do not. The
    `proration_method` is either `CALENDAR_DAY` or `WORKDAY`, and it decides
    which of the two proration variants the term's payroll uses." PRD:
    "**Request shape** — required fields present, enum values within their
    declared sets, dates formatted as ISO 8601 calendar dates, `effort_pct`
    within 1 through 100, `share_pct` within 0.01 through 100.00 with at most two
    decimal places, an `allocations` array holding between 1 and 5 elements,
    `limit` within 1 through 100, `offset` at least 0, `end_date` on or after
    `start_date`, and `period_end_exclusive` strictly after `period_start`. Any
    failure is `ERR_INVALID_REQUEST` (422)."

    Design: Corner/entities/term_invalid_enum_and_reversed_dates_rejected
    """
    malformed = [
        academic_term_payload(term_code="BAD1", session_type="SUMMER_BREAKS"),
        academic_term_payload(term_code="BAD2", proration_method="HOURLY"),
        academic_term_payload(term_code="BAD3", term_start="2026-12-31",
                              term_end="2026-09-01"),
    ]

    for payload in malformed:
        validate_error(
            api_client.create_academic_term(payload, GS_ADMIN),
            ApiErrorId.ERR_INVALID_REQUEST.value, 422,
        )

    good = validate_success(api_client.create_academic_term(
        academic_term_payload(), GS_ADMIN
    ), expected_status=201)
    policies, meta = validate_paginated(api_client.list_term_stipend_policies(
        good["id"], GS_ADMIN, {"limit": 10, "offset": 0}
    ))
    assert policies == [] and meta["total_count"] == 0, (
        "none of the malformed terms left a policy or a term behind"
    )


def test_a_policy_and_a_pay_period_naming_an_unknown_term_are_not_found():
    """A body reference to a missing term is resolved before any shape check.

    PRD: "**Body reference existence** — reference fields in the request body
    resolve to existing rows, checked in this declaration order: `term_id`,
    `department_id`, `student_id`, `funding_source_id`, `appointment_id`,
    `renewed_from_appointment_id`. Each yields its collection's 404 error."

    Design: Corner/entities/stipend_policy_and_pay_period_with_unknown_term_not_found
    """
    validate_error(
        api_client.create_stipend_policy(
            stipend_policy_payload(NON_EXISTENT_UUID), GS_ADMIN
        ),
        ApiErrorId.ERR_TERM_NOT_FOUND.value, 404,
    )
    validate_error(
        api_client.create_pay_period(
            pay_period_payload(NON_EXISTENT_UUID, 1, "2026-09-01",
                               "2026-10-01", "2026-10-05"),
            GS_ADMIN,
        ),
        ApiErrorId.ERR_TERM_NOT_FOUND.value, 404,
    )

    term = make_term()
    policies, policy_meta = validate_paginated(
        api_client.list_term_stipend_policies(term["id"], GS_ADMIN,
                                              {"limit": 10, "offset": 0})
    )
    periods, period_meta = validate_paginated(
        api_client.list_term_pay_periods(term["id"], GS_ADMIN,
                                         {"limit": 10, "offset": 0})
    )
    assert policies == [] and policy_meta["total_count"] == 0
    assert periods == [] and period_meta["total_count"] == 0


def test_appointment_body_references_are_resolved_in_declaration_order():
    """An unknown department reports itself before an unknown student can.

    PRD: "**Body reference existence** — reference fields in the request body
    resolve to existing rows, checked in this declaration order: `term_id`,
    `department_id`, `student_id`, `funding_source_id`, `appointment_id`,
    `renewed_from_appointment_id`. Each yields its collection's 404 error."

    Design: Corner/entities/appointment_creation_with_unknown_student_and_department_not_found
    """
    frame = build_term_frame(
        pay_periods=[(1, "2026-09-01", "2027-01-01", "2027-01-05")]
    )
    student = make_student(student_number="GS-1005")

    unknown_department = appointment_payload(
        student["id"], NON_EXISTENT_UUID, frame["term_id"], effort_pct=50,
        monthly_stipend_cents=200000,
    )
    validate_error(
        api_client.create_appointment(unknown_department, DEPT_ADMIN),
        ApiErrorId.ERR_DEPARTMENT_NOT_FOUND.value, 404,
    )

    unknown_student = appointment_payload(
        NON_EXISTENT_UUID, frame["department_id"], frame["term_id"],
        effort_pct=50, monthly_stipend_cents=200000,
    )
    validate_error(
        api_client.create_appointment(unknown_student, DEPT_ADMIN),
        ApiErrorId.ERR_STUDENT_NOT_FOUND.value, 404,
    )

    appointments, meta = validate_paginated(api_client.list_appointments(
        DEPT_ADMIN, {"limit": 10, "offset": 0}
    ))
    assert appointments == [] and meta["total_count"] == 0, (
        "neither rejected creation stored an appointment"
    )
    assert read_student(student["id"])["total_effort_pct"] == 0
