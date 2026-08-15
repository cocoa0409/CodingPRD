"""Usage standard endpoints (PRD 3.4): half-open windows, overlap rule, retire."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
    ERR_STANDARD_WINDOW_OVERLAP,
)
from middleware import authorized
from response import success_object
from routes.helpers import arg, get_one, list_response
from services.calc import recompute_consumption_flag
from services.core import new_record, serialize, touch
from util import parse_date, round4
from validate import (
    get_body, opt_date, req_date, req_decimal, req_str, require_fk,
    require_path_resource,
)

bp = Blueprint("standards", __name__)


@bp.post("/api/standards")
def create_standard():
    authorized(["AccountManager"])
    body = get_body()
    machine_id = req_str(body, "machine_id")
    product_id = req_str(body, "product_id")
    operation_name = req_str(body, "operation_name")
    qty = req_decimal(body, "standard_qty_per_part", gt=0)
    qty = round4(qty)
    effective_from = req_date(body, "effective_from")
    effective_to = opt_date(body, "effective_to")
    # Half-open window shape: effective_to strictly after effective_from when present.
    if effective_to is not None and parse_date(effective_to) <= parse_date(effective_from):
        raise_error(ERR_INVALID_REQUEST, "effective_to must be strictly after effective_from")
    # Priority 4: body FK existence in canonical order (machine, product).
    require_fk("machines", machine_id, "machine")
    require_fk("products", product_id, "product")
    # Priority 8: no half-open window overlap among ACTIVE standards of the same
    # (machine_id, product_id); adjacency (to == from) is allowed.
    new_from = parse_date(effective_from)
    new_to = parse_date(effective_to) if effective_to is not None else None
    for std in db["standards"].values():
        if std["machine_id"] != machine_id or std["product_id"] != product_id:
            continue
        if std["status"] != "ACTIVE":
            continue
        ex_from = parse_date(std["effective_from"])
        ex_to = parse_date(std["effective_to"]) if std["effective_to"] is not None else None
        overlaps = (ex_to is None or new_from < ex_to) and (new_to is None or ex_from < new_to)
        if overlaps:
            raise_error(
                ERR_STANDARD_WINDOW_OVERLAP,
                "window overlaps an ACTIVE standard for the same machine and product",
            )
    rec = new_record("standards", {
        "machine_id": machine_id,
        "product_id": product_id,
        "operation_name": operation_name,
        "standard_qty_per_part": qty,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "needs_review": False,
        "status": "ACTIVE",
    })
    return success_object(serialize(rec), status=201)


@bp.get("/api/standards/<sid>")
def get_standard(sid):
    return get_one("standards", sid, "standard")


@bp.get("/api/standards")
def list_standards():
    return list_response("standards", {
        "machine_id": arg("machine_id"),
        "product_id": arg("product_id"),
        "status": arg("status"),
    })


@bp.post("/api/standards/<sid>/retire")
def retire_standard(sid):
    authorized(["ProgramAdmin"])
    std = require_path_resource("standards", sid, "standard")
    if std["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE_TRANSITION, "only an ACTIVE standard can be retired")
    std["status"] = "RETIRED"
    touch(std)
    # Retirement may clear the machine's last needs_review: recompute the flag.
    machine = db["machines"].get(std["machine_id"])
    if machine is not None and recompute_consumption_flag(machine):
        touch(machine)
    return success_object(serialize(std))
