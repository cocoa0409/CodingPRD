"""Interdisciplinary and family conferences: calendar, quorum and attestation."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId, assert_conference, assert_same_instant
from test_helpers import factories as f
from test_helpers.fixtures import (
    NURSE,
    PHYSICIAN,
    SOCIAL_WORKER,
    book_conference,
    enroll_patient,
    hold_conference,
    set_clock,
)


# ---------------------------------------------------------------------------
# The patient calendar buffer
# ---------------------------------------------------------------------------
def test_a_gap_of_exactly_fifteen_minutes_is_accepted_on_the_patient_calendar(api):
    """PRD 3.7: "Booking respects the patient's calendar: a new conference must
    leave a gap of at least 15 minutes from every other conference of the same
    patient sitting in `SCHEDULED`, `HELD` or `ATTESTED`. A gap of exactly 15
    minutes is fine; 14 minutes is refused with `ERR_SCHEDULE_CONFLICT`."
    PRD 3.7: "The conference is created in `status` `SCHEDULED` with `quorum_met`
    false, `attestation_complete` false and `consent_recorded` false."

    Design: Difficulty/resource_temporal_overlap/conference_buffer_requires_fifteen_minute_gap_on_patient_calendar
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Quinn Baptiste")

    book_conference(
        patient["id"],
        conference_type="IDT",
        modality="TELEHEALTH",
        scheduled_start="2026-06-15T09:00:00Z",
        scheduled_end="2026-06-15T10:00:00Z",
    )

    response = api.create_conference(
        f.conference_payload(
            patient["id"],
            conference_type="FAMILY",
            modality="TELEHEALTH",
            scheduled_start="2026-06-15T10:15:00Z",
            scheduled_end="2026-06-15T11:00:00Z",
        ),
        SOCIAL_WORKER,
    )
    second = validate_success(response, 201)
    assert_conference(second)

    assert second["status"] == "SCHEDULED"
    assert second["quorum_met"] is False
    assert second["attestation_complete"] is False
    assert second["consent_recorded"] is False
    assert_same_instant(
        second["scheduled_start"],
        "2026-06-15T10:15:00Z",
        "CareConference.scheduled_start",
    )


def test_a_gap_of_fourteen_minutes_is_a_schedule_conflict(api):
    """PRD 2.5: "(b) For conferences: a new conference on the same `patient_id`
    must leave a gap of at least 15 minutes from every other conference of that
    patient whose `status` is `SCHEDULED`, `HELD` or `ATTESTED`; formally the new
    booking is rejected when its `scheduled_start` is earlier than the existing
    conference's `scheduled_end` plus 15 minutes **and** the existing conference's
    `scheduled_start` is earlier than the new `scheduled_end` plus 15 minutes, so
    a gap of exactly 15 minutes is accepted and a gap of 14 minutes is rejected."

    Design: Difficulty/resource_temporal_overlap/conference_buffer_requires_fifteen_minute_gap_on_patient_calendar
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Quinn Baptiste")

    book_conference(
        patient["id"],
        conference_type="IDT",
        modality="TELEHEALTH",
        scheduled_start="2026-06-15T09:00:00Z",
        scheduled_end="2026-06-15T10:00:00Z",
    )
    book_conference(
        patient["id"],
        conference_type="FAMILY",
        modality="TELEHEALTH",
        scheduled_start="2026-06-15T10:15:00Z",
        scheduled_end="2026-06-15T11:00:00Z",
    )

    rejected = api.create_conference(
        f.conference_payload(
            patient["id"],
            conference_type="FAMILY",
            modality="IN_PERSON",
            scheduled_start="2026-06-15T11:14:00Z",
            scheduled_end="2026-06-15T12:00:00Z",
        ),
        SOCIAL_WORKER,
    )
    validate_error(rejected, ApiErrorId.ERR_SCHEDULE_CONFLICT.value, 409)

    rows, meta = validate_paginated(
        api.list_conferences(SOCIAL_WORKER, params={"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 2, (
        f"the rejected booking must not have been persisted, total_count={meta['total_count']}"
    )
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# Quorum
# ---------------------------------------------------------------------------
def test_a_short_roster_fails_quorum_and_a_full_roster_re_enters_the_main_path(api):
    """PRD 3.7: "An `IDT` conference requires **full quorum**:
    `disciplines_present` must cover all four of `PHYSICIAN`, `NURSE`,
    `SOCIAL_WORKER` and `CHAPLAIN`. With quorum, the conference moves `SCHEDULED →
    HELD`, `held_at` is stamped from the logical clock, `attestation_due_at` is
    set to exactly 72 hours after `held_at`, `documented_minutes` is stored and
    `quorum_met` becomes true. Short of quorum, the conference moves `SCHEDULED →
    QUORUM_FAILED` instead: `quorum_met` stays false, `held_at` stays null,
    `documented_minutes` is still stored for the record, and the meeting does not
    count toward interdisciplinary cadence compliance."
    PRD 3.7: "A failed conference is not dead — the same hold operation retried
    with a complete roster moves it `QUORUM_FAILED → HELD`, stamping `held_at` and
    setting `quorum_met` true; retried while still short of a required discipline
    it self-loops `QUORUM_FAILED → QUORUM_FAILED`, replacing `disciplines_present`
    with the new roster and leaving `quorum_met` false."

    Design: Corner/state_machines/conference_quorum_failure_then_retry_with_full_roster_reaches_held
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Jara Bello")
    conference = book_conference(
        patient["id"],
        conference_type="IDT",
        modality="TELEHEALTH",
        scheduled_start="2026-06-02T09:00:00Z",
        scheduled_end="2026-06-02T10:00:00Z",
    )
    set_clock("2026-06-02T09:00:00Z")

    failed = hold_conference(
        conference["id"],
        documented_minutes=30,
        disciplines_present=["PHYSICIAN", "NURSE", "SOCIAL_WORKER"],
    )
    assert failed["status"] == "QUORUM_FAILED"
    assert failed["quorum_met"] is False
    assert failed["held_at"] is None

    retried = hold_conference(
        conference["id"],
        documented_minutes=35,
        disciplines_present=["PHYSICIAN", "CHAPLAIN"],
    )
    assert retried["status"] == "QUORUM_FAILED"
    assert len(retried["disciplines_present"]) == 2, (
        "the self-loop replaces disciplines_present with the new roster"
    )

    held = hold_conference(
        conference["id"],
        documented_minutes=46,
        disciplines_present=["PHYSICIAN", "NURSE", "SOCIAL_WORKER", "CHAPLAIN"],
    )
    assert held["status"] == "HELD"
    assert held["quorum_met"] is True
    assert held["documented_minutes"] == 46
    assert_same_instant(held["held_at"], "2026-06-02T09:00:00Z", "CareConference.held_at")
    assert_same_instant(
        held["attestation_due_at"],
        "2026-06-05T09:00:00Z",
        "CareConference.attestation_due_at",
    )


def test_attesting_a_quorum_failed_conference_names_the_quorum_rule(api):
    """PRD 3.7: "It is accepted only against a conference whose quorum outcome
    succeeded: a conference sitting in `QUORUM_FAILED` is admitted past the
    generic state check precisely so it can be refused here with
    `ERR_QUORUM_NOT_MET`."
    PRD 2.5: "**Quorum recorded.** A note attestation is only accepted against a
    conference whose quorum outcome succeeded; a conference sitting in
    `QUORUM_FAILED` is rejected here rather than at rung 7, with
    `ERR_QUORUM_NOT_MET` (422)."

    Design: Corner/validations/attestation_on_a_quorum_failed_conference_returns_quorum_not_met
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Jonas Weir")
    conference = book_conference(
        patient["id"],
        conference_type="IDT",
        modality="TELEHEALTH",
        scheduled_start="2026-06-02T09:00:00Z",
        scheduled_end="2026-06-02T10:00:00Z",
    )
    set_clock("2026-06-02T09:00:00Z")
    hold_conference(
        conference["id"], documented_minutes=20, disciplines_present=["PHYSICIAN", "NURSE"]
    )

    rejected = api.attest_conference(
        conference["id"],
        {"discipline": "PHYSICIAN", "note_text": "attempted attestation"},
        PHYSICIAN,
    )
    validate_error(rejected, ApiErrorId.ERR_QUORUM_NOT_MET.value, 422)

    unchanged = validate_success(api.get_conference(conference["id"], SOCIAL_WORKER))
    assert unchanged["status"] == "QUORUM_FAILED"
    assert unchanged["quorum_met"] is False
    assert len(unchanged["attested_disciplines"]) == 0


# ---------------------------------------------------------------------------
# The attestation window
# ---------------------------------------------------------------------------
def test_attestation_is_accepted_at_the_deadline_and_refused_one_second_later(api):
    """PRD 3.7: "It must also arrive inside the window — the current logical clock
    at or before `attestation_due_at`, inclusive at exactly that instant, and
    refused with `ERR_ATTESTATION_WINDOW_EXPIRED` afterwards."
    PRD 3.7: "Each accepted attestation appends the discipline to
    `attested_disciplines` and recomputes `attestation_complete`, which becomes
    true when `attested_disciplines` covers every member of `disciplines_present`."

    Design: Corner/validations/conference_attestation_after_the_window_returns_expired
    """
    patient, _ = enroll_patient(clock="2026-06-01T00:00:00Z", full_name="Iris Tovar")
    conference = book_conference(
        patient["id"],
        conference_type="IDT",
        modality="TELEHEALTH",
        scheduled_start="2026-06-02T09:00:00Z",
        scheduled_end="2026-06-02T10:00:00Z",
    )
    set_clock("2026-06-02T09:00:00Z")
    held = hold_conference(
        conference["id"],
        documented_minutes=46,
        disciplines_present=["PHYSICIAN", "NURSE", "SOCIAL_WORKER", "CHAPLAIN"],
    )
    assert_same_instant(
        held["attestation_due_at"],
        "2026-06-05T09:00:00Z",
        "CareConference.attestation_due_at",
    )

    set_clock("2026-06-05T09:00:00Z")
    on_time = validate_success(
        api.attest_conference(
            conference["id"],
            {"discipline": "PHYSICIAN", "note_text": "at the edge of the window"},
            PHYSICIAN,
        )
    )
    assert len(on_time["attested_disciplines"]) == 1

    set_clock("2026-06-05T09:00:01Z")
    late = api.attest_conference(
        conference["id"], {"discipline": "NURSE", "note_text": "one second late"}, NURSE
    )
    validate_error(late, ApiErrorId.ERR_ATTESTATION_WINDOW_EXPIRED.value, 422)

    final = validate_success(api.get_conference(conference["id"], SOCIAL_WORKER))
    assert final["attestation_complete"] is False
    assert final["status"] == "HELD"
    assert len(final["attested_disciplines"]) == 1
