"""
Request validations: the guards that refuse a write outright.

Each test drives one guard to its rejection, pins the error identifier and HTTP
status the contract assigns it, and then proves the refusal changed nothing —
the target record keeps its state and version, the coupled aggregates keep their
counts, and no evidence row appears in a listing.
"""

from test_helpers import (
    assert_admission_dimensions,
    assert_capture_value,
    assert_ids_equal,
    assert_instant_equals,
    assert_ledger,
    assert_storage_value,
    assert_study_dimensions,
    assert_unit_storage,
    assert_version_is,
    assert_whole_minutes,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as errors
from test_helpers import constants as const
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users

SEGMENT_CLOSE = "2026-08-02T02:00:00Z"
PRELIM_AT = "2026-08-02T12:00:00Z"
CONFERENCE_AT = "2026-08-06T00:00:00Z"
LIST_PARAMS = {"limit": 20, "offset": 0}


def _bed_by_id(api, unit_id, bed_id):
    """Read one bed back through the unit's bed listing."""
    beds, _meta = validate_paginated(
        api.list_unit_beds(unit_id, users.COORDINATOR, dict(LIST_PARAMS))
    )
    matches = [bed for bed in beds if bed["id"] == bed_id]
    assert matches, f"bed {bed_id} should still be listed under unit {unit_id}"
    return matches[0]


def test_ambulatory_admission_with_bed_is_rejected(api):
    """An ambulatory stay that names a bed at admit time is refused.

    PRD §2.6: "An `INPATIENT_VEEG` admission supplies a bed, otherwise
    `ERR_BED_REQUIRED_FOR_INPATIENT` (422); an `AMBULATORY_VEEG` admission supplies none,
    otherwise `ERR_BED_NOT_ALLOWED_FOR_AMBULATORY` (422)."

    Design: Corner/validations/ambulatory_admission_with_bed_is_rejected
    """
    baseline = fx.build_admitted_stay(
        api,
        bed_count=1,
        storage_quota_gb=500.00,
        risk_tier=const.RISK_LOW,
        setting=const.SETTING_AMBULATORY,
        requested_days=3,
        authorized_days=3,
        planned_days=2,
        target_event_count=2,
        admitted_at=None,
        with_shift=False,
        with_study=False,
    )
    fx.set_clock(api, const.T_ADMIT)

    validate_error(
        api.admit(
            baseline.admission_id,
            f.admit_payload(baseline.bed_id),
            users.COORDINATOR,
        ),
        errors.ERR_BED_NOT_ALLOWED_FOR_AMBULATORY,
        422,
    )

    admission = validate_success(
        api.get_admission(baseline.admission_id, users.COORDINATOR)
    )
    assert_admission_dimensions(
        admission, const.CLINICAL_SCHEDULED, const.AUTH_STATE_PENDING
    )
    assert admission["admitted_at"] is None, "the refused admit must not stamp admitted_at"
    assert admission["bed_id"] is None, "the refused admit must not pin a bed"
    assert_version_is(admission, 1, "admission")

    bed = _bed_by_id(api, baseline.unit_id, baseline.bed_id)
    assert bed["status"] == const.BED_AVAILABLE, (
        f"the bed should stay AVAILABLE, got {bed['status']!r}"
    )
    assert bed["current_admission_id"] is None

    authorization = validate_success(
        api.get_authorization(baseline.authorization["id"], users.COORDINATOR)
    )
    assert_ledger(authorization, days_available=3, days_reserved=0)


def test_inpatient_admission_without_bed_is_rejected(api):
    """An inpatient stay admitted with no bed in the payload is refused.

    PRD §2.6: "An `INPATIENT_VEEG` admission supplies a bed, otherwise
    `ERR_BED_REQUIRED_FOR_INPATIENT` (422); an `AMBULATORY_VEEG` admission supplies none,
    otherwise `ERR_BED_NOT_ALLOWED_FOR_AMBULATORY` (422)."

    Design: Corner/validations/inpatient_admission_without_bed_is_rejected
    """
    baseline = fx.build_admitted_stay(
        api,
        bed_count=1,
        storage_quota_gb=500.00,
        risk_tier=const.RISK_MODERATE,
        setting=const.SETTING_INPATIENT,
        requested_days=3,
        authorized_days=3,
        planned_days=2,
        target_event_count=2,
        admitted_at=None,
        with_shift=False,
        with_study=False,
    )
    fx.set_clock(api, const.T_ADMIT)

    validate_error(
        api.admit(baseline.admission_id, f.admit_payload(None), users.COORDINATOR),
        errors.ERR_BED_REQUIRED_FOR_INPATIENT,
        422,
    )

    admission = validate_success(
        api.get_admission(baseline.admission_id, users.COORDINATOR)
    )
    assert_admission_dimensions(
        admission, const.CLINICAL_SCHEDULED, const.AUTH_STATE_PENDING
    )
    assert admission["admitted_at"] is None
    assert_version_is(admission, 1, "admission")

    bed = _bed_by_id(api, baseline.unit_id, baseline.bed_id)
    assert bed["status"] == const.BED_AVAILABLE
    assert bed["current_admission_id"] is None

    authorization = validate_success(
        api.get_authorization(baseline.authorization["id"], users.COORDINATOR)
    )
    assert_ledger(authorization, days_available=3, days_reserved=0)

    unit = validate_success(api.get_unit(baseline.unit_id, users.COORDINATOR))
    assert unit["beds_available"] == 1, (
        f"the unit's one bed should still be free, got beds_available {unit['beds_available']!r}"
    )


def test_setting_mismatch_between_admission_and_authorization_rejected(api):
    """Funding approved for ambulatory monitoring cannot admit an inpatient stay.

    PRD §2.6: "When the funding authorization stands in `APPROVED`, the admission's
    `setting` equals the authorization's `authorized_setting` at admit time; and a study's
    `modality` equals its admission's `setting` at start time."
    PRD §2.6: "Otherwise `ERR_SETTING_MISMATCH` (HTTP 422)."

    Design: Corner/validations/setting_mismatch_between_admission_and_authorization_rejected
    """
    unit = fx.create_unit(api, bed_count=1, storage_quota_gb=500.00)
    bed = fx.create_bed(api, unit["id"], label="EMU-1")
    patient = fx.create_patient(api, risk_tier=const.RISK_MODERATE)
    # The payer downgrades the venue: inpatient was requested, ambulatory authorized.
    authorization = fx.approved_authorization(
        api,
        patient["id"],
        requested_setting=const.SETTING_INPATIENT,
        requested_days=3,
        authorized_days=3,
        authorized_setting=const.SETTING_AMBULATORY,
        payer_note="ambulatory venue only",
    )
    admission = fx.schedule_admission(
        api,
        patient_id=patient["id"],
        authorization_id=authorization["id"],
        unit_id=unit["id"],
        setting=const.SETTING_INPATIENT,
        scheduled_admit_at=const.T_ADMIT,
        target_event_count=2,
        planned_days=2,
    )
    fx.set_clock(api, const.T_ADMIT)

    validate_error(
        api.admit(admission["id"], f.admit_payload(bed["id"]), users.COORDINATOR),
        errors.ERR_SETTING_MISMATCH,
        422,
    )

    authorization_after = validate_success(
        api.get_authorization(authorization["id"], users.COORDINATOR)
    )
    assert authorization_after["status"] == const.AUTH_APPROVED
    assert authorization_after["authorized_setting"] == const.SETTING_AMBULATORY
    assert_ledger(authorization_after, days_available=3, days_reserved=0)

    admission_after = validate_success(
        api.get_admission(admission["id"], users.COORDINATOR)
    )
    assert_admission_dimensions(
        admission_after, const.CLINICAL_SCHEDULED, const.AUTH_STATE_PENDING
    )
    assert admission_after["setting"] == const.SETTING_INPATIENT, (
        "the refused admit must not rewrite the stay's own setting"
    )
    assert_version_is(admission_after, 1, "admission")

    bed_after = _bed_by_id(api, unit["id"], bed["id"])
    assert bed_after["status"] == const.BED_AVAILABLE
    assert bed_after["current_admission_id"] is None


def test_authorization_not_approved_on_admit_returns_4xx(api):
    """A stay funded only by a draft authorization cannot be admitted.

    PRD §2.6: "The funding authorization stands in `APPROVED` before an admission may be
    admitted against it, otherwise `ERR_AUTHORIZATION_NOT_APPROVED` (409)."
    PRD §2.6: "An authorization that is not `APPROVED` has a null `authorized_setting`, so
    this rule stays silent for it and rung 19 catches the request instead."

    Design: Corner/validations/authorization_not_approved_on_admit_returns_4xx
    """
    unit = fx.create_unit(api, bed_count=1, storage_quota_gb=500.00)
    bed = fx.create_bed(api, unit["id"], label="EMU-1")
    patient = fx.create_patient(api, risk_tier=const.RISK_MODERATE)
    authorization = fx.draft_authorization(
        api,
        patient["id"],
        requested_setting=const.SETTING_INPATIENT,
        requested_days=3,
    )
    admission = fx.schedule_admission(
        api,
        patient_id=patient["id"],
        authorization_id=authorization["id"],
        unit_id=unit["id"],
        setting=const.SETTING_INPATIENT,
        scheduled_admit_at=const.T_ADMIT,
        target_event_count=2,
        planned_days=2,
    )
    fx.set_clock(api, const.T_ADMIT)

    validate_error(
        api.admit(admission["id"], f.admit_payload(bed["id"]), users.COORDINATOR),
        errors.ERR_AUTHORIZATION_NOT_APPROVED,
        409,
    )

    authorization_after = validate_success(
        api.get_authorization(authorization["id"], users.COORDINATOR)
    )
    assert authorization_after["status"] == const.AUTH_DRAFT
    assert authorization_after["authorized_setting"] is None, (
        "an authorization that never reached APPROVED carries a null authorized_setting"
    )
    assert authorization_after["authorized_days"] == 0

    admission_after = validate_success(
        api.get_admission(admission["id"], users.COORDINATOR)
    )
    assert_admission_dimensions(
        admission_after, const.CLINICAL_SCHEDULED, const.AUTH_STATE_PENDING
    )
    assert_version_is(admission_after, 1, "admission")

    bed_after = _bed_by_id(api, unit["id"], bed["id"])
    assert bed_after["status"] == const.BED_AVAILABLE
    assert bed_after["current_admission_id"] is None


def test_authorization_days_exhausted_on_admit_returns_4xx(api):
    """A second stay cannot reserve a day the authorization no longer has.

    PRD §2.6: "The authorization's `days_available` is at least the number of days being
    reserved, otherwise `ERR_AUTHORIZATION_DAYS_EXHAUSTED` (HTTP 402)."
    PRD §3.2: "Admitting a patient adds that admission's `planned_days` to `days_reserved`
    and subtracts the same number from `days_available`."

    Design: Corner/validations/authorization_days_exhausted_on_admit_returns_4xx
    """
    unit = fx.create_unit(api, bed_count=2, storage_quota_gb=500.00)
    first_bed = fx.create_bed(api, unit["id"], label="EMU-1")
    second_bed = fx.create_bed(api, unit["id"], label="EMU-2")
    patient = fx.create_patient(api, risk_tier=const.RISK_MODERATE)
    # Five days were requested but only two authorized.
    authorization = fx.approved_authorization(
        api,
        patient["id"],
        requested_setting=const.SETTING_INPATIENT,
        requested_days=5,
        authorized_days=2,
        payer_note="two days only",
    )
    first_admission = fx.schedule_admission(
        api,
        patient_id=patient["id"],
        authorization_id=authorization["id"],
        unit_id=unit["id"],
        setting=const.SETTING_INPATIENT,
        scheduled_admit_at=const.T_ADMIT,
        target_event_count=2,
        planned_days=2,
    )
    second_admission = fx.schedule_admission(
        api,
        patient_id=patient["id"],
        authorization_id=authorization["id"],
        unit_id=unit["id"],
        setting=const.SETTING_INPATIENT,
        scheduled_admit_at=const.T_ADMIT,
        target_event_count=1,
        planned_days=1,
    )
    # The first stay reserves both authorized days.
    fx.admit(api, first_admission["id"], bed_id=first_bed["id"], at=const.T_ADMIT)

    validate_error(
        api.admit(
            second_admission["id"], f.admit_payload(second_bed["id"]), users.COORDINATOR
        ),
        errors.ERR_AUTHORIZATION_DAYS_EXHAUSTED,
        402,
    )

    authorization_after = validate_success(
        api.get_authorization(authorization["id"], users.COORDINATOR)
    )
    assert_ledger(
        authorization_after,
        authorized_days=2,
        days_consumed=0,
        days_reserved=2,
        days_available=0,
    )

    second_after = validate_success(
        api.get_admission(second_admission["id"], users.COORDINATOR)
    )
    assert_admission_dimensions(
        second_after, const.CLINICAL_SCHEDULED, const.AUTH_STATE_PENDING
    )
    assert second_after["admitted_at"] is None
    assert second_after["bed_id"] is None
    assert_version_is(second_after, 1, "second admission")

    first_after = validate_success(
        api.get_admission(first_admission["id"], users.COORDINATOR)
    )
    assert_admission_dimensions(
        first_after, const.CLINICAL_ADMITTED, const.AUTH_STATE_ACTIVE
    )

    bed_after = _bed_by_id(api, unit["id"], second_bed["id"])
    assert bed_after["status"] == const.BED_AVAILABLE
    assert bed_after["current_admission_id"] is None

    unit_after = validate_success(api.get_unit(unit["id"], users.COORDINATOR))
    assert unit_after["beds_available"] == 1, (
        "only the first bed should be occupied, got beds_available "
        f"{unit_after['beds_available']!r}"
    )


def test_marking_outside_closed_segment_rejected(api):
    """An onset in the gap after a closed segment is not inside the recording.

    PRD §3.7: "The `onset_at` must fall inside a closed acquisition segment of the study,
    otherwise the marking is refused with `ERR_MARKING_OUTSIDE_STUDY_WINDOW`."
    PRD §2.6: "An event marking's `onset_at` falls inside a closed acquisition segment of
    its study, otherwise `ERR_MARKING_OUTSIDE_STUDY_WINDOW` (422)."

    Design: Corner/validations/marking_outside_closed_segment_rejected
    """
    baseline = fx.build_admitted_stay(
        api,
        bed_count=1,
        storage_quota_gb=500.00,
        requested_days=5,
        authorized_days=5,
        planned_days=2,
        target_event_count=2,
        admitted_at=const.T_ADMIT,
        channel_count=32,
    )
    # The only closed segment is [00:00, 02:00); the study is paused after it.
    fx.acquire_segment(
        api,
        baseline.study_id,
        from_iso=const.T_ADMIT,
        to_iso=SEGMENT_CLOSE,
        shift_id=baseline.shift_id,
    )
    fx.set_clock(api, "2026-08-02T04:00:00Z")

    validate_error(
        api.create_marking(
            f.marking_payload(
                baseline.study_id,
                "2026-08-02T03:00:00Z",
                event_class=const.EVENT_CLINICAL_SEIZURE,
                duration_seconds=45,
            ),
            users.EPILEPTOLOGIST,
        ),
        errors.ERR_MARKING_OUTSIDE_STUDY_WINDOW,
        422,
    )

    markings, meta = validate_paginated(
        api.list_markings(
            users.EPILEPTOLOGIST, dict(LIST_PARAMS, study_id=baseline.study_id)
        )
    )
    assert meta["total_count"] == 0, (
        f"the refused marking must not be stored, got total_count {meta['total_count']!r}"
    )
    assert meta["has_more"] is False
    assert markings == [], f"expected no markings, got {markings!r}"

    study = validate_success(api.get_study(baseline.study_id, users.EPILEPTOLOGIST))
    assert_study_dimensions(study, const.ACQ_PAUSED, const.DATA_ONLINE)
    assert study["closed_segment_count"] == 1
    assert_whole_minutes(study["acquired_minutes"], 120, "acquired_minutes")
    assert_storage_value(study["stored_gb"], 3.84, "stored_gb")

    admission = validate_success(
        api.get_admission(baseline.admission_id, users.EPILEPTOLOGIST)
    )
    assert_capture_value(
        admission["weighted_event_count"], 0.000, "weighted_event_count"
    )
    assert_capture_value(
        admission["capture_adequacy_index"], 0.000, "capture_adequacy_index"
    )


def test_export_quota_exceeded_on_build_returns_4xx(api):
    """A build whose volume would overrun the unit's storage quota is refused.

    PRD §2.6: "The unit's `storage_used_gb` plus the package volume about to be allocated
    does not exceed the unit's `storage_quota_gb`, otherwise `ERR_STORAGE_QUOTA_EXCEEDED`
    (409)."
    PRD §3.9: "Four conditions apply: the package must be `QUEUED`, otherwise
    `ERR_INVALID_EXPORT_STATE`; the study's `data_state` must be `ONLINE`, otherwise
    `ERR_INVALID_DATA_STATE`; the unit's `posture` must not be `STORAGE_LOCKED` —
    equivalently its `storage_pressure_pct` must be below 90.00 percent — otherwise
    `ERR_UNIT_STORAGE_LOCKED`; and the unit's `storage_used_gb` plus the volume about to be
    allocated must not exceed its `storage_quota_gb`, otherwise
    `ERR_STORAGE_QUOTA_EXCEEDED`."

    Design: Corner/validations/export_quota_exceeded_on_build_returns_4xx
    """
    baseline = fx.build_admitted_stay(
        api,
        bed_count=1,
        storage_quota_gb=150.00,
        requested_days=5,
        authorized_days=5,
        planned_days=3,
        target_event_count=2,
        admitted_at=const.T_ADMIT,
        channel_count=32,
    )
    # 3000 minutes at 0.0004 * 32 * 2.5 = 0.032 GB per minute = 96.00 GB
    study = fx.acquire_and_complete(
        api,
        baseline.study_id,
        baseline.shift_id,
        from_iso=const.T_ADMIT,
        to_iso="2026-08-04T02:00:00Z",
    )
    assert_whole_minutes(study["acquired_minutes"], 3000, "acquired_minutes")
    assert_storage_value(study["stored_gb"], 96.00, "stored_gb")
    fx.finalized_report(api, baseline.study_id)
    # include_video true, so the package would allocate another 96.00 GB
    package = fx.queue_export(api, baseline.study_id, include_video=True)

    validate_error(
        api.build_export(package["id"], users.COORDINATOR),
        errors.ERR_STORAGE_QUOTA_EXCEEDED,
        409,
    )

    package_after = validate_success(api.get_export(package["id"], users.COORDINATOR))
    assert package_after["status"] == const.EXPORT_QUEUED, (
        f"the refused build must leave the package QUEUED, got {package_after['status']!r}"
    )
    assert_storage_value(package_after["package_gb"], 0.00, "package_gb")
    assert package_after["built_at"] is None
    assert package_after["retention_expires_at"] is None

    unit = validate_success(api.get_unit(baseline.unit_id, users.COORDINATOR))
    # 96.00 / 150.00 * 100 = 64.00, still short of the 90.00 lock threshold
    assert_unit_storage(
        unit,
        storage_used_gb=96.00,
        storage_pressure_pct=64.00,
        posture=const.POSTURE_OPEN,
    )


def test_final_report_with_proposed_marking_returns_4xx(api):
    """A final interpretation cannot be issued while a marking is still proposed.

    PRD §3.8: "And no event marking of the study may still be `PROPOSED`, otherwise
    `ERR_MARKING_NOT_ADJUDICATED` — the interpretation cannot be final while findings
    remain unadjudicated."
    PRD §2.6: "No event marking of the study is still `PROPOSED` when the final
    interpretation is issued, otherwise `ERR_MARKING_NOT_ADJUDICATED` (409)."

    Design: Corner/validations/final_report_with_proposed_marking_returns_4xx
    """
    baseline = fx.build_admitted_stay(
        api,
        bed_count=1,
        storage_quota_gb=500.00,
        requested_days=5,
        authorized_days=5,
        planned_days=2,
        target_event_count=2,
        admitted_at=const.T_ADMIT,
        channel_count=32,
    )
    fx.acquire_and_complete(
        api,
        baseline.study_id,
        baseline.shift_id,
        from_iso=const.T_ADMIT,
        to_iso=SEGMENT_CLOSE,
    )
    marking = fx.create_marking(
        api,
        baseline.study_id,
        "2026-08-02T01:00:00Z",
        event_class=const.EVENT_CLINICAL_SEIZURE,
        duration_seconds=55,
    )
    assert marking["status"] == const.MARKING_PROPOSED
    report = fx.report_of_study(api, baseline.study_id)
    fx.issue_prelim(
        api,
        report["id"],
        localization="LEFT_FRONTAL",
        author_user_id=users.EPILEPTOLOGIST_ID,
        at=PRELIM_AT,
    )

    validate_error(
        api.issue_final(
            report["id"],
            f.issue_final_payload("LEFT_FRONTAL"),
            users.as_epileptologist(users.EPILEPTOLOGIST_ID_2),
        ),
        errors.ERR_MARKING_NOT_ADJUDICATED,
        409,
    )

    report_after = validate_success(
        api.get_report(report["id"], users.EPILEPTOLOGIST)
    )
    assert report_after["status"] == const.REPORT_PRELIM_ISSUED, (
        f"the refused final must leave the report PRELIM_ISSUED, got {report_after['status']!r}"
    )
    assert_ids_equal(
        report_after["prelim_author_user_id"],
        users.EPILEPTOLOGIST_ID,
        "prelim_author_user_id",
    )
    assert report_after["final_author_user_id"] is None
    assert report_after["final_issued_at"] is None

    marking_after = validate_success(
        api.get_marking(marking["id"], users.EPILEPTOLOGIST)
    )
    assert marking_after["status"] == const.MARKING_PROPOSED
    # No taper plan, so the onset step is 0 and the class weight stands undiscounted.
    assert_capture_value(marking_after["weight"], 1.000, "marking weight")

    admission = validate_success(
        api.get_admission(baseline.admission_id, users.EPILEPTOLOGIST)
    )
    assert_capture_value(
        admission["weighted_event_count"], 0.000, "weighted_event_count"
    )


def test_export_create_without_final_report_returns_4xx(api):
    """An export cannot be queued while the interpretation is only preliminary.

    PRD §3.9: "The study must already have a review report in `FINAL_ISSUED`, otherwise the
    create is refused with `ERR_REPORT_NOT_FINAL`."
    PRD §2.6: "The study has a review report in `FINAL_ISSUED` before an export package may
    be created against it, otherwise `ERR_REPORT_NOT_FINAL` (409)."

    Design: Corner/validations/export_create_without_final_report_returns_4xx
    """
    baseline = fx.build_admitted_stay(
        api,
        bed_count=1,
        storage_quota_gb=500.00,
        requested_days=5,
        authorized_days=5,
        planned_days=2,
        target_event_count=2,
        admitted_at=const.T_ADMIT,
        channel_count=32,
    )
    fx.acquire_and_complete(
        api,
        baseline.study_id,
        baseline.shift_id,
        from_iso=const.T_ADMIT,
        to_iso=SEGMENT_CLOSE,
    )
    report = fx.report_of_study(api, baseline.study_id)
    fx.issue_prelim(
        api,
        report["id"],
        localization="LEFT_TEMPORAL",
        author_user_id=users.EPILEPTOLOGIST_ID,
        at=PRELIM_AT,
    )
    # A freshly read version, so the version expectation cannot be what fails.
    study = validate_success(api.get_study(baseline.study_id, users.COORDINATOR))

    validate_error(
        api.create_export(
            f.export_payload(baseline.study_id, study["version"], include_video=True),
            users.COORDINATOR,
        ),
        errors.ERR_REPORT_NOT_FINAL,
        409,
    )

    packages, meta = validate_paginated(
        api.list_exports(
            users.COORDINATOR, dict(LIST_PARAMS, study_id=baseline.study_id)
        )
    )
    assert meta["total_count"] == 0, (
        f"the refused create must not store a package, got total_count {meta['total_count']!r}"
    )
    assert packages == [], f"expected no export packages, got {packages!r}"

    report_after = validate_success(api.get_report(report["id"], users.EPILEPTOLOGIST))
    assert report_after["status"] == const.REPORT_PRELIM_ISSUED
    assert report_after["final_issued_at"] is None

    unit = validate_success(api.get_unit(baseline.unit_id, users.COORDINATOR))
    assert_unit_storage(unit, storage_used_gb=3.84)


def test_duplicate_vote_in_same_round_rejected(api):
    """A second ballot from the same operator in the same round is refused.

    PRD §3.9: "An operator who has already cast a ballot on this case in the current
    `defer_round` is refused with `ERR_DUPLICATE_VOTE`; voting against a case that is not
    `PRESENTED` is `ERR_INVALID_CASE_STATE`."
    PRD §2.6: "The voting `X-User-ID` has not already cast a ballot on this case in the
    current `defer_round`, otherwise `ERR_DUPLICATE_VOTE` (409)."

    Design: Corner/validations/duplicate_vote_in_same_round_rejected
    """
    baseline = fx.build_admitted_stay(
        api,
        bed_count=1,
        storage_quota_gb=500.00,
        requested_days=5,
        authorized_days=5,
        planned_days=2,
        target_event_count=3,
        admitted_at=const.T_ADMIT,
        channel_count=32,
    )
    fx.acquire_and_complete(
        api,
        baseline.study_id,
        baseline.shift_id,
        from_iso=const.T_ADMIT,
        to_iso=SEGMENT_CLOSE,
    )
    fx.finalized_report(api, baseline.study_id, prelim_at=PRELIM_AT)
    package = fx.delivered_export(
        api,
        baseline.study_id,
        include_video=True,
        recipient_center="Metro Surgical Center",
    )
    fx.set_clock(api, CONFERENCE_AT)
    case = fx.presented_case(
        api,
        admission_id=baseline.admission_id,
        export_id=package["id"],
        presenter_user_id="epi-p",
    )
    first_ballot = fx.cast_ballot(
        api,
        case["id"],
        voter_user_id="epi-a",
        specialty=const.SPECIALTY_EPILEPTOLOGY,
        vote=const.VOTE_CANDIDATE,
        rationale="clear focal onset",
    )

    validate_error(
        api.cast_vote(
            case["id"],
            f.vote_payload(
                specialty=const.SPECIALTY_EPILEPTOLOGY,
                vote=const.VOTE_NON_CANDIDATE,
                rationale="reconsidered",
            ),
            users.as_epileptologist("epi-a"),
        ),
        errors.ERR_DUPLICATE_VOTE,
        409,
    )

    ballots, meta = validate_paginated(
        api.list_case_votes(case["id"], users.EPILEPTOLOGIST, dict(LIST_PARAMS))
    )
    assert meta["total_count"] == 1, (
        f"only the first ballot should be stored, got total_count {meta['total_count']!r}"
    )
    stored = ballots[0]
    assert_ids_equal(stored["id"], first_ballot["id"], "vote id")
    assert stored["vote"] == const.VOTE_CANDIDATE, (
        "the refused ballot must not overwrite the first vote"
    )
    assert_ids_equal(stored["voter_user_id"], "epi-a", "voter_user_id")
    assert stored["round_index"] == 0
    assert stored["counted"] is True

    case_after = validate_success(
        api.get_conference_case(case["id"], users.EPILEPTOLOGIST)
    )
    assert case_after["status"] == const.CASE_PRESENTED
    assert case_after["defer_round"] == 0
    assert case_after["decision_at"] is None


def test_clock_monotonic_violation_rejected(api):
    """The logical clock refuses to move backwards and keeps its advanced value.

    PRD §2.4: "The clock is monotonic: a request whose `to_iso8601` is earlier than the
    current logical value is rejected with `ERR_CLOCK_MONOTONIC` (HTTP 422)."

    Design: Corner/validations/clock_monotonic_violation_rejected
    """
    fx.create_unit(api, bed_count=1, storage_quota_gb=500.00)
    fx.set_clock(api, const.T_ADMIT)

    validate_error(
        api.set_clock("2026-08-01T00:00:00Z", users.COORDINATOR),
        errors.ERR_CLOCK_MONOTONIC,
        422,
    )

    # A record created next is still stamped from the advanced value.
    patient = validate_success(
        api.create_patient(
            f.patient_payload(
                mrn="MRN-CLOCK-1",
                display_name="Clock Probe",
                risk_tier=const.RISK_LOW,
            ),
            users.COORDINATOR,
        ),
        201,
    )
    assert_instant_equals(patient["created_at"], const.T_ADMIT, "patient created_at")


def test_shift_window_invalid_rejected(api):
    """A coverage window that ends exactly when it starts is refused.

    PRD §3.1: "A window whose `ends_at` is not strictly after its `starts_at` is refused
    with `ERR_SHIFT_WINDOW_INVALID`."
    PRD §2.6: "A coverage window's `ends_at` is strictly after its `starts_at`, otherwise
    `ERR_SHIFT_WINDOW_INVALID` (422); and the logical clock never moves backwards,
    otherwise `ERR_CLOCK_MONOTONIC` (422)."

    Design: Corner/validations/shift_window_invalid_rejected
    """
    unit = fx.create_unit(api, bed_count=1, storage_quota_gb=500.00)

    validate_error(
        api.create_shift(
            f.shift_payload(
                unit["id"],
                technologist_user_id=users.TECHNOLOGIST_ID,
                starts_at=const.T_ADMIT,
                ends_at=const.T_ADMIT,
                max_concurrent_studies=2,
            ),
            users.COORDINATOR,
        ),
        errors.ERR_SHIFT_WINDOW_INVALID,
        422,
    )

    shifts, meta = validate_paginated(
        api.list_unit_shifts(unit["id"], users.COORDINATOR, dict(LIST_PARAMS))
    )
    assert meta["total_count"] == 0, (
        f"the refused window must not be stored, got total_count {meta['total_count']!r}"
    )
    assert meta["has_more"] is False
    assert shifts == [], f"expected no coverage windows, got {shifts!r}"

    unit_after = validate_success(api.get_unit(unit["id"], users.COORDINATOR))
    assert unit_after["coverage_capacity"] == 0, (
        "no active window means no capacity, got coverage_capacity "
        f"{unit_after['coverage_capacity']!r}"
    )
    assert unit_after["posture"] == const.POSTURE_OPEN


def test_target_already_met_blocks_extension_returns_4xx(api):
    """A stay that has already met its capture target cannot be extended.

    PRD §3.7: "It is guarded by the version expectation of §2.7, and before any arithmetic
    runs, two refusals apply: an admission already standing in `CAPTURE_TARGET_MET` is
    refused with `ERR_TARGET_ALREADY_MET`, since its deficit is zero and no extension is
    warranted, and a `DISCHARGED` admission is refused with `ERR_INVALID_ADMISSION_STATE`."
    PRD §2.6: "The admission has not already met its capture target when an extension is
    requested, otherwise `ERR_TARGET_ALREADY_MET` (409)."

    Design: Corner/validations/target_already_met_blocks_extension_returns_4xx
    """
    baseline = fx.build_admitted_stay(
        api,
        bed_count=1,
        storage_quota_gb=500.00,
        requested_days=5,
        authorized_days=5,
        planned_days=2,
        target_event_count=1,
        admitted_at=const.T_ADMIT,
        channel_count=32,
    )
    fx.acquire_segment(
        api,
        baseline.study_id,
        from_iso=const.T_ADMIT,
        to_iso=SEGMENT_CLOSE,
        shift_id=baseline.shift_id,
    )
    fx.set_clock(api, const.T_ADMIT_PLUS_1D)
    # One adjudicated clinical seizure against a target of one meets the target exactly.
    fx.create_marking(
        api,
        baseline.study_id,
        "2026-08-02T01:00:00Z",
        event_class=const.EVENT_CLINICAL_SEIZURE,
        duration_seconds=80,
        adjudicate=True,
    )
    admission = validate_success(
        api.get_admission(baseline.admission_id, users.EPILEPTOLOGIST)
    )
    assert admission["clinical_state"] == const.CLINICAL_CAPTURE_TARGET_MET, (
        f"the stay should stand in CAPTURE_TARGET_MET, got {admission['clinical_state']!r}"
    )

    validate_error(
        api.record_extension_decision(
            baseline.admission_id,
            f.extension_payload(admission["version"]),
            users.EPILEPTOLOGIST,
        ),
        errors.ERR_TARGET_ALREADY_MET,
        409,
    )

    admission_after = validate_success(
        api.get_admission(baseline.admission_id, users.EPILEPTOLOGIST)
    )
    assert admission_after["clinical_state"] == const.CLINICAL_CAPTURE_TARGET_MET
    assert_capture_value(
        admission_after["capture_adequacy_index"], 1.000, "capture_adequacy_index"
    )
    assert_capture_value(
        admission_after["weighted_event_count"], 1.000, "weighted_event_count"
    )
    assert_capture_value(
        admission_after["elapsed_monitored_days"], 1.000, "elapsed_monitored_days"
    )
    assert_capture_value(admission_after["deficit_weighted"], 0.000, "deficit_weighted")
    assert admission_after["extension_count"] == 0, (
        "the refused extension must not be counted"
    )
    assert admission_after["last_extension_outcome"] is None
    assert admission_after["last_extension_granted_days"] == 0

    authorization = validate_success(
        api.get_authorization(baseline.authorization["id"], users.EPILEPTOLOGIST)
    )
    assert_ledger(authorization, days_reserved=2, days_available=3)


def test_study_start_with_coverage_and_capacity_satisfied_succeeds(api):
    """A study named against an active window inside its hours starts and pins the window.

    PRD §3.5: "Six conditions must hold, and each has its own rejection: the study must be
    `PREPARING` (`ERR_INVALID_STUDY_STATE`); the admission's `clinical_state` must be
    `ADMITTED` (`ERR_INVALID_ADMISSION_STATE`); the study's `modality` must equal the
    admission's `setting` (`ERR_SETTING_MISMATCH`); the named window's `state` must be
    `ACTIVE` with the logical clock inside its window, at or after `starts_at` and strictly
    before `ends_at` (`ERR_NO_TECH_COVERAGE`); that window's `assigned_study_count` must be
    strictly less than its `max_concurrent_studies` (`ERR_TECH_CAPACITY_EXCEEDED`); and the
    unit's `posture` must not be `STORAGE_LOCKED` (`ERR_UNIT_STORAGE_LOCKED`)."
    PRD §3.5: "On success the study pins the named window on its own `shift_id` and keeps
    it for the rest of its life, opens its first segment by stamping
    `current_segment_started_at` from the clock, increments the window's
    `assigned_study_count`, increments the unit's `active_study_count` and re-derives the
    unit's `posture` — which may now read `COVERAGE_CONSTRAINED` — and increments the
    study's `version` by 1."

    Design: Corner/validations/study_start_with_coverage_and_capacity_satisfied_succeeds
    """
    baseline = fx.build_admitted_stay(
        api,
        bed_count=1,
        storage_quota_gb=500.00,
        requested_days=5,
        authorized_days=5,
        planned_days=2,
        target_event_count=2,
        admitted_at=const.T_ADMIT,
        shift_starts_at=const.T_ADMIT,
        shift_ends_at="2026-08-10T00:00:00Z",
        max_concurrent_studies=2,
        channel_count=32,
    )

    study = validate_success(
        api.start_study(
            baseline.study_id,
            f.start_payload(baseline.shift_id),
            users.TECHNOLOGIST,
        ),
        200,
    )
    assert_study_dimensions(study, const.ACQ_ACQUIRING, const.DATA_ONLINE)
    assert_ids_equal(study["shift_id"], baseline.shift_id, "study shift_id")
    assert_instant_equals(
        study["current_segment_started_at"], const.T_ADMIT, "current_segment_started_at"
    )
    assert_whole_minutes(study["acquired_minutes"], 0, "acquired_minutes")
    assert study["closed_segment_count"] == 0
    assert_storage_value(study["stored_gb"], 0.00, "stored_gb")
    assert_version_is(study, 2, "study")

    shift = validate_success(api.get_shift(baseline.shift_id, users.COORDINATOR))
    assert shift["assigned_study_count"] == 1, (
        f"the window should carry one study, got {shift['assigned_study_count']!r}"
    )
    assert shift["state"] == const.SHIFT_ACTIVE

    unit = validate_success(api.get_unit(baseline.unit_id, users.COORDINATOR))
    assert unit["active_study_count"] == 1, (
        f"the unit should count one acquiring study, got {unit['active_study_count']!r}"
    )
    assert unit["coverage_capacity"] == 2, (
        f"the active window supplies capacity 2, got {unit['coverage_capacity']!r}"
    )
    assert unit["posture"] == const.POSTURE_OPEN, (
        "one acquiring study against capacity 2 leaves the unit OPEN"
    )
