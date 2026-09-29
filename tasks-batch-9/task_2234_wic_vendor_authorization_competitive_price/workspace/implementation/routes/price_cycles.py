"""Price cycle endpoints (PRD §3.3, §3.4)."""

from flask import Blueprint

import config as C
import envelope
import models
import services
import validators
from auth import authenticate
from errors import ApiError
from routes.common import need
from store import db

bp = Blueprint("price_cycles", __name__)


@bp.post("/price-cycles")
def create_cycle():
    authenticate(C.ROLE_SUPERVISOR)
    payload = validators.body()
    cycle_code = validators.req_string(payload, "cycle_code")
    opens = validators.req_instant(payload, "submission_open_at")
    due = validators.req_instant(payload, "submission_due_at")

    for existing in db.price_cycles.values():
        if existing["cycle_code"] == cycle_code:
            raise ApiError("ERR_DUPLICATE_CYCLE_CODE")
    if not opens < due:
        raise ApiError("ERR_INVALID_CYCLE_WINDOW")
    for existing in db.price_cycles.values():
        if existing["status"] not in C.CYCLE_STATUSES:
            continue
        if opens < existing["submission_due_at"] and existing["submission_open_at"] < due:
            raise ApiError("ERR_CYCLE_WINDOW_OVERLAP")

    record = models.price_cycle(
        cycle_code=cycle_code, submission_open_at=opens, submission_due_at=due
    )
    db.price_cycles[record["id"]] = record
    return envelope.success(record, 201)


@bp.get("/price-cycles/<entity_id>")
def read_cycle(entity_id):
    authenticate(
        C.ROLE_ANALYST, C.ROLE_SUPERVISOR, C.ROLE_INVESTIGATOR, C.ROLE_VENDOR_OPERATOR
    )
    return envelope.success(need(db.price_cycles, entity_id, "ERR_PRICE_CYCLE_NOT_FOUND"))


@bp.post("/price-cycles/<entity_id>/close")
def close_cycle(entity_id):
    authenticate(C.ROLE_SUPERVISOR)
    cycle = need(db.price_cycles, entity_id, "ERR_PRICE_CYCLE_NOT_FOUND")
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_INVALID_CYCLE_STATE")
    services.close_cycle(cycle)
    return envelope.success(cycle)


@bp.post("/price-cycles/<entity_id>/publish-ceilings")
def publish_ceilings(entity_id):
    authenticate(C.ROLE_SUPERVISOR)
    cycle = need(db.price_cycles, entity_id, "ERR_PRICE_CYCLE_NOT_FOUND")
    if cycle["status"] != "CLOSED":
        raise ApiError("ERR_INVALID_CYCLE_STATE")
    return envelope.success(services.publish_cycle(cycle))
