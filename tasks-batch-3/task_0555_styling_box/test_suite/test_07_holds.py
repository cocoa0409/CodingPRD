"""Vacation holds: half-open [start, end) windows, overlap rejection, adjacency
acceptance, and date-range validation.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_client_headers,
    create_active_client, setup_client_with_hold,
)

OPS = TEST_USERS["ops_headers"]


# ------------------------------------------ Difficulty: pairwise overlap rejected
def test_overlapping_hold_rejected(api):
    """PRD §3.10: "A new hold must not overlap any existing hold for the same client;
    an overlapping window is rejected with ERR_HOLD_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/hold_windows_pairwise_overlap_rejected
    """
    ctx = setup_client_with_hold("2026-06-01T00:00:00Z", "2026-06-10T00:00:00Z")
    resp = api.create_hold(
        ctx["client_id"],
        {"start_date": "2026-06-05T00:00:00Z", "end_date": "2026-06-15T00:00:00Z"},
        headers=make_client_headers(ctx["client_id"]))
    validate_error(resp, ApiErrorId.ERR_HOLD_OVERLAP.value)


def test_overlapping_hold_not_persisted(api):
    """PRD §3.10: "A subscriber may place a vacation Hold over a date window, supplying
    a start_date (inclusive) and an end_date (exclusive) — a half-open window from
    start up to but not including end."

    Design: Difficulty/resource_temporal_overlap/hold_windows_pairwise_overlap_rejected
    """
    ctx = setup_client_with_hold("2026-06-01T00:00:00Z", "2026-06-10T00:00:00Z")
    api.create_hold(
        ctx["client_id"],
        {"start_date": "2026-06-05T00:00:00Z", "end_date": "2026-06-15T00:00:00Z"},
        headers=make_client_headers(ctx["client_id"]))
    _, meta = validate_paginated(api.list_holds(ctx["client_id"], headers=OPS))
    assert meta["total_count"] == 1, "the overlapping hold must not have been created"


# ------------------------------------------------------- Corner: date validation
def test_hold_end_not_after_start_rejected(api):
    """PRD §3.10: "The window must be non-empty, so end_date must be strictly after
    start_date; otherwise the request is rejected with ERR_INVALID_DATE_RANGE."

    Design: Corner/validations/hold_invalid_date_range_returns_422
    """
    client = create_active_client(region_code="CA")
    resp = api.create_hold(
        client["id"],
        {"start_date": "2026-06-10T00:00:00Z", "end_date": "2026-06-01T00:00:00Z"},
        headers=make_client_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE.value)


def test_adjacent_hold_window_allowed(api):
    """PRD §3.10: "A subscriber may place a vacation Hold over a date window, supplying
    a start_date (inclusive) and an end_date (exclusive) — a half-open window from
    start up to but not including end."

    Design: Corner/validations/hold_adjacent_window_allowed
    """
    ctx = setup_client_with_hold("2026-06-01T00:00:00Z", "2026-06-10T00:00:00Z")
    resp = api.create_hold(
        ctx["client_id"],
        {"start_date": "2026-06-10T00:00:00Z", "end_date": "2026-06-20T00:00:00Z"},
        headers=make_client_headers(ctx["client_id"]))
    validate_success(resp, 201)
