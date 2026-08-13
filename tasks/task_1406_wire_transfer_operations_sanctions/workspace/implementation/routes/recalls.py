"""Recall / return negotiation with the beneficiary bank (PRD §3.9)."""

from datetime import timedelta

from flask import Blueprint, request

from db import STORE, base_entity, iso, now, parse_dt, pub, touch
from errors import (
    ERR_INVALID_STATE,
    ERR_RECALL_ALREADY_RESOLVED,
    ERR_RECALL_AMOUNT_EXCEEDS,
    ERR_RECALL_EXPIRED,
    ERR_RECALL_IN_PROGRESS,
    ERR_RECALL_NOT_RETURNED,
    ApiError,
)
from listing import list_response
from middleware import RECALL_READ, get_body, require_fk, require_roles, validate_body
from response import ok
from services import audit, get_or_404, lazy_eval_recall, lazy_eval_wire

bp = Blueprint("recalls", __name__, url_prefix="/wire-ops")

_REASONS = {"DUPLICATE", "FRAUD", "ERROR_AMOUNT", "ERROR_BENEFICIARY"}
_RESPONSES = {"FUNDS_RETURNED", "FUNDS_DECLINED"}
_TERMINAL = ("COMPLETED", "DECLINED", "EXPIRED")


def _get_recall(rid):
    rec = get_or_404(STORE.recalls, rid, "recall")
    lazy_eval_recall(rec)
    return rec


@bp.post("/recalls")
def create_recall():
    uid, role = require_roles("WireOperator")
    data = get_body()
    require_fk(data, "wire_id", STORE.wires, "wire")
    validate_body(data, {
        "wire_id": ("str", True, None),
        "reason": ("str", True, _REASONS),
        "amount_to_recall_cents": ("posint", True, None),
    })
    wire = STORE.wires[data["wire_id"]]
    lazy_eval_wire(wire)
    if wire["status"] != "EXECUTED":
        raise ApiError(*ERR_INVALID_STATE, "A recall may be opened only against an EXECUTED wire.")
    if data["amount_to_recall_cents"] > wire["amount_cents"]:
        raise ApiError(*ERR_RECALL_AMOUNT_EXCEEDS,
                       "amount_to_recall_cents must be > 0 and <= wire.amount_cents.")
    for r in STORE.recalls.values():
        if r["wire_id"] == wire["id"] and r["status"] not in _TERMINAL:
            raise ApiError(*ERR_RECALL_IN_PROGRESS,
                           "A non-terminal recall already exists for this wire.")
    rec = base_entity()
    rec.update({
        "wire_id": wire["id"],
        "reason": data["reason"],
        "amount_to_recall_cents": data["amount_to_recall_cents"],
        "status": "REQUESTED",
        "beneficiary_bank_response": "NONE",
        "response_due_at": None,
        "responded_at": None,
    })
    STORE.recalls[rec["id"]] = rec
    return ok(pub(rec), 201)


@bp.get("/recalls")
def list_recalls():
    require_roles(*RECALL_READ)
    for r in list(STORE.recalls.values()):
        lazy_eval_recall(r)
    items = list(STORE.recalls.values())
    wire_id = request.args.get("wire_id")
    status = request.args.get("status")
    if wire_id is not None:
        items = [r for r in items if r["wire_id"] == wire_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_response(items)


@bp.get("/recalls/<rid>")
def get_recall(rid):
    require_roles(*RECALL_READ)
    rec = _get_recall(rid)
    return ok(pub(rec))


@bp.post("/recalls/<rid>/send")
def send_recall(rid):
    uid, role = require_roles("WireOperator")
    rec = _get_recall(rid)
    data = get_body()
    if data:
        raise ApiError("ERR_INVALID_REQUEST", 400, "This endpoint does not accept a request body.")
    if rec["status"] != "REQUESTED":
        raise ApiError(*ERR_INVALID_STATE, "Only a REQUESTED recall can be dispatched.")
    rec["status"] = "SENT_TO_BENEFICIARY_BANK"
    rec["response_due_at"] = iso(now() + timedelta(hours=72))
    touch(rec)
    audit("recall.send", "RecallRequest", rid, rec["wire_id"],
          "status: REQUESTED -> SENT_TO_BENEFICIARY_BANK", actor_user_id=uid, actor_role=role)
    return ok(pub(rec))


@bp.post("/recalls/<rid>/respond")
def respond_recall(rid):
    uid, role = require_roles("BeneficiaryBank")
    # No lazy expiry before the checks: a late answer on a still-SENT recall is
    # ERR_RECALL_EXPIRED (priority 20), ahead of the lifecycle rule (21).
    rec = get_or_404(STORE.recalls, rid, "recall")
    data = get_body()
    validate_body(data, {"response": ("str", True, _RESPONSES)})
    if rec["status"] in _TERMINAL:
        raise ApiError(*ERR_RECALL_ALREADY_RESOLVED, "The recall is already in a terminal state.")
    if rec["status"] != "SENT_TO_BENEFICIARY_BANK":
        raise ApiError(*ERR_INVALID_STATE, "The recall has not been sent to the beneficiary bank.")
    # Strict window: at or after response_due_at the recall has auto-expired.
    if now() >= parse_dt(rec["response_due_at"]):
        lazy_eval_recall(rec)
        raise ApiError(*ERR_RECALL_EXPIRED, "The recall response window has expired.")
    rec["beneficiary_bank_response"] = data["response"]
    rec["responded_at"] = iso(now())
    rec["status"] = "BENEFICIARY_RESPONDED"
    touch(rec)
    return ok(pub(rec))


@bp.post("/recalls/<rid>/complete")
def complete_recall(rid):
    uid, role = require_roles("WireOperator")
    rec = _get_recall(rid)
    data = get_body()
    if data:
        raise ApiError("ERR_INVALID_REQUEST", 400, "This endpoint does not accept a request body.")
    if rec["status"] in _TERMINAL:
        raise ApiError(*ERR_RECALL_ALREADY_RESOLVED, "The recall is already in a terminal state.")
    if rec["status"] != "BENEFICIARY_RESPONDED":
        raise ApiError(*ERR_INVALID_STATE, "Only a BENEFICIARY_RESPONDED recall can be completed.")
    if rec["beneficiary_bank_response"] != "FUNDS_RETURNED":
        raise ApiError(*ERR_RECALL_NOT_RETURNED,
                       "Completion requires beneficiary_bank_response = FUNDS_RETURNED.")
    rec["status"] = "COMPLETED"
    touch(rec)
    wire = STORE.wires[rec["wire_id"]]
    if wire["status"] == "EXECUTED":
        wire["status"] = "RECALLED"
        touch(wire)
        audit("wire.recalled", "WireTransfer", wire["id"], wire["id"],
              "status: EXECUTED -> RECALLED", actor_user_id=uid, actor_role=role)
    # Recall compensation is booked (net delta vs net_principal_cents); fee
    # assessments are left on their own lifecycle — completion does not waive.
    audit("recall.complete", "RecallRequest", rid, rec["wire_id"],
          "status: BENEFICIARY_RESPONDED -> COMPLETED; recall compensation booked",
          actor_user_id=uid, actor_role=role)
    return ok(pub(rec))


@bp.post("/recalls/<rid>/decline")
def decline_recall(rid):
    uid, role = require_roles("WireOperator")
    rec = _get_recall(rid)
    data = get_body()
    if data:
        raise ApiError("ERR_INVALID_REQUEST", 400, "This endpoint does not accept a request body.")
    if rec["status"] in _TERMINAL:
        raise ApiError(*ERR_RECALL_ALREADY_RESOLVED, "The recall is already in a terminal state.")
    if rec["status"] != "BENEFICIARY_RESPONDED":
        raise ApiError(*ERR_INVALID_STATE, "Only a BENEFICIARY_RESPONDED recall can be declined.")
    if rec["beneficiary_bank_response"] != "FUNDS_DECLINED":
        raise ApiError(*ERR_INVALID_STATE,
                       "Decline requires beneficiary_bank_response = FUNDS_DECLINED.")
    rec["status"] = "DECLINED"
    touch(rec)
    audit("recall.declined", "RecallRequest", rid, rec["wire_id"],
          "status: BENEFICIARY_RESPONDED -> DECLINED", actor_user_id=uid, actor_role=role)
    return ok(pub(rec))
