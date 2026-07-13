"""Sort-line throughput computation and downtime interval rules."""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
from test_helpers.fixtures import (
    create_municipality, create_sort_line, create_load, audit_load, close_load,
    create_downtime_event,
)

SORT = TEST_USERS["sort_manager_headers"]


def test_throughput_computed_from_processed_and_downtime(api):
    """PRD §2.8: "From these, `throughput_tph` is the processed tonnage divided by
    the line's uptime in hours, where uptime hours equals the line's
    `scheduled_shift_minutes` minus `total_downtime_minutes`, all divided by 60; the
    quotient is rounded to two decimal places."
    PRD §2.8: "`total_processed_tons` is the sum of `net_tons` over the inbound
    loads assigned to that line that have reached `CLOSED`."

    Design: Corner/calculations/corner_sortline_throughput_computed_read
    """
    muni = create_municipality(api)
    line = create_sort_line(api, scheduled_shift_minutes=480)
    create_downtime_event(api, line["id"], "2026-03-01T08:00:00Z",
                          "2026-03-01T10:00:00Z", "jam")
    load = create_load(api, muni["id"], line["id"], gross_tons=22, tare_tons=0)
    audit_load(api, load["id"])
    close_load(api, load["id"], residual_tons=0)
    sl = validate_success(api.get_sort_line(line["id"], SORT))
    assert sl["total_processed_tons"] == 22
    assert sl["total_downtime_minutes"] == 120
    assert sl["throughput_tph"] == 3.67


def test_throughput_zero_when_uptime_nonpositive(api):
    """PRD §2.8: "When uptime hours is zero or negative, `throughput_tph` is
    reported as 0 rather than computed."

    Design: Corner/calculations/corner_sortline_throughput_zero_uptime_boundary
    """
    muni = create_municipality(api)
    line = create_sort_line(api, scheduled_shift_minutes=480)
    create_downtime_event(api, line["id"], "2026-03-01T08:00:00Z",
                          "2026-03-01T16:00:00Z", "outage")
    load = create_load(api, muni["id"], line["id"], gross_tons=22, tare_tons=0)
    audit_load(api, load["id"])
    close_load(api, load["id"], residual_tons=0)
    sl = validate_success(api.get_sort_line(line["id"], SORT))
    assert sl["total_downtime_minutes"] == 480
    assert sl["throughput_tph"] == 0


def test_downtime_invalid_interval_rejected(api):
    """PRD §3.3: "The window must be well-formed — `end_at` strictly after
    `start_at`, else `ERR_INVALID_INTERVAL`."

    Design: Corner/validations/corner_invalid_interval_downtime_rejected
    """
    line = create_sort_line(api)
    resp = api.create_downtime_event(
        {"sort_line_id": line["id"], "start_at": "2026-03-01T10:00:00Z",
         "end_at": "2026-03-01T09:00:00Z", "reason": "bad"}, SORT)
    validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL.value)


def test_downtime_adjacent_interval_conflicts(api):
    """PRD §3.3: "A downtime window may not conflict with any existing downtime
    event on the same line: these are treated as closed intervals, so even touching
    endpoints (adjacency) count as a conflict, and any such collision is rejected
    with `ERR_DOWNTIME_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/downtime_closed_interval_adjacency_conflict
    """
    line = create_sort_line(api)
    create_downtime_event(api, line["id"], "2026-03-01T08:00:00Z",
                          "2026-03-01T10:00:00Z", "jam")
    resp = api.create_downtime_event(
        {"sort_line_id": line["id"], "start_at": "2026-03-01T10:00:00Z",
         "end_at": "2026-03-01T11:00:00Z", "reason": "maintenance"}, SORT)
    validate_error(resp, ApiErrorId.ERR_DOWNTIME_OVERLAP.value)


def test_downtime_non_touching_interval_accepted(api):
    """PRD §3.3: "A downtime window may not conflict with any existing downtime
    event on the same line: these are treated as closed intervals, so even touching
    endpoints (adjacency) count as a conflict, and any such collision is rejected
    with `ERR_DOWNTIME_OVERLAP`."
    PRD §3.3: "the event's `downtime_minutes` is computed as the number of whole
    minutes between `start_at` and `end_at`, taking the floor of any fractional
    minute".

    Design: Difficulty/resource_temporal_overlap/downtime_closed_interval_adjacency_conflict
    """
    line = create_sort_line(api)
    create_downtime_event(api, line["id"], "2026-03-01T08:00:00Z",
                          "2026-03-01T10:00:00Z", "jam")
    resp = api.create_downtime_event(
        {"sort_line_id": line["id"], "start_at": "2026-03-01T10:01:00Z",
         "end_at": "2026-03-01T11:00:00Z", "reason": "maintenance"}, SORT)
    ev = validate_success(resp, 201)
    assert ev["downtime_minutes"] == 59
