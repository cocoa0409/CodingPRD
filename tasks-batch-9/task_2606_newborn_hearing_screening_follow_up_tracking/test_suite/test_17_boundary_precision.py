"""Two boundaries read exactly: the 90-day benchmark, and an empty denominator."""

import pytest

from test_helpers import assertions as check
from test_helpers import factories, fixtures
from test_helpers.test_users import (
    make_facility_admin_headers,
    make_facility_screener_headers,
    make_program_admin_headers,
    make_program_auditor_headers,
)

ADMIN = make_program_admin_headers()
AUDITOR = make_program_auditor_headers()

BIRTH = "2026-08-02T00:00:00Z"
DAY_90 = "2026-10-31T00:00:00Z"
DAY_91 = "2026-11-01T00:00:00Z"


def _two_term_babies_awaiting_finalization(client):
    """Two attested no-loss evaluations on infants born the same instant."""
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    registry = fixtures.Registry(
        birth_hospital=hospital,
        clinic=clinic,
        ei_program=None,
        screener=fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1"),
        audiologist=fixtures.create_provider(client, clinic["id"], "AUDIOLOGIST", "A1", "R1"),
        second_audiologist=fixtures.create_provider(
            client, clinic["id"], "AUDIOLOGIST", "A2", "R1"
        ),
        navigator=None,
        coordinator=None,
    )
    fixtures.set_clock(client, "2026-08-02T06:00:00Z")

    def _one(suffix):
        infant = fixtures.create_infant(
            client,
            hospital["id"],
            birth_datetime=BIRTH,
            birth_setting="INPATIENT",
            gestational_age_weeks=39,
            nicu_stay_days=0,
            guardian_name="G-B{0}".format(suffix),
            guardian_contact_phone="55509{0}".format(suffix),
        )
        fixtures.record_encounter(
            client,
            registry,
            infant["id"],
            "2026-08-02T05:00:00Z",
            encounter_type="BIRTH_ADMISSION",
            method="AABR",
            left_ear_result="REFER",
            right_ear_result="REFER",
        )
        rescreen = fixtures.episodes_of(client, infant["id"])[0]
        assert rescreen["episode_type"] == "RESCREEN"
        episode = fixtures.open_episode(
            client,
            infant["id"],
            "DIAGNOSTIC",
            expected_infant_version=fixtures.infant_version(client, infant["id"]),
            supersedes_episode_id=rescreen["id"],
        )
        evaluation = fixtures.draft_evaluation(
            client, registry, infant["id"], episode["id"], "2026-08-02T06:00:00Z"
        )
        fixtures.submit_evaluation(client, registry, evaluation["id"], 20, 20, "NO_LOSS")
        fixtures.attest_evaluation(client, registry, evaluation["id"])
        return {"infant": infant, "episode": episode, "evaluation": evaluation}

    return registry, _one("01"), _one("02")


def test_ninety_days_is_on_time_and_ninety_one_is_late(client):
    """One day of clock apart, and the inclusive comparison splits the two rows.

    PRD: "The benchmark boundary is inclusive: a diagnostic finalized at exactly 90
    days of applied age is `ON_TIME`, and one finalized at 91 days is `LATE`."

    Design: Difficulty/boundary_precision_check/diagnostic_benchmark_day_90_on_time_day_91_late
    """
    registry, on_the_line, over_the_line = _two_term_babies_awaiting_finalization(client)

    fixtures.set_clock(client, DAY_90)
    exactly_ninety = fixtures.finalize_evaluation(
        client, registry, on_the_line["evaluation"]["id"]
    )
    assert exactly_ninety["status"] == "FINALIZED_NO_LOSS"
    assert exactly_ninety["age_days_at_finalize"] == 90
    assert exactly_ninety["timeliness_status"] == "ON_TIME"
    assert exactly_ninety["timeliness_status_chronological_basis"] == "ON_TIME"
    check.assert_instant_equals(exactly_ninety["finalized_at"], DAY_90)

    fixtures.set_clock(client, DAY_91)
    one_day_over = fixtures.finalize_evaluation(
        client, registry, over_the_line["evaluation"]["id"]
    )
    assert one_day_over["status"] == "FINALIZED_NO_LOSS"
    assert one_day_over["age_days_at_finalize"] == 91
    assert one_day_over["timeliness_status"] == "LATE"
    assert one_day_over["timeliness_status_chronological_basis"] == "LATE"
    check.assert_instant_equals(one_day_over["finalized_at"], DAY_91)


def test_the_late_verdict_changes_the_paperwork_and_nothing_else(client):
    """Both babies settle no-loss, and the stored verdict outlives the clock.

    PRD: "The reference instant is the logical clock for a live read, and the
    milestone's own instant for a stored status — a screening encounter's
    `performed_at`, an evaluation's `finalized_at`, or a referral's `ifsp_date`, as
    applicable."

    Design: Difficulty/boundary_precision_check/diagnostic_benchmark_day_90_on_time_day_91_late
    """
    registry, on_the_line, over_the_line = _two_term_babies_awaiting_finalization(client)
    fixtures.set_clock(client, DAY_90)
    fixtures.finalize_evaluation(client, registry, on_the_line["evaluation"]["id"])
    fixtures.set_clock(client, DAY_91)
    fixtures.finalize_evaluation(client, registry, over_the_line["evaluation"]["id"])

    for case in (on_the_line, over_the_line):
        check.assert_episode_state(
            fixtures.read_episode(client, case["episode"]["id"]),
            "RESOLVED_NO_LOSS",
            closure_reason="DIAGNOSIS_NO_LOSS",
            benchmark_days=90,
        )
        check.assert_infant_dimensions(
            fixtures.read_infant(client, case["infant"]["id"]),
            "DIAGNOSED_NO_LOSS",
            "NOT_APPLICABLE",
        )

    # Both panels are read at the same logical clock, one day past the boundary, so
    # the live ages agree while the stored diagnostic verdicts still disagree.
    for case, verdict in ((on_the_line, "ON_TIME"), (over_the_line, "LATE")):
        panel = check.assert_ok(
            client.get_timeliness(case["infant"]["id"], headers=ADMIN)
        )
        check.assert_timeliness_panel(
            panel,
            infant_id=case["infant"]["id"],
            chronological_age_days=91,
            corrected_age_days=84,
            effective_age_days=91,
            prematurity_offset_days=7,
            benchmark_age_basis="CHRONOLOGICAL",
            diagnostic_timeliness_status=verdict,
            diagnostic_timeliness_status_chronological_basis=verdict,
        )


def _one_screened_baby_and_no_episodes(client):
    """A facility whose only infant passed at birth, so no episode ever opened."""
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    screener = fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")
    period = fixtures.open_period(
        client, "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z", "2026-09-05T00:00:00Z"
    )
    fixtures.set_clock(client, "2026-08-05T06:00:00Z")
    infant = fixtures.create_infant(
        client,
        hospital["id"],
        birth_datetime="2026-08-05T00:00:00Z",
        birth_setting="INPATIENT",
        gestational_age_weeks=39,
        guardian_name="G-N",
        guardian_contact_phone="5551001",
    )
    check.assert_created(
        client.create_encounter(
            factories.encounter_payload(
                infant_id=infant["id"],
                facility_id=hospital["id"],
                performed_by_provider_id=screener["id"],
                performed_at="2026-08-05T04:00:00Z",
                encounter_type="BIRTH_ADMISSION",
                method="OAE",
                left_ear_result="PASS",
                right_ear_result="PASS",
            ),
            headers=make_facility_screener_headers(screener["id"]),
        )
    )
    assert fixtures.episodes_of(client, infant["id"]) == []

    fixtures.set_clock(client, "2026-09-02T00:00:00Z")
    report = fixtures.file_report(
        client, hospital["id"], period["id"], attested_screened_count=1, attested_refer_count=0
    )
    reviewed = fixtures.review_report(client, report["id"], "ACCEPT", note="counts reconcile")
    assert reviewed["status"] == "ACCEPTED"
    return hospital, period, report, infant


def test_a_zero_episode_denominator_nulls_both_published_scores(client):
    """The empty rate is null, and it takes both weighted scores down with it.

    PRD: "If the follow-up episode denominator is 0, that rate is null and **both**
    scores are null. A null score never moves `reporting_compliance_status`; only the
    penalty balance does."

    Design: Difficulty/boundary_precision_check/empty_followup_denominator_publishes_null_scores_not_zero
    """
    hospital, period, _, _ = _one_screened_baby_and_no_episodes(client)
    fixtures.close_period(client, period["id"])

    dashboard = check.assert_ok(
        client.get_facility_performance(
            hospital["id"], headers=make_facility_admin_headers(hospital["id"])
        )
    )
    assert dashboard["facility_id"] == hospital["id"]
    check.assert_rate(dashboard["cohort_screened_rate"], 1.0000)
    check.assert_rate(dashboard["encounter_screened_rate"], 1.0000)
    check.assert_rate(dashboard["followup_resolution_rate"], None)
    check.assert_rate(dashboard["report_timeliness_rate"], 1.0)
    assert dashboard["performance_score"] is None
    assert dashboard["encounter_basis_performance_score"] is None
    assert dashboard["last_closed_period_label"] is not None
    assert dashboard["reporting_compliance_status"] == "COMPLIANT"
    assert dashboard["penalty_points_balance"] == 0

    stored = fixtures.read_facility(client, hospital["id"])
    check.assert_nulls(stored, ["performance_score", "encounter_basis_performance_score"])
    assert stored["last_closed_period_label"] == dashboard["last_closed_period_label"]


def test_the_close_run_still_assesses_the_facility_it_could_not_score(client):
    """A facility with no episodes is counted, escalates nothing and owes nothing.

    PRD: "Empty denominators are not re-normalised. If the cohort denominator is 0,
    the cohort rate is null and `performance_score` is null. If the encounter
    denominator is 0, `encounter_basis_performance_score` is null."

    Design: Difficulty/boundary_precision_check/empty_followup_denominator_publishes_null_scores_not_zero
    """
    hospital, period, report, _ = _one_screened_baby_and_no_episodes(client)

    closed = fixtures.close_period(client, period["id"])
    assert closed["status"] == "CLOSED"
    assert closed["facilities_assessed_count"] == 1
    assert closed["episodes_escalated_count"] == 0
    assert closed["episodes_lost_count"] == 0

    assessed = fixtures.read_report(client, report["id"])
    assert assessed["status"] == "ACCEPTED"
    assert assessed["assessed_penalty_points"] == 0
    assert assessed["auto_generated"] is False
    assert assessed["submitted_late"] is False
    assert assessed["variance_case_count"] == 0
    check.assert_facility_ledger(
        fixtures.read_facility(client, hospital["id"]),
        penalty_points_balance=0,
        reporting_compliance_status="COMPLIANT",
    )
