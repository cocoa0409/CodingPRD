"""Absence intake rules: same-teacher date overlap with adjacency, date-sanity
rejections, and the list endpoint's filter + pagination envelope."""
from test_helpers import (
    ApiErrorId,
    basic_world,
    create_absence_payload,
    make_teacher_headers,
    report_absence,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_absence_overlap_same_teacher_adjacency_allowed(api):
    """PRD 3.3: "One teacher may not hold two non-cancelled absences whose
    date ranges intersect — adjacent ranges are permitted — and a collision
    fails with `ERR_ABSENCE_DATE_OVERLAP`."

    Design: Corner/validations/absence_overlap_same_teacher_adjacency_allowed
    """
    ctx = basic_world()
    teacher = ctx["teacher"]
    headers = make_teacher_headers(teacher["id"])
    report_absence(teacher, start_date="2026-08-03", end_date="2026-08-05")

    overlapping = create_absence_payload(
        teacher["id"],
        start_date="2026-08-05",
        end_date="2026-08-07",
        absence_type="PERSONAL",
    )
    res = api.create_absence(overlapping, headers)
    validate_error(res, ApiErrorId.ERR_ABSENCE_DATE_OVERLAP, expected_status=409)

    adjacent = create_absence_payload(
        teacher["id"],
        start_date="2026-08-06",
        end_date="2026-08-07",
        absence_type="PERSONAL",
    )
    created = validate_success(api.create_absence(adjacent, headers), 201)
    assert created["total_days"] == 2
    assert created["fill_status"] == "REPORTED"


def test_invalid_date_range_variants(api):
    """PRD 3.3: "`end_date` before `start_date`, a `start_date` before the
    current clock date, or a range containing not a single weekday all fail
    with `ERR_INVALID_DATE_RANGE`."

    Design: Corner/validations/invalid_date_range_variants
    """
    ctx = basic_world()
    teacher = ctx["teacher"]
    headers = make_teacher_headers(teacher["id"])

    backwards = create_absence_payload(
        teacher["id"], start_date="2026-08-05", end_date="2026-08-03"
    )
    res = api.create_absence(backwards, headers)
    validate_error(res, ApiErrorId.ERR_INVALID_DATE_RANGE, expected_status=422)

    weekend_only = create_absence_payload(
        teacher["id"], start_date="2026-08-01", end_date="2026-08-02"
    )
    res = api.create_absence(weekend_only, headers)
    validate_error(res, ApiErrorId.ERR_INVALID_DATE_RANGE, expected_status=422)


def test_absence_list_pagination_and_filters(api, district_admin_headers):
    """PRD 2.3: "The `limit` parameter sets the maximum number of items
    returned; when omitted it defaults to 10, and it must lie between a
    minimum of 1 and a maximum of 100. The `offset` parameter sets the number
    of items skipped and defaults to 0."
    PRD 2.3: "The `meta` object of every list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."
    PRD 3.3: "Absences are listable with `school_id`, `staff_member_id`,
    `fill_status`, `from_date`, and `to_date` filters."

    Design: Corner/endpoints/absence_list_pagination_and_filters
    """
    ctx = basic_world()
    teacher = ctx["teacher"]
    report_absence(teacher, start_date="2026-08-03", end_date="2026-08-03")
    report_absence(teacher, start_date="2026-08-04", end_date="2026-08-04")
    third = report_absence(teacher, start_date="2026-08-05", end_date="2026-08-05")
    validate_success(
        api.cancel_absence(third["id"], make_teacher_headers(teacher["id"])), 200
    )

    data, meta = validate_paginated(
        api.list_absences(
            district_admin_headers,
            params={"staff_member_id": teacher["id"], "limit": 2, "offset": 0},
        )
    )
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    data, meta = validate_paginated(
        api.list_absences(
            district_admin_headers,
            params={"staff_member_id": teacher["id"], "limit": 2, "offset": 2},
        )
    )
    assert len(data) == 1
    assert meta["has_more"] is False

    data, meta = validate_paginated(
        api.list_absences(
            district_admin_headers,
            params={"staff_member_id": teacher["id"], "fill_status": "CANCELLED"},
        )
    )
    assert meta["total_count"] == 1
    assert data[0]["id"] == third["id"]
