"""Two chains where every link exists only because the previous link fired."""

import pytest

from test_helpers import api_errors as errors
from test_helpers import assertions as check
from test_helpers import clock, factories, fixtures
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import (
    make_facility_screener_headers,
    make_navigator_headers,
    make_program_admin_headers,
)

ADMIN = make_program_admin_headers()

BIRTH = "2026-08-02T00:00:00Z"
FINALIZE_INSTANT = "2026-09-15T00:00:00Z"


def _home_birth_confirmed_loss(client):
    """A home-birth infant carried to an attested loss, finalized 44 days after birth."""
    practice = fixtures.create_facility(
        client, "MW1", "MIDWIFE_PRACTICE", "R1", navigation_budget_units_total=40
    )
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    program = fixtures.create_facility(client, "EI1", "EI_PROGRAM", "R1")
    registry = fixtures.Registry(
        birth_hospital=practice,
        clinic=clinic,
        ei_program=program,
        screener=fixtures.create_provider(client, practice["id"], "SCREENER", "S1", "R1"),
        audiologist=fixtures.create_provider(client, clinic["id"], "AUDIOLOGIST", "A1", "R1"),
        second_audiologist=fixtures.create_provider(
            client, clinic["id"], "AUDIOLOGIST", "A2", "R1"
        ),
        navigator=fixtures.create_provider(
            client, practice["id"], "NAVIGATOR", "N1", "R1", languages=["EN"]
        ),
        coordinator=fixtures.create_provider(
            client, program["id"], "EI_COORDINATOR", "C1", "R1"
        ),
    )
    fixtures.set_clock(client, "2026-08-02T06:00:00Z")
    infant = fixtures.create_infant(
        client,
        practice["id"],
        birth_datetime=BIRTH,
        birth_setting="HOME_BIRTH",
        gestational_age_weeks=39,
        preferred_language="EN",
        interpreter_required=False,
        guardian_name="G-P2",
        guardian_contact_phone="5550501",
    )
    check.assert_risk(infant, 15, "ELEVATED")
    fixtures.record_encounter(
        client,
        registry,
        infant["id"],
        "2026-08-02T05:00:00Z",
        encounter_type="HOME_VISIT",
        method="OAE",
        left_ear_result="REFER",
        right_ear_result="REFER",
    )
    initial = fixtures.episodes_of(client, infant["id"])[0]
    diagnostic = fixtures.open_episode(
        client,
        infant["id"],
        "DIAGNOSTIC",
        expected_infant_version=fixtures.infant_version(client, infant["id"]),
        supersedes_episode_id=initial["id"],
        headers=registry.n1,
    )
    evaluation = fixtures.draft_evaluation(
        client, registry, infant["id"], diagnostic["id"], "2026-08-02T06:00:00Z"
    )
    fixtures.submit_evaluation(client, registry, evaluation["id"], 45, 50, "BILATERAL_LOSS")
    fixtures.attest_evaluation(
        client, registry, evaluation["id"], note="confirmed by second reader"
    )
    fixtures.set_clock(client, FINALIZE_INSTANT)
    return registry, infant, diagnostic, evaluation


def test_the_finalize_carries_the_diagnosis_through_episode_and_infant(client):
    """Links one to three: the evaluation, its episode, and both infant dimensions.

    PRD: "Because the evaluation reached `FINALIZED_LOSS`, its episode advances to
    `RESOLVED_DIAGNOSED` with `closure_reason` `DIAGNOSIS_CONFIRMED`, `closed_at` at
    the logical clock, and its own `timeliness_status` written"

    Design: Difficulty/transitive_cascade/finalize_loss_cascade_six_links_home_birth_risk_15_to_7
    """
    registry, infant, diagnostic, evaluation = _home_birth_confirmed_loss(client)

    finalized = fixtures.finalize_evaluation(client, registry, evaluation["id"])
    assert finalized["status"] == "FINALIZED_LOSS"
    check.assert_instant_equals(finalized["finalized_at"], FINALIZE_INSTANT)
    assert finalized["age_days_at_finalize"] == 44
    assert finalized["timeliness_status"] == "ON_TIME"

    closed_episode = fixtures.read_episode(client, diagnostic["id"])
    check.assert_episode_state(
        closed_episode,
        "RESOLVED_DIAGNOSED",
        closure_reason="DIAGNOSIS_CONFIRMED",
        benchmark_days=90,
    )
    check.assert_instant_equals(closed_episode["closed_at"], FINALIZE_INSTANT)
    check.assert_infant_dimensions(
        fixtures.read_infant(client, infant["id"]), "DIAGNOSED_LOSS", "REFERRED"
    )


def test_the_referral_the_task_and_the_relief_term_all_land_in_one_request(client):
    """Links four to six: the placement, the funded task, and the rescored infant.

    PRD: "And because that task now exists, the infant's `ltf_risk_score` is
    recomputed with the navigation-relief term and its `priority_band` rewritten. All
    six links complete before the request returns."

    Design: Difficulty/transitive_cascade/finalize_loss_cascade_six_links_home_birth_risk_15_to_7
    """
    registry, infant, _, evaluation = _home_birth_confirmed_loss(client)
    fixtures.finalize_evaluation(client, registry, evaluation["id"])

    referral = check.assert_total_count(
        client.list_referrals(headers=ADMIN, infant_id=infant["id"]), 1
    )[0]
    assert referral["status"] == "PENDING"
    assert referral["ei_program_facility_id"] == registry.ei_id
    assert referral["diagnostic_evaluation_id"] == evaluation["id"]

    task = check.assert_total_count(
        client.list_tasks(headers=ADMIN, infant_id=infant["id"], task_type="EI_LINKAGE"), 1
    )[0]
    assert task["status"] == "OPEN"
    assert task["assigned_provider_id"] == registry.n1_id
    assert task["units_reserved"] == 2
    assert task["budget_shortfall_flag"] is False
    assert task["funding_facility_id"] == registry.bh_id

    check.assert_facility_ledger(
        fixtures.read_facility(client, registry.bh_id), navigation_budget_units_remaining=38
    )
    assert fixtures.read_provider(client, registry.n1_id)["open_task_count"] == 1
    check.assert_risk(fixtures.read_infant(client, infant["id"]), 7, "LOW")


def _lost_to_follow_up(client):
    """Three no-shows and a period close that sweeps the episode into loss."""
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    screener = fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")
    navigator = fixtures.create_provider(
        client, hospital["id"], "NAVIGATOR", "N1", "R1", languages=["EN"]
    )
    audiologist = fixtures.create_provider(client, clinic["id"], "AUDIOLOGIST", "A1", "R1")
    navigator_headers = make_navigator_headers(navigator["id"])
    period = fixtures.open_period(
        client, CLOCK_START, "2026-10-01T00:00:00Z", "2026-10-05T00:00:00Z"
    )

    fixtures.set_clock(client, "2026-08-02T06:00:00Z")
    infant = fixtures.create_infant(
        client,
        hospital["id"],
        birth_datetime=BIRTH,
        birth_setting="INPATIENT",
        gestational_age_weeks=39,
        preferred_language="EN",
        guardian_name="G-Z",
        guardian_contact_phone="5550601",
    )
    check.assert_created(
        client.create_encounter(
            factories.encounter_payload(
                infant_id=infant["id"],
                facility_id=hospital["id"],
                performed_by_provider_id=screener["id"],
                performed_at="2026-08-02T05:00:00Z",
                encounter_type="BIRTH_ADMISSION",
                method="AABR",
                left_ear_result="REFER",
                right_ear_result="PASS",
            ),
            headers=make_facility_screener_headers(screener["id"]),
        )
    )
    episode = fixtures.episodes_of(client, infant["id"])[0]

    for day in (5, 7, 9):
        slot = check.assert_created(
            client.create_slot(
                factories.slot_payload(
                    facility_id=clinic["id"],
                    provider_id=audiologist["id"],
                    starts_at="2026-08-{0:02d}T09:00:00Z".format(day),
                    ends_at="2026-08-{0:02d}T10:00:00Z".format(day),
                    slot_type="RESCREEN",
                    total_capacity=1,
                ),
                headers=ADMIN,
            )
        )
        appointment = fixtures.book(
            client, episode["id"], slot["id"], headers=navigator_headers
        )
        fixtures.set_clock(client, "2026-08-{0:02d}T09:30:00Z".format(day))
        fixtures.close_appointment(
            client,
            appointment["id"],
            "NO_SHOW",
            reason="no answer at door",
            headers=navigator_headers,
        )

    fixtures.set_clock(client, "2026-10-20T00:00:00Z")
    closed_period = fixtures.close_period(client, period["id"])
    return {
        "hospital": hospital,
        "navigator": navigator,
        "navigator_headers": navigator_headers,
        "infant": infant,
        "episode": episode,
        "period": closed_period,
    }


def test_the_close_run_loses_the_episode_the_outreach_will_later_reopen(client):
    """The sweep writes the loss, and a WATCH posture escalates nothing.

    PRD: "an episode still in `PENDING_SCHEDULING` whose applied-basis effective age
    exceeds its `benchmark_days` plus 45 days and whose `attempt_count` has reached 3
    is moved `PENDING_SCHEDULING → LOST_TO_FOLLOW_UP` with `closure_reason`
    `LOST_TO_FOLLOW_UP`, `closed_at` at the logical clock, and `timeliness_status`
    `OVERDUE`"

    Design: Difficulty/transitive_cascade/reengagement_cascade_from_task_close_restores_episode_and_rescores_to_30
    """
    scenario = _lost_to_follow_up(client)

    lost = fixtures.read_episode(client, scenario["episode"]["id"])
    check.assert_episode_state(
        lost,
        "LOST_TO_FOLLOW_UP",
        closure_reason="LOST_TO_FOLLOW_UP",
        timeliness_status="OVERDUE",
        attempt_count=3,
    )
    assert lost["escalation_flag"] is False
    assert lost["owner_scope"] == "FACILITY"
    assert scenario["period"]["episodes_lost_count"] == 1
    assert scenario["period"]["episodes_escalated_count"] == 0

    check.assert_facility_ledger(
        fixtures.read_facility(client, scenario["hospital"]["id"]),
        penalty_points_balance=9,
        reporting_compliance_status="WATCH",
    )
    swept = fixtures.read_infant(client, scenario["infant"]["id"])
    assert swept["screening_status"] == "LOST_TO_FOLLOW_UP"
    assert swept["missed_appointment_count"] == 3
    check.assert_risk(swept, 18, "ELEVATED")


def test_completing_an_outreach_task_reopens_the_episode_and_rescores(client):
    """Three links from one close: task, episode, infant — and the attempts survive.

    PRD: "When a navigator completes an outreach task with an outcome of
    `FAMILY_REENGAGED`, a three-link cascade runs: that infant's episode in
    `LOST_TO_FOLLOW_UP` returns to `PENDING_SCHEDULING` with `closure_reason` and
    `closed_at` both cleared to null while `escalation_flag` and `owner_scope` are
    preserved; because the episode left `LOST_TO_FOLLOW_UP`, the infant advances
    `LOST_TO_FOLLOW_UP → REFERRED` and its `reengagement_count` increments by 1"

    Design: Difficulty/transitive_cascade/reengagement_cascade_from_task_close_restores_episode_and_rescores_to_30
    """
    scenario = _lost_to_follow_up(client)
    task = fixtures.create_task(
        client,
        scenario["infant"]["id"],
        "OUTREACH_CALL",
        headers=scenario["navigator_headers"],
        episode_id=scenario["episode"]["id"],
        auto_assign=True,
    )
    assert task["status"] == "OPEN"
    assert task["assigned_provider_id"] == scenario["navigator"]["id"]

    closed = fixtures.close_task(
        client,
        task["id"],
        "COMPLETED",
        outcome="FAMILY_REENGAGED",
        contacted_language="EN",
        headers=scenario["navigator_headers"],
    )
    assert closed["status"] == "COMPLETED"
    assert closed["outcome"] == "FAMILY_REENGAGED"

    reopened = fixtures.read_episode(client, scenario["episode"]["id"])
    check.assert_episode_state(reopened, "PENDING_SCHEDULING", attempt_count=3)
    assert reopened["closure_reason"] is None
    assert reopened["closed_at"] is None

    reengaged = fixtures.read_infant(client, scenario["infant"]["id"])
    assert reengaged["screening_status"] == "REFERRED"
    assert reengaged["reengagement_count"] == 1
    check.assert_risk(reengaged, 30, "HIGH")
