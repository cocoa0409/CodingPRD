"""Household endpoints."""

from flask import Blueprint, request

import db
from common import (
    require_role, get_json_body, stamp_common_create, bump,
    success, must_exist, get_pagination, paginate_list, clock_now_iso,
)
from errors import raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND

bp = Blueprint("households", __name__)


REQUIRED_CREATE = ["name", "address_line1", "postal_code"]


def _validate_str(body, key, required=True):
    if key not in body or body[key] is None:
        if required:
            raise_err(ERR_INVALID_REQUEST, f"{key} is required")
        return None
    v = body[key]
    if not isinstance(v, str) or v == "":
        raise_err(ERR_INVALID_REQUEST, f"{key} must be a non-empty string")
    return v


@bp.route("/households", methods=["POST"])
def create_household():
    require_role({"Registrar", "PlatformAdmin"})
    body = get_json_body()
    for k in REQUIRED_CREATE:
        _validate_str(body, k, required=True)
    primary = body.get("primary_contact_member_id")
    if primary is not None and not isinstance(primary, str):
        raise_err(ERR_INVALID_REQUEST, "primary_contact_member_id must be a string or null")
    if primary is not None:
        # Existence check per §2.8 rung 3.
        member = db.members.get(primary)
        if member is None:
            raise_err(ERR_NOT_FOUND, "primary_contact_member_id not found")

    rec = {
        "name": body["name"],
        "address_line1": body["address_line1"],
        "postal_code": body["postal_code"],
        "primary_contact_member_id": primary,
        "status": "ACTIVE",
        "archived_at": None,
    }
    stamp_common_create(rec)
    db.households[rec["id"]] = rec
    return success(rec, 201)


@bp.route("/households/<hid>", methods=["GET"])
def get_household(hid):
    require_role({"Registrar", "Coordinator", "FinanceAdmin", "PlatformAdmin"})
    rec = must_exist(db.households, hid, "Household")
    return success(rec, 200)


@bp.route("/households/<hid>", methods=["PATCH"])
def patch_household(hid):
    require_role({"Registrar", "PlatformAdmin"})
    rec = must_exist(db.households, hid, "Household")
    body = get_json_body()

    # Optional fields — validate type when present.
    if "name" in body:
        _validate_str(body, "name")
        rec["name"] = body["name"]
    if "address_line1" in body:
        _validate_str(body, "address_line1")
        rec["address_line1"] = body["address_line1"]
    if "postal_code" in body:
        _validate_str(body, "postal_code")
        rec["postal_code"] = body["postal_code"]
    if "primary_contact_member_id" in body:
        pcm = body["primary_contact_member_id"]
        if pcm is not None:
            if not isinstance(pcm, str):
                raise_err(ERR_INVALID_REQUEST, "primary_contact_member_id must be string or null")
            member = db.members.get(pcm)
            if member is None:
                raise_err(ERR_NOT_FOUND, "primary_contact_member_id not found")
            if member.get("household_id") != hid:
                from errors import ERR_REFERENCE_MISMATCH
                raise_err(ERR_REFERENCE_MISMATCH, "primary_contact must belong to this household")
        rec["primary_contact_member_id"] = pcm
    if "status" in body:
        new_status = body["status"]
        if new_status not in {"ACTIVE", "ARCHIVED"}:
            raise_err(ERR_INVALID_REQUEST, "status must be ACTIVE or ARCHIVED")
        if new_status == "ARCHIVED" and rec["status"] == "ACTIVE":
            rec["status"] = "ARCHIVED"
            rec["archived_at"] = clock_now_iso()
        elif new_status == "ACTIVE" and rec["status"] == "ARCHIVED":
            # Not explicitly permitted or forbidden — treat as invalid state to be safe.
            raise_err(ERR_INVALID_STATE, "cannot un-archive a household")

    bump(rec)
    return success(rec, 200)


@bp.route("/households", methods=["GET"])
def list_households():
    require_role({"Registrar", "Coordinator", "FinanceAdmin", "PlatformAdmin"})
    limit, offset = get_pagination()
    primary = request.args.get("primary_contact_member_id")
    status = request.args.get("status")
    items = list(db.households.values())
    if primary:
        items = [h for h in items if h.get("primary_contact_member_id") == primary]
    if status:
        items = [h for h in items if h.get("status") == status]
    page, meta = paginate_list(items, limit, offset)
    return success(page, 200, meta_extra=meta)


@bp.route("/households/<hid>/members", methods=["GET"])
def list_household_members(hid):
    require_role({"Registrar", "Coordinator", "FinanceAdmin", "PlatformAdmin"})
    must_exist(db.households, hid, "Household")
    items = [m for m in db.members.values() if m.get("household_id") == hid]
    # No pagination declared for this endpoint in the scaffold; sort by created_at ASC.
    items.sort(key=lambda r: r.get("created_at", ""))
    return success(items, 200)
