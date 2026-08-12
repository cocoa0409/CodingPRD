"""Routes: cells, cell bookings, supply requisitions."""
from datetime import timedelta

from flask import Blueprint, request

from mill.common import (
    ALL_ROLES,
    ApiError,
    D,
    endpoint,
    get_body,
    list_response,
    new_rec,
    now_dt,
    now_iso,
    ok,
    parse_dt,
    pub,
    r2,
    req_enum,
    req_field,
    req_int,
    req_pos_num,
    touch,
)
from mill.logic import (
    OP_CELL_TYPE,
    OP_REQUIRED_LINE_STAGE,
    bookings_of_cell,
    lines_of,
    recompute_cell_hours,
)
from mill.store import store

bp = Blueprint("cells", __name__)

WRITE_PLANNER = ["ProductionPlanner"]
CELL_TYPES = ["CUTTING", "SEWING", "UPHOLSTERY"]
OPERATIONS = ["CUT", "SEW", "UPHOLSTER"]
SOURCE_TYPES = ["CONTAINER", "DOMESTIC"]
ACTIVE_BOOKING_STATES = ("BOOKED", "IN_PROGRESS")


def _find_cell(cid):
    rec = store.cells.get(cid)
    if not rec:
        raise ApiError("ERR_CELL_NOT_FOUND", 404, "Cell not found")
    return rec


def _find_booking(bid):
    rec = store.cell_bookings.get(bid)
    if not rec:
        raise ApiError("ERR_CELL_BOOKING_NOT_FOUND", 404, "CellBooking not found")
    return rec


# ---------------------------------------------------------------------------
# Cell
# ---------------------------------------------------------------------------


@bp.post("/mill/cells")
@endpoint(WRITE_PLANNER)
def create_cell():
    b = get_body()
    cell_code = req_field(b, "cell_code")
    cell_type = req_enum(b, "cell_type", CELL_TYPES)
    capacity_slots = b.get("capacity_slots", 1)
    if (
        isinstance(capacity_slots, bool)
        or not isinstance(capacity_slots, int)
        or capacity_slots < 1
    ):
        raise ApiError("ERR_INVALID_REQUEST", 400, "capacity_slots must be an integer >= 1")
    certifications = b.get("certifications") or []
    if not isinstance(certifications, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, "certifications must be an array")
    if any(c["cell_code"] == cell_code for c in store.cells.values()):
        raise ApiError("ERR_DUPLICATE_NATURAL_KEY", 409, f"cell_code {cell_code} already exists")
    rec = new_rec()
    rec.update(
        {
            "cell_code": cell_code,
            "cell_type": cell_type,
            "capacity_slots": capacity_slots,
            "certifications": certifications,
            "committed_hours": 0,
            "status": "ACTIVE",
        }
    )
    store.cells[rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.get("/mill/cells")
@endpoint(ALL_ROLES)
def list_cells():
    return list_response(list(store.cells.values()))


@bp.get("/mill/cells/<cid>")
@endpoint(ALL_ROLES)
def get_cell(cid):
    return ok(pub(_find_cell(cid)))


@bp.post("/mill/cells/<cid>/set-status")
@endpoint(WRITE_PLANNER)
def set_cell_status(cid):
    b = get_body()
    status = req_enum(b, "status", ["ACTIVE", "DOWN"])
    rec = _find_cell(cid)
    rec["status"] = status
    touch(rec)
    return ok(pub(rec))


# ---------------------------------------------------------------------------
# CellBooking
# ---------------------------------------------------------------------------


def _check_line_stage(line, operation):
    required = OP_REQUIRED_LINE_STAGE[operation]
    if line["status"] != required:
        raise ApiError(
            "ERR_LINE_STAGE_MISMATCH",
            409,
            f"Operation {operation} requires the line in {required}",
        )


@bp.post("/mill/cell-bookings")
@endpoint(WRITE_PLANNER)
def create_booking():
    b = get_body()
    cell_id = req_field(b, "cell_id")
    order_line_id = req_field(b, "order_line_id")
    operation = req_enum(b, "operation", OPERATIONS)
    start_raw = req_field(b, "start_at")
    end_raw = req_field(b, "end_at")
    start = parse_dt(start_raw)
    end = parse_dt(end_raw)
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST", 400, "end_at must be later than start_at")
    cell = store.cells.get(cell_id)
    if not cell:
        raise ApiError("ERR_CELL_NOT_FOUND", 404, "Cell not found")
    line = store.order_lines.get(order_line_id)
    if not line:
        raise ApiError("ERR_ORDER_LINE_NOT_FOUND", 404, "OrderLine not found")
    order = store.orders.get(line["order_id"])

    # State legality (level 5).
    if not order or order["status"] not in ("CONFIRMED", "IN_PRODUCTION"):
        raise ApiError(
            "ERR_ORDER_NOT_BOOKABLE",
            409,
            "Booking requires the order in CONFIRMED or IN_PRODUCTION",
        )
    _check_line_stage(line, operation)

    # Business safety (level 6): certifications first, then cell DOWN (PRD §2.8 order).
    if line["fabric_source"] == "COM" and "COM_HANDLING" not in cell["certifications"]:
        raise ApiError(
            "ERR_CELL_CERTIFICATION_MISSING",
            422,
            "Booking a COM line requires a cell with COM_HANDLING certification",
        )
    if cell["status"] == "DOWN":
        raise ApiError("ERR_CELL_DOWN", 422, "Cell is DOWN")

    # Business constraints (level 7).
    if cell["cell_type"] != OP_CELL_TYPE[operation]:
        raise ApiError(
            "ERR_CELL_TYPE_MISMATCH",
            422,
            f"Operation {operation} requires a {OP_CELL_TYPE[operation]} cell",
        )
    if operation == "CUT":
        model = store.product_models.get(line["model_id"])
        for code in (model["required_component_codes"] if model else []):
            received = any(
                r["order_line_id"] == line["id"]
                and r["component_code"] == code
                and r["status"] == "RECEIVED"
                for r in store.requisitions.values()
            )
            if not received:
                raise ApiError(
                    "ERR_COMPONENT_NOT_RECEIVED",
                    422,
                    f"Component {code} has no RECEIVED requisition for the line",
                )
    overlapping = [
        ob
        for ob in bookings_of_cell(cell["id"])
        if ob["status"] in ACTIVE_BOOKING_STATES
        and start < parse_dt(ob["end_at"])
        and parse_dt(ob["start_at"]) < end
    ]
    if cell["capacity_slots"] == 1:
        if overlapping:
            raise ApiError(
                "ERR_CELL_OVERLAP",
                409,
                "New booking overlaps an active booking on an exclusive cell",
            )
    elif len(overlapping) + 1 > cell["capacity_slots"]:
        raise ApiError(
            "ERR_CELL_CAPACITY_EXCEEDED",
            409,
            "Booking would exceed the cell's capacity_slots",
        )

    duration = r2(D(str((end - start).total_seconds())) / D("3600"))
    rec = new_rec()
    rec.update(
        {
            "cell_id": cell_id,
            "order_line_id": order_line_id,
            "operation": operation,
            "start_at": start_raw if isinstance(start_raw, str) else str(start_raw),
            "end_at": end_raw if isinstance(end_raw, str) else str(end_raw),
            "duration_hours": duration,
            "status": "BOOKED",
        }
    )
    store.cell_bookings[rec["id"]] = rec
    recompute_cell_hours(cell)
    return ok(pub(rec), 201)


@bp.get("/mill/cell-bookings")
@endpoint(ALL_ROLES)
def list_bookings():
    recs = list(store.cell_bookings.values())
    for param in ("cell_id", "order_line_id", "status"):
        v = request.args.get(param)
        if v:
            recs = [x for x in recs if x[param] == v]
    return list_response(recs)


@bp.get("/mill/cell-bookings/<bid>")
@endpoint(ALL_ROLES)
def get_booking(bid):
    return ok(pub(_find_booking(bid)))


@bp.post("/mill/cell-bookings/<bid>/start")
@endpoint(WRITE_PLANNER)
def start_booking(bid):
    booking = _find_booking(bid)
    if booking["status"] == "IN_PROGRESS":
        # Idempotent re-start: the booking is already running; return it unchanged.
        return ok(pub(booking))
    if booking["status"] != "BOOKED":
        raise ApiError("ERR_BOOKING_INVALID_STATE", 409, "Booking is not BOOKED")
    line = store.order_lines.get(booking["order_line_id"])
    order = store.orders.get(line["order_id"]) if line else None
    if not order or order["status"] not in ("CONFIRMED", "IN_PRODUCTION"):
        raise ApiError(
            "ERR_ORDER_NOT_BOOKABLE",
            409,
            "Starting a booking requires the order in CONFIRMED or IN_PRODUCTION",
        )
    _check_line_stage(line, booking["operation"])
    booking["status"] = "IN_PROGRESS"
    touch(booking)
    recompute_cell_hours(store.cells[booking["cell_id"]])
    # First IN_PROGRESS booking of any line moves the order to IN_PRODUCTION.
    if order["status"] == "CONFIRMED":
        order["status"] = "IN_PRODUCTION"
        touch(order)
    return ok(pub(booking))


@bp.post("/mill/cell-bookings/<bid>/complete")
@endpoint(WRITE_PLANNER)
def complete_booking(bid):
    booking = _find_booking(bid)
    if booking["status"] != "IN_PROGRESS":
        raise ApiError("ERR_BOOKING_INVALID_STATE", 409, "Booking is not IN_PROGRESS")
    booking["status"] = "COMPLETED"
    touch(booking)
    recompute_cell_hours(store.cells[booking["cell_id"]])
    line = store.order_lines.get(booking["order_line_id"])
    if line:
        if booking["operation"] == "SEW":
            line["status"] = "SEWN"
            touch(line)
        elif booking["operation"] == "UPHOLSTER":
            line["status"] = "UPHOLSTERED"
            touch(line)
            order = store.orders.get(line["order_id"])
            if order and order["status"] == "IN_PRODUCTION":
                if all(l["status"] == "UPHOLSTERED" for l in lines_of(order["id"])):
                    order["status"] = "QUALITY_REVIEW"
                    touch(order)
        # CUT completion does not advance the line; record-cut does.
    return ok(pub(booking))


@bp.post("/mill/cell-bookings/<bid>/release")
@endpoint(WRITE_PLANNER)
def release_booking(bid):
    booking = _find_booking(bid)
    if booking["status"] != "BOOKED":
        raise ApiError("ERR_BOOKING_INVALID_STATE", 409, "Booking is not BOOKED")
    booking["status"] = "RELEASED"
    touch(booking)
    recompute_cell_hours(store.cells[booking["cell_id"]])
    return ok(pub(booking))


# ---------------------------------------------------------------------------
# SupplyRequisition
# ---------------------------------------------------------------------------


@bp.post("/mill/supply-requisitions")
@endpoint(WRITE_PLANNER)
def create_requisition():
    b = get_body()
    order_line_id = req_field(b, "order_line_id")
    component_code = req_field(b, "component_code")
    quantity = req_int(b, "quantity", minimum=1)
    source_type = req_enum(b, "source_type", SOURCE_TYPES)
    line = store.order_lines.get(order_line_id)
    if not line:
        raise ApiError("ERR_ORDER_LINE_NOT_FOUND", 404, "OrderLine not found")
    order = store.orders.get(line["order_id"])
    if not order or order["status"] not in ("CONFIRMED", "MATERIAL_HOLD", "IN_PRODUCTION"):
        raise ApiError(
            "ERR_ORDER_NOT_BOOKABLE",
            409,
            "Requisition requires the order in CONFIRMED, MATERIAL_HOLD, or IN_PRODUCTION",
        )
    if source_type == "CONTAINER":
        ordered_quantity = -(-quantity // 50) * 50  # ceil to a multiple of the MOQ
        unit_cost_cents = 1200
        lead_days = 45
    else:
        ordered_quantity = quantity
        unit_cost_cents = 2000
        lead_days = 7
    confirmed_dt = parse_dt(order["confirmed_at"]) if order["confirmed_at"] else now_dt()
    available_date = (confirmed_dt.date() + timedelta(days=lead_days)).isoformat()
    rec = new_rec()
    rec.update(
        {
            "order_line_id": order_line_id,
            "component_code": component_code,
            "quantity": quantity,
            "source_type": source_type,
            "ordered_quantity": ordered_quantity,
            "unit_cost_cents": unit_cost_cents,
            "extended_cost_cents": ordered_quantity * unit_cost_cents,
            "available_date": available_date,
            "status": "OPEN",
            "received_at": None,
        }
    )
    store.requisitions[rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.get("/mill/supply-requisitions")
@endpoint(ALL_ROLES)
def list_requisitions():
    recs = list(store.requisitions.values())
    v = request.args.get("order_line_id")
    if v:
        recs = [r for r in recs if r["order_line_id"] == v]
    return list_response(recs)


@bp.get("/mill/supply-requisitions/<rid>")
@endpoint(ALL_ROLES)
def get_requisition(rid):
    rec = store.requisitions.get(rid)
    if not rec:
        raise ApiError("ERR_REQUISITION_NOT_FOUND", 404, "SupplyRequisition not found")
    return ok(pub(rec))


@bp.post("/mill/supply-requisitions/<rid>/place")
@endpoint(WRITE_PLANNER)
def place_requisition(rid):
    rec = store.requisitions.get(rid)
    if not rec:
        raise ApiError("ERR_REQUISITION_NOT_FOUND", 404, "SupplyRequisition not found")
    if rec["status"] != "OPEN":
        raise ApiError("ERR_REQUISITION_INVALID_STATE", 409, "Requisition is not OPEN")
    rec["status"] = "PLACED"
    touch(rec)
    return ok(pub(rec))


@bp.post("/mill/supply-requisitions/<rid>/receive")
@endpoint(WRITE_PLANNER)
def receive_requisition(rid):
    rec = store.requisitions.get(rid)
    if not rec:
        raise ApiError("ERR_REQUISITION_NOT_FOUND", 404, "SupplyRequisition not found")
    if rec["status"] != "PLACED":
        raise ApiError("ERR_REQUISITION_INVALID_STATE", 409, "Requisition is not PLACED")
    if now_dt().date() < parse_dt(rec["available_date"]).date():
        raise ApiError(
            "ERR_COMPONENT_NOT_YET_AVAILABLE",
            422,
            "Requisition cannot be received before its available_date",
        )
    rec["status"] = "RECEIVED"
    rec["received_at"] = now_iso()
    touch(rec)
    return ok(pub(rec))
