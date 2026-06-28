"""Resource temporal overlap: half-open bay windows (touching allowed) versus
closed dryer windows with a mandatory cleanout buffer (touching rejected).

Queue A (Difficulty) — resource_temporal_overlap (bay half-open, dryer closed+buffer).
Queue B (Corner) — state_machines (cancel scheduled shipment frees bay window).
"""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
import test_helpers.fixtures as fx

MERCH = TEST_USERS["merchandiser_headers"]
CLERK = TEST_USERS["grade_clerk_headers"]
SHIPPER = TEST_USERS["shipping_clerk_headers"]


def _bay_setup():
    """WAREHOUSE_RECEIPT 1000-bu CORN position, a bay, and a SCHEDULED shipment occupying
    [08:00, 10:00). Returns (commodity, position, bay)."""
    fx.reset_clock_default()
    commodity = fx.create_commodity()
    member = fx.create_member(name="Moe Farm")
    bay = fx.create_loadout_bay(name="BAY-1")
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=commodity["id"], member_id=member["id"],
        deposit_account_type="WAREHOUSE_RECEIPT", member_name="Moe Farm",
    )
    fx.schedule_shipment(
        commodity["id"], position["id"], bay["id"], bushels=10,
        bay_window_start="2026-02-01T08:00:00Z", bay_window_end="2026-02-01T10:00:00Z",
    )
    return commodity, position, bay


def test_bay_touching_window_at_boundary_accepted(api):
    """PRD §3.7: "Because the window is half-open — the end is exclusive — windows that
    merely touch (a new window starting exactly when an existing one ends, or ending
    exactly when an existing one starts) do not conflict."

    Design: Difficulty/resource_temporal_overlap/bay_window_half_open_touching_allowed_overlap_rejected
    """
    commodity, position, bay = _bay_setup()
    resp = api.create_shipment(
        {
            "commodity_id": commodity["id"], "storage_position_id": position["id"],
            "loadout_bay_id": bay["id"], "bushels": 10,
            "bay_window_start": "2026-02-01T10:00:00Z", "bay_window_end": "2026-02-01T11:00:00Z",
        },
        SHIPPER,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SCHEDULED"


def test_bay_strictly_overlapping_window_rejected(api):
    """PRD §3.7: "A new shipment window conflicts with an existing non-cancelled shipment
    window on the same bay when the new window's start is before the existing window's end
    and the new window's end is after the existing window's start." PRD §3.7: "A
    conflicting window is rejected with `ERR_RESOURCE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/bay_window_half_open_touching_allowed_overlap_rejected
    """
    commodity, position, bay = _bay_setup()
    # window [09:30, 10:30) strictly overlaps existing [08:00, 10:00)
    resp = api.create_shipment(
        {
            "commodity_id": commodity["id"], "storage_position_id": position["id"],
            "loadout_bay_id": bay["id"], "bushels": 10,
            "bay_window_start": "2026-02-01T09:30:00Z", "bay_window_end": "2026-02-01T10:30:00Z",
        },
        SHIPPER,
    )
    validate_error(resp, ApiErrorId.ERR_RESOURCE_WINDOW_CONFLICT.value)


def _dryer_setup():
    """A dryer line DRYER-A (buffer 30) with an existing RESERVED window [10:00, 11:00] and
    a second WEIGHED ticket. Returns (line, ticket2)."""
    fx.reset_clock_default()
    commodity = fx.create_commodity()
    member = fx.create_member(name="Ned Farm")
    line = fx.create_dryer_line(name="DRYER-A", cleanout_buffer_minutes=30)
    ticket1 = fx.create_weighed_ticket(
        member["id"], commodity["id"], gross_weight_lbs=58000, tare_weight_lbs=18000,
        moisture_pct=18.0, dockage_pct=0,
    )
    ticket2 = fx.create_weighed_ticket(
        member["id"], commodity["id"], gross_weight_lbs=58000, tare_weight_lbs=18000,
        moisture_pct=18.0, dockage_pct=0,
    )
    fx.api_client.create_drying_reservation(
        {
            "dryer_line_id": line["id"], "scale_ticket_id": ticket1["id"],
            "window_start": "2026-02-01T10:00:00Z", "window_end": "2026-02-01T11:00:00Z",
        },
        CLERK,
    )
    return line, ticket2


def test_dryer_touching_or_within_buffer_window_rejected(api):
    """PRD §3.2: "two batches on the same line must be separated by strictly more than the
    buffer; windows that merely touch, or that fall within the buffer of each other, are
    rejected with `ERR_RESOURCE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/dryer_window_closed_buffer_touching_rejected
    """
    line, ticket2 = _dryer_setup()
    # new window starts 11:00 (touching the 11:00 end), within the 30-min buffer
    resp = api.create_drying_reservation(
        {
            "dryer_line_id": line["id"], "scale_ticket_id": ticket2["id"],
            "window_start": "2026-02-01T11:00:00Z", "window_end": "2026-02-01T11:45:00Z",
        },
        CLERK,
    )
    validate_error(resp, ApiErrorId.ERR_RESOURCE_WINDOW_CONFLICT.value)


def test_dryer_window_separated_beyond_buffer_accepted(api):
    """PRD §3.2: "two batches on the same line must be separated by strictly more than the
    buffer". PRD §3.2: "A reservation is born `RESERVED`."

    Design: Difficulty/resource_temporal_overlap/dryer_window_closed_buffer_touching_rejected
    """
    line, ticket2 = _dryer_setup()
    # [11:31, 12:30] is separated by >30 minutes from the 11:00 end
    resp = api.create_drying_reservation(
        {
            "dryer_line_id": line["id"], "scale_ticket_id": ticket2["id"],
            "window_start": "2026-02-01T11:31:00Z", "window_end": "2026-02-01T12:30:00Z",
        },
        CLERK,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "RESERVED"


def test_cancel_scheduled_shipment_frees_bay_window(api):
    """PRD §3.7: "A scheduled shipment may be cancelled ... the bay window the shipment was
    holding is released and no longer conflicts with new reservations." PRD §3.7: "Only
    shipments in `SCHEDULED`, `LOADED`, or `SHIPPED` status occupy the bay; a cancelled
    shipment's window is free."

    Design: Corner/state_machines/cancel_scheduled_shipment_frees_bay_window
    """
    fx.reset_clock_default()
    commodity = fx.create_commodity()
    member = fx.create_member(name="DD Farm")
    bay = fx.create_loadout_bay(name="BAY-3")
    _, _, _graded, position = fx.create_graded_position(
        commodity_id=commodity["id"], member_id=member["id"],
        deposit_account_type="WAREHOUSE_RECEIPT", member_name="DD Farm",
    )
    sh1 = fx.schedule_shipment(
        commodity["id"], position["id"], bay["id"], bushels=100,
        bay_window_start="2026-02-01T08:00:00Z", bay_window_end="2026-02-01T10:00:00Z",
    )
    cancelled = validate_success(api.cancel_shipment(sh1["id"], SHIPPER))
    assert cancelled["status"] == "CANCELLED"
    # an overlapping window is now accepted because the prior holder is cancelled
    resp = api.create_shipment(
        {
            "commodity_id": commodity["id"], "storage_position_id": position["id"],
            "loadout_bay_id": bay["id"], "bushels": 100,
            "bay_window_start": "2026-02-01T08:30:00Z", "bay_window_end": "2026-02-01T09:30:00Z",
        },
        SHIPPER,
    )
    sh2 = validate_success(resp, expected_status=201)
    assert sh2["status"] == "SCHEDULED"
