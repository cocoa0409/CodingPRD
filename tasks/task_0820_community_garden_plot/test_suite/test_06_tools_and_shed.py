"""Shared tools and shed: active-gardener gate, late-return fines and boundary,
tool buffer overlap, and shed adjacency semantics."""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, make_gardener_headers,
    ApiErrorId,
    set_clock, new_garden, new_gardener, new_tool, new_tool_loan,
    setup_active_gardener_with_tool, setup_assigned_plot,
    create_tool_loan_payload, create_shed_booking_payload,
)

MANAGER = TEST_USERS["manager_headers"]


# ----------------------------------------------------------------------
# Difficulty: tool return exactly at due_at (inclusive boundary) -> no fine
# ----------------------------------------------------------------------

def test_return_exactly_at_due_incurs_no_fine(api):
    """PRD §3.9: "If `returned_at` is at or before `due_at`, the loan is on time: it
    moves to `RETURNED` and its `late_fine_cents` is 0 — the boundary is inclusive, so
    a return exactly at `due_at` incurs no fine."

    Design: Difficulty/boundary_precision_check/tool_return_exactly_at_due_boundary_zero_fine
    """
    ctx = setup_active_gardener_with_tool(api, cleaning_buffer_hours=4)
    loan = new_tool_loan(api, ctx["tool"]["id"], ctx["gardener"]["id"],
                         "2026-03-15T08:00:00Z", "2026-03-15T12:00:00Z")
    returned = validate_success(
        api.return_tool_loan(loan["id"], {"returned_at": "2026-03-15T12:00:00Z"}, ctx["gardener_headers"]), 200
    )
    assert returned["late_fine_cents"] == 0
    assert returned["status"] == "RETURNED"


def test_return_just_after_due_incurs_full_hour_fine(api):
    """PRD §3.9: "If `returned_at` is strictly after `due_at`, the loan moves to
    `RETURNED_LATE` and a fine is assessed: the lateness is measured as the elapsed
    time from `due_at` to `returned_at` rounded up to a whole number of hours (any
    partial hour counts as a full hour), and `late_fine_cents` is that whole-hour count
    multiplied by 200 cents per hour."

    Design: Difficulty/boundary_precision_check/tool_return_exactly_at_due_boundary_zero_fine
    """
    ctx = setup_active_gardener_with_tool(api, cleaning_buffer_hours=4)
    loan = new_tool_loan(api, ctx["tool"]["id"], ctx["gardener"]["id"],
                         "2026-03-15T08:00:00Z", "2026-03-15T12:00:00Z")
    returned = validate_success(
        api.return_tool_loan(loan["id"], {"returned_at": "2026-03-15T12:00:01Z"}, ctx["gardener_headers"]), 200
    )
    assert returned["late_fine_cents"] == 200
    assert returned["status"] == "RETURNED_LATE"


# ----------------------------------------------------------------------
# Difficulty: tool checkout requires the caller to hold an ACTIVE assignment
# ----------------------------------------------------------------------

def test_tool_checkout_without_active_assignment_denied(api):
    """PRD §3.9: "Before a gardener may check out a tool or book the shed, they must
    hold at least one assignment with `occupancy_status` of `ACTIVE` in the relevant
    garden; a gardener without such an active assignment is rejected with
    `ERR_NOT_ACTIVE_GARDENER` (HTTP 403)."

    Design: Difficulty/cross_entity_state_dependency/tool_checkout_requires_active_assignment
    """
    set_clock(api, "2026-03-15T00:00:00Z")
    garden = new_garden(api, name="Laurel Garden")
    gardener = new_gardener(api, full_name="Gwen Ash")
    tool = new_tool(api, garden["id"], name="Hoe 3", category="HAND")
    resp = api.create_tool_loan(
        create_tool_loan_payload(tool["id"], gardener["id"], "2026-03-15T08:00:00Z", "2026-03-15T12:00:00Z"),
        make_gardener_headers(gardener["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_ACTIVE_GARDENER.value, 403)


def test_active_gardener_may_check_out_tool(api):
    """PRD §3.9: "Before a gardener may check out a tool or book the shed, they must
    hold at least one assignment with `occupancy_status` of `ACTIVE` in the relevant
    garden; a gardener without such an active assignment is rejected with
    `ERR_NOT_ACTIVE_GARDENER` (HTTP 403)."

    Design: Difficulty/cross_entity_state_dependency/tool_checkout_requires_active_assignment
    """
    ctx = setup_active_gardener_with_tool(api, cleaning_buffer_hours=4)
    resp = api.create_tool_loan(
        create_tool_loan_payload(ctx["tool"]["id"], ctx["gardener"]["id"],
                                 "2026-03-15T08:00:00Z", "2026-03-15T12:00:00Z"),
        ctx["gardener_headers"],
    )
    loan = validate_success(resp, 201)
    assert loan["status"] == "CHECKED_OUT"


# ----------------------------------------------------------------------
# Difficulty: tool buffer overlap (cleaning window extends past due_at)
# ----------------------------------------------------------------------

def test_tool_loan_within_cleaning_buffer_rejected(api):
    """PRD §3.9: "That occupied window runs from the existing loan's `checked_out_at`
    up to its effective end plus the tool's `cleaning_buffer_hours`, where the effective
    end is the loan's `returned_at` if set and otherwise its `due_at`. An intersecting
    request is rejected with `ERR_TOOL_TIME_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/tool_loan_buffer_overlap_rejected
    """
    ctx = setup_active_gardener_with_tool(api, cleaning_buffer_hours=4)
    new_tool_loan(api, ctx["tool"]["id"], ctx["gardener"]["id"],
                  "2026-03-15T08:00:00Z", "2026-03-15T12:00:00Z")
    # occupied window is [08:00, 16:00); a 14:00 start intersects it.
    resp = api.create_tool_loan(
        create_tool_loan_payload(ctx["tool"]["id"], ctx["gardener"]["id"],
                                 "2026-03-15T14:00:00Z", "2026-03-15T18:00:00Z"),
        ctx["gardener_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_TOOL_TIME_CONFLICT.value, 409)


def test_tool_loan_after_cleaning_buffer_allowed(api):
    """PRD §3.9: "A tool cannot be double-booked: the requested interval from
    `checked_out_at` to `due_at` must not intersect the occupied window of any
    non-returned loan of the same tool. That occupied window runs from the existing
    loan's `checked_out_at` up to its effective end plus the tool's
    `cleaning_buffer_hours`, where the effective end is the loan's `returned_at` if set
    and otherwise its `due_at`."

    Design: Difficulty/resource_temporal_overlap/tool_loan_buffer_overlap_rejected
    """
    ctx = setup_active_gardener_with_tool(api, cleaning_buffer_hours=4)
    new_tool_loan(api, ctx["tool"]["id"], ctx["gardener"]["id"],
                  "2026-03-15T08:00:00Z", "2026-03-15T12:00:00Z")
    # 17:00 start is past the [08:00, 16:00) occupied window: no intersection.
    resp = api.create_tool_loan(
        create_tool_loan_payload(ctx["tool"]["id"], ctx["gardener"]["id"],
                                 "2026-03-15T17:00:00Z", "2026-03-15T19:00:00Z"),
        ctx["gardener_headers"],
    )
    loan = validate_success(resp, 201)
    assert loan["status"] == "CHECKED_OUT"


# ----------------------------------------------------------------------
# Difficulty: shed booking half-open adjacency semantics
# ----------------------------------------------------------------------

def test_shed_booking_interior_overlap_rejected(api):
    """PRD §3.9: "A booking window must not intersect any existing shed booking for the
    same garden, or the request is rejected with `ERR_SHED_TIME_CONFLICT` (HTTP 409);
    as with plot seasons, the interval is half-open with no buffer, so bookings that
    merely touch at a boundary are allowed."

    Design: Difficulty/resource_temporal_overlap/shed_booking_adjacency_overlap_rejected
    """
    ctx = setup_assigned_plot(api, size="MEDIUM", clock="2026-03-15T00:00:00Z")
    gid, gard_id = ctx["garden"]["id"], ctx["gardener"]["id"]
    headers = ctx["gardener_headers"]
    validate_success(api.create_shed_booking(
        create_shed_booking_payload(gid, gard_id, "2026-03-15T09:00:00Z", "2026-03-15T11:00:00Z", "STORAGE"),
        headers), 201)
    resp = api.create_shed_booking(
        create_shed_booking_payload(gid, gard_id, "2026-03-15T10:00:00Z", "2026-03-15T12:00:00Z", "WORKSHOP"),
        headers)
    validate_error(resp, ApiErrorId.ERR_SHED_TIME_CONFLICT.value, 409)


def test_shed_booking_touching_boundary_allowed(api):
    """PRD §3.9: "the interval is half-open with no buffer, so bookings that merely
    touch at a boundary are allowed."

    Design: Difficulty/resource_temporal_overlap/shed_booking_adjacency_overlap_rejected
    """
    ctx = setup_assigned_plot(api, size="MEDIUM", clock="2026-03-15T00:00:00Z")
    gid, gard_id = ctx["garden"]["id"], ctx["gardener"]["id"]
    headers = ctx["gardener_headers"]
    validate_success(api.create_shed_booking(
        create_shed_booking_payload(gid, gard_id, "2026-03-15T09:00:00Z", "2026-03-15T11:00:00Z", "STORAGE"),
        headers), 201)
    # A booking starting exactly at 11:00 only touches the prior booking's exclusive end.
    resp = api.create_shed_booking(
        create_shed_booking_payload(gid, gard_id, "2026-03-15T11:00:00Z", "2026-03-15T13:00:00Z", "MEETING"),
        headers)
    booking = validate_success(resp, 201)
    assert booking["id"], "adjacent booking must be created"


# ----------------------------------------------------------------------
# Corner: one-hour-late tool return fine
# ----------------------------------------------------------------------

def test_tool_late_return_one_hour_fine(api):
    """PRD §3.9: "the lateness is measured as the elapsed time from `due_at` to
    `returned_at` rounded up to a whole number of hours (any partial hour counts as a
    full hour), and `late_fine_cents` is that whole-hour count multiplied by 200 cents
    per hour."

    Design: Corner/calculations/tool_late_return_one_hour_fine
    """
    ctx = setup_active_gardener_with_tool(api, cleaning_buffer_hours=4)
    loan = new_tool_loan(api, ctx["tool"]["id"], ctx["gardener"]["id"],
                         "2026-03-15T08:00:00Z", "2026-03-15T12:00:00Z")
    returned = validate_success(
        api.return_tool_loan(loan["id"], {"returned_at": "2026-03-15T13:00:00Z"}, ctx["gardener_headers"]), 200
    )
    assert returned["late_fine_cents"] == 200
    assert returned["status"] == "RETURNED_LATE"
