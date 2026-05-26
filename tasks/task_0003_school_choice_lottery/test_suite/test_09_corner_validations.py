"""Corner-coverage tests for validation rejections (PRD §3.2, §3.4) and the
business-error catalogue (PRD §3.1, §5).
"""
from test_helpers import (
    set_clock,
    create_district,
    archive_district,
    create_school,
    create_window,
    open_window,
    register_family,
    create_student,
    create_application,
    api_client,
    TEST_USERS,
    make_guardian_headers,
    validate_error,
    validate_error_is_one_of,
    ApiErrorId,
)
from test_helpers.factories import (
    create_school_payload,
    create_application_payload,
    create_district_payload,
)


# =====================================================================
# Corner / validations — close before closes_at → ERR_WINDOW_TIMING
# =====================================================================

def test_close_window_before_closes_at_returns_window_timing(api):
    """PRD §3.2: "Closing the window transitions it from `OPEN` to `CLOSED`.
    Closure is only permitted once the system clock has reached or passed
    `closes_at`; an early-close attempt is rejected with `ERR_INVALID_STATE`."

    Note: PRD §3.2 prose names ERR_INVALID_STATE for early-close, while
    PRD §2.6 also lists ERR_WINDOW_TIMING in the priority order for
    enrollment-window timing rules. We use validate_error_is_one_of to
    admit both faithful PRD readings.

    Design: Corner/validations/error_window_timing_close_before_close_instant
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DCT", name="Ct", poverty_index_pct=0.00)
    window = create_window(district["id"], cycle_label="2026-27-CT")
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    # Clock is well before closes_at=2026-02-01; close attempt should fail.
    res = api.close_window(window["id"], TEST_USERS["district_admin_headers"])
    actual = validate_error_is_one_of(
        res,
        [ApiErrorId.ERR_INVALID_STATE.value, ApiErrorId.ERR_WINDOW_TIMING.value],
    )
    assert actual in (
        ApiErrorId.ERR_INVALID_STATE.value, ApiErrorId.ERR_WINDOW_TIMING.value
    ), f"unexpected error_id: {actual!r}"


# =====================================================================
# Corner / validations — district ARCHIVED prevents school creation
# =====================================================================

def test_create_school_on_archived_district_returns_district_archived(api):
    """PRD §3.1: "References to an `ARCHIVED` district from any subsequent
    create-application, family-register, school-create, or student-create
    operation are rejected with `ERR_DISTRICT_ARCHIVED`."

    Design: Corner/validations/error_district_archived_prevents_school_creation
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DAR", name="Ar", poverty_index_pct=0.00)
    archive_district(district["id"])
    payload = create_school_payload(district["id"], code="SAR", name="Ars",
                                    school_type="MAGNET", grade_min=0,
                                    grade_max=5, total_seats=1)
    res = api.create_school(payload, TEST_USERS["district_admin_headers"])
    err = validate_error(res, ApiErrorId.ERR_DISTRICT_ARCHIVED.value)
    assert err["error_id"] == ApiErrorId.ERR_DISTRICT_ARCHIVED.value


# =====================================================================
# Corner / validations — duplicate choice_rank within window → ERR_DUPLICATE_CHOICE
# =====================================================================

def test_duplicate_choice_rank_within_window_returns_duplicate_choice(api):
    """PRD §3.4: "A student may submit at most five applications per
    window, and within a given window each of that student's applications
    must carry a distinct `choice_rank`; either a duplicate rank for the
    same student in the same window, a rank outside 1-to-5, or a sixth
    application for the same student in the same window is rejected with
    `ERR_DUPLICATE_CHOICE`."

    Design: Corner/validations/error_duplicate_choice_rank_in_window
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DDC", name="Dc", poverty_index_pct=0.00)
    schoolA = create_school(district["id"], code="SDC1", name="Dc1",
                            school_type="MAGNET", grade_min=0, grade_max=12,
                            total_seats=3)
    schoolB = create_school(district["id"], code="SDC2", name="Dc2",
                            school_type="MAGNET", grade_min=0, grade_max=12,
                            total_seats=3)
    window = create_window(district["id"], cycle_label="2026-27-DC")
    family = register_family(district["id"], guardian_email="dc@x.com",
                             residence_zone_code="ZDC", poverty_flag=False)
    student = create_student(family["id"], grade_for_cycle=5)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    # First application at choice_rank=1 — OK.
    create_application(family["id"], window["id"], student["id"],
                       schoolA["id"], choice_rank=1)
    # Second application for the SAME (student, window) at duplicate rank=1 — reject.
    payload = create_application_payload(window["id"], student["id"],
                                         schoolB["id"], choice_rank=1)
    res = api.create_application(payload, make_guardian_headers(family["id"]))
    err = validate_error(res, ApiErrorId.ERR_DUPLICATE_CHOICE.value)
    assert err["error_id"] == ApiErrorId.ERR_DUPLICATE_CHOICE.value


# =====================================================================
# Corner / validations — grade outside [grade_min, grade_max] →
# ERR_GRADE_OUT_OF_RANGE
# =====================================================================

def test_student_grade_out_of_range_for_school_returns_grade_out_of_range(api):
    """PRD §3.4: "The student's `grade_for_cycle` must be within the
    school's `[grade_min, grade_max]` band inclusive on both ends; an
    out-of-band grade is rejected with `ERR_GRADE_OUT_OF_RANGE`."

    Design: Corner/validations/error_grade_out_of_range_for_student
    """
    set_clock("2026-01-01T00:00:00Z")
    district = create_district(code="DGE", name="Ge", poverty_index_pct=0.00)
    school = create_school(district["id"], code="SGE", name="Ges",
                           school_type="MAGNET", grade_min=0, grade_max=5,
                           total_seats=3)
    window = create_window(district["id"], cycle_label="2026-27-GE")
    family = register_family(district["id"], guardian_email="ge@x.com",
                             residence_zone_code="ZGE", poverty_flag=False)
    student = create_student(family["id"], grade_for_cycle=12)
    set_clock("2026-01-03T00:00:00Z")
    open_window(window["id"])
    payload = create_application_payload(window["id"], student["id"],
                                         school["id"], choice_rank=1)
    res = api.create_application(payload, make_guardian_headers(family["id"]))
    err = validate_error(res, ApiErrorId.ERR_GRADE_OUT_OF_RANGE.value)
    assert err["error_id"] == ApiErrorId.ERR_GRADE_OUT_OF_RANGE.value


# =====================================================================
# Corner / errors — district poverty_index_pct out of [0,100] range
# =====================================================================

def test_create_district_with_out_of_range_poverty_pct_rejected(api):
    """PRD §3.1: "the district's federal `poverty_index_pct` — the
    catchment-level federal poverty rate, expressed as a percent between 0
    and 100 inclusive with two decimal places."
    PRD §3.2: "rejected with `ERR_DISTRICT_DATA_INVALID` if the district's
    `poverty_index_pct` is outside the 0-to-100 range — a data-sanity gate
    intended to catch corrupted district configurations before they distort
    lottery weighting."

    PRD §3.1 names the [0,100] range but does not commit the exact error_id
    that a POST /lottery/districts with poverty_index_pct=150 must return.
    PRD §3.2 commits ERR_DISTRICT_DATA_INVALID only for window-open time.
    A faithful implementation may reject early with the schema-level
    ERR_INVALID_REQUEST OR with the business-rule ERR_DISTRICT_DATA_INVALID
    — both are PRD-consistent. We use validate_error_is_one_of accordingly.

    Design: Corner/errors/error_district_data_invalid_on_poverty_out_of_range
    """
    set_clock("2026-01-01T00:00:00Z")
    payload = create_district_payload(code="DBAD", name="Bad",
                                      poverty_index_pct=150.00)
    res = api.create_district(payload, TEST_USERS["district_admin_headers"])
    actual = validate_error_is_one_of(
        res,
        [
            ApiErrorId.ERR_INVALID_REQUEST.value,
            ApiErrorId.ERR_DISTRICT_DATA_INVALID.value,
        ],
    )
    assert actual in (
        ApiErrorId.ERR_INVALID_REQUEST.value,
        ApiErrorId.ERR_DISTRICT_DATA_INVALID.value,
    ), f"unexpected error_id: {actual!r}"
