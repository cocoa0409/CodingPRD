"""
Version discipline and read-after-write consistency: the optimistic-concurrency
token on extension decisions, the version counter of the funding ledger, the
unit-level late-response tally that reconciles after each bedside response, and
the derived storage figures a unit exposes immediately after a segment closes.
"""

from test_helpers import (
    assert_alert_dimensions,
    assert_capture_value,
    assert_fields_null,
    assert_ledger,
    assert_storage_value,
    assert_unit_storage,
    assert_version_is,
    assert_whole_minutes,
    constants as c,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ERR_STALE_ADMISSION_VERSION
from test_helpers.test_users import (
    COORDINATOR,
    EPILEPTOLOGIST,
    NURSE,
    PAYER_REVIEWER,
    TECHNOLOGIST,
)


def test_extension_decision_with_a_stale_admission_version_is_refused(api):
    """A version token read before a cascade no longer matches the admission.

    PRD §2.7: "If that value does not equal the admission's current `version`, the request is rejected with `ERR_STALE_ADMISSION_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_admission_version_on_extension_returns_412
    """
    stay = fx.build_admitted_stay(
        api,
        unit_name="EMU Concurrency",
        bed_count=1,
        storage_quota_gb=500.00,
        risk_tier=c.RISK_MODERATE,
        requested_days=5,
        planned_days=2,
        target_event_count=4,
        with_shift=False,
        with_study=False,
    )
    stale_version = stay.admission["version"]

    shift = fx.create_shift(
        api,
        stay.unit_id,
        starts_at="2026-08-02T00:00:00Z",
        ends_at="2026-08-10T00:00:00Z",
        max_concurrent_studies=2,
        activate=True,
    )
    study = fx.create_study(
        api, stay.admission_id, channel_count=32, modality=c.SETTING_INPATIENT
    )
    fx.start_study(api, study["id"], shift["id"], at="2026-08-02T00:00:00Z")
    fx.pause_study(api, study["id"], at="2026-08-02T02:00:00Z")

    fx.set_clock(api, "2026-08-03T00:00:00Z")
    # Banking the marking's weight cascades into the admission's capture figures,
    # which moves the admission's own version past the token read above.
    fx.create_marking(
        api,
        study["id"],
        "2026-08-02T01:00:00Z",
        event_class=c.EVENT_CLINICAL_SEIZURE,
        adjudicate=True,
    )
    response = api.record_extension_decision(
        stay.admission_id, f.extension_payload(stale_version), EPILEPTOLOGIST
    )

    validate_error(response, ERR_STALE_ADMISSION_VERSION)

    unchanged = validate_success(api.get_admission(stay.admission_id, EPILEPTOLOGIST))
    assert unchanged["extension_count"] == 0, (
        f"the refused decision records no extension, got {unchanged['extension_count']!r}"
    )
    assert_fields_null(unchanged, "last_extension_outcome")
    assert_capture_value(
        unchanged["weighted_event_count"], 1.000, "weighted_event_count"
    )
    # One full-weight clinical seizure against a target of four events.
    assert_capture_value(
        unchanged["capture_adequacy_index"], 0.250, "capture_adequacy_index"
    )

    ledger = validate_success(api.get_authorization(stay.authorization_id, COORDINATOR))
    assert_ledger(ledger, authorized_days=5, days_reserved=2, days_available=3)


def test_authorization_version_increments_on_every_write(api):
    """Draft, submission and a PEND decision leave the request at version 3.

    PRD §2.5: "`version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that record, including server-initiated cascade mutations that no client requested directly."
    PRD §3.2: "Every one of these transitions increments the authorization request's own `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/authorization_version_increments_on_every_write
    """
    fx.create_unit(api, name="EMU Versioning", bed_count=1, storage_quota_gb=500.00)
    patient = fx.create_patient(api, display_name="Pat Pended", risk_tier=c.RISK_LOW)
    authorization = fx.submitted_authorization(
        api,
        patient["id"],
        requested_setting=c.SETTING_AMBULATORY,
        requested_days=3,
    )

    validate_success(
        api.record_payer_decision(
            authorization["id"],
            f.payer_decision_payload(
                outcome=c.OUTCOME_PEND,
                authorized_days=None,
                authorized_setting=None,
                payer_note="need seizure diary",
            ),
            PAYER_REVIEWER,
        )
    )

    pended = validate_success(api.get_authorization(authorization["id"], COORDINATOR))
    assert_version_is(pended, 3, "authorization")
    assert pended["status"] == c.AUTH_PENDED, (
        f"a PEND outcome moves the request to PENDED, got {pended['status']!r}"
    )
    assert pended["payer_note"] == "need seizure diary", (
        f"the PEND outcome stores the supplied payer_note, got {pended['payer_note']!r}"
    )
    assert pended["resubmission_count"] == 0, (
        "pending a request does not itself count as a resubmission, "
        f"got {pended['resubmission_count']!r}"
    )
    assert_ledger(pended, authorized_days=0, days_available=0)
    assert_fields_null(pended, "authorized_setting")


def test_unit_late_response_count_reconciles_after_each_response(api):
    """A late response raises the unit tally; a later on-time response leaves it.

    PRD §3.6: "If the latency is strictly greater, `response_state` moves to `RESPONDED_LATE` and, additionally, the unit's `late_response_count` increases by 1."

    Design: Corner/cross_cutting_complexity_layers/unit_late_response_count_reconciles_after_each_response
    """
    stay = fx.build_acquiring_stay(
        api,
        started_at="2026-08-02T00:00:00Z",
        unit_name="EMU Latency",
        bed_count=1,
        storage_quota_gb=500.00,
        risk_tier=c.RISK_MODERATE,
        planned_days=2,
        target_event_count=4,
        channel_count=32,
    )

    late_alert = fx.raise_alert(
        api,
        stay.study_id,
        source=c.ALERT_SOURCE_ALGORITHM,
        at="2026-08-02T10:00:00Z",
    )
    assert_whole_minutes(
        late_alert["response_deadline_minutes"], 6, "response_deadline_minutes"
    )
    fx.record_intervention(api, late_alert["id"], at="2026-08-02T10:20:00Z")

    settled_late = validate_success(api.get_alert(late_alert["id"], NURSE))
    assert_whole_minutes(settled_late["latency_minutes"], 20, "latency_minutes")
    assert_alert_dimensions(settled_late, c.TRIAGE_DETECTED, c.RESPONSE_LATE)

    after_late = validate_success(api.get_unit(stay.unit_id, COORDINATOR))
    assert after_late["late_response_count"] == 1, (
        f"one late response raises late_response_count to 1, "
        f"got {after_late['late_response_count']!r}"
    )

    prompt_alert = validate_success(
        api.raise_alert(
            stay.study_id, f.alert_payload(c.ALERT_SOURCE_ALGORITHM), TECHNOLOGIST
        ),
        expected_status=201,
    )
    assert_whole_minutes(
        prompt_alert["response_deadline_minutes"], 6, "response_deadline_minutes"
    )
    fx.record_intervention(api, prompt_alert["id"], at="2026-08-02T10:23:00Z")

    settled_prompt = validate_success(api.get_alert(prompt_alert["id"], NURSE))
    assert_whole_minutes(settled_prompt["latency_minutes"], 3, "latency_minutes")
    assert_alert_dimensions(settled_prompt, c.TRIAGE_DETECTED, c.RESPONSE_ON_TIME)

    after_prompt = validate_success(api.get_unit(stay.unit_id, COORDINATOR))
    assert after_prompt["late_response_count"] == 1, (
        "an on-time response leaves late_response_count where it was, "
        f"got {after_prompt['late_response_count']!r}"
    )


def test_unit_storage_figures_are_visible_immediately_after_a_segment_closes(api):
    """The volume banked by a closing segment is already in the unit's derived figures.

    PRD §2.11: "Its `storage_used_gb` is recomputed, as a figure rounded half up to 2 decimal places, as the sum of `stored_gb` over every study of the unit whose `data_state` is `ONLINE` or `EXPORT_HELD`, plus the sum of `package_gb` over every export package on those same studies whose `status` is `BUILT` or `DELIVERED`."
    PRD §2.11: "From that figure, `storage_pressure_pct` is the used volume divided by the unit's `storage_quota_gb`, multiplied by 100, rounded half up to 2 decimal places."

    Design: Corner/consistency_model/derived_unit_storage_visible_in_same_response
    """
    stay = fx.build_admitted_stay(
        api,
        unit_name="EMU Ambulatory",
        bed_count=1,
        storage_quota_gb=500.00,
        risk_tier=c.RISK_LOW,
        setting=c.SETTING_AMBULATORY,
        requested_days=3,
        planned_days=2,
        target_event_count=2,
        channel_count=24,
    )
    fx.start_study(api, stay.study_id, stay.shift_id, at="2026-08-02T00:00:00Z")
    fx.set_clock(api, "2026-08-02T01:30:00Z")

    paused = validate_success(
        api.pause_study(stay.study_id, f.pause_payload(), TECHNOLOGIST)
    )
    assert_whole_minutes(paused["acquired_minutes"], 90, "acquired_minutes")
    assert paused["closed_segment_count"] == 1, (
        f"closed_segment_count should be 1, got {paused['closed_segment_count']!r}"
    )
    # 24 ambulatory channels: 0.0004 * 24 * 1.0 = 0.0096 GB per minute over 90
    # minutes is 0.864, rounded half up to 0.86.
    assert_storage_value(paused["stored_gb"], 0.86, "stored_gb")

    unit = validate_success(api.get_unit(stay.unit_id, COORDINATOR))
    assert_unit_storage(
        unit,
        storage_used_gb=0.86,
        storage_pressure_pct=0.17,
        posture=c.POSTURE_OPEN,
    )
    assert unit["active_study_count"] == 0, (
        f"the only study is paused, so active_study_count is 0, got {unit['active_study_count']!r}"
    )
    assert unit["beds_available"] == 1, (
        "an ambulatory stay occupies no bed, so beds_available stays at 1, "
        f"got {unit['beds_available']!r}"
    )

    admission = validate_success(api.get_admission(stay.admission_id, COORDINATOR))
    assert_fields_null(admission, "bed_id")
    assert admission["clinical_state"] == c.CLINICAL_ADMITTED, (
        f"the ambulatory stay is ADMITTED, got {admission['clinical_state']!r}"
    )
