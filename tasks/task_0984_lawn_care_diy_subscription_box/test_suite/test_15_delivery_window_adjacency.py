"""Delivery windows: half-open interval overlap on a subscription (PRD 3.6)."""
import test_helpers as th

OPS = th.TEST_USERS["fulfillment_ops_headers"]


def test_delivery_window_half_open_adjacency_on_subscription(api):
    """PRD 3.6: "The delivery window must not overlap the window of any other non-terminal box on the same subscription, though half-open adjacency — one window ending exactly when another begins — is allowed; an overlap is rejected with `ERR_DELIVERY_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/delivery_window_half_open_adjacency_on_subscription
    """
    ctx = th.setup_active_subscription(email="dw@x.com")
    sub_id = ctx["subscription"]["id"]
    box_a = th.create_box(
        sub_id, lines=[th.shipment_line("FERT-01", 1)],
        ship_date="2026-06-01T00:00:00Z",
        delivery_window_start="2026-06-01T00:00:00Z",
        delivery_window_end="2026-06-10T00:00:00Z",
    )
    assert box_a["fulfillment_status"] == "SCHEDULED"

    # Adjacency: B's start equals A's end exactly — allowed.
    box_b = th.create_box(
        sub_id, lines=[th.shipment_line("FERT-01", 1)],
        ship_date="2026-06-10T00:00:00Z",
        delivery_window_start="2026-06-10T00:00:00Z",
        delivery_window_end="2026-06-20T00:00:00Z",
    )
    assert box_b["id"], "half-open adjacency must be allowed"

    # True overlap: C [06-09, 06-15) intersects both A and B.
    th.validate_error(
        api.create_shipment(
            th.shipment_payload(
                sub_id, lines=[th.shipment_line("FERT-01", 1)],
                ship_date="2026-06-09T00:00:00Z",
                delivery_window_start="2026-06-09T00:00:00Z",
                delivery_window_end="2026-06-15T00:00:00Z",
            ),
            OPS,
        ),
        th.ApiErrorId.ERR_DELIVERY_WINDOW_CONFLICT,
    )


def test_delivery_window_identical_overlap_rejected(api):
    """PRD 3.6: "The delivery window must not overlap the window of any other non-terminal box on the same subscription, though half-open adjacency — one window ending exactly when another begins — is allowed; an overlap is rejected with `ERR_DELIVERY_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/delivery_window_half_open_adjacency_on_subscription
    """
    ctx = th.setup_active_subscription(email="dw2@x.com")
    sub_id = ctx["subscription"]["id"]
    th.create_box(
        sub_id, lines=[th.shipment_line("FERT-01", 1)],
        ship_date="2026-06-01T00:00:00Z",
        delivery_window_start="2026-06-01T00:00:00Z",
        delivery_window_end="2026-06-10T00:00:00Z",
    )
    # Identical window is the maximal overlap.
    th.validate_error(
        api.create_shipment(
            th.shipment_payload(
                sub_id, lines=[th.shipment_line("FERT-01", 1)],
                ship_date="2026-06-01T00:00:00Z",
                delivery_window_start="2026-06-01T00:00:00Z",
                delivery_window_end="2026-06-10T00:00:00Z",
            ),
            OPS,
        ),
        th.ApiErrorId.ERR_DELIVERY_WINDOW_CONFLICT,
    )
