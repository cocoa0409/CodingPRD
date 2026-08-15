from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

from db import store, fmt_dt, parse_dt
from errors import ApiError
from helpers import (
    base_fields,
    get_booking_or_404,
    get_cell_or_404,
    get_wo_or_404,
    list_response,
    pub,
    touch,
)
from middleware import ALL_ROLES, get_json_body, require_roles, validate_body
from response import ok

bp = Blueprint("test_cells", __name__, url_prefix="/mro")


@bp.route("/test-cells", methods=["POST"])
@require_roles("ShopManager")
def create_test_cell():
    body = validate_body(
        get_json_body(),
        {
            "name": ("str", True),
            "supported_ata_chapters": ("array_str", True),
            "hourly_rate_cents": ("int", True),
        },
    )
    if any(c["name"] == body["name"] for c in store.test_cells.values()):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Test cell name already exists")
    c = dict(base_fields())
    c.update(
        {
            "name": body["name"],
            "supported_ata_chapters": body["supported_ata_chapters"],
            "hourly_rate_cents": body["hourly_rate_cents"],
        }
    )
    store.test_cells[c["id"]] = c
    return ok(pub(c), 201)


@bp.route("/test-cells/<testCellId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_test_cell(testCellId):
    return ok(pub(get_cell_or_404(testCellId)))


@bp.route("/test-cells/<testCellId>/bookings", methods=["POST"])
@require_roles("CustomerServiceRep")
def create_booking(testCellId):
    cell = get_cell_or_404(testCellId)
    body = validate_body(
        get_json_body(),
        {
            "work_order_id": ("str", True),
            "start_time": ("datetime", True),
            "end_time": ("datetime", True),
        },
    )
    wo = get_wo_or_404(body["work_order_id"])
    # Order: from-state, then window overlap (temporal), then ATA capability (constraint).
    if wo["status"] != "READY_FOR_TEST":
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE", 409, "Work order not in READY_FOR_TEST")
    start = parse_dt(body["start_time"])
    end = parse_dt(body["end_time"])
    for other in store.bookings.values():
        if other["test_cell_id"] != cell["id"] or other["status"] != "BOOKED":
            continue
        o_start = parse_dt(other["start_time"])
        o_end = parse_dt(other["end_time"])
        # Half-open [start, end): adjacency allowed; overlap iff start < o_end and o_start < end.
        if start < o_end and o_start < end:
            raise ApiError(
                "ERR_TEST_CELL_OVERLAP", 409, "Window overlaps an existing BOOKED window"
            )
    unit = store.units[wo["unit_id"]]
    part = store.parts[unit["part_id"]]
    if part["ata_chapter"] not in cell["supported_ata_chapters"]:
        raise ApiError(
            "ERR_CELL_ATA_UNSUPPORTED", 422, "Cell does not support the part's ATA chapter"
        )
    delta = end - start
    micro = Decimal(delta.days * 86400 + delta.seconds) * Decimal(10**6) + Decimal(delta.microseconds)
    duration_hours = micro / Decimal(3600 * 10**6)
    fee = int(
        (duration_hours * Decimal(cell["hourly_rate_cents"])).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    b = dict(base_fields())
    b.update(
        {
            "test_cell_id": cell["id"],
            "work_order_id": wo["id"],
            "start_time": fmt_dt(start),
            "end_time": fmt_dt(end),
            "status": "BOOKED",
            "fee_cents": fee,
        }
    )
    store.bookings[b["id"]] = b
    return ok(pub(b), 201)


@bp.route("/test-cells/<testCellId>/bookings", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_cell_bookings(testCellId):
    cell = get_cell_or_404(testCellId)
    return list_response([b for b in store.bookings.values() if b["test_cell_id"] == cell["id"]])


@bp.route("/work-orders/<workOrderId>/bookings", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_wo_bookings(workOrderId):
    wo = get_wo_or_404(workOrderId)
    return list_response([b for b in store.bookings.values() if b["work_order_id"] == wo["id"]])


@bp.route("/test-cell-bookings/<bookingId>/cancel", methods=["POST"])
@require_roles("CustomerServiceRep")
def cancel_booking(bookingId):
    b = get_booking_or_404(bookingId)
    if b["status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", 409, "Booking is not BOOKED")
    b["status"] = "CANCELLED"
    touch(b)
    return ok(pub(b))
