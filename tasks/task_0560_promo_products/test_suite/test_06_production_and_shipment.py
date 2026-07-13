"""Shop-floor scheduling, station overlap, QC spoilage tolerance, and final reconciliation."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_shipment_payload, schedule_payload, qc_payload,
    setup_in_production_issued_po, setup_station_double_book,
    setup_qc_hold_line, setup_confirmed_order, setup_completed_line,
)

AM = TEST_USERS["account_manager_headers"]
PM = TEST_USERS["production_manager_headers"]


# ---- queue A: schedule requires RECEIVED purchase order ------------------

def test_schedule_line_with_unreceived_po_rejected(api):
    """PRD 3.7: "The line's active (non-cancelled) purchase order must have reached
    `RECEIVED`, else `ERR_PO_NOT_RECEIVED` — blanks must be in hand before a press is
    booked."

    Design: Difficulty/cross_entity_state_dependency/schedule_requires_line_purchase_order_received
    """
    ctx = setup_in_production_issued_po()
    resp = api.schedule_line(
        ctx["line_id"],
        schedule_payload(ctx["station_id"], "2026-05-10T09:00:00Z", "2026-05-10T12:00:00Z"),
        PM)
    validate_error(resp, ApiErrorId.ERR_PO_NOT_RECEIVED)


def test_schedule_blocked_by_unreceived_po_leaves_line_confirmed(api):
    """PRD 3.7: "The line's active (non-cancelled) purchase order must have reached
    `RECEIVED`, else `ERR_PO_NOT_RECEIVED` — blanks must be in hand before a press is
    booked."
    PRD 3.7: "Scheduling a line assigns it a station and a production window,
    advancing the line's status from `CONFIRMED` to `SCHEDULED`."

    Design: Difficulty/cross_entity_state_dependency/schedule_requires_line_purchase_order_received
    """
    ctx = setup_in_production_issued_po()
    api.schedule_line(
        ctx["line_id"],
        schedule_payload(ctx["station_id"], "2026-05-10T09:00:00Z", "2026-05-10T12:00:00Z"),
        PM)
    line = validate_success(api.get_line(ctx["line_id"], AM))
    assert line["status"] == "CONFIRMED"


# ---- queue A: station half-open overlap ----------------------------------

def test_station_double_booking_overlap_rejected(api):
    """PRD 3.7: "treating each window as the half-open interval [`scheduled_start`,
    `scheduled_end`), two windows overlap when this line's start is before the other's
    end and the other's start is before this line's end. Adjacency — where one
    window's end equals the next window's start — is permitted and is not an overlap.
    If the proposed window overlaps any other non-cancelled line already assigned to
    that `station_id`, the schedule is rejected with `ERR_STATION_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/station_double_booking_halfopen_overlap
    """
    ctx = setup_station_double_book()
    resp = api.schedule_line(
        ctx["line2_id"],
        schedule_payload(ctx["station_id"], "2026-05-10T11:00:00Z", "2026-05-10T13:00:00Z"),
        PM)
    validate_error(resp, ApiErrorId.ERR_STATION_DOUBLE_BOOKED)


def test_station_double_booking_rejection_leaves_line_confirmed(api):
    """PRD 3.7: "If the proposed window overlaps any other non-cancelled line already
    assigned to that `station_id`, the schedule is rejected with
    `ERR_STATION_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/station_double_booking_halfopen_overlap
    """
    ctx = setup_station_double_book()
    api.schedule_line(
        ctx["line2_id"],
        schedule_payload(ctx["station_id"], "2026-05-10T11:00:00Z", "2026-05-10T13:00:00Z"),
        PM)
    line2 = validate_success(api.get_line(ctx["line2_id"], AM))
    assert line2["status"] == "CONFIRMED"


# ---- queue A: QC spoilage tolerance underrun boundary --------------------

def test_qc_good_below_tolerance_band_rejected(api):
    """PRD 3.7: "Using the ordered quantity as the reference, the minimum acceptable
    good count is the quantity minus the floor of the quantity times 5 percent, and
    the maximum acceptable good count is the quantity plus the floor of the quantity
    times 5 percent; the `good_qty` must be at least the minimum and at most the
    maximum, both bounds inclusive, else the pass is rejected with
    `ERR_SPOILAGE_OUT_OF_TOLERANCE`."

    Design: Difficulty/boundary_precision_check/qc_spoilage_tolerance_boundary_rejects_underrun
    """
    ctx = setup_qc_hold_line(produced_qty=200, spoiled_qty=11)
    resp = api.qc_line(ctx["line_id"], qc_payload("PASS"), PM)
    validate_error(resp, ApiErrorId.ERR_SPOILAGE_OUT_OF_TOLERANCE)


def test_qc_rejection_leaves_line_in_qc_hold_with_good_qty(api):
    """PRD 3.7: "Completing the run advances the line from `PRINTING` to `QC_HOLD` and
    records the run outcome: the request supplies `produced_qty` and `spoiled_qty`, the
    spoiled count must satisfy at least zero and at most the produced count, else
    `ERR_PRODUCED_QTY_INVALID`, and the line's `good_qty` is set to `produced_qty` minus
    `spoiled_qty`."

    Design: Difficulty/boundary_precision_check/qc_spoilage_tolerance_boundary_rejects_underrun
    """
    ctx = setup_qc_hold_line(produced_qty=200, spoiled_qty=11)
    api.qc_line(ctx["line_id"], qc_payload("PASS"), PM)
    line = validate_success(api.get_line(ctx["line_id"], AM))
    assert line["status"] == "QC_HOLD"
    assert line["good_qty"] == 189, "200 produced - 11 spoiled"


# ---- corner: start-print before schedule ---------------------------------

def test_start_print_before_schedule_rejected(api):
    """PRD 3.7: "Starting the print advances the line from `SCHEDULED` to `PRINTING`; a
    line not in `SCHEDULED` yields `ERR_LINE_INVALID_STATE`."

    Design: Corner/state_machines/start_print_before_schedule_returns_invalid_state
    """
    ctx = setup_confirmed_order()
    resp = api.start_print(ctx["line_id"], PM)
    validate_error(resp, ApiErrorId.ERR_LINE_INVALID_STATE)
    line = validate_success(api.get_line(ctx["line_id"], AM))
    assert line["status"] == "CONFIRMED"


# ---- queue A: quoted vs final total divergence at shipment ---------------

def test_final_total_computed_from_actual_good_qty_at_shipment(api):
    """PRD 3.8: "The `final_subtotal_cents` is the sum of `final_line_subtotal_cents` —
    each based on actual `good_qty` — over the non-cancelled lines. The `final_rush_cents`
    is the rush surcharge applied to that final subtotal, computed the same way as at
    quote: when `is_rush` is true, 20 percent of the final subtotal rounded half-up
    exactly once after summing, else 0. The `final_total_cents` is the final subtotal
    plus the final rush."

    Design: Difficulty/dual_variant_calc/order_quote_vs_final_total
    """
    ctx = setup_completed_line(produced_qty=205, spoiled_qty=10)
    validate_success(api.create_shipment(create_shipment_payload(ctx["order_id"]), PM), 201)
    order = validate_success(api.get_order(ctx["order_id"], AM))
    assert order["final_total_cents"] == 118405, (
        f"579*195 goods + 5500 setup, got {order['final_total_cents']}")


def test_final_total_diverges_from_quoted_total(api):
    """PRD 3.8: "Because good quantities can differ from ordered quantities within
    the spoilage band, these final figures may differ from the quoted ones."
    PRD 3.5: "The `quoted_total_cents` is the quoted subtotal plus the quoted rush."

    Design: Difficulty/dual_variant_calc/order_quote_vs_final_total
    """
    ctx = setup_completed_line(produced_qty=205, spoiled_qty=10)
    validate_success(api.create_shipment(create_shipment_payload(ctx["order_id"]), PM), 201)
    order = validate_success(api.get_order(ctx["order_id"], AM))
    assert order["quoted_total_cents"] == 121300
    assert order["final_total_cents"] != order["quoted_total_cents"], (
        "195 good units vs 200 ordered must make final diverge from quoted")
