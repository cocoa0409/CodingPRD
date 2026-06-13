"""Hold-order endpoints (PRD §3.6, §3.7)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import err
from middleware import require_auth
from response import ok_object, ok_array
from services.common import (
    get_json_body, require_fields, require_str, require_int,
    parse_pagination, created_sort_key, paginate,
)
from services.entities import get_hold_or_404
from services.serialize import public
from services.holds import issue_hold, resolve_release, resolve_dispose

bp = Blueprint("holds", __name__)

HOLD_REASONS = {"ALLERGEN", "PATHOGEN", "TEMPERATURE_EXCURSION", "RECALL", "OTHER"}


@bp.post("/traceability/hold-orders")
def create_hold():
    require_auth(["QualityManager"])
    body = get_json_body()
    require_fields(body, ["facility_id", "target_lot_id", "reason"])
    facility_id = require_str(body, "facility_id")
    target_lot_id = require_str(body, "target_lot_id")
    reason = require_str(body, "reason")
    if reason not in HOLD_REASONS:
        raise err("ERR_INVALID_REQUEST", "Invalid hold reason")

    facility = db.facilities.get(facility_id)
    if facility is None:
        raise err("ERR_FACILITY_NOT_FOUND", "Facility not found")
    lot = db.lots.get(target_lot_id)
    if lot is None:
        raise err("ERR_LOT_NOT_FOUND", "Target lot not found")
    if lot["facility_id"] != facility_id:
        raise err("ERR_CROSS_FACILITY_REFERENCE", "Target lot belongs to a different facility")

    rec = issue_hold(facility_id, target_lot_id, reason)
    return ok_object(public(rec), 201)


@bp.get("/traceability/hold-orders/<hid>")
def get_hold(hid):
    require_auth(["QualityManager", "SafetyAuditor"])
    rec = get_hold_or_404(hid)
    return ok_object(public(rec), 200)


@bp.get("/traceability/hold-orders")
def list_holds():
    require_auth(["QualityManager", "SafetyAuditor"])
    items = list(db.hold_orders.values())
    facility_id = request.args.get("facility_id")
    target_lot_id = request.args.get("target_lot_id")
    status = request.args.get("status")
    if facility_id is not None:
        items = [x for x in items if x["facility_id"] == facility_id]
    if target_lot_id is not None:
        items = [x for x in items if x["target_lot_id"] == target_lot_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    items.sort(key=created_sort_key)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return ok_array([public(x) for x in page], limit, offset, total, 200)


@bp.post("/traceability/hold-orders/<hid>/resolve")
def resolve_hold(hid):
    require_auth(["QualityManager"])
    hold = get_hold_or_404(hid)
    body = get_json_body()
    require_fields(body, ["disposition", "expected_hold_order_version"])
    disposition = require_str(body, "disposition")
    expected = require_int(body, "expected_hold_order_version")
    if disposition not in ("RELEASE", "DISPOSE"):
        raise err("ERR_INVALID_REQUEST", "disposition must be RELEASE or DISPOSE")

    # priority 7: OCC version check — before the state precondition.
    if expected != hold["version"]:
        raise err("ERR_STALE_VERSION", "expected_hold_order_version does not match")

    # priority 8: hold must be ACTIVE.
    if hold["status"] != "ACTIVE":
        raise err("ERR_HOLD_NOT_ACTIVE", "Hold is not ACTIVE")

    if disposition == "RELEASE":
        resolve_release(hold)
    else:
        resolve_dispose(hold)

    return ok_object(public(hold), 200)
