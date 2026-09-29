"""
Record shapes, seeded computed fields, request-shape rejections and listings.

Each test builds every precondition it needs through the public endpoints
against a freshly launched server whose logical clock stands at its startup
value, then exercises exactly one documented rule about the shape of a record,
the derivation of one of its fields, or the envelope of a list response.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_append_only_preamble,
    assert_capture_value,
    assert_fields_null,
    assert_full_preamble,
    assert_instant_equals,
    assert_storage_value,
    assert_unit_storage,
    assert_version_is,
    assert_whole_minutes,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_ADMISSION_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_PATIENT_NOT_FOUND,
    ERR_UNIT_NOT_FOUND,
)
from test_helpers.constants import (
    AUTH_STATE_PENDING,
    CLINICAL_SCHEDULED,
    CLOCK_STARTUP_UTC,
    DATA_ARCHIVED,
    DATA_ONLINE,
    DEFAULT_MARKING_DURATION_SECONDS,
    EVENT_CLINICAL_SEIZURE,
    INTERVENTION_POSITIONING,
    INTERVENTION_PHYSICIAN_NOTIFIED,
    INTERVENTION_RESCUE_MEDICATION,
    INTERVENTION_VITALS,
    MARKING_PROPOSED,
    POSTURE_OPEN,
    RESPONSE_ON_TIME,
    RISK_LOW,
    RISK_MODERATE,
    SETTING_INPATIENT,
    T_ADMIT,
)
from test_helpers.test_users import (
    COORDINATOR,
    EPILEPTOLOGIST,
    TECHNOLOGIST,
    as_nurse,
)

# Identifiers that resolve to nothing, used to probe foreign-key resolution.
UNKNOWN_PATIENT_ID = "33333333-3333-3333-3333-333333333333"
UNKNOWN_UNIT_ID = "44444444-4444-4444-4444-444444444444"


def test_create_monitoring_unit_returns_full_entity(api):
    """Creating a unit returns every declared field with its computed figures seeded.

    §3.1: "A newly created unit starts with `storage_used_gb` at 0, `storage_pressure_pct` at 0, `posture` at `OPEN` and `retention_sweep_index` at 0."

    Design: Corner/entities/create_monitoring_unit_returns_full_entity
    """
    response = api.create_unit(
        f.unit_payload(name="EMU Corner Unit", bed_count=3, storage_quota_gb=400.00),
        COORDINATOR,
    )
    unit = validate_success(response, 201)
    assert response.json()["response_type"] == "object"

    assert unit["name"] == "EMU Corner Unit"
    assert unit["bed_count"] == 3
    assert_storage_value(unit["storage_quota_gb"], 400.00, "storage_quota_gb")
    assert_unit_storage(
        unit, storage_used_gb=0, storage_pressure_pct=0, posture=POSTURE_OPEN
    )
    assert unit["beds_available"] == 0
    assert unit["late_response_count"] == 0
    assert unit["retention_sweep_index"] == 0

    assert_full_preamble(unit, "monitoring unit")
    assert_version_is(unit, 1, "monitoring unit")
    assert_instant_equals(unit["created_at"], CLOCK_STARTUP_UTC, "unit created_at")


def test_get_monitoring_unit_returns_stored_entity_with_derived_bed_count(api):
    """A unit's beds_available counts the beds actually created, not its declared bed_count.

    §2.11: "A unit also maintains `beds_available`, the count of its beds whose computed `status` is `AVAILABLE`, `late_response_count`, the number of alerts on its studies whose `response_state` is `RESPONDED_LATE`, and `retention_sweep_index`, which counts completed retention sweeps and increases by 1 with each one."

    Design: Corner/entities/get_monitoring_unit_returns_stored_entity_with_derived_bed_count
    """
    unit = fx.create_unit(
        api, name="EMU Corner Unit", bed_count=3, storage_quota_gb=400.00
    )
    fx.create_bed(api, unit["id"], label="EMU-1")
    fx.create_bed(api, unit["id"], label="EMU-2")

    stored = validate_success(api.get_unit(unit["id"], EPILEPTOLOGIST), 200)

    assert stored["name"] == "EMU Corner Unit"
    # The declared count stays 3 while only two bed records exist (§3.1).
    assert stored["bed_count"] == 3
    assert stored["beds_available"] == 2
    assert_unit_storage(
        stored, storage_used_gb=0, storage_pressure_pct=0, posture=POSTURE_OPEN
    )


def test_list_admissions_paginated_with_filters(api):
    """A filtered admission page reports the filtered total and whether more records remain.

    §2.3: "The response envelope's `meta` object for a list response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the size of the full filtered collection and `has_more` indicates whether records remain beyond the current page."

    Design: Corner/entities/list_admissions_paginated_with_filters
    """
    unit = fx.create_unit(
        api, name="EMU Corner Unit", bed_count=2, storage_quota_gb=400.00
    )
    patient_a = fx.create_patient(
        api, mrn="MRN-C-03A", display_name="Corner A", risk_tier=RISK_LOW
    )
    patient_b = fx.create_patient(
        api, mrn="MRN-C-03B", display_name="Corner B", risk_tier=RISK_MODERATE
    )
    auth_a = fx.approved_authorization(
        api, patient_a["id"], requested_days=6, payer_note="6 days"
    )
    auth_b = fx.approved_authorization(
        api, patient_b["id"], requested_days=3, payer_note="3 days"
    )
    for scheduled_at in ("2026-08-02T00:00:00Z", "2026-08-06T00:00:00Z"):
        fx.schedule_admission(
            api,
            patient_id=patient_a["id"],
            authorization_id=auth_a["id"],
            unit_id=unit["id"],
            scheduled_admit_at=scheduled_at,
            target_event_count=2,
            planned_days=2,
        )
    fx.schedule_admission(
        api,
        patient_id=patient_b["id"],
        authorization_id=auth_b["id"],
        unit_id=unit["id"],
        scheduled_admit_at="2026-08-03T00:00:00Z",
        target_event_count=1,
        planned_days=1,
    )

    first_page = api.list_admissions(
        COORDINATOR, {"patient_id": patient_a["id"], "limit": 1, "offset": 0}
    )
    rows, meta = validate_paginated(first_page)
    assert first_page.json()["response_type"] == "array"
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert len(rows) == 1
    assert rows[0]["patient_id"] == patient_a["id"]

    pending_rows, pending_meta = validate_paginated(
        api.list_admissions(
            COORDINATOR,
            {"authorization_state": AUTH_STATE_PENDING, "limit": 10, "offset": 0},
        )
    )
    assert pending_meta["total_count"] == 3
    assert pending_meta["has_more"] is False
    assert len(pending_rows) == 3
    for row in pending_rows:
        assert row["authorization_state"] == AUTH_STATE_PENDING
        assert row["clinical_state"] == CLINICAL_SCHEDULED


def test_get_patient_with_unknown_id_returns_not_found(api):
    """Reading a patient by an identifier that resolves to nothing is a 404, not an empty body.

    §2.6: "Every identifier embedded in the URL path resolves to an existing record, validated left to right, otherwise the 404 matching the first unresolvable segment: `ERR_UNIT_NOT_FOUND`, `ERR_BED_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_ADMISSION_NOT_FOUND`, `ERR_TAPER_PLAN_NOT_FOUND`, `ERR_STUDY_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_MARKING_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_EXPORT_NOT_FOUND` or `ERR_CASE_NOT_FOUND`."

    Design: Corner/entities/get_patient_with_unknown_id_returns_not_found
    """
    # One unrelated patient exists, so the 404 is about the requested id.
    fx.create_patient(
        api, mrn="MRN-C-04", display_name="Corner Four", risk_tier=RISK_LOW
    )

    response = api.get_patient(NON_EXISTENT_UUID, COORDINATOR)

    validate_error(response, ERR_PATIENT_NOT_FOUND, 404)
    assert response.json()["response_type"] == "error"


def test_create_authorization_missing_required_field_rejected(api):
    """Drafting an authorization without its required requested_days is refused outright.

    §2.6: "The body and query string parse, required fields are present, every enum value is a member of its declared set, and every number respects its declared range, otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/create_authorization_missing_required_field_rejected
    """
    patient = fx.create_patient(
        api, mrn="MRN-C-05", display_name="Corner Five", risk_tier=RISK_LOW
    )

    # `requested_days` is a declared input of the draft with no default (§3.2).
    response = api.create_authorization(
        f.authorization_payload(
            patient["id"], requested_setting=SETTING_INPATIENT, requested_days=None
        ),
        COORDINATOR,
    )

    validate_error(response, ERR_INVALID_REQUEST, 400)

    _rows, meta = validate_paginated(
        api.list_patient_authorizations(
            patient["id"], COORDINATOR, {"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 0


def test_patient_risk_tier_invalid_enum_rejected(api):
    """A risk_tier outside the declared set is refused when registering a patient.

    §3.2: "Patients are registered by the coordinator with an `mrn` that is unique across all patients, a `display_name`, and a `risk_tier` of `LOW`, `MODERATE` or `HIGH`."

    Design: Corner/entities/patient_risk_tier_invalid_enum_rejected
    """
    response = api.create_patient(
        f.patient_payload(
            mrn="MRN-C-09", display_name="Corner Nine", risk_tier="EXTREME"
        ),
        COORDINATOR,
    )

    # Enum membership is checked at the request-shape rung of §2.6.
    validate_error(response, ERR_INVALID_REQUEST, 400)
    assert response.json()["response_type"] == "error"


def test_create_study_below_minimum_channel_count_rejected(api):
    """A study declaring fewer channels than the declared minimum is refused and stored nowhere.

    §3.5: "A technologist creates a study against an `admission_id`, declaring a `channel_count` of at least 8 and a `modality` of `INPATIENT_VEEG` or `AMBULATORY_VEEG`."

    Design: Corner/entities/create_study_below_minimum_channel_count_rejected
    """
    baseline = fx.build_admitted_stay(
        api,
        unit_name="EMU Corner Unit",
        bed_count=1,
        storage_quota_gb=500.00,
        mrn="MRN-C-09B",
        display_name="Corner Nine B",
        risk_tier=RISK_MODERATE,
        requested_days=5,
        planned_days=2,
        target_event_count=2,
        admitted_at=T_ADMIT,
        with_shift=False,
        with_study=False,
    )

    response = api.create_study(
        f.study_payload(
            baseline.admission_id, channel_count=4, modality=SETTING_INPATIENT
        ),
        TECHNOLOGIST,
    )

    validate_error(response, ERR_INVALID_REQUEST, 400)

    _rows, meta = validate_paginated(
        api.list_studies(
            TECHNOLOGIST,
            {"admission_id": baseline.admission_id, "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 0


def test_marking_duration_seconds_default_applied(api):
    """Omitting duration_seconds stores the declared default and leaves alert_id null.

    §3.7: "Two payload fields are optional: `duration_seconds`, the event duration in seconds, which must be at least 1 and defaults to 60 when omitted; and `alert_id`, pointing at the alert this marking substantiates, which is null for a review-time marking that no alert produced."

    Design: Corner/entities/marking_duration_seconds_default_applied
    """
    baseline = fx.build_acquiring_stay(
        api,
        unit_name="EMU Corner Unit",
        bed_count=1,
        storage_quota_gb=500.00,
        mrn="MRN-C-06",
        display_name="Corner Six",
        risk_tier=RISK_MODERATE,
        requested_days=5,
        planned_days=2,
        target_event_count=4,
        admitted_at=T_ADMIT,
        started_at=T_ADMIT,
    )
    # One closed segment [00:00, 02:00) so the onset falls inside the recording.
    fx.pause_study(api, baseline.study_id, at="2026-08-02T02:00:00Z")

    response = api.create_marking(
        f.marking_payload(
            baseline.study_id,
            "2026-08-02T01:00:00Z",
            event_class=EVENT_CLINICAL_SEIZURE,
            duration_seconds=None,
        ),
        EPILEPTOLOGIST,
    )
    marking = validate_success(response, 201)

    assert marking["duration_seconds"] == DEFAULT_MARKING_DURATION_SECONDS
    assert marking["status"] == MARKING_PROPOSED
    assert marking["taper_step_at_onset"] == 0
    # No taper plan exists, so the provoked-event discount does not apply (§3.7).
    assert_capture_value(marking["weight"], 1.000, "marking weight")
    assert_fields_null(marking, "alert_id")

    admission = validate_success(
        api.get_admission(baseline.admission_id, EPILEPTOLOGIST), 200
    )
    assert_capture_value(
        admission["weighted_event_count"], 0.000, "weighted_event_count"
    )


def test_study_stored_gb_computed_field_input_ignored(api):
    """Client-supplied storage figures are ignored: a new study is derived from its closed segments.

    §3.5: "The storage volume of a study is derived from its closed segments alone, and the order of rounding is part of the contract because it changes the answer."

    Design: Corner/entities/study_stored_gb_computed_field_input_ignored
    """
    baseline = fx.build_admitted_stay(
        api,
        unit_name="EMU Corner Unit",
        bed_count=1,
        storage_quota_gb=500.00,
        mrn="MRN-C-07",
        display_name="Corner Seven",
        risk_tier=RISK_MODERATE,
        requested_days=5,
        planned_days=2,
        target_event_count=4,
        admitted_at=T_ADMIT,
        with_shift=False,
        with_study=False,
    )

    study = validate_success(
        api.create_study(
            f.study_payload(
                baseline.admission_id,
                channel_count=32,
                modality=SETTING_INPATIENT,
                stored_gb=999.99,
                acquired_minutes=5000,
                data_state=DATA_ARCHIVED,
            ),
            TECHNOLOGIST,
        ),
        201,
    )

    assert_storage_value(study["stored_gb"], 0, "study stored_gb")
    assert_whole_minutes(study["acquired_minutes"], 0, "acquired_minutes")
    assert study["closed_segment_count"] == 0
    # The opening data_state of §3.5, not the value offered in the payload.
    assert study["data_state"] == DATA_ONLINE
    assert study["channel_count"] == 32
    assert study["modality"] == SETTING_INPATIENT

    unit = validate_success(api.get_unit(baseline.unit_id, COORDINATOR), 200)
    assert_unit_storage(unit, storage_used_gb=0, storage_pressure_pct=0)


def test_intervention_system_fields_generated_and_input_ignored(api):
    """A bedside intervention takes its operator and instant from the request, not the payload.

    §3.6: "The server stamps `nurse_user_id` from the acting `X-User-ID` and `recorded_at` from the logical clock."

    Design: Corner/entities/intervention_system_fields_generated_and_input_ignored
    """
    baseline = fx.build_acquiring_stay(
        api,
        unit_name="EMU Corner Unit",
        bed_count=1,
        storage_quota_gb=500.00,
        mrn="MRN-C-08",
        display_name="Corner Eight",
        risk_tier=RISK_MODERATE,
        requested_days=5,
        planned_days=2,
        target_event_count=4,
        admitted_at=T_ADMIT,
        started_at=T_ADMIT,
    )
    alert = fx.raise_alert(api, baseline.study_id, at="2026-08-02T00:10:00Z")
    fx.set_clock(api, "2026-08-02T00:14:00Z")

    intervention = validate_success(
        api.record_intervention(
            alert["id"],
            f.intervention_payload(
                interventions=[INTERVENTION_POSITIONING, INTERVENTION_VITALS],
                injury_observed=False,
                rescue_med_given=False,
                nurse_user_id="spoofed-nurse",
                recorded_at="2020-01-01T00:00:00Z",
            ),
            as_nurse("nurse-7"),
        ),
        201,
    )

    assert intervention["nurse_user_id"] == "nurse-7"
    assert_instant_equals(
        intervention["recorded_at"], "2026-08-02T00:14:00Z", "recorded_at"
    )
    assert_append_only_preamble(intervention, "safety intervention")

    settled = validate_success(api.get_alert(alert["id"], EPILEPTOLOGIST), 200)
    # MODERATE base 6, no taper step, posture OPEN, detected in an overnight hour.
    assert settled["response_deadline_minutes"] == 7
    assert_instant_equals(
        settled["responded_at"], "2026-08-02T00:14:00Z", "alert responded_at"
    )
    assert_whole_minutes(settled["latency_minutes"], 4, "latency_minutes")
    assert settled["response_state"] == RESPONSE_ON_TIME


def test_safety_intervention_is_immutable_append_only_record(api):
    """A second bedside intervention appends a row and leaves the first one and the latency alone.

    §3.6: "Interventions are append-only evidence: more than one may be documented per alert, they are listable, and they are never edited."

    Design: Corner/entities/safety_intervention_is_immutable_append_only_record
    """
    baseline = fx.build_acquiring_stay(
        api,
        unit_name="EMU Corner Unit",
        bed_count=1,
        storage_quota_gb=500.00,
        mrn="MRN-C-10",
        display_name="Corner Ten",
        risk_tier=RISK_MODERATE,
        requested_days=5,
        planned_days=2,
        target_event_count=4,
        admitted_at=T_ADMIT,
        started_at=T_ADMIT,
    )
    alert = fx.raise_alert(api, baseline.study_id, at="2026-08-02T00:10:00Z")
    first = fx.record_intervention(
        api,
        alert["id"],
        interventions=[INTERVENTION_POSITIONING],
        nurse_user_id="nurse-7",
        at="2026-08-02T00:14:00Z",
    )
    fx.set_clock(api, "2026-08-02T00:20:00Z")

    second = validate_success(
        api.record_intervention(
            alert["id"],
            f.intervention_payload(
                interventions=[
                    INTERVENTION_RESCUE_MEDICATION,
                    INTERVENTION_PHYSICIAN_NOTIFIED,
                ],
                injury_observed=True,
                rescue_med_given=True,
            ),
            as_nurse("nurse-9"),
        ),
        201,
    )
    assert second["id"] != first["id"]

    rows, meta = validate_paginated(
        api.list_alert_interventions(
            alert["id"], EPILEPTOLOGIST, {"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 2
    by_id = {row["id"]: row for row in rows}
    assert set(by_id) == {first["id"], second["id"]}

    kept = by_id[first["id"]]
    assert kept["interventions"] == [INTERVENTION_POSITIONING]
    assert kept["injury_observed"] is False
    assert kept["rescue_med_given"] is False

    appended = by_id[second["id"]]
    assert appended["nurse_user_id"] == "nurse-9"
    assert_instant_equals(
        appended["recorded_at"], "2026-08-02T00:20:00Z", "second recorded_at"
    )
    for row in rows:
        # The reduced preamble of §2.5: no updated_at and no version.
        assert_append_only_preamble(row, "safety intervention")

    settled = validate_success(api.get_alert(alert["id"], EPILEPTOLOGIST), 200)
    assert_instant_equals(
        settled["responded_at"], "2026-08-02T00:14:00Z", "alert responded_at"
    )
    assert_whole_minutes(settled["latency_minutes"], 4, "latency_minutes")
    assert settled["response_state"] == RESPONSE_ON_TIME

    unit = validate_success(api.get_unit(baseline.unit_id, COORDINATOR), 200)
    assert unit["late_response_count"] == 0


def test_taper_plan_with_unknown_admission_returns_not_found(api):
    """A taper plan cannot be created against an admission_id that resolves to nothing.

    §2.6: "Every foreign key supplied in the request body resolves, validated in the order the endpoint declares its input fields, otherwise the corresponding 404 from the set `ERR_PATIENT_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_BED_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`, `ERR_ADMISSION_NOT_FOUND`, `ERR_STUDY_NOT_FOUND`, `ERR_ALERT_NOT_FOUND` or `ERR_EXPORT_NOT_FOUND`."

    Design: Corner/entities/taper_plan_with_unknown_admission_returns_not_found
    """
    response = api.create_taper_plan(
        f.taper_plan_payload(NON_EXISTENT_UUID, total_steps=3), EPILEPTOLOGIST
    )

    validate_error(response, ERR_ADMISSION_NOT_FOUND, 404)


def test_admission_create_validates_foreign_keys_in_declared_order(api):
    """Two unresolvable foreign keys surface the one the endpoint declares first.

    §2.6: "Every foreign key supplied in the request body resolves, validated in the order the endpoint declares its input fields, otherwise the corresponding 404 from the set `ERR_PATIENT_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_BED_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`, `ERR_ADMISSION_NOT_FOUND`, `ERR_STUDY_NOT_FOUND`, `ERR_ALERT_NOT_FOUND` or `ERR_EXPORT_NOT_FOUND`."

    Design: Corner/entities/admission_create_validates_foreign_keys_in_declared_order
    """
    patient = fx.create_patient(
        api, mrn="MRN-C-12", display_name="Corner Twelve", risk_tier=RISK_LOW
    )
    authorization = fx.approved_authorization(api, patient["id"], requested_days=5)

    # `patient_id` precedes `unit_id` in the declared input order of §3.3.
    both_unknown = api.create_admission(
        f.admission_payload(
            UNKNOWN_PATIENT_ID,
            authorization["id"],
            UNKNOWN_UNIT_ID,
            setting=SETTING_INPATIENT,
            scheduled_admit_at=T_ADMIT,
            target_event_count=2,
            planned_days=2,
        ),
        COORDINATOR,
    )
    validate_error(both_unknown, ERR_PATIENT_NOT_FOUND, 404)

    unit_unknown = api.create_admission(
        f.admission_payload(
            patient["id"],
            authorization["id"],
            UNKNOWN_UNIT_ID,
            setting=SETTING_INPATIENT,
            scheduled_admit_at=T_ADMIT,
            target_event_count=2,
            planned_days=2,
        ),
        COORDINATOR,
    )
    validate_error(unit_unknown, ERR_UNIT_NOT_FOUND, 404)

    _rows, meta = validate_paginated(
        api.list_admissions(COORDINATOR, {"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 0
