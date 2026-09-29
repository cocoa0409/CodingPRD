"""Resource shapes, server-minted fields and declared defaults."""

from test_helpers import (
    ADMIN_HEADERS,
    ELIGIBILITY_PENDING_SCREENING,
    ERR_INVALID_REQUEST,
    ERR_PROGRAM_MISMATCH,
    ERR_PROJECT_NOT_FOUND,
    ERR_SEAL_JOB_NOT_FOUND,
    GRADE_C,
    JOB_SCHEDULED,
    NON_EXISTENT_UUID,
    QA_HEADERS,
    REBATE_BASIS_PER_CFM,
    SCREENING_PENDING,
    SEAL_STATUS_SEAL_PENDING,
    WARRANTY_NOT_REGISTERED,
    assert_append_only_fields,
    assert_common_fields,
    assert_ordered_by,
    assert_pagination_meta,
    assert_program_ledger,
    assert_request_id,
    factories as f,
    fixtures as fx,
    leakage_per_100_sqft,
    normalize_to_cfm25,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_utility_program_opens_with_a_zeroed_money_ledger(api):
    """Registering a program echoes every declared parameter and opens the ledger at zero.

    PRD 3.1: "A newly registered program opens with `committed_rebate_cents` and
    `paid_rebate_cents` both at 0, `remaining_budget_cents` equal to
    `annual_budget_cents`, and `version` at 1."

    Design: Corner/entities/create_utility_program_returns_full_payload_and_zeroed_money_ledger
    """
    payload = f.utility_program_payload()
    response = api.create_utility_program(payload, ADMIN_HEADERS)
    program = validate_success(response, 201)
    assert_request_id(response.json()["meta"])

    for field, value in payload.items():
        assert program[field] == value, f"{field} was not stored as supplied"
    assert program["rebate_basis"] == REBATE_BASIS_PER_CFM

    assert_program_ledger(program, 0, 0, payload["annual_budget_cents"])
    assert_common_fields(program, expected_version=1)


def test_duct_system_read_back_carries_its_declared_defaults(api):
    """A freshly catalogued duct system reads back with every default the PRD names.

    PRD 3.2: "A new duct system opens with `asbestos_screening_result` at
    `PENDING`, `lab_reference` null, `eligibility_status` at `PENDING_SCREENING`,
    `seal_status` at `SEAL_PENDING`, `sealed_leakage_reduction_cfm` at 0.00,
    `baseline_leakage_cfm25` and `working_leakage_cfm25` both null,
    `active_seal_job_id` null and `version` at 1."

    Design: Corner/entities/get_duct_system_returns_stored_row_with_declared_defaults
    """
    sc = fx.scenario_base(api)
    created = validate_success(
        api.create_duct_system(sc.project_id, f.duct_system_payload(), ADMIN_HEADERS), 201
    )

    duct_system = validate_success(api.get_duct_system(created["id"], ADMIN_HEADERS))
    assert duct_system["id"] == created["id"]
    assert duct_system["project_id"] == sc.project_id
    assert duct_system["system_label"] == "AHU-1"
    assert duct_system["total_register_count"] == 9
    assert duct_system["design_cfm"] == 1200.0
    assert duct_system["asbestos_screening_result"] == SCREENING_PENDING
    assert duct_system["lab_reference"] is None
    assert duct_system["eligibility_status"] == ELIGIBILITY_PENDING_SCREENING
    assert duct_system["exclusion_reason"] is None
    assert duct_system["seal_status"] == SEAL_STATUS_SEAL_PENDING
    assert duct_system["sealed_leakage_reduction_cfm"] == 0.00
    assert duct_system["baseline_leakage_cfm25"] is None
    assert duct_system["working_leakage_cfm25"] is None
    assert duct_system["active_seal_job_id"] is None
    assert_common_fields(duct_system, expected_version=1)

    # "Creation raises the project's `duct_system_count` by 1 and deliberately
    # leaves `eligible_duct_system_count` untouched".
    project = sc.read_project()
    assert project["duct_system_count"] == 1
    assert project["eligible_duct_system_count"] == 0


def test_project_listing_reports_the_filtered_population_not_the_page(api):
    """`total_count` counts the population while `has_more` describes the page.

    PRD 2.3: "`total_count` is the size of the filtered population, not the size
    of the returned page ... `has_more` is true when the sum of `offset` and the
    number of rows actually returned is less than `total_count`, and false
    otherwise."

    Design: Corner/entities/list_projects_paginates_with_total_count_and_has_more
    """
    sc = fx.scenario_base(api)
    fx.add_project(sc, address_line="20 Larkspur Ln")
    fx.add_project(sc, address_line="22 Larkspur Ln")

    first_page, meta = validate_paginated(api.list_projects(ADMIN_HEADERS, limit=2))
    assert len(first_page) == 2
    assert_pagination_meta(meta, limit=2, offset=0, total_count=3, has_more=True)
    assert_ordered_by(first_page, "created_at")

    last_page, meta = validate_paginated(
        api.list_projects(ADMIN_HEADERS, limit=2, offset=2)
    )
    assert len(last_page) == 1
    assert_pagination_meta(meta, limit=2, offset=2, total_count=3, has_more=False)

    assert {row["id"] for row in first_page}.isdisjoint({row["id"] for row in last_page})


def test_reading_an_unknown_seal_job_reports_the_seal_job_not_found_code(api):
    """A well-formed but unknown run identifier is a 404 naming that resource.

    PRD 2.5: "The same precedence applies to `ERR_DUCT_SYSTEM_NOT_FOUND`,
    `ERR_LEAKAGE_TEST_NOT_FOUND`, `ERR_SEAL_JOB_NOT_FOUND` ..."

    Design: Corner/entities/get_seal_job_unknown_uuid_returns_seal_job_not_found
    """
    validate_error(
        api.get_seal_job(NON_EXISTENT_UUID, ADMIN_HEADERS), ERR_SEAL_JOB_NOT_FOUND, 404
    )


def test_reserving_a_measurement_without_a_window_end_is_a_malformed_request(api):
    """A missing required field is rejected without touching the parent row.

    PRD 2.8 rung 5: "**Request validity** — required fields present ... Violations
    are `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/create_leakage_test_missing_window_end_returns_invalid_request
    """
    sc = fx.scenario_eligible_system(api)
    before = sc.read_duct_system()
    # Creation set version 1 and the screening bumped it to 2.
    assert before["version"] == 2

    payload = f.leakage_test_payload(sc.duct_system_id, window_end_at=f.OMIT)
    assert "window_end_at" not in payload
    validate_error(
        api.create_leakage_test(payload, sc.tech_headers), ERR_INVALID_REQUEST, 400
    )

    assert sc.read_duct_system()["version"] == 2, (
        "a rejected reservation must not mutate the duct system"
    )


def test_omitted_optional_inputs_take_their_declared_defaults(api):
    """Leaving an optional input out is not the same as sending a different value.

    PRD 3.1: "`requires_inspector_verification` defaults to true ... and
    `combustion_safety_required` also defaults to true"; "Certification standing
    lives in `certification_status` ... when the field is omitted at registration
    it defaults to `PENDING`. `certification_expires_at` ... is null for a
    technician who has never been certified."

    Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
    """
    program = validate_success(
        api.create_utility_program(
            f.utility_program_payload(
                requires_inspector_verification=f.OMIT, combustion_safety_required=f.OMIT
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert program["requires_inspector_verification"] is True
    assert program["combustion_safety_required"] is True

    technician = validate_success(
        api.create_technician(
            f.technician_payload(
                certification_status=f.OMIT, certification_expires_at=f.OMIT
            ),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert technician["certification_status"] == "PENDING"
    assert technician["certification_expires_at"] is None
    assert technician["open_seal_job_count"] == 0
    assert_common_fields(technician, expected_version=1)


def test_recording_a_reading_normalizes_from_pressure_and_floor_area(api):
    """Recording derives both normalized figures and leaves the ledger alone.

    PRD 3.3: "Step two derives `leakage_per_100_sqft` by dividing the
    **already-rounded** `normalized_leakage_cfm25` from step one by the project's
    `conditioned_floor_area_sqft` expressed in hundreds of square feet"; "Accepting
    a `PRE`-phase measurement is the moment the duct system's ledger is
    established".

    Design: Corner/entities/recorded_leakage_normalization_is_derived_from_pressure_and_floor_area
    """
    sc = fx.scenario_eligible_system(api)
    test = validate_success(
        api.create_leakage_test(f.leakage_test_payload(sc.duct_system_id), sc.tech_headers),
        201,
    )
    validate_success(
        api.pressurize_leakage_test(test["id"], f.pressurize_payload(), sc.tech_headers)
    )
    recorded = validate_success(
        api.record_leakage_test(test["id"], f.record_payload(), sc.tech_headers)
    )

    # 300.0 CFM held at the 25-pascal reference itself normalizes to itself.
    assert recorded["normalized_leakage_cfm25"] == normalize_to_cfm25(300.0, 25.0) == 300.00
    # 2000 conditioned square feet is twenty hundreds of square feet.
    assert recorded["leakage_per_100_sqft"] == leakage_per_100_sqft(300.00, 2000) == 15.00
    assert recorded["measured_leakage_cfm"] == 300.0
    assert recorded["ambient_temp_f"] == 78.0
    assert recorded["performed_by_user_id"] == sc.technician_id
    assert recorded["status"] == "RECORDED"

    assert sc.read_duct_system()["baseline_leakage_cfm25"] is None, (
        "the baseline is established by acceptance, not by recording"
    )


def test_a_booked_run_opens_with_server_minted_curve_state(api):
    """Every curve and warranty field of a new run is minted by the server.

    PRD 3.5: "A successful booking opens the run in status `SCHEDULED` with
    `masked_register_labels` empty, `masked_register_count` at 0, `sample_count`
    at 0, `current_leakage_cfm` null, `target_reached` false, `stall_flag` false,
    `pause_count` at 0, `warranty_status` at `NOT_REGISTERED`,
    `warranty_suspended` false, and `version` at 1."

    Design: Corner/entities/seal_job_system_and_computed_fields_are_server_minted
    """
    sc = fx.scenario_ready_to_inject(api)
    job = fx.schedule_seal_job(sc)

    assert job["status"] == JOB_SCHEDULED
    assert job["masked_register_labels"] == []
    assert job["masked_register_count"] == 0
    assert job["sample_count"] == 0
    assert job["current_leakage_cfm"] is None
    assert job["target_reached"] is False
    assert job["stall_flag"] is False
    assert job["pause_count"] == 0
    assert job["warranty_status"] == WARRANTY_NOT_REGISTERED
    assert job["warranty_suspended"] is False
    assert job["abort_reason"] is None
    assert job["retest_of_job_id"] is None
    assert job["retest_due_at"] is None
    assert job["sealant_lbs_used"] is None
    assert_common_fields(job, expected_version=1)
    # "On startup the logical clock reads exactly `2026-08-01T00:00:00Z`".
    assert job["created_at"] == "2026-08-01T00:00:00.000Z"


def test_cataloguing_a_system_rejects_a_bad_enum_and_a_non_positive_design_flow(api):
    """Enum membership and the strictly-positive design flow are both rung-5 checks.

    PRD 3.2: "`condition_grade`, the field condition assessment, one of `A`, `B`,
    `C` or `FAIL`"; "`design_cfm`, the system's design airflow, which must be
    strictly greater than zero".

    Design: Corner/entities/create_duct_system_rejects_bad_enum_and_non_positive_design_cfm
    """
    sc = fx.scenario_base(api)

    validate_error(
        api.create_duct_system(
            sc.project_id, f.duct_system_payload(condition_grade="Z"), ADMIN_HEADERS
        ),
        ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_duct_system(
            sc.project_id, f.duct_system_payload(design_cfm=0.0), ADMIN_HEADERS
        ),
        ERR_INVALID_REQUEST,
        400,
    )

    accepted = validate_success(
        api.create_duct_system(
            sc.project_id,
            f.duct_system_payload(condition_grade=GRADE_C, design_cfm=800.0),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert accepted["condition_grade"] == GRADE_C
    assert accepted["design_cfm"] == 800.0
    assert sc.read_project()["duct_system_count"] == 1, (
        "only the accepted create may raise the counter"
    )


def test_curve_samples_are_append_only_and_carry_no_version(api):
    """A curve point is an append-only measurement row, not a versioned resource.

    PRD 2.4: "Two record types are append-only measurement rows and therefore
    carry only `id` and `created_at` — they have **no** `updated_at` and **no**
    `version` field at all: the individual leakage-curve samples appended during
    an injection run, and the individual room airflow readings taken during
    balancing."

    Design: Corner/entities/leakage_sample_is_immutable_and_carries_no_version_field
    """
    sc = fx.scenario_injecting_job(api)
    stored = fx.stream_samples(sc, [(1, 300.0, 0, 700.0), (2, 200.0, 240, 720.0)])
    for sample in stored:
        assert_append_only_fields(sample)
        # "For a point whose `sample_seq` is 1 or 2, `seal_rate_cfm_per_min` is null."
        assert sample["seal_rate_cfm_per_min"] is None
        assert sample["cutoff_triggered"] is False
        assert sample["seal_job_id"] == sc.seal_job_id

    rows, _ = validate_paginated(api.list_leakage_samples(sc.seal_job_id, ADMIN_HEADERS))
    assert len(rows) == 2
    # "the leakage curve of a sealing run is returned in ascending `sample_seq` order".
    assert [row["sample_seq"] for row in rows] == [1, 2]
    for row in rows:
        assert_append_only_fields(row)


def test_cataloguing_a_system_under_an_unknown_project_is_a_project_not_found(api):
    """The path entity is resolved before the body is examined at all.

    PRD 2.5: "a request against a project that does not exist fails with
    `ERR_PROJECT_NOT_FOUND` (HTTP 404) before anything in the body is examined."

    Design: Corner/entities/create_duct_system_under_unknown_project_returns_project_not_found
    """
    fx.scenario_base(api)
    validate_error(
        api.create_duct_system(NON_EXISTENT_UUID, f.duct_system_payload(), ADMIN_HEADERS),
        ERR_PROJECT_NOT_FOUND,
        404,
    )


def test_a_claim_naming_a_program_the_project_does_not_use_is_a_mismatch(api):
    """The claim's program must be the one the report's project actually names.

    PRD 3.8: "`utility_program_id`, which must be the very program the report's
    project names in its own `utility_program_id`; a different program, or a
    project that has no program at all, is refused with `ERR_PROGRAM_MISMATCH`."

    Design: Corner/entities/rebate_claim_against_foreign_program_returns_program_mismatch
    """
    sc = fx.scenario_issued_report(api)
    foreign = validate_success(
        api.create_utility_program(
            f.utility_program_payload(name="Suburban Gas 2026", annual_budget_cents=9000000),
            ADMIN_HEADERS,
        ),
        201,
    )

    validate_error(
        api.create_rebate_claim(
            f.rebate_claim_payload(sc.report_id, foreign["id"]), ADMIN_HEADERS
        ),
        ERR_PROGRAM_MISMATCH,
        422,
    )

    untouched = validate_success(api.get_utility_program(foreign["id"], QA_HEADERS))
    assert_program_ledger(untouched, 0, 0, 9000000)
    assert untouched["version"] == 1
