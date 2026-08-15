"""Correspondent charges and fee assessments (PRD §3.7)."""

from flask import Blueprint

from db import STORE, base_entity, pub, touch
from errors import ERR_INVALID_STATE, ApiError
from listing import list_response
from middleware import ALL_INTERNAL, get_body, require_roles, validate_body
from response import ok
from services import audit, compute_fee, get_or_404, lazy_eval_wire

bp = Blueprint("money", __name__, url_prefix="/wire-ops")

_CHARGE_TYPES = {"OUR", "BENEFICIARY", "DEDUCTED_FROM_PRINCIPAL"}
_SOURCES = {"PROVISIONAL_ESTIMATE", "ACTUAL_ADVICE"}
_ESTIMATE_STATES = ("INITIATED", "CALLBACK_PENDING", "PENDING_APPROVAL", "REPAIR", "APPROVED")
_ADVICE_STATES = ("PENDING_APPROVAL", "REPAIR", "APPROVED", "EXECUTED", "RECALLED")


@bp.post("/wires/<wid>/charges")
def post_charge(wid):
    uid, role = require_roles("WireOperator", "WireOpsAdmin")
    wire = get_or_404(STORE.wires, wid, "wire")
    lazy_eval_wire(wire)
    data = get_body()
    validate_body(data, {
        "correspondent_name": ("str", True, None),
        "charge_type": ("str", True, _CHARGE_TYPES),
        "amount_cents": ("posint", True, None),
        "source": ("str", True, _SOURCES),
    })
    # Provenance is gated by the wire's stage.
    if data["source"] == "PROVISIONAL_ESTIMATE" and wire["status"] not in _ESTIMATE_STATES:
        raise ApiError(*ERR_INVALID_STATE,
                       "A provisional estimate may be posted only pre-execution.")
    if data["source"] == "ACTUAL_ADVICE" and wire["status"] not in _ADVICE_STATES:
        raise ApiError(*ERR_INVALID_STATE,
                       "An actual advice may be posted only from PENDING_APPROVAL onward.")
    charge = base_entity()
    charge.update({
        "wire_id": wid,
        "correspondent_name": data["correspondent_name"],
        "charge_type": data["charge_type"],
        "amount_cents": data["amount_cents"],
        "source": data["source"],
        "status": "POSTED",
    })
    STORE.charges[charge["id"]] = charge
    return ok(pub(charge), 201)


@bp.get("/wires/<wid>/charges")
def list_charges(wid):
    require_roles(*ALL_INTERNAL)
    wire = get_or_404(STORE.wires, wid, "wire")
    lazy_eval_wire(wire)
    items = [c for c in STORE.charges.values() if c["wire_id"] == wid]
    return list_response(items)


@bp.post("/wires/<wid>/fees/assess")
def assess_fee(wid):
    uid, role = require_roles("WireOperator", "WireOpsAdmin")
    wire = get_or_404(STORE.wires, wid, "wire")
    lazy_eval_wire(wire)
    data = get_body()
    validate_body(data, {"kind": ("str", True, {"PROVISIONAL", "FINAL"})})
    if data["kind"] == "PROVISIONAL" and wire["status"] not in _ESTIMATE_STATES:
        raise ApiError(*ERR_INVALID_STATE,
                       "PROVISIONAL assessment requires a pre-execution wire status.")
    if data["kind"] == "FINAL" and wire["status"] not in ("EXECUTED", "RECALLED"):
        raise ApiError(*ERR_INVALID_STATE,
                       "FINAL assessment requires an EXECUTED or RECALLED wire.")
    comp = compute_fee(wire, data["kind"])
    fee = base_entity()
    fee.update({
        "wire_id": wid,
        "base_fee_cents": comp["base_fee_cents"],
        "priority_fee_cents": comp["priority_fee_cents"],
        "beneficiary_share_cents": comp["beneficiary_share_cents"],
        "correspondent_share_cents": comp["correspondent_share_cents"],
        "total_fee_cents": comp["total_fee_cents"],
        "kind": data["kind"],
        "status": "OPEN",
    })
    STORE.fees[fee["id"]] = fee
    return ok(pub(fee), 201)


@bp.get("/wires/<wid>/fees")
def list_fees(wid):
    require_roles(*ALL_INTERNAL)
    wire = get_or_404(STORE.wires, wid, "wire")
    lazy_eval_wire(wire)
    items = [f for f in STORE.fees.values() if f["wire_id"] == wid]
    return list_response(items)


@bp.get("/fees/<fid>")
def get_fee(fid):
    require_roles(*ALL_INTERNAL)
    fee = get_or_404(STORE.fees, fid, "fee assessment")
    return ok(pub(fee))


@bp.post("/fees/<fid>/bill")
def bill_fee(fid):
    uid, role = require_roles("WireOperator")
    fee = get_or_404(STORE.fees, fid, "fee assessment")
    data = get_body()
    if data:
        raise ApiError("ERR_INVALID_REQUEST", 400, "This endpoint does not accept a request body.")
    if fee["status"] != "OPEN":
        raise ApiError(*ERR_INVALID_STATE, "Only an OPEN fee assessment can be billed.")
    wire = STORE.wires[fee["wire_id"]]
    lazy_eval_wire(wire)
    if wire["status"] not in ("EXECUTED", "RECALLED"):
        raise ApiError(*ERR_INVALID_STATE,
                       "Billing requires the linked wire to be EXECUTED or RECALLED.")
    fee["status"] = "BILLED"
    touch(fee)
    audit("fee.billed", "FeeAssessment", fid, fee["wire_id"],
          "status: OPEN -> BILLED", actor_user_id=uid, actor_role=role)
    return ok(pub(fee))


@bp.post("/fees/<fid>/waive")
def waive_fee(fid):
    uid, role = require_roles("WireOpsAdmin")
    fee = get_or_404(STORE.fees, fid, "fee assessment")
    data = get_body()
    if data:
        raise ApiError("ERR_INVALID_REQUEST", 400, "This endpoint does not accept a request body.")
    if fee["status"] != "OPEN":
        raise ApiError(*ERR_INVALID_STATE, "Only an OPEN fee assessment can be waived.")
    fee["status"] = "WAIVED"
    touch(fee)
    audit("fee.waived", "FeeAssessment", fid, fee["wire_id"],
          "status: OPEN -> WAIVED", actor_user_id=uid, actor_role=role)
    return ok(pub(fee))
