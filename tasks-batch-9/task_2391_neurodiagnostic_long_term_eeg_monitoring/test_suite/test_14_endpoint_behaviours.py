"""
Endpoint behaviours: the retention checkpoint, list filtering, the supersession
link between export packages, and the conditional electrode-maintenance branch
of a pause.

Every test builds its own unit, funding, stay and coverage through the public
endpoints, because each test starts against an empty database with the logical
clock standing at its startup value.
"""

import pytest

from test_helpers import (
    assert_fields_null,
    assert_ids_equal,
    assert_instant_equals,
    assert_storage_value,
    assert_study_dimensions,
    assert_unit_storage,
    assert_whole_minutes,
    constants as c,
    factories as f,
    fixtures as fx,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import COORDINATOR, TECHNOLOGIST


def test_retention_sweep_purges_expired_package_and_releases_its_volume(api):
    """The sweep purges a package whose retention expiry the clock has reached.

    PRD §3.9: "It purges every export package of the unit whose `status` is `BUILT` or `DELIVERED` and whose `retention_expires_at` has been reached by the logical clock, moving it to `PURGED` and subtracting its `package_gb` from the unit's `storage_used_gb`; both entry paths into `PURGED` release storage identically."
    PRD §3.9: "It increments the unit's `retention_sweep_index` by 1."

    Design: Corner/endpoints/unit_retention_sweep_purges_expired_packages
    """
    stay = fx.build_admitted_stay(
        api,
        unit_name="EMU Retention",
        bed_count=1,
        storage_quota_gb=500.00,
        risk_tier=c.RISK_MODERATE,
        requested_days=5,
        planned_days=2,
        target_event_count=2,
        channel_count=32,
    )
    # One 120-minute inpatient segment on 32 channels: 0.0004 * 32 * 2.5 = 0.032
    # GB per minute, so stored_gb is 3.84.
    fx.acquire_and_complete(
        api,
        stay.study_id,
        stay.shift_id,
        from_iso="2026-08-02T00:00:00Z",
        to_iso="2026-08-02T02:00:00Z",
    )
    fx.finalized_report(api, stay.study_id, prelim_at="2026-08-02T12:00:00Z")

    package = fx.queue_export(api, stay.study_id, include_video=True)
    fx.set_clock(api, "2026-08-05T00:00:00Z")
    built = validate_success(api.build_export(package["id"], COORDINATOR))
    assert_storage_value(built["package_gb"], 3.84, "package_gb")
    assert_instant_equals(
        built["retention_expires_at"], "2026-09-04T00:00:00Z", "retention_expires_at"
    )

    fx.set_clock(api, "2026-09-04T00:00:00Z")
    validate_success(api.run_retention_sweep(stay.unit_id, COORDINATOR))

    purged = validate_success(api.get_export(package["id"], COORDINATOR))
    assert purged["status"] == c.EXPORT_PURGED, (
        f"package should be PURGED once the clock reaches its retention expiry, "
        f"got {purged['status']!r}"
    )
    assert_storage_value(purged["package_gb"], 3.84, "package_gb after purge")
    assert_instant_equals(
        purged["retention_expires_at"],
        "2026-09-04T00:00:00Z",
        "retention_expires_at after purge",
    )

    study = validate_success(api.get_study(stay.study_id, COORDINATOR))
    assert_study_dimensions(study, c.ACQ_COMPLETED, c.DATA_ONLINE)
    assert_storage_value(study["stored_gb"], 3.84, "stored_gb")

    unit = validate_success(api.get_unit(stay.unit_id, COORDINATOR))
    assert_unit_storage(
        unit,
        storage_used_gb=3.84,
        storage_pressure_pct=0.77,
        posture=c.POSTURE_OPEN,
    )
    assert unit["retention_sweep_index"] == 1, (
        f"retention_sweep_index should be 1 after one sweep, "
        f"got {unit['retention_sweep_index']!r}"
    )


def test_studies_list_composes_shift_and_acquisition_state_filters(api):
    """Filtering by covering shift and acquisition state narrows to one study.

    PRD §3.5: "Studies may be listed with filters on `admission_id`, `shift_id`, `acquisition_state` and `data_state`."
    PRD §2.3: "The response envelope's `meta` object for a list response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the size of the full filtered collection and `has_more` indicates whether records remain beyond the current page."

    Design: Corner/endpoints/list_studies_filtered_by_shift_and_acquisition_state
    """
    stay = fx.build_admitted_stay(
        api,
        unit_name="EMU Listing",
        bed_count=1,
        storage_quota_gb=500.00,
        planned_days=2,
        target_event_count=2,
        max_concurrent_studies=2,
        channel_count=32,
    )
    fx.start_study(api, stay.study_id, stay.shift_id, at="2026-08-02T00:00:00Z")
    study_b = fx.create_study(
        api, stay.admission_id, channel_count=24, modality=c.SETTING_INPATIENT
    )
    fx.start_study(api, study_b["id"], stay.shift_id)
    fx.pause_study(api, study_b["id"], at="2026-08-02T01:00:00Z")

    acquiring, acquiring_meta = validate_paginated(
        api.list_studies(
            TECHNOLOGIST,
            params={
                "shift_id": stay.shift_id,
                "acquisition_state": c.ACQ_ACQUIRING,
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert acquiring_meta["total_count"] == 1, (
        "only the still-acquiring study of the shift should match, "
        f"got total_count {acquiring_meta['total_count']!r}"
    )
    assert acquiring_meta["has_more"] is False, "a single match leaves nothing beyond the page"
    assert len(acquiring) == 1, f"expected one record on the page, got {len(acquiring)}"
    assert_ids_equal(acquiring[0]["id"], stay.study_id, "filtered study id")

    _, shift_meta = validate_paginated(
        api.list_studies(
            TECHNOLOGIST,
            params={"shift_id": stay.shift_id, "limit": 10, "offset": 0},
        )
    )
    assert shift_meta["total_count"] == 2, (
        "both studies remain pinned to the shift when the state filter is dropped, "
        f"got total_count {shift_meta['total_count']!r}"
    )
    assert shift_meta["has_more"] is False, "two records fit inside the default page"

    paused = validate_success(api.get_study(study_b["id"], TECHNOLOGIST))
    assert_study_dimensions(paused, c.ACQ_PAUSED, c.DATA_ONLINE)
    assert_whole_minutes(paused["acquired_minutes"], 60, "acquired_minutes")
    assert paused["closed_segment_count"] == 1, (
        f"closed_segment_count should be 1, got {paused['closed_segment_count']!r}"
    )
    # 24 channels inpatient: 0.0004 * 24 * 2.5 = 0.024 GB per minute over 60 minutes.
    assert_storage_value(paused["stored_gb"], 1.44, "stored_gb")

    shift = validate_success(api.get_shift(stay.shift_id, TECHNOLOGIST))
    assert shift["assigned_study_count"] == 2, (
        "a paused study still sits against its window, so assigned_study_count is 2, "
        f"got {shift['assigned_study_count']!r}"
    )

    unit = validate_success(api.get_unit(stay.unit_id, COORDINATOR))
    assert unit["active_study_count"] == 1, (
        f"active_study_count should count only the ACQUIRING study, got {unit['active_study_count']!r}"
    )
    assert unit["posture"] == c.POSTURE_OPEN, (
        f"posture should be OPEN below the coverage capacity, got {unit['posture']!r}"
    )


def test_export_created_with_supersedes_link_records_the_association(api):
    """A replacement package stores its supersession link and is discoverable by it.

    PRD §3.9: "Creating one names the `study_id` being exported, a boolean `include_video` stating whether synchronized video travels with it, the version expectation `expected_study_version` of §2.7, and optionally a `supersedes_export_id` pointing at the package this one replaces — null for a first-generation package."
    PRD §3.9: "Packages may be listed with filters on `study_id`, `supersedes_export_id` and `status`."

    Design: Corner/endpoints/export_supersedes_link_records_association
    """
    stay = fx.build_admitted_stay(
        api,
        unit_name="EMU Supersede",
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
    fx.finalized_report(api, stay.study_id, prelim_at="2026-08-02T12:00:00Z")
    original = fx.delivered_export(
        api,
        stay.study_id,
        include_video=True,
        recipient_center="Metro Surgical Center",
    )

    study = validate_success(api.get_study(stay.study_id, COORDINATOR))
    replacement = validate_success(
        api.create_export(
            f.export_payload(
                stay.study_id,
                study["version"],
                include_video=False,
                supersedes_export_id=original["id"],
            ),
            COORDINATOR,
        ),
        expected_status=201,
    )
    assert_ids_equal(
        replacement["supersedes_export_id"], original["id"], "supersedes_export_id"
    )
    assert replacement["status"] == c.EXPORT_QUEUED, (
        f"a new package opens in QUEUED, got {replacement['status']!r}"
    )
    assert float(replacement["package_gb"]) == 0, (
        f"a queued package has allocated nothing yet, got {replacement['package_gb']!r}"
    )
    assert replacement["include_video"] is False, (
        f"include_video should be stored as supplied, got {replacement['include_video']!r}"
    )
    assert_fields_null(replacement, "built_at")

    linked, linked_meta = validate_paginated(
        api.list_exports(
            COORDINATOR,
            params={
                "supersedes_export_id": original["id"],
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert linked_meta["total_count"] == 1, (
        "only the replacement package points at the original, "
        f"got total_count {linked_meta['total_count']!r}"
    )
    assert_ids_equal(linked[0]["id"], replacement["id"], "superseding package id")

    superseded = validate_success(api.get_export(original["id"], COORDINATOR))
    assert superseded["status"] == c.EXPORT_DELIVERED, (
        f"the superseded package keeps its own status, got {superseded['status']!r}"
    )
    assert_storage_value(superseded["package_gb"], 3.84, "superseded package_gb")
    assert_fields_null(superseded, "supersedes_export_id")

    unit = validate_success(api.get_unit(stay.unit_id, COORDINATOR))
    # 3.84 for the ONLINE study plus 3.84 for the DELIVERED package; the freshly
    # queued package allocates nothing.
    assert_unit_storage(unit, storage_used_gb=7.68)


def test_pause_with_electrode_regel_records_impedance_and_counts_the_failure(api):
    """A maintenance pause records the impedance reading and counts it as a failure.

    PRD §3.5: "When the pause carries a `maintenance_kind` of `ELECTRODE_REGEL`, the accompanying `impedance_kohm` is recorded on the study's `last_impedance_kohm`, and if that reading exceeds the electrode limit of 10.00 kilohms, `impedance_fail_count` increases by 1."

    Design: Corner/endpoints/study_pause_records_electrode_maintenance_and_impedance
    """
    stay = fx.build_admitted_stay(
        api,
        unit_name="EMU Impedance",
        bed_count=1,
        storage_quota_gb=500.00,
        planned_days=2,
        target_event_count=2,
        channel_count=32,
    )
    fx.start_study(api, stay.study_id, stay.shift_id, at="2026-08-02T00:00:00Z")
    first_pause = fx.pause_study(api, stay.study_id, at="2026-08-02T01:00:00Z")
    assert_fields_null(first_pause, "last_impedance_kohm")
    fx.resume_study(api, stay.study_id)
    fx.set_clock(api, "2026-08-02T01:30:00Z")

    paused = validate_success(
        api.pause_study(
            stay.study_id,
            f.pause_payload(
                reason="ELECTRODE_REGEL",
                maintenance_kind=c.MAINTENANCE_ELECTRODE_REGEL,
                impedance_kohm=12.50,
            ),
            TECHNOLOGIST,
        )
    )
    assert_study_dimensions(paused, c.ACQ_PAUSED, c.DATA_ONLINE)
    assert_fields_null(paused, "current_segment_started_at")
    assert_whole_minutes(paused["acquired_minutes"], 90, "acquired_minutes")
    assert paused["closed_segment_count"] == 2, (
        f"closed_segment_count should be 2, got {paused['closed_segment_count']!r}"
    )
    # 60 minutes -> 1.92 rounded, then 30 minutes -> 0.96, re-rounded to 2.88.
    assert_storage_value(paused["stored_gb"], 2.88, "stored_gb")
    assert paused["last_impedance_kohm"] == pytest.approx(12.50, abs=0.01), (
        f"last_impedance_kohm should record the supplied reading, "
        f"got {paused['last_impedance_kohm']!r}"
    )
    assert paused["impedance_fail_count"] == 1, (
        "12.50 kilohms exceeds the 10.00 electrode limit, so impedance_fail_count is 1, "
        f"got {paused['impedance_fail_count']!r}"
    )

    unit = validate_success(api.get_unit(stay.unit_id, COORDINATOR))
    assert_unit_storage(unit, storage_used_gb=2.88, storage_pressure_pct=0.58)
    assert unit["active_study_count"] == 0, (
        f"pausing the only study leaves active_study_count at 0, got {unit['active_study_count']!r}"
    )
