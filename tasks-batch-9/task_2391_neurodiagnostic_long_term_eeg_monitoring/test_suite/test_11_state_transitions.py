"""
Corner behaviour of the parallel state machines: valid moves, initial states,
refused triggers from terminal or wrong states, and one compensating retraction.

Every test drives the server through public endpoints only, starting from the
freshly launched empty database with its logical clock at the startup instant,
and advances the clock explicitly whenever the outcome depends on time.
"""

from typing import Any, Dict

from test_helpers import (
    assert_admission_dimensions,
    assert_alert_dimensions,
    assert_capture_value,
    assert_fields_null,
    assert_instant_equals,
    assert_ledger,
    assert_study_dimensions,
    assert_version_is,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_INVALID_ALERT_STATE,
    ERR_INVALID_REPORT_STATE,
    ERR_INVALID_TAPER_STATE,
    ERR_OPEN_STUDY_ON_DISCHARGE,
    ERR_SHIFT_HAS_ACTIVE_STUDIES,
)
from test_helpers.constants import (
    ACQ_ACQUIRING,
    ACQ_COMPLETED,
    ACQ_PREPARING,
    AUTH_STATE_ACTIVE,
    BED_OCCUPIED,
    CLASSIFICATION_SUBCLINICAL,
    CLINICAL_ADMITTED,
    DATA_ONLINE,
    EVENT_CLINICAL_SEIZURE,
    MARKING_RETRACTED,
    REPORT_FINAL_ISSUED,
    RESPONSE_AWAITING,
    RISK_LOW,
    RISK_MODERATE,
    SETTING_INPATIENT,
    SHIFT_ACTIVE,
    SHIFT_CLOSED,
    T_ADMIT,
    TAPER_ACTIVE,
    TRIAGE_CLOSED,
)
from test_helpers.test_users import (
    COORDINATOR,
    EPILEPTOLOGIST,
    EPILEPTOLOGIST_ID,
    EPILEPTOLOGIST_ID_2,
    EPILEPTOLOGIST_ID_3,
    TECHNOLOGIST,
    as_epileptologist,
)


def _bed_row(api, unit_id: str, bed_id: str, headers) -> Dict[str, Any]:
    """The current stored row of one bed, read back through its unit's listing."""
    rows, _meta = validate_paginated(
        api.list_unit_beds(unit_id, headers, {"limit": 50, "offset": 0})
    )
    matches = [row for row in rows if row["id"] == bed_id]
    assert matches, f"bed {bed_id} is missing from the listing of unit {unit_id}"
    return matches[0]


def test_admit_valid_transition_sets_both_state_dimensions(api):
    """Admitting moves the clinical and the authorization dimension in a single call.

    §3.3: "It moves `authorization_state` from `AUTH_PENDING` to `AUTH_ACTIVE`."

    Design: Corner/state_machines/admit_valid_transition_sets_both_state_dimensions
    """
    unit = fx.create_unit(
        api, name="EMU Corner Unit", bed_count=1, storage_quota_gb=500.00
    )
    bed = fx.create_bed(api, unit["id"], label="EMU-1")
    patient = fx.create_patient(
        api, mrn="MRN-C-20", display_name="Corner Twenty", risk_tier=RISK_LOW
    )
    authorization = fx.approved_authorization(
        api,
        patient["id"],
        requested_setting=SETTING_INPATIENT,
        requested_days=5,
        authorized_days=5,
        payer_note="5 days approved",
    )
    admission = fx.schedule_admission(
        api,
        patient_id=patient["id"],
        authorization_id=authorization["id"],
        unit_id=unit["id"],
        setting=SETTING_INPATIENT,
        scheduled_admit_at=T_ADMIT,
        target_event_count=3,
        planned_days=2,
    )
    fx.set_clock(api, T_ADMIT)

    response = api.admit(admission["id"], f.admit_payload(bed_id=bed["id"]), COORDINATOR)
    admitted = validate_success(response, 200)

    assert_admission_dimensions(admitted, CLINICAL_ADMITTED, AUTH_STATE_ACTIVE)
    assert_instant_equals(admitted["admitted_at"], T_ADMIT, "admitted_at")
    # planned_days 2 counted as 24-hour blocks from the admission instant (§3.3).
    assert_instant_equals(
        admitted["planned_discharge_at"], "2026-08-04T00:00:00Z", "planned_discharge_at"
    )
    assert admitted["bed_id"] == bed["id"]

    ledger = validate_success(
        api.get_authorization(authorization["id"], COORDINATOR), 200
    )
    assert_ledger(
        ledger,
        authorized_days=5,
        days_consumed=0,
        days_reserved=2,
        days_available=3,
    )

    occupied = _bed_row(api, unit["id"], bed["id"], COORDINATOR)
    assert occupied["status"] == BED_OCCUPIED
    assert occupied["current_admission_id"] == admission["id"]

    unit_after = validate_success(api.get_unit(unit["id"], COORDINATOR), 200)
    assert unit_after["beds_available"] == 0


def test_study_initial_state_is_preparing_online(api):
    """A new study seeds both of its parallel dimensions, not only the acquisition one.

    §3.5: "The study opens with `acquisition_state` at `PREPARING` and `data_state` at `ONLINE`, with `acquired_minutes`, `stored_gb`, `closed_segment_count` and `impedance_fail_count` at 0 and `shift_id`, `current_segment_started_at`, `completed_at`, `last_impedance_kohm` and `export_hold_reason` all null."

    Design: Corner/state_machines/study_initial_state_is_preparing_online
    """
    baseline = fx.build_admitted_stay(
        api,
        unit_name="EMU Corner Unit",
        bed_count=1,
        storage_quota_gb=500.00,
        mrn="MRN-C-21",
        display_name="Corner TwentyOne",
        risk_tier=RISK_MODERATE,
        requested_days=5,
        planned_days=2,
        target_event_count=3,
        admitted_at=T_ADMIT,
        with_shift=True,
        with_study=False,
    )

    study = validate_success(
        api.create_study(
            f.study_payload(
                baseline.admission_id, channel_count=32, modality=SETTING_INPATIENT
            ),
            TECHNOLOGIST,
        ),
        201,
    )

    assert_study_dimensions(study, ACQ_PREPARING, DATA_ONLINE)
    assert_fields_null(
        study,
        "shift_id",
        "current_segment_started_at",
        "completed_at",
        "last_impedance_kohm",
        "export_hold_reason",
    )
    assert study["closed_segment_count"] == 0
    assert study["impedance_fail_count"] == 0
    assert_version_is(study, 1, "study")

    # The shift stays unclaimed until the study is started (§3.5).
    shift = validate_success(api.get_shift(baseline.shift_id, TECHNOLOGIST), 200)
    assert shift["assigned_study_count"] == 0


def test_shift_close_with_assigned_studies_rejected(api):
    """A coverage window carrying an assigned study refuses to close until the study ends.

    §3.1: "Closing a window moves `state` from `ACTIVE` to `CLOSED` and likewise re-derives `coverage_capacity` and `posture` — but only if the window carries nothing: a window whose `assigned_study_count` is greater than zero is refused with `ERR_SHIFT_HAS_ACTIVE_STUDIES`."

    Design: Corner/state_machines/shift_close_with_assigned_studies_rejected
    """
    baseline = fx.build_acquiring_stay(
        api,
        unit_name="EMU Corner Unit",
        bed_count=1,
        storage_quota_gb=500.00,
        mrn="MRN-C-22",
        display_name="Corner TwentyTwo",
        risk_tier=RISK_MODERATE,
        requested_days=5,
        planned_days=2,
        target_event_count=3,
        admitted_at=T_ADMIT,
        started_at=T_ADMIT,
    )

    refused = api.close_shift(baseline.shift_id, COORDINATOR)
    validate_error(refused, ERR_SHIFT_HAS_ACTIVE_STUDIES, 409)

    still_open = validate_success(api.get_shift(baseline.shift_id, COORDINATOR), 200)
    assert still_open["state"] == SHIFT_ACTIVE
    assert still_open["assigned_study_count"] == 1

    fx.complete_study(api, baseline.study_id, at="2026-08-02T02:00:00Z")

    closed = validate_success(api.close_shift(baseline.shift_id, COORDINATOR), 200)
    assert closed["state"] == SHIFT_CLOSED
    assert closed["assigned_study_count"] == 0

    study = validate_success(api.get_study(baseline.study_id, TECHNOLOGIST), 200)
    assert study["acquisition_state"] == ACQ_COMPLETED
    # The pin to the window that recorded the study survives the close (§3.5).
    assert study["shift_id"] == baseline.shift_id


def test_taper_resume_from_active_is_invalid_transition(api):
    """Resuming a plan that was never held is a trigger the ACTIVE state does not accept.

    §3.4: "The plan must be `ACTIVE` — advancing a plan that is not, holding a plan that is not `ACTIVE`, or resuming a plan that is not `HELD`, are all `ERR_INVALID_TAPER_STATE`."

    Design: Corner/state_machines/taper_resume_from_active_is_invalid_transition
    """
    baseline = fx.build_admitted_stay(
        api,
        unit_name="EMU Corner Unit",
        bed_count=1,
        storage_quota_gb=500.00,
        mrn="MRN-C-23",
        display_name="Corner TwentyThree",
        risk_tier=RISK_MODERATE,
        requested_days=5,
        planned_days=2,
        target_event_count=3,
        admitted_at=T_ADMIT,
        with_shift=False,
        with_study=False,
    )
    plan = fx.create_taper_plan(api, baseline.admission_id, total_steps=3)
    assert plan["status"] == TAPER_ACTIVE

    response = api.resume_taper_plan(plan["id"], EPILEPTOLOGIST)

    validate_error(response, ERR_INVALID_TAPER_STATE, 409)

    unchanged = validate_success(api.get_taper_plan(plan["id"], EPILEPTOLOGIST), 200)
    assert unchanged["status"] == TAPER_ACTIVE
    assert unchanged["current_step"] == 0
    assert_fields_null(unchanged, "hold_reason")


def test_duplicate_alert_close_is_rejected(api):
    """Closing an alert twice is refused: the replayed close is not a no-op.

    §3.6: "The alert must be standing in `DETECTED`; adjudicating one that is not, or closing one that is still `DETECTED` or already `CLOSED`, is `ERR_INVALID_ALERT_STATE`."

    Design: Corner/state_machines/duplicate_alert_close_is_rejected
    """
    baseline = fx.build_acquiring_stay(
        api,
        unit_name="EMU Corner Unit",
        bed_count=1,
        storage_quota_gb=500.00,
        mrn="MRN-C-24",
        display_name="Corner TwentyFour",
        risk_tier=RISK_MODERATE,
        requested_days=5,
        planned_days=2,
        target_event_count=3,
        admitted_at=T_ADMIT,
        started_at=T_ADMIT,
    )
    alert = fx.raise_alert(api, baseline.study_id, at="2026-08-02T10:00:00Z")
    # A SUBCLINICAL adjudication needs no bedside intervention beforehand (§3.6).
    fx.adjudicate_alert(api, alert["id"], CLASSIFICATION_SUBCLINICAL)
    fx.close_alert(api, alert["id"])

    replayed = api.close_alert(alert["id"], EPILEPTOLOGIST)

    validate_error(replayed, ERR_INVALID_ALERT_STATE, 409)

    settled = validate_success(api.get_alert(alert["id"], EPILEPTOLOGIST), 200)
    assert_alert_dimensions(settled, TRIAGE_CLOSED, RESPONSE_AWAITING)
    assert_instant_equals(
        settled["adjudicated_at"], "2026-08-02T10:00:00Z", "adjudicated_at"
    )


def test_discharge_with_open_study_returns_4xx(api):
    """Discharge is refused while a study is still recording, and no side effect happens.

    §3.3: "In both cases the server first refuses if any study of the admission is still in `PREPARING`, `ACQUIRING` or `PAUSED`, with `ERR_OPEN_STUDY_ON_DISCHARGE`; discharging from any other clinical state is `ERR_INVALID_ADMISSION_STATE`."

    Design: Corner/state_machines/discharge_with_open_study_returns_4xx
    """
    baseline = fx.build_acquiring_stay(
        api,
        unit_name="EMU Corner Unit",
        bed_count=1,
        storage_quota_gb=500.00,
        mrn="MRN-C-25",
        display_name="Corner TwentyFive",
        risk_tier=RISK_MODERATE,
        requested_days=5,
        planned_days=2,
        target_event_count=3,
        admitted_at=T_ADMIT,
        started_at=T_ADMIT,
    )
    fx.set_clock(api, "2026-08-03T00:00:00Z")

    response = api.discharge(
        baseline.admission_id, f.discharge_payload(), COORDINATOR
    )

    validate_error(response, ERR_OPEN_STUDY_ON_DISCHARGE, 409)

    admission = validate_success(
        api.get_admission(baseline.admission_id, COORDINATOR), 200
    )
    assert_admission_dimensions(admission, CLINICAL_ADMITTED, AUTH_STATE_ACTIVE)
    assert_fields_null(admission, "discharged_at", "disposition")

    study = validate_success(api.get_study(baseline.study_id, TECHNOLOGIST), 200)
    assert study["acquisition_state"] == ACQ_ACQUIRING

    ledger = validate_success(
        api.get_authorization(baseline.authorization_id, COORDINATOR), 200
    )
    assert_ledger(ledger, days_consumed=0, days_reserved=2, days_available=3)

    bed = _bed_row(api, baseline.unit_id, baseline.bed_id, COORDINATOR)
    assert bed["status"] == BED_OCCUPIED
    assert_fields_null(bed, "released_at", "turnover_clear_at")


def test_final_report_terminal_state_locks_further_transitions(api):
    """Once the final interpretation is issued the report accepts no further trigger.

    §3.8: "Issuing the final interpretation moves `status` from `PRELIM_ISSUED` to `FINAL_ISSUED`, which is terminal, and its payload also carries `localization`."

    Design: Corner/state_machines/final_report_terminal_state_locks_further_transitions
    """
    baseline = fx.build_acquiring_stay(
        api,
        unit_name="EMU Corner Unit",
        bed_count=1,
        storage_quota_gb=500.00,
        mrn="MRN-C-26",
        display_name="Corner TwentySix",
        risk_tier=RISK_MODERATE,
        requested_days=5,
        planned_days=2,
        target_event_count=3,
        admitted_at=T_ADMIT,
        started_at=T_ADMIT,
    )
    fx.complete_study(api, baseline.study_id, at="2026-08-02T02:00:00Z")
    report = fx.report_of_study(api, baseline.study_id)
    fx.issue_prelim(
        api,
        report["id"],
        localization="LEFT_TEMPORAL",
        author_user_id=EPILEPTOLOGIST_ID,
        at="2026-08-02T12:00:00Z",
    )
    fx.issue_final(
        api,
        report["id"],
        localization="LEFT_TEMPORAL",
        author_user_id=EPILEPTOLOGIST_ID_2,
    )

    addendum = api.open_addendum(
        report["id"],
        f.addendum_payload(addendum_reason="LATE_REVIEW"),
        as_epileptologist(EPILEPTOLOGIST_ID_2),
    )
    validate_error(addendum, ERR_INVALID_REPORT_STATE, 409)

    reprelim = api.issue_prelim(
        report["id"],
        f.issue_prelim_payload(localization="RIGHT_TEMPORAL"),
        as_epileptologist(EPILEPTOLOGIST_ID),
    )
    validate_error(reprelim, ERR_INVALID_REPORT_STATE, 409)

    refinal = api.issue_final(
        report["id"],
        f.issue_final_payload(localization="RIGHT_TEMPORAL"),
        as_epileptologist(EPILEPTOLOGIST_ID_3),
    )
    validate_error(refinal, ERR_INVALID_REPORT_STATE, 409)

    locked = validate_success(api.get_report(report["id"], EPILEPTOLOGIST), 200)
    assert locked["status"] == REPORT_FINAL_ISSUED
    assert locked["addendum_count"] == 0
    assert_fields_null(locked, "addendum_reason")
    assert locked["prelim_author_user_id"] == EPILEPTOLOGIST_ID
    assert locked["final_author_user_id"] == EPILEPTOLOGIST_ID_2
    assert locked["localization"] == "LEFT_TEMPORAL"
    assert_instant_equals(
        locked["final_issued_at"], "2026-08-02T12:00:00Z", "final_issued_at"
    )


def test_marking_retraction_compensates_capture_target_cascade(api):
    """Retracting the only adjudicated event unwinds the whole capture-target cascade.

    §3.7: "A marking in `ADJUDICATED` moves to `RETRACTED`, storing the supplied `retraction_reason`, recomputing the admission's `weighted_event_count` and both capture-adequacy variants downward, possibly driving the admission from `CAPTURE_TARGET_MET` back to `ADMITTED` — which in turn returns that admission's `COMPLETED` taper plans whose `current_step` is short of `total_steps` to `ACTIVE` — and incrementing the marking's `version` by 1."

    Design: Corner/state_machines/marking_retraction_compensates_capture_target_cascade
    """
    baseline = fx.build_admitted_stay(
        api,
        unit_name="EMU Corner Unit",
        bed_count=1,
        storage_quota_gb=500.00,
        mrn="MRN-C-27",
        display_name="Corner TwentySeven",
        risk_tier=RISK_MODERATE,
        requested_days=5,
        planned_days=2,
        target_event_count=1,
        admitted_at=T_ADMIT,
        with_shift=False,
        with_study=False,
    )
    plan = fx.create_taper_plan(api, baseline.admission_id, total_steps=3)
    shift = fx.create_shift(
        api,
        baseline.unit_id,
        starts_at=T_ADMIT,
        ends_at="2026-08-10T00:00:00Z",
        max_concurrent_studies=2,
    )
    study = fx.create_study(api, baseline.admission_id, channel_count=32)
    fx.start_study(api, study["id"], shift["id"], at=T_ADMIT)
    fx.pause_study(api, study["id"], at="2026-08-02T02:00:00Z")
    marking = fx.create_marking(
        api,
        study["id"],
        "2026-08-02T01:00:00Z",
        event_class=EVENT_CLINICAL_SEIZURE,
        duration_seconds=95,
        adjudicate=False,
    )
    fx.set_clock(api, "2026-08-03T00:00:00Z")
    validate_success(api.adjudicate_marking(marking["id"], EPILEPTOLOGIST), 200)

    response = api.retract_marking(
        marking["id"],
        f.retract_marking_payload(retraction_reason="REVIEW_REVERSAL"),
        EPILEPTOLOGIST,
    )
    retracted = validate_success(response, 200)

    assert retracted["status"] == MARKING_RETRACTED
    assert retracted["retraction_reason"] == "REVIEW_REVERSAL"
    # The frozen weight stays on the retracted row (§3.7).
    assert_capture_value(retracted["weight"], 1.000, "marking weight")

    admission = validate_success(
        api.get_admission(baseline.admission_id, EPILEPTOLOGIST), 200
    )
    assert_capture_value(
        admission["weighted_event_count"], 0.000, "weighted_event_count"
    )
    assert_capture_value(
        admission["capture_adequacy_index"], 0.000, "capture_adequacy_index"
    )
    assert_capture_value(
        admission["capture_adequacy_index_prospective"],
        0.000,
        "capture_adequacy_index_prospective",
    )
    assert_capture_value(
        admission["projected_daily_yield"], 0.000, "projected_daily_yield"
    )
    assert_capture_value(admission["deficit_weighted"], 1.000, "deficit_weighted")
    assert_admission_dimensions(admission, CLINICAL_ADMITTED, AUTH_STATE_ACTIVE)

    reopened = validate_success(api.get_taper_plan(plan["id"], EPILEPTOLOGIST), 200)
    assert reopened["status"] == TAPER_ACTIVE
    assert reopened["current_step"] == 0

    ledger = validate_success(
        api.get_authorization(baseline.authorization_id, COORDINATOR), 200
    )
    assert_ledger(ledger, days_consumed=0, days_reserved=2, days_available=3)
