"""One set of rows, two published answers: age basis and screening attribution."""

import pytest

from test_helpers import api_errors as errors
from test_helpers import assertions as check
from test_helpers import clock, factories, fixtures
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import (
    make_facility_admin_headers,
    make_facility_screener_headers,
    make_program_admin_headers,
)

ADMIN = make_program_admin_headers()

PREMATURE_BIRTH = "2026-08-03T08:00:00Z"
FINALIZE_INSTANT = "2026-12-11T08:00:00Z"

AUGUST_START = CLOCK_START
AUGUST_END = "2026-09-01T00:00:00Z"
AUGUST_DUE = "2026-09-05T00:00:00Z"


def _attested_premature_evaluation(client, registry):
    """A 32-week infant carried to an attested NO_LOSS evaluation on the diagnostic track."""
    fixtures.set_clock(client, "2026-08-03T10:00:00Z")
    infant = fixtures.create_infant(
        client,
        registry.bh_id,
        birth_datetime=PREMATURE_BIRTH,
        birth_setting="INPATIENT",
        gestational_age_weeks=32,
        nicu_stay_days=0,
        guardian_name="G-P",
        guardian_contact_phone="5550001",
    )
    fixtures.record_encounter(
        client,
        registry,
        infant["id"],
        "2026-08-03T09:00:00Z",
        encounter_type="BIRTH_ADMISSION",
        left_ear_result="REFER",
        right_ear_result="PASS",
        method="AABR",
    )
    rescreen = fixtures.episodes_of(client, infant["id"])[0]
    diagnostic = fixtures.open_episode(
        client,
        infant["id"],
        "DIAGNOSTIC",
        expected_infant_version=fixtures.infant_version(client, infant["id"]),
        supersedes_episode_id=rescreen["id"],
    )
    evaluation = fixtures.draft_evaluation(
        client, registry, infant["id"], diagnostic["id"], "2026-08-03T10:00:00Z"
    )
    fixtures.submit_evaluation(client, registry, evaluation["id"], 20, 20, "NO_LOSS")
    fixtures.attest_evaluation(client, registry, evaluation["id"], note="second reader agrees")
    fixtures.set_clock(client, FINALIZE_INSTANT)
    return infant, diagnostic, evaluation


def test_one_finalize_writes_two_disagreeing_timeliness_answers(client, registry):
    """The applied basis says ON_TIME and the chronological basis says LATE, on one row.

    PRD: "The two genuinely disagree: a 32-week infant whose evaluation is finalized
    at 130 chronological days is `ON_TIME` under the applied basis, because its
    corrected age is 74 days, and `LATE` under the chronological basis — two stored
    answers on one row, by design."

    Design: Difficulty/dual_variant_calc/diagnostic_timeliness_applied_vs_chronological_basis_on_one_row
    """
    infant, diagnostic, evaluation = _attested_premature_evaluation(client, registry)

    finalized = fixtures.finalize_evaluation(client, registry, evaluation["id"])
    assert finalized["status"] == "FINALIZED_NO_LOSS"
    check.assert_instant_equals(finalized["finalized_at"], FINALIZE_INSTANT)
    assert finalized["age_days_at_finalize"] == 130
    assert finalized["timeliness_status"] == "ON_TIME"
    assert finalized["timeliness_status_chronological_basis"] == "LATE"
    assert finalized["timeliness_status"] != finalized["timeliness_status_chronological_basis"]

    check.assert_episode_state(
        fixtures.read_episode(client, diagnostic["id"]),
        "RESOLVED_NO_LOSS",
        closure_reason="DIAGNOSIS_NO_LOSS",
        benchmark_days=90,
    )
    check.assert_infant_dimensions(
        fixtures.read_infant(client, infant["id"]), "DIAGNOSED_NO_LOSS", "NOT_APPLICABLE"
    )


def test_the_panel_carries_both_age_variants_side_by_side(client, registry):
    """The panel publishes 130 chronological days and 74 corrected days at once.

    PRD: "The **prematurity offset in days** is the number of weeks by which the
    birth fell short of term gestation, multiplied by seven, and floored at zero: term
    gestation is 40 completed weeks, so an infant of 32 completed weeks carries an
    offset of 56 days, while an infant of 40 or more completed weeks carries an offset
    of 0."

    Design: Difficulty/dual_variant_calc/diagnostic_timeliness_applied_vs_chronological_basis_on_one_row
    """
    infant, _, evaluation = _attested_premature_evaluation(client, registry)
    fixtures.finalize_evaluation(client, registry, evaluation["id"])

    panel = check.assert_ok(client.get_timeliness(infant["id"], headers=ADMIN))
    check.assert_timeliness_panel(
        panel,
        infant_id=infant["id"],
        chronological_age_days=130,
        prematurity_offset_days=56,
        corrected_age_days=74,
        effective_age_days=74,
        benchmark_age_basis="CORRECTED",
        diagnostic_timeliness_status="ON_TIME",
        diagnostic_timeliness_status_chronological_basis="LATE",
    )
    assert panel["corrected_age_days"] == panel["chronological_age_days"] - 56


def _august_cohort_of_two(client):
    """One baby screened before discharge, one discharged unscreened, and an on-time filing."""
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    screener = fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")
    screener_headers = make_facility_screener_headers(screener["id"])
    period = fixtures.open_period(client, AUGUST_START, AUGUST_END, AUGUST_DUE)

    fixtures.set_clock(client, "2026-08-05T06:00:00Z")
    screened = fixtures.create_infant(
        client,
        hospital["id"],
        birth_datetime="2026-08-05T00:00:00Z",
        birth_setting="INPATIENT",
        guardian_name="G-X1",
        guardian_contact_phone="5550011",
    )
    check.assert_created(
        client.create_encounter(
            factories.encounter_payload(
                infant_id=screened["id"],
                facility_id=hospital["id"],
                performed_by_provider_id=screener["id"],
                performed_at="2026-08-05T04:00:00Z",
                encounter_type="BIRTH_ADMISSION",
                method="OAE",
                left_ear_result="PASS",
                right_ear_result="PASS",
            ),
            headers=screener_headers,
        )
    )

    fixtures.set_clock(client, "2026-08-31T20:00:00Z")
    unscreened = fixtures.create_infant(
        client,
        hospital["id"],
        birth_datetime="2026-08-31T12:00:00Z",
        birth_setting="INPATIENT",
        guardian_name="G-X2",
        guardian_contact_phone="5550012",
    )
    check.assert_ok(
        client.discharge_infant(
            unscreened["id"],
            {"discharge_datetime": "2026-08-31T20:00:00Z"},
            headers=screener_headers,
        )
    )

    fixtures.set_clock(client, "2026-09-02T00:00:00Z")
    report = fixtures.file_report(
        client,
        hospital["id"],
        period["id"],
        attested_screened_count=1,
        attested_refer_count=0,
    )
    return hospital, period, report, screened, unscreened


def test_the_two_attribution_bases_publish_forty_five_and_seventy(client):
    """Identical rows yield 45.00 on the cohort basis and 70.00 on the encounter basis.

    PRD: "Continuing the two-infant illustration above, with a follow-up resolution
    rate of 0.0000 and a report timeliness rate of 1.0, the two published figures are
    45.00 and 70.00 — same rows, two answers, which is the whole point of carrying
    both."

    Design: Difficulty/dual_variant_calc/facility_performance_cohort_vs_encounter_basis_diverge_45_vs_70
    """
    hospital, period, report, _, _ = _august_cohort_of_two(client)

    closed = fixtures.close_period(client, period["id"])
    assert closed["status"] == "CLOSED"

    assessed = fixtures.read_facility(client, hospital["id"])
    check.assert_score(assessed["performance_score"], 45.00)
    check.assert_score(assessed["encounter_basis_performance_score"], 70.00)
    assert (
        assessed["encounter_basis_performance_score"] - assessed["performance_score"]
        == pytest.approx(25.00, abs=0.01)
    )
    check.assert_facility_ledger(
        assessed, penalty_points_balance=0, reporting_compliance_status="COMPLIANT"
    )

    settled = fixtures.read_report(client, report["id"])
    assert settled["status"] == "ACCEPTED"
    assert settled["variance_case_count"] == 0
    assert settled["assessed_penalty_points"] == 0
    assert settled["auto_generated"] is False
    assert settled["submitted_late"] is False


def test_the_dashboard_shows_the_rates_that_produced_the_two_scores(client):
    """The unscreened baby counts against one denominator and leaves the other.

    PRD: "For one small cohort of two infants where the second is discharged
    unscreened, the cohort-basis rate is 0.5000 while the encounter-basis rate is
    1.0000 from identical rows."

    Design: Difficulty/dual_variant_calc/facility_performance_cohort_vs_encounter_basis_diverge_45_vs_70
    """
    hospital, period, _, _, _ = _august_cohort_of_two(client)
    fixtures.close_period(client, period["id"])

    dashboard = check.assert_ok(
        client.get_facility_performance(hospital["id"], headers=ADMIN)
    )
    assert dashboard["facility_id"] == hospital["id"]
    check.assert_rate(dashboard["cohort_screened_rate"], 0.5000)
    check.assert_rate(dashboard["encounter_screened_rate"], 1.0000)
    check.assert_rate(dashboard["followup_resolution_rate"], 0.0000)
    check.assert_rate(dashboard["report_timeliness_rate"], 1.0)
    check.assert_score(dashboard["performance_score"], 45.00)
    check.assert_score(dashboard["encounter_basis_performance_score"], 70.00)
    assert dashboard["reporting_compliance_status"] == "COMPLIANT"
    assert dashboard["penalty_points_balance"] == 0
    assert dashboard["last_closed_period_label"] is not None
