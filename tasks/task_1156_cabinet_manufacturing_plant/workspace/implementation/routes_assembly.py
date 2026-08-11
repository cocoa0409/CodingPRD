"""Box assembly: sub-lots and line balancing (PRD §3.6)."""
from flask import Blueprint, request

from auth import require_any_role, require_roles
from domain import line_slotted_qty, reevaluate_order, sublots_of_line
from errors import api_error
from serializers import ser_sub_lot
from store import db, new_id, now, stamp, touch
from util import Body, paginate, respond_list, respond_object, sort_records

bp = Blueprint("assembly", __name__)


def _get_sub_lot(sub_lot_id):
    sub = db.sub_lots.get(sub_lot_id)
    if sub is None:
        raise api_error("ERR_SUB_LOT_NOT_FOUND", f"SubLot {sub_lot_id} not found")
    return sub


@bp.post("/kcma/sub-lots")
def create_sub_lot():
    require_roles({"ProductionPlanner"})
    body = Body(request.get_json(silent=True))
    order_line_id = body.req_str("order_line_id")
    assembly_line_id = body.req_str("assembly_line_id")
    scheduled_date = body.req_date("scheduled_date")
    start_minute = body.req_int("start_minute", min_value=0, range_error="ERR_INVALID_TIME_WINDOW")
    qty = body.req_int("qty")

    # priority 5: body FKs exist
    line = None
    if order_line_id is not None:
        line = db.order_lines.get(order_line_id)
        if line is None:
            raise api_error("ERR_ORDER_LINE_NOT_FOUND", f"OrderLine {order_line_id} not found")
    aline = None
    if assembly_line_id is not None:
        aline = db.assembly_lines.get(assembly_line_id)
        if aline is None:
            raise api_error("ERR_ASSEMBLY_LINE_NOT_FOUND", f"AssemblyLine {assembly_line_id} not found")

    # priority 6: the covered line's order must be SUBMITTED or IN_PRODUCTION
    if line is not None:
        order = db.orders[line["order_id"]]
        if order["status"] not in ("SUBMITTED", "IN_PRODUCTION"):
            raise api_error(
                "ERR_LINE_ORDER_NOT_RELEASED_TO_PRODUCTION",
                f"Order {order['id']} is not in SUBMITTED or IN_PRODUCTION",
            )

    # priority 8: assembly line must be active
    if aline is not None and not aline["active"]:
        raise api_error("ERR_ASSEMBLY_LINE_INACTIVE", f"AssemblyLine {aline['id']} is inactive")

    # priority 9: sub-lots cover BOX lines only
    if line is not None and line["line_type"] != "BOX":
        raise api_error("ERR_WRONG_LINE_TYPE", "Sub-lots require a BOX order line")

    # priority 11: temporal rules — half-open window overlap, aggregate
    # line-day capacity, then schedule date. Exact capacity ties are allowed.
    work_minutes = end_minute = None
    if qty is not None and aline is not None:
        work_minutes = qty * aline["standard_minutes_per_box"] + aline["setup_minutes_per_sub_lot"]
        if start_minute is not None:
            end_minute = start_minute + work_minutes
    if (
        aline is not None and scheduled_date is not None
        and start_minute is not None and 0 <= start_minute <= 1439
        and end_minute is not None
    ):
        day_load = 0
        for other in db.sub_lots.values():
            if (
                other["assembly_line_id"] == aline["id"]
                and other["scheduled_date"] == scheduled_date.isoformat()
                and other["status"] != "CANCELLED"
            ):
                # half-open overlap: adjacency (start == other.end or
                # end == other.start) is allowed
                if start_minute < other["end_minute"] and other["start_minute"] < end_minute:
                    raise api_error(
                        "ERR_LINE_WINDOW_OVERLAP",
                        "Sub-lot window overlaps another sub-lot on the same line and date",
                    )
                day_load += other["work_minutes"]
        if day_load + work_minutes > aline["capacity_minutes_per_day"]:
            raise api_error(
                "ERR_LINE_CAPACITY_EXCEEDED",
                "Aggregate line-day load exceeds capacity_minutes_per_day",
            )
    if scheduled_date is not None and scheduled_date < now().date():
        raise api_error("ERR_SCHEDULE_DATE_IN_PAST", "scheduled_date is before the current date")

    # priority 13: sub-lot qty may not exceed the line's unslotted remainder
    if line is not None and qty is not None and line["line_type"] == "BOX":
        if qty > line["qty"] - line_slotted_qty(line["id"]):
            raise api_error(
                "ERR_SUB_LOT_QTY_EXCEEDS_LINE",
                "Sub-lot qty exceeds the line's remaining unslotted quantity",
            )

    # priority 14: field-level sanity (incl. computed end beyond the day)
    if start_minute is not None and start_minute > 1439:
        body.add_error("ERR_INVALID_TIME_WINDOW", "start_minute must be within 0..1439")
    if qty is not None and qty <= 0:
        body.add_error("ERR_INVALID_QUANTITY", "qty must be > 0")
    if end_minute is not None and end_minute > 1440:
        body.add_error("ERR_INVALID_TIME_WINDOW", "computed end_minute exceeds minute 1440")
    body.raise_field_errors()

    sub = {
        "id": new_id(),
        "order_id": line["order_id"],
        "order_line_id": line["id"],
        "assembly_line_id": aline["id"],
        "scheduled_date": scheduled_date.isoformat(),
        "start_minute": start_minute,
        "qty": qty,
        "work_minutes": work_minutes,
        "end_minute": end_minute,
        "status": "SCHEDULED",
    }
    stamp(sub)
    db.sub_lots[sub["id"]] = sub
    if line["status"] == "QUOTED":
        line["status"] = "IN_PROGRESS"  # first sub-lot slots the line
        touch(line)
    reevaluate_order(db.orders[line["order_id"]])
    return respond_object(ser_sub_lot(sub), 201)


@bp.get("/kcma/sub-lots")
def list_sub_lots():
    require_any_role()
    records = list(db.sub_lots.values())
    order_id = request.args.get("order_id")
    if order_id is not None:
        records = [s for s in records if s["order_id"] == order_id]
    line_id = request.args.get("order_line_id")
    if line_id is not None:
        records = [s for s in records if s["order_line_id"] == line_id]
    aline_id = request.args.get("assembly_line_id")
    if aline_id is not None:
        records = [s for s in records if s["assembly_line_id"] == aline_id]
    page, total, limit, offset = paginate(sort_records(records))
    return respond_list([ser_sub_lot(s) for s in page], total, limit, offset)


@bp.get("/kcma/sub-lots/<subLotId>")
def get_sub_lot(subLotId):
    require_any_role()
    return respond_object(ser_sub_lot(_get_sub_lot(subLotId)), 200)


@bp.post("/kcma/sub-lots/<subLotId>/complete")
def complete_sub_lot(subLotId):
    require_roles({"ProductionPlanner"})
    sub = _get_sub_lot(subLotId)
    if sub["status"] != "SCHEDULED":
        raise api_error("ERR_SUB_LOT_NOT_COMPLETABLE", "Complete requires the sub-lot in SCHEDULED")
    sub["status"] = "COMPLETE"
    touch(sub)

    line = db.order_lines[sub["order_line_id"]]
    siblings = [s for s in sublots_of_line(line["id"]) if s["status"] != "CANCELLED"]
    if (
        line["status"] == "IN_PROGRESS"
        and line_slotted_qty(line["id"]) == line["qty"]
        and all(s["status"] == "COMPLETE" for s in siblings)
    ):
        line["status"] = "COMPLETED"
        touch(line)
    reevaluate_order(db.orders[sub["order_id"]])
    return respond_object(ser_sub_lot(sub), 200)
