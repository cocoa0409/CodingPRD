"""Rejection paths: uniqueness scopes, geometry containment, precondition gates and the
precedence between two rules that both fire on the same request."""
from test_helpers import (
    PATHOLOGIST,
    PATIENT_NAVIGATOR,
    PRACTICE_ADMIN,
    QUALITY_OFFICER,
    REFERRAL_COORDINATOR,
    active_recommendation,
    api_client,
    apply_block_action,
    attest_prep,
    book_slot,
    check_in,
    close_episode,
    complete_exam,
    confirm_prep,
    create_anesthesia_coverage_payload,
    create_block,
    create_clinician_payload,
    create_endoscopy_session_payload,
    create_insurance_plan_payload,
    create_patient_payload,
    create_procedure_booking_payload,
    create_quality_period_payload,
    create_screening_episode_payload,
    create_surveillance_recommendation_payload,
    finalize_report,
    list_bookings,
    list_blocks,
    list_coverage,
    list_episodes,
    list_quality_periods,
    make_endoscopist_headers,
    move_clock,
    noninvasive_test_result_payload,
    open_episode,
    open_quality_period,
    order_noninvasive_test,
    post_test_result,
    read_block,
    read_booking,
    read_episode,
    read_noninvasive_test,
    read_patient,
    read_report,
    record_outreach,
    receive_report,
    register_anesthesia_clinician,
    register_endoscopist,
    register_patient,
    register_plan,
    specimen,
    staff_block,
    start_exam,
    submit_referral,
    triage,
    validate_error,
    validate_success,
)

PLAN_P1 = {"deductible_cents": 150000, "diagnostic_coinsurance_pct": 0.20}


def test_uniqueness_is_scoped_to_each_entity_own_identifier_field():
    """A registration whose `plan_code` duplicates an existing plan is rejected with
    `ERR_DUPLICATE_IDENTIFIER`. The submitted record carries an `mrn` of 1 to 32 characters
    that must be unique across all patients — a duplicate is rejected with
    `ERR_DUPLICATE_IDENTIFIER` — a `birth_date` in `YYYY-MM-DD` form, and an
    `insurance_plan_id` naming the plan whose cost-sharing terms will price this patient's
    claims. A clinician is registered with an `npi` of 1 to 20 characters, unique across all
    clinicians, a `full_name`, and a `clinician_type` of either `ENDOSCOPIST` or `ANESTHESIA`.

    Design: Corner/validations/duplicate_mrn_and_duplicate_plan_code_rejected
    """
    plan = register_plan()
    patient = register_patient(plan["id"], mrn="MRN-0001")

    validate_error(
        api_client.create_patient(
            create_patient_payload(plan["id"], mrn="MRN-0001", birth_date="1980-02-02"),
            PRACTICE_ADMIN),
        "ERR_DUPLICATE_IDENTIFIER")
    validate_error(
        api_client.create_insurance_plan(
            create_insurance_plan_payload(plan_code="P1", payer_name="Other Payer"),
            PRACTICE_ADMIN),
        "ERR_DUPLICATE_IDENTIFIER")

    reused_as_npi = validate_success(
        api_client.create_clinician(create_clinician_payload(npi="MRN-0001"), PRACTICE_ADMIN),
        201)
    assert reused_as_npi["npi"] == "MRN-0001"
    assert read_patient(patient["id"])["mrn"] == "MRN-0001"


def test_the_open_episode_ban_keys_on_the_indication_and_lifts_once_the_episode_closes():
    """A patient may not hold two live episodes with the same `indication` at once: if another
    episode for the same patient with the same `indication` has a `clinical_status` of `OPEN`,
    `PROCEDURE_SCHEDULED`, or `PATHOLOGY_PENDING`, the creation is rejected with
    `ERR_DUPLICATE_OPEN_EPISODE`.

    A `PatientNavigator` or `ReferralCoordinator` may close an `OPEN` episode by supplying a
    `reason` of `PATIENT_DECLINED`, `LOST_TO_FOLLOW_UP`, or `SUPERSEDED_BY_OTHER_PATHWAY`; the
    reason is stored in `closure_reason`, the first two both drive `OPEN → CLOSED_DECLINED` and
    the third drives `OPEN → CLOSED_SUPERSEDED`, and in every case the patient's
    `open_episode_count` and `navigation_priority` are recomputed afterwards.

    Design: Corner/validations/duplicate_open_episode_is_scoped_to_the_indication
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    patient = register_patient(plan["id"])
    first = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")

    validate_error(
        api_client.create_screening_episode(
            create_screening_episode_payload(patient["id"], "SCREENING_AVERAGE_RISK"),
            REFERRAL_COORDINATOR),
        "ERR_DUPLICATE_OPEN_EPISODE")

    surveillance = open_episode(patient["id"], "SURVEILLANCE")
    assert surveillance["eligibility_status"] == "ELIGIBLE"

    closed = close_episode(first["id"], "PATIENT_DECLINED")
    assert closed["clinical_status"] == "CLOSED_DECLINED"
    assert closed["closure_reason"] == "PATIENT_DECLINED"

    reopened = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    assert reopened["id"] != first["id"]
    assert read_patient(patient["id"])["open_episode_count"] == 2


def test_the_out_of_range_override_is_reported_before_the_self_attestation():
    """The supplied `override_interval_months` must be at least 6 and at most 120, must differ
    from `computed_interval_months` by no more than 48 months in either direction, and must be
    accompanied by a non-empty `override_reason`; a violation of any of those three conditions
    is rejected with `ERR_OVERRIDE_OUT_OF_RANGE` (HTTP 422). The segregation rule of Section
    2.11 then applies: an override attested by the clinician who performed the anchoring
    procedure is rejected with `ERR_SEGREGATION_OF_DUTIES`, while a recommendation with no
    override carries no such restriction. When an override survives both checks,
    `assigned_interval_months` takes the override value and `basis` is recorded as
    `OVERRIDE_ATTESTED`, with `attesting_endoscopist_id` set to the acting `X-User-ID`; with no
    override, `assigned_interval_months` equals `computed_interval_months`, `basis` is
    `GUIDELINE`, and `attesting_endoscopist_id` stays null.

    Design: Corner/validations/override_range_beats_segregation_of_duties
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan(**PLAN_P1)
    performer = register_endoscopist()
    attester = register_endoscopist(npi="1000000002", full_name="Dr Cy Okafor")
    patient = register_patient(plan["id"])
    block = create_block(performer["id"])
    apply_block_action(block["id"], "PUBLISH")
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    booking = book_slot(block["id"], episode["id"], performer["id"])
    confirm_prep(episode["id"], patient["id"])
    check_in(booking["id"])
    start_exam(booking["id"], performer["id"])
    complete_exam(booking["id"], performer["id"], prep_quality_bbps=8,
                  polyps_removed_count=1, largest_polyp_mm=7, specimen_count=1)
    report = receive_report(booking["id"], [specimen("A", "TUBULAR_ADENOMA", 7)])
    finalize_report(report["id"])

    closed = read_episode(episode["id"])
    assert closed["assigned_interval_months"] == 84
    pinned = closed["version"]

    def attempt(months, headers):
        return api_client.create_surveillance_recommendation(
            episode["id"],
            create_surveillance_recommendation_payload(
                pinned, pathology_report_id=report["id"],
                override_interval_months=months, override_reason="PATIENT_PREFERENCE"),
            headers)

    validate_error(attempt(140, make_endoscopist_headers(performer["id"])),
                   "ERR_OVERRIDE_OUT_OF_RANGE")
    validate_error(attempt(6, make_endoscopist_headers(performer["id"])),
                   "ERR_OVERRIDE_OUT_OF_RANGE")
    validate_error(attempt(40, make_endoscopist_headers(performer["id"])),
                   "ERR_SEGREGATION_OF_DUTIES")

    accepted = validate_success(attempt(40, make_endoscopist_headers(attester["id"])), 201)
    assert accepted["computed_interval_months"] == 84
    assert accepted["assigned_interval_months"] == 40
    assert accepted["basis"] == "OVERRIDE_ATTESTED"
    assert accepted["next_due_date"] == "2030-01-15"
    assert accepted["attesting_endoscopist_id"] == attester["id"]

    after = read_episode(episode["id"])
    assert after["assigned_interval_months"] == 40
    assert after["due_date"] == "2030-01-15"


def test_containment_is_checked_on_the_occupancy_interval_not_on_the_slot():
    """First, `slot_end_utc` is derived as `slot_start_utc` advanced by `duration_minutes`, and
    `occupancy_end_utc` as `slot_end_utc` advanced by the block's `turnover_minutes`; the whole
    occupancy interval, turnover included, must sit inside the block window — `slot_start_utc` at
    or after `window_start_utc` and `occupancy_end_utc` at or before `window_end_utc` — else the
    request is rejected with `ERR_SLOT_OUTSIDE_SESSION_WINDOW` (HTTP 422).

    Design: Corner/validations/slot_must_fit_the_window_including_turnover
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endoscopist = register_endoscopist()
    patient = register_patient(plan["id"])
    block = create_block(endoscopist["id"], turnover_minutes=15)
    published = apply_block_action(block["id"], "PUBLISH")
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")

    validate_error(
        api_client.create_procedure_booking(
            block["id"],
            create_procedure_booking_payload(
                episode["id"], endoscopist["id"], published["version"],
                "2026-09-15T20:30:00Z", 45),
            REFERRAL_COORDINATOR),
        "ERR_SLOT_OUTSIDE_SESSION_WINDOW")

    untouched = read_block(block["id"])
    assert untouched["booked_minutes"] == 0
    assert untouched["version"] == published["version"]

    booking = validate_success(
        api_client.create_procedure_booking(
            block["id"],
            create_procedure_booking_payload(
                episode["id"], endoscopist["id"], published["version"],
                "2026-09-15T20:00:00Z", 45),
            REFERRAL_COORDINATOR),
        201)
    assert booking["slot_end_utc"][:19] == "2026-09-15T20:45:00"
    assert booking["occupancy_end_utc"][:19] == "2026-09-15T21:00:00"

    after = read_block(block["id"])
    assert after["booked_minutes"] == 60
    assert after["remaining_minutes"] == 420


def test_partial_coverage_is_refused_outright_rather_than_stored_as_not_full():
    """First, the coverage must fully span the block: `covers_full_window` is true exactly when
    `coverage_start_utc` is at or before the block's `window_start_utc` **and**
    `coverage_end_utc` is at or after the block's `window_end_utc`; when it is false the
    assignment is rejected with `ERR_COVERAGE_WINDOW_INSUFFICIENT` (HTTP 422). Partial coverage
    of an endoscopy block is not a thing this practice does.

    Design: Corner/validations/coverage_must_span_the_whole_session_window
    """
    move_clock("2026-09-01T00:00:00Z")
    endoscopist = register_endoscopist()
    anesthetist = register_anesthesia_clinician(max_overlapping_rooms=1)
    block = create_block(endoscopist["id"], anesthesia_mode="MAC")
    published = apply_block_action(block["id"], "PUBLISH")
    assert published["status"] == "PUBLISHED"

    validate_error(
        api_client.create_anesthesia_coverage(
            block["id"],
            create_anesthesia_coverage_payload(
                anesthetist["id"], "2026-09-15T13:00:00Z", "2026-09-15T20:00:00Z"),
            PRACTICE_ADMIN),
        "ERR_COVERAGE_WINDOW_INSUFFICIENT")

    rows, meta = list_coverage({"session_id": block["id"]})
    assert meta["total_count"] == 0
    assert rows == []

    coverage = staff_block(block["id"], anesthetist["id"],
                           coverage_start_utc="2026-09-15T12:30:00Z",
                           coverage_end_utc="2026-09-15T21:30:00Z")
    assert coverage["covers_full_window"] is True
    assert read_block(block["id"])["status"] == "COVERAGE_CONFIRMED"


def test_the_same_calendar_month_may_be_measured_twice_under_two_bases():
    """The requested window may not intersect an existing window that has both the same
    `endoscopist_id` **and** the same `attribution_basis`; such a collision is rejected with
    `ERR_QUALITY_PERIOD_OVERLAP` (HTTP 409). Windows that differ in `attribution_basis` may
    overlap freely — indeed, measuring the same calendar month both ways is the point.

    A new window begins in `status` `OPEN` with `screening_colonoscopy_count` and
    `adenoma_positive_count` at 0, `remediation_required` false, and `adr_pct`, `benchmark_pct`,
    `benchmark_result`, `remediation_plan`, and `attesting_user_id` all empty.

    Design: Corner/validations/quality_period_overlap_is_scoped_to_the_attribution_basis
    """
    endoscopist = register_endoscopist(adr_benchmark_pct=0.25)
    september = open_quality_period(endoscopist["id"], "2026-09-01", "2026-09-30",
                                   attribution_basis="PROCEDURE_DATE")

    validate_error(
        api_client.create_quality_period(
            create_quality_period_payload(endoscopist["id"], "2026-09-15", "2026-10-15",
                                          attribution_basis="PROCEDURE_DATE"),
            QUALITY_OFFICER),
        "ERR_QUALITY_PERIOD_OVERLAP")

    other_basis = open_quality_period(endoscopist["id"], "2026-09-01", "2026-09-30",
                                      attribution_basis="PATHOLOGY_FINALIZATION_DATE")
    assert other_basis["attribution_basis"] == "PATHOLOGY_FINALIZATION_DATE"

    october = open_quality_period(endoscopist["id"], "2026-10-01", "2026-10-31",
                                  attribution_basis="PROCEDURE_DATE")

    for period in (september, other_basis, october):
        assert period["status"] == "OPEN"
        assert period["screening_colonoscopy_count"] == 0


def test_check_in_reads_the_navigation_dimension_and_not_the_booking_status():
    """A `PatientNavigator` checks the patient in, moving `BOOKED → CHECKED_IN`, and this is the
    gate the navigation dimension guards: the episode's `navigation_status` must be
    `PREP_CONFIRMED`, else the check-in is rejected with `ERR_PREP_NOT_CONFIRMED` (HTTP 422).
    Check-in makes no change to the minute ledger, because the room minutes were committed at
    booking time.

    Design: Corner/validations/check_in_rejected_until_prep_is_confirmed
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endoscopist = register_endoscopist()
    patient = register_patient(plan["id"])
    block = create_block(endoscopist["id"])
    apply_block_action(block["id"], "PUBLISH")
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    booking = book_slot(block["id"], episode["id"], endoscopist["id"])

    validate_error(api_client.check_in_booking(booking["id"], PATIENT_NAVIGATOR),
                   "ERR_PREP_NOT_CONFIRMED")
    assert read_booking(booking["id"])["status"] == "BOOKED"

    reached = record_outreach(episode["id"], "PHONE", True)
    assert reached["prep_adherence_score"] == 3.00
    assert reached["navigation_status"] == "OUTREACH_ACTIVE"

    attested = attest_prep(episode["id"], patient["id"], True)
    assert attested["prep_adherence_score"] == 5.50
    assert attested["navigation_status"] == "PREP_CONFIRMED"
    assert attested["prep_attestation"] == "COMPLETED"

    assert check_in(booking["id"])["status"] == "CHECKED_IN"
    assert read_block(block["id"])["booked_minutes"] == 60


def test_a_suspended_credential_only_bites_at_the_moment_of_the_start():
    """That clinician's `credential_status` must be `ACTIVE` — a `SUSPENDED` credential is
    rejected with `ERR_CLINICIAN_CREDENTIAL_SUSPENDED` (HTTP 422) — and when the block's
    `anesthesia_mode` is `MAC`, the block's `status` must be `COVERAGE_CONFIRMED` at the moment of
    the start, else the request is rejected with `ERR_ANESTHESIA_COVERAGE_REQUIRED` (HTTP 409).

    Design: Corner/validations/suspended_credential_blocks_procedure_start
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endoscopist = register_endoscopist(credential_status="SUSPENDED")
    assert endoscopist["credential_status"] == "SUSPENDED"
    patient = register_patient(plan["id"])
    block = create_block(endoscopist["id"])
    apply_block_action(block["id"], "PUBLISH")
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    booking = book_slot(block["id"], episode["id"], endoscopist["id"])
    confirm_prep(episode["id"], patient["id"])
    assert check_in(booking["id"])["status"] == "CHECKED_IN"

    validate_error(
        api_client.start_procedure(booking["id"], make_endoscopist_headers(endoscopist["id"])),
        "ERR_CLINICIAN_CREDENTIAL_SUSPENDED")

    assert read_booking(booking["id"])["status"] == "CHECKED_IN"
    assert read_episode(episode["id"])["clinical_status"] == "PROCEDURE_SCHEDULED"


def test_a_resulted_test_refuses_a_second_posting_and_never_runs_the_cascade():
    """Only a `Pathologist` may post a laboratory outcome, and only once: the submitted `result`
    must be one of `NEGATIVE`, `POSITIVE`, or `INSUFFICIENT_SPECIMEN`, and a test whose `result`
    is no longer `PENDING` rejects a second posting with `ERR_TEST_ALREADY_RESULTED`. Posting a
    result stamps `resulted_at` from the logical clock in every case.

    Design: Corner/validations/noninvasive_test_cannot_be_resulted_twice
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    patient = register_patient(plan["id"])
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    test = order_noninvasive_test(episode["id"], "FIT", "2026-09-01")
    assert test["result"] == "PENDING"
    assert test["follow_up_episode_id"] is None

    negative = post_test_result(test["id"], "NEGATIVE")
    assert negative["result"] == "NEGATIVE"
    assert negative["resulted_at"] == "2026-09-01T00:00:00.000Z"

    validate_error(
        api_client.post_noninvasive_test_result(
            test["id"], noninvasive_test_result_payload("POSITIVE"), PATHOLOGIST),
        "ERR_TEST_ALREADY_RESULTED")

    unchanged = read_noninvasive_test(test["id"])
    assert unchanged["result"] == "NEGATIVE"
    assert unchanged["follow_up_episode_id"] is None
    assert read_patient(patient["id"])["open_episode_count"] == 1


def test_an_empty_report_is_storable_but_neither_finalizable_nor_visible_to_the_aggregate():
    """The `specimens` list may be empty only while the report sits in `RECEIVED`. Finalizing a
    report whose `specimens` list is empty is rejected with `ERR_NO_SPECIMENS` (HTTP 422) — the
    practice will not close a surveillance interval on a report with nothing in it.

    Design: Corner/validations/finalize_with_no_specimens_is_rejected
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan(**PLAN_P1)
    endoscopist = register_endoscopist()
    patient = register_patient(plan["id"])
    block = create_block(endoscopist["id"])
    apply_block_action(block["id"], "PUBLISH")
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    booking = book_slot(block["id"], episode["id"], endoscopist["id"])
    confirm_prep(episode["id"], patient["id"])
    check_in(booking["id"])
    start_exam(booking["id"], endoscopist["id"])
    complete_exam(booking["id"], endoscopist["id"], prep_quality_bbps=8,
                  polyps_removed_count=1, largest_polyp_mm=7, specimen_count=1)

    empty = receive_report(booking["id"], [], accession_number="ACC-EMPTY")
    assert empty["status"] == "RECEIVED"
    assert empty["adenoma_count"] == 0

    validate_error(api_client.finalize_pathology_report(empty["id"], PATHOLOGIST),
                   "ERR_NO_SPECIMENS")
    assert read_report(empty["id"])["finalized_at"] is None

    real = receive_report(booking["id"], [specimen("A", "TUBULAR_ADENOMA", 7)],
                          accession_number="ACC-0001")
    assert finalize_report(real["id"])["status"] == "FINALIZED"

    recommendation = active_recommendation(episode["id"])
    assert recommendation["computed_interval_months"] == 84
    assert recommendation["next_due_date"] == "2033-09-15"
    assert read_episode(episode["id"])["clinical_status"] == "CLOSED_SURVEILLANCE_SET"


def test_a_submitted_referral_is_a_resolvable_link_but_not_an_accepted_one():
    """When a `referral_id` is supplied, that referral's `status` must be either
    `ACCEPTED_OPEN_ACCESS` or `ACCEPTED_OFFICE_VISIT`; anything else is rejected with
    `ERR_REFERRAL_NOT_ACCEPTED`. It is `REFERRAL` whenever `referral_id` is set.

    Design: Corner/validations/episode_create_rejected_while_referral_is_not_accepted
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    patient = register_patient(plan["id"])
    referral = submit_referral(patient["id"], referring_provider_npi="3000000001",
                               reason="FAMILY_HISTORY", asa_class_reported=2)

    validate_error(
        api_client.create_screening_episode(
            create_screening_episode_payload(patient["id"], "SCREENING_AVERAGE_RISK",
                                             referral_id=referral["id"]),
            REFERRAL_COORDINATOR),
        "ERR_REFERRAL_NOT_ACCEPTED")
    assert list_episodes({"patient_id": patient["id"]})[1]["total_count"] == 0

    screened = triage(referral["id"], "BEGIN_TRIAGE")
    assert screened["risk_screen_result"] == "CLEARED_OPEN_ACCESS"
    accepted = triage(referral["id"], "ACCEPT_OPEN_ACCESS")
    assert accepted["status"] == "ACCEPTED_OPEN_ACCESS"

    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK",
                           referral_id=referral["id"])
    assert episode["origin"] == "REFERRAL"
    assert episode["eligibility_status"] == "ELIGIBLE"
    assert episode["referral_id"] == referral["id"]
    assert episode["due_date"] == "2027-02-28"


def test_the_type_check_guards_three_reference_slots_in_both_directions():
    """Only an `ENDOSCOPIST` row may lead a room block, perform a booking, or be the subject of a
    quality measurement window; only an `ANESTHESIA` row may hold anesthesia coverage. Using one
    where the other is required is rejected with `ERR_CLINICIAN_TYPE_MISMATCH`, and that check
    applies to four write operations: room-block creation validating `lead_endoscopist_id`,
    coverage assignment validating `anesthesia_clinician_id`, booking creation validating
    `performing_endoscopist_id`, and measurement-window creation validating `endoscopist_id`.

    Design: Corner/validations/clinician_type_mismatch_rejected_in_both_directions
    """
    move_clock("2026-09-01T00:00:00Z")
    endoscopist = register_endoscopist()
    anesthetist = register_anesthesia_clinician(max_overlapping_rooms=1)
    block = create_block(endoscopist["id"], anesthesia_mode="MAC")
    apply_block_action(block["id"], "PUBLISH")

    validate_error(
        api_client.create_endoscopy_session(
            create_endoscopy_session_payload(
                anesthetist["id"], room_code="ENDO-2", session_date="2026-09-16",
                window_start_utc="2026-09-16T13:00:00Z",
                window_end_utc="2026-09-16T21:00:00Z"),
            PRACTICE_ADMIN),
        "ERR_CLINICIAN_TYPE_MISMATCH")
    validate_error(
        api_client.create_anesthesia_coverage(
            block["id"],
            create_anesthesia_coverage_payload(
                endoscopist["id"], "2026-09-15T13:00:00Z", "2026-09-15T21:00:00Z"),
            PRACTICE_ADMIN),
        "ERR_CLINICIAN_TYPE_MISMATCH")
    validate_error(
        api_client.create_quality_period(
            create_quality_period_payload(anesthetist["id"], "2026-09-01", "2026-09-30"),
            QUALITY_OFFICER),
        "ERR_CLINICIAN_TYPE_MISMATCH")

    assert list_blocks()[1]["total_count"] == 1
    assert list_coverage()[1]["total_count"] == 0
    assert list_quality_periods()[1]["total_count"] == 0
    assert read_block(block["id"])["status"] == "PUBLISHED"


def test_authorization_is_decided_before_any_path_identifier_is_resolved():
    """Role authorization against the endpoint's role list — `ERR_FORBIDDEN_ROLE`.
    Path-parameter resolution, evaluated left to right along the URL — the not-found error
    naming the segment that failed to resolve.

    Design: Corner/validations/forbidden_role_beats_unknown_path_id
    """
    endoscopist = register_endoscopist()
    block = create_block(endoscopist["id"])
    published = apply_block_action(block["id"], "PUBLISH")

    validate_error(
        api_client.create_procedure_booking(
            "00000000-0000-4000-8000-000000000000",
            create_procedure_booking_payload(
                "00000000-0000-4000-8000-000000000001", endoscopist["id"],
                published["version"], "2026-09-15T13:00:00Z", 45),
            PATIENT_NAVIGATOR),
        "ERR_FORBIDDEN_ROLE")

    assert list_bookings()[1]["total_count"] == 0
    assert read_block(block["id"])["version"] == published["version"]


def test_the_asa_four_block_is_waived_by_an_office_visit_referral():
    """A patient whose `asa_class` is 4 or 5 may not be slotted straight into the suite; such a
    booking is permitted only when the episode carries a `referral_id` whose referral reached
    `ACCEPTED_OFFICE_VISIT`, evidencing that the patient was seen in clinic first. Otherwise the
    booking is rejected with `ERR_PREPROCEDURE_RISK_UNCLEARED` (HTTP 422). A patient with
    `asa_class` of 3 or below clears this rule unconditionally.

    Design: Corner/validations/office_visit_referral_waives_the_asa_four_block
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endoscopist = register_endoscopist()
    patient = register_patient(plan["id"], asa_class=4)
    assert patient["asa_class"] == 4

    referral = submit_referral(patient["id"], referring_provider_npi="3000000001",
                               reason="FAMILY_HISTORY", asa_class_reported=4)
    screened = triage(referral["id"], "BEGIN_TRIAGE")
    assert screened["risk_screen_result"] == "OFFICE_VISIT_REQUIRED"
    cleared = triage(referral["id"], "ACCEPT_OFFICE_VISIT", note="ANESTHESIA_CONSULT_DONE")
    assert cleared["status"] == "ACCEPTED_OFFICE_VISIT"

    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK",
                           referral_id=referral["id"])
    assert episode["origin"] == "REFERRAL"

    block = create_block(endoscopist["id"])
    apply_block_action(block["id"], "PUBLISH")
    booking = book_slot(block["id"], episode["id"], endoscopist["id"])
    assert booking["status"] == "BOOKED"
    assert booking["planned_classification"] == "SCREENING_PREVENTIVE"
    assert read_episode(episode["id"])["clinical_status"] == "PROCEDURE_SCHEDULED"
    assert read_block(block["id"])["booked_minutes"] == 60
