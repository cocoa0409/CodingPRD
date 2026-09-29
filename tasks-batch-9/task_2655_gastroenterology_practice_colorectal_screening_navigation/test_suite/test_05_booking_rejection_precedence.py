"""Validation precedence on the busiest write in the system: two rules fail at once and
only the higher-precedence rejection reaches the client."""
from test_helpers import (
    REFERRAL_COORDINATOR,
    api_client,
    apply_block_action,
    book_slot,
    create_block,
    create_procedure_booking_payload,
    move_clock,
    open_episode,
    read_block,
    read_episode,
    register_endoscopist,
    register_patient,
    register_plan,
    validate_error,
)


def _attempt_booking(session_id, episode_id, endoscopist_id, expected_session_version,
                     slot_start_utc, duration_minutes=45):
    return api_client.create_procedure_booking(
        session_id,
        create_procedure_booking_payload(episode_id, endoscopist_id,
                                         expected_session_version, slot_start_utc,
                                         duration_minutes),
        REFERRAL_COORDINATOR,
    )


def _suspended_block_holding_its_only_permitted_booking():
    """A one-procedure block that is already full and has since been suspended."""
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endoscopist = register_endoscopist()
    patient_a = register_patient(plan["id"], mrn="MRN-0001", birth_date="1975-04-10")
    patient_b = register_patient(plan["id"], mrn="MRN-0002", birth_date="1972-06-22")
    episode_a = open_episode(patient_a["id"], "SCREENING_AVERAGE_RISK")
    episode_b = open_episode(patient_b["id"], "SCREENING_AVERAGE_RISK")
    block = create_block(endoscopist["id"], max_procedures=1)
    apply_block_action(block["id"], "PUBLISH")
    book_slot(block["id"], episode_a["id"], endoscopist["id"],
              slot_start_utc="2026-09-15T13:00:00Z", duration_minutes=45)
    suspended = apply_block_action(block["id"], "SUSPEND", reason="Anesthesia staffing gap")
    return {
        "block_id": block["id"],
        "endoscopist_id": endoscopist["id"],
        "episode_b_id": episode_b["id"],
        "suspended": suspended,
    }


def test_suspended_posture_is_reported_ahead_of_the_headcount_ceiling():
    """The block itself must be in `PUBLISHED` or `COVERAGE_CONFIRMED`; a `DRAFT`,
    `SUSPENDED`, or `CLOSED` block accepts no bookings and rejects the request with
    `ERR_SESSION_NOT_ACCEPTING_BOOKINGS`.

    Third, the headcount ceiling: when the number of bookings on the block whose `status`
    is anything other than `CANCELLED` already equals `max_procedures`, the request is
    rejected with `ERR_SESSION_CAPACITY_EXCEEDED` (HTTP 409).

    Design: Difficulty/priority_pair_validation_conflict/suspended_session_at_capacity_returns_session_not_accepting
    """
    scenario = _suspended_block_holding_its_only_permitted_booking()
    assert scenario["suspended"]["status"] == "SUSPENDED"

    response = _attempt_booking(scenario["block_id"], scenario["episode_b_id"],
                                scenario["endoscopist_id"],
                                scenario["suspended"]["version"],
                                "2026-09-15T15:00:00Z")
    validate_error(response, "ERR_SESSION_NOT_ACCEPTING_BOOKINGS")


def test_resume_reopens_the_block_and_the_headcount_ceiling_then_bites():
    """`RESUME` is deliberately not a memory operation. From `SUSPENDED` it clears
    `suspension_reason` and returns the block to whichever posture its *current* coverage
    implies, not the posture it held before suspension: `SUSPENDED → COVERAGE_CONFIRMED`
    when the block still has an `ACTIVE` coverage row that fully spans its window, and
    `SUSPENDED → PUBLISHED` when it does not.

    Design: Difficulty/priority_pair_validation_conflict/suspended_session_at_capacity_returns_session_not_accepting
    """
    scenario = _suspended_block_holding_its_only_permitted_booking()
    resumed = apply_block_action(scenario["block_id"], "RESUME")
    assert resumed["status"] == "PUBLISHED"

    response = _attempt_booking(scenario["block_id"], scenario["episode_b_id"],
                                scenario["endoscopist_id"], resumed["version"],
                                "2026-09-15T15:00:00Z")
    validate_error(response, "ERR_SESSION_CAPACITY_EXCEEDED")


def test_two_rejected_bookings_leave_the_ledger_and_the_second_episode_untouched():
    """The invariant that booked and remaining minutes sum to capacity holds at every
    observable instant.

    The episode's `clinical_status` must be `OPEN`, else `ERR_INVALID_EPISODE_STATE`, and
    its `eligibility_status` must be `ELIGIBLE`, else `ERR_EPISODE_NOT_ELIGIBLE` (HTTP
    422) — this is where an ineligible episode finally stops being bookable.

    Design: Difficulty/priority_pair_validation_conflict/suspended_session_at_capacity_returns_session_not_accepting
    """
    scenario = _suspended_block_holding_its_only_permitted_booking()
    _attempt_booking(scenario["block_id"], scenario["episode_b_id"],
                     scenario["endoscopist_id"], scenario["suspended"]["version"],
                     "2026-09-15T15:00:00Z")
    resumed = apply_block_action(scenario["block_id"], "RESUME")
    _attempt_booking(scenario["block_id"], scenario["episode_b_id"],
                     scenario["endoscopist_id"], resumed["version"],
                     "2026-09-15T15:00:00Z")

    block = read_block(scenario["block_id"])
    episode_b = read_episode(scenario["episode_b_id"])

    assert block["booked_minutes"] == 60
    assert block["capacity_minutes"] == 480
    assert block["remaining_minutes"] == 420
    assert episode_b["clinical_status"] == "OPEN"


def _block_with_one_slot_taken_and_two_waiting_episodes():
    """One 13:00Z slot is already occupied through 14:00Z; an ASA 4 patient and an ASA 2
    patient both want the overlapping 13:30Z slot."""
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endoscopist = register_endoscopist()
    patient_a = register_patient(plan["id"], mrn="MRN-0001", birth_date="1975-04-10",
                                asa_class=2)
    patient_b = register_patient(plan["id"], mrn="MRN-0002", birth_date="1972-06-22",
                                asa_class=4)
    patient_c = register_patient(plan["id"], mrn="MRN-0003", birth_date="1970-02-14",
                                asa_class=2)
    episode_a = open_episode(patient_a["id"], "SCREENING_AVERAGE_RISK")
    episode_b = open_episode(patient_b["id"], "SCREENING_AVERAGE_RISK")
    episode_c = open_episode(patient_c["id"], "SCREENING_AVERAGE_RISK")
    block = create_block(endoscopist["id"], turnover_minutes=15, max_procedures=8)
    apply_block_action(block["id"], "PUBLISH")
    book_slot(block["id"], episode_a["id"], endoscopist["id"],
              slot_start_utc="2026-09-15T13:00:00Z", duration_minutes=45)
    return {
        "block_id": block["id"],
        "endoscopist_id": endoscopist["id"],
        "episode_b": episode_b,
        "episode_c": episode_c,
    }


def test_pre_procedure_risk_clearance_is_reported_ahead_of_room_occupancy_overlap():
    """A patient whose `asa_class` is 4 or 5 may not be slotted straight into the suite;
    such a booking is permitted only when the episode carries a `referral_id` whose
    referral reached `ACCEPTED_OFFICE_VISIT`, evidencing that the patient was seen in
    clinic first. Otherwise the booking is rejected with `ERR_PREPROCEDURE_RISK_UNCLEARED`
    (HTTP 422).

    Design: Difficulty/priority_pair_validation_conflict/asa_four_patient_on_overlapping_slot_returns_risk_uncleared
    """
    scenario = _block_with_one_slot_taken_and_two_waiting_episodes()
    assert scenario["episode_b"]["eligibility_status"] == "ELIGIBLE"

    block = read_block(scenario["block_id"])
    response = _attempt_booking(scenario["block_id"], scenario["episode_b"]["id"],
                                scenario["endoscopist_id"], block["version"],
                                "2026-09-15T13:30:00Z")
    validate_error(response, "ERR_PREPROCEDURE_RISK_UNCLEARED")


def test_an_already_cleared_patient_on_the_same_slot_reports_the_occupancy_conflict():
    """Two intervals conflict when the candidate starts strictly before the other's
    `occupancy_end_utc` **and** the other starts strictly before the candidate's
    `occupancy_end_utc`, so touching intervals do not conflict and a slot beginning
    exactly at another's `occupancy_end_utc` is accepted. A conflict is rejected with
    `ERR_SLOT_OVERLAP` (HTTP 409).

    A patient with `asa_class` of 3 or below clears this rule unconditionally.

    Design: Difficulty/priority_pair_validation_conflict/asa_four_patient_on_overlapping_slot_returns_risk_uncleared
    """
    scenario = _block_with_one_slot_taken_and_two_waiting_episodes()
    block = read_block(scenario["block_id"])
    response = _attempt_booking(scenario["block_id"], scenario["episode_c"]["id"],
                                scenario["endoscopist_id"], block["version"],
                                "2026-09-15T13:30:00Z")
    validate_error(response, "ERR_SLOT_OVERLAP")

    after = read_block(scenario["block_id"])
    assert after["booked_minutes"] == 60
    assert after["remaining_minutes"] == 420
    assert read_episode(scenario["episode_b"]["id"])["clinical_status"] == "OPEN"
    assert read_episode(scenario["episode_c"]["id"])["clinical_status"] == "OPEN"
