"""
Role authority: three roles reaching past their authorized endpoints, the nurse
pathway that is genuinely theirs, and the reporting segregation of duties that
looks past the role to the acting operator identity.

Each rejected request is otherwise well formed and well sequenced, so the
authority rung is the first one it reaches.
"""

from test_helpers import (
    assert_alert_dimensions,
    assert_capture_value,
    assert_fields_null,
    assert_ids_equal,
    assert_instant_equals,
    assert_ledger,
    assert_turnaround_value,
    assert_version_is,
    assert_whole_minutes,
    constants as c,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ERR_ROLE_NOT_PERMITTED, ERR_SEGREGATION_OF_DUTIES
from test_helpers.test_users import (
    COORDINATOR,
    EPILEPTOLOGIST,
    NURSE,
    PAYER_REVIEWER,
    TECHNOLOGIST,
    as_epileptologist,
)


def test_technologist_may_not_adjudicate_an_alert(api):
    """Alert adjudication is reserved to the epileptologist role.

    PRD §2.1: "Once authentication succeeds, authority is checked against the operation being attempted: a role that is not listed among the authorized roles for the target endpoint in §4 is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/technologist_cannot_adjudicate_alert
    """
    stay = fx.build_acquiring_stay(
        api,
        started_at="2026-08-02T00:00:00Z",
        unit_name="EMU Authority",
        bed_count=1,
        storage_quota_gb=500.00,
        risk_tier=c.RISK_MODERATE,
        planned_days=2,
        target_event_count=2,
        channel_count=32,
    )
    alert = fx.raise_alert(
        api,
        stay.study_id,
        source=c.ALERT_SOURCE_ALGORITHM,
        at="2026-08-02T10:00:00Z",
    )

    response = api.adjudicate_alert(
        alert["id"],
        f.adjudicate_alert_payload(c.CLASSIFICATION_CLINICAL),
        TECHNOLOGIST,
    )

    validate_error(response, ERR_ROLE_NOT_PERMITTED)

    unchanged = validate_success(api.get_alert(alert["id"], TECHNOLOGIST))
    assert unchanged["triage_state"] == c.TRIAGE_DETECTED, (
        f"the refused adjudication leaves triage_state at DETECTED, "
        f"got {unchanged['triage_state']!r}"
    )
    assert_fields_null(unchanged, "adjudicated_at")
    assert_whole_minutes(
        unchanged["response_deadline_minutes"], 6, "response_deadline_minutes"
    )

    admission = validate_success(api.get_admission(stay.admission_id, EPILEPTOLOGIST))
    assert_capture_value(admission["weighted_event_count"], 0.000, "weighted_event_count")


def test_payer_reviewer_may_not_admit_a_patient(api):
    """Admitting a scheduled stay is reserved to the unit coordinator role.

    PRD §2.1: "Once authentication succeeds, authority is checked against the operation being attempted: a role that is not listed among the authorized roles for the target endpoint in §4 is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/payer_reviewer_cannot_admit_patient
    """
    unit = fx.create_unit(api, name="EMU Admit Guard", bed_count=1, storage_quota_gb=500.00)
    bed = fx.create_bed(api, unit["id"], label="EMU-1")
    patient = fx.create_patient(api, display_name="Pat Guarded", risk_tier=c.RISK_MODERATE)
    authorization = fx.approved_authorization(
        api,
        patient["id"],
        requested_setting=c.SETTING_INPATIENT,
        requested_days=5,
        authorized_days=5,
    )
    admission = fx.schedule_admission(
        api,
        patient_id=patient["id"],
        authorization_id=authorization["id"],
        unit_id=unit["id"],
        setting=c.SETTING_INPATIENT,
        scheduled_admit_at="2026-08-02T00:00:00Z",
        target_event_count=4,
        planned_days=2,
    )
    fx.set_clock(api, "2026-08-02T00:00:00Z")

    response = api.admit(admission["id"], f.admit_payload(bed["id"]), PAYER_REVIEWER)

    validate_error(response, ERR_ROLE_NOT_PERMITTED)

    unchanged = validate_success(api.get_admission(admission["id"], COORDINATOR))
    assert unchanged["clinical_state"] == c.CLINICAL_SCHEDULED, (
        f"the refused admission leaves clinical_state at SCHEDULED, "
        f"got {unchanged['clinical_state']!r}"
    )
    assert_fields_null(unchanged, "admitted_at")
    assert_version_is(unchanged, 1, "admission")

    ledger = validate_success(api.get_authorization(authorization["id"], COORDINATOR))
    assert_ledger(ledger, authorized_days=5, days_reserved=0, days_available=5)

    beds, _ = validate_paginated(
        api.list_unit_beds(unit["id"], COORDINATOR, params={"limit": 10, "offset": 0})
    )
    assert_ids_equal(beds[0]["id"], bed["id"], "listed bed id")
    assert beds[0]["status"] == c.BED_AVAILABLE, (
        f"the bed is never taken, so it stays AVAILABLE, got {beds[0]['status']!r}"
    )


def test_unit_coordinator_may_not_record_a_payer_decision(api):
    """Recording the payer's decision is reserved to the payer reviewer role.

    PRD §2.1: "Once authentication succeeds, authority is checked against the operation being attempted: a role that is not listed among the authorized roles for the target endpoint in §4 is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/rbac/unit_coordinator_cannot_record_payer_decision
    """
    fx.create_unit(api, name="EMU Funding Guard", bed_count=1, storage_quota_gb=500.00)
    patient = fx.create_patient(api, display_name="Pat Ambulatory", risk_tier=c.RISK_LOW)
    authorization = fx.submitted_authorization(
        api,
        patient["id"],
        requested_setting=c.SETTING_AMBULATORY,
        requested_days=3,
    )

    response = api.record_payer_decision(
        authorization["id"],
        f.payer_decision_payload(
            outcome=c.OUTCOME_APPROVE,
            authorized_days=3,
            authorized_setting=c.SETTING_AMBULATORY,
            payer_note="approved",
        ),
        COORDINATOR,
    )

    validate_error(response, ERR_ROLE_NOT_PERMITTED)

    unchanged = validate_success(api.get_authorization(authorization["id"], COORDINATOR))
    assert unchanged["status"] == c.AUTH_SUBMITTED, (
        f"the refused decision leaves the request SUBMITTED, got {unchanged['status']!r}"
    )
    assert_ledger(unchanged, authorized_days=0, days_available=0)
    assert_fields_null(unchanged, "authorized_setting")
    assert_version_is(unchanged, 2, "authorization")


def test_nurse_raises_an_alert_and_documents_the_bedside_response(api):
    """The nurse pathway through alert raising and intervention recording succeeds.

    PRD §3.6: "An alert may be raised on a study by a technologist, a nurse or an epileptologist, and its payload carries only a `source` of `ALGORITHM`, `TECHNOLOGIST` or `PATIENT_PUSH_BUTTON`."
    PRD §3.6: "If that latency is less than or equal to `response_deadline_minutes` — equality counts as on time — `response_state` moves from `AWAITING_RESPONSE` to `RESPONDED_ON_TIME`."

    Design: Corner/rbac/nurse_can_raise_alert_and_record_intervention
    """
    stay = fx.build_acquiring_stay(
        api,
        started_at="2026-08-02T00:00:00Z",
        unit_name="EMU Nurse",
        bed_count=1,
        storage_quota_gb=500.00,
        risk_tier=c.RISK_MODERATE,
        planned_days=2,
        target_event_count=2,
        channel_count=32,
    )
    fx.set_clock(api, "2026-08-02T10:00:00Z")

    alert = validate_success(
        api.raise_alert(
            stay.study_id,
            f.alert_payload(c.ALERT_SOURCE_PATIENT_PUSH_BUTTON),
            NURSE,
        ),
        expected_status=201,
    )
    assert_whole_minutes(
        alert["response_deadline_minutes"], 6, "response_deadline_minutes"
    )

    intervention = validate_success(
        api.record_intervention(
            alert["id"],
            f.intervention_payload(
                interventions=[
                    c.INTERVENTION_POSITIONING,
                    c.INTERVENTION_SEIZURE_TESTING,
                ],
                injury_observed=False,
                rescue_med_given=False,
            ),
            NURSE,
        ),
        expected_status=201,
    )
    assert_instant_equals(
        intervention["recorded_at"], "2026-08-02T10:00:00Z", "recorded_at"
    )
    assert intervention["injury_observed"] is False, (
        f"injury_observed should be stored as supplied, got {intervention['injury_observed']!r}"
    )
    assert intervention["rescue_med_given"] is False, (
        "rescue_med_given should be stored as supplied, "
        f"got {intervention['rescue_med_given']!r}"
    )

    settled = validate_success(api.get_alert(alert["id"], NURSE))
    assert_instant_equals(settled["responded_at"], "2026-08-02T10:00:00Z", "responded_at")
    assert_whole_minutes(settled["latency_minutes"], 0, "latency_minutes")
    assert_alert_dimensions(settled, c.TRIAGE_DETECTED, c.RESPONSE_ON_TIME)

    unit = validate_success(api.get_unit(stay.unit_id, COORDINATOR))
    assert unit["late_response_count"] == 0, (
        f"an on-time response leaves late_response_count at 0, got {unit['late_response_count']!r}"
    )


def test_final_interpretation_by_the_preliminary_author_is_refused(api):
    """The operator who issued the preliminary read cannot issue the final one.

    PRD §3.8: "The acting `X-User-ID` must differ from `prelim_author_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`: two epileptologists must have looked at the recording."

    Design: Corner/rbac/final_report_by_prelim_author_is_rejected
    """
    stay = fx.build_admitted_stay(
        api,
        unit_name="EMU Duties",
        bed_count=1,
        storage_quota_gb=500.00,
        planned_days=2,
        target_event_count=2,
        channel_count=32,
    )
    fx.acquire_and_complete(
        api,
        stay.study_id,
        stay.shift_id,
        from_iso="2026-08-02T00:00:00Z",
        to_iso="2026-08-02T02:00:00Z",
    )
    report = fx.report_of_study(api, stay.study_id)
    fx.issue_prelim(
        api,
        report["id"],
        localization="LEFT_TEMPORAL",
        author_user_id="epi-1",
        at="2026-08-02T12:00:00Z",
    )

    response = api.issue_final(
        report["id"],
        f.issue_final_payload("LEFT_TEMPORAL"),
        as_epileptologist("epi-1"),
    )

    validate_error(response, ERR_SEGREGATION_OF_DUTIES)

    unchanged = validate_success(api.get_report(report["id"], EPILEPTOLOGIST))
    assert unchanged["status"] == c.REPORT_PRELIM_ISSUED, (
        f"the refused finalization leaves the report PRELIM_ISSUED, "
        f"got {unchanged['status']!r}"
    )
    assert_fields_null(unchanged, "final_issued_at", "final_author_user_id")
    assert_ids_equal(
        unchanged["prelim_author_user_id"], "epi-1", "prelim_author_user_id"
    )
    assert_instant_equals(
        unchanged["prelim_issued_at"], "2026-08-02T12:00:00Z", "prelim_issued_at"
    )
    # 02:00 to 12:00 is 10 calendar hours, of which only 08:00 to 12:00 falls
    # inside the reading window.
    assert_turnaround_value(
        unchanged["turnaround_calendar_hours"], 10.00, "turnaround_calendar_hours"
    )
    assert_turnaround_value(
        unchanged["turnaround_coverage_hours"], 4.00, "turnaround_coverage_hours"
    )
    assert unchanged["sla_breached"] is False, (
        f"4 coverage hours is not a breach of the eight-hour level, "
        f"got sla_breached {unchanged['sla_breached']!r}"
    )
