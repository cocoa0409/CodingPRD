"""Handlers and certifications (PRD §3.3)."""
from flask import Blueprint, request

from db import store
from errors import raise_err, ERR_HANDLER_NOT_FOUND
from middleware import require
from response import ok
from serializers import ser_handler, ser_staff_assignment
from util import body_json, new_common, paginate, v_str, v_str_array

bp = Blueprint("handlers", __name__)

CERTIFICATIONS = {"REPTILE_CERTIFIED", "PONY_RIDE_CERTIFIED", "FIRST_AID"}
HANDLER_STATUSES = {"ACTIVE", "INACTIVE"}


def get_handler_or_404(handler_id):
    handler = store.handlers.get(handler_id)
    if handler is None:
        raise_err(ERR_HANDLER_NOT_FOUND, "Handler not found")
    return handler


@bp.post("/petting-zoo/handlers")
def create_handler():
    require({"Operator"})
    body = body_json()
    handler = new_common()
    handler.update({
        "name": v_str(body, "name"),
        "certifications": v_str_array(body, "certifications", allowed=CERTIFICATIONS),
        "status": "ACTIVE",
        "scheduled_minutes_total": 0,
    })
    store.handlers[handler["id"]] = handler
    return ok(ser_handler(handler), status=201)


@bp.get("/petting-zoo/handlers")
def list_handlers():
    require({"Coordinator", "Operator"})
    handlers = list(store.handlers.values())
    status = request.args.get("status")
    if status is not None:
        handlers = [h for h in handlers if h["status"] == status]
    data, meta = paginate(handlers, ser_handler)
    return ok(data, pagination=meta)


@bp.get("/petting-zoo/handlers/<handler_id>")
def get_handler(handler_id):
    require({"Coordinator", "Operator"})
    return ok(ser_handler(get_handler_or_404(handler_id)))


@bp.get("/petting-zoo/handlers/<handler_id>/staff-assignments")
def list_handler_assignments(handler_id):
    require({"Coordinator", "Operator"})
    get_handler_or_404(handler_id)
    assignments = [s for s in store.staff_assignments.values() if s["handler_id"] == handler_id]
    data, meta = paginate(assignments, ser_staff_assignment)
    return ok(data, pagination=meta)
