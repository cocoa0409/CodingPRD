"""Hospice election: two certifications, benefit periods and the revoke cycle."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    assert_hospice_election,
    assert_same_instant,
    make_headers,
)
from test_helpers import factories as f
from test_helpers.fixtures import (
    CHAPLAIN,
    HOSPICE_DIRECTOR,
    PHYSICIAN,
    attest_conference,
    book_conference,
    certified_hospice_election,
    elected_hospice_patient,
    enroll_patient,
    hold_conference,
    open_benefit_period,
    open_hospice_election,
    read_election,
    read_patient,
    set_clock,
)


def _cadence_scenario():
    """An IDT conference held with a full roster but only three disciplines attested,
    plus a certified election waiting for its first benefit period."""
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Omar Delgado")
    conference = book_conference(
        patient["id"],
        conference_type="IDT",
        modality="TELEHEALTH",
        scheduled_start="2026-06-02T09:00:00Z",
        scheduled_end="2026-06-02T10:00:00Z",
    )
    set_clock("2026-06-02T09:00:00Z")
    hold_conference(
        conference["id"],
        documented_minutes=50,
        disciplines_present=["PHYSICIAN", "NURSE", "SOCIAL_WORKER", "CHAPLAIN"],
    )
    attest_conference(conference["id"], "PHYSICIAN", "prognosis reviewed")
    attest_conference(conference["id"], "NURSE", "symptoms reviewed")
    attest_conference(conference["id"], "SOCIAL_WORKER", "supports reviewed")
    election = certified_hospice_election(patient["id"], diagnosis="C50.911")
    return patient, conference, election


# ---------------------------------------------------------------------------
# Cadence gate on benefit periods
# ---------------------------------------------------------------------------
def test_a_held_but_unattested_idt_meeting_does_not_keep_the_benefit_alive(api):
    """PRD 3.10: "Then interdisciplinary cadence: the patient must have an
    attested `IDT` conference held within 15 days of the current logical clock, or
    the request is refused with `ERR_IDT_CADENCE_LAPSED` — an interdisciplinary
    team that has stopped meeting cannot keep a hospice benefit alive."
    PRD 3.7: "Conferences sitting in `SCHEDULED`, `HELD`, `QUORUM_FAILED` or
    `CONSENT_INVALIDATED` are excluded from that maximum, so an interdisciplinary
    meeting that was held but never attested does **not** restore cadence."

    Design: Difficulty/cross_entity_state_dependency/hospice_benefit_period_requires_attested_idt_conference
    """
    _, conference, election = _cadence_scenario()
    assert election["status"] == "CERTIFIED"
    assert election["certification_count"] == 2

    rejected = api.open_hospice_period(
        election["id"],
        {
            "expected_election_version": election["version"],
            "period_start": "2026-06-02T00:00:00Z",
        },
        HOSPICE_DIRECTOR,
    )
    validate_error(rejected, ApiErrorId.ERR_IDT_CADENCE_LAPSED.value, 422)

    still_held = validate_success(api.get_conference(conference["id"], PHYSICIAN))
    assert still_held["status"] == "HELD"
    assert still_held["attestation_complete"] is False
    assert read_election(election["id"])["status"] == "CERTIFIED"


def test_the_final_discipline_attestation_flips_the_period_call_to_success(api):
    """PRD 3.7: "The attestation that completes the set moves the conference `HELD
    → ATTESTED`, and from that moment an interdisciplinary conference counts as
    the patient's most recent attested `IDT` meeting for cadence purposes."
    PRD 3.10: "Opening period 1 moves the election `CERTIFIED → ELECTED` and
    simultaneously moves the patient's `program_status` `ACTIVE →
    HOSPICE_ELECTED`, incrementing the patient's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/hospice_benefit_period_requires_attested_idt_conference
    """
    patient, conference, election = _cadence_scenario()

    validate_error(
        api.open_hospice_period(
            election["id"],
            {
                "expected_election_version": election["version"],
                "period_start": "2026-06-02T00:00:00Z",
            },
            HOSPICE_DIRECTOR,
        ),
        ApiErrorId.ERR_IDT_CADENCE_LAPSED.value,
        422,
    )

    completed = validate_success(
        api.attest_conference(
            conference["id"],
            {"discipline": "CHAPLAIN", "note_text": "spiritual care reviewed"},
            CHAPLAIN,
        )
    )
    assert completed["status"] == "ATTESTED"
    assert completed["attestation_complete"] is True

    elected = validate_success(
        api.open_hospice_period(
            election["id"],
            {
                "expected_election_version": election["version"],
                "period_start": "2026-06-02T00:00:00Z",
            },
            HOSPICE_DIRECTOR,
        )
    )
    assert_hospice_election(elected)
    assert elected["status"] == "ELECTED"
    assert elected["current_period_number"] == 1
    assert_same_instant(
        elected["current_period_end"],
        "2026-08-31T00:00:00Z",
        "HospiceElection.current_period_end",
    )
    assert elected["cumulative_benefit_days"] == 90
    assert read_patient(patient["id"])["program_status"] == "HOSPICE_ELECTED"


# ---------------------------------------------------------------------------
# The revoke and re-elect cycle
# ---------------------------------------------------------------------------
def test_re_election_continues_the_benefit_period_sequence(api):
    """PRD 3.10: "A revoked election can be resurrected: a certification against
    it moves it `REVOKED → PENDING_CERT`, resets `certification_count` to 1,
    re-stamps `attending_certifier_user_id` from the acting user and clears
    `hospice_director_certifier_user_id` back to null. The patient may then be
    certified again and re-elect, walking `PENDING_CERT → CERTIFIED → ELECTED` a
    second time, with `current_period_number` continuing the sequence where it
    left off rather than restarting."
    PRD 3.10: "The new period number is one more than `current_period_number`. The
    first period runs 90 days, the second period runs 90 days, and every period
    from the third onward runs 60 days."

    Design: Difficulty/non_linear_state_machine/hospice_election_revoke_then_reelect_completes_the_cycle
    """
    patient, election = elected_hospice_patient(
        clock="2026-06-01T00:00:00Z",
        conference_held_at="2026-06-02T09:00:00Z",
        period_start="2026-06-02T00:00:00Z",
        full_name="Faye Okonkwo",
    )
    assert election["status"] == "ELECTED"
    assert election["current_period_number"] == 1

    revoked = validate_success(
        api.revoke_hospice_election(
            election["id"],
            {"revocation_reason": "patient elected to resume disease-directed therapy"},
            HOSPICE_DIRECTOR,
        )
    )
    assert revoked["status"] == "REVOKED"
    assert revoked["revocation_count"] == 1

    resurrected = validate_success(
        api.certify_hospice_election(
            election["id"], f.hospice_certification_payload("C34.90"), PHYSICIAN
        )
    )
    assert resurrected["status"] == "PENDING_CERT"
    assert resurrected["certification_count"] == 1

    recertified = validate_success(
        api.certify_hospice_election(
            election["id"], f.hospice_certification_payload("C34.90"), HOSPICE_DIRECTOR
        )
    )
    assert recertified["status"] == "CERTIFIED"
    assert recertified["certification_count"] == 2

    second_period = open_benefit_period(
        election["id"], "2026-09-01T00:00:00Z", recertified["version"]
    )

    assert second_period["status"] == "ELECTED"
    assert second_period["current_period_number"] == 2, (
        "the counter continues where it left off rather than restarting at 1"
    )
    assert_same_instant(
        second_period["current_period_start"],
        "2026-09-01T00:00:00Z",
        "HospiceElection.current_period_start",
    )
    assert_same_instant(
        second_period["current_period_end"],
        "2026-11-30T00:00:00Z",
        "HospiceElection.current_period_end",
    )
    assert second_period["cumulative_benefit_days"] == 180


def test_revocation_returns_the_patient_and_re_election_takes_them_back(api):
    """PRD 3.10: "A `HospiceMedicalDirector` supplies a `revocation_reason`; the
    election moves `ELECTED → REVOKED`, `revocation_count` increments by 1,
    `current_period_number` is retained for the audit trail, and the patient's
    `program_status` returns `HOSPICE_ELECTED → ACTIVE` with the patient's
    `version` incremented by 1."
    PRD 3.10: "Opening period 1 moves the election `CERTIFIED → ELECTED` and
    simultaneously moves the patient's `program_status` `ACTIVE →
    HOSPICE_ELECTED`, incrementing the patient's `version` by 1."

    Design: Difficulty/non_linear_state_machine/hospice_election_revoke_then_reelect_completes_the_cycle
    """
    patient, election = elected_hospice_patient(
        clock="2026-06-01T00:00:00Z",
        conference_held_at="2026-06-02T09:00:00Z",
        period_start="2026-06-02T00:00:00Z",
        full_name="Faye Okonkwo",
    )
    assert read_patient(patient["id"])["program_status"] == "HOSPICE_ELECTED"

    revoked = validate_success(
        api.revoke_hospice_election(
            election["id"],
            {"revocation_reason": "patient elected to resume disease-directed therapy"},
            HOSPICE_DIRECTOR,
        )
    )
    assert revoked["current_period_number"] == 1, (
        "current_period_number is retained for the audit trail across a revocation"
    )
    assert read_patient(patient["id"])["program_status"] == "ACTIVE"

    validate_success(
        api.certify_hospice_election(
            election["id"], f.hospice_certification_payload("C34.90"), PHYSICIAN
        )
    )
    recertified = validate_success(
        api.certify_hospice_election(
            election["id"], f.hospice_certification_payload("C34.90"), HOSPICE_DIRECTOR
        )
    )
    open_benefit_period(election["id"], "2026-09-01T00:00:00Z", recertified["version"])

    assert read_patient(patient["id"])["program_status"] == "HOSPICE_ELECTED"


# ---------------------------------------------------------------------------
# Certifier segregation
# ---------------------------------------------------------------------------
def test_the_second_certification_must_come_from_a_different_user(api):
    """PRD 3.10: "The first certification is a self-loop on `PENDING_CERT`: it
    stamps `attending_certifier_user_id` from `X-User-ID` and sets
    `certification_count` to 1. The second certification moves the election
    `PENDING_CERT → CERTIFIED`, stamps `hospice_director_certifier_user_id` and
    sets `certification_count` to 2, the number of certifiers the benefit
    requires. It must come from a different user: a second certification whose
    `X-User-ID` equals `attending_certifier_user_id` is refused with
    `ERR_DUPLICATE_CERTIFIER`."
    PRD 3.10: "It opens in `status` `PENDING_CERT` with `certification_count` 0,
    `current_period_number` 0, `cumulative_benefit_days` 0, `revocation_count` 0
    and `version` 1."

    Design: Corner/validations/second_hospice_certification_by_the_same_user_returns_duplicate_certifier
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Fatima Sow")
    election = open_hospice_election(patient["id"])
    assert election["status"] == "PENDING_CERT"
    assert election["certification_count"] == 0
    assert election["current_period_number"] == 0
    assert election["cumulative_benefit_days"] == 0
    assert election["revocation_count"] == 0
    assert election["version"] == 1

    first = validate_success(
        api.certify_hospice_election(
            election["id"], f.hospice_certification_payload("I50.9"), PHYSICIAN
        )
    )
    assert first["certification_count"] == 1
    assert first["attending_certifier_user_id"] == "u_physician_1"

    duplicate = api.certify_hospice_election(
        election["id"],
        f.hospice_certification_payload("I50.9"),
        make_headers("u_physician_1", "HospiceMedicalDirector"),
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_CERTIFIER.value, 422)

    second = validate_success(
        api.certify_hospice_election(
            election["id"], f.hospice_certification_payload("I50.9"), HOSPICE_DIRECTOR
        )
    )
    assert second["status"] == "CERTIFIED"
    assert second["certification_count"] == 2
    assert second["attending_certifier_user_id"] == "u_physician_1"
    assert second["hospice_director_certifier_user_id"] == "u_hospice_md_1"


# ---------------------------------------------------------------------------
# Period lengths and the face-to-face window
# ---------------------------------------------------------------------------
def test_the_third_period_runs_sixty_days_behind_a_windowed_face_to_face(api):
    """PRD 3.10: "Then, for the third and every later period, the face-to-face
    encounter: when the period number about to be opened is 3 or higher,
    `face_to_face_at` must be supplied and must fall at or after the instant 30
    days before `period_start` and strictly before `period_start` itself. An
    encounter exactly 30 days before `period_start` is valid; an encounter exactly
    at `period_start` is not. Violations are refused with
    `ERR_FACE_TO_FACE_WINDOW`."
    PRD 3.10: "The new period number is one more than `current_period_number`. The
    first period runs 90 days, the second period runs 90 days, and every period
    from the third onward runs 60 days."

    Design: Corner/calculations/hospice_third_benefit_period_is_sixty_days_and_needs_a_windowed_face_to_face
    """
    _, election = elected_hospice_patient(
        clock="2026-06-01T00:00:00Z",
        conference_held_at="2026-06-02T09:00:00Z",
        period_start="2026-06-02T00:00:00Z",
        full_name="Yuki Tanaka",
    )
    assert_same_instant(
        election["current_period_end"],
        "2026-08-31T00:00:00Z",
        "HospiceElection.current_period_end after period 1",
    )

    second = open_benefit_period(
        election["id"], "2026-08-31T00:00:00Z", election["version"]
    )
    assert second["current_period_number"] == 2
    assert_same_instant(
        second["current_period_end"],
        "2026-11-29T00:00:00Z",
        "HospiceElection.current_period_end after period 2",
    )
    assert second["cumulative_benefit_days"] == 180

    for face_to_face in ("2026-10-29T00:00:00Z", "2026-11-29T00:00:00Z"):
        rejected = api.open_hospice_period(
            election["id"],
            {
                "expected_election_version": second["version"],
                "period_start": "2026-11-29T00:00:00Z",
                "face_to_face_at": face_to_face,
            },
            HOSPICE_DIRECTOR,
        )
        validate_error(rejected, ApiErrorId.ERR_FACE_TO_FACE_WINDOW.value, 422)

    third = validate_success(
        api.open_hospice_period(
            election["id"],
            {
                "expected_election_version": second["version"],
                "period_start": "2026-11-29T00:00:00Z",
                "face_to_face_at": "2026-10-30T00:00:00Z",
            },
            HOSPICE_DIRECTOR,
        )
    )

    assert third["current_period_number"] == 3
    assert_same_instant(
        third["current_period_end"],
        "2027-01-28T00:00:00Z",
        "HospiceElection.current_period_end after period 3",
    )
    assert third["cumulative_benefit_days"] == 240
    assert_same_instant(
        third["face_to_face_at"], "2026-10-30T00:00:00Z", "HospiceElection.face_to_face_at"
    )
