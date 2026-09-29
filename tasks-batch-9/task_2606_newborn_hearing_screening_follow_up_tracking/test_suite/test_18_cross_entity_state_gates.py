"""Writes whose legality is decided by a state field on a different row."""

import pytest

from test_helpers import api_errors as errors
from test_helpers import assertions as check
from test_helpers import factories, fixtures
from test_helpers.test_users import (
    make_facility_screener_headers,
    make_program_admin_headers,
)

ADMIN = make_program_admin_headers()

BIRTH = "2026-08-02T00:00:00Z"
SCREEN_AT = "2026-08-02T05:00:00Z"


def _suspended_hospital_with_an_unscreened_baby(client):
    """A hospital sanctioned to 18 points, and a baby waiting for its birth screen."""
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    screener = fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")
    fixtures.set_clock(client, "2026-08-02T06:00:00Z")
    infant = fixtures.create_infant(
        client,
        hospital["id"],
        birth_datetime=BIRTH,
        birth_setting="INPATIENT",
        gestational_age_weeks=39,
        guardian_name="G-U",
        guardian_contact_phone="5551101",
    )
    fixtures.adjust_penalty(
        client, hospital["id"], 18, reason="suspension for chronic non-reporting"
    )
    check.assert_facility_ledger(
        fixtures.read_facility(client, hospital["id"]),
        penalty_points_balance=18,
        reporting_compliance_status="SUSPENDED",
        manual_adjustment_points_total=18,
    )
    payload = factories.encounter_payload(
        infant_id=infant["id"],
        facility_id=hospital["id"],
        performed_by_provider_id=screener["id"],
        performed_at=SCREEN_AT,
        encounter_type="BIRTH_ADMISSION",
        method="AABR",
        left_ear_result="REFER",
        right_ear_result="PASS",
    )
    return hospital, infant, payload, make_facility_screener_headers(screener["id"])


def test_a_suspended_hospital_may_register_a_baby_but_not_screen_one(client):
    """The posture of the facility row decides whether the encounter may exist.

    PRD: "A suspended facility cannot screen. Recording any encounter at a facility
    whose `reporting_compliance_status` is `SUSPENDED` is rejected with
    `ERR_FACILITY_SUSPENDED`, which is the sharp end of the compliance regime in
    §3.9."

    Design: Difficulty/cross_entity_state_dependency/suspended_birth_facility_blocks_screening_encounter_probation_allows_it
    """
    _, infant, payload, screener_headers = _suspended_hospital_with_an_unscreened_baby(client)

    refused = client.create_encounter(payload, headers=screener_headers)
    check.assert_error_envelope(refused, errors.ERR_FACILITY_SUSPENDED)
    assert refused.status_code == 409

    untouched = fixtures.read_infant(client, infant["id"])
    assert untouched["screening_status"] == "NOT_SCREENED"
    check.assert_total_count(
        client.list_encounters(headers=ADMIN, infant_id=infant["id"]), 0
    )
    assert fixtures.episodes_of(client, infant["id"]) == []


def test_remitting_one_point_lets_the_identical_screen_through(client):
    """Eighteen blocks and seventeen does not: the same request, the other polarity.

    PRD: "`reporting_compliance_status` is `COMPLIANT` while `penalty_points_balance`
    is 4 or less, `WATCH` from 5 through 9, `PROBATION` from 10 through 17, and
    `SUSPENDED` at 18 or more."

    Design: Difficulty/cross_entity_state_dependency/suspended_birth_facility_blocks_screening_encounter_probation_allows_it
    """
    hospital, infant, payload, screener_headers = _suspended_hospital_with_an_unscreened_baby(
        client
    )
    check.assert_error_envelope(
        client.create_encounter(payload, headers=screener_headers),
        errors.ERR_FACILITY_SUSPENDED,
    )

    fixtures.adjust_penalty(
        client, hospital["id"], -1, reason="one point remitted on appeal"
    )
    check.assert_facility_ledger(
        fixtures.read_facility(client, hospital["id"]),
        penalty_points_balance=17,
        reporting_compliance_status="PROBATION",
        manual_adjustment_points_total=17,
    )

    encounter = check.assert_created(client.create_encounter(payload, headers=screener_headers))
    assert encounter["overall_result"] == "REFER"
    assert encounter["before_discharge"] is True
    assert encounter["age_days_at_encounter"] == 0

    assert fixtures.read_infant(client, infant["id"])["screening_status"] == "REFERRED"
    episodes = fixtures.episodes_of(client, infant["id"])
    assert len(episodes) == 1
    assert episodes[0]["episode_type"] == "RESCREEN"
    check.assert_episode_state(episodes[0], "PENDING_SCHEDULING", benchmark_days=30)


def _draft_evaluation_on_an_unscreened_baby(client):
    """A valid DRAFT evaluation whose infant has never been screened at all."""
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
        guardian_name="G-W2",
        guardian_contact_phone="5551201",
        guardian_consent_status="GRANTED",
    )
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
    return registry, infant, episode, evaluation


def test_the_submit_is_refused_on_the_infants_status_not_its_own(client):
    """The evaluation is a perfectly good DRAFT; the infant is what is wrong.

    PRD: "The infant's `screening_status` must be `REFERRED` or
    `DIAGNOSTIC_IN_PROGRESS`, else `ERR_INFANT_NOT_REFERRED`, since diagnostic work
    only makes sense on the diagnostic track."

    Design: Difficulty/cross_entity_state_dependency/infant_screening_status_gates_diagnostic_submit_both_polarities
    """
    registry, infant, _, evaluation = _draft_evaluation_on_an_unscreened_baby(client)

    refused = client.submit_evaluation(
        evaluation["id"],
        factories.submit_payload(40, 15, "UNILATERAL_LOSS"),
        headers=registry.a1,
    )
    check.assert_error_envelope(refused, errors.ERR_INFANT_NOT_REFERRED)
    assert refused.status_code == 409

    still_draft = fixtures.read_evaluation(client, evaluation["id"])
    assert still_draft["status"] == "DRAFT"
    check.assert_nulls(
        still_draft, ["outcome", "left_ear_threshold_db", "right_ear_threshold_db"]
    )
    assert fixtures.read_infant(client, infant["id"])["screening_status"] == "NOT_SCREENED"


def test_a_refer_screen_on_the_infant_unblocks_the_untouched_evaluation(client):
    """Nothing about the evaluation changes, and the identical body now succeeds.

    PRD: "On success the thresholds and outcome are stored and the evaluation advances
    `DRAFT → PENDING_ATTESTATION`."

    Design: Difficulty/cross_entity_state_dependency/infant_screening_status_gates_diagnostic_submit_both_polarities
    """
    registry, infant, episode, evaluation = _draft_evaluation_on_an_unscreened_baby(client)
    body = factories.submit_payload(40, 15, "UNILATERAL_LOSS")
    check.assert_error_envelope(
        client.submit_evaluation(evaluation["id"], body, headers=registry.a1),
        errors.ERR_INFANT_NOT_REFERRED,
    )

    fixtures.record_encounter(
        client,
        registry,
        infant["id"],
        SCREEN_AT,
        encounter_type="BIRTH_ADMISSION",
        method="AABR",
        left_ear_result="REFER",
        right_ear_result="PASS",
    )
    referred = fixtures.read_infant(client, infant["id"])
    assert referred["screening_status"] == "REFERRED"
    # The diagnostic episode is already active, so the refer cascade opens no second one.
    episodes = fixtures.episodes_of(client, infant["id"])
    assert len(episodes) == 1
    assert episodes[0]["id"] == episode["id"]
    assert episodes[0]["episode_type"] == "DIAGNOSTIC"

    submitted = check.assert_ok(
        client.submit_evaluation(evaluation["id"], body, headers=registry.a1)
    )
    assert submitted["status"] == "PENDING_ATTESTATION"
    assert submitted["outcome"] == "UNILATERAL_LOSS"
    assert submitted["left_ear_threshold_db"] == 40
    assert submitted["right_ear_threshold_db"] == 15
    assert fixtures.read_infant(client, infant["id"])["screening_status"] == "REFERRED"
