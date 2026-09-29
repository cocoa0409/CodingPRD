"""
Two resources this contract shares over time, and the windows that govern them.

A bed cannot host a second stay until its turnover buffer has elapsed, and a
coverage window only lends its concurrency allowance while the logical clock
stands inside it. Both boundaries are exact instants, so each test below probes
the refused side and the permitted side of the same boundary and then checks the
figures the unit derives from the window that actually contains the clock.
"""

from test_helpers import (
    api_errors as e,
    assert_admission_dimensions,
    assert_ids_equal,
    assert_instant_equals,
    assert_storage_value,
    assert_whole_minutes,
    constants as c,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import COORDINATOR, TECHNOLOGIST

# The first stay ends mid-afternoon, so the 90-minute buffer expires at 13:30Z.
FIRST_RELEASE_AT = "2026-08-04T12:00:00Z"
ONE_MINUTE_BEFORE_CLEAR = "2026-08-04T13:29:00Z"
TURNOVER_CLEAR_AT = "2026-08-04T13:30:00Z"

# Two abutting coverage windows: only the first one contains the working clock.
FIRST_WINDOW_STARTS_AT = "2026-08-02T00:00:00Z"
FIRST_WINDOW_ENDS_AT = "2026-08-03T00:00:00Z"
SECOND_WINDOW_ENDS_AT = "2026-08-04T00:00:00Z"
WORKING_CLOCK = "2026-08-02T12:00:00Z"


def _single_bed_stay(api):
    """One unit with exactly one bed, occupied by a two-day inpatient stay."""
    return fx.build_admitted_stay(
        api,
        bed_count=1,
        bed_labels=["EMU-1"],
        storage_quota_gb=500.00,
        risk_tier=c.RISK_LOW,
        requested_days=5,
        planned_days=2,
        target_event_count=3,
        admitted_at=c.T_ADMIT,
        with_shift=False,
        with_study=False,
    )


def _waiting_admission(api, unit_id):
    """A second patient scheduled into the same unit, waiting for the bed."""
    patient = fx.create_patient(api, display_name="Pat Waiting", risk_tier=c.RISK_LOW)
    authorization = fx.approved_authorization(
        api, patient["id"], requested_days=5, authorized_days=5
    )
    return fx.schedule_admission(
        api,
        patient_id=patient["id"],
        authorization_id=authorization["id"],
        unit_id=unit_id,
        scheduled_admit_at=ONE_MINUTE_BEFORE_CLEAR,
        target_event_count=3,
        planned_days=2,
    )


def _bed_by_id(api, unit_id, bed_id):
    """Read one bed back through the unit's bed listing."""
    beds, _meta = validate_paginated(api.list_unit_beds(unit_id, COORDINATOR))
    matches = [bed for bed in beds if bed["id"] == bed_id]
    assert matches, f"bed {bed_id} is missing from the listing for unit {unit_id}"
    return matches[0]


def _two_abutting_windows(api):
    """A stay under two adjacent windows, only the earlier of which holds the clock."""
    stay = fx.build_admitted_stay(
        api,
        storage_quota_gb=500.00,
        risk_tier=c.RISK_MODERATE,
        requested_days=5,
        planned_days=5,
        target_event_count=4,
        admitted_at=c.T_ADMIT,
        shift_starts_at=FIRST_WINDOW_STARTS_AT,
        shift_ends_at=FIRST_WINDOW_ENDS_AT,
        max_concurrent_studies=2,
        with_study=False,
    )
    later_window = fx.create_shift(
        api,
        stay.unit_id,
        technologist_user_id="tech-2",
        starts_at=FIRST_WINDOW_ENDS_AT,
        ends_at=SECOND_WINDOW_ENDS_AT,
        max_concurrent_studies=2,
    )
    fx.set_clock(api, WORKING_CLOCK)
    studies = [
        fx.create_study(api, stay.admission_id, channel_count=32)["id"] for _ in range(3)
    ]
    fx.start_study(api, studies[0], stay.shift_id)
    fx.start_study(api, studies[1], stay.shift_id)
    return stay, later_window, studies


# ---------------------------------------------------------------------------
# The bed turnover buffer is a half-open exclusion
# ---------------------------------------------------------------------------


def test_readmission_refused_one_minute_before_the_turnover_buffer_clears(api):
    """The released bed reopens exactly at its turnover_clear_at, not a minute earlier.

    PRD §2.6: "The requested bed is available — it has no `current_admission_id`, and either its `released_at` is null or the logical clock has reached its `turnover_clear_at` — otherwise `ERR_BED_OCCUPANCY_CONFLICT` (409)."
    PRD §3.1: "The turnover buffer itself is a fixed hour and a half: `turnover_clear_at` is 90 minutes after `released_at`, and it is null whenever `released_at` is null."

    Design: Difficulty/resource_temporal_overlap/bed_turnover_buffer_is_half_open
    """
    stay = _single_bed_stay(api)
    waiting = _waiting_admission(api, stay.unit_id)
    fx.discharge(api, stay.admission_id, disposition=c.DISPOSITION_ROUTINE, at=FIRST_RELEASE_AT)

    fx.set_clock(api, ONE_MINUTE_BEFORE_CLEAR)
    refused = api.admit(waiting["id"], f.admit_payload(stay.bed_id), COORDINATOR)
    validate_error(refused, e.ERR_BED_OCCUPANCY_CONFLICT, 409)

    still_scheduled = validate_success(api.get_admission(waiting["id"], COORDINATOR))
    # PRD 3.3: a scheduled admission opens at AUTH_PENDING and only the
    # successful admit moves it to AUTH_ACTIVE, so a refused admit leaves the
    # funding dimension exactly where scheduling left it.
    assert_admission_dimensions(
        still_scheduled, c.CLINICAL_SCHEDULED, c.AUTH_STATE_PENDING
    )

    # The buffer expiry is inclusive: reaching turnover_clear_at is enough.
    fx.set_clock(api, TURNOVER_CLEAR_AT)
    admitted = validate_success(
        api.admit(waiting["id"], f.admit_payload(stay.bed_id), COORDINATOR)
    )
    assert_admission_dimensions(admitted, c.CLINICAL_ADMITTED, c.AUTH_STATE_ACTIVE)
    assert_instant_equals(admitted["admitted_at"], TURNOVER_CLEAR_AT, "admitted_at")
    # Two planned days of 24 hours each, measured from the new admitted_at.
    assert_instant_equals(
        admitted["planned_discharge_at"],
        "2026-08-06T13:30:00Z",
        "planned_discharge_at",
    )
    assert_ids_equal(admitted["bed_id"], stay.bed_id, "admission bed_id")

    bed = _bed_by_id(api, stay.unit_id, stay.bed_id)
    assert bed["status"] == c.BED_OCCUPIED, (
        f"the re-admitted bed should read OCCUPIED, got {bed['status']!r}"
    )
    assert_ids_equal(bed["current_admission_id"], waiting["id"], "current_admission_id")


def test_released_bed_reads_turnover_for_ninety_minutes(api):
    """Discharge releases the bed into a computed TURNOVER window rather than free it.

    PRD §3.1: "A bed reads `TURNOVER` when its `released_at` is set and the logical clock has not yet reached its `turnover_clear_at`."
    PRD §3.3: "For an inpatient stay it releases the bed: the bed's `current_admission_id` is cleared, its `released_at` is set to `discharged_at`, its `turnover_clear_at` is set to 90 minutes after that, its `status` therefore reads `TURNOVER`, and the admission's own `bed_id` is cleared."

    Design: Difficulty/resource_temporal_overlap/bed_turnover_buffer_is_half_open
    """
    stay = _single_bed_stay(api)
    waiting = _waiting_admission(api, stay.unit_id)
    discharged = fx.discharge(
        api, stay.admission_id, disposition=c.DISPOSITION_ROUTINE, at=FIRST_RELEASE_AT
    )

    assert_admission_dimensions(
        discharged, c.CLINICAL_DISCHARGED, c.AUTH_STATE_CLOSED
    )
    assert discharged["bed_id"] is None, (
        f"a discharged admission holds no bed, got bed_id {discharged['bed_id']!r}"
    )

    bed = _bed_by_id(api, stay.unit_id, stay.bed_id)
    assert bed["current_admission_id"] is None, (
        f"the released bed should hold no admission, got {bed['current_admission_id']!r}"
    )
    assert_instant_equals(bed["released_at"], FIRST_RELEASE_AT, "released_at")
    assert_instant_equals(bed["turnover_clear_at"], TURNOVER_CLEAR_AT, "turnover_clear_at")
    assert bed["status"] == c.BED_TURNOVER, (
        f"the bed should read TURNOVER during its buffer, got {bed['status']!r}"
    )

    fx.set_clock(api, ONE_MINUTE_BEFORE_CLEAR)
    validate_error(
        api.admit(waiting["id"], f.admit_payload(stay.bed_id), COORDINATOR),
        e.ERR_BED_OCCUPANCY_CONFLICT,
        409,
    )
    mid_buffer = _bed_by_id(api, stay.unit_id, stay.bed_id)
    assert mid_buffer["status"] == c.BED_TURNOVER, (
        f"one minute short of the buffer the bed still reads TURNOVER, got {mid_buffer['status']!r}"
    )


# ---------------------------------------------------------------------------
# Concurrency capacity comes only from the window containing the clock
# ---------------------------------------------------------------------------


def test_third_concurrent_start_refused_until_a_study_completes(api):
    """The allowance belongs to the covering window, and an abutting window lends none.

    PRD §2.6: "The coverage window's `assigned_study_count` is strictly below its `max_concurrent_studies`, otherwise `ERR_TECH_CAPACITY_EXCEEDED` (409)."

    Design: Difficulty/resource_temporal_overlap/shift_coverage_capacity_counts_only_the_containing_window
    """
    stay, later_window, studies = _two_abutting_windows(api)

    refused = api.start_study(studies[2], f.start_payload(stay.shift_id), TECHNOLOGIST)
    validate_error(refused, e.ERR_TECH_CAPACITY_EXCEEDED, 409)

    # The adjacent window is ACTIVE but does not contain the clock, so it cannot lend.
    borrowed = api.start_study(
        studies[2], f.start_payload(later_window["id"]), TECHNOLOGIST
    )
    validate_error(borrowed, e.ERR_NO_TECH_COVERAGE, 409)

    validate_success(api.complete_study(studies[0], TECHNOLOGIST))

    started = validate_success(
        api.start_study(studies[2], f.start_payload(stay.shift_id), TECHNOLOGIST)
    )
    assert started["acquisition_state"] == c.ACQ_ACQUIRING, (
        f"the freed slot should admit the third study, got {started['acquisition_state']!r}"
    )
    assert_ids_equal(started["shift_id"], stay.shift_id, "study shift_id")


def test_coverage_capacity_counts_only_the_window_holding_the_clock(api):
    """The unit's allowance and posture read the containing window alone.

    PRD §2.11: "Here `active_study_count` is the number of studies of the unit whose `acquisition_state` is `ACQUIRING`, and `coverage_capacity` is the sum of `max_concurrent_studies` over the unit's coverage windows whose `state` is `ACTIVE` and whose half-open window — inclusive of `starts_at`, exclusive of `ends_at` — contains the current logical clock."
    PRD §2.11: "Otherwise, if the unit's `active_study_count` is greater than zero and is greater than or equal to its `coverage_capacity`, the posture is `COVERAGE_CONSTRAINED`."

    Design: Difficulty/resource_temporal_overlap/shift_coverage_capacity_counts_only_the_containing_window
    """
    stay, later_window, studies = _two_abutting_windows(api)
    validate_error(
        api.start_study(studies[2], f.start_payload(stay.shift_id), TECHNOLOGIST),
        e.ERR_TECH_CAPACITY_EXCEEDED,
        409,
    )

    unit = validate_success(api.get_unit(stay.unit_id, COORDINATOR))
    assert unit["coverage_capacity"] == 2, (
        "only the window containing the clock contributes its allowance of 2, "
        f"got coverage_capacity {unit['coverage_capacity']!r}"
    )
    assert unit["active_study_count"] == 2, (
        f"two studies are ACQUIRING, got {unit['active_study_count']!r}"
    )
    assert unit["posture"] == c.POSTURE_COVERAGE_CONSTRAINED, (
        "an active count that has reached the capacity constrains the unit, got posture "
        f"{unit['posture']!r}"
    )

    covering = validate_success(api.get_shift(stay.shift_id, COORDINATOR))
    assert covering["assigned_study_count"] == 2, (
        f"the covering window carries both studies, got {covering['assigned_study_count']!r}"
    )
    adjacent = validate_success(api.get_shift(later_window["id"], COORDINATOR))
    assert adjacent["assigned_study_count"] == 0, (
        "the abutting window carries nothing, got "
        f"{adjacent['assigned_study_count']!r}"
    )


def test_completing_a_study_returns_its_slot_to_the_covering_window(api):
    """Completion decrements the window and the unit before the next start can proceed.

    PRD §3.5: "Completing from `ACQUIRING` closes the currently open segment and recomputes `acquired_minutes`, `closed_segment_count` and `stored_gb`, stamps `completed_at` from the clock, decrements both the window's `assigned_study_count` and the unit's `active_study_count` and re-derives the unit's `posture`, re-derives the unit's `storage_used_gb` and `storage_pressure_pct`, creates exactly one review report for the study in `PRELIM_DRAFT`, and increments the study's `version` by 1."

    Design: Difficulty/resource_temporal_overlap/shift_coverage_capacity_counts_only_the_containing_window
    """
    stay, _later_window, studies = _two_abutting_windows(api)
    validate_error(
        api.start_study(studies[2], f.start_payload(stay.shift_id), TECHNOLOGIST),
        e.ERR_TECH_CAPACITY_EXCEEDED,
        409,
    )

    completed = validate_success(api.complete_study(studies[0], TECHNOLOGIST))
    assert completed["acquisition_state"] == c.ACQ_COMPLETED, (
        f"the study should read COMPLETED, got {completed['acquisition_state']!r}"
    )
    # The segment opened and closed on the same instant, so nothing accrued.
    assert_whole_minutes(completed["acquired_minutes"], 0, "acquired_minutes")
    assert_storage_value(completed["stored_gb"], 0.00, "stored_gb")
    assert_instant_equals(completed["completed_at"], WORKING_CLOCK, "completed_at")

    covering = validate_success(api.get_shift(stay.shift_id, COORDINATOR))
    assert covering["assigned_study_count"] == 1, (
        f"the freed window should carry one study, got {covering['assigned_study_count']!r}"
    )
    unit = validate_success(api.get_unit(stay.unit_id, COORDINATOR))
    assert unit["active_study_count"] == 1, (
        f"one study remains ACQUIRING, got {unit['active_study_count']!r}"
    )
    assert_storage_value(unit["storage_used_gb"], 0.00, "storage_used_gb")
