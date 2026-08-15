"""DeliveryJob planning, window conflicts, and dispatch guards."""
from test_helpers import (
    TEST_USERS,
    assert_delivery_job,
    create_delivery_job_payload,
    get_success_data,
    setup_quote_accepted,
    validate_error,
    validate_success,
)

PM = TEST_USERS["project_manager_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]


def test_invalid_job_window_rejected(api):
    """PRD §3.6: "supplying a delivery window — `scheduled_start` and
    `scheduled_end`, both ISO 8601 UTC, with the end strictly after the start
    or creation fails with `ERR_INVALID_JOB_WINDOW`".

    Design: Corner/validations/invalid_job_window_rejected
    """
    customer, project, layout, items, quote = setup_quote_accepted()
    res = api.create_delivery_job(
        project["id"],
        create_delivery_job_payload(
            scheduled_start="2026-08-05T12:00:00Z",
            scheduled_end="2026-08-05T08:00:00Z",
        ),
        LC,
    )
    validate_error(res, "ERR_INVALID_JOB_WINDOW", expected_status=422)


def test_delivery_window_buffer_conflict(api):
    """PRD §3.6: "the new job must not collide with another non-cancelled job
    on the same project: overlap is permitted only when the two jobs differ in
    `rigging_required` or their windows are disjoint with at least a 2-hour
    buffer between them; otherwise dispatch fails with
    `ERR_DELIVERY_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/delivery_window_buffer_conflict
    """
    customer, project, layout, items, quote = setup_quote_accepted()
    job1 = get_success_data(
        api.create_delivery_job(
            project["id"],
            create_delivery_job_payload(
                scheduled_start="2026-08-05T08:00:00Z",
                scheduled_end="2026-08-05T12:00:00Z",
            ),
            LC,
        )
    )
    job2 = get_success_data(
        api.create_delivery_job(
            project["id"],
            create_delivery_job_payload(
                scheduled_start="2026-08-05T13:00:00Z",
                scheduled_end="2026-08-05T15:00:00Z",
            ),
            LC,
        )
    )

    # 1-hour gap < required 2-hour buffer, same rigging_required.
    res = api.dispatch_delivery_job(project["id"], job2["id"], LC)
    validate_error(res, "ERR_DELIVERY_WINDOW_CONFLICT", expected_status=422)


def test_delivery_window_two_hour_buffer_accepted(api):
    """PRD §3.6: "overlap is permitted only when the two jobs differ in
    `rigging_required` or their windows are disjoint with at least a 2-hour
    buffer between them".

    Design: Difficulty/resource_temporal_overlap/delivery_window_buffer_conflict
    """
    customer, project, layout, items, quote = setup_quote_accepted()
    job1 = get_success_data(
        api.create_delivery_job(
            project["id"],
            create_delivery_job_payload(
                scheduled_start="2026-08-05T08:00:00Z",
                scheduled_end="2026-08-05T12:00:00Z",
            ),
            LC,
        )
    )
    get_success_data(api.dispatch_delivery_job(project["id"], job1["id"], LC))

    # Exactly 2-hour buffer, same rigging_required -> allowed.
    job2 = get_success_data(
        api.create_delivery_job(
            project["id"],
            create_delivery_job_payload(
                scheduled_start="2026-08-05T14:00:00Z",
                scheduled_end="2026-08-05T16:00:00Z",
            ),
            LC,
        )
    )
    dispatched = validate_success(
        api.dispatch_delivery_job(project["id"], job2["id"], LC), 200
    )
    assert_delivery_job(dispatched)
    assert dispatched["status"] == "DISPATCHED"
