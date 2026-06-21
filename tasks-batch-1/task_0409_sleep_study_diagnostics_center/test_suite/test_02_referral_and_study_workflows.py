"""Referral authorization branching, study scoring/return loop, cascade
propagation, and the follow-up lifecycle.

Covers difficulty queue (A) non-linear-state-machine and transitive-cascade
instances, and corner queue (B) state-machine instances.
"""

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_submitted_referral,
    create_pending_auth_referral,
    create_authorized_referral,
    create_scored_study,
    create_scheduled_study,
    create_in_progress_study,
    create_interpreted_study,
    create_scheduled_follow_up,
    create_bed,
    create_study_order_payload,
    schedule_study_payload,
    score_study_payload,
    interpret_payload,
    approve_auth_payload,
    create_follow_up_payload,
    TEST_USERS,
)

COORD = TEST_USERS["scheduling_coordinator_headers"]
TECH = TEST_USERS["sleep_technologist_headers"]
PHYS = TEST_USERS["physician_headers"]


# ─── Score -> return -> re-score cycle (non-linear state machine) ──────────

def test_return_report_reverts_study_to_in_progress(api):
    """PRD 3.7: "Returning a report sends it from DRAFT to RETURNED and, in the
    same operation, reverts the linked study from SCORED back to IN_PROGRESS,
    bumping that study's version."

    Design: Difficulty/non_linear_state_machine/study_score_return_rescore_cycle
    """
    _, _, study, report, _ = create_scored_study(modality="HSAT")
    res = api.return_scoring_report(report["id"], PHYS)
    returned = validate_success(res, 200)
    assert returned["status"] == "RETURNED"
    study_after = get_success_data(api.get_study_order(study["id"], COORD))
    assert study_after["status"] == "IN_PROGRESS", (
        f"Expected IN_PROGRESS after return, got {study_after['status']}"
    )


def test_study_can_be_rescored_after_return(api):
    """PRD 3.7: "a physician who is unsatisfied kicks the work back to the
    technologist, who re-records or re-scores and, on the next successful scoring,
    produces a new DRAFT report. A study may therefore cycle through SCORED and
    back to IN_PROGRESS several times before it is finally interpreted."

    Design: Difficulty/non_linear_state_machine/study_score_return_rescore_cycle
    """
    _, _, study, report, _ = create_scored_study(modality="HSAT")
    api.return_scoring_report(report["id"], PHYS)
    reverted = get_success_data(api.get_study_order(study["id"], COORD))
    assert reverted["status"] == "IN_PROGRESS"
    rescore = api.score_study(
        study["id"],
        score_study_payload(480, 200, reverted["version"]),
        TECH,
    )
    rescored = validate_success(rescore, 200)
    assert rescored["status"] == "SCORED", "Re-scoring must drive the study back to SCORED"


# ─── Referral PENDING_AUTH -> DENIED branch (non-linear state machine) ─────

def test_deny_auth_from_pending_is_terminal_denied(api):
    """PRD 3.2: "Denial advances the referral from PENDING_AUTH to DENIED, which
    is terminal and carries no further preconditions."

    Design: Difficulty/non_linear_state_machine/referral_branch_pending_auth_to_denied
    """
    _, referral = create_pending_auth_referral(modality="IN_LAB_PSG")
    res = api.deny_auth(referral["id"], COORD)
    denied = validate_success(res, 200)
    assert denied["status"] == "DENIED"


def test_denied_referral_carries_no_auth_fields(api):
    """PRD 3.2: "Denial advances the referral from PENDING_AUTH to DENIED, which
    is terminal and carries no further preconditions."
    PRD 3.1: "Two further fields, prior_auth_number and prior_auth_expires_on,
    remain null on a new referral; they are populated only when authorization is
    granted, the latter being the ISO date on which the authorization lapses."

    The DENIED arm never populates the auth fields (unlike the AUTHORIZED arm).

    Design: Difficulty/non_linear_state_machine/referral_branch_pending_auth_to_denied
    """
    _, referral = create_pending_auth_referral(modality="IN_LAB_PSG")
    res = api.deny_auth(referral["id"], COORD)
    denied = validate_success(res, 200)
    assert denied["status"] == "DENIED"
    assert denied["prior_auth_number"] is None, "DENIED arm must not stamp prior_auth_number"


# ─── Interpret cascade: report -> study -> referral (transitive cascade) ───

def test_interpret_cascades_report_study_referral(api):
    """PRD 3.7: "On success the interpretation text and the recommendation flag
    are persisted, the report advances from DRAFT to FINALIZED, the linked study
    advances from SCORED to INTERPRETED (a terminal study state), and the parent
    referral bubbles up from SCHEDULED to COMPLETED (a terminal referral state)."

    Design: Difficulty/transitive_cascade/interpret_cascade_report_to_study_to_referral
    """
    _, referral, study, report, _ = create_scored_study(
        modality="IN_LAB_PSG", total_recording_minutes=480, respiratory_event_count=240
    )
    res = api.interpret_scoring_report(
        report["id"],
        interpret_payload(interpretation_text="Severe OSA, CPAP recommended",
                          physician_recommends_cpap=True),
        PHYS,
    )
    finalized = validate_success(res, 200)
    assert finalized["status"] == "FINALIZED"
    study_after = get_success_data(api.get_study_order(study["id"], COORD))
    assert study_after["status"] == "INTERPRETED"
    referral_after = get_success_data(api.get_referral(referral["id"], COORD))
    assert referral_after["status"] == "COMPLETED"


def test_interpret_completes_parent_referral(api):
    """PRD 3.7: "the parent referral bubbles up from SCHEDULED to COMPLETED (a
    terminal referral state). Each of these propagated mutations refreshes the
    affected resource's updated_at and increments its version."

    Design: Difficulty/transitive_cascade/interpret_cascade_report_to_study_to_referral
    """
    _, referral, study, report, _ = create_scored_study(
        modality="IN_LAB_PSG", total_recording_minutes=480, respiratory_event_count=240
    )
    ref_before = get_success_data(api.get_referral(referral["id"], COORD))
    assert ref_before["status"] == "SCHEDULED"
    api.interpret_scoring_report(
        report["id"],
        interpret_payload(interpretation_text="Severe OSA", physician_recommends_cpap=True),
        PHYS,
    )
    ref_after = get_success_data(api.get_referral(referral["id"], COORD))
    assert ref_after["status"] == "COMPLETED"
    assert ref_after["version"] > ref_before["version"], "Bubble-up must bump the referral version"


# ─── Referral cancel cascade + bed release (transitive cascade) ────────────

def test_referral_cancel_cascades_to_scheduled_study(api):
    """PRD 3.2: "When cancellation does proceed the referral becomes CANCELLED,
    which is terminal; every study beneath it that is still in ORDERED or
    SCHEDULED is cascade-cancelled to CANCELLED; and each of those
    cascade-cancelled studies that was holding a bed night releases that occupancy
    so the bed becomes bookable for that interval again."

    Design: Difficulty/transitive_cascade/referral_cancel_cascade_study_and_bed_release
    """
    _, referral, study, bed = create_scheduled_study(
        modality="IN_LAB_PSG",
        night_start_utc="2026-07-10T22:00:00Z",
        night_end_utc="2026-07-11T06:00:00Z",
    )
    res = api.cancel_referral(referral["id"], COORD)
    cancelled_ref = validate_success(res, 200)
    assert cancelled_ref["status"] == "CANCELLED"
    study_after = get_success_data(api.get_study_order(study["id"], COORD))
    assert study_after["status"] == "CANCELLED", "Scheduled study must cascade to CANCELLED"


def test_referral_cancel_releases_bed_night_for_rebooking(api):
    """PRD 3.2: "each of those cascade-cancelled studies that was holding a bed
    night releases that occupancy so the bed becomes bookable for that interval
    again."

    After the cascade releases the night, a fresh study can book the exact same
    interval on the same bed.

    Design: Difficulty/transitive_cascade/referral_cancel_cascade_study_and_bed_release
    """
    _, referral, study, bed = create_scheduled_study(
        modality="IN_LAB_PSG",
        night_start_utc="2026-07-10T22:00:00Z",
        night_end_utc="2026-07-11T06:00:00Z",
    )
    api.cancel_referral(referral["id"], COORD)

    # A fresh authorized study books the freed interval on the same bed.
    _, referral2 = create_authorized_referral(modality="IN_LAB_PSG")
    study2 = get_success_data(
        api.create_study_order(
            create_study_order_payload(referral2["id"], referral2["version"],
                                       modality="IN_LAB_PSG"),
            COORD,
        )
    )
    res = api.schedule_study(
        study2["id"],
        schedule_study_payload(
            night_start_utc="2026-07-10T22:00:00Z",
            night_end_utc="2026-07-11T06:00:00Z",
            bed_id=bed["id"],
        ),
        COORD,
    )
    scheduled = validate_success(res, 200)
    assert scheduled["status"] == "SCHEDULED", "Released night must be re-bookable"


# ─── Corner: referral cancel blocked by active study ───────────────────────

def test_cancel_referral_blocked_by_in_progress_study(api):
    """PRD 3.2: "Cancellation is refused with ERR_REFERRAL_HAS_ACTIVE_STUDY if any
    study under the referral has progressed to IN_PROGRESS, SCORED, or
    INTERPRETED, because an active clinical study must not be abandoned by
    cancelling its parent."

    Design: Corner/state_machines/cancel_referral_blocked_by_active_study
    """
    _, referral, study, _ = create_in_progress_study(modality="HSAT")
    res = api.cancel_referral(referral["id"], COORD)
    validate_error(res, "ERR_REFERRAL_HAS_ACTIVE_STUDY")
    ref_after = get_success_data(api.get_referral(referral["id"], COORD))
    assert ref_after["status"] == "SCHEDULED"


# ─── Corner: request-auth when not required ────────────────────────────────

def test_request_auth_when_not_required_rejected(api):
    """PRD 3.2: "This request is rejected with ERR_AUTH_NOT_REQUIRED if the
    referral's prior_auth_required flag is false, because a no-authorization
    referral must not enter the pending state."

    Design: Corner/state_machines/request_auth_when_not_required_returns_error
    """
    _, referral = create_submitted_referral(modality="HSAT", prior_auth_required=False)
    res = api.request_auth(referral["id"], COORD)
    validate_error(res, "ERR_AUTH_NOT_REQUIRED")


# ─── Corner: deny-auth from AUTHORIZED is invalid state ────────────────────

def test_deny_auth_from_authorized_invalid_state(api):
    """PRD 3.2: "Denial advances the referral from PENDING_AUTH to DENIED, which
    is terminal and carries no further preconditions."
    PRD 2.7: "fifth, whether the target resource is in a state from which the
    requested transition is legal (ERR_INVALID_STATE and its specific siblings)."

    Deny is only legal from PENDING_AUTH; from AUTHORIZED it is ERR_INVALID_STATE.

    Design: Corner/state_machines/deny_auth_from_authorized_returns_invalid_state
    """
    _, referral = create_authorized_referral(modality="HSAT")
    res = api.deny_auth(referral["id"], COORD)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner: start from ORDERED is invalid state ───────────────────────────

def test_start_study_from_ordered_invalid_state(api):
    """PRD 3.6: "Once a study is scheduled, a SleepTechnologist begins the
    overnight recording, advancing the study from SCHEDULED to IN_PROGRESS. This
    transition is legal only from SCHEDULED."

    Design: Corner/state_machines/start_study_from_ordered_returns_invalid_state
    """
    from test_helpers import create_ordered_study
    _, _, study = create_ordered_study(modality="HSAT")
    res = api.start_study(study["id"], TECH)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner: cancel an interpreted (terminal) study ────────────────────────

def test_cancel_interpreted_study_not_cancellable(api):
    """PRD 3.8: "A cancellation attempted from any other state is rejected with
    ERR_STUDY_NOT_CANCELLABLE."

    INTERPRETED is terminal, outside {ORDERED, SCHEDULED}.

    Design: Corner/state_machines/cancel_interpreted_study_not_cancellable
    """
    _, _, study, _, _ = create_interpreted_study(modality="HSAT")
    res = api.cancel_study(study["id"], COORD)
    validate_error(res, "ERR_STUDY_NOT_CANCELLABLE")


# ─── Corner: interpret requires non-empty text ─────────────────────────────

def test_interpret_requires_nonempty_text(api):
    """PRD 3.7: "The physician supplies the interpretation_text, which must be
    non-empty, and the boolean physician_recommends_cpap indicating whether CPAP
    therapy is recommended; when omitted this flag defaults to false."

    Omitting interpretation_text is rejected at body validation (422); report
    stays DRAFT.

    Design: Corner/state_machines/interpret_requires_nonempty_text
    """
    _, _, study, report, _ = create_scored_study(modality="HSAT")
    res = api.interpret_scoring_report(report["id"], {"physician_recommends_cpap": True}, PHYS)
    validate_error(res, "ERR_INVALID_REQUEST")
    report_after = get_success_data(api.get_scoring_report(report["id"], PHYS))
    assert report_after["status"] == "DRAFT"


# ─── Corner: titration pressure required on score ──────────────────────────

def test_titration_score_requires_pressure(api):
    """PRD 3.6: "A titration study additionally requires a titration_optimal_cmh2o
    greater than zero; a titration scored without it is rejected with
    ERR_TITRATION_PRESSURE_REQUIRED."

    Design: Corner/state_machines/titration_pressure_required_on_score
    """
    _, _, study, _ = create_in_progress_study(modality="IN_LAB_TITRATION")
    res = api.score_study(
        study["id"],
        score_study_payload(480, 60, study["version"]),
        TECH,
    )
    validate_error(res, "ERR_TITRATION_PRESSURE_REQUIRED")
    study_after = get_success_data(api.get_study_order(study["id"], COORD))
    assert study_after["status"] == "IN_PROGRESS"


# ─── Corner: insufficient recording (zero minutes) on score ────────────────

def test_score_zero_minutes_insufficient_recording(api):
    """PRD 3.6: "The recording must be sufficient: total_recording_minutes must be
    greater than zero, and a non-positive value is rejected with
    ERR_INSUFFICIENT_RECORDING, while respiratory_event_count must be zero or
    greater."

    Design: Corner/state_machines/score_insufficient_recording_zero_minutes
    """
    _, _, study, _ = create_in_progress_study(modality="HSAT")
    res = api.score_study(
        study["id"],
        score_study_payload(0, 10, study["version"]),
        TECH,
    )
    validate_error(res, "ERR_INSUFFICIENT_RECORDING")


# ─── Corner: follow-up complete sets epworth_improvement ───────────────────

def test_followup_complete_sets_improvement_and_status(api):
    """PRD 3.11: "On completion the system records the post-treatment score and
    derives the patient's epworth_improvement — the symptom change between
    baseline and treatment."
    PRD 3.11: "The improvement is the patient's baseline_epworth_score minus the
    post_treatment_epworth_score, so a positive result indicates the patient's
    daytime sleepiness improved; the value may be negative if symptoms worsened."

    baseline 16, post-treatment 6 -> improvement 10; status COMPLETED.

    Design: Corner/state_machines/followup_complete_sets_epworth_improvement
    """
    _, _, follow_up = create_scheduled_follow_up(baseline_epworth_score=16)
    res = api.complete_follow_up(follow_up["id"], {"post_treatment_epworth_score": 6}, COORD)
    completed = validate_success(res, 200)
    assert completed["status"] == "COMPLETED"
    assert completed["epworth_improvement"] == 10


# ─── Corner: follow-up no-show terminal ────────────────────────────────────

def test_followup_no_show_terminal(api):
    """PRD 3.11: "It may be marked a no-show, moving from SCHEDULED to NO_SHOW."

    Design: Corner/state_machines/followup_no_show_terminal
    """
    _, _, follow_up = create_scheduled_follow_up(baseline_epworth_score=14)
    res = api.no_show_follow_up(follow_up["id"], COORD)
    completed = validate_success(res, 200)
    assert completed["status"] == "NO_SHOW"


# ─── Corner: follow-up create requires interpreted study ───────────────────

def test_followup_create_requires_interpreted_study(api):
    """PRD 3.11: "A SchedulingCoordinator schedules a follow-up against an
    interpreted study by naming it through study_order_id and supplying the
    scheduled_for_utc appointment time; the study must be in INTERPRETED status for
    a follow-up to be scheduled."

    A SCORED (not interpreted) study is rejected with ERR_INVALID_STATE.

    Design: Corner/state_machines/followup_create_requires_interpreted_study
    """
    _, _, study, _, _ = create_scored_study(modality="HSAT")
    res = api.create_follow_up(create_follow_up_payload(study["id"]), COORD)
    validate_error(res, "ERR_INVALID_STATE")
