"""Computed reads: the timeliness panel, the preference patch, and booking visibility."""

import pytest

from test_helpers import api_errors as errors
from test_helpers import assertions as check
from test_helpers import clock, factories, fixtures
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import (
    make_facility_admin_headers,
    make_facility_screener_headers,
    make_navigator_headers,
    make_program_admin_headers,
    make_program_auditor_headers,
)

ADMIN = make_program_admin_headers()
AUDITOR = make_program_auditor_headers()


def test_the_preference_patch_touches_only_what_it_names(client):
    """Two supplied fields change, the rest survive, and the score is re-derived.

    PRD: "The **language-gap term** contributes 10 points when the infant's
    `interpreter_required` is true and there is no provider at all whose
    `provider_type` is `NAVIGATOR`, whose `credential_status` is `ACTIVE`, whose
    `region_code` matches the region code of the infant's birth facility, and whose
    `languages` array contains the infant's `preferred_language`".

    Design: Corner/endpoints/contact_preferences_patch_updates_supplied_fields_and_rescores_language_gap
    """
    practice = fixtures.create_facility(client, "MW1", "MIDWIFE_PRACTICE", "R1")
    screener = fixtures.create_provider(client, practice["id"], "SCREENER", "S1", "R1")
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    navigator = fixtures.create_provider(
        client, clinic["id"], "NAVIGATOR", "N1", "R1", languages=["EN"]
    )
    fixtures.set_clock(client, clock.at(hours=6))
    infant = check.assert_created(
        client.create_infant(
            factories.infant_payload(
                birth_facility_id=practice["id"],
                birth_datetime=CLOCK_START,
                birth_setting="HOME_BIRTH",
                gestational_age_weeks=39,
                guardian_name="G-PT",
                guardian_contact_phone="5555101",
            ),
            headers=make_facility_screener_headers(screener["id"]),
        )
    )
    check.assert_risk(infant, 15, "ELEVATED")

    patched = check.assert_ok(
        client.patch_contact_preferences(
            infant["id"],
            {"preferred_language": "ZH", "interpreter_required": True},
            headers=make_navigator_headers(navigator["id"]),
        )
    )
    assert patched["preferred_language"] == "ZH"
    assert patched["interpreter_required"] is True
    assert patched["guardian_contact_phone"] == "5555101"
    assert patched["guardian_consent_status"] == "GRANTED"
    check.assert_risk(patched, 25, "ELEVATED")
    check.assert_versioned(patched, 2)


def test_the_timeliness_panel_derives_the_corrected_basis_for_a_nicu_stay(client):
    """A five-day NICU stay forces the corrected basis on its own.

    PRD: "The `benchmark_age_basis` is `CORRECTED` when the infant's
    `gestational_age_weeks` is below 35 or the infant's `nicu_stay_days` is 5 or more,
    and `CHRONOLOGICAL` otherwise."

    Design: Corner/endpoints/timeliness_read_returns_corrected_age_for_a_nicu_infant
    """
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    screener = fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")
    screener_headers = make_facility_screener_headers(screener["id"])
    fixtures.set_clock(client, "2026-08-02T00:00:00Z")
    infant = check.assert_created(
        client.create_infant(
            factories.infant_payload(
                birth_facility_id=hospital["id"],
                birth_datetime=CLOCK_START,
                birth_setting="INPATIENT",
                gestational_age_weeks=36,
                nicu_stay_days=5,
                guardian_name="G-CR",
                guardian_contact_phone="5555401",
            ),
            headers=screener_headers,
        )
    )
    check.assert_ok(
        client.discharge_infant(
            infant["id"],
            {"discharge_datetime": "2026-08-02T00:00:00Z"},
            headers=screener_headers,
        )
    )
    fixtures.set_clock(client, "2026-11-09T00:00:00Z")
    family_history = fixtures.register_risk_factor(
        client,
        infant["id"],
        "FAMILY_HISTORY",
        "2026-11-09T00:00:00Z",
        headers=screener_headers,
    )

    panel = check.assert_ok(client.get_timeliness(infant["id"], headers=AUDITOR))
    check.assert_timeliness_panel(
        panel,
        infant_id=infant["id"],
        chronological_age_days=100,
        prematurity_offset_days=28,
        corrected_age_days=72,
        effective_age_days=72,
        benchmark_age_basis="CORRECTED",
        screening_timeliness_status="OVERDUE",
        diagnostic_timeliness_status="PENDING",
        ltf_risk_score=28,
        priority_band="ELEVATED",
    )

    entries = check.assert_total_count(
        client.list_risk_factor_entries(infant["id"], headers=ADMIN), 2
    )
    auto = [row for row in entries if row["risk_factor_code"] == "NICU_5_PLUS_DAYS"][0]
    assert auto["source"] == "REGISTRY_AUTO"
    assert auto["status"] == "ACTIVE"
    check.assert_instant_equals(auto["identified_at"], CLOCK_START)
    check.assert_instant_equals(auto["surveillance_due_date"], "2027-04-28T00:00:00Z")
    stored_family_history = [row for row in entries if row["id"] == family_history["id"]][0]
    check.assert_instant_equals(
        stored_family_history["surveillance_due_date"], "2027-04-28T00:00:00Z"
    )


def test_one_booking_leaves_every_touched_row_already_consistent(client):
    """Five rows move on one write and each reads back correct on the next call.

    PRD: "All six links complete before the request returns."

    Design: Corner/consistency_model/booking_side_effects_are_all_visible_without_any_further_write
    """
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    screener = fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")
    screener_headers = make_facility_screener_headers(screener["id"])
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    audiologist = fixtures.create_provider(client, clinic["id"], "AUDIOLOGIST", "A1", "R1")
    navigator = fixtures.create_provider(
        client, clinic["id"], "NAVIGATOR", "N1", "R1", languages=["EN", "ES"]
    )
    navigator_headers = make_navigator_headers(navigator["id"])
    fixtures.set_clock(client, clock.at(hours=6))
    infant = check.assert_created(
        client.create_infant(
            factories.infant_payload(
                birth_facility_id=hospital["id"],
                birth_datetime=CLOCK_START,
                birth_setting="INPATIENT",
                gestational_age_weeks=39,
                preferred_language="ES",
                interpreter_required=True,
                guardian_name="G-IM",
                guardian_contact_phone="5556801",
            ),
            headers=screener_headers,
        )
    )
    check.assert_created(
        client.create_encounter(
            factories.encounter_payload(
                infant_id=infant["id"],
                facility_id=hospital["id"],
                performed_by_provider_id=screener["id"],
                performed_at=clock.at(hours=4),
                encounter_type="BIRTH_ADMISSION",
                method="AABR",
                left_ear_result="REFER",
                right_ear_result="REFER",
            ),
            headers=screener_headers,
        )
    )
    episode = fixtures.episodes_of(client, infant["id"])[0]
    slot = check.assert_created(
        client.create_slot(
            factories.slot_payload(
                facility_id=clinic["id"],
                provider_id=audiologist["id"],
                starts_at="2026-08-05T09:00:00Z",
                ends_at="2026-08-05T10:00:00Z",
                slot_type="RESCREEN",
            ),
            headers=make_facility_admin_headers(clinic["id"]),
        )
    )

    appointment = check.assert_created(
        client.create_appointment(
            factories.appointment_payload(
                episode_id=episode["id"], slot_id=slot["id"], interpreter_needed=True
            ),
            headers=navigator_headers,
        )
    )
    assert appointment["status"] == "BOOKED"
    assert appointment["infant_id"] == infant["id"]
    task_id = appointment["linked_navigation_task_id"]
    assert task_id is not None

    check.assert_slot_capacity(
        check.assert_ok(client.get_slot(slot["id"], headers=navigator_headers)), 1, 0, "FULL"
    )
    check.assert_episode_state(
        check.assert_ok(client.get_episode(episode["id"], headers=navigator_headers)),
        "SCHEDULED",
        attempt_count=1,
    )

    task = check.assert_ok(client.get_task(task_id, headers=navigator_headers))
    assert task["task_type"] == "INTERPRETER_SESSION"
    assert task["status"] == "OPEN"
    assert task["assigned_provider_id"] == navigator["id"]
    assert task["units_reserved"] == 5
    assert task["episode_id"] == episode["id"]
    assert task["funding_facility_id"] == hospital["id"]

    check.assert_facility_ledger(
        check.assert_ok(client.get_facility(hospital["id"], headers=navigator_headers)),
        navigation_budget_units_remaining=35,
    )
    check.assert_risk(
        check.assert_ok(client.get_infant(infant["id"], headers=navigator_headers)), 0, "LOW"
    )
