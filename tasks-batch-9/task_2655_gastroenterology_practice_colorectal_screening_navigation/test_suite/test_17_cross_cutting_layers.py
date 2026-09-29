"""Cross-cutting layers: the two optimistic-concurrency tokens, filtered pagination, a live
counter that walks its threshold in both directions, and the read-your-write guarantee."""
from test_helpers import (
    REFERRAL_COORDINATOR,
    api_client,
    apply_block_action,
    assert_utc_instant,
    book_slot,
    check_in,
    close_episode,
    complete_exam,
    confirm_prep,
    create_block,
    create_procedure_booking_payload,
    create_surveillance_recommendation_payload,
    finalize_report,
    list_claims,
    list_episodes,
    list_recommendations,
    make_endoscopist_headers,
    move_clock,
    open_episode,
    read_block,
    read_episode,
    read_patient,
    receive_report,
    record_outreach,
    register_anesthesia_clinician,
    register_endoscopist,
    register_patient,
    register_plan,
    specimen,
    staff_block,
    start_exam,
    validate_error,
    validate_success,
)


def test_a_coverage_write_stales_the_held_block_version_and_the_re_read_books():
    """A booking consumes room minutes and slot geometry that another writer may have just
    consumed, so if the block's current `version` differs from the supplied
    `expected_session_version`, the create is rejected with `ERR_STALE_SESSION_VERSION` (HTTP
    412) — the request priced its slot against a capacity picture that no longer holds.
    Accepting a fully covering row against a block in `PUBLISHED` advances that block
    `PUBLISHED → COVERAGE_CONFIRMED`, and increments the block's `version` by 1.

    Design: Corner/cross_cutting_complexity_layers/stale_expected_session_version_is_rejected_then_retried
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endoscopist = register_endoscopist()
    anesthetist = register_anesthesia_clinician(max_overlapping_rooms=1)
    patient = register_patient(plan["id"], asa_class=2)
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")

    block = create_block(endoscopist["id"], anesthesia_mode="MAC")
    created_version = block["version"]
    published_version = apply_block_action(block["id"], "PUBLISH")["version"]
    assert published_version == created_version + 1

    staff_block(block["id"], anesthetist["id"])

    validate_error(
        api_client.create_procedure_booking(
            block["id"],
            create_procedure_booking_payload(
                episode["id"], endoscopist["id"], published_version,
                "2026-09-15T13:00:00Z", 45),
            REFERRAL_COORDINATOR),
        "ERR_STALE_SESSION_VERSION")

    # The coverage write, not another booking, is what invalidated the held version.
    staffed = read_block(block["id"])
    assert staffed["booked_minutes"] == 0
    assert staffed["status"] == "COVERAGE_CONFIRMED"
    assert staffed["version"] == published_version + 1
    assert read_episode(episode["id"])["clinical_status"] == "OPEN"

    booking = validate_success(
        api_client.create_procedure_booking(
            block["id"],
            create_procedure_booking_payload(
                episode["id"], endoscopist["id"], staffed["version"],
                "2026-09-15T13:00:00Z", 45),
            REFERRAL_COORDINATOR),
        201)
    assert booking["status"] == "BOOKED"

    settled = read_block(block["id"])
    assert settled["booked_minutes"] == 60
    assert settled["version"] == staffed["version"] + 1
    assert read_episode(episode["id"])["clinical_status"] == "PROCEDURE_SCHEDULED"


def test_the_booking_and_the_finalize_cascade_both_stale_the_held_episode_version():
    """An attested override recommendation legitimately supersedes the guideline recommendation
    that the pathology-finalization cascade produced, so this operation cannot be rejected on
    episode state alone; it is rejected only when the writer's view of the episode is stale,
    and that rejection carries `ERR_STALE_EPISODE_VERSION` (HTTP 412). Recording a
    recommendation supersedes the episode's previously `ACTIVE` row to `SUPERSEDED`, copies
    `assigned_interval_months` and `next_due_date` onto the episode's
    `assigned_interval_months` and `due_date`, and increments the episode's `version` by 1.

    Design: Corner/cross_cutting_complexity_layers/stale_expected_episode_version_is_rejected_then_retried
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endo_a = register_endoscopist()
    endo_b = register_endoscopist(npi="1000000002", full_name="Dr Cy Vale")
    patient = register_patient(plan["id"], asa_class=2)
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    held_version = episode["version"]

    block = create_block(endo_a["id"])
    apply_block_action(block["id"], "PUBLISH")
    booking = book_slot(block["id"], episode["id"], endo_a["id"])
    confirm_prep(episode["id"], patient["id"])
    check_in(booking["id"])
    start_exam(booking["id"], endo_a["id"])
    complete_exam(booking["id"], endo_a["id"], 8, 1, 7, 1)
    report = receive_report(booking["id"], [specimen("A", "TUBULAR_ADENOMA", 7)])
    finalized = finalize_report(report["id"])
    assert finalized["status"] == "FINALIZED"

    b_headers = make_endoscopist_headers(endo_b["id"])
    validate_error(
        api_client.create_surveillance_recommendation(
            episode["id"],
            create_surveillance_recommendation_payload(
                held_version, pathology_report_id=report["id"]),
            b_headers),
        "ERR_STALE_EPISODE_VERSION")

    cascaded = read_episode(episode["id"])
    assert cascaded["clinical_status"] == "CLOSED_SURVEILLANCE_SET"
    assert cascaded["assigned_interval_months"] == 84
    # The booking create and the finalize cascade each wrote the episode.
    assert cascaded["version"] > held_version

    accepted = validate_success(
        api_client.create_surveillance_recommendation(
            episode["id"],
            create_surveillance_recommendation_payload(
                cascaded["version"], pathology_report_id=report["id"]),
            b_headers),
        201)
    assert accepted["status"] == "ACTIVE"
    assert accepted["assigned_interval_months"] == 84

    # Exactly the cascade's own recommendation was superseded; the 412 created nothing.
    superseded, superseded_meta = list_recommendations(
        {"episode_id": episode["id"], "status": "SUPERSEDED"})
    assert superseded_meta["total_count"] == 1
    assert read_episode(episode["id"])["version"] == cascaded["version"] + 1


def test_the_page_window_and_the_filters_describe_the_filtered_collection():
    """The `meta` object of a list response carries `limit` and `offset` as they were resolved for
    the request, `total_count` as the number of rows matching the filters before pagination is
    applied, and `has_more` as a boolean that is true when rows remain beyond the current page.
    Filter query parameters, where an endpoint offers them, combine conjunctively: a row must
    match every supplied filter to appear in the result.

    Design: Corner/cross_cutting_complexity_layers/episode_list_filter_and_page_windows_interact
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    patient_a = register_patient(
        plan["id"], mrn="MRN-0001", birth_date="1975-04-10", family_history_crc=True)
    patient_b = register_patient(plan["id"], mrn="MRN-0002", birth_date="1970-02-02")

    episode_a1 = open_episode(patient_a["id"], "SCREENING_HIGH_RISK")
    episode_a2 = open_episode(patient_a["id"], "SURVEILLANCE")
    episode_a3 = open_episode(patient_a["id"], "DIAGNOSTIC_FOLLOWUP")
    episode_b1 = open_episode(patient_b["id"], "SCREENING_AVERAGE_RISK")
    episode_b2 = open_episode(patient_b["id"], "DIAGNOSTIC_FOLLOWUP")

    everything, everything_meta = list_episodes()
    assert everything_meta["total_count"] == 5
    assert everything_meta["limit"] == 10
    assert everything_meta["offset"] == 0
    assert everything_meta["has_more"] is False

    page_one, page_one_meta = list_episodes(
        {"patient_id": patient_a["id"], "limit": 2, "offset": 0})
    assert page_one_meta["total_count"] == 3
    assert page_one_meta["has_more"] is True
    assert len(page_one) == 2
    assert all(row["patient_id"] == patient_a["id"] for row in page_one)

    page_two, page_two_meta = list_episodes(
        {"patient_id": patient_a["id"], "limit": 2, "offset": 2})
    assert page_two_meta["total_count"] == 3
    assert page_two_meta["has_more"] is False
    assert len(page_two) == 1
    assert page_two[0]["patient_id"] == patient_a["id"]

    walked = [row["id"] for row in page_one] + [row["id"] for row in page_two]
    assert len(set(walked)) == 3
    assert set(walked) == {episode_a1["id"], episode_a2["id"], episode_a3["id"]}
    assert episode_b1["id"] not in walked
    assert episode_b2["id"] not in walked

    closed = close_episode(episode_a2["id"], "PATIENT_DECLINED")
    assert closed["clinical_status"] == "CLOSED_DECLINED"

    still_open, still_open_meta = list_episodes(
        {"patient_id": patient_a["id"], "clinical_status": "OPEN", "limit": 100, "offset": 0})
    assert still_open_meta["total_count"] == 2
    assert still_open_meta["has_more"] is False

    _, unfiltered_meta = list_episodes({"patient_id": patient_a["id"]})
    assert unfiltered_meta["total_count"] == 3

    composed, composed_meta = list_episodes(
        {"patient_id": patient_a["id"], "indication": "DIAGNOSTIC_FOLLOWUP"})
    assert composed_meta["total_count"] == 1
    assert composed[0]["id"] == episode_a3["id"]


def test_the_open_episode_counter_trips_and_untrips_at_two():
    """`open_episode_count` starts at 0 and is the count of that patient's screening episodes
    whose `clinical_status` is `OPEN`, `PROCEDURE_SCHEDULED`, or `PATHOLOGY_PENDING`.
    `navigation_priority` starts at `ROUTINE` and becomes `HIGH` whenever `open_episode_count`
    reaches two or more; it returns to `ROUTINE` whenever the count falls below two.

    Design: Corner/cross_cutting_complexity_layers/navigation_priority_flips_at_the_two_open_episode_boundary
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    patient = register_patient(plan["id"], asa_class=2)
    assert patient["open_episode_count"] == 0
    assert patient["navigation_priority"] == "ROUTINE"

    episode_one = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    after_one = read_patient(patient["id"])
    assert after_one["open_episode_count"] == 1
    assert after_one["navigation_priority"] == "ROUTINE"

    episode_two = open_episode(patient["id"], "DIAGNOSTIC_FOLLOWUP")
    after_two = read_patient(patient["id"])
    assert after_two["open_episode_count"] == 2
    assert after_two["navigation_priority"] == "HIGH"

    closed = close_episode(episode_one["id"], "LOST_TO_FOLLOW_UP")
    assert closed["clinical_status"] == "CLOSED_DECLINED"
    assert closed["closure_reason"] == "LOST_TO_FOLLOW_UP"

    # The flag falls back, so it is not a high-water mark.
    after_close = read_patient(patient["id"])
    assert after_close["open_episode_count"] == 1
    assert after_close["navigation_priority"] == "ROUTINE"
    assert read_episode(episode_two["id"])["clinical_status"] == "OPEN"


def test_a_write_response_already_carries_every_field_the_next_read_returns():
    """The episode moves `OPEN → PROCEDURE_SCHEDULED`, the provisional pricing pass described
    in Section 3.9 runs and writes `planned_classification` on the booking while creating a
    `BillingClaim` in `PROVISIONAL_PRICED`, and the block's `version` increments by 1.
    `prep_adherence_score` is then recomputed **from the whole log, from scratch, every single
    time** — it is never incrementally adjusted, and no status filter applies because the log
    has no statuses.

    Design: Corner/consistency_model/derived_fields_are_visible_in_the_writing_response
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan(deductible_cents=150000, diagnostic_coinsurance_pct=0.20)
    endoscopist = register_endoscopist()
    patient = register_patient(plan["id"], asa_class=2)
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    block = create_block(endoscopist["id"])
    published_version = apply_block_action(block["id"], "PUBLISH")["version"]

    booking = validate_success(
        api_client.create_procedure_booking(
            block["id"],
            create_procedure_booking_payload(
                episode["id"], endoscopist["id"], published_version,
                "2026-09-15T13:00:00Z", 45),
            REFERRAL_COORDINATOR),
        201)
    # The geometry is already derived in the creating response.
    assert_utc_instant(booking["slot_end_utc"], "2026-09-15T13:45:00")
    assert_utc_instant(booking["occupancy_end_utc"], "2026-09-15T14:00:00")
    assert booking["planned_classification"] == "SCREENING_PREVENTIVE"

    # The claim exists before any further call: 78000 + 950 * 45 facility and 41500
    # professional make a base of 162250, which is TIER_2 and takes the 8500 addon.
    claims, claim_meta = list_claims({"booking_id": booking["id"]})
    assert claim_meta["total_count"] == 1
    assert claims[0]["status"] == "PROVISIONAL_PRICED"
    assert claims[0]["variant"] == "PROVISIONAL"
    assert claims[0]["allowed_amount_cents"] == 170750
    assert claims[0]["patient_responsibility_cents"] == 0

    ledger = read_block(block["id"])
    assert ledger["booked_minutes"] == 60
    assert ledger["remaining_minutes"] == 420

    # One acknowledged SMS touchpoint scores 2.0, below the 3.00 advancement threshold.
    navigated = record_outreach(episode["id"], "SMS", True)
    assert navigated["prep_adherence_score"] == 2.00
    assert navigated["navigation_status"] == "PREP_AT_RISK"
    assert len(navigated["outreach_log"]) == 1
    assert navigated["outreach_log"][0]["channel"] == "SMS"
    assert navigated["outreach_log"][0]["acknowledged"] is True
    assert_utc_instant(navigated["outreach_log"][0]["occurred_at"], "2026-09-01T00:00:00")

    # The read repeats the write response instead of improving on it.
    reread = read_episode(episode["id"])
    assert reread["prep_adherence_score"] == 2.00
    assert reread["navigation_status"] == "PREP_AT_RISK"
    assert reread["clinical_status"] == "PROCEDURE_SCHEDULED"
