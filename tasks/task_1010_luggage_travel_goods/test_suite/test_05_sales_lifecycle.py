"""Sales lifecycle: independent payment/fulfillment axes, monogram scheduling, and fulfillment guards."""
import test_helpers as H


def _order_with_two_monogram_lines(api):
    """PENDING order with a station and two monogrammed lines; line_a scheduled [09:00,09:30)."""
    station = H.new_station(api)
    customer = H.new_customer(api)
    product = H.new_product(api, msrp_cents=22000)
    order = H.new_sales_order(customer["id"], api)
    line_a = H.new_sales_order_line(order["id"], product["id"], api,
                                    unit_price_cents=22000, qty=1, monogram_text="AA")
    line_b = H.new_sales_order_line(order["id"], product["id"], api,
                                    unit_price_cents=22000, qty=1, monogram_text="BB")
    H.get_success_data(api.schedule_monogram(
        line_a["id"], {"monogram_station_id": station["id"],
                       "monogram_start": "2026-07-05T09:00:00Z",
                       "monogram_end": "2026-07-05T09:30:00Z"}, H.TEST_USERS["associate_headers"]))
    return station, order, line_b


# ==========================================================================
# Queue A — non-linear state machine: parallel payment/fulfillment axes
# ==========================================================================
def test_capture_advances_payment_axis_only(api):
    """PRD §3.5: "Payment is captured by an `Associate`, moving the payment axis
    `PENDING → CAPTURED`."

    Design: Difficulty/non_linear_state_machine/sales_order_parallel_payment_fulfillment_axes
    """
    customer = H.new_customer(api)
    product = H.new_product(api, msrp_cents=15000)
    order = H.captured_order_with_line(customer["id"], product["id"], unit_price_cents=15000, qty=1, api=api)
    assert order["payment_status"] == "CAPTURED"


def test_capture_leaves_fulfillment_axis_unfulfilled(api):
    """PRD §3.5: "The fulfillment axis evolves independently of payment."

    Design: Difficulty/non_linear_state_machine/sales_order_parallel_payment_fulfillment_axes
    """
    customer = H.new_customer(api)
    product = H.new_product(api, msrp_cents=15000)
    order = H.captured_order_with_line(customer["id"], product["id"], unit_price_cents=15000, qty=1, api=api)
    assert order["fulfillment_status"] == "UNFULFILLED"


# ==========================================================================
# Queue A — resource temporal overlap: buffered monogram station windows
# ==========================================================================
def test_monogram_window_within_buffer_is_rejected(api, associate_headers):
    """PRD §2.10: "Two monograms conflict on the same station when, after each occupied window is
    padded by 15 minutes before its start and after its end, the padded intervals intersect (a
    closed-interval intersection: touching at a single instant after padding counts as a conflict)."

    Design: Difficulty/resource_temporal_overlap/monogram_station_buffer_conflict_on_gap
    """
    station, _order, line_b = _order_with_two_monogram_lines(api)
    H.validate_error(api.schedule_monogram(
        line_b["id"], {"monogram_station_id": station["id"],
                       "monogram_start": "2026-07-05T09:40:00Z",
                       "monogram_end": "2026-07-05T10:00:00Z"}, associate_headers),
        H.ApiErrorId.ERR_SCHEDULE_CONFLICT)


def test_monogram_window_clearing_buffer_is_allowed(api, associate_headers):
    """PRD §2.10: "Two monograms conflict on the same station when, after each occupied window is
    padded by 15 minutes before its start and after its end, the padded intervals intersect (a
    closed-interval intersection: touching at a single instant after padding counts as a conflict)."

    Design: Difficulty/resource_temporal_overlap/monogram_station_buffer_conflict_on_gap
    """
    station, _order, line_b = _order_with_two_monogram_lines(api)
    data = H.validate_success(api.schedule_monogram(
        line_b["id"], {"monogram_station_id": station["id"],
                       "monogram_start": "2026-07-05T10:05:00Z",
                       "monogram_end": "2026-07-05T10:35:00Z"}, associate_headers))
    assert data["monogram_status"] == "SCHEDULED"


# ==========================================================================
# Queue A — cross-entity state dependency: start-monogram needs captured order
# ==========================================================================
def _pending_order_with_scheduled_monogram(api):
    station = H.new_station(api)
    customer = H.new_customer(api)
    product = H.new_product(api, msrp_cents=21000)
    order = H.new_sales_order(customer["id"], api)
    line = H.new_sales_order_line(order["id"], product["id"], api,
                                  unit_price_cents=21000, qty=1, monogram_text="ABC")
    H.get_success_data(api.schedule_monogram(
        line["id"], {"monogram_station_id": station["id"],
                     "monogram_start": "2026-07-03T09:00:00Z",
                     "monogram_end": "2026-07-03T09:30:00Z"}, H.TEST_USERS["associate_headers"]))
    return order, line


def test_start_monogram_before_capture_is_rejected(api, associate_headers):
    """PRD §3.5: "From `SCHEDULED`, an `Associate` begins the work, moving
    `SCHEDULED → IN_PROGRESS`, but only if the parent order's payment is `CAPTURED` (otherwise
    `ERR_ORDER_NOT_CAPTURED`)."

    Design: Difficulty/cross_entity_state_dependency/start_monogram_requires_order_captured
    """
    _order, line = _pending_order_with_scheduled_monogram(api)
    H.validate_error(api.start_monogram(line["id"], associate_headers), H.ApiErrorId.ERR_ORDER_NOT_CAPTURED)


def test_start_monogram_before_capture_leaves_line_scheduled(api, associate_headers):
    """PRD §3.5: "From `SCHEDULED`, an `Associate` begins the work, moving
    `SCHEDULED → IN_PROGRESS`, but only if the parent order's payment is `CAPTURED` (otherwise
    `ERR_ORDER_NOT_CAPTURED`)."

    Design: Difficulty/cross_entity_state_dependency/start_monogram_requires_order_captured
    """
    _order, line = _pending_order_with_scheduled_monogram(api)
    H.validate_error(api.start_monogram(line["id"], associate_headers), H.ApiErrorId.ERR_ORDER_NOT_CAPTURED)
    after = H.get_sales_order_line(line["id"], api)
    assert after["monogram_status"] == "SCHEDULED"


# ==========================================================================
# Queue B — state machines / validations
# ==========================================================================
def test_capture_already_captured_order_returns_invalid_state(api, associate_headers):
    """PRD §2.8: "4. **State validity** — the target resource is in a state from which the
    requested transition is defined, else `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/capture_order_twice_returns_invalid_state
    """
    customer = H.new_customer(api)
    product = H.new_product(api, msrp_cents=10000)
    order = H.captured_order_with_line(customer["id"], product["id"], unit_price_cents=10000, qty=1, api=api)
    H.validate_error(api.capture_sales_order(order["id"], associate_headers), H.ApiErrorId.ERR_INVALID_STATE)


def test_fulfill_with_pending_monogram_is_rejected(api, associate_headers):
    """PRD §3.5: "An `Associate` fulfills an order, moving `UNFULFILLED → FULFILLED`, but only when
    the order's payment is `CAPTURED` and every line bearing a `monogram_text` has reached
    `monogram_status` `DONE`; a monogrammed line still in progress blocks fulfillment with
    `ERR_MONOGRAM_PENDING`."

    Design: Corner/validations/fulfill_with_pending_monogram_returns_monogram_pending
    """
    customer = H.new_customer(api)
    product = H.new_product(api, msrp_cents=15000)
    order = H.new_sales_order(customer["id"], api)
    H.new_sales_order_line(order["id"], product["id"], api, unit_price_cents=15000, qty=1, monogram_text="ZZ")
    H.get_success_data(api.capture_sales_order(order["id"], associate_headers))
    H.validate_error(api.fulfill_sales_order(order["id"], associate_headers), H.ApiErrorId.ERR_MONOGRAM_PENDING)
