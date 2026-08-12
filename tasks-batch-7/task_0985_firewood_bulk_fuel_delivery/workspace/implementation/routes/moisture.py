"""Moisture reading endpoints (PRD §3.7)."""

from datetime import datetime, timedelta

from flask import Blueprint

import errors
from clock import clock
from db import db, new_id
from middleware import require_roles
from response import success_list, success_object
from services.domain import serialize_moisture_reading
from services.pricing import compute_reading_pass
from util import get_json_body, now_iso, paginate, parse_pagination, require_number

bp = Blueprint("moisture", __name__)


def _get_line_or_404(lid):
    l = db.order_lines.get(lid)
    if not l:
        raise errors.not_found(f"OrderLine {lid} not found")
    return l


@bp.post("/api/v1/order-lines/<lid>/moisture-readings")
def record_moisture_reading(lid):
    auth = require_roles("Driver")
    line = _get_line_or_404(lid)
    body = get_json_body()
    moisture_pct = require_number(body, "moisture_pct")
    if moisture_pct < 0.0 or moisture_pct > 100.0:
        raise errors.validation("moisture_pct must be within [0.0, 100.0]")

    order = db.orders.get(line["order_id"])

    # Self-override guard (priority 7): a Driver may not record a reading on
    # their own previously-failed delivery within one logical hour.
    if order and order.get("_last_failure"):
        lf = order["_last_failure"]
        if lf.get("driver_id") == auth.user_id:
            failed_at = datetime.fromisoformat(lf["at"].replace("Z", "+00:00"))
            if clock.now() - failed_at < timedelta(hours=1):
                raise errors.self_override()

    product = db.products.get(line["product_id"])
    reading_pass = compute_reading_pass(moisture_pct, product) if product else False

    ts = now_iso()
    rid = new_id()
    reading = {
        "id": rid,
        "created_at": ts,
        "order_line_id": lid,
        "recorded_by_user_id": auth.user_id,
        "moisture_pct": moisture_pct,
        "reading_pass": reading_pass,
        "recorded_at": clock.now_iso(),
    }
    db.moisture_readings[rid] = reading
    # Link accepted reading back onto the line
    line["moisture_reading_id"] = rid
    line["updated_at"] = now_iso()
    line["version"] = line.get("version", 1) + 1
    return success_object(serialize_moisture_reading(reading), status=201)


@bp.get("/api/v1/order-lines/<lid>/moisture-readings")
def list_moisture_readings(lid):
    auth = require_roles("Driver", "CustomerService", "OperationsManager", "Customer")
    line = _get_line_or_404(lid)
    if auth.is_customer():
        order = db.orders.get(line["order_id"])
        if not order or order["customer_id"] != auth.user_id:
            raise errors.unauthorized()
    limit, offset = parse_pagination()
    items = [r for r in db.moisture_readings.values() if r["order_line_id"] == lid]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_moisture_reading(r) for r in page], total, limit, offset)
