"""Order capture: cut-off boundary, delivery-window half-open adjacency, and the
pinned per-line rounding order (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_accepted_lot,
    create_customer,
    create_ordered_lot,
    create_pending_order,
    order_line,
    set_clock,
    setup_accepted_lot,
    setup_market_day,
    validate_error,
    validate_success,
)
from test_helpers import RECEIVER_HEADERS, SALES_HEADERS


def _setup_order_ready():
    """ACCEPTED lot + ACTIVE customer with ample credit. Clock at 08:00."""
    base = setup_accepted_lot(defect_pct=0)
    base["customer"] = create_customer(credit_limit_cents=1000000)
    return base


# --- Cut-off boundary (Difficulty/boundary_precision_check) -------------------

def test_next_day_order_at_exactly_1400_accepted(api):
    """PRD §3.6: "First, the cut-off: a `delivery_date` on or before the current clock
    date is rejected with `ERR_CUTOFF_PASSED`; so is a `delivery_date` exactly one day
    ahead when the clock time is strictly after 14:00:00 — exactly 14:00:00 itself is
    still allowed."

    Design: Difficulty/boundary_precision_check/order_cutoff_exactly_at_1400_accepted
    """
    base = _setup_order_ready()
    set_clock("2026-05-01T14:00:00Z")
    resp = api.create_sales_order(
        {"customer_id": base["customer"]["id"], "delivery_date": "2026-05-02",
         "window_start": "08:00", "window_end": "10:00",
         "lines": [order_line(base["lot"]["id"], 1, 10.00)]}, SALES_HEADERS)
    data = validate_success(resp, 201)
    assert data["status"] == "PENDING"


def test_next_day_order_before_1400_accepted(api):
    """PRD §3.6: "so is a `delivery_date` exactly one day ahead when the clock time is
    strictly after 14:00:00 — exactly 14:00:00 itself is still allowed."

    Design: Difficulty/boundary_precision_check/order_cutoff_exactly_at_1400_accepted
    """
    base = _setup_order_ready()
    set_clock("2026-05-01T13:59:59Z")
    resp = api.create_sales_order(
        {"customer_id": base["customer"]["id"], "delivery_date": "2026-05-02",
         "window_start": "08:00", "window_end": "10:00",
         "lines": [order_line(base["lot"]["id"], 1, 10.00)]}, SALES_HEADERS)
    data = validate_success(resp, 201)
    assert data["status"] == "PENDING"


# --- Delivery-window half-open adjacency (Difficulty/resource_temporal_overlap) --

def test_adjacent_delivery_windows_allowed(api):
    """PRD §3.6: "Adjacency is allowed — an existing `[08:00,10:00)` followed by a new
    `[10:00,12:00)` passes."

    Design: Difficulty/resource_temporal_overlap/delivery_window_strict_half_open_adjacency
    """
    base = _setup_order_ready()
    create_pending_order(base["customer"]["id"], base["lot"]["id"],
                         window_start="08:00", window_end="10:00")
    resp = api.create_sales_order(
        {"customer_id": base["customer"]["id"], "delivery_date": "2026-05-02",
         "window_start": "10:00", "window_end": "12:00",
         "lines": [order_line(base["lot"]["id"], 1, 10.00)]}, SALES_HEADERS)
    data = validate_success(resp, 201)
    assert data["status"] == "PENDING"


def test_intersecting_delivery_window_rejected(api):
    """PRD §3.6: "on the same `delivery_date`, the new order's half-open window
    `[window_start, window_end)` must not intersect the window of any of the
    customer's existing orders that are neither `CANCELLED` nor `INVOICED`; an
    intersection is `ERR_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/delivery_window_strict_half_open_adjacency
    """
    base = _setup_order_ready()
    create_pending_order(base["customer"]["id"], base["lot"]["id"],
                         window_start="08:00", window_end="10:00")
    resp = api.create_sales_order(
        {"customer_id": base["customer"]["id"], "delivery_date": "2026-05-02",
         "window_start": "09:00", "window_end": "11:00",
         "lines": [order_line(base["lot"]["id"], 1, 10.00)]}, SALES_HEADERS)
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)


# --- Per-line rounding order (Difficulty/combinatorial_formula) ---------------

def _setup_half_cent_lots():
    """Two ACCEPTED lots of 10 units @ 2.505 inside the [2.00, 3.00] band."""
    base = setup_market_day(
        commodity_overrides={"code": "HER", "name": "Herbs",
                             "ethylene_class": "NEUTRAL",
                             "temp_min_f": 34, "temp_max_f": 40},
        low_price=2.00, high_price=3.00)
    lot1 = create_accepted_lot(base["shipper"]["id"], base["commodity"]["id"],
                               defect_pct=0, quantity_units=10,
                               shipper_unit_price=2.505)
    lot2 = create_accepted_lot(base["shipper"]["id"], base["commodity"]["id"],
                               defect_pct=0, quantity_units=10,
                               shipper_unit_price=2.505)
    base["lot1"] = lot1
    base["lot2"] = lot2
    base["customer"] = create_customer(credit_limit_cents=1000000)
    return base


def test_two_half_cent_lines_round_individually_then_sum(api):
    """PRD §3.6: "The rounding order is pinned: each line is first extended by
    multiplying its `unit_price` by its `quantity` and by 100, rounding half-up to
    integer cents; then those per-line amounts are summed to produce
    `subtotal_cents`."
    PRD §3.6: "Summing the raw products and rounding once at the end is explicitly not
    the rule — two lines of 2.505 × 1 yield 251 + 251 = 502, not 501."

    Design: Difficulty/combinatorial_formula/order_subtotal_per_line_rounding_then_sum
    """
    base = _setup_half_cent_lots()
    resp = api.create_sales_order(
        {"customer_id": base["customer"]["id"], "delivery_date": "2026-05-02",
         "window_start": "08:00", "window_end": "10:00",
         "lines": [order_line(base["lot1"]["id"], 1, 2.505),
                   order_line(base["lot2"]["id"], 1, 2.505)]}, SALES_HEADERS)
    data = validate_success(resp, 201)
    assert data["subtotal_cents"] == 502, (
        "per-line round_half_up(250.5)=251 then sum; sum-then-round would give 501")


def test_single_half_cent_line_rounds_half_up(api):
    """PRD §3.6: "each line is first extended by multiplying its `unit_price` by its
    `quantity` and by 100, rounding half-up to integer cents; then those per-line
    amounts are summed to produce `subtotal_cents`."

    Design: Difficulty/combinatorial_formula/order_subtotal_per_line_rounding_then_sum
    """
    base = _setup_half_cent_lots()
    resp = api.create_sales_order(
        {"customer_id": base["customer"]["id"], "delivery_date": "2026-05-02",
         "window_start": "08:00", "window_end": "10:00",
         "lines": [order_line(base["lot1"]["id"], 3, 2.505)]}, SALES_HEADERS)
    data = validate_success(resp, 201)
    assert data["subtotal_cents"] == 752, (
        "round_half_up(2.505 * 3 * 100) = round_half_up(751.5) = 752")


# --- Breadth: cut-off rejection sides and validation priority -----------------

def test_order_create_after_cutoff_returns_cutoff_passed(api):
    """PRD §3.6: "First, the cut-off: a `delivery_date` on or before the current clock
    date is rejected with `ERR_CUTOFF_PASSED`; so is a `delivery_date` exactly one day
    ahead when the clock time is strictly after 14:00:00 — exactly 14:00:00 itself is
    still allowed."

    Design: Corner/validations/order_create_after_cutoff_returns_cutoff_passed
    """
    base = _setup_order_ready()
    set_clock("2026-05-01T14:00:01Z")  # one second past the cut-off
    next_day = api.create_sales_order(
        {"customer_id": base["customer"]["id"], "delivery_date": "2026-05-02",
         "window_start": "08:00", "window_end": "10:00",
         "lines": [order_line(base["lot"]["id"], 1, 10.00)]}, SALES_HEADERS)
    validate_error(next_day, ApiErrorId.ERR_CUTOFF_PASSED)

    same_day = api.create_sales_order(
        {"customer_id": base["customer"]["id"], "delivery_date": "2026-05-01",
         "window_start": "08:00", "window_end": "10:00",
         "lines": [order_line(base["lot"]["id"], 1, 10.00)]}, SALES_HEADERS)
    validate_error(same_day, ApiErrorId.ERR_CUTOFF_PASSED)


def test_shape_error_beats_not_found_on_order_create(api):
    """PRD §2.8: "The order, from first to last, is: authentication
    (`ERR_UNAUTHENTICATED`); authorization (`ERR_FORBIDDEN`); request shape and field
    types (`ERR_VALIDATION`); existence of path ids and body foreign keys, validated
    left-to-right with path parameters first (`ERR_NOT_FOUND`)"

    Design: Corner/validations/shape_error_beats_not_found_on_order_create
    """
    # Missing required `lines` AND a customer_id that resolves to nothing: shape
    # validation (earlier in the priority order) must win over existence.
    resp = api.create_sales_order(
        {"customer_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
         "delivery_date": "2026-05-02", "window_start": "08:00",
         "window_end": "10:00"}, SALES_HEADERS)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
