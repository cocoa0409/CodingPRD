"""Shipment carrier-window overlap geometry (PRD §3.8).

GROUND windows are half-open [start, end); EXPRESS windows are closed [start, end]
with an additional 24-hour buffer between windows on the same step.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_case_active_step1_manufactured,
    create_shipment_payload,
    api_client, TEST_USERS,
)

MFG = TEST_USERS["manufacturing_headers"]


def _book(api, step_id, ws, we, carrier="GROUND"):
    return api.create_shipment(
        create_shipment_payload(step_id, carrier_code=carrier, window_start=ws, window_end=we),
        MFG,
    )


# ── GROUND half-open overlap ──
def test_ground_overlapping_windows_rejected(api):
    """PRD §3.8: "For `GROUND` shipments, the windows booked for the same step
    are treated as half-open intervals from `window_start` inclusive to
    `window_end` exclusive; two such windows for the same step must not overlap,
    though touching endpoints (one window's end equal to another's start) are
    allowed. An overlap is rejected with `ERR_GROUND_WINDOW_OVERLAP` (HTTP 409)."

    A second GROUND window [05-03, 05-05) starting before the first window's end
    05-04 overlaps it and is rejected.

    Design: Difficulty/resource_temporal_overlap/ground_window_halfopen_overlap_rejected
    """
    ctx = setup_case_active_step1_manufactured(proposed_step_count=10)
    s1 = ctx["steps"][0]
    validate_success(_book(api, s1["id"], "2026-05-02T00:00:00Z", "2026-05-04T00:00:00Z"), 201)
    res = _book(api, s1["id"], "2026-05-03T00:00:00Z", "2026-05-05T00:00:00Z")
    validate_error(res, "ERR_GROUND_WINDOW_OVERLAP", expected_status=409)


def test_ground_touching_windows_allowed(api):
    """PRD §3.8: "two such windows for the same step must not overlap, though
    touching endpoints (one window's end equal to another's start) are allowed."

    A second GROUND window [05-04, 05-06) starting exactly at the first window's
    exclusive end 05-04 touches but does not overlap, so it books successfully
    (201, BOOKED) - the half-open boundary does not collide.

    Design: Difficulty/resource_temporal_overlap/ground_window_halfopen_overlap_rejected
    """
    ctx = setup_case_active_step1_manufactured(proposed_step_count=10)
    s1 = ctx["steps"][0]
    validate_success(_book(api, s1["id"], "2026-05-02T00:00:00Z", "2026-05-04T00:00:00Z"), 201)
    second = validate_success(
        _book(api, s1["id"], "2026-05-04T00:00:00Z", "2026-05-06T00:00:00Z"), 201
    )
    assert second["status"] == "BOOKED", second["status"]


# ── EXPRESS closed-interval + 24h buffer ──
def test_express_window_within_24h_buffer_rejected(api):
    """PRD §3.8: "additionally, an express buffer of 24 hours must separate
    express windows on the same step - a new express window whose `window_start`
    is less than 24 hours after a prior express window's `window_end` is
    rejected. Either condition yields `ERR_EXPRESS_WINDOW_OVERLAP` (HTTP 409)."

    A second EXPRESS window starting only 12h after the first window's end
    (05-02T06:00 -> 05-02T18:00) violates the 24h buffer even though the raw
    intervals do not overlap.

    Design: Difficulty/resource_temporal_overlap/express_window_buffer_within_24h_rejected
    """
    ctx = setup_case_active_step1_manufactured(proposed_step_count=10)
    s1 = ctx["steps"][0]
    validate_success(
        _book(api, s1["id"], "2026-05-02T00:00:00Z", "2026-05-02T06:00:00Z", carrier="EXPRESS"),
        201,
    )
    res = _book(api, s1["id"], "2026-05-02T18:00:00Z", "2026-05-03T00:00:00Z", carrier="EXPRESS")
    validate_error(res, "ERR_EXPRESS_WINDOW_OVERLAP", expected_status=409)


def test_express_touching_windows_collide(api):
    """PRD §3.8: "For `EXPRESS` shipments, the windows booked for the same step
    are treated as closed intervals from `window_start` to `window_end`
    inclusive, so even touching endpoints collide". "Either condition yields
    `ERR_EXPRESS_WINDOW_OVERLAP` (HTTP 409)."

    Unlike GROUND, a second EXPRESS window starting exactly at the first
    window's inclusive end (05-02T06:00 -> 05-02T06:00) collides on the closed
    boundary and is rejected.

    Design: Difficulty/resource_temporal_overlap/express_window_buffer_within_24h_rejected
    """
    ctx = setup_case_active_step1_manufactured(proposed_step_count=10)
    s1 = ctx["steps"][0]
    validate_success(
        _book(api, s1["id"], "2026-05-02T00:00:00Z", "2026-05-02T06:00:00Z", carrier="EXPRESS"),
        201,
    )
    res = _book(api, s1["id"], "2026-05-02T06:00:00Z", "2026-05-02T12:00:00Z", carrier="EXPRESS")
    validate_error(res, "ERR_EXPRESS_WINDOW_OVERLAP", expected_status=409)
