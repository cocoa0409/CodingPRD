"""DeliveryTruck endpoints (PRD §3.3)."""
from flask import Blueprint

from db import DB, LOCK
from middleware import require_auth
from services.common import new_record, require_body, req_str, req_int, get_or_404
from .helpers import get_json_body, list_response, single_response

bp = Blueprint("delivery_trucks", __name__)


@bp.post("/rental-yard/delivery-trucks")
def create_delivery_truck():
    require_auth({"YardManager"})
    body = require_body(get_json_body())
    name = req_str(body, "name", 1, 60)
    buffer_minutes = req_int(body, "buffer_minutes", 0)

    with LOCK:
        rec = new_record({
            "name": name,
            "buffer_minutes": buffer_minutes,
        })
        DB.delivery_trucks[rec["id"]] = rec
    return single_response(rec, 201)


@bp.get("/rental-yard/delivery-trucks/<rid>")
def get_delivery_truck(rid):
    rec = get_or_404(DB.delivery_trucks, rid)
    return single_response(rec)


@bp.get("/rental-yard/delivery-trucks")
def list_delivery_trucks():
    return list_response(DB.delivery_trucks.values())
