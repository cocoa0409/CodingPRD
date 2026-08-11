"""TitleSearch endpoints."""

from datetime import datetime, timedelta

from flask import Blueprint

import db
from db import (
    escrow_file_store, title_search_store, lien_store, party_store,
    aircraft_store, make_common_fields, touch, now_iso, get_logical_now,
)
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_SEARCH_ALREADY_ACTIVE,
    ERR_INVALID_TRANSITION, ERR_FILE_ON_HOLD, ERR_ALREADY_TERMINAL,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.escrow import recompute_posture, try_bubble_cleared, try_bubble_funded, recompute_lien_priorities
from validators import get_body, require_fields, require_string, require_positive_int, require_enum, require_date_string

bp = Blueprint("title_searches", __name__)

VALID_LIEN_TYPES = ["FAA_RECORDED", "IR_INTEREST", "STATE", "JUDGMENT"]
SEARCH_ALLOWED_STATUSES = {"OPENED", "SEARCH_ORDERED", "SEARCH_COMPLETE", "CLEARED", "FUNDED", "CLOSED", "RECORDED"}
TERMINAL_STATUSES = {"CANCELLED", "VERIFIED"}


@bp.route("/api/escrow-files/<id>/title-searches", methods=["POST"])
def create_title_search(id):
    user_id, role = require_roles(["EscrowOfficer"])
    ef = escrow_file_store.get(id)
    if not ef:
        raise ApiError(ERR_NOT_FOUND, "EscrowFile not found.", 404)

    # ON_HOLD blocks child mutations
    if ef["status"] == "ON_HOLD":
        raise ApiError(ERR_FILE_ON_HOLD, "EscrowFile is ON_HOLD.", 409)
    if ef["status"] in TERMINAL_STATUSES:
        raise ApiError(ERR_ALREADY_TERMINAL, f"EscrowFile is {ef['status']}.", 409)
    if ef["status"] not in SEARCH_ALLOWED_STATUSES:
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot order search in status {ef['status']}.", 409)

    # Check for existing ACTIVE or COMPLETED (non-stale) search
    for ts in title_search_store.values():
        if ts["escrow_file_id"] == id and ts["status"] in ("ACTIVE", "COMPLETED"):
            raise ApiError(ERR_SEARCH_ALREADY_ACTIVE, "An active or completed search already exists.", 409)

    fields = make_common_fields()
    ts = {
        **fields,
        "escrow_file_id": id,
        "status": "ACTIVE",
        "effective_at": None,
        "completed_at": None,
        "finding_count": 0,
    }
    title_search_store[ts["id"]] = ts

    # Auto-transition OPENED -> SEARCH_ORDERED
    if ef["status"] == "OPENED":
        ef["status"] = "SEARCH_ORDERED"
        touch(ef)

    return success_object(ts, 201)


@bp.route("/api/title-searches/<id>/complete", methods=["POST"])
def complete_title_search(id):
    user_id, role = require_roles(["EscrowOfficer"])
    ts = title_search_store.get(id)
    if not ts:
        raise ApiError(ERR_NOT_FOUND, "TitleSearch not found.", 404)

    ef = escrow_file_store.get(ts["escrow_file_id"])
    if ef:
        if ef["status"] == "ON_HOLD":
            raise ApiError(ERR_FILE_ON_HOLD, "EscrowFile is ON_HOLD.", 409)
        if ef["status"] in TERMINAL_STATUSES:
            raise ApiError(ERR_ALREADY_TERMINAL, f"EscrowFile is {ef['status']}.", 409)

    if ts["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot complete search in status {ts['status']}.", 409)

    body = get_body()
    require_fields(body, ["findings"])
    findings = body["findings"]
    if not isinstance(findings, list):
        raise ApiError(ERR_INVALID_REQUEST, "findings must be an array.", 400)

    # Validate findings
    for i, f in enumerate(findings):
        if not isinstance(f, dict):
            raise ApiError(ERR_INVALID_REQUEST, f"findings[{i}] must be an object.", 400)
        _validate_finding(f, i)

    now = now_iso()
    ts["status"] = "COMPLETED"
    ts["effective_at"] = now
    ts["completed_at"] = now
    ts["finding_count"] = len(findings)
    touch(ts)

    # Create liens in array order
    for f in findings:
        lien_fields = make_common_fields()
        lien = {
            **lien_fields,
            "escrow_file_id": ts["escrow_file_id"],
            "aircraft_id": ef["aircraft_id"],
            "title_search_id": ts["id"],
            "lienor_party_id": f["lienor_party_id"],
            "lienor_name": f["lienor_name"],
            "original_amount_cents": f["amount_cents"],
            "amount_paid_cents": 0,
            "outstanding_cents": f["amount_cents"],
            "lien_type": f["lien_type"],
            "filed_at": f["filed_at"],
            "ir_registered_at": f.get("ir_registered_at"),
            "priority_rank": 0,  # will be recomputed
            "status": "DISCOVERED",
        }
        lien_store[lien["id"]] = lien

    # Recompute priority ranks for this aircraft
    recompute_lien_priorities(ef["aircraft_id"])

    # Advance file SEARCH_ORDERED -> SEARCH_COMPLETE
    if ef["status"] == "SEARCH_ORDERED":
        ef["status"] = "SEARCH_COMPLETE"
        touch(ef)

    # Recompute posture and bubble
    recompute_posture(ef)
    touch(ef)
    try_bubble_cleared(ef)
    try_bubble_funded(ef)

    return success_object(ts)


@bp.route("/api/title-searches/<id>/refresh", methods=["POST"])
def refresh_title_search(id):
    user_id, role = require_roles(["EscrowOfficer"])
    ts = title_search_store.get(id)
    if not ts:
        raise ApiError(ERR_NOT_FOUND, "TitleSearch not found.", 404)

    ef = escrow_file_store.get(ts["escrow_file_id"])
    if ef:
        if ef["status"] == "ON_HOLD":
            raise ApiError(ERR_FILE_ON_HOLD, "EscrowFile is ON_HOLD.", 409)
        if ef["status"] in TERMINAL_STATUSES:
            raise ApiError(ERR_ALREADY_TERMINAL, f"EscrowFile is {ef['status']}.", 409)

    if ts["status"] != "STALE":
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot refresh search in status {ts['status']}.", 409)

    ts["status"] = "ACTIVE"
    ts["effective_at"] = now_iso()
    touch(ts)
    return success_object(ts)


@bp.route("/api/escrow-files/<id>/title-searches", methods=["GET"])
def list_title_searches(id):
    user_id, role = require_roles(ALL_ROLES)
    ef = escrow_file_store.get(id)
    if not ef:
        raise ApiError(ERR_NOT_FOUND, "EscrowFile not found.", 404)

    items = [ts for ts in title_search_store.values() if ts["escrow_file_id"] == id]
    items.sort(key=lambda x: x["created_at"])

    from flask import request
    try:
        limit = max(1, min(100, int(request.args.get("limit", 10))))
    except (ValueError, TypeError):
        limit = 10
    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except (ValueError, TypeError):
        offset = 0
    total = len(items)
    items = items[offset:offset + limit]
    return success_list(items, limit, offset, total)


def _validate_finding(f: dict, idx: int):
    """Validate one findings entry."""
    allowed = {"lienor_party_id", "lienor_name", "amount_cents", "lien_type", "filed_at", "ir_registered_at"}
    unknown = set(f.keys()) - allowed
    if unknown:
        raise ApiError(ERR_INVALID_REQUEST, f"findings[{idx}] has unknown fields: {', '.join(unknown)}", 400)

    for req in ["lienor_party_id", "lienor_name", "amount_cents", "lien_type", "filed_at"]:
        if req not in f or f[req] is None:
            raise ApiError(ERR_INVALID_REQUEST, f"findings[{idx}].{req} is required.", 400)

    require_string(f["lienor_party_id"], f"findings[{idx}].lienor_party_id")
    require_string(f["lienor_name"], f"findings[{idx}].lienor_name")
    require_positive_int(f["amount_cents"], f"findings[{idx}].amount_cents")
    require_enum(f["lien_type"], f"findings[{idx}].lien_type", VALID_LIEN_TYPES)
    require_date_string(f["filed_at"], f"findings[{idx}].filed_at")

    # lienor_party_id must reference a Party with party_type LENDER
    party = party_store.get(f["lienor_party_id"])
    if not party:
        raise ApiError(ERR_NOT_FOUND, f"findings[{idx}].lienor_party_id not found.", 404)
    if party["party_type"] != "LENDER":
        raise ApiError(ERR_INVALID_REQUEST, f"findings[{idx}].lienor_party_id must be a LENDER party.", 400)

    # ir_registered_at required iff IR_INTEREST
    if f["lien_type"] == "IR_INTEREST":
        if not f.get("ir_registered_at"):
            raise ApiError(ERR_INVALID_REQUEST, f"findings[{idx}].ir_registered_at is required for IR_INTEREST.", 400)
        require_date_string(f["ir_registered_at"], f"findings[{idx}].ir_registered_at")
