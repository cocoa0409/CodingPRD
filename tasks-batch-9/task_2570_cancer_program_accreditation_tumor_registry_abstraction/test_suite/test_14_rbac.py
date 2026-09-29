"""Who may call what: authentication, the per-endpoint matrix, and ownership."""

from test_helpers import (
    ApiErrorId,
    PLATFORM_ADMIN,
    REGISTRY_MANAGER,
    STATE_REGISTRY_LIAISON,
    assert_created,
    assert_ok,
    assert_program,
    factories as f,
    get_success_data,
    make_accreditation_coordinator_headers,
    make_coc_surveyor_headers,
    make_headers,
    make_qa_reviewer_headers,
    make_registry_abstractor_headers,
    validate_error,
    validate_paginated,
)

COORDINATOR = make_accreditation_coordinator_headers("user-coord-1")
SURVEYOR = make_coc_surveyor_headers("user-surveyor-1")
SURVEYOR_2 = make_coc_surveyor_headers("user-surveyor-2")
NO_HEADERS = {"Content-Type": "application/json"}
NO_USER_ID = {"X-User-Role": "RegistryManager", "Content-Type": "application/json"}
UNKNOWN_ROLE = make_headers("user-unknown-1", "RegistryDirector")
UNKNOWN_PROGRAM_ID = "00000000-0000-0000-0000-0000000000ff"
UNKNOWN_CASE_ID = "00000000-0000-0000-0000-0000000000c1"


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


def test_unauthenticated_requests_answer_before_the_body_or_the_path_is_read(api):
    """No headers, an unrecognised role, and a missing user id all stop at 401.

    PRD 2.1: "If either header is absent, or if `X-User-Role` is not one of the
    seven roles recognised by this system, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 401)."

    PRD 2.1: "Authentication is always evaluated before authorization, and both are
    evaluated before anything else in the request is inspected."

    Design: Corner/rbac/missing_and_unknown_role_headers_are_unauthenticated_before_any_other_check
    """
    program = _program(api)

    validate_error(
        api.create_abstractor(
            f.abstractor_payload(
                program["id"],
                name="No Headers",
                credential="CTR",
                productivity_target_cases_per_day=2,
                certification_expires_on="2027-12-31",
            ),
            NO_HEADERS,
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        401,
    )

    error = validate_error(
        api.create_abstractor({"name": "Bad Role And No Program"}, UNKNOWN_ROLE),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        401,
    )
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value

    error = validate_error(
        api.get_program(UNKNOWN_PROGRAM_ID, NO_USER_ID),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        401,
    )
    assert error["error_id"] != ApiErrorId.ERR_PROGRAM_NOT_FOUND.value

    _rows, meta = validate_paginated(
        api.list_abstractors(REGISTRY_MANAGER, {"program_id": program["id"]})
    )
    assert meta["total_count"] == 0


def test_holding_a_role_grants_nothing_on_another_roles_operation(api):
    """Seven authenticated callers, seven operations that belong to someone else.

    PRD 2.1: "A syntactically valid caller whose role is not listed for the endpoint
    being called is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    PRD 2.1: "A `PlatformAdmin` operates the registry platform itself: it onboards
    cancer programs, moves the logical clock, and records assessment payments."

    PRD 2.1: "It holds no clinical or accreditation authority."

    PRD 2.1: "An `AccreditationCoordinator` runs the multidisciplinary conference
    calendar, files deficiency responses, and drives quality-measure improvement
    projects."

    PRD 2.1: "A `StateRegistryLiaison` is the state central registry counterpart who
    returns edit results for a transmitted batch, and holds no authority over cases,
    abstractions, or accreditation."

    PRD 2.1: "A `CoCSurveyor` completes the survey, cites deficiencies, reviews
    responses, and renders the accreditation decision."

    Design: Corner/rbac/every_role_is_forbidden_from_another_roles_exclusive_operation
    """
    program = _program(api)
    registrar = _registrar(api, program["id"], "Dana Reyes")
    batch = get_success_data(
        api.create_submission(
            f.submission_payload(
                program["id"],
                period_start="2026-07-01",
                period_end="2026-07-31",
                deadline_date="2026-12-31",
            ),
            REGISTRY_MANAGER,
        )
    )
    measure = get_success_data(
        api.create_quality_measure(
            f.quality_measure_payload(
                program["id"], measure_code="CSTC", measurement_year=2026, threshold_pct=80.0
            ),
            REGISTRY_MANAGER,
        )
    )

    validate_error(
        api.create_deficiency(
            f.deficiency_payload(
                program["id"], severity="MAJOR", standard_code="STD-4.5", cited_on="2026-08-01"
            ),
            PLATFORM_ADMIN,
        ),
        ApiErrorId.ERR_FORBIDDEN.value,
        403,
    )
    validate_error(
        api.improvement_project(
            measure["id"],
            f.improvement_project_payload("OPEN", project_title="Manager-driven project"),
            REGISTRY_MANAGER,
        ),
        ApiErrorId.ERR_FORBIDDEN.value,
        403,
    )
    validate_error(
        api.create_program(
            f.program_payload(
                name="Rogue Program",
                coc_program_id="COC-9999R",
                annual_analytic_caseload=100,
                reference_year=2020,
                timeliness_standard_days=180,
            ),
            make_registry_abstractor_headers(registrar["id"]),
        ),
        ApiErrorId.ERR_FORBIDDEN.value,
        403,
    )
    validate_error(
        api.survey_complete(
            program["id"],
            f.survey_complete_payload(
                completed_on="2026-08-01", surveyor_note="Reviewer overreach"
            ),
            make_qa_reviewer_headers(registrar["id"]),
        ),
        ApiErrorId.ERR_FORBIDDEN.value,
        403,
    )
    validate_error(
        api.post_edit_results(batch["id"], f.edit_results_payload([]), SURVEYOR),
        ApiErrorId.ERR_FORBIDDEN.value,
        403,
    )
    error = validate_error(
        api.assign_case(
            UNKNOWN_CASE_ID, f.assign_payload(registrar["id"]), STATE_REGISTRY_LIAISON
        ),
        ApiErrorId.ERR_FORBIDDEN.value,
        403,
    )
    assert error["error_id"] != ApiErrorId.ERR_CASE_NOT_FOUND.value
    validate_error(
        api.set_clock(f.clock_payload("2026-08-02T00:00:00Z"), COORDINATOR),
        ApiErrorId.ERR_FORBIDDEN.value,
        403,
    )

    _defs, def_meta = validate_paginated(
        api.list_deficiencies(REGISTRY_MANAGER, {"program_id": program["id"]})
    )
    assert def_meta["total_count"] == 0

    reread_measure = assert_ok(api.get_quality_measure(measure["id"], REGISTRY_MANAGER))
    assert reread_measure["measure_state"] == "DRAFT"
    assert reread_measure["project_title"] is None

    _programs, program_meta = validate_paginated(api.list_programs(REGISTRY_MANAGER))
    assert program_meta["total_count"] == 1

    reread_program = assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))
    assert reread_program["accreditation_state"] == "ACCREDITED"
    assert reread_program["survey_year"] is None

    # NOTE: 2.6 measures "timeliness, follow-up ageing, response windows, and
    # audit windows" against the logical clock, and 2.4 says only that created_at
    # is "an ISO 8601 UTC instant with exactly three fractional digits" -- the PRD
    # never names the logical clock as the source of the created_at audit stamp,
    # so the refused set_clock is verified by its 403 above rather than by
    # inspecting a later resource's created_at.


def test_the_two_measure_owning_roles_share_the_operations_they_share(api):
    """Either role registers and evaluates; only the coordinator opens the project.

    PRD 2.1: "A `RegistryManager` runs the registry office — staffing registrars,
    owning casefinding sources, assigning and releasing cases, opening and transmitting
    state submissions, and voiding audits."

    PRD 2.1: "An `AccreditationCoordinator` runs the multidisciplinary conference
    calendar, files deficiency responses, and drives quality-measure improvement
    projects."

    PRD 3.8: "The verdict has three bands, tested against `threshold_pct` with
    inclusive comparisons: a basis rate at or above `threshold_pct` plus 10.0 is
    `EXCEEDS`, a basis rate at or above `threshold_pct` is `MEETS`, and anything below
    is `UNDER_THRESHOLD`."

    PRD 3.8: "`OPEN` records a `project_title` and a `target_rate_pct` and moves the
    measure `PROJECT_REQUIRED → PROJECT_ACTIVE`; a measure not in `PROJECT_REQUIRED` is
    refused with `ERR_PROJECT_NOT_REQUIRED`, and a `target_rate_pct` that is not
    strictly greater than the measure's current `performance_rate_pct` is
    `ERR_INVALID_REQUEST`, because a project must actually aim higher than where the
    program already is."

    Design: Corner/rbac/shared_quality_measure_operations_work_for_both_owning_roles
    """
    program = _program(api)
    measure_mgr = get_success_data(
        api.create_quality_measure(
            f.quality_measure_payload(
                program["id"], measure_code="CSTC", measurement_year=2026, threshold_pct=80.0
            ),
            REGISTRY_MANAGER,
        )
    )
    measure_coord = assert_created(
        api.create_quality_measure(
            f.quality_measure_payload(
                program["id"], measure_code="BCSRT", measurement_year=2026, threshold_pct=90.0
            ),
            COORDINATOR,
        )
    )

    by_coordinator = assert_ok(
        api.evaluate_quality_measure(
            measure_mgr["id"],
            f.evaluate_measure_payload([f.stratum("STAGE_I", 10, 7)]),
            COORDINATOR,
        )
    )
    assert by_coordinator["performance_rate_pct"] == 70.0
    assert by_coordinator["performance_state"] == "UNDER_THRESHOLD"
    assert by_coordinator["measure_state"] == "PROJECT_REQUIRED"

    by_manager = assert_ok(
        api.evaluate_quality_measure(
            measure_coord["id"],
            f.evaluate_measure_payload([f.stratum("STAGE_II", 10, 10)]),
            REGISTRY_MANAGER,
        )
    )
    assert by_manager["performance_rate_pct"] == 100.0
    assert by_manager["performance_state"] == "EXCEEDS"
    assert by_manager["measure_state"] == "MEASURED"

    opened = assert_ok(
        api.improvement_project(
            measure_mgr["id"],
            f.improvement_project_payload(
                "OPEN", project_title="Chemo start timeliness", target_rate_pct=85.0
            ),
            COORDINATOR,
        )
    )
    assert opened["measure_state"] == "PROJECT_ACTIVE"
    assert opened["target_rate_pct"] == 85.0
    assert opened["project_title"] == "Chemo start timeliness"

    _rows, meta = validate_paginated(
        api.list_quality_measures(REGISTRY_MANAGER, {"program_id": program["id"]})
    )
    assert meta["total_count"] == 2


def test_all_seven_roles_read_the_same_program_record(api):
    """The liaison and the surveyor see exactly what the platform admin sees.

    PRD 2.9: "| GET | `/cancer-registry/programs/{programId}` | Read one program
    including every derived compliance aggregate | Any authenticated role |"

    PRD 2.1: "A syntactically valid caller whose role is not listed for the endpoint
    being called is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/every_role_can_read_every_get_endpoint
    """
    program = _program(api)
    registrar = _registrar(api, program["id"], "Dana Reyes")
    readers = [
        PLATFORM_ADMIN,
        REGISTRY_MANAGER,
        make_registry_abstractor_headers(registrar["id"]),
        make_qa_reviewer_headers(registrar["id"]),
        COORDINATOR,
        STATE_REGISTRY_LIAISON,
        SURVEYOR,
    ]

    bodies = [assert_program(assert_ok(api.get_program(program["id"], h))) for h in readers]

    baseline = bodies[0]
    assert baseline["id"] == program["id"]
    assert baseline["coc_program_id"] == "COC-1456N"
    assert baseline["accreditation_state"] == "ACCREDITED"
    assert baseline["registry_posture"] == "OPEN"
    for body in bodies[1:]:
        assert body == baseline
        assert set(body.keys()) == set(baseline.keys())


def test_a_peer_registrar_cannot_abstract_a_case_assigned_to_someone_else(api):
    """The role is right, the body is right, the version is right, the user is not.

    PRD 3.3: "The acting `X-User-ID` must equal the case's `assigned_abstractor_id`,
    and the `abstractor_id` in the payload must equal it too; anyone else is refused
    with `ERR_NOT_ASSIGNED_ABSTRACTOR` (HTTP 403)."

    PRD 3.3: "A successful create places the abstraction in `DRAFT`, sets its
    `abstractor_id` from the acting user, advances the case `ASSIGNED →
    IN_ABSTRACTION`, and increments the case's `version` by one — which is exactly why
    a client that wants to write twice against the same case must re-read the case in
    between."

    Design: Corner/rbac/a_peer_registrar_cannot_abstract_or_submit_another_registrars_case
    """
    program = _program(api)
    registrar_a = _registrar(api, program["id"], "Dana Reyes")
    registrar_b = _registrar(api, program["id"], "Bea Nakamura")
    source = get_success_data(
        api.create_casefinding_source(
            f.casefinding_source_payload(
                program["id"], source_type="PATHOLOGY", expected_monthly_volume=40
            ),
            REGISTRY_MANAGER,
        )
    )
    entry = get_success_data(
        api.create_casefinding_entry(
            source["id"],
            f.casefinding_entry_payload(
                patient_mrn="MRN-0001",
                accession_date="2026-08-03",
                primary_site_code="C50.9",
                histology_code="8500/3",
                behavior_code="MALIGNANT_3",
                diagnosis_date="2026-07-01",
                first_contact_date="2026-07-05",
                diagnosed_at_facility=True,
                first_treatment_at_facility=True,
            ),
            REGISTRY_MANAGER,
        )
    )
    case_id = get_success_data(
        api.reportability_decision(
            entry["id"], f.reportability_decision_payload("REPORTABLE"), REGISTRY_MANAGER
        )
    )["created_case_id"]
    assigned = get_success_data(
        api.assign_case(case_id, f.assign_payload(registrar_a["id"]), REGISTRY_MANAGER)
    )

    def _payload(abstractor_id):
        return f.abstraction_payload(
            case_id,
            abstractor_id,
            assigned["version"],
            first_treatment_date="2026-07-10",
            diagnostic_confirmation_code="POSITIVE_HISTOLOGY",
            last_contact_date="2026-07-20",
        )

    validate_error(
        api.create_abstraction(
            _payload(registrar_b["id"]), make_registry_abstractor_headers(registrar_b["id"])
        ),
        ApiErrorId.ERR_NOT_ASSIGNED_ABSTRACTOR.value,
        403,
    )
    _rows, meta = validate_paginated(api.list_abstractions(REGISTRY_MANAGER, {"case_id": case_id}))
    assert meta["total_count"] == 0
    waiting = assert_ok(api.get_case(case_id, REGISTRY_MANAGER))
    assert waiting["case_state"] == "ASSIGNED"
    assert waiting["version"] == assigned["version"]

    abstraction = assert_created(
        api.create_abstraction(
            _payload(registrar_a["id"]), make_registry_abstractor_headers(registrar_a["id"])
        )
    )
    assert abstraction["abstraction_state"] == "DRAFT"
    assert abstraction["abstractor_id"] == registrar_a["id"]
    assert assert_ok(api.get_case(case_id, REGISTRY_MANAGER))["case_state"] == "IN_ABSTRACTION"

    assert assert_ok(api.get_abstractor(registrar_b["id"], REGISTRY_MANAGER))[
        "assigned_open_case_count"
    ] == 0
    assert assert_ok(api.get_abstractor(registrar_a["id"], REGISTRY_MANAGER))[
        "assigned_open_case_count"
    ] == 1


def test_the_responder_cannot_review_their_own_deficiency_response(api):
    """Swapping the role but keeping the user id does not clear the segregation check.

    PRD 2.1: "When `X-User-Role` is `PlatformAdmin`, `RegistryManager`,
    `AccreditationCoordinator`, `StateRegistryLiaison`, or `CoCSurveyor`, `X-User-ID`
    is an opaque operator identifier that is not tied to any persisted entity; the
    server may record it — for example as `decided_by_user_id` on a casefinding entry,
    or as the surveyor of record on a survey completion — but never compares it to any
    entity's `id`."

    PRD 3.9: "A `CoCSurveyor` records an `outcome` of `ACCEPTED` or `REJECTED`,
    optionally with `reviewer_notes`, against a deficiency that must be in
    `RESPONSE_SUBMITTED` (`ERR_DEFICIENCY_NOT_UNDER_REVIEW`), and the reviewing user
    must not be the user recorded on the response
    (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`)."

    PRD 3.9: "A second response overwrites `response_narrative` and
    `evidence_reference` rather than appending, and the acting `X-User-ID` is retained
    on the deficiency so that the segregation-of-duties check on review has something
    to compare against."

    Design: Corner/rbac/deficiency_review_must_come_from_a_different_user_than_the_response
    """
    program = _program(api)
    deficiency = get_success_data(
        api.create_deficiency(
            f.deficiency_payload(
                program["id"], severity="MAJOR", standard_code="STD-4.5", cited_on="2026-08-01"
            ),
            SURVEYOR,
        )
    )
    get_success_data(
        api.respond_to_deficiency(
            deficiency["id"],
            f.deficiency_response_payload(
                response_narrative="Corrective action plan filed", evidence_reference="CAP-1"
            ),
            COORDINATOR,
        )
    )

    validate_error(
        api.review_deficiency_response(
            deficiency["id"],
            f.deficiency_review_payload("ACCEPTED", reviewer_notes="Self-review attempt"),
            make_coc_surveyor_headers("user-coord-1"),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value,
        409,
    )
    pending = assert_ok(api.get_deficiency(deficiency["id"], SURVEYOR))
    assert pending["deficiency_state"] == "RESPONSE_SUBMITTED"
    assert pending["reviewer_notes"] is None

    resolved = assert_ok(
        api.review_deficiency_response(
            deficiency["id"],
            f.deficiency_review_payload("ACCEPTED", reviewer_notes="Independent review"),
            SURVEYOR,
        )
    )
    assert resolved["deficiency_state"] == "RESOLVED"
    assert resolved["reviewer_notes"] == "Independent review"
    assert resolved["escalation_count"] == 0
    assert resolved["response_due_date"] == "2026-09-15"


def test_the_surveyor_of_record_cannot_render_the_accreditation_decision(api):
    """Survey completion stamps the surveyor, and the decision must come from another.

    PRD 3.10: "Both branches set `survey_year` to the logical clock year and
    `next_survey_due_year` to that year plus three."

    PRD 3.10: "Either way the acting `X-User-ID` is recorded as the surveyor of record
    for the segregation check on the decision."

    PRD 3.10: "The accreditation decision is rendered by a `CoCSurveyor` as a
    `decision` of `ACCREDIT`, `PROBATION`, or `WITHDRAW`, optionally with a
    `decision_note`, and may not be rendered by the same user who completed the survey
    (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`)."

    Design: Corner/rbac/accreditation_decision_must_come_from_a_different_surveyor_than_the_survey
    """
    program = _program(api)
    get_success_data(api.set_clock(f.clock_payload("2026-10-01T00:00:00Z"), PLATFORM_ADMIN))
    deficiency = get_success_data(
        api.create_deficiency(
            f.deficiency_payload(
                program["id"], severity="MAJOR", standard_code="STD-4.5", cited_on="2026-10-01"
            ),
            SURVEYOR,
        )
    )
    get_success_data(
        api.survey_schedule(
            program["id"], f.survey_schedule_payload(survey_date="2027-01-15"), COORDINATOR
        )
    )

    completed = assert_ok(
        api.survey_complete(
            program["id"],
            f.survey_complete_payload(
                completed_on="2026-10-01", surveyor_note="One major standard unmet"
            ),
            SURVEYOR,
        )
    )
    assert completed["accreditation_state"] == "DEFICIENCY_RESPONSE"
    assert completed["survey_year"] == 2026
    assert completed["next_survey_due_year"] == 2029

    validate_error(
        api.accreditation_decision(
            program["id"],
            f.accreditation_decision_payload(
                decision="PROBATION", decision_note="Same surveyor deciding"
            ),
            SURVEYOR,
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value,
        409,
    )
    unchanged = assert_ok(api.get_program(program["id"], REGISTRY_MANAGER))
    assert unchanged["accreditation_state"] == "DEFICIENCY_RESPONSE"
    assert unchanged["registry_posture"] == "OPEN"

    decided = assert_ok(
        api.accreditation_decision(
            program["id"],
            f.accreditation_decision_payload(
                decision="PROBATION", decision_note="Independent decision"
            ),
            SURVEYOR_2,
        )
    )
    assert decided["accreditation_state"] == "PROBATION"
    assert decided["registry_posture"] == "FROZEN"

    reread_deficiency = assert_ok(api.get_deficiency(deficiency["id"], SURVEYOR))
    assert reread_deficiency["deficiency_state"] == "CITED"
    assert reread_deficiency["response_due_date"] == "2026-11-15"
