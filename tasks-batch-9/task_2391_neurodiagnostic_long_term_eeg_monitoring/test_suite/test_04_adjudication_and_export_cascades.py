"""
Multi-record cascades fired by a single request.

Two chains are exercised here. The clinical chain runs from one alert
adjudication through the event markings that alert substantiates, into the
admission's capture figures, and out again into the medication-reduction
protocol. The storage chain runs from one export build through the package
volume, into the unit's storage ledger and gating posture, and sideways into an
unrelated package that was merely sitting in the queue.

Every test builds its own world through the public endpoints: the database is
empty and the logical clock stands at its startup value when the test begins.
"""

from test_helpers import (
    assert_admission_dimensions,
    assert_capture_value,
    assert_instant_equals,
    assert_storage_value,
    assert_unit_storage,
    fixtures,
    validate_success,
)
from test_helpers.constants import (
    ALERT_SOURCE_TECHNOLOGIST,
    AUTH_STATE_ACTIVE,
    BLOCKED_REASON_UNIT_STORAGE_LOCKED,
    CLASSIFICATION_CLINICAL,
    CLINICAL_CAPTURE_TARGET_MET,
    EVENT_CLINICAL_SEIZURE,
    EXPORT_BLOCKED,
    EXPORT_BUILT,
    INTERVENTION_POSITIONING,
    INTERVENTION_SEIZURE_TESTING,
    MARKING_ADJUDICATED,
    POSTURE_STORAGE_LOCKED,
    SETTING_INPATIENT,
    T_ADMIT,
    T_COMPLETE,
    TAPER_COMPLETED,
    TRIAGE_CONFIRMED_CLINICAL,
)
from test_helpers.test_users import COORDINATOR, EPILEPTOLOGIST

# Instants this file pins so the arithmetic in each docstring stays checkable.
SEGMENT_CLOSE = "2026-08-03T00:00:00Z"
ALERT_DETECTED = "2026-08-03T00:30:00Z"
FIRST_ONSET = "2026-08-02T06:00:00Z"
SECOND_ONSET = "2026-08-02T18:00:00Z"
STUDY_B_COMPLETE = "2026-08-02T20:00:00Z"
RETENTION_EXPIRY = "2026-09-03T12:00:00Z"


def _stay_with_two_attended_clinical_markings(api):
    """An attended alert on a paused study carrying two PROPOSED unit-weight markings.

    The stay targets 2 weighted events, so the two markings exactly satisfy it.
    The taper plan stands at step 1 of 3, which is below the provoked-event
    discount threshold, so each marking freezes a weight of 1.000.
    """
    stay = fixtures.build_admitted_stay(
        api,
        storage_quota_gb=500.00,
        max_concurrent_studies=2,
        channel_count=32,
        target_event_count=2,
        planned_days=3,
        requested_days=5,
    )
    plan = fixtures.create_taper_plan(
        api, stay.admission_id, total_steps=3, steps_advanced=1
    )
    fixtures.start_study(api, stay.study_id, stay.shift_id, at=T_ADMIT)
    fixtures.pause_study(api, stay.study_id, at=SEGMENT_CLOSE)
    alert = fixtures.raise_alert(
        api, stay.study_id, source=ALERT_SOURCE_TECHNOLOGIST, at=ALERT_DETECTED
    )
    fixtures.record_intervention(
        api,
        alert["id"],
        interventions=[INTERVENTION_POSITIONING, INTERVENTION_SEIZURE_TESTING],
    )
    # The first intervention settles the response dimension and is itself a
    # mutation of the alert (PRD 3.6: "Either way the alert's `version`
    # increments by 1."), so re-read the alert to hold the state as it stands
    # immediately before adjudication.
    alert = validate_success(api.get_alert(alert["id"], EPILEPTOLOGIST))
    first = fixtures.create_marking(
        api,
        stay.study_id,
        FIRST_ONSET,
        event_class=EVENT_CLINICAL_SEIZURE,
        duration_seconds=90,
        alert_id=alert["id"],
    )
    second = fixtures.create_marking(
        api,
        stay.study_id,
        SECOND_ONSET,
        event_class=EVENT_CLINICAL_SEIZURE,
        duration_seconds=55,
        alert_id=alert["id"],
    )
    return stay, plan, alert, first, second


def test_clinical_adjudication_confirms_alert_and_adjudicates_its_markings(api):
    """A CLINICAL adjudication confirms the alert and carries both of its markings to ADJUDICATED.

    PRD §3.6: "A `CLINICAL` classification moves `triage_state` to `CONFIRMED_CLINICAL` — but only if at least one safety intervention already exists on that alert, otherwise the adjudication is refused with `ERR_INTERVENTION_REQUIRED`."
    PRD §3.6: "On success it stamps `adjudicated_at` from the clock and runs the capture cascade in four links: first, every event marking pointing at this alert whose `status` is `PROPOSED` moves to `ADJUDICATED`; second, that marking transition recomputes the admission's `weighted_event_count`, `capture_adequacy_index`, `capture_adequacy_index_prospective`, `projected_daily_yield` and `deficit_weighted`; third, if `capture_adequacy_index` has reached 1.000 or more, the admission's `clinical_state` moves from `ADMITTED` to `CAPTURE_TARGET_MET`; and fourth, that admission transition drives every taper plan of the admission in `ACTIVE` or `HELD` to `COMPLETED`."

    Design: Difficulty/transitive_cascade/alert_adjudication_cascade_marking_admission_taper
    """
    stay, _plan, alert, first, second = _stay_with_two_attended_clinical_markings(api)

    adjudicated = validate_success(
        api.adjudicate_alert(
            alert["id"], {"classification": CLASSIFICATION_CLINICAL}, EPILEPTOLOGIST
        )
    )

    assert adjudicated["triage_state"] == TRIAGE_CONFIRMED_CLINICAL, (
        "a CLINICAL classification on an attended alert should confirm it, got "
        f"{adjudicated['triage_state']!r}"
    )
    assert_instant_equals(
        adjudicated["adjudicated_at"], ALERT_DETECTED, "alert adjudicated_at"
    )
    assert adjudicated["version"] == alert["version"] + 1, (
        "the alert's own version should increment by 1 on adjudication, got "
        f"{adjudicated['version']!r} from {alert['version']!r}"
    )

    for label, marking in (("first", first), ("second", second)):
        moved = validate_success(api.get_marking(marking["id"], EPILEPTOLOGIST))
        assert moved["status"] == MARKING_ADJUDICATED, (
            f"the {label} marking pointing at this alert should have moved to "
            f"ADJUDICATED, got {moved['status']!r}"
        )
        assert_instant_equals(
            moved["adjudicated_at"], ALERT_DETECTED, f"{label} marking adjudicated_at"
        )
        assert moved["taper_step_at_onset"] == 1, (
            f"the {label} marking should have frozen the plan's step 1 at onset, got "
            f"{moved['taper_step_at_onset']!r}"
        )
        assert_capture_value(moved["weight"], 1.000, f"{label} marking weight")
        assert moved["version"] == marking["version"] + 1, (
            f"the {label} marking's version should increment by 1, got "
            f"{moved['version']!r} from {marking['version']!r}"
        )


def test_clinical_adjudication_meets_capture_target_and_completes_the_taper(api):
    """Banking both weights drives capture adequacy to 1.000, meets the target and force-completes the taper.

    PRD §3.7: "`weighted_event_count` is the sum of the members' `weight` values, rounded half up to 3 decimal places."
    PRD §3.7: "The retrospective figure stored on `capture_adequacy_index` is the lesser of 1.000 and `weighted_event_count` divided by `target_event_count`, rounded half up to 3 decimal places; it counts only weight already banked by adjudicated markings, it is clamped at 1.000, and it is **the only figure the `ADMITTED` to `CAPTURE_TARGET_MET` transition reads** — the transition fires when it reaches 1.000 or more, and the reverse transition fires when it falls below 1.000."
    PRD §3.4: "Reaching `COMPLETED` freezes `current_step` where it stands."

    Design: Difficulty/transitive_cascade/alert_adjudication_cascade_marking_admission_taper
    """
    stay, plan, alert, _first, _second = _stay_with_two_attended_clinical_markings(api)
    admission_before = validate_success(
        api.get_admission(stay.admission_id, EPILEPTOLOGIST)
    )

    validate_success(
        api.adjudicate_alert(
            alert["id"], {"classification": CLASSIFICATION_CLINICAL}, EPILEPTOLOGIST
        )
    )

    admission = validate_success(api.get_admission(stay.admission_id, EPILEPTOLOGIST))
    # Two CLINICAL_SEIZURE markings at 1.000 each against a target of 2.
    assert_capture_value(
        admission["weighted_event_count"], 2.000, "weighted_event_count"
    )
    assert_capture_value(admission["deficit_weighted"], 0.000, "deficit_weighted")
    assert_capture_value(
        admission["capture_adequacy_index"], 1.000, "capture_adequacy_index"
    )
    assert_admission_dimensions(
        admission, CLINICAL_CAPTURE_TARGET_MET, AUTH_STATE_ACTIVE
    )
    assert admission["version"] > admission_before["version"], (
        "the admission should have been mutated by the cascade, version stayed at "
        f"{admission['version']!r}"
    )

    completed_plan = validate_success(api.get_taper_plan(plan["id"], EPILEPTOLOGIST))
    assert completed_plan["status"] == TAPER_COMPLETED, (
        "the target having been met, the ACTIVE taper plan should have been driven to "
        f"COMPLETED, got {completed_plan['status']!r}"
    )
    assert completed_plan["current_step"] == 1, (
        "reaching COMPLETED should freeze current_step at 1 of 3, got "
        f"{completed_plan['current_step']!r}"
    )
    assert completed_plan["total_steps"] == 3, (
        f"total_steps should be untouched at 3, got {completed_plan['total_steps']!r}"
    )
    assert completed_plan["version"] == plan["version"] + 1, (
        "the server-driven move to COMPLETED should increment the plan's version by 1, "
        f"got {completed_plan['version']!r} from {plan['version']!r}"
    )


def _two_finalized_studies_with_two_queued_packages(api):
    """Two finalized recordings on one unit and one queued package on each.

    The unit's quota is 220.00 GB. Study A records 3600 whole minutes at 25
    channels of inpatient video-EEG, a per-minute rate of 0.0004 * 25 * 2.5 =
    0.025 GB, so its single closed segment is 90.00 GB. Study B records 1200
    minutes, so 30.00 GB. Together they leave the unit at 120.00 GB, a pressure
    of 54.55 percent, comfortably below the lock.
    """
    stay = fixtures.build_admitted_stay(
        api,
        storage_quota_gb=220.00,
        max_concurrent_studies=2,
        channel_count=25,
        target_event_count=4,
        planned_days=5,
        requested_days=5,
    )
    study_a = stay.study
    study_b = fixtures.create_study(
        api, stay.admission_id, channel_count=25, modality=SETTING_INPATIENT
    )
    fixtures.start_study(api, study_a["id"], stay.shift_id, at=T_ADMIT)
    fixtures.start_study(api, study_b["id"], stay.shift_id)

    fixtures.complete_study(api, study_b["id"], at=STUDY_B_COMPLETE)
    fixtures.finalized_report(api, study_b["id"])
    fixtures.complete_study(api, study_a["id"], at=T_COMPLETE)
    fixtures.finalized_report(api, study_a["id"])

    package_one = fixtures.queue_export(api, study_a["id"], include_video=True)
    package_two = fixtures.queue_export(api, study_b["id"], include_video=True)
    return stay, study_a, study_b, package_one, package_two


def test_export_build_allocates_the_full_video_volume_and_sets_retention(api):
    """Building a video-bearing package allocates the study's stored volume exactly and dates its retention.

    PRD §3.9: "The volume itself is a two-branch figure: when `include_video` is true, `package_gb` equals the study's `stored_gb` at build time exactly; when it is false, `package_gb` is the study's `stored_gb` divided by the study's modality factor — 2.5 for `INPATIENT_VEEG`, 1.0 for `AMBULATORY_VEEG` — rounded half up to 2 decimal places, since stripping video from an inpatient recording strips most of its bulk while an ambulatory recording carries no video premium to strip."
    PRD §3.9: "On success the cascade runs in four links: first, `package_gb` is set from that computation, `built_at` is stamped from the clock, and `retention_expires_at` is set to 30 days after `built_at`, that being the first instant from which a sweep may purge the package; second, the package volume is added to the unit's `storage_used_gb`, which re-derives `storage_pressure_pct`; third, if that pressure has reached 90.00 percent or more the unit's `posture` becomes `STORAGE_LOCKED`; and fourth, because the posture is now locked, every *other* export package of that unit standing in `QUEUED` moves to `BLOCKED` with `blocked_reason` set to `UNIT_STORAGE_LOCKED`."

    Design: Difficulty/transitive_cascade/export_build_cascade_storage_posture_blocks_queued
    """
    _stay, study_a, _study_b, package_one, _package_two = (
        _two_finalized_studies_with_two_queued_packages(api)
    )
    recording = validate_success(api.get_study(study_a["id"], COORDINATOR))
    assert_storage_value(recording["stored_gb"], 90.00, "study A stored_gb")

    built = validate_success(api.build_export(package_one["id"], COORDINATOR))

    assert built["status"] == EXPORT_BUILT, (
        f"a queued package should build to BUILT, got {built['status']!r}"
    )
    # include_video true, so the package takes the study's stored_gb exactly.
    assert_storage_value(built["package_gb"], 90.00, "package_gb")
    assert_instant_equals(built["built_at"], T_COMPLETE, "built_at")
    assert_instant_equals(
        built["retention_expires_at"], RETENTION_EXPIRY, "retention_expires_at"
    )
    assert built["blocked_reason"] is None, (
        f"the built package should carry no blocked_reason, got {built['blocked_reason']!r}"
    )
    assert built["version"] == package_one["version"] + 1, (
        "the package's version should increment by 1 on build, got "
        f"{built['version']!r} from {package_one['version']!r}"
    )


def test_export_build_locks_the_unit_and_blocks_the_sibling_queued_package(api):
    """The allocated volume pushes storage pressure past the lock, and the lock blocks an unrelated queued package.

    PRD §2.11: "From that figure, `storage_pressure_pct` is the used volume divided by the unit's `storage_quota_gb`, multiplied by 100, rounded half up to 2 decimal places."
    PRD §2.11: "If `storage_pressure_pct` has reached 90.00 percent or more, the posture is `STORAGE_LOCKED`."
    PRD §3.9: "A package in `QUEUED` moves to `BLOCKED` whenever the unit's posture becomes `STORAGE_LOCKED` or the study enters `EXPORT_HELD`, with `blocked_reason` recording which of the two literals — `UNIT_STORAGE_LOCKED` or `STUDY_EXPORT_HELD` — caused it."

    Design: Difficulty/transitive_cascade/export_build_cascade_storage_posture_blocks_queued
    """
    stay, _study_a, _study_b, package_one, package_two = (
        _two_finalized_studies_with_two_queued_packages(api)
    )
    unit_before = validate_success(api.get_unit(stay.unit_id, COORDINATOR))
    # 90.00 + 30.00 of study volume against a 220.00 quota.
    assert_unit_storage(
        unit_before, storage_used_gb=120.00, storage_pressure_pct=54.55
    )

    validate_success(api.build_export(package_one["id"], COORDINATOR))

    unit = validate_success(api.get_unit(stay.unit_id, COORDINATOR))
    # 120.00 online study volume plus the 90.00 package just allocated.
    assert_unit_storage(
        unit,
        storage_used_gb=210.00,
        storage_pressure_pct=95.45,
        posture=POSTURE_STORAGE_LOCKED,
    )
    assert unit["version"] > unit_before["version"], (
        "the unit should have been mutated by the storage cascade, version stayed at "
        f"{unit['version']!r}"
    )

    blocked = validate_success(api.get_export(package_two["id"], COORDINATOR))
    assert blocked["status"] == EXPORT_BLOCKED, (
        "the unit's other queued package should have been blocked by the new lock, got "
        f"{blocked['status']!r}"
    )
    assert blocked["blocked_reason"] == BLOCKED_REASON_UNIT_STORAGE_LOCKED, (
        "the blocked package should name the storage lock as its reason, got "
        f"{blocked['blocked_reason']!r}"
    )
    assert_storage_value(
        blocked["package_gb"], 0.00, "blocked package package_gb"
    )
    assert blocked["built_at"] is None, (
        f"a blocked package was never built, got built_at {blocked['built_at']!r}"
    )
    assert blocked["version"] == package_two["version"] + 1, (
        "the blocked package's version should increment by 1, got "
        f"{blocked['version']!r} from {package_two['version']!r}"
    )
