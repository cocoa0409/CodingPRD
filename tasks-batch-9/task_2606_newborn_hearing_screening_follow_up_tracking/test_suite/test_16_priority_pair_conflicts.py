"""Requests that break two rules at once, where only the earlier check may answer."""

import pytest

from test_helpers import api_errors as errors
from test_helpers import assertions as check
from test_helpers import clock, factories, fixtures
from test_helpers.test_users import (
    make_audiologist_headers,
    make_facility_screener_headers,
    make_program_admin_headers,
)

ADMIN = make_program_admin_headers()

BIRTH = "2026-08-02T00:00:00Z"
SLOT_START = "2026-08-05T09:00:00Z"
SLOT_END = "2026-08-05T10:00:00Z"
AFTER_THE_SLOT = "2026-08-06T00:00:00Z"


def _declined_episode_and_a_slot_gone_by(client):
    """A family-declined episode and a slot that the clock has already passed."""
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    screener = fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")
    audiologist = fixtures.create_provider(client, clinic["id"], "AUDIOLOGIST", "A1", "R1")
    fixtures.set_clock(client, "2026-08-02T06:00:00Z")
    infant = fixtures.create_infant(
        client,
        hospital["id"],
        birth_datetime=BIRTH,
        birth_setting="INPATIENT",
        gestational_age_weeks=39,
        guardian_name="G-R",
        guardian_contact_phone="5550701",
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
    slot = check.assert_created(
        client.create_slot(
            factories.slot_payload(
                facility_id=clinic["id"],
                provider_id=audiologist["id"],
                starts_at=SLOT_START,
                ends_at=SLOT_END,
                slot_type="RESCREEN",
                total_capacity=2,
            ),
            headers=ADMIN,
        )
    )
    check.assert_ok(
        client.close_episode(
            episode["id"], {"closure_reason": "FAMILY_DECLINED"}, headers=ADMIN
        )
    )
    fixtures.set_clock(client, AFTER_THE_SLOT)
    return {"clinic": clinic, "audiologist": audiologist, "episode": episode, "slot": slot}


def test_the_declined_episode_answers_before_the_stale_slot_is_noticed(client):
    """State outranks the calendar: a 409 on the episode, not a 422 on the slot.

    PRD: "the episode must be in `PENDING_SCHEDULING`, else
    `ERR_EPISODE_NOT_SCHEDULABLE`; the slot's `slot_type` must be `RESCREEN` for an
    `INITIAL_SCREEN` or `RESCREEN` episode and `DIAGNOSTIC` for a `DIAGNOSTIC`
    episode, else `ERR_SLOT_TYPE_MISMATCH`; the slot's `starts_at` must be strictly
    after the logical clock, else `ERR_SLOT_IN_PAST`"

    Design: Difficulty/priority_pair_validation_conflict/closed_episode_and_past_slot_returns_episode_not_schedulable_not_slot_in_past
    """
    scenario = _declined_episode_and_a_slot_gone_by(client)

    response = client.create_appointment(
        factories.appointment_payload(
            episode_id=scenario["episode"]["id"], slot_id=scenario["slot"]["id"]
        ),
        headers=ADMIN,
    )
    body = check.assert_error_envelope(response, errors.ERR_EPISODE_NOT_SCHEDULABLE)
    assert response.status_code == 409
    assert body["error_id"] != errors.ERR_SLOT_IN_PAST

    stored_slot = fixtures.read_slot(client, scenario["slot"]["id"])
    check.assert_instant_equals(stored_slot["starts_at"], SLOT_START)
    check.assert_slot_capacity(stored_slot, 0, 2, "OPEN")
    check.assert_total_count(
        client.list_appointments(headers=ADMIN, slot_id=scenario["slot"]["id"]), 0
    )
    check.assert_episode_state(
        fixtures.read_episode(client, scenario["episode"]["id"]),
        "CLOSED_DECLINED",
        closure_reason="FAMILY_DECLINED",
        attempt_count=0,
    )


def test_each_of_the_two_broken_rules_still_answers_on_its_own(client):
    """Isolated, the stale slot gives 422 and the declined episode gives 409.

    PRD: "When a single request violates several rules at once, the response is
    decidable: checks are evaluated strictly in the order below, and the **first**
    failing check determines the error and status code."

    Design: Difficulty/priority_pair_validation_conflict/closed_episode_and_past_slot_returns_episode_not_schedulable_not_slot_in_past
    """
    scenario = _declined_episode_and_a_slot_gone_by(client)
    hospital = fixtures.create_facility(client, "BH2", "BIRTH_HOSPITAL", "R1")
    screener = fixtures.create_provider(client, hospital["id"], "SCREENER", "S2", "R1")
    second_infant = fixtures.create_infant(
        client,
        hospital["id"],
        birth_datetime=BIRTH,
        birth_setting="INPATIENT",
        gestational_age_weeks=39,
        guardian_name="G-S",
        guardian_contact_phone="5550702",
    )
    check.assert_created(
        client.create_encounter(
            factories.encounter_payload(
                infant_id=second_infant["id"],
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
    open_episode = fixtures.episodes_of(client, second_infant["id"])[0]
    check.assert_episode_state(open_episode, "PENDING_SCHEDULING")

    only_the_slot_is_wrong = client.create_appointment(
        factories.appointment_payload(
            episode_id=open_episode["id"], slot_id=scenario["slot"]["id"]
        ),
        headers=ADMIN,
    )
    check.assert_error_envelope(only_the_slot_is_wrong, errors.ERR_SLOT_IN_PAST)
    assert only_the_slot_is_wrong.status_code == 422

    future_slot = check.assert_created(
        client.create_slot(
            factories.slot_payload(
                facility_id=scenario["clinic"]["id"],
                provider_id=scenario["audiologist"]["id"],
                starts_at="2026-08-10T09:00:00Z",
                ends_at="2026-08-10T10:00:00Z",
                slot_type="RESCREEN",
                total_capacity=2,
            ),
            headers=ADMIN,
        )
    )
    only_the_episode_is_wrong = client.create_appointment(
        factories.appointment_payload(
            episode_id=scenario["episode"]["id"], slot_id=future_slot["id"]
        ),
        headers=ADMIN,
    )
    check.assert_error_envelope(
        only_the_episode_is_wrong, errors.ERR_EPISODE_NOT_SCHEDULABLE
    )
    assert only_the_episode_is_wrong.status_code == 409
    check.assert_slot_capacity(fixtures.read_slot(client, future_slot["id"]), 0, 2, "OPEN")


def _unscreened_infant_with_a_draft_evaluation(client, guardian_consent_status):
    """A never-screened infant on a diagnostic episode with results still to come."""
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    registry = fixtures.Registry(
        birth_hospital=hospital,
        clinic=clinic,
        ei_program=None,
        screener=fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1"),
        audiologist=fixtures.create_provider(client, clinic["id"], "AUDIOLOGIST", "A1", "R1"),
        second_audiologist=None,
        navigator=None,
        coordinator=None,
    )
    fixtures.set_clock(client, "2026-08-02T06:00:00Z")
    infant = fixtures.create_infant(
        client,
        hospital["id"],
        birth_datetime=BIRTH,
        birth_setting="INPATIENT",
        gestational_age_weeks=39,
        guardian_name="G-V",
        guardian_contact_phone="5550801",
        guardian_consent_status=guardian_consent_status,
    )
    assert infant["guardian_consent_status"] == guardian_consent_status
    assert infant["screening_status"] == "NOT_SCREENED"
    episode = fixtures.open_episode(
        client,
        infant["id"],
        "DIAGNOSTIC",
        expected_infant_version=fixtures.infant_version(client, infant["id"]),
    )
    evaluation = fixtures.draft_evaluation(
        client, registry, infant["id"], episode["id"], "2026-08-02T06:00:00Z"
    )
    assert evaluation["status"] == "DRAFT"
    return registry, infant, evaluation


def test_the_refused_consent_answers_before_the_missing_referral(client):
    """Safety outranks referential fitness: 422 on consent, not 409 on the track.

    PRD: "The infant's `guardian_consent_status` must not be `REFUSED`, else
    `ERR_GUARDIAN_CONSENT_REFUSED` — a family that has refused consent cannot have
    diagnostic results recorded against the baby. The infant's `screening_status` must
    be `REFERRED` or `DIAGNOSTIC_IN_PROGRESS`, else `ERR_INFANT_NOT_REFERRED`, since
    diagnostic work only makes sense on the diagnostic track."

    Design: Difficulty/priority_pair_validation_conflict/consent_refused_and_not_referred_returns_guardian_consent_refused_not_not_referred
    """
    registry, infant, evaluation = _unscreened_infant_with_a_draft_evaluation(
        client, "REFUSED"
    )

    response = client.submit_evaluation(
        evaluation["id"],
        factories.submit_payload(45, 50, "BILATERAL_LOSS"),
        headers=registry.a1,
    )
    body = check.assert_error_envelope(response, errors.ERR_GUARDIAN_CONSENT_REFUSED)
    assert response.status_code == 422
    assert body["error_id"] != errors.ERR_INFANT_NOT_REFERRED

    untouched = fixtures.read_evaluation(client, evaluation["id"])
    assert untouched["status"] == "DRAFT"
    check.assert_nulls(
        untouched, ["left_ear_threshold_db", "right_ear_threshold_db", "outcome"]
    )
    assert fixtures.read_infant(client, infant["id"])["screening_status"] == "NOT_SCREENED"


def test_with_consent_in_hand_the_missing_referral_becomes_the_answer(client):
    """The second violation is real, and it surfaces the moment consent is not at issue.

    PRD: "20. through 25. Referential fitness — provider credential standing
    (`ERR_PROVIDER_NOT_CREDENTIALED`), provider type fitness
    (`ERR_PROVIDER_TYPE_MISMATCH`), slot type fitness (`ERR_SLOT_TYPE_MISMATCH`),
    cross-reference linkage integrity (`ERR_LINKAGE_MISMATCH`), the diagnostic-track
    requirement on the infant (`ERR_INFANT_NOT_REFERRED`), and facility type fitness
    (`ERR_FACILITY_TYPE_MISMATCH`) — in that relative order."

    Design: Difficulty/priority_pair_validation_conflict/consent_refused_and_not_referred_returns_guardian_consent_refused_not_not_referred
    """
    registry, infant, evaluation = _unscreened_infant_with_a_draft_evaluation(
        client, "GRANTED"
    )

    response = client.submit_evaluation(
        evaluation["id"],
        factories.submit_payload(45, 50, "BILATERAL_LOSS"),
        headers=registry.a1,
    )
    body = check.assert_error_envelope(response, errors.ERR_INFANT_NOT_REFERRED)
    assert response.status_code == 409
    assert body["error_id"] != errors.ERR_GUARDIAN_CONSENT_REFUSED

    still_draft = fixtures.read_evaluation(client, evaluation["id"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft["timeliness_status"] == "PENDING"
    check.assert_nulls(still_draft, ["outcome", "attested_by_provider_id", "finalized_at"])
