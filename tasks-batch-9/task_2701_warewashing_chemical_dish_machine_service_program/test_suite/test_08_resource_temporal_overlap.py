"""
Two contended resources with opposite interval semantics: an engineer's calendar,
padded by half an hour on both sides, and a reporting window that is half-open
with no pad at all.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_REVIEW_PERIOD_OVERLAP,
    ERR_TECHNICIAN_SCHEDULE_CONFLICT,
)
from test_helpers.assertions import assert_instant_equals
from test_helpers.test_users import (
    ACCOUNT_MANAGER_HEADERS,
    AUDITOR_1_HEADERS,
    AUDITOR_2_HEADERS,
    PLATFORM_ADMIN_HEADERS,
)
from test_helpers.types import (
    BASIS_AS_CALIBRATED,
    BASIS_NAMEPLATE,
    REVIEW_DRAFT,
    REVIEW_PUBLISHED,
    TICKET_DISPATCHED,
    VISIT_SCHEDULED,
)


def _engineer_with_one_booked_hour(api):
    """
    Three INSTALLED machines, three RACK_QUALITY tickets all dispatched to the one
    AVAILABLE NW engineer, and a SCHEDULED visit already holding
    2026-08-01T10:00Z to 11:00Z against the first of them.
    """
    base = X.program_base(api)

    tickets = []
    for index in range(3):
        placement = X.installed_placement(api, base, asset_tag=f"AT-C0{index + 1}")
        ticket = X.file_ticket(api, base, placement["id"])
        tickets.append(X.dispatch_ticket(api, ticket["id"]))

    first_visit = X.book_visit(api, base, tickets[0]["id"])
    assert first_visit["visit_status"] == VISIT_SCHEDULED

    base["tickets"] = tickets
    base["first_visit"] = first_visit
    return base


def _propose_window(api, base, ticket_id, start, end):
    return api.create_service_visit(
        F.service_visit_payload(ticket_id, base["technician_id"], start, end),
        base["technician_headers"],
    )


def _visits_for(api, technician_id):
    rows, _meta = validate_paginated(
        api.list_service_visits(
            ACCOUNT_MANAGER_HEADERS, {"technician_id": technician_id, "limit": 100}
        )
    )
    return rows


def test_a_twenty_nine_minute_gap_still_collides_with_the_booked_hour(api):
    """
    11:29 to 12:29 does not intersect the 10:00-to-11:00 window at all, yet it
    starts one minute inside the half-hour pad and is refused; 11:30 to 12:30, the
    very next minute, is accepted.

    PRD §3.6: "A visit beginning exactly 30 minutes after another ends is
    therefore accepted; one beginning 29 minutes after is rejected."

    Design: Difficulty/resource_temporal_overlap/technician_visit_windows_reject_inside_the_thirty_minute_travel_buffer
    """
    base = _engineer_with_one_booked_hour(api)
    second_ticket = base["tickets"][1]["id"]

    validate_error(
        _propose_window(
            api,
            base,
            second_ticket,
            "2026-08-01T11:29:00Z",
            "2026-08-01T12:29:00Z",
        ),
        ERR_TECHNICIAN_SCHEDULE_CONFLICT,
        409,
    )

    accepted = validate_success(
        _propose_window(
            api,
            base,
            second_ticket,
            "2026-08-01T11:30:00Z",
            "2026-08-01T12:30:00Z",
        ),
        201,
    )
    assert_instant_equals(accepted["scheduled_start_at"], "2026-08-01T11:30:00Z", "scheduled_start_at")
    assert accepted["visit_status"] == VISIT_SCHEDULED
    assert accepted["technician_id"] == base["technician_id"]


def test_the_travel_pad_applies_on_the_earlier_side_and_rejections_change_nothing(api):
    """
    09:31 to 09:59 ends one minute inside the pad *before* the booked hour and is
    refused just the same, so the pad is symmetric. Two visits exist in total and
    the twice-refused engineer still carries three open jobs.

    PRD §3.6: "the booking is refused with `ERR_TECHNICIAN_SCHEDULE_CONFLICT`
    when the new window's start is earlier than the existing window's end plus 30
    minutes *and* the existing window's start is earlier than the new window's end
    plus 30 minutes."

    Design: Difficulty/resource_temporal_overlap/technician_visit_windows_reject_inside_the_thirty_minute_travel_buffer
    """
    base = _engineer_with_one_booked_hour(api)

    second = validate_success(
        _propose_window(
            api,
            base,
            base["tickets"][1]["id"],
            "2026-08-01T11:30:00Z",
            "2026-08-01T12:30:00Z",
        ),
        201,
    )

    validate_error(
        _propose_window(
            api,
            base,
            base["tickets"][2]["id"],
            "2026-08-01T09:31:00Z",
            "2026-08-01T09:59:00Z",
        ),
        ERR_TECHNICIAN_SCHEDULE_CONFLICT,
        409,
    )

    rows = _visits_for(api, base["technician_id"])
    assert len(rows) == 2
    assert {row["id"] for row in rows} == {base["first_visit"]["id"], second["id"]}

    third_ticket = get_success_data(
        api.get_service_ticket(base["tickets"][2]["id"], ACCOUNT_MANAGER_HEADERS)
    )
    assert third_ticket["status"] == TICKET_DISPATCHED
    technician = get_success_data(
        api.get_technician(base["technician_id"], PLATFORM_ADMIN_HEADERS)
    )
    assert technician["open_ticket_count"] == 3


def _august_window_published(api):
    """
    3000 racks of August telemetry, one PUBLISHED NAMEPLATE review over
    [2026-08-01, 2026-09-01) and a DRAFT AS_CALIBRATED twin over the identical
    window. No ticket is ever filed, so the kitchen's posture cannot block the
    publish.
    """
    base = X.program_base(api)
    placement = X.installed_placement(api, base, asset_tag="AT-C04")
    X.fit_dispenser(api, base, placement["id"], dose=8.00)

    X.ingest_reading_at_clock(api, placement["id"], "2026-08-05T12:00:00Z", 1000)
    X.ingest_reading_at_clock(api, placement["id"], "2026-08-20T12:00:00Z", 3000)
    X.set_clock(api, "2026-10-01T00:00:00Z")

    review_a = X.draft_review(api, base, basis=BASIS_NAMEPLATE)
    twin = X.draft_review(api, base, basis=BASIS_AS_CALIBRATED)
    assert twin["status"] == REVIEW_DRAFT
    assert twin["period_start"] == review_a["period_start"]
    assert twin["period_end"] == review_a["period_end"]

    published = X.publish_review(api, review_a["id"])
    assert published["status"] == REVIEW_PUBLISHED

    base.update(
        {
            "placement_id": placement["id"],
            "review_a_id": review_a["id"],
            "twin_id": twin["id"],
        }
    )
    return base


def _draft_window(api, base, period_start, period_end):
    return api.create_usage_variance_review(
        F.usage_variance_review_payload(
            base["site_id"],
            base["detergent_id"],
            period_start=period_start,
            period_end=period_end,
            basis=BASIS_NAMEPLATE,
        ),
        AUDITOR_1_HEADERS,
    )


def test_a_window_beginning_at_the_shared_instant_is_accepted(api):
    """
    September starts at the exact instant August's window ends. Because the window
    is half-open and carries no buffer, that instant belongs only to September and
    the second review is created.

    PRD §3.7: "That overlap test carries **no** buffer and treats windows as
    half-open, so a window beginning exactly at another's `period_end` is
    accepted."

    Design: Difficulty/resource_temporal_overlap/review_windows_are_half_open_with_no_buffer_at_the_shared_boundary
    """
    base = _august_window_published(api)

    review_b = validate_success(
        _draft_window(api, base, "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"), 201
    )
    assert_instant_equals(review_b["period_start"], "2026-09-01T00:00:00Z", "period_start")
    assert review_b["status"] == REVIEW_DRAFT
    assert review_b["site_id"] == base["site_id"]
    assert review_b["product_id"] == base["detergent_id"]


def test_a_single_second_of_intersection_is_refused_and_leaves_no_row(api):
    """
    Backing the window up by one second to 2026-08-31T23:59:59Z makes it overlap
    the published August review, and that one second is enough; no fourth review
    row is created. Two DRAFTs over the identical window never collided, because
    only publication claims a window.

    PRD §3.7: "Drafts never block anything: two drafts may cover the identical
    window, which is precisely how the `NAMEPLATE` and `AS_CALIBRATED` bases are
    compared side by side. Publication is what claims a window, so the same
    overlap test runs again at publish time."

    Design: Difficulty/resource_temporal_overlap/review_windows_are_half_open_with_no_buffer_at_the_shared_boundary
    """
    base = _august_window_published(api)

    review_b = validate_success(
        _draft_window(api, base, "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z"), 201
    )

    validate_error(
        _draft_window(api, base, "2026-08-31T23:59:59Z", "2026-09-30T00:00:00Z"),
        ERR_REVIEW_PERIOD_OVERLAP,
        409,
    )

    rows, _meta = validate_paginated(
        api.list_usage_variance_reviews(
            AUDITOR_1_HEADERS, {"site_id": base["site_id"], "limit": 100}
        )
    )
    assert len(rows) == 3
    assert {row["id"] for row in rows} == {
        base["review_a_id"],
        base["twin_id"],
        review_b["id"],
    }

    # The same test re-runs at publish time, so the DRAFT twin can no longer be
    # published against the now-claimed August window.
    validate_error(
        api.publish_usage_variance_review(base["twin_id"], AUDITOR_2_HEADERS),
        ERR_REVIEW_PERIOD_OVERLAP,
        409,
    )
    twin = get_success_data(
        api.get_usage_variance_review(base["twin_id"], AUDITOR_1_HEADERS)
    )
    assert twin["status"] == REVIEW_DRAFT
