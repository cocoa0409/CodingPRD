"""Product application window: half-open [start, end) edges (PRD 3.1, 3.7)."""
import test_helpers as th


def test_application_window_half_open_edges(api):
    """PRD 3.1: "Each product defines a seasonal application window through `window_start_md` and `window_end_md`, both month-and-day strings. The window is half-open: an application scheduled on the start day is inside the window, while one scheduled on the end day is already outside it."
    PRD 3.7: "The second guard is the product window: the scheduled date must fall on or after `window_start_date` and strictly before `window_end_date`, otherwise `ERR_APPLICATION_WINDOW_VIOLATION` (HTTP 422)."

    Design: Corner/calculations/application_window_half_open_edges
    """
    ctx = th.setup_active_subscription(email="aw@x.com")
    box, _ = th.setup_delivered_box(ctx, lines=[th.shipment_line("FERT-01", 1)])
    sub_id = ctx["subscription"]["id"]

    # FERT-01's window is [03-01, 07-01): the start day is inside.
    task = th.validate_success(
        api.create_application(
            th.application_payload(sub_id, box["id"], product_sku="FERT-01",
                                   scheduled_date="2026-03-01"),
            ctx["customer_headers"],
        ),
        201,
    )
    assert task["status"] == "SCHEDULED"
    assert task["window_start_date"] == "2026-03-01"
    assert task["window_end_date"] == "2026-07-01"

    # The end day is already outside the half-open window.
    th.validate_error(
        api.create_application(
            th.application_payload(sub_id, box["id"], product_sku="FERT-01",
                                   scheduled_date="2026-07-01"),
            ctx["customer_headers"],
        ),
        th.ApiErrorId.ERR_APPLICATION_WINDOW_VIOLATION,
    )
