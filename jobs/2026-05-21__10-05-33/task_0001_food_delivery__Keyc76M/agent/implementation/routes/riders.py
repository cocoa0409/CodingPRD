"""Rider endpoints."""

from flask import Blueprint, request

import auth
import envelope
import projection
import state
import validators
from services import riders as svc


bp = Blueprint("riders", __name__)


def _read_payload():
    try:
        return request.get_json(silent=True) or {}
    except Exception:
        return {}


@bp.route("/api/riders", methods=["POST"])
def register_rider():
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role != "PlatformAdmin":
        return envelope.forbidden()

    payload = _read_payload()
    err = validators.require_body(payload)
    if err:
        return err
    if "name" not in payload or not isinstance(payload["name"], str) or not payload["name"]:
        return envelope.validation("name must be a non-empty string.")
    if "phone" not in payload or not isinstance(payload["phone"], str) or not payload["phone"]:
        return envelope.validation("phone must be a non-empty string.")

    with state.lock():
        if payload["phone"] in state.STORE.rider_phones:
            return envelope.error(
                409, "ERR_INVALID_STATE", "phone already registered to a rider."
            )
        rec = svc.new_rider(payload["name"], payload["phone"])
        return envelope.created(projection.render(rec))


@bp.route("/api/riders/<rid>", methods=["GET"])
def get_rider(rid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role not in ("PlatformAdmin", "Rider", "CustomerService"):
        return envelope.forbidden()
    with state.lock():
        rec = state.STORE.riders.get(rid)
        if rec is None:
            return envelope.not_found("Rider not found.")
        if role == "Rider" and user_id != rid:
            return envelope.forbidden()
        return envelope.success(projection.render(rec))


@bp.route("/api/riders/<rid>/go-online", methods=["POST"])
def go_online(rid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role != "Rider":
        return envelope.forbidden()
    with state.lock():
        rec = state.STORE.riders.get(rid)
        if rec is None:
            return envelope.not_found("Rider not found.")
        if user_id != rid:
            return envelope.forbidden()
        if rec["status"] != "OFFLINE":
            return envelope.invalid_state("Rider must be OFFLINE to go online.")
        rec["status"] = "AVAILABLE"
        svc.bump(rec)
        return envelope.success(projection.render(rec))


@bp.route("/api/riders/<rid>/go-offline", methods=["POST"])
def go_offline(rid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role != "Rider":
        return envelope.forbidden()
    with state.lock():
        rec = state.STORE.riders.get(rid)
        if rec is None:
            return envelope.not_found("Rider not found.")
        if user_id != rid:
            return envelope.forbidden()
        if rec["status"] not in ("AVAILABLE", "ON_DELIVERY"):
            return envelope.invalid_state(
                "Rider must be AVAILABLE or ON_DELIVERY to go offline."
            )
        if svc.rider_has_blocking_assignments(rid):
            return envelope.invalid_state(
                "Rider has live assignments (OFFERED/ACCEPTED/PICKED_UP)."
            )
        rec["status"] = "OFFLINE"
        svc.bump(rec)
        return envelope.success(projection.render(rec))


@bp.route("/api/riders/<rid>/suspend", methods=["POST"])
def suspend_rider(rid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role != "PlatformAdmin":
        return envelope.forbidden()
    with state.lock():
        rec = state.STORE.riders.get(rid)
        if rec is None:
            return envelope.not_found("Rider not found.")
        if rec["status"] != "AVAILABLE":
            return envelope.invalid_state(
                "Only AVAILABLE riders can be suspended."
            )
        if rec["on_time_rate"] >= 0.70 and rec["acceptance_rate"] >= 0.50:
            return envelope.error(
                422, "ERR_SUSPEND_CRITERIA_NOT_MET",
                "Rider's metrics do not meet the suspension thresholds.",
            )
        rec["status"] = "SUSPENDED"
        svc.bump(rec)
        return envelope.success(projection.render(rec))
