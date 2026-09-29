"""Refusals: the exact code, the exact band, and the untouched state behind it."""

from test_helpers import (
    ApiErrorId,
    PLATFORM_ADMIN,
    REGISTRY_MANAGER,
    assert_casefinding_entry,
    assert_conference_session,
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
    validate_success,
)

COORDINATOR = make_accreditation_coordinator_headers("user-coord-1")
UNKNOWN_CASE_ID = "00000000-0000-0000-0000-0000000000ff"
UNKNOWN_ABSTRACTOR_ID = "00000000-0000-0000-0000-0000000000ee"


def _program(api, **overrides):
    base = dict(
        name="Northside Cancer Center",
        coc_program_id="COC-1456N",
        annual_analytic_caseload=300,
        reference_year=2018,
        timeliness_standard_days=180,
    )
    base.update(overrides)
    return get_success_data(api.create_program(f.program_payload(**base), PLATFORM_ADMIN))


def _registrar(api, program_id, name):
    return get_success_data(
        api.create_abstractor(
            f.abstractor_payload(
                program_id,
                name=name,
                credential="CTR",
                productivity_target_cases_per_day=2,
                certification_expires_on="2027-12-31",
            ),
            REGISTRY_MANAGER,
        )
    )


def _source(api, program_id):
    return get_success_data(
        api.create_casefinding_source(
            f.casefinding_source_payload(
                program_id, source_type="PATHOLOGY", expected_monthly_volume=40
            ),
            REGISTRY_MANAGER,
        )
    )


def _entry_payload(mrn="MRN-0001", **overrides):
    base = dict(
        patient_mrn=mrn,
        accession_date="2026-08-03",
        primary_site_code="C50.9",
        histology_code="8500/3",
        behavior_code="MALIGNANT_3",
        diagnosis_date="2026-07-01",
        first_contact_date="2026-07-05",
        diagnosed_at_facility=True,
        first_treatment_at_facility=True,
    )
    base.update(overrides)
    return f.casefinding_entry_payload(**base)


def _entry(api, source_id, mrn="MRN-0001", **overrides):
    return get_success_data(
        api.create_casefinding_entry(source_id, _entry_payload(mrn, **overrides), REGISTRY_MANAGER)
    )


def _mint(api, entry_id):
    return get_success_data(
        api.reportability_decision(
            entry_id, f.reportability_decision_payload("REPORTABLE"), REGISTRY_MANAGER
        )
    )["created_case_id"]


def test_a_pre_reference_year_entry_may_only_be_ruled_non_reportable(api):
    """The override reason cannot buy a REPORTABLE verdict on a 2017 diagnosis.

    PRD 2.6: "If the `diagnosis_date` falls before January 1 of the program's
    `reference_year`, the suggestion is `NON_REPORTABLE` with reason
    `BEFORE_REFERENCE_YEAR`."

    PRD 2.6: "A `REPORTABLE` determination additionally requires that the entry's
    `diagnosis_date` be on or after January 1 of the program's `reference_year`; an
    earlier diagnosis is rejected with `ERR_DIAGNOSIS_BEFORE_REFERENCE_YEAR` (HTTP
    422)."

    Design: Corner/validations/reportable_decision_on_pre_reference_year_entry_rejected
    """
    program = _program(api)
    source = _source(api, program["id"])
    entry = assert_casefinding_entry(
        assert_created(
            api.create_casefinding_entry(
                source["id"],
                _entry_payload(
                    "MRN-0009", diagnosis_date="2017-06-10", first_contact_date="2017-06-15"
                ),
                REGISTRY_MANAGER,
            )
        )
    )
    assert entry["suggested_reportability"] == "NON_REPORTABLE"
    assert entry["suggested_reason_code"] == "BEFORE_REFERENCE_YEAR"

    validate_error(
        api.reportability_decision(
            entry["id"],
            f.reportability_decision_payload(
                "REPORTABLE", override_reason_code="REGISTRAR_JUDGEMENT"
            ),
            REGISTRY_MANAGER,
        ),
        ApiErrorId.ERR_DIAGNOSIS_BEFORE_REFERENCE_YEAR.value,
        422,
    )

    refused = assert_ok(api.get_casefinding_entry(entry["id"], REGISTRY_MANAGER))
    assert refused["reportability_state"] == "PENDING_REVIEW"
    assert refused["created_case_id"] is None
    assert assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))["identified_case_count"] == 0

    ruled = assert_ok(
        api.reportability_decision(
            entry["id"],
            f.reportability_decision_payload(
                "NON_REPORTABLE", decision_reason_code="BEFORE_REFERENCE_YEAR"
            ),
            REGISTRY_MANAGER,
        )
    )
    assert ruled["reportability_state"] == "NON_REPORTABLE"
    assert ruled["created_case_id"] is None
    assert assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))["identified_case_count"] == 0


def test_a_registrar_from_another_program_cannot_take_the_case(api):
    """Both ids resolve, so the mismatch is a conflict and not a not-found.

    PRD 3.2: "The registrar must be `ACTIVE` (`ERR_ABSTRACTOR_NOT_ACTIVE`), must
    hold a credential that has not lapsed as of the logical clock date
    (`ERR_ABSTRACTOR_CERTIFICATION_EXPIRED`), and must belong to the same program
    as the case (`ERR_ABSTRACTOR_PROGRAM_MISMATCH`)."

    Design: Corner/validations/assign_with_abstractor_from_another_program_rejected
    """
    program_a = _program(api)
    program_b = _program(api, name="Lakeside Cancer Institute", coc_program_id="COC-2200L")
    foreign = _registrar(api, program_b["id"], "Sam Okafor")
    source = _source(api, program_a["id"])
    case_id = _mint(api, _entry(api, source["id"])["id"])
    before = assert_ok(api.get_case(case_id, REGISTRY_MANAGER))

    error = validate_error(
        api.assign_case(case_id, f.assign_payload(foreign["id"]), REGISTRY_MANAGER),
        ApiErrorId.ERR_ABSTRACTOR_PROGRAM_MISMATCH.value,
        409,
    )
    assert error["error_id"] != ApiErrorId.ERR_ABSTRACTOR_NOT_FOUND.value

    case = assert_ok(api.get_case(case_id, REGISTRY_MANAGER))
    assert case["case_state"] == "IDENTIFIED"
    assert case["assigned_abstractor_id"] is None
    assert case["version"] == before["version"]
    assert assert_ok(api.get_abstractor(foreign["id"], REGISTRY_MANAGER))[
        "assigned_open_case_count"
    ] == 0


def test_the_stale_case_version_outranks_the_case_state_and_ownership_gates(api):
    """Assign then unassign breaks three rules at once; concurrency is checked first.

    PRD 2.11: "The bands, from first-evaluated to last, are: authentication of the
    two headers; authorization of the role against the endpoint; request shape;
    existence of path identifiers, then existence of body foreign keys, then
    membership of ids inside a batched payload; optimistic concurrency; state
    preconditions; safety and compliance gates; temporal gates; referential and
    uniqueness constraints; and finally fiscal gates."

    Design: Corner/validations/stale_case_version_outranks_case_state_check_on_abstraction_create
    """
    program = _program(api)
    registrar = _registrar(api, program["id"], "Dana Reyes")
    source = _source(api, program["id"])
    case_id = _mint(api, _entry(api, source["id"])["id"])
    assigned = get_success_data(
        api.assign_case(case_id, f.assign_payload(registrar["id"]), REGISTRY_MANAGER)
    )
    released = get_success_data(
        api.unassign_case(
            case_id,
            f.unassign_payload(unassign_reason="Registrar reassigned to backlog triage"),
            REGISTRY_MANAGER,
        )
    )
    assert released["version"] == assigned["version"] + 1

    error = validate_error(
        api.create_abstraction(
            f.abstraction_payload(
                case_id,
                registrar["id"],
                assigned["version"],
                first_treatment_date="2026-07-10",
                diagnostic_confirmation_code="POSITIVE_HISTOLOGY",
                last_contact_date="2026-07-20",
            ),
            make_registry_abstractor_headers(registrar["id"]),
        ),
        ApiErrorId.ERR_STALE_CASE_VERSION.value,
        412,
    )
    assert error["error_id"] != ApiErrorId.ERR_CASE_NOT_ABSTRACTABLE.value
    assert error["error_id"] != ApiErrorId.ERR_NOT_ASSIGNED_ABSTRACTOR.value

    rows, meta = validate_paginated(api.list_abstractions(REGISTRY_MANAGER, {"case_id": case_id}))
    assert meta["total_count"] == 0
    assert rows == []
    assert assert_ok(api.get_case(case_id, REGISTRY_MANAGER))["case_state"] == "IDENTIFIED"
    assert assert_ok(api.get_abstractor(registrar["id"], REGISTRY_MANAGER))[
        "assigned_open_case_count"
    ] == 0


def test_the_unknown_case_in_the_path_is_reported_before_the_unknown_body_id(api):
    """Two unresolvable ids, and only the path one is named.

    PRD 2.3: "Foreign keys supplied in a request body are resolved after every path
    identifier has resolved, and they are checked in a fixed declaration order:
    `program_id` against a cancer program, then `source_id` against a casefinding
    source, then `case_id` against a tumor case, then `abstractor_id` against a
    registrar, then `entry_id` against a casefinding entry, then
    `source_measure_id` against a quality measure."

    Design: Corner/validations/unknown_case_path_id_outranks_unknown_body_abstractor_id
    """
    error = validate_error(
        api.assign_case(
            UNKNOWN_CASE_ID, f.assign_payload(UNKNOWN_ABSTRACTOR_ID), REGISTRY_MANAGER
        ),
        ApiErrorId.ERR_CASE_NOT_FOUND.value,
        404,
    )

    assert error["error_id"] != ApiErrorId.ERR_ABSTRACTOR_NOT_FOUND.value
    assert isinstance(error["message"], str)
    assert error["message"] != ""


def test_a_contact_dated_after_the_logical_clock_or_before_diagnosis_is_refused(api):
    """One day past the clock and one day before diagnosis fail the same way.

    PRD 2.8: "The `contact_date` must be neither in the future relative to the
    logical clock date nor earlier than the case's `diagnosis_date`, and either
    violation is `ERR_CONTACT_DATE_INVALID`."

    Design: Corner/validations/future_follow_up_contact_date_rejected
    """
    program = _program(api)
    author = _registrar(api, program["id"], "Dana Reyes")
    reviewer = _registrar(api, program["id"], "Priya Raman")
    source = _source(api, program["id"])
    case_id = _mint(api, _entry(api, source["id"])["id"])
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

    validate_error(
        api.create_follow_up_contact(
            case_id,
            f.follow_up_contact_payload(contact_date="2026-08-02", contact_method="PHONE"),
            REGISTRY_MANAGER,
        ),
        ApiErrorId.ERR_CONTACT_DATE_INVALID.value,
        422,
    )
    validate_error(
        api.create_follow_up_contact(
            case_id,
            f.follow_up_contact_payload(contact_date="2026-06-30", contact_method="PHONE"),
            REGISTRY_MANAGER,
        ),
        ApiErrorId.ERR_CONTACT_DATE_INVALID.value,
        422,
    )

    reread = assert_ok(api.get_case(case_id, REGISTRY_MANAGER))
    assert reread["last_contact_date"] is None
    assert reread["vital_status"] == "UNKNOWN"

    rows, meta = validate_paginated(
        api.list_follow_up_contacts(REGISTRY_MANAGER, {"case_id": case_id})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_a_twenty_nine_minute_pathologist_does_not_cover_the_discipline(api):
    """Every required discipline has a body in the room, and quorum still fails.

    PRD 3.7: "An attendance qualifies only when its `attended_minutes` is at least
    30, so an attendee present for exactly 30 minutes qualifies and one present for
    29 does not."

    PRD 3.7: "Quorum is met when `cases_presented_count` is greater than zero, when
    every discipline in `required_disciplines` appears among the disciplines of the
    qualifying attendances, and when the rounded `prospective_case_ratio` is at
    least 0.80 — a ratio of exactly 0.800 meets the standard."

    Design: Corner/validations/attendance_of_twenty_nine_minutes_leaves_discipline_uncovered_and_credit_rejected
    """
    program = _program(api)
    session = get_success_data(
        api.create_conference_session(
            f.conference_session_payload(
                program["id"],
                start_at="2026-07-15T13:00:00Z",
                end_at="2026-07-15T14:30:00Z",
                required_disciplines=[
                    "SURGERY",
                    "MEDICAL_ONCOLOGY",
                    "RADIATION_ONCOLOGY",
                    "PATHOLOGY",
                ],
            ),
            COORDINATOR,
        )
    )
    get_success_data(
        api.record_attendance(
            session["id"],
            f.attendance_payload("DR-SURG-1", "SURGERY", 45, is_required_coordinator=True),
            COORDINATOR,
        )
    )
    for ref, discipline in (
        ("DR-MEDONC-1", "MEDICAL_ONCOLOGY"),
        ("DR-RADONC-1", "RADIATION_ONCOLOGY"),
    ):
        get_success_data(
            api.record_attendance(
                session["id"], f.attendance_payload(ref, discipline, 45), COORDINATOR
            )
        )
    get_success_data(
        api.record_attendance(
            session["id"], f.attendance_payload("DR-PATH-1", "PATHOLOGY", 29), COORDINATOR
        )
    )

    held = assert_conference_session(
        assert_ok(api.hold_session(session["id"], f.hold_session_payload(10, 9), COORDINATOR))
    )
    assert held["quorum_met"] is False
    assert held["prospective_case_ratio"] == 0.9

    validate_error(
        api.credit_session(
            session["id"],
            f.credit_session_payload("CREDIT", credit_note="Quarterly tumour board"),
            COORDINATOR,
        ),
        ApiErrorId.ERR_CONFERENCE_QUORUM_NOT_MET.value,
        409,
    )

    reread = assert_ok(api.get_conference_session(session["id"], COORDINATOR))
    assert reread["session_state"] == "HELD"
    assert reread["credited_on"] is None

    reread_program = assert_program(assert_ok(api.get_program(program["id"], REGISTRY_MANAGER)))
    assert reread_program["credited_sessions_12mo"] == 0
    assert reread_program["conference_frequency_compliant"] is False


def test_the_accession_date_is_not_part_of_the_duplicate_key(api):
    """A re-listed report duplicates; a second primary site on the same chart does not.

    PRD 2.6: "The combination of `source_id`, `patient_mrn`, `primary_site_code`,
    and `diagnosis_date` must be unique across all entries; a repeat is rejected
    with `ERR_DUPLICATE_CASEFINDING_ENTRY`."

    Design: Corner/validations/duplicate_casefinding_entry_on_same_natural_key_rejected
    """
    program = _program(api)
    source = _source(api, program["id"])
    _entry(api, source["id"], "MRN-0001")

    validate_error(
        api.create_casefinding_entry(
            source["id"],
            _entry_payload("MRN-0001", accession_date="2026-08-09"),
            REGISTRY_MANAGER,
        ),
        ApiErrorId.ERR_DUPLICATE_CASEFINDING_ENTRY.value,
        409,
    )

    second_primary = assert_created(
        api.create_casefinding_entry(
            source["id"],
            _entry_payload(
                "MRN-0001",
                accession_date="2026-08-09",
                primary_site_code="C34.9",
                histology_code="8140/3",
            ),
            REGISTRY_MANAGER,
        )
    )
    assert second_primary["primary_site_code"] == "C34.9"

    reread = assert_ok(api.get_casefinding_source(source["id"], REGISTRY_MANAGER))
    assert reread["entries_this_month"] == 2


def test_the_survey_lead_window_accepts_the_sixtieth_day_and_not_the_fifty_ninth(api):
    """2026-09-29 is one day too soon; 2026-09-30 is exactly sixty days out.

    PRD 3.10: "Scheduling the survey is performed by an `AccreditationCoordinator`
    supplying a `survey_date`, and is accepted only from `ACCREDITED` or
    `PROBATION` (`ERR_PROGRAM_STATE_INVALID`); the date must be at least 60 days
    after the logical clock date, so a date exactly 60 days out is accepted and
    anything sooner is refused with `ERR_SURVEY_DATE_TOO_SOON`."

    Design: Corner/validations/survey_date_one_day_inside_lead_window_rejected_and_boundary_accepted
    """
    program = _program(api)

    validate_error(
        api.survey_schedule(
            program["id"], f.survey_schedule_payload(survey_date="2026-09-29"), COORDINATOR
        ),
        ApiErrorId.ERR_SURVEY_DATE_TOO_SOON.value,
        422,
    )
    refused = assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))
    assert refused["accreditation_state"] == "ACCREDITED"
    assert refused["survey_date"] is None

    scheduled = assert_ok(
        api.survey_schedule(
            program["id"], f.survey_schedule_payload(survey_date="2026-09-30"), COORDINATOR
        )
    )
    assert scheduled["accreditation_state"] == "SURVEY_SCHEDULED"
    assert scheduled["survey_date"] == "2026-09-30"
    assert scheduled["survey_year"] == 2026
    assert scheduled["registry_posture"] == "OPEN"


def test_resetting_the_clock_to_its_own_instant_is_an_error_and_not_a_no_op(api):
    """Time only moves forward, so equal and earlier instants both fail.

    PRD 2.2: "A `PlatformAdmin` moves the clock by supplying a `current_utc`
    instant, and time only moves forward: a requested instant that is not strictly
    later than the current logical instant is rejected with
    `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422)."

    Design: Corner/validations/clock_cannot_stand_still_or_move_backward
    """
    validate_error(
        api.set_clock(f.clock_payload("2026-08-01T00:00:00Z"), PLATFORM_ADMIN),
        ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value,
        422,
    )
    validate_error(
        api.set_clock(f.clock_payload("2026-07-31T23:59:59Z"), PLATFORM_ADMIN),
        ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value,
        422,
    )

    # PRD 2.2: a 2xx call carries the standard envelope; "For 2xx responses with
    # no data, it contains an empty object" -- so a successful forward move is a
    # 200 with a well-formed envelope, never a null body.
    validate_success(
        api.set_clock(f.clock_payload("2026-09-01T00:00:00Z"), PLATFORM_ADMIN), 200
    )

    validate_error(
        api.set_clock(f.clock_payload("2026-08-15T00:00:00Z"), PLATFORM_ADMIN),
        ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value,
        422,
    )
