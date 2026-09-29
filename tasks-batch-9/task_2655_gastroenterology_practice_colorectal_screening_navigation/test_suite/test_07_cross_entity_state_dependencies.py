"""One resource's admissibility depends on another resource's live state: a MAC start
needs confirmed coverage, and a recommendation needs a finalized report on its booking."""
from test_helpers import (
    api_client,
    apply_block_action,
    attest_prep,
    amend_report,
    book_slot,
    check_in,
    complete_exam,
    create_block,
    create_surveillance_recommendation_payload,
    finalize_report,
    list_recommendations,
    make_endoscopist_headers,
    move_clock,
    open_episode,
    read_block,
    read_booking,
    read_coverage,
    read_episode,
    receive_report,
    record_outreach,
    record_recommendation,
    register_anesthesia_clinician,
    register_endoscopist,
    register_patient,
    register_plan,
    release_coverage,
    specimen,
    staff_block,
    start_exam,
    validate_error,
)


def _checked_in_mac_booking():
    """A MAC block staffed for its whole window, with the patient checked in and waiting."""
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endoscopist = register_endoscopist()
    anesthetist = register_anesthesia_clinician(max_overlapping_rooms=1)
    patient = register_patient(plan["id"], birth_date="1975-04-10")
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    block = create_block(endoscopist["id"], anesthesia_mode="MAC")
    apply_block_action(block["id"], "PUBLISH")
    coverage = staff_block(block["id"], anesthetist["id"])
    booking = book_slot(block["id"], episode["id"], endoscopist["id"],
                        slot_start_utc="2026-09-15T13:00:00Z", duration_minutes=45)
    record_outreach(episode["id"], "PHONE", True)
    attest_prep(episode["id"], patient["id"], True)
    checked_in = check_in(booking["id"])
    return {
        "block_id": block["id"],
        "endoscopist_id": endoscopist["id"],
        "anesthetist_id": anesthetist["id"],
        "booking_id": booking["id"],
        "coverage": coverage,
        "checked_in": checked_in,
    }


def test_a_fully_spanning_coverage_row_confirms_the_block_and_records_overlap_index_one():
    """First, the coverage must fully span the block: `covers_full_window` is true exactly
    when `coverage_start_utc` is at or before the block's `window_start_utc` **and**
    `coverage_end_utc` is at or after the block's `window_end_utc`; when it is false the
    assignment is rejected with `ERR_COVERAGE_WINDOW_INSUFFICIENT` (HTTP 422).

    When the assignment is accepted, `overlap_index` is stored on the new row as a
    one-based count: one plus the number of that clinician's `ACTIVE` rows whose interval
    contains the candidate's own start instant, so the first coverage at that instant
    records 1.

    Design: Difficulty/cross_entity_state_dependency/procedure_start_requires_coverage_confirmed_session
    """
    scenario = _checked_in_mac_booking()

    assert scenario["coverage"]["covers_full_window"] is True
    assert scenario["coverage"]["overlap_index"] == 1
    assert scenario["coverage"]["status"] == "ACTIVE"
    assert read_block(scenario["block_id"])["status"] == "COVERAGE_CONFIRMED"
    assert scenario["checked_in"]["status"] == "CHECKED_IN"


def test_releasing_the_only_covering_row_demotes_the_block_and_blocks_the_start():
    """The inverse operation releases a coverage row: it sets that row's `status` to
    `RELEASED` so it stops counting toward its clinician's overlap ceiling, returns the
    released row as the response payload, moves the block `COVERAGE_CONFIRMED → PUBLISHED`
    when no `ACTIVE` fully covering row remains on it, and increments the block's `version`
    by 1.

    That clinician's `credential_status` must be `ACTIVE` — a `SUSPENDED` credential is
    rejected with `ERR_CLINICIAN_CREDENTIAL_SUSPENDED` (HTTP 422) — and when the block's
    `anesthesia_mode` is `MAC`, the block's `status` must be `COVERAGE_CONFIRMED` at the
    moment of the start, else the request is rejected with
    `ERR_ANESTHESIA_COVERAGE_REQUIRED` (HTTP 409).

    Design: Difficulty/cross_entity_state_dependency/procedure_start_requires_coverage_confirmed_session
    """
    scenario = _checked_in_mac_booking()
    released = release_coverage(scenario["coverage"]["id"])

    assert released["status"] == "RELEASED"
    assert read_block(scenario["block_id"])["status"] == "PUBLISHED"

    response = api_client.start_procedure(
        scenario["booking_id"], make_endoscopist_headers(scenario["endoscopist_id"])
    )
    validate_error(response, "ERR_ANESTHESIA_COVERAGE_REQUIRED")
    assert read_booking(scenario["booking_id"])["status"] == "CHECKED_IN"


def test_restaffing_the_block_lets_the_same_booking_start():
    """Accepting a fully covering row against a block in `PUBLISHED` advances that block
    `PUBLISHED → COVERAGE_CONFIRMED`, and increments the block's `version` by 1.

    Starting the procedure moves `CHECKED_IN → IN_PROGRESS` and is reserved to the
    `Endoscopist` whose `X-User-ID` equals the booking's `performing_endoscopist_id`;
    another endoscopist is refused with `ERR_NOT_RESOURCE_OWNER`.

    Design: Difficulty/cross_entity_state_dependency/procedure_start_requires_coverage_confirmed_session
    """
    scenario = _checked_in_mac_booking()
    release_coverage(scenario["coverage"]["id"])
    replacement = staff_block(scenario["block_id"], scenario["anesthetist_id"])

    assert replacement["overlap_index"] == 1
    assert read_coverage(scenario["coverage"]["id"])["status"] == "RELEASED"
    assert read_block(scenario["block_id"])["status"] == "COVERAGE_CONFIRMED"

    started = start_exam(scenario["booking_id"], scenario["endoscopist_id"])
    assert started["status"] == "IN_PROGRESS"


def _amended_report_on_a_closed_episode():
    """Finalize a two-adenoma report, then amend it so a villous component and a
    twelve-millimetre adenoma appear while the report sits outside every aggregate."""
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endoscopist = register_endoscopist(npi="1000000001", full_name="Dr Ada Ng")
    reviewer = register_endoscopist(npi="1000000002", full_name="Dr Cy Okafor")
    anesthetist = register_anesthesia_clinician()
    patient = register_patient(plan["id"], birth_date="1975-04-10")
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    block = create_block(endoscopist["id"], anesthesia_mode="MAC")
    apply_block_action(block["id"], "PUBLISH")
    staff_block(block["id"], anesthetist["id"])
    booking = book_slot(block["id"], episode["id"], endoscopist["id"],
                        slot_start_utc="2026-09-15T13:00:00Z", duration_minutes=45)
    record_outreach(episode["id"], "PHONE", True)
    attest_prep(episode["id"], patient["id"], True)
    check_in(booking["id"])
    start_exam(booking["id"], endoscopist["id"])
    complete_exam(booking["id"], endoscopist["id"], prep_quality_bbps=7,
                  polyps_removed_count=2, largest_polyp_mm=12, specimen_count=2)
    report = receive_report(booking["id"], [
        specimen("A", "TUBULAR_ADENOMA", 4),
        specimen("B", "TUBULAR_ADENOMA", 3),
    ])
    finalize_report(report["id"])
    episode_after_finalize = read_episode(episode["id"])
    amended = amend_report(report["id"], [
        specimen("A", "TUBULAR_ADENOMA", 4),
        specimen("B", "TUBULOVILLOUS_ADENOMA", 12),
    ], amendment_reason="Second review upgraded specimen B")
    return {
        "episode_id": episode["id"],
        "report_id": report["id"],
        "reviewer_id": reviewer["id"],
        "episode_after_finalize": episode_after_finalize,
        "amended": amended,
        "episode_after_amend": read_episode(episode["id"]),
    }


def test_a_report_sitting_in_amended_cannot_anchor_a_recommendation():
    """When a `pathology_report_id` is cited, that report's `status` must be `FINALIZED` and
    its `booking_id` must belong to the addressed episode's booking; a report still in
    `RECEIVED` or `AMENDED`, or one belonging to a different booking, is rejected with
    `ERR_PATHOLOGY_NOT_FINALIZED` (HTTP 409).

    The report moves `FINALIZED → AMENDED`, `specimens` and `high_grade_dysplasia` are
    replaced, all five derived findings fields are recomputed, `amendment_count` increases
    by 1, and — critically — **while the report sits in `AMENDED` it is excluded from every
    finalized-only aggregate**, both the surveillance aggregate and the quality numerator,
    until it is finalized again.

    Design: Difficulty/cross_entity_state_dependency/recommendation_requires_finalized_report_pair
    """
    scenario = _amended_report_on_a_closed_episode()
    episode = scenario["episode_after_amend"]

    assert scenario["episode_after_finalize"]["clinical_status"] == "CLOSED_SURVEILLANCE_SET"
    assert scenario["episode_after_finalize"]["assigned_interval_months"] == 84
    assert scenario["amended"]["status"] == "AMENDED"
    assert scenario["amended"]["villous_component"] is True
    assert episode["clinical_status"] == "CLOSED_SURVEILLANCE_SET"

    response = api_client.create_surveillance_recommendation(
        scenario["episode_id"],
        create_surveillance_recommendation_payload(
            episode["version"], pathology_report_id=scenario["report_id"]
        ),
        make_endoscopist_headers(scenario["reviewer_id"]),
    )
    validate_error(response, "ERR_PATHOLOGY_NOT_FINALIZED")


def test_refinalizing_the_amended_report_recomputes_the_interval_to_thirty_six_months():
    """Re-finalizing an amended report against an episode that already sits in
    `CLOSED_SURVEILLANCE_SET` re-runs the whole cascade against an already-closed state as
    a self-loop: the episode stays in `CLOSED_SURVEILLANCE_SET`, `finalized_at` is
    re-stamped from the current logical clock, the previously `ACTIVE` recommendation is
    superseded and a new `ACTIVE` one is created from the amended aggregate, the episode's
    `assigned_interval_months` and `due_date` are overwritten, and the claim is repriced
    again under the final pass with `reprice_count` incremented once more.

    Otherwise, if the aggregate adenoma count is 5 or more, or the aggregate largest
    adenoma measures 10 millimetres or more, or a villous component is present, the base is
    36 months.

    Design: Difficulty/cross_entity_state_dependency/recommendation_requires_finalized_report_pair
    """
    scenario = _amended_report_on_a_closed_episode()
    version_before = scenario["episode_after_amend"]["version"]

    refinalized = finalize_report(scenario["report_id"])
    episode = read_episode(scenario["episode_id"])

    assert refinalized["status"] == "FINALIZED"
    assert episode["version"] == version_before + 1
    assert episode["clinical_status"] == "CLOSED_SURVEILLANCE_SET"
    assert episode["assigned_interval_months"] == 36


def test_an_attested_override_supersedes_both_guideline_rows_on_the_episode():
    """When an override survives both checks, `assigned_interval_months` takes the override
    value and `basis` is recorded as `OVERRIDE_ATTESTED`, with `attesting_endoscopist_id`
    set to the acting `X-User-ID`; with no override, `assigned_interval_months` equals
    `computed_interval_months`, `basis` is `GUIDELINE`, and `attesting_endoscopist_id` stays
    null.

    Recording a recommendation supersedes the episode's previously `ACTIVE` row to
    `SUPERSEDED`, copies `assigned_interval_months` and `next_due_date` onto the episode's
    `assigned_interval_months` and `due_date`, and increments the episode's `version` by 1.

    Design: Difficulty/cross_entity_state_dependency/recommendation_requires_finalized_report_pair
    """
    scenario = _amended_report_on_a_closed_episode()
    finalize_report(scenario["report_id"])

    override = record_recommendation(
        scenario["episode_id"], scenario["reviewer_id"],
        pathology_report_id=scenario["report_id"],
        override_interval_months=60,
        override_reason="Piecemeal resection warrants earlier review",
    )

    assert override["basis"] == "OVERRIDE_ATTESTED"
    assert override["computed_interval_months"] == 36
    assert override["assigned_interval_months"] == 60
    assert override["next_due_date"] == "2031-09-15"
    assert override["attesting_endoscopist_id"] == scenario["reviewer_id"]

    rows, meta = list_recommendations({"episode_id": scenario["episode_id"]})
    assert meta["total_count"] == 3
    active = [row for row in rows if row["status"] == "ACTIVE"]
    superseded = [row for row in rows if row["status"] == "SUPERSEDED"]
    assert len(active) == 1
    assert active[0]["id"] == override["id"]
    assert sorted(row["assigned_interval_months"] for row in superseded) == [36, 84]
    assert all(row["basis"] == "GUIDELINE" for row in superseded)

    episode = read_episode(scenario["episode_id"])
    assert episode["assigned_interval_months"] == 60
    assert episode["due_date"] == "2031-09-15"
