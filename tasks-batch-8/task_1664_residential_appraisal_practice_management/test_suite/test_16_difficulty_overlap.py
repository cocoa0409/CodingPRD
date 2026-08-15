"""Difficulty queue A: resource temporal overlap — the appointment travel
buffer's half-open interval semantics and the fee-schedule half-open window
semantics (PRD 3.1, 3.4)."""
from test_helpers import (
    ApiErrorId,
    confirm_appointment,
    create_appointment,
    create_client,
    create_fee_schedule_payload,
    get_client,
    set_clock,
    setup_assigned_order,
    validate_error,
    validate_success,
)
from test_helpers import ADMIN


def _setup_overlap_scenario():
    """Inspection order ASSIGNED to appraiser A; one CONFIRMED appointment
    2026-08-02 09:00-10:00; two more PROPOSED at 10:30-11:30 (conflicts via
    buffer) and 11:00-12:00 (buffer-adjacent, allowed)."""
    ctx = setup_assigned_order(desktop=False, order_overrides={"requested_turn_days": 14})
    first = create_appointment(
        ctx["order"]["id"],
        ctx["appraiser"]["id"],
        "2026-08-02T09:00:00Z",
        "2026-08-02T10:00:00Z",
    )
    confirm_appointment(first["id"], ctx["appraiser"]["id"])
    conflicting = create_appointment(
        ctx["order"]["id"],
        ctx["appraiser"]["id"],
        "2026-08-02T10:30:00Z",
        "2026-08-02T11:30:00Z",
    )
    adjacent = create_appointment(
        ctx["order"]["id"],
        ctx["appraiser"]["id"],
        "2026-08-02T11:00:00Z",
        "2026-08-02T12:00:00Z",
    )
    return ctx, conflicting, adjacent


def test_appointment_buffer_overlap_rejected(api):
    """PRD 3.4: "Confirmation also enforces a travel buffer: every appointment
    carries a buffered window from thirty minutes before its `window_start`
    to thirty minutes after its `window_end`, half-open, and the candidate's
    buffered window may not intersect the buffered window of any other
    `CONFIRMED` appointment belonging to the same appraiser."
    PRD 3.4: "A violation is rejected with `ERR_APPOINTMENT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/appointment_buffer_expanded_overlap_semantics
    """
    ctx, conflicting, _ = _setup_overlap_scenario()
    # buffered [09:45, 12:00) vs existing [08:30, 10:30) -> intersect
    response = api.confirm_appointment(conflicting["id"], ctx["appraiser_headers"])
    validate_error(response, ApiErrorId.ERR_APPOINTMENT_OVERLAP, 422)


def test_appointment_buffer_exact_adjacency_allowed(api):
    """PRD 3.4: "Because the interval is half-open, one buffer ending at the
    exact instant another begins is not an intersection."

    Design: Difficulty/resource_temporal_overlap/appointment_buffer_expanded_overlap_semantics
    """
    ctx, _, adjacent = _setup_overlap_scenario()
    # buffered [10:30, 12:30) vs existing [08:30, 10:30) -> empty intersection
    confirmed = validate_success(
        api.confirm_appointment(adjacent["id"], ctx["appraiser_headers"]), 200
    )
    assert confirmed["status"] == "CONFIRMED"


def _setup_schedule_windows(api):
    """Client with STANDARD window A [2026-07-01, 2026-08-01) base 40000."""
    set_clock("2026-08-01T00:00:00Z")
    client = create_client(name="AMC Nineteen")
    validate_success(
        api.create_fee_schedule(
            create_fee_schedule_payload(
                client["id"],
                client["version"],
                base_fee_cents=40000,
                rush_multiplier_bps=1000,
                revision_fee_cents=12000,
                effective_from="2026-07-01T00:00:00Z",
                effective_to="2026-08-01T00:00:00Z",
            ),
            ADMIN,
        ),
        201,
    )
    return client


def test_fee_schedule_adjacent_window_allowed(api):
    """PRD 3.1: "Windows are half-open: a schedule governs from
    `effective_from` up to but not including `effective_to`."

    Design: Difficulty/resource_temporal_overlap/fee_schedule_half_open_window_adjacency_vs_overlap
    """
    client = _setup_schedule_windows(api)
    # effective_from == A.effective_to: half-open touch is not an overlap
    created = validate_success(
        api.create_fee_schedule(
            create_fee_schedule_payload(
                client["id"],
                get_client(client["id"])["version"],
                base_fee_cents=52000,
                rush_multiplier_bps=1000,
                revision_fee_cents=12000,
                effective_from="2026-08-01T00:00:00Z",
            ),
            ADMIN,
        ),
        201,
    )
    assert created["effective_from"] == "2026-08-01T00:00:00Z"


def test_fee_schedule_overlapping_window_rejected(api):
    """PRD 3.1: "For any one client and tier, windows must never overlap; a
    new row whose window would intersect an existing window for the same pair
    is rejected with `ERR_SCHEDULE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/fee_schedule_half_open_window_adjacency_vs_overlap
    """
    client = _setup_schedule_windows(api)
    # first extend the timeline with the legal adjacent window B
    validate_success(
        api.create_fee_schedule(
            create_fee_schedule_payload(
                client["id"],
                get_client(client["id"])["version"],
                base_fee_cents=52000,
                rush_multiplier_bps=1000,
                revision_fee_cents=12000,
                effective_from="2026-08-01T00:00:00Z",
            ),
            ADMIN,
        ),
        201,
    )
    # window C starting 2026-07-15 intersects A [07-01, 08-01)
    response = api.create_fee_schedule(
        create_fee_schedule_payload(
            client["id"],
            get_client(client["id"])["version"],
            base_fee_cents=60000,
            rush_multiplier_bps=1000,
            revision_fee_cents=12000,
            effective_from="2026-07-15T00:00:00Z",
        ),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_SCHEDULE_WINDOW_OVERLAP, 422)
