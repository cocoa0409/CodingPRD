"""Port calls: create/list/get plus the full lifecycle state machine
(delay, confirm-revised, arrive, begin-turnaround, depart, close, cancel).
PRD 3.2 / 3.3."""

from datetime import timedelta

from flask import Blueprint

import db
import services
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE,
    ERR_TURNAROUND_TOO_SHORT, ERR_WINDOW_NOT_CONTAINED, ERR_POSTURE_EMERGENCY,
    ERR_SCREENING_CAPACITY, ERR_CUSTOMS_NOT_CLEARED, ERR_OPEN_MISTAGS,
    ERR_OPEN_SERVICE_ORDERS, ERR_INVOICE_KIND_EXISTS,
)
from middleware import authenticate, ANY, scope_call
from response import success_obj, success_list
from util import (
    body_json, check_shape, exist_body_fks, pagination_params, paginate,
    apply_filters, parse_dt, dt_of,
)

bp = Blueprint("port_calls", __name__, url_prefix="/port-ops")

_CREATE_SPEC = {
    "terminal_id": {"type": "string", "required": True},
    "vessel_id": {"type": "string", "required": True},
    "voyage_ref": {"type": "string", "required": True},
    "scheduled_eta": {"type": "datetime", "required": True},
    "scheduled_etd": {"type": "datetime", "required": True},
    "booked_embark_pax": {"type": "integer", "required": True, "min": 0},
    "booked_debark_pax": {"type": "integer", "required": True, "min": 0},
}


def _get_call_or_404(call_id):
    call = db.get("port_calls", call_id)
    if call is None:
        raise ApiError(ERR_NOT_FOUND, 404, "port call not found")
    return call


def _check_turnaround(eta_iso, etd_iso):
    """Priority 12: etd - eta >= MIN_TURNAROUND_HOURS; exactly 6h allowed."""
    span = parse_dt(etd_iso, "scheduled_etd") - parse_dt(eta_iso, "scheduled_eta")
    if span < timedelta(hours=services.MIN_TURNAROUND_HOURS):
        raise ApiError(ERR_TURNAROUND_TOO_SHORT, 422,
                       "etd - eta must be at least 6 hours")


@bp.route("/port-calls", methods=["POST"])
def create_port_call():
    user_id, role = authenticate({"VesselAgent", "PortAuthorityAdmin"})
    body = body_json()
    exist_body_fks(body, {
        "terminal_id": ("terminals", "terminal"),
        "vessel_id": ("vessels", "vessel"),
    })
    # Priority 4: VesselAgent may open a call only for its own vessel.
    if role == "VesselAgent" and body.get("vessel_id") != user_id:
        from errors import ERR_VESSEL_SCOPE
        raise ApiError(ERR_VESSEL_SCOPE, 403,
                       "vessel agent may only open calls for its own vessel")
    check_shape(body, _CREATE_SPEC)
    _check_turnaround(body["scheduled_eta"], body["scheduled_etd"])
    # Priority 15: voyage_ref unique within the terminal.
    for other in db.all_of("port_calls"):
        if other["terminal_id"] == body["terminal_id"] and other["voyage_ref"] == body["voyage_ref"]:
            raise ApiError(ERR_VALIDATION, 400, "voyage_ref must be unique within the terminal")
    call = db.new_entity("port_calls", {
        "terminal_id": body["terminal_id"],
        "vessel_id": body["vessel_id"],
        "voyage_ref": body["voyage_ref"],
        "scheduled_eta": body["scheduled_eta"],
        "scheduled_etd": body["scheduled_etd"],
        "booked_embark_pax": body["booked_embark_pax"],
        "booked_debark_pax": body["booked_debark_pax"],
        "revised_eta": None,
        "revised_etd": None,
        "delay_reason": None,
        "actual_eta": None,
        "actual_etd": None,
        "status": "SCHEDULED",
    })
    return success_obj(services.serialize_call(call), code=201)


@bp.route("/port-calls", methods=["GET"])
def list_port_calls():
    user_id, role = authenticate(ANY)
    limit, offset = pagination_params()
    items = db.all_of("port_calls")
    if role == "VesselAgent":
        items = [c for c in items if c["vessel_id"] == user_id]
    items = apply_filters(items, ["terminal_id", "vessel_id", "status"])
    page, total, has_more = paginate([services.serialize_call(c) for c in items], limit, offset)
    return success_list(page, limit, offset, total, has_more)


@bp.route("/port-calls/<call_id>", methods=["GET"])
def get_port_call(call_id):
    user_id, role = authenticate(ANY)
    call = _get_call_or_404(call_id)
    scope_call(user_id, role, call)
    return success_obj(services.serialize_call(call))


@bp.route("/port-calls/<call_id>/delay", methods=["POST"])
def delay(call_id):
    user_id, role = authenticate({"VesselAgent"})
    call = _get_call_or_404(call_id)
    scope_call(user_id, role, call)
    body = body_json()
    check_shape(body, {
        "revised_eta": {"type": "datetime", "required": True},
        "revised_etd": {"type": "datetime", "required": True},
        "reason": {"type": "string", "required": True},
    })
    if call["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "delay requires status SCHEDULED")
    _check_turnaround(body["revised_eta"], body["revised_etd"])
    call["revised_eta"] = body["revised_eta"]
    call["revised_etd"] = body["revised_etd"]
    call["delay_reason"] = body["reason"]
    call["status"] = "DELAYED"
    db.touch(call)
    return success_obj(services.serialize_call(call))


@bp.route("/port-calls/<call_id>/confirm-revised", methods=["POST"])
def confirm_revised(call_id):
    authenticate({"Harbormaster"})
    call = _get_call_or_404(call_id)
    if call["status"] != "DELAYED":
        raise ApiError(ERR_INVALID_STATE, 409, "confirm-revised requires status DELAYED")
    services.cascade_confirm_revised(call)
    call["status"] = "SCHEDULED"
    db.touch(call)
    return success_obj(services.serialize_call(call))


@bp.route("/port-calls/<call_id>/arrive", methods=["POST"])
def arrive(call_id):
    authenticate({"Harbormaster"})
    call = _get_call_or_404(call_id)
    body = body_json()
    check_shape(body, {"actual_eta": {"type": "datetime", "required": True}})
    if call["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "arrive requires status SCHEDULED")
    confirmed = next(
        (a for a in services.assignments_of_call(call["id"]) if a["status"] == "CONFIRMED"),
        None,
    )
    if confirmed is None:
        raise ApiError(ERR_INVALID_STATE, 409, "no CONFIRMED berth assignment for this call")
    actual_eta = parse_dt(body["actual_eta"], "actual_eta")
    # Arrival containment is inclusive at both window ends (PRD 3.3).
    if not (dt_of(confirmed, "window_start") <= actual_eta <= dt_of(confirmed, "window_end")):
        raise ApiError(ERR_WINDOW_NOT_CONTAINED, 422,
                       "actual_eta is outside the CONFIRMED assignment window")
    call["actual_eta"] = body["actual_eta"]
    call["status"] = "ARRIVED"
    confirmed["status"] = "ACTIVE"
    db.touch(confirmed)
    db.touch(call)
    return success_obj(services.serialize_call(call))


@bp.route("/port-calls/<call_id>/begin-turnaround", methods=["POST"])
def begin_turnaround(call_id):
    authenticate({"TerminalOperator"})
    call = _get_call_or_404(call_id)
    if call["status"] != "ARRIVED":
        raise ApiError(ERR_INVALID_STATE, 409, "begin-turnaround requires status ARRIVED")
    term = services.terminal_of_call(call)
    req = services.screening_requirement(term, call, "PROJECTION")
    if not req["satisfied"]:
        raise ApiError(ERR_SCREENING_CAPACITY, 409,
                       "assigned screening officers below the requirement")
    call["status"] = "TURNAROUND"
    db.touch(call)
    return success_obj(services.serialize_call(call))


@bp.route("/port-calls/<call_id>/depart", methods=["POST"])
def depart(call_id):
    authenticate({"Harbormaster"})
    call = _get_call_or_404(call_id)
    body = body_json()
    check_shape(body, {"actual_etd": {"type": "datetime", "required": True}})
    if call["status"] != "TURNAROUND":
        raise ApiError(ERR_INVALID_STATE, 409, "depart requires status TURNAROUND")
    # Priority 9: posture gate.
    term = services.terminal_of_call(call)
    posture, _a, _o, _f = services.posture_of(term)
    if posture == "EMERGENCY":
        raise ApiError(ERR_POSTURE_EMERGENCY, 409,
                       "terminal posture is EMERGENCY; departure is gated")
    # Priority 21: customs coordination.
    case = services.customs_case_of(call["id"])
    if case is None or case["status"] != "CLEARED":
        raise ApiError(ERR_CUSTOMS_NOT_CLEARED, 409,
                       "the call's customs case is not CLEARED")
    # Priority 22: departure completeness.
    for bag in services.bags_of_call(call["id"]):
        if bag["status"] in ("MISTAGGED", "RECOVERED"):
            raise ApiError(ERR_OPEN_MISTAGS, 409,
                           "bags of this call remain MISTAGGED or RECOVERED")
    for so in services.orders_of_call(call["id"]):
        if so["status"] not in ("COMPLETED", "REJECTED", "CANCELLED"):
            raise ApiError(ERR_OPEN_SERVICE_ORDERS, 409,
                           "service orders of this call are not all terminal")
    call["actual_etd"] = body["actual_etd"]
    services.cascade_depart(call)
    call["status"] = "DEPARTED"
    db.touch(call)
    return success_obj(services.serialize_call(call))


@bp.route("/port-calls/<call_id>/close", methods=["POST"])
def close(call_id):
    authenticate({"BillingClerk"})
    call = _get_call_or_404(call_id)
    if call["status"] != "DEPARTED":
        raise ApiError(ERR_INVALID_STATE, 409, "close requires status DEPARTED")
    if services.final_invoice_of(call["id"]) is not None:
        raise ApiError(ERR_INVOICE_KIND_EXISTS, 409,
                       "a FINAL invoice already exists for this call")
    dockage, tax, service, gross = services.compute_invoice_fields(call, "FINAL")
    db.new_entity("invoices", {
        "port_call_id": call["id"],
        "kind": "FINAL",
        "status": "DRAFT",
        "dockage_fee_cents": dockage,
        "head_tax_cents": tax,
        "service_fee_cents": service,
        "adjustments_total_cents": 0,
        "gross_cents": gross,
        "total_cents": gross,
        "payment_cents": None,
        "dispute_reason": None,
    })
    call["status"] = "CLOSED"
    db.touch(call)
    return success_obj(services.serialize_call(call))


@bp.route("/port-calls/<call_id>/cancel", methods=["POST"])
def cancel(call_id):
    user_id, role = authenticate({"VesselAgent", "Harbormaster"})
    call = _get_call_or_404(call_id)
    scope_call(user_id, role, call)
    body = body_json()
    check_shape(body, {"reason": {"type": "string", "required": False}})
    if call["status"] not in ("SCHEDULED", "DELAYED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "cancel requires status SCHEDULED or DELAYED")
    services.cascade_cancel(call)
    call["status"] = "CANCELLED"
    db.touch(call)
    return success_obj(services.serialize_call(call))
