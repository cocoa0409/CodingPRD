"""Two temporal resources whose separation rules differ, deliberately.

Transfer-agreement date windows must be kept a clear calendar day apart, so merely
adjacent windows are refused; coverage blocks are half-open intervals, so blocks that
touch at an instant are perfectly legal.  The same file therefore pins one rule that is
stricter than non-overlap and one that is looser.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_hours_equal
from test_helpers.factories import (
    make_physician_shift_payload,
    make_transfer_agreement_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    OFFICER,
    create_physician_shift,
    create_transfer_agreement,
    open_facility,
)

WORKING_INSTANT = "2026-08-01T08:00:00Z"
OVERLAP_FACILITY = {
    "observation_bed_count": 2,
    "imaging_scope": ["XRAY", "CT"],
    "lab_scope": ["CBC", "TROPONIN"],
    "max_concurrent_physicians": 2,
}
TRINITY = "Trinity Regional Hospital"
SABINE = "Sabine County Hospital"
SHIFT_DAY = "2026-08-03"


def _facility_with_an_august_cardiac_agreement():
    """A live Trinity CARDIAC agreement covering the whole of August."""
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=OVERLAP_FACILITY)
    current = create_transfer_agreement(
        context["facility_id"],
        ADMIN,
        destination_hospital_name=TRINITY,
        service_line="CARDIAC",
        capability_tier=3,
        accepts_unstable=True,
        effective_start_date="2026-08-01",
        effective_end_date="2026-08-31",
    )
    context.update({"current_agreement": current, "current_agreement_id": current["id"]})
    return context


def _trinity_cardiac_window(start_date, end_date):
    return make_transfer_agreement_payload(
        destination_hospital_name=TRINITY,
        service_line="CARDIAC",
        capability_tier=3,
        accepts_unstable=True,
        effective_start_date=start_date,
        effective_end_date=end_date,
    )


def test_an_adjacent_agreement_window_is_refused_and_one_clear_day_is_enough():
    """September the first touches August the thirty-first; September the second does not.

    PRD 3.5: "a new agreement's inclusive date window must be separated from it by at
    least one clear calendar day in whichever direction the new window sits: either the new
    `effective_start_date` falls at least two days after the existing `effective_end_date`,
    or the new `effective_end_date` plus two days falls on or before the existing
    `effective_start_date`. Windows that overlap, windows that touch at a shared endpoint,
    and windows that are merely adjacent with no clear day between them are all rejected
    with `ERR_AGREEMENT_WINDOW_CONFLICT`."  A window opening on 2026-09-02 leaves
    2026-09-01 entirely free, which is exactly the one clear day the rule demands.

    Design: Difficulty/resource_temporal_overlap/transfer_agreement_windows_require_one_clear_calendar_day_so_adjacent_is_rejected
    """
    context = _facility_with_an_august_cardiac_agreement()
    facility_id = context["facility_id"]

    assert context["current_agreement"]["status"] == "ACTIVE"

    validate_error(
        api_client.create_transfer_agreement(
            facility_id, _trinity_cardiac_window("2026-09-01", "2026-09-30"), ADMIN
        ),
        ApiErrorId.ERR_AGREEMENT_WINDOW_CONFLICT.value,
    )

    accepted = validate_success(
        api_client.create_transfer_agreement(
            facility_id, _trinity_cardiac_window("2026-09-02", "2026-09-30"), ADMIN
        ),
        expected_status=201,
    )

    assert accepted["status"] == "PENDING"
    assert accepted["effective_start_date"] == "2026-09-02"

    agreements, meta = validate_paginated(
        api_client.list_transfer_agreements(facility_id, OFFICER)
    )
    assert meta["total_count"] == 2
    assert sorted(row["status"] for row in agreements) == ["ACTIVE", "PENDING"]


def test_the_window_conflict_is_scoped_to_one_hospital_and_one_service_line():
    """The very window that conflicts for Trinity is free for a different hospital.

    PRD 3.5 draws the resource boundary itself: "Agreements for the same facility, the same
    `destination_hospital_name` and the same `service_line` must be kept genuinely apart in
    time, and the separation rule is stricter than mere non-overlap."  And: "Agreements for
    a different hospital or a different service line are not compared at all."  PRD 3.5
    also fixes what the accepted row's status must read from the clock: "`PENDING` while
    the clock date is before `effective_start_date`, `ACTIVE` while the clock date falls
    within the window inclusive of both endpoints, and `EXPIRED` once the clock date has
    passed `effective_end_date`."

    Design: Difficulty/resource_temporal_overlap/transfer_agreement_windows_require_one_clear_calendar_day_so_adjacent_is_rejected
    """
    context = _facility_with_an_august_cardiac_agreement()
    facility_id = context["facility_id"]

    validate_error(
        api_client.create_transfer_agreement(
            facility_id, _trinity_cardiac_window("2026-09-01", "2026-09-30"), ADMIN
        ),
        ApiErrorId.ERR_AGREEMENT_WINDOW_CONFLICT.value,
    )

    other_hospital = validate_success(
        api_client.create_transfer_agreement(
            facility_id,
            make_transfer_agreement_payload(
                destination_hospital_name=SABINE,
                service_line="CARDIAC",
                capability_tier=3,
                accepts_unstable=True,
                effective_start_date="2026-09-01",
                effective_end_date="2026-09-30",
            ),
            ADMIN,
        ),
        expected_status=201,
    )
    other_service_line = validate_success(
        api_client.create_transfer_agreement(
            facility_id,
            make_transfer_agreement_payload(
                destination_hospital_name=TRINITY,
                service_line="GENERAL_MEDICAL",
                capability_tier=1,
                accepts_unstable=False,
                effective_start_date="2026-09-01",
                effective_end_date="2026-09-30",
            ),
            ADMIN,
        ),
        expected_status=201,
    )

    assert other_hospital["destination_hospital_name"] == SABINE
    assert other_hospital["status"] == "PENDING"
    assert other_service_line["service_line"] == "GENERAL_MEDICAL"
    assert other_service_line["status"] == "PENDING"

    _agreements, meta = validate_paginated(
        api_client.list_transfer_agreements(facility_id, OFFICER)
    )
    assert meta["total_count"] == 3


def _facility_with_a_day_shift_for_doctor_a():
    """One board-certified physician block from 08:00 to 16:00, cap of two."""
    context = open_facility(clock=WORKING_INSTANT, facility_overrides=OVERLAP_FACILITY)
    base = create_physician_shift(
        context["facility_id"],
        ADMIN,
        clinician_user_id="doc-a",
        role_type="PHYSICIAN",
        board_certified=True,
        start_utc=f"{SHIFT_DAY}T08:00:00Z",
        end_utc=f"{SHIFT_DAY}T16:00:00Z",
    )
    context.update({"base_shift": base, "base_shift_id": base["id"]})
    return context


def test_a_block_starting_where_another_ends_is_free_but_a_third_overlap_breaks_the_cap():
    """Touching intervals do not intersect; three simultaneous physicians do.

    PRD 3.4: "no clinician may be double-booked: a new block may not overlap another block
    of the same `clinician_user_id` at the same facility under half-open interval
    semantics, which means a block starting at exactly the instant another one ends is
    accepted, while any genuine intersection is rejected with
    `ERR_CLINICIAN_DOUBLE_BOOKED`."  The aggregate rule is separate: "counting the new
    block itself, the number of `PHYSICIAN` blocks that overlap any single instant of the
    new block's half-open interval may not exceed `max_concurrent_physicians`, and a breach
    is `ERR_COVERAGE_CAPACITY_EXCEEDED`."  Durations follow PRD 3.4's rule that a block's
    "`duration_hours` is the elapsed time from `start_utc` to `end_utc` expressed in hours
    and rounded half up to two decimals."

    Design: Difficulty/resource_temporal_overlap/physician_shifts_use_half_open_intervals_so_touching_is_free_but_third_overlap_breaks_the_cap
    """
    context = _facility_with_a_day_shift_for_doctor_a()
    facility_id = context["facility_id"]

    touching = create_physician_shift(
        facility_id,
        ADMIN,
        clinician_user_id="doc-a",
        role_type="PHYSICIAN",
        board_certified=True,
        start_utc=f"{SHIFT_DAY}T16:00:00Z",
        end_utc=f"{SHIFT_DAY}T20:00:00Z",
    )
    assert_hours_equal(touching["duration_hours"], "4.00", "touching block duration")

    second_physician = create_physician_shift(
        facility_id,
        ADMIN,
        clinician_user_id="doc-b",
        role_type="PHYSICIAN",
        board_certified=False,
        start_utc=f"{SHIFT_DAY}T12:00:00Z",
        end_utc=f"{SHIFT_DAY}T18:00:00Z",
    )
    assert_hours_equal(
        second_physician["duration_hours"], "6.00", "second physician duration"
    )

    validate_error(
        api_client.create_physician_shift(
            facility_id,
            make_physician_shift_payload(
                clinician_user_id="doc-c",
                role_type="PHYSICIAN",
                board_certified=True,
                start_utc=f"{SHIFT_DAY}T10:00:00Z",
                end_utc=f"{SHIFT_DAY}T14:00:00Z",
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_COVERAGE_CAPACITY_EXCEEDED.value,
    )

    _shifts, meta = validate_paginated(
        api_client.list_physician_shifts(
            facility_id, OFFICER, params={"role_type": "PHYSICIAN"}
        )
    )
    assert meta["total_count"] == 3


def test_an_advanced_practice_block_escapes_the_cap_and_double_booking_outranks_it():
    """The cap counts physicians only, and the per-clinician rule is checked first.

    PRD 3.4: "Only `PHYSICIAN` blocks matter for compliance:
    `ADVANCED_PRACTICE_PROVIDER` blocks are excluded from both coverage totals and from the
    concurrency cap, even though they are perfectly legitimate rows to record."  When one
    request breaks both temporal rules at once, PRD 2.6 decides which is reported — "the
    checks are evaluated in the order below and the **first** failure is the one reported"
    — and the double-booking check sits ahead of the cap: "21. A new coverage block must not
    overlap another block of the same `clinician_user_id` at the same facility, else
    `ERR_CLINICIAN_DOUBLE_BOOKED` (409)."

    Design: Difficulty/resource_temporal_overlap/physician_shifts_use_half_open_intervals_so_touching_is_free_but_third_overlap_breaks_the_cap
    """
    context = _facility_with_a_day_shift_for_doctor_a()
    facility_id = context["facility_id"]

    create_physician_shift(
        facility_id,
        ADMIN,
        clinician_user_id="doc-a",
        role_type="PHYSICIAN",
        board_certified=True,
        start_utc=f"{SHIFT_DAY}T16:00:00Z",
        end_utc=f"{SHIFT_DAY}T20:00:00Z",
    )
    create_physician_shift(
        facility_id,
        ADMIN,
        clinician_user_id="doc-b",
        role_type="PHYSICIAN",
        board_certified=False,
        start_utc=f"{SHIFT_DAY}T12:00:00Z",
        end_utc=f"{SHIFT_DAY}T18:00:00Z",
    )

    advanced_practice = create_physician_shift(
        facility_id,
        ADMIN,
        clinician_user_id="doc-c",
        role_type="ADVANCED_PRACTICE_PROVIDER",
        board_certified=False,
        start_utc=f"{SHIFT_DAY}T10:00:00Z",
        end_utc=f"{SHIFT_DAY}T14:00:00Z",
    )
    assert advanced_practice["role_type"] == "ADVANCED_PRACTICE_PROVIDER"
    assert_hours_equal(advanced_practice["duration_hours"], "4.00", "APP duration")

    reported = validate_error(
        api_client.create_physician_shift(
            facility_id,
            make_physician_shift_payload(
                clinician_user_id="doc-a",
                role_type="PHYSICIAN",
                board_certified=True,
                start_utc=f"{SHIFT_DAY}T15:00:00Z",
                end_utc=f"{SHIFT_DAY}T17:00:00Z",
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_CLINICIAN_DOUBLE_BOOKED.value,
    )
    assert reported["error_id"] != ApiErrorId.ERR_COVERAGE_CAPACITY_EXCEEDED.value

    _physicians, physician_meta = validate_paginated(
        api_client.list_physician_shifts(
            facility_id, OFFICER, params={"role_type": "PHYSICIAN"}
        )
    )
    _providers, provider_meta = validate_paginated(
        api_client.list_physician_shifts(
            facility_id, OFFICER, params={"role_type": "ADVANCED_PRACTICE_PROVIDER"}
        )
    )
    assert physician_meta["total_count"] == 3
    assert provider_meta["total_count"] == 1
