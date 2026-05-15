"""Limit adjustment (temporary override) approval workflow."""
from __future__ import annotations

from flask import Blueprint, g

from app.auth import require_auth
from app.clock import clock, parse_iso
from app.errors import make_error
from app.numeric import to_decimal, ZERO
from app.responses import success_object
from app.services import positions as positions_service
from app.services.serializers import limit_adjustment_dto
from app.store import store
from app.validation import (
    check_version,
    get_json_body,
    optional_decimal,
    require_decimal,
    require_str,
)


bp = Blueprint("limit_adjustments", __name__, url_prefix="/fx-risk")


@bp.route("/limit-adjustments", methods=["POST"])
@require_auth(["Trader"])
def create_adjustment():
    with store.lock:
        body = get_json_body()
        limit_id = require_str(body, "limit_id")
        limit = store.limits.get(limit_id)
        if limit is None:
            raise make_error("ERR_NOT_FOUND")
        # Trader must own the limit
        if limit["trader_id"] != g.user_id:
            raise make_error("ERR_FORBIDDEN")
        # Trader must exist and be ACTIVE per the PRD's flow
        trader = store.traders.get(limit["trader_id"])
        if trader is None:
            raise make_error("ERR_NOT_FOUND")
        delta = require_decimal(body, "requested_delta_usd", gt=ZERO)
        justification = require_str(body, "justification", min_len=1, max_len=500)
        expires_at_str = require_str(body, "expires_at")
        try:
            expires_at = parse_iso(expires_at_str)
        except ValueError:
            raise make_error("ERR_VALIDATION", "expires_at must be ISO 8601.")
        if expires_at <= clock.now():
            raise make_error("ERR_EXPIRES_IN_PAST")
        meta = store.stamp_common(create=True)
        row = {
            **meta,
            "limit_id": limit_id,
            "requested_delta_usd": delta,
            "justification": justification,
            "expires_at": expires_at_str,
            "status": "PENDING",
            "requester_trader_id": g.user_id,
            "approver_user_id": None,
        }
        store.limit_adjustments[row["id"]] = row
        return success_object(limit_adjustment_dto(row), status=201)


def _load_pending(adj_id: str) -> dict:
    adj = store.limit_adjustments.get(adj_id)
    if adj is None:
        raise make_error("ERR_NOT_FOUND")
    return adj


@bp.route("/limit-adjustments/<adj_id>/approve", methods=["POST"])
@require_auth(["RiskOfficer"])
def approve_adjustment(adj_id: str):
    with store.lock:
        adj = _load_pending(adj_id)
        if adj["status"] != "PENDING":
            # Either already decided (concurrent) or in a terminal state
            raise make_error("ERR_REQUEST_ALREADY_DECIDED")
        # Segregation of duties
        if g.user_id == adj["requester_trader_id"]:
            raise make_error("ERR_SEGREGATION_VIOLATION")
        limit = store.limits.get(adj["limit_id"])
        if limit is None:
            raise make_error("ERR_NOT_FOUND")
        trader = store.traders.get(limit["trader_id"])
        if trader is None:
            raise make_error("ERR_NOT_FOUND")
        if trader["status"] != "ACTIVE":
            raise make_error("ERR_INVALID_STATE", "Trader is not ACTIVE.")
        # Re-check expires_at at approve time
        try:
            exp = parse_iso(adj["expires_at"])
        except ValueError:
            raise make_error("ERR_EXPIRES_IN_PAST")
        if exp <= clock.now():
            raise make_error("ERR_EXPIRES_IN_PAST")
        # Apply
        before = {"status": "PENDING",
                  "temporary_override_usd": float(limit.get("temporary_override_usd") or 0)}
        delta = to_decimal(adj["requested_delta_usd"])
        limit["temporary_override_usd"] = to_decimal(limit.get("temporary_override_usd") or 0) + delta
        limit["updated_at"] = clock.now_iso()
        limit["version"] = limit["version"] + 1
        adj["status"] = "APPROVED"
        adj["approver_user_id"] = g.user_id
        adj["updated_at"] = clock.now_iso()
        adj["version"] = adj["version"] + 1
        trading_day = clock.today_iso_date()
        positions_service.recompute_limit_utilization(store, limit, trading_day)
        positions_service.recompute_warning_status_for_trader(store, limit["trader_id"], trading_day)
        store.audit(
            event_type="LIMIT_OVERRIDE_APPROVED",
            actor_user_id=g.user_id,
            actor_role=g.role,
            subject_entity="LimitAdjustmentRequest",
            subject_id=adj["id"],
            before_snapshot=before,
            after_snapshot={"status": "APPROVED",
                            "temporary_override_usd": float(limit["temporary_override_usd"])},
        )
        return success_object(limit_adjustment_dto(adj))


@bp.route("/limit-adjustments/<adj_id>/reject", methods=["POST"])
@require_auth(["RiskOfficer"])
def reject_adjustment(adj_id: str):
    with store.lock:
        adj = _load_pending(adj_id)
        if adj["status"] != "PENDING":
            raise make_error("ERR_REQUEST_ALREADY_DECIDED")
        if g.user_id == adj["requester_trader_id"]:
            raise make_error("ERR_SEGREGATION_VIOLATION")
        before = {"status": "PENDING"}
        adj["status"] = "REJECTED"
        adj["approver_user_id"] = g.user_id
        adj["updated_at"] = clock.now_iso()
        adj["version"] = adj["version"] + 1
        store.audit(
            event_type="LIMIT_CHANGE",
            actor_user_id=g.user_id,
            actor_role=g.role,
            subject_entity="LimitAdjustmentRequest",
            subject_id=adj["id"],
            before_snapshot=before,
            after_snapshot={"status": "REJECTED"},
        )
        return success_object(limit_adjustment_dto(adj))


@bp.route("/limit-adjustments/<adj_id>/request-revision", methods=["POST"])
@require_auth(["RiskOfficer"])
def request_revision_adjustment(adj_id: str):
    with store.lock:
        adj = _load_pending(adj_id)
        if adj["status"] != "PENDING":
            raise make_error("ERR_INVALID_STATE")
        before = {"status": "PENDING"}
        adj["status"] = "REVISION_REQUESTED"
        adj["updated_at"] = clock.now_iso()
        adj["version"] = adj["version"] + 1
        store.audit(
            event_type="LIMIT_CHANGE",
            actor_user_id=g.user_id,
            actor_role=g.role,
            subject_entity="LimitAdjustmentRequest",
            subject_id=adj["id"],
            before_snapshot=before,
            after_snapshot={"status": "REVISION_REQUESTED"},
        )
        return success_object(limit_adjustment_dto(adj))


@bp.route("/limit-adjustments/<adj_id>", methods=["PATCH"])
@require_auth(["Trader"])
def patch_adjustment(adj_id: str):
    with store.lock:
        adj = store.limit_adjustments.get(adj_id)
        if adj is None:
            raise make_error("ERR_NOT_FOUND")
        if adj["status"] != "REVISION_REQUESTED":
            raise make_error("ERR_INVALID_STATE")
        if g.user_id != adj["requester_trader_id"]:
            raise make_error("ERR_FORBIDDEN")
        body = get_json_body()
        check_version(body, adj["version"])
        new_delta = optional_decimal(body, "requested_delta_usd", gt=ZERO)
        new_justification = body.get("justification")
        new_expires_at = body.get("expires_at")
        if new_delta is not None:
            adj["requested_delta_usd"] = new_delta
        if new_justification is not None:
            if not isinstance(new_justification, str) or not (1 <= len(new_justification) <= 500):
                raise make_error("ERR_VALIDATION", "justification must be 1..500 chars.")
            adj["justification"] = new_justification
        if new_expires_at is not None:
            if not isinstance(new_expires_at, str):
                raise make_error("ERR_VALIDATION", "expires_at must be ISO 8601 string.")
            try:
                exp = parse_iso(new_expires_at)
            except ValueError:
                raise make_error("ERR_VALIDATION", "expires_at must be ISO 8601.")
            if exp <= clock.now():
                raise make_error("ERR_EXPIRES_IN_PAST")
            adj["expires_at"] = new_expires_at
        before = {"status": "REVISION_REQUESTED"}
        adj["status"] = "PENDING"
        adj["updated_at"] = clock.now_iso()
        adj["version"] = adj["version"] + 1
        store.audit(
            event_type="LIMIT_CHANGE",
            actor_user_id=g.user_id,
            actor_role=g.role,
            subject_entity="LimitAdjustmentRequest",
            subject_id=adj["id"],
            before_snapshot=before,
            after_snapshot={"status": "PENDING"},
        )
        return success_object(limit_adjustment_dto(adj))
