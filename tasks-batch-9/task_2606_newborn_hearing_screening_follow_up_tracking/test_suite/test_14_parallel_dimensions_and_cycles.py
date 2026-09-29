"""Two shapes of non-linearity: parallel dimensions on the infant, and a booking cycle."""

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
)

ADMIN = make_program_admin_headers()

BIRTH = "2026-08-02T00:00:00Z"
FINALIZE_INSTANT = "2026-09-01T00:00:00Z"


def _confirmed_loss_referred(client):
    """One infant carried by a single finalize from a birth refer to a placed referral."""
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    program = fixtures.create_facility(client, "EI1", "EI_PROGRAM", "R1")
    registry = fixtures.Registry(
        birth_hospital=hospital,
        clinic=clinic,
        ei_program=program,
        screener=fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1"),
        audiologist=fixtures.create_provider(client, clinic["id"], "AUDIOLOGIST", "A1", "R1"),
        second_audiologist=fixtures.create_provider(
            client, clinic["id"], "AUDIOLOGIST", "A2", "R1"
        ),
        navigator=fixtures.create_provider(
            client, hospital["id"], "NAVIGATOR", "N1", "R1", languages=["EN"]
        ),
        coordinator=fixtures.create_provider(
            client, program["id"], "EI_COORDINATOR", "C1", "R1"
        ),
    )
    fixtures.set_clock(client, "2026-08-02T06:00:00Z")
    infant = fixtures.create_infant(
        client,
        hospital["id"],
        birth_datetime=BIRTH,
        birth_setting="INPATIENT",
        gestational_age_weeks=39,
        preferred_language="EN",
        interpreter_required=False,
        guardian_consent_status="GRANTED",
        guardian_name="G-Y",
        guardian_contact_phone="5550301",
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
    diagnostic = fixtures.open_episode(
        client,
        infant["id"],
        "DIAGNOSTIC",
        expected_infant_version=fixtures.infant_version(client, infant["id"]),
        supersedes_episode_id=rescreen["id"],
        headers=registry.n1,
    )
    evaluation = fixtures.draft_evaluation(
        client, registry, infant["id"], diagnostic["id"], "2026-08-02T06:00:00Z"
    )
    fixtures.submit_evaluation(client, registry, evaluation["id"], 45, 50, "BILATERAL_LOSS")
    fixtures.attest_evaluation(client, registry, evaluation["id"])
    fixtures.set_clock(client, FINALIZE_INSTANT)
    fixtures.finalize_evaluation(client, registry, evaluation["id"])
    return registry, infant


def test_one_finalize_advances_both_dimensions_of_the_infant_row(client):
    """Dimension B crosses REFERRAL_DUE and lands on REFERRED inside one request.

    PRD: "Because that episode resolved, the infant's `screening_status` advances
    `DIAGNOSTIC_IN_PROGRESS → DIAGNOSED_LOSS` and, on the independent intervention
    dimension, `intervention_status` advances `NOT_APPLICABLE → REFERRAL_DUE`. Because
    `intervention_status` became `REFERRAL_DUE`, an `EarlyInterventionReferral` is
    minted in `PENDING` with its `ei_program_facility_id` chosen by the program
    selector of §3.7, and `intervention_status` immediately advances `REFERRAL_DUE →
    REFERRED`."

    Design: Difficulty/non_linear_state_machine/infant_parallel_dimensions_advance_and_stall_independently
    """
    registry, infant = _confirmed_loss_referred(client)

    check.assert_infant_dimensions(
        fixtures.read_infant(client, infant["id"]), "DIAGNOSED_LOSS", "REFERRED"
    )
    referral = check.assert_total_count(
        client.list_referrals(headers=ADMIN, infant_id=infant["id"]), 1
    )[0]
    assert referral["status"] == "PENDING"
    assert referral["ei_program_facility_id"] == registry.ei_id
    check.assert_instant_equals(referral["referred_at"], FINALIZE_INSTANT)

    task = check.assert_total_count(
        client.list_tasks(headers=ADMIN, infant_id=infant["id"], task_type="EI_LINKAGE"), 1
    )[0]
    assert task["status"] == "OPEN"
    assert task["assigned_provider_id"] == registry.n1_id
    check.assert_facility_ledger(
        fixtures.read_facility(client, registry.bh_id), navigation_budget_units_remaining=38
    )


def test_the_family_decline_moves_one_dimension_and_leaves_the_other_standing(client):
    """The screening dimension does not budge when the intervention dimension ends.

    PRD: "The service tracks each newborn along two independent dimensions at once."
    PRD: "`FAMILY_DECLINED` is a `Navigator` action available while the referral is
    `PENDING` or `ACCEPTED`: it advances the referral to `DECLINED_BY_FAMILY` with the
    reason stored in `resolution_reason`, moves the infant's `intervention_status` to
    `DECLINED`, and cancels any `EI_LINKAGE` navigation task for that infant still in
    `UNASSIGNED` or `OPEN`, crediting its `units_reserved` back to the funding
    facility's `navigation_budget_units_remaining`."

    Design: Difficulty/non_linear_state_machine/infant_parallel_dimensions_advance_and_stall_independently
    """
    registry, infant = _confirmed_loss_referred(client)
    referral = check.assert_total_count(
        client.list_referrals(headers=ADMIN, infant_id=infant["id"]), 1
    )[0]
    linkage = check.assert_total_count(
        client.list_tasks(headers=ADMIN, infant_id=infant["id"], task_type="EI_LINKAGE"), 1
    )[0]

    declined = check.assert_ok(
        client.decide_referral(
            referral["id"],
            {"decision": "FAMILY_DECLINED", "reason": "family declined early intervention"},
            headers=registry.n1,
        )
    )
    assert declined["status"] == "DECLINED_BY_FAMILY"
    assert declined["resolution_reason"] == "family declined early intervention"

    check.assert_infant_dimensions(
        fixtures.read_infant(client, infant["id"]), "DIAGNOSED_LOSS", "DECLINED"
    )
    assert fixtures.read_task(client, linkage["id"])["status"] == "CANCELLED"
    check.assert_facility_ledger(
        fixtures.read_facility(client, registry.bh_id), navigation_budget_units_remaining=40
    )


def _no_show_cycle(client):
    """A refer at birth, two slots two days apart, and one booking already no-showed."""
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    screener = fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")
    audiologist = fixtures.create_provider(client, clinic["id"], "AUDIOLOGIST", "A1", "R1")
    hospital_admin = make_facility_admin_headers(hospital["id"])

    fixtures.set_clock(client, "2026-08-02T06:00:00Z")
    infant = fixtures.create_infant(
        client,
        hospital["id"],
        birth_datetime=BIRTH,
        birth_setting="INPATIENT",
        gestational_age_weeks=39,
        guardian_name="G-Q",
        guardian_contact_phone="5550401",
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

    def _slot(day):
        return check.assert_created(
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

    first_slot = _slot(5)
    second_slot = _slot(7)
    first_appointment = check.assert_created(
        client.create_appointment(
            factories.appointment_payload(
                episode_id=episode["id"], slot_id=first_slot["id"]
            ),
            headers=hospital_admin,
        )
    )
    fixtures.set_clock(client, "2026-08-05T09:30:00Z")
    check.assert_ok(
        client.close_appointment(
            first_appointment["id"],
            {"disposition": "NO_SHOW", "reason": "family did not attend"},
            headers=hospital_admin,
        )
    )
    return {
        "infant": infant,
        "episode": episode,
        "first_slot": first_slot,
        "second_slot": second_slot,
        "first_appointment": first_appointment,
        "hospital_admin": hospital_admin,
    }


def test_a_no_show_returns_the_episode_to_scheduling_and_frees_the_slot(client):
    """The cycle's first half: back to PENDING_SCHEDULING with the attempt retained.

    PRD: "A `NO_SHOW` alone re-derives the infant's `missed_appointment_count` upward
    by one and recomputes `ltf_risk_score` and `priority_band` with the
    6-point-per-no-show term. In both cases the episode returns `SCHEDULED →
    PENDING_SCHEDULING`, and the family may be re-booked — up to three counted
    attempts, since `attempt_count` continues to count `NO_SHOW` attempts but not
    `CANCELLED` ones."

    Design: Difficulty/non_linear_state_machine/episode_no_show_cycle_returns_to_scheduled_with_attempt_count_two
    """
    scenario = _no_show_cycle(client)

    assert (
        fixtures.read_appointment(client, scenario["first_appointment"]["id"])["status"]
        == "NO_SHOW"
    )
    check.assert_episode_state(
        fixtures.read_episode(client, scenario["episode"]["id"]),
        "PENDING_SCHEDULING",
        attempt_count=1,
    )
    check.assert_slot_capacity(
        fixtures.read_slot(client, scenario["first_slot"]["id"]), 0, 1, "OPEN"
    )
    assert fixtures.read_infant(client, scenario["infant"]["id"])["missed_appointment_count"] == 1


def test_the_attempt_counter_ratchets_across_the_loop_and_never_resets(client):
    """Re-booking returns the episode to SCHEDULED with the attempts now at two.

    PRD: "Its `attempt_count` always equals the number of appointments on it whose
    status is `BOOKED`, `ATTENDED`, or `NO_SHOW`."

    Design: Difficulty/non_linear_state_machine/episode_no_show_cycle_returns_to_scheduled_with_attempt_count_two
    """
    scenario = _no_show_cycle(client)

    second_appointment = check.assert_created(
        client.create_appointment(
            factories.appointment_payload(
                episode_id=scenario["episode"]["id"], slot_id=scenario["second_slot"]["id"]
            ),
            headers=scenario["hospital_admin"],
        )
    )
    assert second_appointment["status"] == "BOOKED"

    check.assert_episode_state(
        fixtures.read_episode(client, scenario["episode"]["id"]),
        "SCHEDULED",
        attempt_count=2,
    )
    check.assert_slot_capacity(
        fixtures.read_slot(client, scenario["second_slot"]["id"]), 1, 0, "FULL"
    )
    scored = fixtures.read_infant(client, scenario["infant"]["id"])
    assert scored["missed_appointment_count"] == 1
    check.assert_risk(scored, 6, "LOW")
