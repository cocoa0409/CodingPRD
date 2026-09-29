"""Role authorization: the endpoint's own role list decides, there is no hierarchical override,
and the two entity-backed roles are additionally scoped by the identity in `X-User-ID`."""
from test_helpers import (
    DEFAULTS,
    PATHOLOGIST,
    PATIENT_NAVIGATOR,
    PRACTICE_ADMIN,
    QUALITY_OFFICER,
    REFERRAL_COORDINATOR,
    abort_procedure_payload,
    api_client,
    apply_block_action,
    assert_utc_instant,
    book_slot,
    cancel_booking_payload,
    check_in,
    complete_exam,
    complete_procedure_payload,
    confirm_prep,
    create_anesthesia_coverage_payload,
    create_block,
    create_clinician_payload,
    create_endoscopy_session_payload,
    create_patient_payload,
    create_procedure_booking_payload,
    create_quality_period_payload,
    create_screening_episode_payload,
    create_surveillance_recommendation_payload,
    finalize_report,
    list_blocks,
    list_bookings,
    list_coverage,
    list_quality_periods,
    lock_quality_period,
    make_endoscopist_headers,
    move_clock,
    open_quality_period,
    read_block,
    read_booking,
    read_episode,
    read_quality_period,
    receive_report,
    record_outreach,
    register_anesthesia_clinician,
    register_endoscopist,
    register_patient,
    register_plan,
    session_status_action_payload,
    specimen,
    start_exam,
    validate_error,
    validate_success,
)


def test_a_navigator_is_refused_every_practice_admin_only_write():
    """If the headers are well formed but the named role is not authorized for the endpoint
    being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). Recording
    outreach compares the freshly recomputed score against 3.00: at 3.00 or above the episode
    advances `NOT_STARTED → OUTREACH_ACTIVE` (or holds/returns to `OUTREACH_ACTIVE` from
    `PREP_AT_RISK`), and below 3.00 it moves to `PREP_AT_RISK` — from `NOT_STARTED →
    PREP_AT_RISK` on a first weak touchpoint, or `OUTREACH_ACTIVE → PREP_AT_RISK` when decay
    has eroded a previously adequate score.

    Design: Corner/rbac/patient_navigator_cannot_run_practice_admin_operations
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endoscopist = register_endoscopist()
    anesthetist = register_anesthesia_clinician(max_overlapping_rooms=1)
    patient = register_patient(plan["id"], asa_class=2)

    # Opening an episode is shared with the navigator, so this one succeeds.
    episode = validate_success(
        api_client.create_screening_episode(
            create_screening_episode_payload(patient["id"], "SCREENING_AVERAGE_RISK"),
            PATIENT_NAVIGATOR),
        201)

    block = create_block(endoscopist["id"])
    apply_block_action(block["id"], "PUBLISH")

    validate_error(
        api_client.create_endoscopy_session(
            create_endoscopy_session_payload(
                endoscopist["id"], room_code="ENDO-2", session_date="2026-09-16",
                window_start_utc="2026-09-16T13:00:00Z",
                window_end_utc="2026-09-16T21:00:00Z"),
            PATIENT_NAVIGATOR),
        "ERR_FORBIDDEN_ROLE")
    validate_error(
        api_client.session_status_action(
            block["id"], session_status_action_payload("SUSPEND", "ROOM_MAINTENANCE"),
            PATIENT_NAVIGATOR),
        "ERR_FORBIDDEN_ROLE")
    validate_error(
        api_client.create_anesthesia_coverage(
            block["id"],
            create_anesthesia_coverage_payload(
                anesthetist["id"], "2026-09-15T13:00:00Z", "2026-09-15T21:00:00Z"),
            PATIENT_NAVIGATOR),
        "ERR_FORBIDDEN_ROLE")
    validate_error(
        api_client.set_clock("2026-09-02T00:00:00Z", PATIENT_NAVIGATOR),
        "ERR_FORBIDDEN_ROLE")

    # None of the four refusals left a trace.
    kept = read_block(block["id"])
    assert kept["status"] == "PUBLISHED"
    assert kept["suspension_reason"] is None
    blocks, block_meta = list_blocks()
    assert block_meta["total_count"] == 1
    coverage, coverage_meta = list_coverage()
    assert coverage_meta["total_count"] == 0
    assert coverage == []

    # The clock never moved, so the touchpoint is stamped at the original instant and
    # carries no decay: 3.0 for PHONE, acknowledged, times a decay of 1.00.
    navigated = record_outreach(episode["id"], "PHONE", True)
    assert navigated["navigation_status"] == "OUTREACH_ACTIVE"
    assert navigated["prep_adherence_score"] == 3.00
    assert len(navigated["outreach_log"]) == 1
    assert_utc_instant(navigated["outreach_log"][0]["occurred_at"], "2026-09-01T00:00:00")
    assert navigated["outreach_log"][0]["channel"] == "PHONE"
    assert navigated["outreach_log"][0]["acknowledged"] is True


def test_a_second_endoscopist_may_read_a_booking_but_may_not_work_it():
    """Starting the procedure moves `CHECKED_IN → IN_PROGRESS` and is reserved to the
    `Endoscopist` whose `X-User-ID` equals the booking's `performing_endoscopist_id`; another
    endoscopist is refused with `ERR_NOT_RESOURCE_OWNER`. Concretely, ownership is enforced on
    six operations: reading a single patient record, reading a single screening episode,
    submitting a bowel-preparation attestation, and starting, completing, or aborting a
    procedure.

    Design: Corner/rbac/endoscopist_cannot_act_on_a_peers_booking
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endo_a = register_endoscopist()
    endo_b = register_endoscopist(npi="1000000002", full_name="Dr Cy Vale")
    patient = register_patient(plan["id"], asa_class=2)

    block = create_block(endo_a["id"])
    apply_block_action(block["id"], "PUBLISH")
    episode = validate_success(
        api_client.create_screening_episode(
            create_screening_episode_payload(patient["id"], "SCREENING_AVERAGE_RISK"),
            REFERRAL_COORDINATOR),
        201)
    booking = book_slot(block["id"], episode["id"], endo_a["id"])
    confirm_prep(episode["id"], patient["id"])
    check_in(booking["id"])

    b_headers = make_endoscopist_headers(endo_b["id"])
    validate_error(
        api_client.start_procedure(booking["id"], b_headers), "ERR_NOT_RESOURCE_OWNER")
    validate_error(
        api_client.abort_procedure(
            booking["id"], abort_procedure_payload(3, "INADEQUATE_PREP"), b_headers),
        "ERR_NOT_RESOURCE_OWNER")

    # Reads are not owner-scoped for the Endoscopist role.
    peer_read = validate_success(api_client.get_procedure_booking(booking["id"], b_headers))
    assert peer_read["status"] == "CHECKED_IN"
    assert peer_read["performing_endoscopist_id"] == endo_a["id"]

    started = start_exam(booking["id"], endo_a["id"])
    assert started["status"] == "IN_PROGRESS"

    validate_error(
        api_client.complete_procedure(
            booking["id"], complete_procedure_payload(8, 0, 0, 0), b_headers),
        "ERR_NOT_RESOURCE_OWNER")
    assert read_booking(booking["id"])["status"] == "IN_PROGRESS"

    held = read_episode(episode["id"])
    assert held["clinical_status"] == "PROCEDURE_SCHEDULED"
    assert held["navigation_status"] == "PREP_CONFIRMED"


def test_either_shared_role_may_book_a_slot_and_either_may_cancel_it():
    """If the headers are well formed but the named role is not authorized for the endpoint
    being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). A
    `ReferralCoordinator` or `PracticeAdmin` cancels a booking that is still in `BOOKED`,
    supplying a `cancellation_reason`; the booking moves `BOOKED → CANCELLED`,
    `released_minutes` is set to that booking's `duration_minutes` plus the block's
    `turnover_minutes` — exactly the quantity the booking had consumed, and zero for every
    booking in any other status — and the block's ledger is recomputed so that booked and
    remaining minutes again sum to capacity.

    Design: Corner/rbac/booking_create_and_cancel_are_shared_across_two_roles
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endoscopist = register_endoscopist()
    patient_a = validate_success(
        api_client.create_patient(
            create_patient_payload(plan["id"], mrn="MRN-0001", birth_date="1975-04-10"),
            REFERRAL_COORDINATOR),
        201)
    patient_b = validate_success(
        api_client.create_patient(
            create_patient_payload(plan["id"], mrn="MRN-0002", birth_date="1970-02-02"),
            PRACTICE_ADMIN),
        201)
    episode_a = validate_success(
        api_client.create_screening_episode(
            create_screening_episode_payload(patient_a["id"], "SCREENING_AVERAGE_RISK"),
            REFERRAL_COORDINATOR),
        201)
    episode_b = validate_success(
        api_client.create_screening_episode(
            create_screening_episode_payload(patient_b["id"], "SCREENING_AVERAGE_RISK"),
            PATIENT_NAVIGATOR),
        201)

    block = create_block(endoscopist["id"])
    apply_block_action(block["id"], "PUBLISH")

    version_one = read_block(block["id"])["version"]
    booking_a = validate_success(
        api_client.create_procedure_booking(
            block["id"],
            create_procedure_booking_payload(
                episode_a["id"], endoscopist["id"], version_one,
                "2026-09-15T13:00:00Z", 45),
            REFERRAL_COORDINATOR),
        201)
    assert booking_a["status"] == "BOOKED"

    version_two = read_block(block["id"])["version"]
    booking_b = validate_success(
        api_client.create_procedure_booking(
            block["id"],
            create_procedure_booking_payload(
                episode_b["id"], endoscopist["id"], version_two,
                "2026-09-15T14:00:00Z", 30),
            PRACTICE_ADMIN),
        201)
    assert booking_b["status"] == "BOOKED"

    # 45 + 15 turnover, then 30 + 15 turnover.
    version_three = read_block(block["id"])
    assert version_three["booked_minutes"] == 105

    validate_error(
        api_client.create_procedure_booking(
            block["id"],
            create_procedure_booking_payload(
                episode_b["id"], endoscopist["id"], version_three["version"],
                "2026-09-15T16:00:00Z", 30),
            PATHOLOGIST),
        "ERR_FORBIDDEN_ROLE")
    bookings, booking_meta = list_bookings()
    assert booking_meta["total_count"] == 2

    cancelled = validate_success(
        api_client.cancel_booking(
            booking_a["id"], cancel_booking_payload("PATIENT_RESCHEDULED"), PRACTICE_ADMIN))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["released_minutes"] == 60

    settled = read_block(block["id"])
    assert settled["booked_minutes"] == 45
    assert settled["remaining_minutes"] == 435


def test_the_practice_admin_reads_a_measurement_window_but_never_writes_one():
    """If the headers are well formed but the named role is not authorized for the endpoint
    being called, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).
    `benchmark_result` is then `INSUFFICIENT_VOLUME` when `screening_colonoscopy_count` is
    below the minimum measurable volume of one exam — that is, when it is zero — otherwise
    `MET` when `adr_pct` is at or above `benchmark_pct`, and otherwise `MISSED`.

    Design: Corner/rbac/quality_operations_are_exclusive_to_the_quality_officer
    """
    move_clock("2026-10-01T00:00:00Z")
    endoscopist = register_endoscopist()
    period = open_quality_period(endoscopist["id"], "2026-09-01", "2026-09-30")
    assert period["status"] == "OPEN"

    validate_error(
        api_client.create_quality_period(
            create_quality_period_payload(endoscopist["id"], "2026-10-01", "2026-10-31"),
            PRACTICE_ADMIN),
        "ERR_FORBIDDEN_ROLE")
    validate_error(
        api_client.lock_quality_period(period["id"], PRACTICE_ADMIN), "ERR_FORBIDDEN_ROLE")
    validate_error(
        api_client.create_clinician(
            create_clinician_payload(npi="1000000009", full_name="Dr Di Sato"),
            QUALITY_OFFICER),
        "ERR_FORBIDDEN_ROLE")

    shared_read = validate_success(api_client.get_quality_period(period["id"], PRACTICE_ADMIN))
    assert shared_read["status"] == "OPEN"
    assert shared_read["attribution_basis"] == "PROCEDURE_DATE"

    locked = lock_quality_period(period["id"])
    assert locked["status"] == "LOCKED"
    assert locked["benchmark_result"] == "INSUFFICIENT_VOLUME"

    validate_error(
        api_client.attest_quality_period(
            period["id"], {"remediation_plan": "MONTHLY_WITHDRAWAL_TIME_AUDIT"}, PRACTICE_ADMIN),
        "ERR_FORBIDDEN_ROLE")
    unattested = read_quality_period(period["id"])
    assert unattested["status"] == "LOCKED"
    assert unattested["attesting_user_id"] is None

    periods, period_meta = list_quality_periods()
    assert period_meta["total_count"] == 1

    # The refused clinician create persisted nothing, so the identifier is still free.
    reserved = validate_success(
        api_client.create_clinician(
            create_clinician_payload(npi="1000000009", full_name="Dr Di Sato"), PRACTICE_ADMIN),
        201)
    assert reserved["npi"] == "1000000009"


def test_only_the_acting_identity_separates_the_refused_override_from_the_accepted_one():
    """The segregation rule of Section 2.11 then applies: an override attested by the clinician
    who performed the anchoring procedure is rejected with `ERR_SEGREGATION_OF_DUTIES`, while a
    recommendation with no override carries no such restriction. When an override survives both
    checks, `assigned_interval_months` takes the override value and `basis` is recorded as
    `OVERRIDE_ATTESTED`, with `attesting_endoscopist_id` set to the acting `X-User-ID`; with no
    override, `assigned_interval_months` equals `computed_interval_months`, `basis` is
    `GUIDELINE`, and `attesting_endoscopist_id` stays null.

    Design: Corner/rbac/same_endoscopist_cannot_attest_an_override_of_own_procedure
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endo_a = register_endoscopist()
    endo_b = register_endoscopist(npi="1000000002", full_name="Dr Cy Vale")
    patient = register_patient(plan["id"], asa_class=2)

    block = create_block(endo_a["id"])
    apply_block_action(block["id"], "PUBLISH")
    episode = validate_success(
        api_client.create_screening_episode(
            create_screening_episode_payload(patient["id"], "SCREENING_AVERAGE_RISK"),
            REFERRAL_COORDINATOR),
        201)
    booking = book_slot(block["id"], episode["id"], endo_a["id"])
    confirm_prep(episode["id"], patient["id"])
    check_in(booking["id"])
    start_exam(booking["id"], endo_a["id"])
    complete_exam(booking["id"], endo_a["id"], 8, 1, 7, 1)

    report = receive_report(
        booking["id"], [specimen("A", "TUBULAR_ADENOMA", 7)], DEFAULTS["ACCESSION_NUMBER"])
    finalize_report(report["id"])

    # One 7 mm tubular adenoma with an AVERAGE cap and an adequate prep leaves the
    # guideline interval at the seven-year base.
    cascaded = read_episode(episode["id"])
    assert cascaded["assigned_interval_months"] == 84
    pinned_version = cascaded["version"]

    override = create_surveillance_recommendation_payload(
        pinned_version, pathology_report_id=report["id"], override_interval_months=60,
        override_reason="PIECEMEAL_RESECTION")

    validate_error(
        api_client.create_surveillance_recommendation(
            episode["id"], override, make_endoscopist_headers(endo_a["id"])),
        "ERR_SEGREGATION_OF_DUTIES")
    assert read_episode(episode["id"])["version"] == pinned_version

    accepted = validate_success(
        api_client.create_surveillance_recommendation(
            episode["id"], override, make_endoscopist_headers(endo_b["id"])),
        201)
    assert accepted["basis"] == "OVERRIDE_ATTESTED"
    assert accepted["assigned_interval_months"] == 60
    assert accepted["computed_interval_months"] == 84
    assert accepted["next_due_date"] == "2031-09-15"
    assert accepted["attesting_endoscopist_id"] == endo_b["id"]

    revised = read_episode(episode["id"])
    assert revised["assigned_interval_months"] == 60
    assert revised["due_date"] == "2031-09-15"
    assert revised["version"] == pinned_version + 1
