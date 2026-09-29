"""Contention for one individual's non-biometric process slot.

The accommodation rule is the strict opposite of the notice rule: closed intervals
inflated by a day on both ends, so touching windows collide.
"""

from test_helpers import (
    HR_ADMIN,
    ApiErrorId,
    accommodations_for_subject,
    assert_instant_equals,
    assert_is_null,
    assert_pagination,
    baseline_with_active_asset,
    create_data_subject,
    validate_error,
    validate_paginated,
    validate_success,
)


def _employee_with_a_first_ten_day_accommodation(api):
    ctx = baseline_with_active_asset(api, activation_clock=None)
    subject = create_data_subject(
        api,
        ctx["program_id"],
        ctx["jurisdiction_id"],
        "EMP-0001",
        accommodation_needed=True,
    )
    first = validate_success(
        api.create_accommodation(
            {
                "data_subject_id": subject["id"],
                "asset_id": ctx["asset_id"],
                "method": "MANUAL_TIMESHEET",
                "starts_at": "2026-08-01T00:00:00Z",
                "ends_at": "2026-08-10T00:00:00Z",
            },
            HR_ADMIN,
        ),
        expected_status=201,
    )
    ctx["subject_id"] = subject["id"]
    ctx["first_accommodation_id"] = first["id"]
    return ctx


def _request_window(api, ctx, starts_at: str):
    return api.create_accommodation(
        {
            "data_subject_id": ctx["subject_id"],
            "asset_id": ctx["asset_id"],
            "method": "MANUAL_TIMESHEET",
            "starts_at": starts_at,
            "ends_at": "2026-08-20T00:00:00Z",
        },
        HR_ADMIN,
    )


def test_windows_one_day_apart_and_exactly_touching_both_collide(api):
    """A day's gap is not enough, and the buffered touch is not enough either.

    PRD §3.7: "Manual creation enforces a window-collision rule that is
    deliberately stricter than the notice-window rule of §3.4: the requested closed
    interval from `starts_at` through `ends_at` is inflated by a twenty-four-hour
    changeover buffer on **both** ends, and if the inflated interval intersects the
    window of any other accommodation for the same `data_subject_id` whose status is
    `REQUESTED`, `PROVISIONED` or `ACTIVE`, the request is rejected with
    `ERR_ACCOMMODATION_WINDOW_CONFLICT`."

    The incumbent occupies the closed window 2026-08-01 through 2026-08-10. A
    successor starting 2026-08-10 touches that window on its inclusive end, and the
    PRD's own gloss says "windows that merely touch — or that sit within a day of
    each other — do collide". A successor starting 2026-08-11 sits exactly a day
    clear, but the request's own inflated interval reaches back to 2026-08-10 and so
    still intersects the incumbent's window: the buffer is what makes this second
    probe collide.

    Design: Difficulty/resource_temporal_overlap/accommodation_windows_are_closed_plus_24h_buffer_so_touching_windows_collide
    """
    ctx = _employee_with_a_first_ten_day_accommodation(api)

    validate_error(
        _request_window(api, ctx, "2026-08-10T00:00:00Z"), ApiErrorId.ACCOMMODATION_WINDOW_CONFLICT
    )
    validate_error(
        _request_window(api, ctx, "2026-08-11T00:00:00Z"), ApiErrorId.ACCOMMODATION_WINDOW_CONFLICT
    )

    rows = accommodations_for_subject(api, ctx["subject_id"])
    assert [row["id"] for row in rows] == [ctx["first_accommodation_id"]], (
        "a refused window creates nothing"
    )


def test_a_two_day_gap_is_admissible_and_lands_a_manual_request(api):
    """Clear of the buffer on both sides, the request is accepted.

    PRD §3.7: "The request lands in `REQUESTED` with `origin` of `MANUAL`,
    `created_from_consent_id` null, `sla_breached` false, and `sla_due_at` set to
    five days after the current logical clock — the deadline for reaching
    `PROVISIONED`."

    The clock still reads 2026-08-01, so the provisioning deadline is 2026-08-06,
    and the individual ends up holding exactly two accommodations.

    Design: Difficulty/resource_temporal_overlap/accommodation_windows_are_closed_plus_24h_buffer_so_touching_windows_collide
    """
    ctx = _employee_with_a_first_ten_day_accommodation(api)

    created = validate_success(
        _request_window(api, ctx, "2026-08-13T00:00:00Z"), expected_status=201
    )

    assert created["status"] == "REQUESTED"
    assert created["origin"] == "MANUAL"
    assert created["method"] == "MANUAL_TIMESHEET"
    assert_is_null(created["created_from_consent_id"], "created_from_consent_id on a manual request")
    assert created["sla_breached"] is False
    assert_instant_equals(created["sla_due_at"], "2026-08-06T00:00:00.000Z", "sla_due_at")

    _rows, meta = validate_paginated(
        api.list_accommodations(HR_ADMIN, {"data_subject_id": ctx["subject_id"]})
    )
    assert_pagination(meta, total_count=2, has_more=False, limit=10, offset=0)
