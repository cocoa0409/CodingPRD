"""DisposalOrder routes — the most heavily gated workflow in the archive."""
from flask import Blueprint, request

import calc
import cascades
from auth import ALL_ROLES, require_roles
from db import STORE, new_id, now, stamp
from envelope import ok, paginate
from errors import raise_err
from serializers import order_out
from validate import body, opt_bool, req_dt, req_int, req_str

bp = Blueprint("disposal", __name__, url_prefix="/archive")

NON_TERMINAL = ("DRAFT", "PENDING_APPROVAL", "APPROVED", "BLOCKED")


def _get_order(oid):
    rec = STORE.orders.get(oid)
    if rec is None:
        raise_err("ERR_ORDER_NOT_FOUND", "Disposal order not found")
    return rec


def _hold_clear(asset):
    if calc.hold_status(asset) != "CLEAR":
        raise_err("ERR_LEGAL_HOLD_ACTIVE", "Asset is under an active legal hold")


def _pin_intact(order, asset):
    if asset["version"] != order["pinned_asset_version"]:
        raise_err(
            "ERR_ASSET_VERSION_DRIFT",
            "Asset version has drifted from the order's pinned_asset_version",
        )


@bp.post("/disposal-orders")
def create_order():
    uid, _ = require_roles("ArchivistLead")
    j = body()
    asset_id = req_str(j, "asset_id")
    asset = STORE.assets.get(asset_id)
    if asset is None:
        raise_err("ERR_ASSET_NOT_FOUND", "Asset not found")
    # OCC field presence/type (needed before the version comparison)
    if "expected_asset_version" not in j or j["expected_asset_version"] is None:
        raise_err("ERR_INVALID_REQUEST", "Field 'expected_asset_version': is required")
    if isinstance(j["expected_asset_version"], bool) or not isinstance(
        j["expected_asset_version"], int
    ):
        raise_err("ERR_INVALID_REQUEST", "Field 'expected_asset_version': must be an integer")
    expected = j["expected_asset_version"]
    # retention_override requires a justification (malformed without it)
    if "retention_override" in j and not isinstance(j["retention_override"], bool):
        raise_err("ERR_INVALID_REQUEST", "Field 'retention_override': must be a boolean")
    retention_override = j.get("retention_override", False)
    override_reason = j.get("override_reason")
    if override_reason is not None and not isinstance(override_reason, str):
        raise_err("ERR_INVALID_REQUEST", "Field 'override_reason': must be a string")
    if retention_override and not override_reason:
        raise_err(
            "ERR_INVALID_REQUEST",
            "override_reason is required when retention_override is true",
        )
    scheduled = req_dt(j, "scheduled_execution_date")
    # State preconditions
    if asset["catalog_status"] != "ARCHIVED":
        raise_err("ERR_ASSET_NOT_ARCHIVED", "Disposal-order create requires an ARCHIVED asset")
    if any(
        o["asset_id"] == asset_id and o["status"] in NON_TERMINAL
        for o in STORE.orders.values()
    ):
        raise_err(
            "ERR_ACTIVE_DISPOSAL_ORDER_EXISTS",
            "A non-terminal disposal order already exists for this asset",
        )
    # Optimistic concurrency
    if expected != asset["version"]:
        raise_err(
            "ERR_STALE_ASSET_VERSION",
            "expected_asset_version does not match the asset's current version",
        )
    # Safety gate
    _hold_clear(asset)
    # Temporal/shape: execution date strictly in the future
    if scheduled <= now():
        raise_err(
            "ERR_INVALID_REQUEST",
            "scheduled_execution_date must be strictly in the future",
        )
    # Constraint: retention elapsed unless overridden
    if not retention_override and not calc.retention_eligible(asset):
        raise_err(
            "ERR_RETENTION_NOT_ELAPSED",
            "The retention period for this asset has not elapsed",
        )
    rec = {
        "id": new_id(),
        "asset_id": asset_id,
        "created_by_user_id": uid,
        "scheduled_execution_date": scheduled,
        "retention_override": retention_override,
        "override_reason": override_reason if retention_override else j.get("override_reason"),
        "status": "DRAFT",
        "approved_by_user_id": None,
        "reject_reason": None,
    }
    # The create's own write bumps the asset version; the pin records the
    # post-increment version (== expected_asset_version + 1).
    asset["version"] += 1
    asset["updated_at"] = now()
    rec["pinned_asset_version"] = asset["version"]
    stamp(rec)
    STORE.orders[rec["id"]] = rec
    return ok(order_out(rec), 201)


@bp.get("/disposal-orders")
def list_orders():
    require_roles(*ALL_ROLES)
    recs = list(STORE.orders.values())
    for param, field in (("asset_id", "asset_id"), ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            recs = [r for r in recs if r[field] == v]
    return paginate(recs, order_out)


@bp.get("/disposal-orders/<oid>")
def get_order(oid):
    require_roles(*ALL_ROLES)
    return ok(order_out(_get_order(oid)))


@bp.post("/disposal-orders/<oid>/submit")
def submit_order(oid):
    require_roles("ArchivistLead")
    rec = _get_order(oid)
    if rec["status"] != "DRAFT":
        raise_err("ERR_DISPOSAL_ORDER_NOT_DRAFT", "submit requires DRAFT")
    rec["status"] = "PENDING_APPROVAL"
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(order_out(rec))


@bp.post("/disposal-orders/<oid>/approve")
def approve_order(oid):
    uid, _ = require_roles("ArchivistLead")
    rec = _get_order(oid)
    # PRD 3.5 pins the order: state -> hold gate -> version pin -> segregation
    if rec["status"] != "PENDING_APPROVAL":
        raise_err("ERR_DISPOSAL_ORDER_NOT_PENDING", "approve requires PENDING_APPROVAL")
    asset = STORE.assets.get(rec["asset_id"])
    if asset is None:
        raise_err("ERR_ASSET_NOT_FOUND", "Asset not found")
    _hold_clear(asset)
    _pin_intact(rec, asset)
    if uid == rec["created_by_user_id"]:
        raise_err("ERR_SOD_DISPOSAL_SELF_APPROVE", "Approver must differ from the creator")
    rec["status"] = "APPROVED"
    rec["approved_by_user_id"] = uid
    rec["updated_at"] = now()
    rec["version"] += 1
    # System-driven asset transition ARCHIVED -> DISPOSAL_SCHEDULED (no version bump)
    asset["catalog_status"] = "DISPOSAL_SCHEDULED"
    return ok(order_out(rec))


@bp.post("/disposal-orders/<oid>/reject")
def reject_order(oid):
    require_roles("ArchivistLead")
    rec = _get_order(oid)
    if rec["status"] != "PENDING_APPROVAL":
        raise_err("ERR_DISPOSAL_ORDER_NOT_PENDING", "reject requires PENDING_APPROVAL")
    j = body()
    reason = req_str(j, "reason")
    rec["status"] = "REJECTED"
    rec["reject_reason"] = reason
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(order_out(rec))


@bp.post("/disposal-orders/<oid>/resubmit")
def resubmit_order(oid):
    require_roles("ArchivistLead")
    rec = _get_order(oid)
    if rec["status"] != "BLOCKED":
        raise_err("ERR_DISPOSAL_ORDER_NOT_BLOCKED", "resubmit requires BLOCKED")
    asset = STORE.assets.get(rec["asset_id"])
    if asset is None:
        raise_err("ERR_ASSET_NOT_FOUND", "Asset not found")
    _hold_clear(asset)
    rec["status"] = "PENDING_APPROVAL"
    rec["pinned_asset_version"] = asset["version"]  # re-pin, discarding the stale pin
    rec["updated_at"] = now()
    rec["version"] += 1
    return ok(order_out(rec))


@bp.post("/disposal-orders/<oid>/execute")
def execute_order(oid):
    require_roles("ArchivistLead")
    rec = _get_order(oid)
    if rec["status"] != "APPROVED":
        raise_err("ERR_DISPOSAL_ORDER_NOT_APPROVED", "execute requires APPROVED")
    asset = STORE.assets.get(rec["asset_id"])
    if asset is None:
        raise_err("ERR_ASSET_NOT_FOUND", "Asset not found")
    _hold_clear(asset)
    _pin_intact(rec, asset)
    if now() < rec["scheduled_execution_date"]:
        raise_err("ERR_DISPOSAL_NOT_YET_DUE", "The scheduled execution date has not been reached")
    rec["status"] = "EXECUTED"
    rec["updated_at"] = now()
    rec["version"] += 1
    cascades.disposal_execute_cascade(asset)
    return ok(order_out(rec))


@bp.post("/disposal-orders/<oid>/withdraw")
def withdraw_order(oid):
    uid, _ = require_roles("ArchivistLead")
    rec = _get_order(oid)
    # Ownership: only the creating ArchivistLead may withdraw
    if uid != rec["created_by_user_id"]:
        raise_err(
            "ERR_INSUFFICIENT_PERMISSIONS",
            "Only the creating ArchivistLead may withdraw this order",
        )
    if rec["status"] not in ("DRAFT", "APPROVED"):
        raise_err(
            "ERR_DISPOSAL_ORDER_NOT_WITHDRAWABLE",
            "withdraw requires DRAFT or APPROVED",
        )
    was_approved = rec["status"] == "APPROVED"
    rec["status"] = "WITHDRAWN"
    rec["updated_at"] = now()
    rec["version"] += 1
    if was_approved:
        asset = STORE.assets.get(rec["asset_id"])
        if asset is not None and asset["catalog_status"] == "DISPOSAL_SCHEDULED":
            asset["catalog_status"] = "ARCHIVED"  # no version bump
    return ok(order_out(rec))
