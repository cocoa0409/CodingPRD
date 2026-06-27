"""Insurance superbills (PRD §3.11)."""
from flask import Blueprint, request

import db
import helpers as h
import response
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_BILLABLE,
    ERR_UNAUTHORIZED,
)
from middleware import authenticate, require_role

bp = Blueprint("superbills", __name__)


def serialize(s):
    return h.public(s)


@bp.post("/practice/superbills")
def issue():
    caller = authenticate()
    require_role(caller, {"FrontDesk", "PracticeAdmin"})
    body = h.get_body()

    appointment_id = h.as_str(h.require(body, "appointment_id"), "appointment_id")
    appt = h.resolve(db.appointments, appointment_id)
    diagnosis_codes = h.require(body, "diagnosis_codes")
    if not isinstance(diagnosis_codes, list) or len(diagnosis_codes) < 1:
        raise ApiError(*ERR_INVALID_REQUEST, message="diagnosis_codes must have at least one code")
    cpt_code = h.as_str(h.require(body, "cpt_code"), "cpt_code")

    # superbill gate: PAID and payer not MEMBERSHIP
    if appt["settlement_status"] != "PAID" or appt["payer"] == "MEMBERSHIP":
        raise ApiError(*ERR_NOT_BILLABLE, message="not billable")

    ent = h.new_entity({
        "appointment_id": appointment_id,
        "client_id": appt["client_id"],
        "diagnosis_codes": list(diagnosis_codes),
        "cpt_code": cpt_code,
        "billable_amount_cents": appt["service_charge_cents"],
        "superbill_status": "ISSUED",
    })
    db.superbills[ent["id"]] = ent
    return response.success(serialize(ent), status=201)


@bp.get("/practice/superbills")
def list_superbills():
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk", "Client"})
    limit, offset = h.get_pagination()
    appointment_id = request.args.get("appointment_id")
    client_id = request.args.get("client_id")
    items = list(db.superbills.values())
    if appointment_id is not None:
        items = [s for s in items if s["appointment_id"] == appointment_id]
    if client_id is not None:
        items = [s for s in items if s["client_id"] == client_id]
    if caller.role == "Client":
        items = [s for s in items if s["client_id"] == caller.user_id]
    page, total = h.paginate(items, limit, offset)
    return response.list_success([serialize(s) for s in page], limit, offset, total)


@bp.get("/practice/superbills/<id>")
def get_superbill(id):
    caller = authenticate()
    require_role(caller, {"PracticeAdmin", "FrontDesk", "Client"})
    ent = h.resolve(db.superbills, id)
    if caller.role == "Client" and ent["client_id"] != caller.user_id:
        raise ApiError(*ERR_UNAUTHORIZED, message="not owner")
    return response.success(serialize(ent))


@bp.post("/practice/superbills/<id>/void")
def void_superbill(id):
    caller = authenticate()
    require_role(caller, {"FrontDesk", "PracticeAdmin"})
    ent = h.resolve(db.superbills, id)
    if ent["superbill_status"] != "ISSUED":
        raise ApiError(*ERR_INVALID_STATE, message="not ISSUED")
    ent["superbill_status"] = "VOID"
    h.touch(ent)
    return response.success(serialize(ent))
