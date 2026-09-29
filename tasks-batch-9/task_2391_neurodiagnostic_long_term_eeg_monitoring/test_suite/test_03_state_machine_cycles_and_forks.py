"""
State machines that are neither linear nor single-dimensional.

The payer negotiation cycles between two states and is terminated by a counter
rather than by a state. A study advances two dimensions independently, with one
guarded transition demanding that both agree. An alert forks into three branches
with different preconditions and cascades, and all three converge on one close.
"""

from test_helpers import (
    assert_admission_dimensions,
    assert_alert_dimensions,
    assert_capture_value,
    assert_storage_value,
    assert_study_dimensions,
    assert_unit_storage,
    assert_whole_minutes,
    factories as f,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_INTERVENTION_REQUIRED,
    ERR_INVALID_DATA_STATE,
    ERR_INVALID_STUDY_STATE,
    ERR_RESUBMISSION_LIMIT,
)
from test_helpers.constants import (
    ACQ_ACQUIRING,
    ACQ_COMPLETED,
    ACQ_PAUSED,
    ALERT_SOURCE_ALGORITHM,
    AUTH_PENDED,
    AUTH_STATE_ACTIVE,
    AUTH_SUBMITTED,
    CLASSIFICATION_ARTIFACT,
    CLASSIFICATION_CLINICAL,
    CLINICAL_ADMITTED,
    DATA_ARCHIVED,
    DATA_EXPORT_HELD,
    EVENT_CLINICAL_SEIZURE,
    INTERVENTION_POSITIONING,
    INTERVENTION_SUCTION,
    MARKING_ADJUDICATED,
    MARKING_RETRACTED,
    OUTCOME_PEND,
    POSTURE_OPEN,
    RESPONSE_AWAITING,
    RESPONSE_LATE,
    RETRACTION_REASON_ARTIFACT,
    RISK_LOW,
    RISK_MODERATE,
    SETTING_INPATIENT,
    TRIAGE_CLOSED,
    TRIAGE_CONFIRMED_CLINICAL,
    TRIAGE_DETECTED,
    TRIAGE_REJECTED_ARTIFACT,
)
from test_helpers.test_users import (
    COORDINATOR,
    EPILEPTOLOGIST,
    NURSE_ID_2,
    PAYER_REVIEWER,
)

PEND_NOTE_ROUND_1 = "need seizure diary"
PEND_NOTE_ROUND_2 = "need prior AED trials"
PEND_NOTE_ROUND_3 = "need MRI report"

# The study timeline shared by the parallel-dimension and fork-join tests: one
# 1440-minute segment from admission to the next midnight.
T_SEGMENT_CLOSED = "2026-08-03T00:00:00Z"
T_ALERT_A_DETECTED = "2026-08-03T01:00:00Z"
T_BEDSIDE_RESPONSE = "2026-08-03T02:00:00Z"
T_ALERT_B_DETECTED = "2026-08-03T02:00:00Z"
ONSET_A = "2026-08-02T06:00:00Z"
ONSET_B = "2026-08-02T09:00:00Z"


def _pend(api, authorization_id, payer_note):
    """Record a PEND decision, which carries no authorized days or setting."""
    return validate_success(
        api.record_payer_decision(
            authorization_id,
            f.payer_decision_payload(
                outcome=OUTCOME_PEND,
                authorized_days=None,
                authorized_setting=None,
                payer_note=payer_note,
            ),
            PAYER_REVIEWER,
        )
    )


def _authorization_pended_three_times(api):
    """Walk the submit-pend loop until `resubmission_count` stands at 2."""
    patient = fixtures.create_patient(api, display_name="Pat Six", risk_tier=RISK_LOW)
    authorization = fixtures.draft_authorization(
        api, patient["id"], requested_setting=SETTING_INPATIENT, requested_days=5
    )
    authorization_id = authorization["id"]
    validate_success(api.submit_authorization(authorization_id, COORDINATOR))
    _pend(api, authorization_id, PEND_NOTE_ROUND_1)
    validate_success(api.submit_authorization(authorization_id, COORDINATOR))
    _pend(api, authorization_id, PEND_NOTE_ROUND_2)
    validate_success(api.submit_authorization(authorization_id, COORDINATOR))
    _pend(api, authorization_id, PEND_NOTE_ROUND_3)
    return authorization_id


def _acquiring_study_one_day_in(api):
    """An acquiring 32-channel inpatient study with the clock one day past admission."""
    baseline = fixtures.build_acquiring_stay(
        api,
        storage_quota_gb=500.00,
        risk_tier=RISK_MODERATE,
        setting=SETTING_INPATIENT,
        requested_days=5,
        planned_days=3,
        target_event_count=4,
        max_concurrent_studies=2,
        channel_count=32,
    )
    fixtures.set_clock(api, T_SEGMENT_CLOSED)
    return baseline


def _paused_study_with_alert_a(api):
    """A paused study carrying alert A at 01:00 UTC and one PROPOSED marking on it."""
    baseline = _acquiring_study_one_day_in(api)
    fixtures.pause_study(api, baseline.study_id)
    alert = fixtures.raise_alert(
        api, baseline.study_id, source=ALERT_SOURCE_ALGORITHM, at=T_ALERT_A_DETECTED
    )
    marking = fixtures.create_marking(
        api,
        baseline.study_id,
        ONSET_A,
        event_class=EVENT_CLINICAL_SEIZURE,
        duration_seconds=60,
        alert_id=alert["id"],
    )
    return baseline, alert, marking


def test_pend_and_resubmit_cycle_returns_to_submitted_and_counts_each_lap(api):
    """The same submit endpoint is legal from DRAFT and from PENDED, and each lap increments the counter.

    PRD §3.2: "A `PEND` outcome moves `SUBMITTED` to `PENDED` and stores the
    supplied `payer_note`, returning the request to the unit for one more attempt;
    resubmitting a `PENDED` request moves it back to `SUBMITTED` and increments
    `resubmission_count` by 1, and a resubmission attempted when
    `resubmission_count` has already reached 2 is refused with
    `ERR_RESUBMISSION_LIMIT`."
    PRD §3.2: "Submission moves the request from `DRAFT` to `SUBMITTED` and, on
    that first submission, explicitly clears `payer_note` back to null."

    Design: Difficulty/non_linear_state_machine/authorization_pend_resubmit_cycle_capped_at_two
    """
    patient = fixtures.create_patient(api, display_name="Pat Six", risk_tier=RISK_LOW)
    authorization = fixtures.draft_authorization(
        api, patient["id"], requested_setting=SETTING_INPATIENT, requested_days=5
    )
    authorization_id = authorization["id"]

    first = validate_success(api.submit_authorization(authorization_id, COORDINATOR))
    assert first["status"] == AUTH_SUBMITTED, (
        f"the first submission should reach {AUTH_SUBMITTED}, got {first['status']!r}"
    )
    assert first["resubmission_count"] == 0, (
        "the first submission is not a resubmission, so resubmission_count stays "
        f"0, got {first['resubmission_count']!r}"
    )
    assert first["payer_note"] is None, (
        f"the first submission clears payer_note, got {first['payer_note']!r}"
    )

    pended = _pend(api, authorization_id, PEND_NOTE_ROUND_1)
    assert pended["status"] == AUTH_PENDED, (
        f"a PEND outcome should reach {AUTH_PENDED}, got {pended['status']!r}"
    )
    assert pended["resubmission_count"] == 0, (
        "pending does not itself consume a resubmission, got "
        f"{pended['resubmission_count']!r}"
    )

    second = validate_success(api.submit_authorization(authorization_id, COORDINATOR))
    assert second["status"] == AUTH_SUBMITTED, (
        f"resubmitting a PENDED request returns it to {AUTH_SUBMITTED}, got "
        f"{second['status']!r}"
    )
    assert second["resubmission_count"] == 1, (
        f"the first resubmission counts 1, got {second['resubmission_count']!r}"
    )

    _pend(api, authorization_id, PEND_NOTE_ROUND_2)
    third = validate_success(api.submit_authorization(authorization_id, COORDINATOR))
    assert third["status"] == AUTH_SUBMITTED, (
        f"the second lap also returns to {AUTH_SUBMITTED}, got {third['status']!r}"
    )
    assert third["resubmission_count"] == 2, (
        f"the second resubmission counts 2, got {third['resubmission_count']!r}"
    )


def test_resubmission_is_refused_once_the_count_has_reached_two(api):
    """The loop is terminated by the counter, not by any state change, and the refusal leaves everything intact.

    PRD §2.2 rung 23: "An authorization's `resubmission_count` is below 2 when
    resubmitting, otherwise `ERR_RESUBMISSION_LIMIT`; a report's `addendum_count`
    is below 2 when opening an addendum, otherwise `ERR_ADDENDUM_LIMIT`; a case's
    `defer_round` is below 2 when re-presenting, otherwise `ERR_DEFER_LIMIT`."
    PRD §3.2: "Only an authorization in `APPROVED` can fund a stay at all —
    requests in `DRAFT`, `SUBMITTED`, `PENDED` or `DENIED` carry `authorized_days`
    of 0 and cannot fund anything."

    Design: Difficulty/non_linear_state_machine/authorization_pend_resubmit_cycle_capped_at_two
    """
    authorization_id = _authorization_pended_three_times(api)

    validate_error(
        api.submit_authorization(authorization_id, COORDINATOR),
        ERR_RESUBMISSION_LIMIT,
        expected_status=409,
    )

    stored = validate_success(api.get_authorization(authorization_id, COORDINATOR))
    assert stored["status"] == AUTH_PENDED, (
        "the refused resubmission leaves the request where the third PEND put it, "
        f"expected {AUTH_PENDED}, got {stored['status']!r}"
    )
    assert stored["resubmission_count"] == 2, (
        "a refused resubmission does not consume a further lap, got "
        f"{stored['resubmission_count']!r}"
    )
    assert stored["payer_note"] == PEND_NOTE_ROUND_3, (
        "the note from the last PEND survives the refusal, expected "
        f"{PEND_NOTE_ROUND_3!r}, got {stored['payer_note']!r}"
    )
    assert stored["authorized_days"] == 0, (
        f"a PENDED request funds nothing, so authorized_days is 0, got "
        f"{stored['authorized_days']!r}"
    )


def test_export_hold_and_pause_move_the_two_study_dimensions_independently(api):
    """Data residency moves while acquisition is still running, and acquisition moves while the hold stands.

    PRD §3.9: "The data-residency dimension of a study moves independently of its
    acquisition."
    PRD §3.9: "Placing an export hold moves `data_state` from `ONLINE` to
    `EXPORT_HELD` and stores the supplied `hold_reason` on the study's
    `export_hold_reason`; the study must be `ONLINE`, otherwise
    `ERR_INVALID_DATA_STATE`."
    PRD §3.9: "A study whose `data_state` is not `ONLINE` is refused with
    `ERR_INVALID_DATA_STATE`; a study whose acquisition has not completed is
    refused with `ERR_INVALID_STUDY_STATE`."

    Design: Difficulty/non_linear_state_machine/study_parallel_acquisition_and_data_dimensions
    """
    baseline = _acquiring_study_one_day_in(api)

    # Archiving while acquisition is still running fails on the acquisition
    # dimension, even though the data dimension is exactly where archive wants it.
    validate_error(
        api.archive_study(baseline.study_id, COORDINATOR),
        ERR_INVALID_STUDY_STATE,
        expected_status=409,
    )

    held = validate_success(
        api.place_export_hold(
            baseline.study_id, f.export_hold_payload("LEGAL_HOLD"), COORDINATOR
        )
    )
    assert_study_dimensions(held, ACQ_ACQUIRING, DATA_EXPORT_HELD)
    assert held["export_hold_reason"] == "LEGAL_HOLD", (
        f"export_hold_reason should store the supplied reason, got "
        f"{held['export_hold_reason']!r}"
    )

    paused = fixtures.pause_study(api, baseline.study_id, reason="ELECTRODE_CHECK")
    assert_study_dimensions(paused, ACQ_PAUSED, DATA_EXPORT_HELD)
    # 2026-08-02T00:00:00Z to 2026-08-03T00:00:00Z is 1440 whole minutes at the
    # 0.032 GB per-minute rate of a 32-channel inpatient recording.
    assert_whole_minutes(paused["acquired_minutes"], 1440, "acquired_minutes")
    assert_storage_value(paused["stored_gb"], 46.08, "stored_gb")


def test_archive_needs_both_dimensions_to_agree_before_it_releases_storage(api):
    """A completed study still under export hold cannot archive, and releasing the hold frees the volume.

    PRD §3.9: "Archiving is the storage-relief move, and it is the one
    cross-dimension guarded transition in the study machine: `data_state` moves
    from `ONLINE` to `ARCHIVED` only when `acquisition_state` has reached
    `COMPLETED`."
    PRD §3.9: "Archiving removes that study's `stored_gb` from the unit's
    `storage_used_gb`, re-derives `storage_pressure_pct` and `posture`, and — when
    the posture consequently leaves `STORAGE_LOCKED` — returns every export
    package of that unit standing in `BLOCKED` with `blocked_reason` equal to the
    literal `UNIT_STORAGE_LOCKED` to `QUEUED`."

    Design: Difficulty/non_linear_state_machine/study_parallel_acquisition_and_data_dimensions
    """
    baseline = _acquiring_study_one_day_in(api)
    validate_success(
        api.place_export_hold(
            baseline.study_id, f.export_hold_payload("LEGAL_HOLD"), COORDINATOR
        )
    )
    fixtures.pause_study(api, baseline.study_id, reason="ELECTRODE_CHECK")
    completed = fixtures.complete_study(api, baseline.study_id)
    assert_study_dimensions(completed, ACQ_COMPLETED, DATA_EXPORT_HELD)

    # Acquisition now satisfies archive, but the data dimension does not.
    validate_error(
        api.archive_study(baseline.study_id, COORDINATOR),
        ERR_INVALID_DATA_STATE,
        expected_status=409,
    )

    validate_success(api.release_export_hold(baseline.study_id, COORDINATOR))
    archived = validate_success(api.archive_study(baseline.study_id, COORDINATOR))
    assert_study_dimensions(archived, ACQ_COMPLETED, DATA_ARCHIVED)
    assert_storage_value(archived["stored_gb"], 46.08, "stored_gb")

    unit = validate_success(api.get_unit(baseline.unit_id, COORDINATOR))
    # An ARCHIVED study is excluded from the unit's used volume entirely.
    assert_unit_storage(
        unit, storage_used_gb=0.00, storage_pressure_pct=0.00, posture=POSTURE_OPEN
    )


def test_clinical_fork_demands_a_documented_bedside_response_before_it_will_confirm(api):
    """The CLINICAL branch is refused until an intervention exists, then confirms, banks its marking and closes.

    PRD §3.6: "A `CLINICAL` classification moves `triage_state` to
    `CONFIRMED_CLINICAL` — but only if at least one safety intervention already
    exists on that alert, otherwise the adjudication is refused with
    `ERR_INTERVENTION_REQUIRED`."
    PRD §3.6: "Closing from `CONFIRMED_CLINICAL` is permitted only when the
    response dimension has left `AWAITING_RESPONSE` — a confirmed clinical event
    may not be closed with the bedside response still outstanding, and the refusal
    is `ERR_INTERVENTION_REQUIRED`."

    Design: Difficulty/non_linear_state_machine/alert_fork_join_clinical_branch_requires_intervention
    """
    _, alert, marking = _paused_study_with_alert_a(api)

    validate_error(
        api.adjudicate_alert(
            alert["id"],
            f.adjudicate_alert_payload(CLASSIFICATION_CLINICAL),
            EPILEPTOLOGIST,
        ),
        ERR_INTERVENTION_REQUIRED,
        expected_status=409,
    )
    unattended = validate_success(api.get_alert(alert["id"], EPILEPTOLOGIST))
    assert_alert_dimensions(unattended, TRIAGE_DETECTED, RESPONSE_AWAITING)

    fixtures.record_intervention(
        api,
        alert["id"],
        interventions=[INTERVENTION_POSITIONING, INTERVENTION_SUCTION],
        injury_observed=False,
        rescue_med_given=True,
        nurse_user_id=NURSE_ID_2,
        at=T_BEDSIDE_RESPONSE,
    )
    confirmed = validate_success(
        api.adjudicate_alert(
            alert["id"],
            f.adjudicate_alert_payload(CLASSIFICATION_CLINICAL),
            EPILEPTOLOGIST,
        )
    )
    assert confirmed["triage_state"] == TRIAGE_CONFIRMED_CLINICAL, (
        f"the CLINICAL branch should reach {TRIAGE_CONFIRMED_CLINICAL}, got "
        f"{confirmed['triage_state']!r}"
    )

    banked = validate_success(api.get_marking(marking["id"], EPILEPTOLOGIST))
    assert banked["status"] == MARKING_ADJUDICATED, (
        "the clinical cascade moves the alert's PROPOSED marking to "
        f"{MARKING_ADJUDICATED}, got {banked['status']!r}"
    )

    closed = validate_success(api.close_alert(alert["id"], EPILEPTOLOGIST))
    # Detected 01:00, attended 02:00: a latency of 60 minutes against a deadline
    # of 7 minutes (MODERATE base 6 plus the overnight allowance).
    assert_alert_dimensions(closed, TRIAGE_CLOSED, RESPONSE_LATE)
    assert_whole_minutes(closed["latency_minutes"], 60, "latency_minutes")


def test_artifact_fork_retracts_its_marking_and_joins_the_same_closed_state(api):
    """The ARTIFACT branch needs no bedside response, retracts its marking, and both forks converge on CLOSED.

    PRD §3.6: "An `ARTIFACT` classification moves `triage_state` to
    `REJECTED_ARTIFACT` and stamps `adjudicated_at`. Its cascade runs the opposite
    way: every event marking pointing at this alert whose `status` is `PROPOSED`
    moves to `RETRACTED` with `retraction_reason` set to the literal
    `ALERT_REJECTED_AS_ARTIFACT`, and the admission's capture figures are
    recomputed and consequently do not increase."
    PRD §3.6: "Closing from `CONFIRMED_SUBCLINICAL` carries no bedside-response
    requirement at all, and closing from `REJECTED_ARTIFACT` likewise carries
    none, having granted no capture credit in the first place."

    Design: Difficulty/non_linear_state_machine/alert_fork_join_clinical_branch_requires_intervention
    """
    baseline, alert_a, marking_a = _paused_study_with_alert_a(api)
    alert_b = fixtures.raise_alert(
        api, baseline.study_id, source=ALERT_SOURCE_ALGORITHM, at=T_ALERT_B_DETECTED
    )
    marking_b = fixtures.create_marking(
        api,
        baseline.study_id,
        ONSET_B,
        event_class=EVENT_CLINICAL_SEIZURE,
        duration_seconds=45,
        alert_id=alert_b["id"],
    )

    rejected = validate_success(
        api.adjudicate_alert(
            alert_b["id"],
            f.adjudicate_alert_payload(CLASSIFICATION_ARTIFACT),
            EPILEPTOLOGIST,
        )
    )
    assert rejected["triage_state"] == TRIAGE_REJECTED_ARTIFACT, (
        f"the ARTIFACT branch should reach {TRIAGE_REJECTED_ARTIFACT}, got "
        f"{rejected['triage_state']!r}"
    )
    retracted = validate_success(api.get_marking(marking_b["id"], EPILEPTOLOGIST))
    assert retracted["status"] == MARKING_RETRACTED, (
        "the artifact cascade moves the alert's PROPOSED marking to "
        f"{MARKING_RETRACTED}, got {retracted['status']!r}"
    )
    assert retracted["retraction_reason"] == RETRACTION_REASON_ARTIFACT, (
        "retraction_reason should be the literal "
        f"{RETRACTION_REASON_ARTIFACT!r}, got {retracted['retraction_reason']!r}"
    )

    # No intervention was ever documented on alert B, yet the close is permitted.
    closed_b = validate_success(api.close_alert(alert_b["id"], EPILEPTOLOGIST))
    assert_alert_dimensions(closed_b, TRIAGE_CLOSED, RESPONSE_AWAITING)

    # The clinical fork now walks its own path to the same join state.
    fixtures.record_intervention(
        api,
        alert_a["id"],
        interventions=[INTERVENTION_POSITIONING, INTERVENTION_SUCTION],
        injury_observed=False,
        rescue_med_given=True,
        nurse_user_id=NURSE_ID_2,
    )
    fixtures.adjudicate_alert(api, alert_a["id"], CLASSIFICATION_CLINICAL)
    closed_a = validate_success(api.close_alert(alert_a["id"], EPILEPTOLOGIST))
    assert closed_a["triage_state"] == TRIAGE_CLOSED, (
        f"both forks converge on {TRIAGE_CLOSED}, got {closed_a['triage_state']!r}"
    )
    banked = validate_success(api.get_marking(marking_a["id"], EPILEPTOLOGIST))
    assert banked["status"] == MARKING_ADJUDICATED, (
        f"the clinical marking should stand at {MARKING_ADJUDICATED}, got "
        f"{banked['status']!r}"
    )

    admission = validate_success(
        api.get_admission(baseline.admission_id, EPILEPTOLOGIST)
    )
    # Only the clinical marking banks weight: 1.000 against a target of 4.
    assert_capture_value(
        admission["weighted_event_count"], 1.000, "weighted_event_count"
    )
    assert_capture_value(
        admission["capture_adequacy_index"], 0.250, "capture_adequacy_index"
    )
    assert_admission_dimensions(admission, CLINICAL_ADMITTED, AUTH_STATE_ACTIVE)
