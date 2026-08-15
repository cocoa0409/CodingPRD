"""Physician interpretation: report lifecycle (draft, sign, finalize,
addendum), severity bands, turnaround accounting, SLA verdicts, and the
creation guards (OCC, supersession, segregation of duties)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_interpretation_report,
    assign_task,
    complete_acquisition_ws,
    create_physician,
    create_report,
    create_scorer,
    create_technologist,
    get_study,
    get_success_data,
    make_physician_headers,
    score_primary,
    score_rescore,
    set_clock,
    setup_finalized_report,
    setup_scored_study,
    setup_scoring_queued,
    setup_signed_report,
    setup_study_in_progress,
    sign_report,
    start_task,
    validate_error,
    validate_paginated,
)

SCHED = TEST_USERS["scheduler_headers"]
DIRECTOR = TEST_USERS["lab_director_headers"]


class TestSeverityBoundaries:
    def test_severity_moderate_at_exactly_15(self, api):
        """PRD: "The `severity` bands against that index are: `NORMAL` below
        5.0, `MILD` at least 5.0 but below 15.0, `MODERATE` at least 15.0 but
        below 30.0, and `SEVERE` at least 30.0 — each boundary is inclusive on
        the higher band, so exactly 15.0 is `MODERATE`."

        Design: Difficulty/boundary_precision_check/severity_moderate_at_exactly_15_0
        """
        ws = setup_scored_study(
            study_type="PSG_DIAGNOSTIC",
            submit_overrides={
                "obstructive_apneas": 30, "central_apneas": 0,
                "mixed_apneas": 0, "hypopneas": 60, "reras": 0,
                "epochs_total": 720, "total_sleep_time_minutes": 360,
                "total_recording_time_minutes": 420,
            })
        # 90 events * 60 / 360 = exactly 15.0.
        assert ws["study"]["accepted_ahi"] == pytest.approx(15.0)

        create_report(ws)
        report = sign_report(ws)
        assert_interpretation_report(report)
        assert report["index_at_interpretation"] == pytest.approx(15.0)
        assert report["severity"] == "MODERATE", (
            "15.0 is the inclusive lower bound of MODERATE, not MILD")

    def test_severity_mild_just_below_15(self, api):
        """PRD: "The `severity` bands against that index are: `NORMAL` below
        5.0, `MILD` at least 5.0 but below 15.0, `MODERATE` at least 15.0 but
        below 30.0, and `SEVERE` at least 30.0 — each boundary is inclusive on
        the higher band, so exactly 15.0 is `MODERATE`."

        Design: Difficulty/boundary_precision_check/severity_moderate_at_exactly_15_0
        """
        ws = setup_scored_study(
            study_type="PSG_DIAGNOSTIC",
            submit_overrides={
                "obstructive_apneas": 29, "central_apneas": 0,
                "mixed_apneas": 0, "hypopneas": 60, "reras": 0,
                "epochs_total": 720, "total_sleep_time_minutes": 360,
                "total_recording_time_minutes": 420,
            })
        # 89 events * 60 / 360 = 14.833 -> 14.8, strictly below the band edge.
        assert ws["study"]["accepted_ahi"] == pytest.approx(14.8)

        create_report(ws)
        report = sign_report(ws)
        assert report["index_at_interpretation"] == pytest.approx(14.8)
        assert report["severity"] == "MILD"


class TestAddendumCycle:
    def test_open_addendum(self, api):
        """PRD: "Finalized reports support an addendum cycle: opening an
        addendum requires the author and a `FINALIZED` report, moves it to
        `ADDENDUM_OPEN`, and increments `addendum_count` — which begins at zero
        — by one; closing the addendum requires the author and an
        `ADDENDUM_OPEN` report and returns it to `FINALIZED`."

        Design: Difficulty/non_linear_state_machine/report_addendum_cycle
        """
        ws = setup_finalized_report(study_type="HST")
        report = ws["report"]
        assert report["status"] == "FINALIZED"
        assert report["addendum_count"] == 0

        opened = get_success_data(api.open_addendum(
            report["id"], make_physician_headers(report["physician_id"])))
        assert opened["status"] == "ADDENDUM_OPEN"
        assert opened["addendum_count"] == 1

    def test_close_addendum_returns_to_finalized(self, api):
        """PRD: "Finalized reports support an addendum cycle: opening an
        addendum requires the author and a `FINALIZED` report, moves it to
        `ADDENDUM_OPEN`, and increments `addendum_count` — which begins at zero
        — by one; closing the addendum requires the author and an
        `ADDENDUM_OPEN` report and returns it to `FINALIZED`."

        Design: Difficulty/non_linear_state_machine/report_addendum_cycle
        """
        ws = setup_finalized_report(study_type="HST")
        report = ws["report"]
        get_success_data(api.open_addendum(
            report["id"], make_physician_headers(report["physician_id"])))

        closed = get_success_data(api.close_addendum(
            report["id"], make_physician_headers(report["physician_id"])))
        assert closed["status"] == "FINALIZED", "The addendum cycle closes"
        assert closed["addendum_count"] == 1, (
            "Closing does not erase the recorded cycle")
        assert get_study(ws["study"]["id"])["status"] == "REPORT_FINALIZED", (
            "The study stays REPORT_FINALIZED throughout the addendum cycle")


class TestTurnaroundVariants:
    def _weekend_span_report(self, api):
        """HST study: acquisition Friday 2026-08-07 22:00Z, report signed
        Monday 2026-08-10 10:00Z (ROUTINE order)."""
        ws = setup_study_in_progress(study_type="HST",
                                     scheduled_date="2026-08-07")
        set_clock("2026-08-07T22:00:00Z")
        complete_acquisition_ws(ws, total_recording_time_minutes=480)
        score_primary(ws, obstructive_apneas=20, hypopneas=28,
                      epochs_total=960, total_recording_time_minutes=480)
        create_report(ws)
        set_clock("2026-08-10T10:00:00Z")
        return sign_report(ws)

    def test_turnaround_business_hours_weekend_span(self, api):
        """PRD: "The `turnaround_business_hours` accumulate only the
        intersection of that same interval with the laboratory's business
        window — Monday through Friday, 08:00:00Z to 17:00:00Z UTC, with
        Saturdays and Sundays contributing zero — again in whole minutes
        divided by 60 and rounded half-up to one decimal, so an interval
        spanning a weekend yields a far smaller business value than its
        calendar twin."
        PRD: "For a `ROUTINE` order the business-hours variant governs: a
        turnaround strictly greater than 48.0 business hours is a breach, and
        exactly 48.0 is not."

        Design: Difficulty/dual_variant_calc/turnaround_business_vs_calendar_weekend_span
        """
        report = self._weekend_span_report(api)
        # Fri 22:00 -> Mon 10:00: only Mon 08:00-10:00 falls in the window.
        assert report["turnaround_business_hours"] == pytest.approx(2.0)
        assert report["sla_breached"] is False

    def test_turnaround_calendar_hours_weekend_span(self, api):
        """PRD: "The `turnaround_calendar_hours` measure the whole minutes from
        `acquisition_completed_at` to `signed_at`, divided by 60 and rounded
        half-up to one decimal, counting every wall-clock hour including
        nights and weekends."

        Design: Difficulty/dual_variant_calc/turnaround_business_vs_calendar_weekend_span
        """
        report = self._weekend_span_report(api)
        # Fri 22:00 -> Mon 10:00 wall clock is exactly 60 hours.
        assert report["turnaround_calendar_hours"] == pytest.approx(60.0)

    def test_turnaround_exactly_48_business_hours_not_breach(self, api):
        """PRD: "For a `ROUTINE` order the business-hours variant governs: a
        turnaround strictly greater than 48.0 business hours is a breach, and
        exactly 48.0 is not."

        Design: Corner/calculations/turnaround_exactly_48_business_hours_not_breach
        """
        ws = setup_study_in_progress(study_type="HST",
                                     scheduled_date="2026-08-03")
        set_clock("2026-08-03T09:00:00Z")
        complete_acquisition_ws(ws, total_recording_time_minutes=480)
        score_primary(ws, obstructive_apneas=20, hypopneas=20)
        create_report(ws)
        # Mon 09:00 -> next Mon 12:00 spans exactly 48 business hours
        # (8 + 9 + 9 + 9 + 9 + 4).
        set_clock("2026-08-10T12:00:00Z")
        report = sign_report(ws)

        assert report["turnaround_business_hours"] == pytest.approx(48.0)
        assert report["sla_breached"] is False, (
            "48.0 > 48.0 is false — the SLA comparison is strict")


class TestReportCreationGuards:
    def test_sign_by_non_author_forbidden(self, api):
        """PRD: "Signing is reserved to the report's author
        (`ERR_NOT_REPORT_AUTHOR`)"

        Design: Corner/state_machines/sign_by_non_author_forbidden
        """
        ws = setup_scored_study(study_type="HST")
        create_report(ws)
        other = create_physician()

        resp = api.sign_report(ws["report"]["id"],
                               make_physician_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_REPORT_AUTHOR, 403)

        reread = get_success_data(
            api.get_interpretation_report(ws["report"]["id"], DIRECTOR))
        assert reread["status"] == "DRAFT"
        assert reread["signed_at"] is None

    def test_sign_with_matching_scorer_npi_rejected(self, api):
        """PRD: "Segregation of duties applies at the pen: the signing
        physician's `npi` must differ from the `npi` of the scorer who staged
        the accepted primary task (`ERR_SOD_REPORT_SCORER`)."

        Design: Corner/errors/sign_with_matching_scorer_npi_rejected
        """
        staff = {
            "technologist": create_technologist(),
            "scorer": create_scorer(npi="NPI-SAME"),
            "physician": create_physician(npi="NPI-SAME"),
        }
        ws = setup_scored_study(study_type="HST", staff=staff)
        create_report(ws)

        resp = api.sign_report(
            ws["report"]["id"],
            make_physician_headers(ws["physician"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SOD_REPORT_SCORER, 422)

        reread = get_success_data(
            api.get_interpretation_report(ws["report"]["id"], DIRECTOR))
        assert reread["status"] == "DRAFT"

    def test_report_with_rescore_task_rejected(self, api):
        """PRD: "The named `primary_scoring_task_id` must be the study's
        accepted `PRIMARY` task (`ERR_INVALID_PRIMARY_TASK`)."

        Design: Corner/errors/report_with_rescore_task_rejected
        """
        ws = setup_scored_study(study_type="HST")
        rescorer = create_scorer(credential="RST", reliability_pool=True)
        score_rescore(ws, rescorer=rescorer)
        study = get_study(ws["study"]["id"])

        resp = api.create_interpretation_report(
            {"study_id": study["id"],
             "primary_scoring_task_id": ws["rescore_task"]["id"],
             "diagnosis_code": "G47.33",
             "expected_sleep_study_version": study["version"]},
            make_physician_headers(ws["physician"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PRIMARY_TASK, 422)

        _, meta = validate_paginated(api.list_interpretation_reports(
            DIRECTOR, {"study_id": study["id"]}))
        assert meta["total_count"] == 0

    def test_second_report_after_sign_rejected(self, api):
        """PRD: "Creation enforces, within the state-precondition group and in
        this relative order: first, a live report in `SIGNED`, `FINALIZED`, or
        `ADDENDUM_OPEN` already covering the study blocks creation with
        `ERR_FINAL_REPORT_EXISTS`; then the study must be `SCORED` or
        `INTERPRETATION_IN_PROGRESS` (`ERR_STUDY_NOT_SCORED`)."

        Design: Corner/errors/second_report_after_sign_rejected
        """
        ws = setup_signed_report(study_type="HST")
        study = get_study(ws["study"]["id"])  # INTERPRETED, fresh version

        resp = api.create_interpretation_report(
            {"study_id": study["id"],
             "primary_scoring_task_id": ws["task"]["id"],
             "diagnosis_code": "G47.33",
             "expected_sleep_study_version": study["version"]},
            make_physician_headers(ws["physician"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FINAL_REPORT_EXISTS, 409)

        _, meta = validate_paginated(api.list_interpretation_reports(
            DIRECTOR, {"study_id": study["id"]}))
        assert meta["total_count"] == 1

    def test_report_create_on_unscored_study_rejected(self, api):
        """PRD: "then the study must be `SCORED` or
        `INTERPRETATION_IN_PROGRESS` (`ERR_STUDY_NOT_SCORED`)."

        Design: Corner/validations/report_create_on_unscored_study_rejected
        """
        ws = setup_scoring_queued(study_type="HST")
        task = assign_task(ws["study"]["id"], ws["scorer"]["id"])
        start_task(task["id"], ws["scorer"]["id"])
        study = get_study(ws["study"]["id"])
        assert study["status"] == "SCORING_IN_PROGRESS"

        resp = api.create_interpretation_report(
            {"study_id": study["id"], "primary_scoring_task_id": task["id"],
             "diagnosis_code": "G47.33",
             "expected_sleep_study_version": study["version"]},
            make_physician_headers(ws["physician"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STUDY_NOT_SCORED, 409)

    def test_occ_report_create_stale_version_rejected(self, api):
        """PRD: "Creating an interpretation report requires
        `expected_sleep_study_version`, matching the study's current `version`.
        A report created since the client's last read legitimately supersedes
        a prior draft, so a stale `version` is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_report_create_stale_version_rejected
        """
        ws = setup_scored_study(study_type="HST")
        study = get_study(ws["study"]["id"])
        observed_version = study["version"]

        report = create_report(ws)
        assert report["status"] == "DRAFT"

        resp = api.create_interpretation_report(
            {"study_id": study["id"],
             "primary_scoring_task_id": ws["task"]["id"],
             "diagnosis_code": "G47.33",
             "expected_sleep_study_version": observed_version},
            make_physician_headers(ws["physician"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        _, meta = validate_paginated(api.list_interpretation_reports(
            DIRECTOR, {"study_id": study["id"]}))
        assert meta["total_count"] == 1

    def test_report_create_supersedes_draft(self, api):
        """PRD: "Creation captures the author from `X-User-ID` into
        `physician_id`, opens the report in `DRAFT`, moves the study from
        `SCORED` to `INTERPRETATION_IN_PROGRESS` — a superseding creation
        while a prior draft exists leaves the study in
        `INTERPRETATION_IN_PROGRESS` — increments the study's `version` by
        one, and transitions any existing `DRAFT` report for the study to
        `SUPERSEDED`."

        Design: Corner/complexity_layers/report_create_supersedes_draft
        """
        ws = setup_scored_study(study_type="HST")
        report1 = create_report(ws)
        version_after_first = ws["study"]["version"]

        report2 = create_report(ws)
        assert report2["status"] == "DRAFT"
        assert report2["id"] != report1["id"]

        prior = get_success_data(
            api.get_interpretation_report(report1["id"], DIRECTOR))
        assert prior["status"] == "SUPERSEDED"

        study = get_study(ws["study"]["id"])
        assert study["status"] == "INTERPRETATION_IN_PROGRESS", (
            "A superseding creation is a self-loop on the study")
        assert study["version"] == version_after_first + 1, (
            "Each report creation increments the study's version by one")
