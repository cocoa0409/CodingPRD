"""Reporting: roster disclosure, the stale gate, the programme freeze and the two report walls."""

from types import SimpleNamespace

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_report,
    assert_same_instant,
    build_patient,
    build_program_period,
    build_site,
    current_encounter_version,
    exam_encounter,
    get_success_data,
    list_encounter_procedures,
    make_guardian_headers,
    make_program_admin_headers,
    make_site_coordinator_headers,
    register_encounter,
    screen_encounter,
    set_clock,
    setup_program_site_and_staff,
    setup_screened_and_examined,
    setup_visit_in_progress,
    validate_error,
    validate_success,
)

ADMIN = make_program_admin_headers()


def test_summary_only_roster_lines_omit_the_clinical_keys_entirely(api):
    """PRD §3.8: "It carries the `site_id`, the site's `roster_disclosure_level`, a
    `patient_line_count`, a `lines` array, and the same `urgent_count`, `early_care_count` and
    `no_problem_count` computed over that site's in-period encounters."
    PRD §3.8: "When the level is `SUMMARY_ONLY`, each line carries only `patient_id`,
    `external_ref` and a `seen` flag set to true; the three clinical keys are **omitted from
    the object entirely rather than present with null values**, because a facility that is not
    entitled to clinical detail should not receive keys implying that detail exists."
    PRD §3.8: "Generating a report builds its `payload` and stamps `generated_at`."

    Design: Corner/endpoints/facility_roster_report_omits_clinical_fields_when_the_site_is_summary_only
    """
    stack = setup_screened_and_examined(clock="2026-05-11T09:00:00Z")
    report = validate_success(
        api.create_report(
            {
                "program_period_id": stack.pp_id,
                "report_type": "FACILITY_ROSTER",
                "site_id": stack.site_id,
            },
            stack.coord_headers,
        ),
        201,
    )
    generated = validate_success(api.generate_report(report["id"], stack.coord_headers))
    assert_report(generated)
    assert generated["status"] == "GENERATED"
    assert_same_instant(generated["generated_at"], "2026-05-11T09:00:00Z", "generated_at")

    payload = generated["payload"]
    assert payload["roster_disclosure_level"] == "SUMMARY_ONLY"
    assert payload["patient_line_count"] == 1
    assert payload["early_care_count"] == 1
    line = payload["lines"][0]
    assert set(line.keys()) == {"patient_id", "external_ref", "seen"}, (
        f"A SUMMARY_ONLY line carries exactly three keys, got {sorted(line.keys())}"
    )
    assert line["external_ref"] == "S-001"
    assert "triage_band" not in line


def test_submitting_a_stale_programme_report_is_refused(api):
    """PRD §2.11: "every report that is currently `GENERATED`, whose `report_type` is
    `PROGRAM_PERIOD`, and whose `program_period_id` is the period the written entity resolves
    to, moves to `STALE` with `stale_reason` set to `PERIOD_DATA_CHANGED` and its `version`
    incremented by 1."
    PRD §3.8: "It is legal only for a `PROGRAM_PERIOD` report that is currently `GENERATED` —
    a `STALE` report is refused with `ERR_REPORT_STALE` and must be regenerated first — and
    only while the covered period is in `REPORTING`."

    Design: Corner/validations/submitting_a_stale_program_report_returns_report_stale
    """
    stack = setup_screened_and_examined(clock="2026-05-11T09:00:00Z")
    validate_success(api.set_program_period_status(stack.pp_id, {"to_status": "REPORTING"}, ADMIN))
    report = validate_success(
        api.create_report({"program_period_id": stack.pp_id, "report_type": "PROGRAM_PERIOD"}, ADMIN),
        201,
    )
    validate_success(api.generate_report(report["id"], ADMIN))

    # A gated clinical write inside the period moves the generated report to STALE.
    validate_success(
        api.create_procedure(
            {
                "encounter_id": stack.enc_id,
                "procedure_code": "D1206",
                "expected_encounter_version": current_encounter_version(stack),
            },
            stack.hyg_headers,
        ),
        201,
    )

    resp = api.submit_report(report["id"], {"state_submission_ref": "CA-DHCS-2026-0001"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_REPORT_STALE.value, 409)

    after = validate_success(api.get_report(report["id"], ADMIN))
    assert after["status"] == "STALE"
    assert after["stale_reason"] == "PERIOD_DATA_CHANGED"
    assert after["submitted_at"] is None
    period = validate_success(api.get_program_period(stack.pp_id, ADMIN))
    assert period["status"] == "REPORTING"
    assert period["frozen_at"] is None


def _frozen_period_fixture():
    """A SUBMITTED period whose IN_PROGRESS visit has only 8 free chair minutes left."""
    stack = setup_program_site_and_staff(clock="2026-05-11T09:00:00Z")
    setup_visit_in_progress(
        stack, scope_tier="SCREENING_FLUORIDE_SEALANT", chair_count=1,
        scheduled_start_at="2026-05-11T09:00:00Z", scheduled_end_at="2026-05-11T09:39:00Z",
    )
    register_encounter(stack)
    screen_encounter(stack)
    exam_encounter(stack)
    stack.enc_v1 = current_encounter_version(stack)

    get_success_data(
        api_client.set_program_period_status(stack.pp_id, {"to_status": "REPORTING"}, ADMIN)
    )
    report = get_success_data(
        api_client.create_report(
            {"program_period_id": stack.pp_id, "report_type": "PROGRAM_PERIOD"}, ADMIN
        )
    )
    get_success_data(api_client.generate_report(report["id"], ADMIN))
    stack.report = get_success_data(
        api_client.submit_report(report["id"], {"state_submission_ref": "CA-DHCS-2026-0001"}, ADMIN)
    )
    stack.report_id = report["id"]
    return stack


def test_the_freeze_gate_pre_empts_the_chair_capacity_rung(api):
    """PRD §2.6: "rungs are evaluated from 1 upward, the first rung whose check fails decides
    the response, and no later rung runs."
    PRD §2.6: "A gated write is refused whenever the entity it targets resolves to a
    `ProgramPeriod` whose `status` is `SUBMITTED` or `CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/period_freeze_gate_beats_chair_capacity_on_a_gated_procedure_create
    """
    stack = _frozen_period_fixture()
    visit = validate_success(api.get_site_visit(stack.visit_id, ADMIN))
    assert visit["capacity_chair_minutes"] == 33
    assert visit["booked_chair_minutes"] == 25, "Only 8 chair minutes remain, but the gate fires first"

    resp = api.create_procedure(
        {
            "encounter_id": stack.enc_id,
            "procedure_code": "D1351",
            "tooth_number": 3,
            "surface": "O",
            "expected_encounter_version": stack.enc_v1,
        },
        stack.hyg_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_FROZEN.value, 409)

    rows = list_encounter_procedures(stack.enc_id)
    assert len(rows) == 2, f"Only the auto-created rows may exist, got {len(rows)}"
    after = validate_success(api.get_site_visit(stack.visit_id, ADMIN))
    assert after["booked_chair_minutes"] == 25


def test_report_submission_arms_the_freeze_and_stamps_the_period(api):
    """PRD §3.8: "It then runs two further links: the covered period moves `REPORTING →
    SUBMITTED` with `frozen_at` stamped at the logical clock instant, arming the global write
    gate over everything that resolves to that period"
    PRD §3.8: "Submission stamps the report's `submitted_at` and moves it to `SUBMITTED`,
    which is terminal."

    Design: Difficulty/priority_pair_validation_conflict/period_freeze_gate_beats_chair_capacity_on_a_gated_procedure_create
    """
    stack = _frozen_period_fixture()
    period = validate_success(api.get_program_period(stack.pp_id, ADMIN))
    assert period["status"] == "SUBMITTED"
    assert_same_instant(period["frozen_at"], "2026-05-11T09:00:00Z", "frozen_at")

    report = validate_success(api.get_report(stack.report_id, ADMIN))
    assert report["status"] == "SUBMITTED"
    assert_same_instant(report["submitted_at"], "2026-05-11T09:00:00Z", "submitted_at")

    # With the gate armed, the gated procedure create is refused.
    validate_error(
        api.create_procedure(
            {
                "encounter_id": stack.enc_id,
                "procedure_code": "D1351",
                "tooth_number": 3,
                "surface": "O",
                "expected_encounter_version": stack.enc_v1,
            },
            stack.hyg_headers,
        ),
        ApiErrorId.ERR_PERIOD_FROZEN.value, 409,
    )


def _two_parent_reports_fixture():
    set_clock("2026-05-11T09:00:00Z")
    period = build_program_period()
    site = build_site()
    coord = make_site_coordinator_headers(site["id"])
    patient1 = build_patient(site["id"], coord, external_ref="S-001")
    patient2 = build_patient(site["id"], coord, external_ref="S-002", first_name="Noah",
                             last_name="Park", date_of_birth="2015-11-20", household_size=3)
    report1 = get_success_data(
        api_client.create_report(
            {
                "program_period_id": period["id"],
                "report_type": "PARENT",
                "site_id": site["id"],
                "patient_id": patient1["id"],
                "recipient_user_id": "guardian-user-001",
            },
            coord,
        )
    )
    get_success_data(api_client.generate_report(report1["id"], coord))
    report2 = get_success_data(
        api_client.create_report(
            {
                "program_period_id": period["id"],
                "report_type": "PARENT",
                "site_id": site["id"],
                "patient_id": patient2["id"],
                "recipient_user_id": "guardian-user-002",
            },
            coord,
        )
    )
    get_success_data(api_client.generate_report(report2["id"], coord))
    return SimpleNamespace(report1_id=report1["id"], report2_id=report2["id"])


def test_the_guardian_wall_answers_not_found_for_another_familys_report(api):
    """PRD §2.6: "Any other report — a `FACILITY_ROSTER` report, a `PROGRAM_PERIOD` report, or
    another family's `PARENT` report — is answered with `ERR_NOT_FOUND` and **not** with
    `ERR_UNAUTHORIZED`, so that the very existence of other families' reports is never
    revealed to a guardian."
    PRD §2.6: "When the acting role is `Guardian` on the single-report read (`GET
    /mobile-dentistry/reports/{id}`), the report must satisfy both conditions: its
    `report_type` is `PARENT`, **and** its `recipient_user_id` equals the caller's
    `X-User-ID`."

    Design: Corner/rbac/guardian_reading_another_familys_parent_report_returns_not_found_not_forbidden
    """
    fx = _two_parent_reports_fixture()
    guardian_one = make_guardian_headers("guardian-user-001")

    refused = api.get_report(fx.report2_id, guardian_one)
    validate_error(refused, ApiErrorId.ERR_NOT_FOUND.value, 404)
    assert refused.status_code != 403, "The wall must not leak a 403"

    own = validate_success(api.get_report(fx.report1_id, guardian_one))
    assert own["id"] == fx.report1_id
    assert own["recipient_user_id"] == "guardian-user-001"
    assert validate_success(api.get_report(fx.report2_id, ADMIN))["status"] == "GENERATED"


def test_a_coordinator_reading_a_programme_report_is_refused_with_unauthorized(api):
    """PRD §2.6: "On the single-report read, the report's `site_id` must equal the
    coordinator's `X-User-ID`; a report for another site, and a `PROGRAM_PERIOD` report whose
    `site_id` is null, are both refused with `ERR_UNAUTHORIZED`."
    PRD §2.6: "This is a deliberately different outcome from the guardian wall one rung above:
    a coordinator learns that the report exists and is not theirs, while a guardian learns
    nothing."

    Design: Corner/rbac/site_coordinator_cannot_read_a_program_period_report
    """
    set_clock("2026-05-11T09:00:00Z")
    period = build_program_period()
    site = build_site()
    coord = make_site_coordinator_headers(site["id"])
    report = validate_success(
        api.create_report({"program_period_id": period["id"], "report_type": "PROGRAM_PERIOD"}, ADMIN),
        201,
    )
    validate_success(api.generate_report(report["id"], ADMIN))

    resp = api.get_report(report["id"], coord)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    as_admin = validate_success(api.get_report(report["id"], ADMIN))
    assert as_admin["site_id"] is None
    assert as_admin["status"] == "GENERATED"
