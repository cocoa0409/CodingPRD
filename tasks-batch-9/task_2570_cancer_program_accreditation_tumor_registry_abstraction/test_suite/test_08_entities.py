"""Creation defaults, echoed reads, paging, and the shape of a bad request."""

from test_helpers import (
    ApiErrorId,
    PLATFORM_ADMIN,
    REGISTRY_MANAGER,
    assert_abstractor,
    assert_created,
    assert_ok,
    assert_program,
    factories as f,
    get_success_data,
    make_accreditation_coordinator_headers,
    make_qa_reviewer_headers,
    make_registry_abstractor_headers,
    validate_error,
    validate_paginated,
)

COORDINATOR = make_accreditation_coordinator_headers("coord-lee")
UNKNOWN_CASE_ID = "00000000-0000-4000-8000-000000000abc"
UNKNOWN_SOURCE_ID = "00000000-0000-4000-8000-0000000000ff"
UNKNOWN_PROGRAM_ID = "00000000-0000-4000-8000-0000000000aa"


def _program_payload(**overrides):
    base = dict(
        name="Northside Cancer Center",
        coc_program_id="COC-1456N",
        annual_analytic_caseload=300,
        reference_year=2018,
        timeliness_standard_days=180,
    )
    base.update(overrides)
    return f.program_payload(**base)


def _program(api, **overrides):
    return get_success_data(api.create_program(_program_payload(**overrides), PLATFORM_ADMIN))


def _source(api, program_id):
    return get_success_data(
        api.create_casefinding_source(
            f.casefinding_source_payload(
                program_id, source_type="PATHOLOGY", expected_monthly_volume=40
            ),
            REGISTRY_MANAGER,
        )
    )


def _entry(api, source_id, mrn, **overrides):
    payload = f.casefinding_entry_payload(
        patient_mrn=mrn,
        accession_date="2026-08-03",
        primary_site_code="C50.9",
        histology_code="8500/3",
        behavior_code="MALIGNANT_3",
        diagnosis_date="2026-07-01",
        first_contact_date="2026-07-05",
        diagnosed_at_facility=True,
        first_treatment_at_facility=True,
        **overrides,
    )
    return get_success_data(api.create_casefinding_entry(source_id, payload, REGISTRY_MANAGER))


def _mint(api, entry_id):
    return get_success_data(
        api.reportability_decision(
            entry_id, f.reportability_decision_payload("REPORTABLE"), REGISTRY_MANAGER
        )
    )["created_case_id"]


def test_new_program_opens_with_every_derived_field_at_its_documented_start(api):
    """The 201 body already carries the whole derived baseline, not nulls.

    PRD 2.5: "A new program opens in `accreditation_state` `ACCREDITED` with
    `registry_posture` `OPEN`, every derived count at zero, both follow-up rates
    at 100.0, `lost_to_follow_up_pct` at 0.0, `survey_date` and `survey_year`
    null, `next_survey_due_year` set to the `reference_year` plus 3, and its
    `required_sessions_12mo` already derived from the caseload as described in
    §3.7."

    Design: Corner/entities/program_creation_returns_accreditation_defaults_and_zeroed_counters
    """
    program = assert_program(assert_created(api.create_program(_program_payload(), PLATFORM_ADMIN)))

    assert program["accreditation_state"] == "ACCREDITED"
    assert program["registry_posture"] == "OPEN"
    assert program["survey_date"] is None
    assert program["survey_year"] is None
    assert program["next_survey_due_year"] == 2021
    assert program["identified_case_count"] == 0
    assert program["open_backlog_count"] == 0
    assert program["overdue_backlog_count"] == 0
    assert program["follow_up_rate_coc_pct"] == 100.0
    assert program["follow_up_rate_state_pct"] == 100.0
    assert program["lost_to_follow_up_pct"] == 0.0
    assert program["credited_sessions_12mo"] == 0
    assert program["required_sessions_12mo"] == 12
    assert program["conference_frequency_compliant"] is False
    assert program["coordinator_attendance_compliant"] is False
    assert program["open_critical_deficiency_count"] == 0
    assert program["version"] == 1


def test_registrar_read_echoes_its_inputs_and_the_opening_derived_figures(api):
    """The read path returns the stored row, target and expiry included.

    PRD 2.6: "A new registrar starts with `employment_status` `ACTIVE`, with
    `assigned_open_case_count`, `lifetime_discrepancy_points`, `audit_fail_streak`,
    and `completed_cases_30d` all at zero, with both `quality_score_rolling_90d`
    and `quality_score_cumulative` at 100.0, and with `productivity_rate_per_day`
    at 0.0 — which, since no work has been approved yet, makes the opening
    `productivity_status` `BELOW` rather than `MEETS`."

    Design: Corner/entities/abstractor_retrieval_returns_stored_record
    """
    program = _program(api)
    created = get_success_data(
        api.create_abstractor(
            f.abstractor_payload(
                program["id"],
                name="Dana Reyes",
                credential="CTR",
                productivity_target_cases_per_day=2,
                certification_expires_on="2027-12-31",
            ),
            REGISTRY_MANAGER,
        )
    )

    registrar = assert_abstractor(assert_ok(api.get_abstractor(created["id"], REGISTRY_MANAGER)))

    assert registrar["id"] == created["id"]
    assert registrar["program_id"] == program["id"]
    assert registrar["name"] == "Dana Reyes"
    assert registrar["credential"] == "CTR"
    assert registrar["productivity_target_cases_per_day"] == 2
    assert registrar["certification_expires_on"] == "2027-12-31"
    assert registrar["employment_status"] == "ACTIVE"
    assert registrar["assigned_open_case_count"] == 0
    assert registrar["lifetime_discrepancy_points"] == 0
    assert registrar["audit_fail_streak"] == 0
    assert registrar["quality_score_rolling_90d"] == 100.0
    assert registrar["quality_score_cumulative"] == 100.0
    assert registrar["completed_cases_30d"] == 0
    assert registrar["productivity_rate_per_day"] == 0.0
    assert registrar["productivity_status"] == "BELOW"


def test_case_listing_reports_the_unpaginated_total_across_two_pages(api):
    """Three cases read two at a time: the count is the filtered total, not the page.

    PRD 2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count` is
    the size of the full filtered result set before pagination is applied and
    `has_more` indicates whether records remain beyond the current page."

    Design: Corner/entities/case_listing_paginates_with_total_count_and_has_more
    """
    program = _program(api)
    source = _source(api, program["id"])
    expected = {
        _mint(api, _entry(api, source["id"], "MRN-0001")["id"]),
        _mint(api, _entry(api, source["id"], "MRN-0002")["id"]),
        _mint(api, _entry(api, source["id"], "MRN-0003")["id"]),
    }

    first_rows, first_meta = validate_paginated(
        api.list_cases(REGISTRY_MANAGER, {"program_id": program["id"], "limit": 2, "offset": 0})
    )
    second_rows, second_meta = validate_paginated(
        api.list_cases(REGISTRY_MANAGER, {"program_id": program["id"], "limit": 2, "offset": 2})
    )

    assert len(first_rows) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    assert len(second_rows) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 2

    seen = [row["id"] for row in first_rows + second_rows]
    assert len(seen) == len(set(seen))
    assert set(seen) == expected
    for row in first_rows + second_rows:
        assert row["case_state"] == "IDENTIFIED"
        assert row["submission_state"] == "NOT_SUBMITTED"


def test_unknown_case_id_returns_the_per_resource_not_found_code(api):
    """A well-formed but unused UUID is a 404 naming the case, not a blank 200.

    PRD 2.3: "The per-resource codes are `ERR_PROGRAM_NOT_FOUND`,
    `ERR_ABSTRACTOR_NOT_FOUND`, `ERR_SOURCE_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`,
    `ERR_CASE_NOT_FOUND`, `ERR_CONTACT_NOT_FOUND`, `ERR_ABSTRACTION_NOT_FOUND`,
    `ERR_AUDIT_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_SUBMISSION_NOT_FOUND`,
    `ERR_SUBMISSION_ITEM_NOT_FOUND`, `ERR_DEFICIENCY_NOT_FOUND`, and
    `ERR_MEASURE_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/entities/case_detail_with_unknown_id_returns_not_found
    """
    error = validate_error(
        api.get_case(UNKNOWN_CASE_ID, REGISTRY_MANAGER),
        ApiErrorId.ERR_CASE_NOT_FOUND.value,
        404,
    )

    assert isinstance(error["message"], str)
    assert error["message"] != ""


def test_registrar_created_without_a_credential_is_a_request_shape_failure(api):
    """credential has no default, so its absence is a 400 and writes nothing.

    PRD 2.11: "Request-shape validation, which yields `ERR_INVALID_REQUEST` (HTTP
    400), covers all of the following: every field the operation declares as
    required is present; every enum-typed field carries one of its declared
    values; dates are ISO 8601 calendar dates and timestamps are ISO 8601 UTC
    instants; counts and cent amounts are non-negative integers; percentages are
    numbers within 0 through 100 inclusive; and end bounds respect their start
    bounds, meaning a session's `end_at` must be strictly after its `start_at`, a
    submission's `period_end` must be on or after its `period_start`, and an
    audit's `window_end` must be on or after its `window_start`."

    Design: Corner/entities/abstractor_create_missing_credential_is_rejected
    """
    program = _program(api)

    validate_error(
        api.create_abstractor(
            f.abstractor_payload(
                program["id"],
                name="Dana Reyes",
                credential=f.OMIT,
                productivity_target_cases_per_day=2,
                certification_expires_on="2027-12-31",
            ),
            REGISTRY_MANAGER,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _rows, meta = validate_paginated(
        api.list_abstractors(REGISTRY_MANAGER, {"program_id": program["id"]})
    )
    assert meta["total_count"] == 0


def test_omitted_timeliness_standard_defaults_to_180_and_dates_a_case(api):
    """The default is visible on the program and again in the case's due date.

    PRD 2.5: "A `PlatformAdmin` registers one with a `name`, a `coc_program_id`
    identifying it to the Commission on Cancer, an `annual_analytic_caseload`, and
    a `reference_year`, and may optionally supply `timeliness_standard_days` — the
    number of days after first contact within which an abstract must be completed,
    which defaults to 180 and may not be set below 30."

    PRD 2.6: "A case's `abstract_due_date` is its `first_contact_date` advanced by
    the program's `timeliness_standard_days`."

    Design: Corner/entities/program_create_omitting_timeliness_standard_days_applies_default_180
    """
    program = _program(
        api,
        name="Harborview Cancer Program",
        coc_program_id="COC-2201H",
        timeliness_standard_days=f.OMIT,
    )
    source = _source(api, program["id"])
    case_id = _mint(api, _entry(api, source["id"], "MRN-0001")["id"])

    reread = assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))
    assert reread["timeliness_standard_days"] == 180

    case = assert_ok(api.get_case(case_id, REGISTRY_MANAGER))
    assert case["abstract_due_date"] == "2027-01-01"
    assert case["days_to_due"] == 153
    assert case["timeliness_status"] == "ON_TIME"


def test_posted_referral_lag_is_discarded_and_recomputed_from_the_dates(api):
    """A posted 999 must not reach the class-of-case derivation.

    PRD 2.6: "The registrar may also raise `ambiguous_terminology_flag`, which
    defaults to false, to mark pathology text that needs judgement, and may
    include `referral_lag_days` in the payload, though the server always derives
    that value itself."

    PRD 2.6: "The first derives `referral_lag_days` as the whole number of days
    from `diagnosis_date` to `first_contact_date` and then fixes
    `class_of_case_code` by the first matching case of five: an entry both
    diagnosed at the facility and first-treated at the facility is `CLASS_10`; one
    diagnosed at the facility but not first-treated there is `CLASS_00`; one not
    diagnosed at the facility but first-treated there whose referral lag is 120
    days or fewer is `CLASS_20`; one not diagnosed at the facility but
    first-treated there whose referral lag exceeds 120 days is `CLASS_31`; and
    anything else is `CLASS_40`."

    Design: Corner/entities/entry_computed_referral_lag_days_input_ignored
    """
    program = _program(api)
    source = _source(api, program["id"])

    entry = assert_created(
        api.create_casefinding_entry(
            source["id"],
            f.casefinding_entry_payload(
                patient_mrn="MRN-0007",
                accession_date="2026-08-03",
                primary_site_code="C50.9",
                histology_code="8500/3",
                behavior_code="MALIGNANT_3",
                diagnosis_date="2026-07-01",
                first_contact_date="2026-07-05",
                diagnosed_at_facility=False,
                first_treatment_at_facility=True,
                referral_lag_days=999,
            ),
            REGISTRY_MANAGER,
        )
    )

    assert entry["referral_lag_days"] == 4
    assert entry["class_of_case_code"] == "CLASS_20"
    assert entry["analytic_flag"] is True
    assert entry["program_id"] == program["id"]

    reread = assert_ok(api.get_casefinding_source(source["id"], REGISTRY_MANAGER))
    assert reread["program_id"] == program["id"]
    stored = assert_ok(api.get_casefinding_entry(entry["id"], REGISTRY_MANAGER))
    assert stored["referral_lag_days"] == 4


def test_credential_outside_its_enum_is_rejected_before_anything_is_written(api):
    """A plausible but undeclared credential value is a shape failure.

    PRD 2.6: "Registrars are created by a `RegistryManager` against a
    `program_id`, each with a `name`, a `credential` of `CTR`, `NON_CTR`, or
    `TRAINEE`, a contracted `productivity_target_cases_per_day` that must be
    greater than zero, and a `certification_expires_on` date written as a plain
    ISO calendar date."

    Design: Corner/entities/abstractor_create_with_invalid_credential_enum_rejected
    """
    program = _program(api)

    validate_error(
        api.create_abstractor(
            f.abstractor_payload(
                program["id"],
                name="Dana Reyes",
                credential="REGISTERED",
                productivity_target_cases_per_day=2,
                certification_expires_on="2027-12-31",
            ),
            REGISTRY_MANAGER,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _rows, meta = validate_paginated(
        api.list_abstractors(REGISTRY_MANAGER, {"program_id": program["id"]})
    )
    assert meta["total_count"] == 0


def test_zero_length_conference_session_is_a_shape_failure_not_a_slot_conflict(api):
    """end_at equal to start_at never reaches the overlap check.

    PRD 2.11: "and end bounds respect their start bounds, meaning a session's
    `end_at` must be strictly after its `start_at`, a submission's `period_end`
    must be on or after its `period_start`, and an audit's `window_end` must be on
    or after its `window_start`."

    Design: Corner/entities/conference_session_with_end_at_not_after_start_at_rejected
    """
    program = _program(api)

    error = validate_error(
        api.create_conference_session(
            f.conference_session_payload(
                program["id"],
                start_at="2026-07-15T13:00:00Z",
                end_at="2026-07-15T13:00:00Z",
                required_disciplines=["SURGERY", "MEDICAL_ONCOLOGY", "RADIATION_ONCOLOGY"],
            ),
            COORDINATOR,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    assert error["error_id"] != ApiErrorId.ERR_CONFERENCE_SLOT_CONFLICT.value

    _rows, meta = validate_paginated(
        api.list_conference_sessions(COORDINATOR, {"program_id": program["id"]})
    )
    assert meta["total_count"] == 0


def test_follow_up_contacts_are_appended_events_and_never_walk_the_date_back(api):
    """A second, non-qualifying contact still stamps vital status; the row is kept.

    PRD 2.8: "A contact carries `counts_for_follow_up` true when its `outcome` is
    `CONTACT_MADE` or `DECEASED` and false for `NO_RESPONSE` or `MOVED_UNKNOWN` —
    only qualifying contacts advance the case's `last_contact_date`, which is set
    to the later of its existing value and the new `contact_date` so that
    back-dated entries cannot walk it backwards."

    PRD 2.8: "Every contact writes `vital_status` onto the case from
    `vital_status_at_contact`, then recomputes the case's follow-up standing and
    the program's follow-up rates and posture."

    Design: Corner/entities/follow_up_contact_is_immutable_event_with_no_version_field
    """
    program = _program(api)
    author = get_success_data(
        api.create_abstractor(
            f.abstractor_payload(program["id"], name="Dana Reyes"), REGISTRY_MANAGER
        )
    )
    reviewer = get_success_data(
        api.create_abstractor(
            f.abstractor_payload(program["id"], name="Priya Raman"), REGISTRY_MANAGER
        )
    )
    source = _source(api, program["id"])
    case_id = _mint(api, _entry(api, source["id"], "MRN-0001")["id"])
    case = get_success_data(
        api.assign_case(case_id, f.assign_payload(author["id"]), REGISTRY_MANAGER)
    )
    abstraction = get_success_data(
        api.create_abstraction(
            f.abstraction_payload(
                case_id,
                author["id"],
                case["version"],
                first_treatment_date="2026-07-10",
                diagnostic_confirmation_code="POSITIVE_HISTOLOGY",
                last_contact_date="2026-07-20",
            ),
            make_registry_abstractor_headers(author["id"]),
        )
    )
    get_success_data(
        api.submit_qa(
            abstraction["id"],
            f.submit_qa_payload(submit_note=f.OMIT),
            make_registry_abstractor_headers(author["id"]),
        )
    )
    get_success_data(
        api.qa_decision(
            abstraction["id"],
            f.qa_decision_payload("APPROVED"),
            make_qa_reviewer_headers(reviewer["id"]),
        )
    )
    first = assert_created(
        api.create_follow_up_contact(
            case_id,
            f.follow_up_contact_payload(
                contact_date="2026-07-20",
                contact_method="CLINIC_VISIT",
                outcome="CONTACT_MADE",
                vital_status_at_contact="ALIVE",
            ),
            make_registry_abstractor_headers(author["id"]),
        )
    )

    second = assert_created(
        api.create_follow_up_contact(
            case_id,
            f.follow_up_contact_payload(
                contact_date="2026-07-28",
                contact_method="PHONE",
                outcome="NO_RESPONSE",
                vital_status_at_contact="UNKNOWN",
            ),
            make_registry_abstractor_headers(author["id"]),
        )
    )

    assert "version" not in first
    assert "version" not in second
    assert first["counts_for_follow_up"] is True
    assert second["counts_for_follow_up"] is False

    rows, meta = validate_paginated(
        api.list_follow_up_contacts(REGISTRY_MANAGER, {"case_id": case_id})
    )
    assert meta["total_count"] == 2
    kept = [row for row in rows if row["id"] == first["id"]][0]
    assert kept["contact_method"] == "CLINIC_VISIT"
    assert kept["outcome"] == "CONTACT_MADE"

    reread = assert_ok(api.get_case(case_id, REGISTRY_MANAGER))
    assert reread["last_contact_date"] == "2026-07-20"
    assert reread["vital_status"] == "UNKNOWN"


def test_entry_under_an_unknown_source_resolves_the_path_id_first(api):
    """A perfect body cannot rescue an unresolvable path parent.

    PRD 2.3: "Where two identifiers appear in one path — a submission item
    addressed inside its batch — they are resolved strictly left to right, and the
    first identifier that does not resolve determines the error: an unknown
    `{submissionId}` yields `ERR_SUBMISSION_NOT_FOUND` before the `{itemId}` is
    ever looked up."

    Design: Corner/entities/entry_create_under_unknown_source_returns_not_found
    """
    program = _program(api)

    validate_error(
        api.create_casefinding_entry(
            UNKNOWN_SOURCE_ID,
            f.casefinding_entry_payload(
                patient_mrn="MRN-0001",
                accession_date="2026-08-03",
                diagnosis_date="2026-07-01",
                first_contact_date="2026-07-05",
            ),
            REGISTRY_MANAGER,
        ),
        ApiErrorId.ERR_SOURCE_NOT_FOUND.value,
        404,
    )

    _rows, meta = validate_paginated(
        api.list_casefinding_entries(REGISTRY_MANAGER, {"program_id": program["id"]})
    )
    assert meta["total_count"] == 0


def test_registrar_pointing_at_an_unknown_program_raises_the_parents_code(api):
    """The parent arrives in the body here, and it still yields the parent's 404.

    PRD 2.3: "Foreign keys supplied in a request body are resolved after every
    path identifier has resolved, and they are checked in a fixed declaration
    order: `program_id` against a cancer program, then `source_id` against a
    casefinding source, then `case_id` against a tumor case, then `abstractor_id`
    against a registrar, then `entry_id` against a casefinding entry, then
    `source_measure_id` against a quality measure."

    Design: Corner/entities/abstractor_create_with_unknown_program_fk_returns_not_found
    """
    validate_error(
        api.create_abstractor(
            f.abstractor_payload(
                UNKNOWN_PROGRAM_ID,
                name="Dana Reyes",
                credential="CTR",
                productivity_target_cases_per_day=2,
                certification_expires_on="2027-12-31",
            ),
            REGISTRY_MANAGER,
        ),
        ApiErrorId.ERR_PROGRAM_NOT_FOUND.value,
        404,
    )

    _rows, meta = validate_paginated(api.list_abstractors(REGISTRY_MANAGER))
    assert meta["total_count"] == 0


def test_reusing_a_coc_program_id_is_refused_however_different_the_rest_is(api):
    """The identifier is global, so the second registration cannot land.

    PRD 2.5: "The `coc_program_id` must be unique across all programs; a repeat is
    rejected with `ERR_DUPLICATE_COC_PROGRAM_ID`."

    Design: Corner/entities/program_with_duplicate_coc_program_id_rejected
    """
    first = _program(api)

    validate_error(
        api.create_program(
            _program_payload(
                name="Southbank Cancer Institute",
                annual_analytic_caseload=900,
                reference_year=2020,
                timeliness_standard_days=120,
            ),
            PLATFORM_ADMIN,
        ),
        ApiErrorId.ERR_DUPLICATE_COC_PROGRAM_ID.value,
        409,
    )

    rows, meta = validate_paginated(api.list_programs(PLATFORM_ADMIN))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
