"""
Requests that violate two rules at once.

Each scenario here is arranged so that two independent guards are both live on
the same call. The contract fixes which one answers: the earlier rung of the
validation ladder wins and the later one is never allowed to mask it. So each
scenario asserts the winning error identifier specifically, and also reads back
the record state that would have produced the losing error, so that the test
cannot pass by accident on a server that simply never reached the second guard.
"""

from test_helpers import (
    api_errors,
    assert_storage_value,
    assert_study_dimensions,
    assert_unit_storage,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import (
    ACQ_ACQUIRING,
    ACQ_COMPLETED,
    ACQ_PREPARING,
    DATA_EXPORT_HELD,
    DATA_ONLINE,
    MAINTENANCE_ELECTRODE_REGEL,
    POSTURE_STORAGE_LOCKED,
    REPORT_PRELIM_DRAFT,
    SHIFT_SCHEDULED,
    T_ADMIT,
    T_COMPLETE,
)
from test_helpers.test_users import COORDINATOR, TECHNOLOGIST

SHIFT_END = "2026-08-10T00:00:00Z"


# ---------------------------------------------------------------------------
# Declared transition (rung 6) outranks technologist coverage (rung 11)
# ---------------------------------------------------------------------------


def _acquiring_study_and_an_unactivated_second_window(api):
    """One study already acquiring on an ACTIVE window, plus a SCHEDULED window.

    Starting the acquiring study against the SCHEDULED window violates two
    conditions at once: the study is not `PREPARING`, and the named window is
    not `ACTIVE`.
    """
    stay = fixtures.build_admitted_stay(
        api,
        storage_quota_gb=500.00,
        max_concurrent_studies=2,
        channel_count=32,
        shift_ends_at=SHIFT_END,
    )
    scheduled_window = fixtures.create_shift(
        api,
        stay.unit_id,
        technologist_user_id="tech-2",
        starts_at=T_ADMIT,
        ends_at=SHIFT_END,
        max_concurrent_studies=2,
        activate=False,
    )
    fixtures.start_study(api, stay.study_id, stay.shift_id, at=T_ADMIT)
    return stay, scheduled_window


def test_start_on_an_acquiring_study_reports_study_state_not_missing_coverage(api):
    """An already-acquiring study named against a SCHEDULED window is refused on its own state, not on coverage.

    PRD §2.6: "Checks are evaluated in the following fixed order, and the first violation encountered ends the request."
    PRD §3.5: "Six conditions must hold, and each has its own rejection: the study must be `PREPARING` (`ERR_INVALID_STUDY_STATE`); the admission's `clinical_state` must be `ADMITTED` (`ERR_INVALID_ADMISSION_STATE`); the study's `modality` must equal the admission's `setting` (`ERR_SETTING_MISMATCH`); the named window's `state` must be `ACTIVE` with the logical clock inside its window, at or after `starts_at` and strictly before `ends_at` (`ERR_NO_TECH_COVERAGE`); that window's `assigned_study_count` must be strictly less than its `max_concurrent_studies` (`ERR_TECH_CAPACITY_EXCEEDED`); and the unit's `posture` must not be `STORAGE_LOCKED` (`ERR_UNIT_STORAGE_LOCKED`)."

    Design: Difficulty/priority_pair_validation_conflict/study_state_outranks_coverage_check_on_start
    """
    stay, scheduled_window = _acquiring_study_and_an_unactivated_second_window(api)
    # The losing condition is genuinely live: the named window is not ACTIVE, so
    # a start that got as far as the coverage rung would answer with
    # ERR_NO_TECH_COVERAGE.
    assert scheduled_window["state"] == SHIFT_SCHEDULED, (
        "the second coverage window should still be SCHEDULED, got "
        f"{scheduled_window['state']!r}"
    )

    response = api.start_study(
        stay.study_id, factories.start_payload(scheduled_window["id"]), TECHNOLOGIST
    )

    error = validate_error(response, api_errors.ERR_INVALID_STUDY_STATE, 409)
    assert error["error_id"] == api_errors.ERR_INVALID_STUDY_STATE, (
        "the study-state rung precedes the coverage rung, so the refusal should be "
        f"ERR_INVALID_STUDY_STATE, got {error['error_id']!r}"
    )


def test_refused_start_leaves_both_windows_and_the_study_untouched(api):
    """The refused start pins nothing: the study keeps its original window and the SCHEDULED window stays empty.

    PRD §2.6: "Nothing later in the ladder may mask something earlier in it."
    PRD §3.5: "On success the study pins the named window on its own `shift_id` and keeps it for the rest of its life, opens its first segment by stamping `current_segment_started_at` from the clock, increments the window's `assigned_study_count`, increments the unit's `active_study_count` and re-derives the unit's `posture` — which may now read `COVERAGE_CONSTRAINED` — and increments the study's `version` by 1."

    Design: Difficulty/priority_pair_validation_conflict/study_state_outranks_coverage_check_on_start
    """
    stay, scheduled_window = _acquiring_study_and_an_unactivated_second_window(api)
    study_before = validate_success(api.get_study(stay.study_id, TECHNOLOGIST))

    validate_error(
        api.start_study(
            stay.study_id, factories.start_payload(scheduled_window["id"]), TECHNOLOGIST
        ),
        api_errors.ERR_INVALID_STUDY_STATE,
        409,
    )

    study = validate_success(api.get_study(stay.study_id, TECHNOLOGIST))
    assert_study_dimensions(study, ACQ_ACQUIRING, DATA_ONLINE)
    assert study["shift_id"] == stay.shift_id, (
        "the study should still be pinned to the window it started on, got "
        f"{study['shift_id']!r}"
    )
    assert study["version"] == study_before["version"], (
        f"a refused start mutates nothing, version moved to {study['version']!r}"
    )

    untouched = validate_success(api.get_shift(scheduled_window["id"], TECHNOLOGIST))
    assert untouched["state"] == SHIFT_SCHEDULED, (
        f"the second window should still be SCHEDULED, got {untouched['state']!r}"
    )
    assert untouched["assigned_study_count"] == 0, (
        "no study should have been assigned to the second window, got "
        f"{untouched['assigned_study_count']!r}"
    )


# ---------------------------------------------------------------------------
# Concurrent-acquisition capacity (rung 12) outranks the storage lock (rung 21)
# ---------------------------------------------------------------------------


def _saturated_window_on_a_storage_locked_unit(api):
    """One window at capacity on a unit whose posture is already STORAGE_LOCKED.

    The unit's quota is 100.00 GB. The first study records 3600 whole minutes at
    25 channels of inpatient video-EEG, a per-minute rate of 0.0004 * 25 * 2.5 =
    0.025 GB, so 90.00 GB, which is exactly 90.00 percent of the quota. The
    pausing study still counts against the window's single concurrency slot, so
    starting a second study violates both the capacity rung and the storage-lock
    rung at once.
    """
    stay = fixtures.build_admitted_stay(
        api,
        storage_quota_gb=100.00,
        max_concurrent_studies=1,
        channel_count=25,
        shift_ends_at=SHIFT_END,
    )
    fixtures.acquire_segment(
        api,
        stay.study_id,
        from_iso=T_ADMIT,
        to_iso=T_COMPLETE,
        shift_id=stay.shift_id,
        reason="ELECTRODE_MAINTENANCE",
        maintenance_kind=MAINTENANCE_ELECTRODE_REGEL,
        impedance_kohm=4.50,
    )
    second_study = fixtures.create_study(api, stay.admission_id, channel_count=25)
    return stay, second_study


def test_start_when_window_is_full_reports_capacity_not_the_storage_lock(api):
    """A start blocked by both a full window and a locked unit answers on capacity, the earlier rung.

    PRD §2.6: "**Concurrent-acquisition capacity.** The coverage window's `assigned_study_count` is strictly below its `max_concurrent_studies`, otherwise `ERR_TECH_CAPACITY_EXCEEDED` (409)."
    PRD §2.6: "**Storage lock.** The unit's `posture` is not `STORAGE_LOCKED`, otherwise `ERR_UNIT_STORAGE_LOCKED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/tech_capacity_outranks_storage_lock_on_start
    """
    stay, second_study = _saturated_window_on_a_storage_locked_unit(api)
    # Both losing and winning conditions are live: the window holds its one
    # allowed study, and the unit is already locked at exactly 90.00 percent.
    window = validate_success(api.get_shift(stay.shift_id, TECHNOLOGIST))
    assert window["assigned_study_count"] == 1, (
        "the paused study should still occupy the window's only slot, got "
        f"{window['assigned_study_count']!r}"
    )
    assert window["max_concurrent_studies"] == 1, (
        f"the window should allow one study at a time, got {window['max_concurrent_studies']!r}"
    )
    unit = validate_success(api.get_unit(stay.unit_id, COORDINATOR))
    assert_unit_storage(
        unit, storage_pressure_pct=90.00, posture=POSTURE_STORAGE_LOCKED
    )

    response = api.start_study(
        second_study["id"], factories.start_payload(stay.shift_id), TECHNOLOGIST
    )

    error = validate_error(response, api_errors.ERR_TECH_CAPACITY_EXCEEDED, 409)
    assert error["error_id"] == api_errors.ERR_TECH_CAPACITY_EXCEEDED, (
        "the capacity rung precedes the storage-lock rung, so the refusal should be "
        f"ERR_TECH_CAPACITY_EXCEEDED, got {error['error_id']!r}"
    )


def test_refused_start_leaves_the_second_study_preparing_and_storage_unchanged(api):
    """The refused start neither pins a window on the second study nor disturbs the storage figures.

    PRD §3.5: "The study opens with `acquisition_state` at `PREPARING` and `data_state` at `ONLINE`, with `acquired_minutes`, `stored_gb`, `closed_segment_count` and `impedance_fail_count` at 0 and `shift_id`, `current_segment_started_at`, `completed_at`, `last_impedance_kohm` and `export_hold_reason` all null."
    PRD §3.5: "When the pause carries a `maintenance_kind` of `ELECTRODE_REGEL`, the accompanying `impedance_kohm` is recorded on the study's `last_impedance_kohm`, and if that reading exceeds the electrode limit of 10.00 kilohms, `impedance_fail_count` increases by 1."

    Design: Difficulty/priority_pair_validation_conflict/tech_capacity_outranks_storage_lock_on_start
    """
    stay, second_study = _saturated_window_on_a_storage_locked_unit(api)

    validate_error(
        api.start_study(
            second_study["id"], factories.start_payload(stay.shift_id), TECHNOLOGIST
        ),
        api_errors.ERR_TECH_CAPACITY_EXCEEDED,
        409,
    )

    blocked_study = validate_success(api.get_study(second_study["id"], TECHNOLOGIST))
    assert_study_dimensions(blocked_study, ACQ_PREPARING, DATA_ONLINE)
    assert blocked_study["shift_id"] is None, (
        f"a refused start pins no window, got shift_id {blocked_study['shift_id']!r}"
    )
    assert blocked_study["version"] == second_study["version"], (
        f"a refused start mutates nothing, version moved to {blocked_study['version']!r}"
    )

    first_study = validate_success(api.get_study(stay.study_id, TECHNOLOGIST))
    assert_storage_value(first_study["stored_gb"], 90.00, "stored_gb")
    assert_storage_value(
        first_study["last_impedance_kohm"], 4.50, "last_impedance_kohm"
    )
    assert first_study["impedance_fail_count"] == 0, (
        "a 4.50 kilohm reading is inside the 10.00 limit, so no impedance failure "
        f"should be counted, got {first_study['impedance_fail_count']!r}"
    )

    unit = validate_success(api.get_unit(stay.unit_id, COORDINATOR))
    assert_unit_storage(
        unit,
        storage_used_gb=90.00,
        storage_pressure_pct=90.00,
        posture=POSTURE_STORAGE_LOCKED,
    )


# ---------------------------------------------------------------------------
# Optimistic concurrency (rung 7) outranks the final-report prerequisite (rung 16)
# ---------------------------------------------------------------------------


def _completed_study_held_after_capturing_a_stale_version(api):
    """A completed study whose report is still a draft, mutated once after its version was read.

    The caller keeps the version it read before the export hold, so an export
    create that quotes it violates two conditions at once: the quoted version is
    stale, and the study has no report in `FINAL_ISSUED`.
    """
    stay = fixtures.build_admitted_stay(
        api,
        storage_quota_gb=500.00,
        max_concurrent_studies=2,
        channel_count=32,
        shift_ends_at=SHIFT_END,
    )
    fixtures.acquire_and_complete(
        api, stay.study_id, stay.shift_id, from_iso=T_ADMIT, to_iso=T_COMPLETE
    )
    stale_version = validate_success(api.get_study(stay.study_id, COORDINATOR))["version"]
    validate_success(
        api.place_export_hold(
            stay.study_id,
            factories.export_hold_payload("LEGAL_HOLD"),
            COORDINATOR,
        )
    )
    return stay, stale_version


def test_export_create_with_stale_version_reports_concurrency_not_the_missing_final(api):
    """An export create quoting a stale study version is refused on concurrency, not on the missing final report.

    PRD §2.7: "If that value does not equal the study's current `version`, the create is rejected with `ERR_STALE_STUDY_VERSION` (HTTP 412)."
    PRD §2.6: "The study has a review report in `FINAL_ISSUED` before an export package may be created against it, otherwise `ERR_REPORT_NOT_FINAL` (409)."

    Design: Difficulty/priority_pair_validation_conflict/stale_study_version_outranks_report_not_final_on_export_create
    """
    stay, stale_version = _completed_study_held_after_capturing_a_stale_version(api)
    # The losing condition is genuinely live: the study's only report never left
    # its draft state, so a create that reached the later rung would answer with
    # ERR_REPORT_NOT_FINAL.
    report = fixtures.report_of_study(api, stay.study_id)
    assert report["status"] == REPORT_PRELIM_DRAFT, (
        "the study's report should still be a preliminary draft, got "
        f"{report['status']!r}"
    )

    response = api.create_export(
        factories.export_payload(stay.study_id, stale_version, include_video=False),
        COORDINATOR,
    )

    error = validate_error(response, api_errors.ERR_STALE_STUDY_VERSION, 412)
    assert error["error_id"] == api_errors.ERR_STALE_STUDY_VERSION, (
        "the optimistic-concurrency rung precedes the final-report rung, so the "
        f"refusal should be ERR_STALE_STUDY_VERSION, got {error['error_id']!r}"
    )


def test_refused_export_create_records_no_package_and_leaves_the_hold_standing(api):
    """The refused create adds no package, and the export hold that made the quoted version stale still stands.

    PRD §3.9: "Placing an export hold moves `data_state` from `ONLINE` to `EXPORT_HELD` and stores the supplied `hold_reason` on the study's `export_hold_reason`; the study must be `ONLINE`, otherwise `ERR_INVALID_DATA_STATE`."
    PRD §2.5: "`version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that record, including server-initiated cascade mutations that no client requested directly."

    Design: Difficulty/priority_pair_validation_conflict/stale_study_version_outranks_report_not_final_on_export_create
    """
    stay, stale_version = _completed_study_held_after_capturing_a_stale_version(api)

    validate_error(
        api.create_export(
            factories.export_payload(stay.study_id, stale_version, include_video=False),
            COORDINATOR,
        ),
        api_errors.ERR_STALE_STUDY_VERSION,
        412,
    )

    study = validate_success(api.get_study(stay.study_id, COORDINATOR))
    assert_study_dimensions(study, ACQ_COMPLETED, DATA_EXPORT_HELD)
    assert study["export_hold_reason"] == "LEGAL_HOLD", (
        f"the hold reason should still be recorded, got {study['export_hold_reason']!r}"
    )
    assert study["version"] == stale_version + 1, (
        "the export hold is the single mutation that made the quoted version stale, "
        f"so the study should stand one version on from {stale_version}, got "
        f"{study['version']!r}"
    )

    packages, meta = validate_paginated(
        api.list_exports(COORDINATOR, {"study_id": stay.study_id})
    )
    assert packages == [], (
        f"the refused create should have persisted no package, got {packages!r}"
    )
    assert meta["total_count"] == 0, (
        f"the study should have no export packages, got total_count {meta['total_count']!r}"
    )
