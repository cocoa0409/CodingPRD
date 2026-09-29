"""Endpoint surfaces: the coverage collection round trip, the clock write, a gated close
action, a cross-reference link and the recomputed minute ledger on a block read."""
from test_helpers import (
    PATIENT_NAVIGATOR,
    PRACTICE_ADMIN,
    REFERRAL_COORDINATOR,
    api_client,
    apply_block_action,
    assert_utc_instant,
    book_slot,
    check_in,
    close_episode_payload,
    complete_exam,
    confirm_prep,
    create_block,
    create_surveillance_recommendation_payload,
    finalize_report,
    list_coverage,
    list_recommendations,
    make_endoscopist_headers,
    move_clock,
    open_episode,
    read_block,
    read_coverage,
    read_episode,
    read_patient,
    receive_report,
    register_anesthesia_clinician,
    register_endoscopist,
    register_patient,
    register_plan,
    release_coverage,
    specimen,
    staff_block,
    start_exam,
    validate_error,
    validate_success,
)

PLAN_P1 = {"deductible_cents": 150000, "diagnostic_coinsurance_pct": 0.20}


def test_the_coverage_row_survives_the_release_that_demotes_its_block():
    """A coverage row is created in `status` `ACTIVE`, and its `session_id` records the block it
    staffs. Accepting a fully covering row against a block in `PUBLISHED` advances that block
    `PUBLISHED → COVERAGE_CONFIRMED`, and increments the block's `version` by 1. The inverse
    operation releases a coverage row: it sets that row's `status` to `RELEASED` so it stops
    counting toward its clinician's overlap ceiling, returns the released row as the response
    payload, moves the block `COVERAGE_CONFIRMED → PUBLISHED` when no `ACTIVE` fully covering row
    remains on it, and increments the block's `version` by 1.

    When the assignment is accepted, `overlap_index` is stored on the new row as a one-based
    count: one plus the number of that clinician's `ACTIVE` rows whose interval contains the
    candidate's own start instant, so the first coverage at that instant records 1.

    Design: Corner/endpoints/anesthesia_coverage_create_read_list_and_release
    """
    move_clock("2026-09-01T00:00:00Z")
    endoscopist = register_endoscopist()
    anesthetist = register_anesthesia_clinician(max_overlapping_rooms=1)
    block = create_block(endoscopist["id"], anesthesia_mode="MAC")
    assert block["capacity_minutes"] == 480
    published = apply_block_action(block["id"], "PUBLISH")
    assert published["remaining_minutes"] == 480
    baseline_version = published["version"]

    coverage = staff_block(block["id"], anesthetist["id"],
                           coverage_start_utc="2026-09-15T12:30:00Z",
                           coverage_end_utc="2026-09-15T21:30:00Z")
    assert coverage["covers_full_window"] is True
    assert coverage["overlap_index"] == 1
    assert coverage["status"] == "ACTIVE"

    fetched = read_coverage(coverage["id"])
    assert fetched["session_id"] == block["id"]
    assert_utc_instant(fetched["coverage_start_utc"], "2026-09-15T12:30:00")
    assert fetched["covers_full_window"] is True

    confirmed = read_block(block["id"])
    assert confirmed["status"] == "COVERAGE_CONFIRMED"
    assert confirmed["version"] == baseline_version + 1

    rows, meta = list_coverage({"session_id": block["id"], "status": "ACTIVE"})
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert rows[0]["id"] == coverage["id"]

    released = release_coverage(coverage["id"])
    assert released["status"] == "RELEASED"
    assert read_coverage(coverage["id"])["status"] == "RELEASED"

    demoted = read_block(block["id"])
    assert demoted["status"] == "PUBLISHED"
    assert demoted["version"] == baseline_version + 2
    assert list_coverage({"session_id": block["id"], "status": "ACTIVE"})[1]["total_count"] == 0


def test_two_identical_creates_straddling_a_clock_write_land_on_different_dates():
    """The episode's `index_date` is the calendar date of the logical clock at creation, in
    `YYYY-MM-DD` form, and it anchors both the age calculation and the due date. The `due_date`
    is computed at creation in `YYYY-MM-DD` form by adding a whole number of calendar days to
    `index_date`. A `DIAGNOSTIC_FOLLOWUP` episode is due in 90 days; every other indication is
    due in 180 days.

    Design: Corner/endpoints/clock_endpoint_reanchors_index_date_and_due_date
    """
    plan = register_plan()
    patient_a = register_patient(plan["id"], mrn="MRN-0001")
    patient_b = register_patient(plan["id"], mrn="MRN-0002")

    before = open_episode(patient_a["id"], "SCREENING_AVERAGE_RISK")
    assert before["index_date"] == "2026-08-01"
    assert before["due_date"] == "2027-01-28"
    assert before["created_at"] == "2026-08-01T00:00:00.000Z"

    moved = validate_success(api_client.set_clock("2026-12-25T09:30:00Z", PRACTICE_ADMIN))
    assert moved == {}

    after = open_episode(patient_b["id"], "SCREENING_AVERAGE_RISK")
    assert after["index_date"] == "2026-12-25"
    assert after["due_date"] == "2027-06-23"
    assert after["created_at"] == "2026-12-25T09:30:00.000Z"

    untouched = read_episode(before["id"])
    assert untouched["index_date"] == "2026-08-01"
    assert untouched["due_date"] == "2027-01-28"


def test_the_close_action_is_legal_exactly_once_and_moves_only_the_clinical_dimension():
    """A `PatientNavigator` or `ReferralCoordinator` may close an `OPEN` episode by supplying a
    `reason` of `PATIENT_DECLINED`, `LOST_TO_FOLLOW_UP`, or `SUPERSEDED_BY_OTHER_PATHWAY`; the
    reason is stored in `closure_reason`, the first two both drive `OPEN → CLOSED_DECLINED` and
    the third drives `OPEN → CLOSED_SUPERSEDED`, and in every case the patient's
    `open_episode_count` and `navigation_priority` are recomputed afterwards. Closing an episode
    whose `clinical_status` is not `OPEN` is rejected with `ERR_INVALID_EPISODE_STATE`.

    Design: Corner/endpoints/episode_close_is_gated_on_an_open_clinical_status
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    patient = register_patient(plan["id"], family_history_crc=True)
    kept = open_episode(patient["id"], "SCREENING_HIGH_RISK")
    doomed = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")

    before = read_patient(patient["id"])
    assert before["open_episode_count"] == 2
    assert before["navigation_priority"] == "HIGH"

    closed = validate_success(
        api_client.close_screening_episode(
            doomed["id"], close_episode_payload("SUPERSEDED_BY_OTHER_PATHWAY"),
            PATIENT_NAVIGATOR))
    assert closed["clinical_status"] == "CLOSED_SUPERSEDED"
    assert closed["closure_reason"] == "SUPERSEDED_BY_OTHER_PATHWAY"
    assert closed["navigation_status"] == "NOT_STARTED"

    after = read_patient(patient["id"])
    assert after["open_episode_count"] == 1
    assert after["navigation_priority"] == "ROUTINE"

    validate_error(
        api_client.close_screening_episode(
            doomed["id"], close_episode_payload("PATIENT_DECLINED"), REFERRAL_COORDINATOR),
        "ERR_INVALID_EPISODE_STATE")

    unchanged = read_episode(doomed["id"])
    assert unchanged["clinical_status"] == "CLOSED_SUPERSEDED"
    assert unchanged["closure_reason"] == "SUPERSEDED_BY_OTHER_PATHWAY"
    assert read_episode(kept["id"])["clinical_status"] == "OPEN"


def test_only_the_finalized_sibling_report_is_a_legal_link_target():
    """When a `pathology_report_id` is cited, that report's `status` must be `FINALIZED` and its
    `booking_id` must belong to the addressed episode's booking; a report still in `RECEIVED` or
    `AMENDED`, or one belonging to a different booking, is rejected with
    `ERR_PATHOLOGY_NOT_FINALIZED` (HTTP 409).

    Recording a recommendation supersedes the episode's previously `ACTIVE` row to `SUPERSEDED`,
    copies `assigned_interval_months` and `next_due_date` onto the episode's
    `assigned_interval_months` and `due_date`, and increments the episode's `version` by 1.

    Design: Corner/endpoints/recommendation_link_requires_a_finalized_report_on_that_episode
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan(**PLAN_P1)
    performer = register_endoscopist()
    recorder = register_endoscopist(npi="1000000002", full_name="Dr Cy Vale")
    patient = register_patient(plan["id"])
    block = create_block(performer["id"])
    apply_block_action(block["id"], "PUBLISH")
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    booking = book_slot(block["id"], episode["id"], performer["id"])
    confirm_prep(episode["id"], patient["id"])
    check_in(booking["id"])
    start_exam(booking["id"], performer["id"])
    complete_exam(booking["id"], performer["id"], prep_quality_bbps=8,
                  polyps_removed_count=2, largest_polyp_mm=6, specimen_count=2)

    to_finalize = receive_report(booking["id"], [specimen("A", "TUBULAR_ADENOMA", 6)],
                                accession_number="ACC-0001")
    left_open = receive_report(booking["id"], [specimen("B", "HYPERPLASTIC", 3)],
                               accession_number="ACC-0002")
    assert left_open["status"] == "RECEIVED"
    assert finalize_report(to_finalize["id"])["status"] == "FINALIZED"

    closed = read_episode(episode["id"])
    assert closed["clinical_status"] == "CLOSED_SURVEILLANCE_SET"
    assert closed["assigned_interval_months"] == 84
    pinned = closed["version"]

    validate_error(
        api_client.create_surveillance_recommendation(
            episode["id"],
            create_surveillance_recommendation_payload(
                pinned, pathology_report_id=left_open["id"]),
            make_endoscopist_headers(recorder["id"])),
        "ERR_PATHOLOGY_NOT_FINALIZED")
    assert read_episode(episode["id"])["version"] == pinned

    recorded = validate_success(
        api_client.create_surveillance_recommendation(
            episode["id"],
            create_surveillance_recommendation_payload(
                pinned, pathology_report_id=to_finalize["id"]),
            make_endoscopist_headers(recorder["id"])),
        201)
    assert recorded["status"] == "ACTIVE"
    assert recorded["computed_interval_months"] == 84
    assert recorded["next_due_date"] == "2033-09-15"
    assert recorded["basis"] == "GUIDELINE"
    assert recorded["pathology_report_id"] == to_finalize["id"]

    active, meta = list_recommendations({"episode_id": episode["id"], "status": "ACTIVE"})
    assert meta["total_count"] == 1
    assert active[0]["id"] == recorded["id"]


def test_the_ledger_charges_turnover_on_every_booking_not_just_the_last_one():
    """The block's minute ledger is recomputed — never adjusted incrementally — as follows:
    `capacity_minutes` is the whole minutes between the window instants; `booked_minutes` is the
    sum, over every booking on the block whose `status` is `BOOKED`, `CHECKED_IN`, `IN_PROGRESS`,
    `COMPLETED`, or `ABORTED_INADEQUATE_PREP`, of that booking's `duration_minutes` plus the
    block's `turnover_minutes`; and `remaining_minutes` is `capacity_minutes` less
    `booked_minutes`. The invariant that booked and remaining minutes sum to capacity holds at
    every observable instant.

    Design: Corner/endpoints/session_read_recomputes_the_minute_ledger_across_two_bookings
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endoscopist = register_endoscopist()
    patient_a = register_patient(plan["id"], mrn="MRN-0001")
    patient_b = register_patient(plan["id"], mrn="MRN-0002", birth_date="1970-02-02")
    episode_a = open_episode(patient_a["id"], "SCREENING_AVERAGE_RISK")
    episode_b = open_episode(patient_b["id"], "SCREENING_AVERAGE_RISK")

    block = create_block(endoscopist["id"])
    assert block["turnover_minutes"] == 15
    assert block["capacity_minutes"] == 480
    assert block["booked_minutes"] == 0
    published = apply_block_action(block["id"], "PUBLISH")
    assert published["remaining_minutes"] == 480

    first = book_slot(block["id"], episode_a["id"], endoscopist["id"],
                      expected_session_version=published["version"],
                      slot_start_utc="2026-09-15T13:00:00Z", duration_minutes=45)
    assert first["slot_end_utc"][:19] == "2026-09-15T13:45:00"
    assert first["occupancy_end_utc"][:19] == "2026-09-15T14:00:00"

    mid = read_block(block["id"])
    assert mid["booked_minutes"] == 60
    assert mid["remaining_minutes"] == 420
    assert mid["version"] == published["version"] + 1

    second = book_slot(block["id"], episode_b["id"], endoscopist["id"],
                       expected_session_version=mid["version"],
                       slot_start_utc="2026-09-15T14:00:00Z", duration_minutes=30)
    assert second["slot_end_utc"][:19] == "2026-09-15T14:30:00"
    assert second["occupancy_end_utc"][:19] == "2026-09-15T14:45:00"

    end = read_block(block["id"])
    assert end["booked_minutes"] == 105
    assert end["remaining_minutes"] == 375
    assert end["status"] == "PUBLISHED"
