"""Declared transitions, undeclared transitions and terminal lockdown across the machines."""
from test_helpers import (
    BILLING_SPECIALIST,
    PATHOLOGIST,
    PRACTICE_ADMIN,
    QUALITY_OFFICER,
    REFERRAL_COORDINATOR,
    amend_pathology_report_payload,
    api_client,
    apply_block_action,
    attest_quality_period,
    book_slot,
    cancel_slot,
    check_in,
    claim_for_booking,
    complete_exam,
    complete_procedure_payload,
    confirm_prep,
    create_block,
    create_referral_payload,
    list_recommendations,
    lock_quality_period,
    make_endoscopist_headers,
    move_clock,
    open_episode,
    open_quality_period,
    read_block,
    read_claim,
    read_quality_period,
    read_coverage,
    read_episode,
    read_patient,
    read_report,
    receive_report,
    register_anesthesia_clinician,
    register_endoscopist,
    register_patient,
    register_plan,
    release_coverage,
    finalize_report,
    specimen,
    staff_block,
    start_exam,
    validate_error,
    validate_success,
)

PLAN_P1 = {
    "plan_code": "P1",
    "payer_name": "Meridian Health",
    "deductible_cents": 150000,
    "diagnostic_coinsurance_pct": 0.20,
}


def _in_progress_moderate_sedation_booking():
    """A published moderate-sedation block holding one 45-minute booking that has been
    checked in and started."""
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan(**PLAN_P1)
    endoscopist = register_endoscopist()
    patient = register_patient(plan["id"])
    block = create_block(endoscopist["id"])
    apply_block_action(block["id"], "PUBLISH")
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    booking = book_slot(block["id"], episode["id"], endoscopist["id"],
                        slot_start_utc="2026-09-15T13:00:00Z", duration_minutes=45)
    confirm_prep(episode["id"], patient["id"])
    check_in(booking["id"])
    start_exam(booking["id"], endoscopist["id"])
    return {
        "patient_id": patient["id"],
        "block_id": block["id"],
        "episode_id": episode["id"],
        "endoscopist_id": endoscopist["id"],
        "booking_id": booking["id"],
        "claim_id": claim_for_booking(booking["id"])["id"],
    }


def _received_report_on_a_pathology_pending_episode():
    """The same chain carried through completion with one specimen, so a report sits in
    `RECEIVED` against a `PATHOLOGY_PENDING` episode."""
    scenario = _in_progress_moderate_sedation_booking()
    complete_exam(scenario["booking_id"], scenario["endoscopist_id"], prep_quality_bbps=8,
                  polyps_removed_count=1, largest_polyp_mm=7, specimen_count=1)
    report = receive_report(scenario["booking_id"],
                            [specimen("A", "TUBULAR_ADENOMA", 7)])
    scenario["report"] = report
    return scenario


def test_publishing_covering_and_closing_a_block_walks_three_transitions():
    """`PUBLISH` moves `DRAFT → PUBLISHED` and sets `remaining_minutes` equal to
    `capacity_minutes`, opening the block for booking.

    Accepting a fully covering row against a block in `PUBLISHED` advances that block
    `PUBLISHED → COVERAGE_CONFIRMED`, and increments the block's `version` by 1.

    Closing the block also releases every one of its `ACTIVE` anesthesia coverage rows to
    `RELEASED`, which immediately frees those intervals from the covering clinician's
    supervision load.

    Design: Corner/state_machines/session_publish_cover_and_close_path
    """
    move_clock("2026-09-01T00:00:00Z")
    endoscopist = register_endoscopist()
    anesthetist = register_anesthesia_clinician(max_overlapping_rooms=1)
    block = create_block(endoscopist["id"], anesthesia_mode="MAC", turnover_minutes=15,
                         max_procedures=8)
    assert block["capacity_minutes"] == 480
    assert block["remaining_minutes"] == 480

    published = apply_block_action(block["id"], "PUBLISH")
    assert published["status"] == "PUBLISHED"
    assert published["capacity_minutes"] == 480
    assert published["remaining_minutes"] == 480
    assert published["version"] > 1

    coverage = staff_block(block["id"], anesthetist["id"])
    assert coverage["covers_full_window"] is True
    assert coverage["overlap_index"] == 1
    assert coverage["status"] == "ACTIVE"
    assert read_block(block["id"])["status"] == "COVERAGE_CONFIRMED"

    closed = apply_block_action(block["id"], "CLOSE")
    assert closed["status"] == "CLOSED"
    assert read_coverage(coverage["id"])["status"] == "RELEASED"


def test_closing_a_block_over_a_live_booking_is_refused_until_the_slot_is_cancelled():
    """`CLOSE` may be applied from `PUBLISHED`, `COVERAGE_CONFIRMED`, or `SUSPENDED`, but only
    when no booking on the block is still in `BOOKED`, `CHECKED_IN`, or `IN_PROGRESS`; an
    attempt to close over live work is rejected with `ERR_INVALID_SESSION_STATE`.

    Design: Corner/state_machines/session_close_blocked_by_an_active_booking
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endoscopist = register_endoscopist()
    patient = register_patient(plan["id"])
    block = create_block(endoscopist["id"])
    apply_block_action(block["id"], "PUBLISH")
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    booking = book_slot(block["id"], episode["id"], endoscopist["id"],
                        slot_start_utc="2026-09-15T13:00:00Z", duration_minutes=45)

    validate_error(
        api_client.session_status_action(block["id"], {"action": "CLOSE"}, PRACTICE_ADMIN),
        "ERR_INVALID_SESSION_STATE")
    assert read_block(block["id"])["status"] == "PUBLISHED"

    cancel_slot(booking["id"], "PATIENT_RESCHEDULED")
    after_cancel = read_block(block["id"])
    assert after_cancel["booked_minutes"] == 0
    assert after_cancel["remaining_minutes"] == 480

    assert apply_block_action(block["id"], "CLOSE")["status"] == "CLOSED"


def test_amending_a_report_that_has_never_been_finalized_is_refused():
    """Finalization is admitted from `RECEIVED` or from `AMENDED`; amendment is admitted only
    from `FINALIZED`; anything else is rejected with `ERR_INVALID_PATHOLOGY_STATE`.

    Design: Corner/state_machines/pathology_amend_from_received_is_rejected
    """
    scenario = _received_report_on_a_pathology_pending_episode()
    assert scenario["report"]["status"] == "RECEIVED"

    validate_error(
        api_client.amend_pathology_report(
            scenario["report"]["id"],
            amend_pathology_report_payload([specimen("A", "TUBULAR_ADENOMA", 9)],
                                           "SIZE_CORRECTION"),
            PATHOLOGIST),
        "ERR_INVALID_PATHOLOGY_STATE")

    unchanged = read_report(scenario["report"]["id"])
    assert unchanged["amendment_count"] == 0
    assert unchanged["largest_adenoma_mm"] == 7
    assert read_episode(scenario["episode_id"])["clinical_status"] == "PATHOLOGY_PENDING"


def test_replaying_finalize_on_a_finalized_report_is_refused_and_the_cascade_runs_once():
    """Hop four: because the episode has closed, the booking's `BillingClaim` is repriced under
    the final pricing pass, moving `PROVISIONAL_PRICED → REPRICED`, incrementing the claim's
    `reprice_count`, and writing the booking's `final_classification`.

    Hop two: because the report is now finalized, a `SurveillanceRecommendation` is created
    with `basis` `GUIDELINE` from the finalized-pathology aggregate, and any recommendation on
    that episode that was previously `ACTIVE` becomes `SUPERSEDED`, since only one
    recommendation per episode may be `ACTIVE` at a time.

    Design: Corner/state_machines/second_finalize_of_a_finalized_report_is_rejected
    """
    scenario = _received_report_on_a_pathology_pending_episode()
    assert finalize_report(scenario["report"]["id"])["status"] == "FINALIZED"

    validate_error(
        api_client.finalize_pathology_report(scenario["report"]["id"], PATHOLOGIST),
        "ERR_INVALID_PATHOLOGY_STATE")

    rows, meta = list_recommendations({"episode_id": scenario["episode_id"]})
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "ACTIVE"

    claim = read_claim(scenario["claim_id"])
    assert claim["reprice_count"] == 1
    assert claim["status"] == "REPRICED"


def test_six_machines_are_born_in_their_declared_initial_states():
    """A new referral begins with `status` `SUBMITTED`, `info_request_rounds` at 0, and
    `risk_screen_result` at `PENDING`. A new block is created in `status` `DRAFT` with
    `suspension_reason` null, and `capacity_minutes` is computed from the window as the whole
    number of minutes between `window_start_utc` and `window_end_utc`. `clinical_status` tracks
    the clinical pathway and takes the values `OPEN`, `PROCEDURE_SCHEDULED`,
    `PATHOLOGY_PENDING`, `CLOSED_SURVEILLANCE_SET`, `CLOSED_DECLINED`, and `CLOSED_SUPERSEDED`,
    beginning at `OPEN`, with `CLOSED_DECLINED` and `CLOSED_SUPERSEDED` terminal.
    `navigation_status` tracks bowel-preparation navigation and takes the values `NOT_STARTED`,
    `OUTREACH_ACTIVE`, `PREP_AT_RISK`, `PREP_CONFIRMED`, and `NAVIGATION_COMPLETE`, beginning
    at `NOT_STARTED`, with `NAVIGATION_COMPLETE` terminal. Once accepted, the booking is
    created in `status` `BOOKED` with `released_minutes` at 0 and `prep_quality_bbps`,
    `polyps_removed_count`, `largest_polyp_mm`, `specimen_count`, `final_classification`, and
    `cancellation_reason` all still empty. A `BillingClaim` is created when a booking is
    created, records the `booking_id` it prices and the `insurance_plan_id` copied from the
    patient at booking time as the plan snapshot used for pricing, and begins in `status`
    `PROVISIONAL_PRICED` with `variant` `PROVISIONAL` and `reprice_count` at 0.

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endoscopist = register_endoscopist()
    patient = register_patient(plan["id"])

    referral = validate_success(
        api_client.create_referral(create_referral_payload(patient["id"]),
                                   REFERRAL_COORDINATOR), 201)
    assert referral["status"] == "SUBMITTED"

    block = create_block(endoscopist["id"])
    assert block["status"] == "DRAFT"

    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    assert episode["clinical_status"] == "OPEN"
    assert episode["navigation_status"] == "NOT_STARTED"
    assert episode["prep_adherence_score"] == 0.00

    apply_block_action(block["id"], "PUBLISH")
    booking = book_slot(block["id"], episode["id"], endoscopist["id"],
                        slot_start_utc="2026-09-15T13:00:00Z", duration_minutes=45)
    assert booking["status"] == "BOOKED"
    assert booking["released_minutes"] == 0

    claim = claim_for_booking(booking["id"])
    assert claim["status"] == "PROVISIONAL_PRICED"
    assert claim["variant"] == "PROVISIONAL"
    assert claim["reprice_count"] == 0

    period = open_quality_period(endoscopist["id"], "2026-09-01", "2026-09-30")
    assert period["status"] == "OPEN"


def test_an_attested_measurement_window_refuses_both_of_its_triggers():
    """Attesting a locked window moves `LOCKED → ATTESTED`, requires a `remediation_plan` —
    omitting it is `ERR_INVALID_REQUEST` — stores that plan text, and records the acting
    `X-User-ID` in `attesting_user_id`.

    Measurement-window state admissibility — `ERR_INVALID_QUALITY_PERIOD_STATE`.

    Design: Corner/state_machines/attested_quality_period_admits_no_further_actions
    """
    move_clock("2026-09-30T00:00:00Z")
    endoscopist = register_endoscopist(adr_benchmark_pct=0.25)
    period = open_quality_period(endoscopist["id"], "2026-09-01", "2026-09-30")
    assert lock_quality_period(period["id"])["status"] == "LOCKED"

    attested = attest_quality_period(period["id"], "NONE_REQUIRED_INSUFFICIENT_VOLUME")
    assert attested["status"] == "ATTESTED"
    assert attested["attesting_user_id"] == QUALITY_OFFICER["X-User-ID"]

    validate_error(api_client.lock_quality_period(period["id"], QUALITY_OFFICER),
                   "ERR_INVALID_QUALITY_PERIOD_STATE")
    validate_error(
        api_client.attest_quality_period(period["id"],
                                         {"remediation_plan": "SECOND_ATTEMPT"},
                                         QUALITY_OFFICER),
        "ERR_INVALID_QUALITY_PERIOD_STATE")

    assert read_quality_period(period["id"])["remediation_plan"] == (
        "NONE_REQUIRED_INSUFFICIENT_VOLUME")


def test_an_abort_collapses_the_claim_to_a_technical_line_and_keeps_the_minutes_committed():
    """One override replaces that whole schedule: when the booking's `status` is
    `ABORTED_INADEQUATE_PREP`, `line_items` becomes a single line with `code`
    `ABORTED_TECHNICAL` allowed a flat 30000 cents. Crucially, **an abort releases no room
    minutes**: `booked_minutes` is left as it stands, because the room really was occupied. The
    tier carries an addon of 0 cents for `TIER_1`, 8500 cents for `TIER_2`, and 19000 cents for
    `TIER_3`; the addon is added to the `allowed_cents` of the first line in the array, and
    `allowed_amount_cents` becomes `base_allowed_cents` plus the addon.

    Design: Corner/state_machines/abort_reprices_to_a_technical_fee_without_releasing_minutes
    """
    scenario = _in_progress_moderate_sedation_booking()
    provisional = read_claim(scenario["claim_id"])
    assert provisional["allowed_amount_cents"] == 170750
    assert provisional["complexity_tier"] == "TIER_2"

    aborted = validate_success(
        api_client.abort_procedure(
            scenario["booking_id"],
            {"prep_quality_bbps": 3, "cancellation_reason": "INADEQUATE_PREP"},
            make_endoscopist_headers(scenario["endoscopist_id"])))
    assert aborted["status"] == "ABORTED_INADEQUATE_PREP"
    assert aborted["released_minutes"] == 0

    block = read_block(scenario["block_id"])
    assert block["booked_minutes"] == 60
    assert block["remaining_minutes"] == 420

    claim = read_claim(scenario["claim_id"])
    assert claim["status"] == "REPRICED"
    assert claim["variant"] == "FINAL"
    assert claim["reprice_count"] == 1
    assert claim["base_allowed_cents"] == 30000
    assert claim["complexity_tier"] == "TIER_1"
    assert claim["allowed_amount_cents"] == 30000
    assert claim["classification"] == "SCREENING_PREVENTIVE"
    assert claim["patient_responsibility_cents"] == 0
    assert claim["plan_paid_cents"] == 30000
    assert [line["code"] for line in claim["line_items"]] == ["ABORTED_TECHNICAL"]
    assert claim["line_items"][0]["allowed_cents"] == 30000


def test_a_voided_claim_refuses_finalize_dispute_and_reprice_alike():
    """Cancelling the underlying booking voids the claim from either `PROVISIONAL_PRICED →
    VOIDED` or `REPRICED → VOIDED`, zeroing `base_allowed_cents`, `allowed_amount_cents`,
    `deductible_applied_cents`, `coinsurance_cents`, `patient_responsibility_cents`, and
    `plan_paid_cents` and emptying `line_items`.

    A claim's `status` cycles among `PROVISIONAL_PRICED`, `REPRICED`, `FINALIZED`, `DISPUTED`,
    and the terminal `VOIDED`. Any action requested from a status that does not admit it is
    rejected with `ERR_INVALID_CLAIM_STATE`.

    Design: Corner/state_machines/voided_claim_admits_no_billing_actions
    """
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan(**PLAN_P1)
    endoscopist = register_endoscopist()
    patient = register_patient(plan["id"])
    block = create_block(endoscopist["id"])
    apply_block_action(block["id"], "PUBLISH")
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    booking = book_slot(block["id"], episode["id"], endoscopist["id"],
                        slot_start_utc="2026-09-15T13:00:00Z", duration_minutes=45)
    claim_id = claim_for_booking(booking["id"])["id"]
    cancel_slot(booking["id"], "PATIENT_RESCHEDULED")

    claim = read_claim(claim_id)
    assert claim["status"] == "VOIDED"
    assert claim["allowed_amount_cents"] == 0
    assert claim["patient_responsibility_cents"] == 0

    validate_error(api_client.finalize_billing_claim(claim_id, BILLING_SPECIALIST),
                   "ERR_INVALID_CLAIM_STATE")
    validate_error(
        api_client.dispute_billing_claim(claim_id, {"dispute_reason": "PATIENT_APPEAL"},
                                         BILLING_SPECIALIST),
        "ERR_INVALID_CLAIM_STATE")
    validate_error(api_client.reprice_billing_claim(claim_id, BILLING_SPECIALIST),
                   "ERR_INVALID_CLAIM_STATE")

    patient_row = read_patient(patient["id"])
    assert patient_row["deductible_applied_cents"] == 0
    assert patient_row["oop_applied_cents"] == 0


def test_resume_reads_current_coverage_rather_than_the_pre_suspension_posture():
    """`RESUME` is deliberately not a memory operation. From `SUSPENDED` it clears
    `suspension_reason` and returns the block to whichever posture its *current* coverage
    implies, not the posture it held before suspension: `SUSPENDED → COVERAGE_CONFIRMED` when
    the block still has an `ACTIVE` coverage row that fully spans its window, and `SUSPENDED →
    PUBLISHED` when it does not.

    `SUSPEND` moves either `PUBLISHED → SUSPENDED` or `COVERAGE_CONFIRMED → SUSPENDED`,
    requires a `reason` — omitting it is `ERR_INVALID_REQUEST` — records it in
    `suspension_reason`, and stops the block accepting new bookings.

    Design: Corner/state_machines/resume_lands_on_the_posture_implied_by_current_coverage
    """
    move_clock("2026-09-01T00:00:00Z")
    endoscopist = register_endoscopist()
    anesthetist = register_anesthesia_clinician(max_overlapping_rooms=1)
    block = create_block(endoscopist["id"], anesthesia_mode="MAC")
    apply_block_action(block["id"], "PUBLISH")
    coverage = staff_block(block["id"], anesthetist["id"])

    suspended = apply_block_action(block["id"], "SUSPEND", "STAFFING_SHORTFALL")
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == "STAFFING_SHORTFALL"

    resumed = apply_block_action(block["id"], "RESUME")
    assert resumed["status"] == "COVERAGE_CONFIRMED"
    assert resumed["suspension_reason"] is None

    release_coverage(coverage["id"])
    assert read_block(block["id"])["status"] == "PUBLISHED"
    assert read_coverage(coverage["id"])["status"] == "RELEASED"

    assert apply_block_action(block["id"], "SUSPEND",
                              "STAFFING_SHORTFALL")["status"] == "SUSPENDED"
    assert apply_block_action(block["id"], "RESUME")["status"] == "PUBLISHED"


def test_completing_with_no_specimens_closes_the_episode_in_one_call():
    """The clinical dimension then branches on `specimen_count`: with at least one specimen the
    episode moves `PROCEDURE_SCHEDULED → PATHOLOGY_PENDING` and waits for the laboratory; with
    zero specimens there is nothing to wait for, and the **no-specimen closure cascade** runs
    instead — a `SurveillanceRecommendation` is created with `pathology_report_id` null,
    `basis` `GUIDELINE`, and `status` `ACTIVE`, computed from an all-zero, all-false
    finalized-pathology aggregate; its `assigned_interval_months` and `next_due_date` are
    copied onto the episode's `assigned_interval_months` and `due_date`; the episode moves
    `PROCEDURE_SCHEDULED → CLOSED_SURVEILLANCE_SET`; and the claim is repriced under the final
    pricing pass, moving `PROVISIONAL_PRICED → REPRICED` and writing the booking's
    `final_classification`. Otherwise, if both the aggregate adenoma count and the aggregate
    sessile serrated count are zero — a clean exam — the base is 120 months, ten years.

    Design: Corner/state_machines/no_specimen_completion_runs_the_closure_cascade
    """
    scenario = _in_progress_moderate_sedation_booking()
    before = read_episode(scenario["episode_id"])
    assert before["due_date"] == "2027-02-28"
    assert before["risk_tier_snapshot"] == "AVERAGE"

    completed = validate_success(
        api_client.complete_procedure(
            scenario["booking_id"],
            complete_procedure_payload(8, 0, 0, 0),
            make_endoscopist_headers(scenario["endoscopist_id"])))
    assert completed["status"] == "COMPLETED"
    assert completed["final_classification"] == "SCREENING_PREVENTIVE"

    episode = read_episode(scenario["episode_id"])
    assert episode["clinical_status"] == "CLOSED_SURVEILLANCE_SET"
    assert episode["navigation_status"] == "NAVIGATION_COMPLETE"
    assert episode["assigned_interval_months"] == 120
    assert episode["due_date"] == "2036-09-15"

    rows, meta = list_recommendations({"episode_id": scenario["episode_id"]})
    assert meta["total_count"] == 1
    assert rows[0]["pathology_report_id"] is None
    assert rows[0]["basis"] == "GUIDELINE"
    assert rows[0]["status"] == "ACTIVE"
    assert rows[0]["computed_interval_months"] == 120
    assert rows[0]["next_due_date"] == "2036-09-15"

    claim = read_claim(scenario["claim_id"])
    assert claim["status"] == "REPRICED"
    assert claim["variant"] == "FINAL"
    assert claim["complexity_tier"] == "TIER_2"
    assert claim["allowed_amount_cents"] == 170750
    assert claim["patient_responsibility_cents"] == 0
    assert claim["plan_paid_cents"] == 170750
