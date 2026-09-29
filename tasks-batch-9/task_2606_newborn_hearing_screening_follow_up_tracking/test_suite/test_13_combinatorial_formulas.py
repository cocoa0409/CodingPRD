"""Two pinned arithmetic orders: one rounding, one tier evaluation."""

import pytest

from test_helpers import api_errors as errors
from test_helpers import assertions as check
from test_helpers import clock, factories, fixtures
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import (
    make_audiologist_headers,
    make_facility_admin_headers,
    make_facility_screener_headers,
    make_program_admin_headers,
    make_program_auditor_headers,
)

ADMIN = make_program_admin_headers()
AUDITOR = make_program_auditor_headers()

AUGUST_END = "2026-09-01T00:00:00Z"
AUGUST_DUE = "2026-09-05T00:00:00Z"
CLOSE_INSTANT = "2026-09-02T00:00:00Z"


def _three_infant_august(client):
    """One rescreened to resolution, one still pending, one discharged unscreened."""
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    screener = fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")
    audiologist = fixtures.create_provider(client, clinic["id"], "AUDIOLOGIST", "A1", "R1")
    screener_headers = make_facility_screener_headers(screener["id"])
    period = fixtures.open_period(client, CLOCK_START, AUGUST_END, AUGUST_DUE)

    def _birth_screen(infant_id, performed_at, left, right):
        return check.assert_created(
            client.create_encounter(
                factories.encounter_payload(
                    infant_id=infant_id,
                    facility_id=hospital["id"],
                    performed_by_provider_id=screener["id"],
                    performed_at=performed_at,
                    encounter_type="BIRTH_ADMISSION",
                    method="AABR",
                    left_ear_result=left,
                    right_ear_result=right,
                ),
                headers=screener_headers,
            )
        )

    fixtures.set_clock(client, "2026-08-02T06:00:00Z")
    resolved = fixtures.create_infant(
        client,
        hospital["id"],
        birth_datetime="2026-08-02T00:00:00Z",
        birth_setting="INPATIENT",
        guardian_name="G-K1",
        guardian_contact_phone="5550101",
    )
    _birth_screen(resolved["id"], "2026-08-02T05:00:00Z", "REFER", "PASS")
    resolved_episode = fixtures.episodes_of(client, resolved["id"])[0]
    slot = check.assert_created(
        client.create_slot(
            factories.slot_payload(
                facility_id=clinic["id"],
                provider_id=audiologist["id"],
                starts_at="2026-08-10T09:00:00Z",
                ends_at="2026-08-10T10:00:00Z",
                slot_type="RESCREEN",
                total_capacity=1,
            ),
            headers=ADMIN,
        )
    )
    appointment = check.assert_created(
        client.create_appointment(
            factories.appointment_payload(
                episode_id=resolved_episode["id"], slot_id=slot["id"]
            ),
            headers=ADMIN,
        )
    )
    fixtures.set_clock(client, "2026-08-10T09:30:00Z")
    check.assert_created(
        client.create_encounter(
            factories.encounter_payload(
                infant_id=resolved["id"],
                facility_id=clinic["id"],
                performed_by_provider_id=audiologist["id"],
                performed_at="2026-08-10T09:15:00Z",
                encounter_type="OUTPATIENT_RESCREEN",
                method="AABR",
                left_ear_result="PASS",
                right_ear_result="PASS",
                episode_id=resolved_episode["id"],
                appointment_id=appointment["id"],
            ),
            headers=make_audiologist_headers(audiologist["id"]),
        )
    )

    fixtures.set_clock(client, "2026-08-11T06:00:00Z")
    pending = fixtures.create_infant(
        client,
        hospital["id"],
        birth_datetime="2026-08-11T00:00:00Z",
        birth_setting="INPATIENT",
        guardian_name="G-K2",
        guardian_contact_phone="5550102",
    )
    _birth_screen(pending["id"], "2026-08-11T05:00:00Z", "REFER", "REFER")

    fixtures.set_clock(client, "2026-08-12T12:00:00Z")
    unscreened = fixtures.create_infant(
        client,
        hospital["id"],
        birth_datetime="2026-08-12T00:00:00Z",
        birth_setting="INPATIENT",
        guardian_name="G-K3",
        guardian_contact_phone="5550103",
    )
    check.assert_ok(
        client.discharge_infant(
            unscreened["id"],
            {"discharge_datetime": "2026-08-12T12:00:00Z"},
            headers=screener_headers,
        )
    )

    fixtures.set_clock(client, CLOSE_INSTANT)
    report = fixtures.file_report(
        client,
        hospital["id"],
        period["id"],
        attested_screened_count=2,
        attested_refer_count=2,
    )
    return {
        "hospital": hospital,
        "clinic": clinic,
        "period": period,
        "report": report,
        "resolved_episode": resolved_episode,
    }


def test_the_weighted_sum_is_rounded_once_and_lands_on_sixty_three_thirty_three(client):
    """Rounding the three products first would publish one cent too much.

    PRD: "The three rounded rates are multiplied by their weights and the three
    products summed at full precision without intermediate rounding; the sum is
    multiplied by 100 and rounded once to 2 decimal places, round-half-up."

    Design: Difficulty/combinatorial_formula/performance_score_pinned_rounding_order_63_33_not_63_34
    """
    scenario = _three_infant_august(client)
    fixtures.close_period(client, scenario["period"]["id"])

    assessed = fixtures.read_facility(client, scenario["hospital"]["id"])
    check.assert_score(assessed["performance_score"], 63.33)
    assert assessed["performance_score"] != pytest.approx(63.34, abs=0.001)
    check.assert_score(assessed["encounter_basis_performance_score"], 80.00)
    check.assert_episode_state(
        fixtures.read_episode(client, scenario["resolved_episode"]["id"]),
        "RESOLVED_PASS",
        closure_reason="RESCREEN_PASSED",
    )


def test_each_component_rate_is_rounded_to_four_places_before_it_is_weighted(client):
    """The dashboard shows the two thirds and one third that produced the score.

    PRD: "Each of the three rates is rounded to 4 decimal places, round-half-up. The
    screened-before-discharge rate is weighted at 0.50, the follow-up resolution rate
    at 0.30, and the report timeliness rate at 0.20."

    Design: Difficulty/combinatorial_formula/performance_score_pinned_rounding_order_63_33_not_63_34
    """
    scenario = _three_infant_august(client)
    fixtures.close_period(client, scenario["period"]["id"])

    dashboard = check.assert_ok(
        client.get_facility_performance(scenario["hospital"]["id"], headers=AUDITOR)
    )
    check.assert_rate(dashboard["cohort_screened_rate"], 0.6667)
    check.assert_rate(dashboard["encounter_screened_rate"], 1.0000)
    check.assert_rate(dashboard["followup_resolution_rate"], 0.3333)
    check.assert_rate(dashboard["report_timeliness_rate"], 1.0)

    settled = fixtures.read_report(client, scenario["report"]["id"])
    assert settled["actual_screened_count"] == 2
    assert settled["actual_refer_count"] == 2
    assert settled["variance_case_count"] == 0
    assert settled["assessed_penalty_points"] == 0

    non_filer = fixtures.read_facility(client, scenario["clinic"]["id"])
    check.assert_facility_ledger(
        non_filer, penalty_points_balance=6, reporting_compliance_status="WATCH"
    )


def _carryover_of_six(client):
    """A facility already six points down, filing an over-attested report on time."""
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    screener = fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")
    period = fixtures.open_period(client, CLOCK_START, AUGUST_END, AUGUST_DUE)

    fixtures.set_clock(client, "2026-08-05T06:00:00Z")
    infant = fixtures.create_infant(
        client,
        hospital["id"],
        birth_datetime="2026-08-05T00:00:00Z",
        birth_setting="INPATIENT",
        guardian_name="G-M",
        guardian_contact_phone="5550201",
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
    fixtures.adjust_penalty(
        client, hospital["id"], 6, reason="prior-period audit finding carried forward"
    )
    carried = fixtures.read_facility(client, hospital["id"])
    check.assert_facility_ledger(
        carried,
        penalty_points_balance=6,
        reporting_compliance_status="WATCH",
        manual_adjustment_points_total=6,
    )

    fixtures.set_clock(client, CLOSE_INSTANT)
    report = fixtures.file_report(
        client,
        hospital["id"],
        period["id"],
        attested_screened_count=3,
        attested_refer_count=0,
    )
    return hospital, period, report


def test_the_tier_reads_the_pre_surcharge_total_but_multiplies_the_base_alone(client):
    """Four base points and six carried points assess six, not four and not fifteen.

    PRD: "The surcharge tier is keyed on the pre-surcharge total, that is the base
    points added to the carryover: a total of 4 or less attracts no surcharge, a total
    from 5 through 9 attracts a 25 percent surcharge, and a total of 10 or more
    attracts a 50 percent surcharge. The surcharge then multiplies the **base points
    only** — never the carryover — and that single product is rounded half-up to a
    whole number to give the report's `assessed_penalty_points`."

    Design: Difficulty/combinatorial_formula/penalty_tier_keyed_on_pre_surcharge_total_assessed_6_balance_12
    """
    _, period, report = _carryover_of_six(client)
    fixtures.close_period(client, period["id"])

    settled = check.assert_ok(client.get_report(report["id"], headers=AUDITOR))
    assert settled["variance_case_count"] == 2
    assert settled["submitted_late"] is False
    assert settled["status"] == "ACCEPTED"
    assert settled["accepted_by_user_id"] is None
    assert settled["assessed_penalty_points"] == 6
    assert settled["assessed_penalty_points"] != 4
    assert settled["assessed_penalty_points"] != 15


def test_the_new_balance_is_the_carryover_plus_the_assessment(client):
    """Six carried plus six assessed is twelve, and twelve is PROBATION.

    PRD: "The facility's new `penalty_points_balance` is the carryover plus the
    assessed points."

    Design: Difficulty/combinatorial_formula/penalty_tier_keyed_on_pre_surcharge_total_assessed_6_balance_12
    """
    hospital, period, _ = _carryover_of_six(client)
    fixtures.close_period(client, period["id"])

    assessed = fixtures.read_facility(client, hospital["id"])
    check.assert_facility_ledger(
        assessed,
        penalty_points_balance=12,
        reporting_compliance_status="PROBATION",
        manual_adjustment_points_total=6,
    )
    check.assert_nulls(
        assessed, ["performance_score", "encounter_basis_performance_score"]
    )
