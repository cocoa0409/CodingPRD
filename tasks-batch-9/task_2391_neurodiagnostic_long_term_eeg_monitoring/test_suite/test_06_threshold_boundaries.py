"""
Thresholds probed exactly on their edge.

Three inclusive-or-exclusive comparators decide behaviour in this contract: the
storage lock fires at 90.00 percent inclusive, the preliminary reading service
level is breached only strictly beyond eight coverage hours, and an extension
decision needs a strictly non-zero yield basis before any arithmetic runs. Each
test lands the governing figure exactly on its edge, or one minimal step past
it, and recomputes the pinned figure from the stated formula.
"""

from test_helpers import (
    api_errors,
    assert_capture_value,
    assert_instant_equals,
    assert_ledger,
    assert_storage_value,
    assert_turnaround_value,
    assert_unit_storage,
    assert_whole_minutes,
    factories,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.constants import (
    ACQ_ACQUIRING,
    CLINICAL_ADMITTED,
    POSTURE_OPEN,
    POSTURE_STORAGE_LOCKED,
    REPORT_PRELIM_ISSUED,
    SETTING_INPATIENT,
    T_ADMIT,
    T_COMPLETE,
)
from test_helpers.test_users import COORDINATOR, EPILEPTOLOGIST, TECHNOLOGIST

SHIFT_END = "2026-08-10T00:00:00Z"

# Storage boundary instants: a first segment two minutes short of the lock, then
# a two-minute second segment that lands the unit exactly on it.
FIRST_SEGMENT_END = "2026-08-04T11:58:00Z"
SECOND_SEGMENT_START = "2026-08-04T12:00:00Z"
SECOND_SEGMENT_END = "2026-08-04T12:02:00Z"

# Turnaround boundary instants measured from a completion at 2026-08-04T12:00:00Z.
PRELIM_AT_EIGHT_COVERAGE_HOURS = "2026-08-05T10:00:00Z"
PRELIM_ONE_MINUTE_LATER = "2026-08-05T10:01:00Z"


# ---------------------------------------------------------------------------
# Storage pressure: the lock fires at exactly 90.00 percent
# ---------------------------------------------------------------------------


def _stay_two_minutes_short_of_the_storage_lock(api):
    """A 25-channel inpatient recording holding 89.95 GB against a 100.00 GB quota.

    The per-minute rate is 0.0004 * 25 * 2.5 = 0.025 GB. The first closed segment
    runs 2026-08-02T00:00:00Z to 2026-08-04T11:58:00Z, which is 3598 whole
    minutes, so 3598 * 0.025 = 89.95 GB. Against a 100.00 GB quota that is 89.95
    percent, two hundredths of a point below the lock.
    """
    stay = fixtures.build_admitted_stay(
        api,
        storage_quota_gb=100.00,
        max_concurrent_studies=2,
        channel_count=25,
        shift_ends_at=SHIFT_END,
    )
    fixtures.acquire_segment(
        api,
        stay.study_id,
        from_iso=T_ADMIT,
        to_iso=FIRST_SEGMENT_END,
        shift_id=stay.shift_id,
    )
    return stay


def test_storage_pressure_just_below_ninety_leaves_the_unit_open(api):
    """At 89.95 percent the unit is still OPEN, and acquisition may be resumed.

    PRD §3.5: "For each segment, take its duration truncated down to whole minutes, multiply by the per-minute rate, and round that product half up to 2 decimal places to get that segment's volume; then add the segment volume to the running total and round the new running total half up to 2 decimal places before moving on."
    PRD §2.11: "Otherwise the posture is `OPEN`, which is also the value a newly created unit carries."

    Design: Difficulty/boundary_precision_check/storage_pressure_exactly_ninety_locks_unit
    """
    stay = _stay_two_minutes_short_of_the_storage_lock(api)

    study = validate_success(api.get_study(stay.study_id, TECHNOLOGIST))
    assert_whole_minutes(study["acquired_minutes"], 3598, "acquired_minutes")
    assert study["closed_segment_count"] == 1, (
        f"one segment should have closed, got {study['closed_segment_count']!r}"
    )
    assert_storage_value(study["stored_gb"], 89.95, "stored_gb")

    unit = validate_success(api.get_unit(stay.unit_id, COORDINATOR))
    assert_unit_storage(
        unit,
        storage_used_gb=89.95,
        storage_pressure_pct=89.95,
        posture=POSTURE_OPEN,
    )

    # The lock has not fired, so the storage-lock guard on resume does not bite.
    fixtures.set_clock(api, SECOND_SEGMENT_START)
    resumed = validate_success(api.resume_study(stay.study_id, TECHNOLOGIST))
    assert resumed["acquisition_state"] == ACQ_ACQUIRING, (
        "a unit below the storage lock should permit a resume, got acquisition_state "
        f"{resumed['acquisition_state']!r}"
    )


def test_storage_pressure_of_exactly_ninety_locks_the_unit(api):
    """Closing a second segment lands storage pressure on 90.00 percent, and the inclusive comparator locks the unit.

    PRD §2.11: "If `storage_pressure_pct` has reached 90.00 percent or more, the posture is `STORAGE_LOCKED`."
    PRD §3.5: "Rounding each segment and re-rounding after each accumulation is required; summing raw segment volumes and rounding once at the end yields a different figure and is wrong."

    Design: Difficulty/boundary_precision_check/storage_pressure_exactly_ninety_locks_unit
    """
    stay = _stay_two_minutes_short_of_the_storage_lock(api)

    # A second segment of exactly 2 minutes adds 2 * 0.025 = 0.05 GB, taking the
    # running total from 89.95 to exactly 90.00.
    fixtures.acquire_segment(
        api,
        stay.study_id,
        from_iso=SECOND_SEGMENT_START,
        to_iso=SECOND_SEGMENT_END,
    )

    study = validate_success(api.get_study(stay.study_id, TECHNOLOGIST))
    assert study["closed_segment_count"] == 2, (
        f"two segments should have closed, got {study['closed_segment_count']!r}"
    )
    assert_whole_minutes(study["acquired_minutes"], 3600, "acquired_minutes")
    assert_storage_value(study["stored_gb"], 90.00, "stored_gb")

    unit = validate_success(api.get_unit(stay.unit_id, COORDINATOR))
    assert_unit_storage(
        unit,
        storage_used_gb=90.00,
        storage_pressure_pct=90.00,
        posture=POSTURE_STORAGE_LOCKED,
    )


def test_the_lock_at_exactly_ninety_refuses_a_resume(api):
    """The posture reached at exactly 90.00 percent is enforced, not merely reported.

    PRD §3.5: "The study must be `PAUSED`, otherwise `ERR_INVALID_STUDY_STATE`; the pinned coverage window must again be `ACTIVE` with the clock inside its half-open window, otherwise `ERR_NO_TECH_COVERAGE`; and the unit must not be `STORAGE_LOCKED`, otherwise `ERR_UNIT_STORAGE_LOCKED`."

    Design: Difficulty/boundary_precision_check/storage_pressure_exactly_ninety_locks_unit
    """
    stay = _stay_two_minutes_short_of_the_storage_lock(api)
    fixtures.acquire_segment(
        api,
        stay.study_id,
        from_iso=SECOND_SEGMENT_START,
        to_iso=SECOND_SEGMENT_END,
    )
    unit = validate_success(api.get_unit(stay.unit_id, COORDINATOR))
    assert_unit_storage(
        unit, storage_pressure_pct=90.00, posture=POSTURE_STORAGE_LOCKED
    )

    response = api.resume_study(stay.study_id, TECHNOLOGIST)

    validate_error(response, api_errors.ERR_UNIT_STORAGE_LOCKED, 409)


# ---------------------------------------------------------------------------
# Yield basis: zero banked weight is no basis at all
# ---------------------------------------------------------------------------


def _admitted_stay_with_no_adjudicated_markings(api):
    """A one-day-old stay targeting 4 weighted events with nothing banked yet.

    The stay is admitted at 2026-08-02T00:00:00Z against a 5-day authorization
    with 2 planned days reserved, and the clock is moved to 2026-08-03T00:00:00Z,
    exactly one elapsed monitored day. No marking has been adjudicated, so the
    banked weight is 0.000 and the yield has no basis.
    """
    stay = fixtures.build_admitted_stay(
        api,
        storage_quota_gb=500.00,
        max_concurrent_studies=2,
        channel_count=32,
        target_event_count=4,
        planned_days=2,
        requested_days=5,
        shift_ends_at=SHIFT_END,
    )
    fixtures.create_taper_plan(api, stay.admission_id, total_steps=3, steps_advanced=0)
    fixtures.start_study(api, stay.study_id, stay.shift_id, at=T_ADMIT)
    fixtures.set_clock(api, "2026-08-03T00:00:00Z")
    return stay


def test_extension_decision_without_banked_weight_has_no_yield_basis(api):
    """An extension decision on a stay with zero banked weight is refused before any arithmetic runs.

    PRD §2.6: "**Yield basis.** The admission has a non-zero `weighted_event_count` and a non-zero `elapsed_monitored_days`, otherwise `ERR_NO_YIELD_BASIS` (422)."
    PRD §3.7: "**Step three** reads `projected_daily_yield`; if the admission's `weighted_event_count` is zero or the elapsed monitored days figure is zero, the yield has no basis and the request is refused with `ERR_NO_YIELD_BASIS`."

    Design: Difficulty/boundary_precision_check/extension_with_empty_adjudicated_set_has_no_yield_basis
    """
    stay = _admitted_stay_with_no_adjudicated_markings(api)
    admission = validate_success(api.get_admission(stay.admission_id, EPILEPTOLOGIST))
    # Exactly one of the two basis inputs is zero: a day has elapsed, but no
    # adjudicated marking has banked any weight.
    assert_capture_value(
        admission["weighted_event_count"], 0.000, "weighted_event_count"
    )
    assert_capture_value(
        admission["elapsed_monitored_days"], 1.000, "elapsed_monitored_days"
    )
    assert_capture_value(
        admission["projected_daily_yield"], 0.000, "projected_daily_yield"
    )
    assert_capture_value(admission["deficit_weighted"], 4.000, "deficit_weighted")

    response = api.record_extension_decision(
        stay.admission_id,
        factories.extension_payload(admission["version"]),
        EPILEPTOLOGIST,
    )

    validate_error(response, api_errors.ERR_NO_YIELD_BASIS, 422)


def test_refused_extension_decision_records_no_outcome(api):
    """Because the decision was refused rather than decided, no outcome is recorded and the day ledger does not move.

    PRD §3.7: "`extension_count` increases by 1, `last_extension_granted_days` is set to the days granted — 0 for any refusal — and `last_extension_outcome` records which of the four declared outcomes applied: `GRANTED`, `DENIED_RISK`, `DENIED_AUTH_DAYS` or `DENIED_TARGET_MET`."
    PRD §3.3: "It reserves the days on the funding ledger, adding `planned_days` to `days_reserved` and subtracting the same from `days_available` so the conserved equality still holds."

    Design: Difficulty/boundary_precision_check/extension_with_empty_adjudicated_set_has_no_yield_basis
    """
    stay = _admitted_stay_with_no_adjudicated_markings(api)
    admission_before = validate_success(
        api.get_admission(stay.admission_id, EPILEPTOLOGIST)
    )

    validate_error(
        api.record_extension_decision(
            stay.admission_id,
            factories.extension_payload(admission_before["version"]),
            EPILEPTOLOGIST,
        ),
        api_errors.ERR_NO_YIELD_BASIS,
        422,
    )

    admission = validate_success(api.get_admission(stay.admission_id, EPILEPTOLOGIST))
    assert admission["extension_count"] == 0, (
        "a refused decision is not one of the four declared outcomes, so nothing "
        f"should have been counted, got extension_count {admission['extension_count']!r}"
    )
    assert admission["last_extension_granted_days"] == 0, (
        f"no days were granted, got {admission['last_extension_granted_days']!r}"
    )
    assert admission["last_extension_outcome"] is None, (
        "no declared outcome applies to a refused decision, got "
        f"{admission['last_extension_outcome']!r}"
    )
    assert admission["clinical_state"] == CLINICAL_ADMITTED, (
        f"the stay should still be ADMITTED, got {admission['clinical_state']!r}"
    )
    assert admission["version"] == admission_before["version"], (
        f"a refused decision mutates nothing, version moved to {admission['version']!r}"
    )

    authorization = validate_success(
        api.get_authorization(stay.authorization_id, COORDINATOR)
    )
    # Only the 2 planned days reserved at admission stand against the 5 authorized.
    assert_ledger(
        authorization,
        authorized_days=5,
        days_consumed=0,
        days_reserved=2,
        days_available=3,
    )


# ---------------------------------------------------------------------------
# Preliminary turnaround: eight coverage hours exactly is not a breach
# ---------------------------------------------------------------------------


def _completed_studies_awaiting_interpretation(api, count=1):
    """`count` 25-channel inpatient recordings, all completed at 2026-08-04T12:00:00Z.

    Each recording synthesizes exactly one review report in `PRELIM_DRAFT`, so
    turnaround is measured from the shared completion instant.
    """
    stay = fixtures.build_admitted_stay(
        api,
        storage_quota_gb=500.00,
        max_concurrent_studies=count,
        channel_count=25,
        shift_ends_at=SHIFT_END,
    )
    studies = [stay.study]
    for _ in range(count - 1):
        studies.append(
            fixtures.create_study(
                api, stay.admission_id, channel_count=25, modality=SETTING_INPATIENT
            )
        )
    for study in studies:
        fixtures.start_study(api, study["id"], stay.shift_id, at=T_ADMIT)
    for study in studies:
        fixtures.complete_study(api, study["id"], at=T_COMPLETE)
    return stay, studies


def test_exactly_eight_coverage_hours_is_not_an_sla_breach(api):
    """A preliminary read delivered on exactly eight coverage hours is not a breach.

    PRD §3.8: "To compute it, walk each UTC calendar day from the date of the study completion through the date of the preliminary issuance inclusive; for each such day, take that day's reading window, take the portion of the interval between the two instants that overlaps that window — treating a non-overlap as zero rather than as a negative amount — and add the overlap's minutes to a running total."
    PRD §3.8: "`sla_breached` is true if and only if `turnaround_coverage_hours` is **strictly greater** than the eight-hour preliminary reading service level; a coverage figure of exactly 8 is not a breach."

    Design: Difficulty/boundary_precision_check/prelim_sla_coverage_boundary_at_eight_hours
    """
    _stay, studies = _completed_studies_awaiting_interpretation(api)
    report = fixtures.report_of_study(api, studies[0]["id"])

    issued = fixtures.issue_prelim(
        api, report["id"], at=PRELIM_AT_EIGHT_COVERAGE_HOURS
    )

    assert issued["status"] == REPORT_PRELIM_ISSUED, (
        f"the report should have moved to PRELIM_ISSUED, got {issued['status']!r}"
    )
    assert_instant_equals(
        issued["prelim_issued_at"], PRELIM_AT_EIGHT_COVERAGE_HOURS, "prelim_issued_at"
    )
    # 2026-08-04 contributes 12:00 to 18:00, six hours; 2026-08-05 contributes
    # 08:00 to 10:00, two hours; 480 minutes over 60 is exactly 8.00.
    assert_turnaround_value(
        issued["turnaround_coverage_hours"], 8.00, "turnaround_coverage_hours"
    )
    assert_turnaround_value(
        issued["turnaround_calendar_hours"], 22.00, "turnaround_calendar_hours"
    )
    assert issued["sla_breached"] is False, (
        "a coverage figure of exactly 8 is not a breach, got sla_breached "
        f"{issued['sla_breached']!r}"
    )


def test_one_minute_beyond_eight_coverage_hours_is_an_sla_breach(api):
    """One logical minute past the boundary breaches, while the report read on the boundary does not.

    PRD §3.8: "The coverage figure on `turnaround_coverage_hours` counts only the minutes that fall inside the unit's daily reading window, which runs from 08:00:00 UTC up to but not including 18:00:00 UTC."
    PRD §3.8: "The coverage figure is that total divided by 60, rounded half up to 2 decimal places."

    Design: Difficulty/boundary_precision_check/prelim_sla_coverage_boundary_at_eight_hours
    """
    _stay, studies = _completed_studies_awaiting_interpretation(api, count=2)
    report_on_boundary = fixtures.report_of_study(api, studies[0]["id"])
    report_past_boundary = fixtures.report_of_study(api, studies[1]["id"])

    on_boundary = fixtures.issue_prelim(
        api, report_on_boundary["id"], at=PRELIM_AT_EIGHT_COVERAGE_HOURS
    )
    past_boundary = fixtures.issue_prelim(
        api, report_past_boundary["id"], at=PRELIM_ONE_MINUTE_LATER
    )

    assert past_boundary["status"] == REPORT_PRELIM_ISSUED, (
        f"the second report should have moved to PRELIM_ISSUED, got {past_boundary['status']!r}"
    )
    # 481 covered minutes over 60 is 8.0166..., which rounds half up to 8.02.
    assert_turnaround_value(
        past_boundary["turnaround_coverage_hours"], 8.02, "turnaround_coverage_hours"
    )
    # 22 hours and 1 minute is 22.0166..., which rounds half up to 22.02.
    assert_turnaround_value(
        past_boundary["turnaround_calendar_hours"], 22.02, "turnaround_calendar_hours"
    )
    assert past_boundary["sla_breached"] is True, (
        "8.02 coverage hours is strictly greater than the eight-hour service level, so "
        f"it should breach, got sla_breached {past_boundary['sla_breached']!r}"
    )

    # The strict comparator seen from both sides in one run.
    assert_turnaround_value(
        on_boundary["turnaround_coverage_hours"], 8.00, "turnaround_coverage_hours"
    )
    assert on_boundary["sla_breached"] is False, (
        "the report read on the boundary should still not be a breach, got "
        f"sla_breached {on_boundary['sla_breached']!r}"
    )
