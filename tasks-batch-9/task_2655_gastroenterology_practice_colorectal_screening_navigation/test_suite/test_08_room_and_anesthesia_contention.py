"""The two contended axes of the suite: buffered single room occupancy and an aggregate
ceiling on simultaneously active anesthesia coverage."""
from test_helpers import (
    PRACTICE_ADMIN,
    api_client,
    apply_block_action,
    assert_utc_instant,
    book_slot,
    create_anesthesia_coverage_payload,
    create_block,
    move_clock,
    open_episode,
    read_block,
    read_coverage,
    read_episode,
    register_anesthesia_clinician,
    register_endoscopist,
    register_patient,
    register_plan,
    release_coverage,
    staff_block,
    validate_error,
    validate_success,
)
from test_helpers import create_procedure_booking_payload, REFERRAL_COORDINATOR


def _attempt_booking(session_id, episode_id, endoscopist_id, expected_session_version,
                     slot_start_utc, duration_minutes=45):
    return api_client.create_procedure_booking(
        session_id,
        create_procedure_booking_payload(episode_id, endoscopist_id,
                                         expected_session_version, slot_start_utc,
                                         duration_minutes),
        REFERRAL_COORDINATOR,
    )


def _block_with_the_first_slot_occupied():
    """A fifteen-minute turnover block whose 13:00Z slot occupies the room to 14:00Z."""
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endoscopist = register_endoscopist()
    episodes = []
    for index, (mrn, birth_date) in enumerate((
        ("MRN-0001", "1975-04-10"),
        ("MRN-0002", "1972-06-22"),
        ("MRN-0003", "1970-02-14"),
    )):
        patient = register_patient(plan["id"], mrn=mrn, birth_date=birth_date)
        episodes.append(open_episode(patient["id"], "SCREENING_AVERAGE_RISK"))
    block = create_block(endoscopist["id"], turnover_minutes=15, max_procedures=8)
    apply_block_action(block["id"], "PUBLISH")
    booking_a = book_slot(block["id"], episodes[0]["id"], endoscopist["id"],
                          slot_start_utc="2026-09-15T13:00:00Z", duration_minutes=45)
    return {
        "block_id": block["id"],
        "endoscopist_id": endoscopist["id"],
        "booking_a": booking_a,
        "episode_b": episodes[1],
        "episode_c": episodes[2],
    }


def test_the_occupied_interval_runs_to_the_slot_end_plus_the_turnover_minutes():
    """A room block's occupancy is *buffered*: a booking occupies its room from
    `slot_start_utc` until `occupancy_end_utc`, and `occupancy_end_utc` is the slot's end
    plus the block's `turnover_minutes`.

    `booked_minutes` is the sum, over every booking on the block whose `status` is
    `BOOKED`, `CHECKED_IN`, `IN_PROGRESS`, `COMPLETED`, or `ABORTED_INADEQUATE_PREP`, of
    that booking's `duration_minutes` plus the block's `turnover_minutes`; and
    `remaining_minutes` is `capacity_minutes` less `booked_minutes`.

    Design: Difficulty/resource_temporal_overlap/room_occupancy_includes_turnover_buffer
    """
    scenario = _block_with_the_first_slot_occupied()
    block = read_block(scenario["block_id"])

    assert_utc_instant(scenario["booking_a"]["occupancy_end_utc"], "2026-09-15T14:00:00")
    assert block["capacity_minutes"] == 480
    assert block["booked_minutes"] == 60
    assert block["remaining_minutes"] == 420


def test_a_slot_starting_one_minute_inside_the_turnover_buffer_is_rejected():
    """Because the interval is half-open, a booking that starts at exactly another booking's
    `occupancy_end_utc` is accepted; one that starts a single minute earlier is not.

    Turnover minutes are part of the occupied interval and part of the minute ledger, which
    is why a block with a fifteen-minute turnover cannot host four back-to-back sixty-minute
    exams in a four-hour window.

    Design: Difficulty/resource_temporal_overlap/room_occupancy_includes_turnover_buffer
    """
    scenario = _block_with_the_first_slot_occupied()
    block = read_block(scenario["block_id"])
    response = _attempt_booking(scenario["block_id"], scenario["episode_b"]["id"],
                                scenario["endoscopist_id"], block["version"],
                                "2026-09-15T13:45:00Z")
    validate_error(response, "ERR_SLOT_OVERLAP")

    assert read_block(scenario["block_id"])["booked_minutes"] == 60
    assert read_episode(scenario["episode_b"]["id"])["clinical_status"] == "OPEN"


def test_a_slot_starting_exactly_at_the_occupancy_end_is_accepted():
    """Second, the candidate occupancy interval must be disjoint from the occupancy interval
    of every booking already on the block whose `status` is `BOOKED`, `CHECKED_IN`,
    `IN_PROGRESS`, `COMPLETED`, or `ABORTED_INADEQUATE_PREP`; `CANCELLED` rows are skipped
    entirely.

    The episode moves `OPEN → PROCEDURE_SCHEDULED`, the provisional pricing pass described
    in Section 3.9 runs and writes `planned_classification` on the booking while creating a
    `BillingClaim` in `PROVISIONAL_PRICED`, and the block's `version` increments by 1.

    Design: Difficulty/resource_temporal_overlap/room_occupancy_includes_turnover_buffer
    """
    scenario = _block_with_the_first_slot_occupied()
    block = read_block(scenario["block_id"])
    response = _attempt_booking(scenario["block_id"], scenario["episode_c"]["id"],
                                scenario["endoscopist_id"], block["version"],
                                "2026-09-15T14:00:00Z")
    booking_c = validate_success(response, 201)

    assert_utc_instant(booking_c["occupancy_end_utc"], "2026-09-15T15:00:00")
    after = read_block(scenario["block_id"])
    assert after["booked_minutes"] == 120
    assert after["remaining_minutes"] == 360
    assert read_episode(scenario["episode_c"]["id"])["clinical_status"] == "PROCEDURE_SCHEDULED"
    assert read_episode(scenario["episode_b"]["id"])["clinical_status"] == "OPEN"


def _anesthetist_covering_two_of_four_blocks():
    """One anesthesia clinician with a ceiling of two already covers two of three
    simultaneous afternoon blocks; a fourth block sits immediately afterwards."""
    move_clock("2026-09-01T00:00:00Z")
    register_plan()
    endoscopist = register_endoscopist()
    anesthetist = register_anesthesia_clinician(max_overlapping_rooms=2)
    blocks = []
    for room_code in ("ENDO-1", "ENDO-2", "ENDO-3"):
        block = create_block(endoscopist["id"], room_code=room_code,
                             anesthesia_mode="MAC")
        apply_block_action(block["id"], "PUBLISH")
        blocks.append(block)
    late_block = create_block(endoscopist["id"], room_code="ENDO-4",
                              anesthesia_mode="MAC",
                              window_start_utc="2026-09-15T21:00:00Z",
                              window_end_utc="2026-09-15T23:00:00Z")
    apply_block_action(late_block["id"], "PUBLISH")
    coverage_one = staff_block(blocks[0]["id"], anesthetist["id"])
    coverage_two = staff_block(blocks[1]["id"], anesthetist["id"])
    return {
        "anesthetist_id": anesthetist["id"],
        "block_one_id": blocks[0]["id"],
        "block_three_id": blocks[2]["id"],
        "late_block_id": late_block["id"],
        "coverage_one": coverage_one,
        "coverage_two": coverage_two,
    }


def _attempt_coverage(session_id, anesthesia_clinician_id, start_utc, end_utc):
    return api_client.create_anesthesia_coverage(
        session_id,
        create_anesthesia_coverage_payload(anesthesia_clinician_id, start_utc, end_utc),
        PRACTICE_ADMIN,
    )


def test_a_third_simultaneous_interval_exceeds_the_supervision_ceiling():
    """The peak load is the largest of those per-instant loads, and if that peak exceeds the
    clinician's `max_overlapping_rooms`, the assignment is rejected with
    `ERR_ANESTHESIA_CONCURRENCY_EXCEEDED` (HTTP 409). Second, the assignment is tested against
    the supervision ceiling, computed across **every** block in the system rather than just
    this one, since an anesthesia clinician's attention is a single resource.

    Design: Difficulty/resource_temporal_overlap/anesthesia_aggregate_ceiling_and_adjacency
    """
    scenario = _anesthetist_covering_two_of_four_blocks()

    assert scenario["coverage_one"]["overlap_index"] == 1
    assert scenario["coverage_two"]["overlap_index"] == 2

    response = _attempt_coverage(scenario["block_three_id"], scenario["anesthetist_id"],
                                 "2026-09-15T13:00:00Z", "2026-09-15T21:00:00Z")
    validate_error(response, "ERR_ANESTHESIA_CONCURRENCY_EXCEEDED")
    assert read_block(scenario["block_three_id"])["status"] == "PUBLISHED"


def test_coverage_beginning_exactly_when_the_others_end_adds_no_load():
    """An anesthesia clinician's load is *aggregate*: coverage runs from `coverage_start_utc`
    to `coverage_end_utc`, no buffer is appended, and the constraint is a ceiling on how
    many of that clinician's simultaneously active coverage intervals may contain any single
    instant. A coverage interval beginning exactly when another ends therefore adds no load.

    Design: Difficulty/resource_temporal_overlap/anesthesia_aggregate_ceiling_and_adjacency
    """
    scenario = _anesthetist_covering_two_of_four_blocks()
    response = _attempt_coverage(scenario["late_block_id"], scenario["anesthetist_id"],
                                 "2026-09-15T21:00:00Z", "2026-09-15T23:00:00Z")
    late_coverage = validate_success(response, 201)

    assert late_coverage["overlap_index"] == 1
    assert late_coverage["covers_full_window"] is True
    assert read_block(scenario["late_block_id"])["status"] == "COVERAGE_CONFIRMED"


def test_releasing_a_row_frees_the_instant_for_a_replacement_assignment():
    """Collect that clinician's coverage rows whose `status` is `ACTIVE`; rows in `RELEASED`
    are excluded and stop counting the instant they are released.

    Design: Difficulty/resource_temporal_overlap/anesthesia_aggregate_ceiling_and_adjacency
    """
    scenario = _anesthetist_covering_two_of_four_blocks()
    _attempt_coverage(scenario["late_block_id"], scenario["anesthetist_id"],
                      "2026-09-15T21:00:00Z", "2026-09-15T23:00:00Z")
    release_coverage(scenario["coverage_one"]["id"])

    assert read_coverage(scenario["coverage_one"]["id"])["status"] == "RELEASED"
    assert read_block(scenario["block_one_id"])["status"] == "PUBLISHED"

    response = _attempt_coverage(scenario["block_three_id"], scenario["anesthetist_id"],
                                 "2026-09-15T13:00:00Z", "2026-09-15T21:00:00Z")
    replacement = validate_success(response, 201)

    assert replacement["overlap_index"] == 2
    assert read_block(scenario["block_three_id"])["status"] == "COVERAGE_CONFIRMED"
    assert read_block(scenario["late_block_id"])["status"] == "COVERAGE_CONFIRMED"
