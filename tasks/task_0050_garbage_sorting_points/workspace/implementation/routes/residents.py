"""Resident endpoints: register, verify, restrict, read."""

from __future__ import annotations

from flask import Blueprint, g, jsonify

from db import db
from errors import (
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_VALIDATION,
    raise_api_error,
)
from middleware import require_roles
from response import success_response
from services.common import (
    HEX64_RE,
    check_version,
    get_json_body,
    parse_iso8601_utc,
    require_enum,
    require_str,
)
from services.lookup import get_household, get_resident, get_resident_by_id

bp = Blueprint("residents", __name__)

RELATIONS = {"HEAD", "SPOUSE", "CHILD", "PARENT", "OTHER"}


@bp.post("/communities/<community_id>/households/<household_id>/residents")
@require_roles("CommunityAdmin")
def create_resident(community_id: str, household_id: str):
    get_household(community_id, household_id)
    body = get_json_body()
    full_name = require_str(body, "full_name", min_len=1, max_len=80)
    id_document_hash = require_str(body, "id_document_hash", min_len=64, max_len=64)
    if not HEX64_RE.match(id_document_hash):
        raise_api_error(ERR_VALIDATION, "id_document_hash must be 64 lowercase hex chars.")
    relation = require_enum(body, "relation", RELATIONS)

    obj = {
        "household_id": household_id,
        "full_name": full_name,
        "id_document_hash": id_document_hash,
        "relation": relation,
        "identity_status": "PENDING",
        "account_status": "INACTIVE",
        "restricted_until": None,
        "consecutive_disposal_days": 0,
    }
    db.stamp_create(obj)
    db.residents[obj["id"]] = obj
    return jsonify(success_response(obj)), 201


@bp.post("/communities/<community_id>/households/<household_id>/residents/<resident_id>/verify")
@require_roles("CommunityAdmin")
def verify_resident(community_id: str, household_id: str, resident_id: str):
    resident = get_resident(community_id, household_id, resident_id)
    body = get_json_body()
    check_version(body, resident)
    decision = require_enum(body, "decision", {"APPROVE", "REJECT"})

    if resident["identity_status"] != "PENDING":
        raise_api_error(ERR_INVALID_STATE, "Resident is not PENDING.")
    if not resident.get("id_document_hash"):
        raise_api_error(ERR_INVALID_STATE, "id_document_hash is required for verification.")

    if decision == "APPROVE":
        resident["identity_status"] = "VERIFIED"
        if resident["account_status"] != "RESTRICTED":
            resident["account_status"] = "ACTIVE"
        # Set head_resident_id if first VERIFIED in household
        household = db.households[household_id]
        if household.get("head_resident_id") is None:
            household["head_resident_id"] = resident["id"]
            db.stamp_update(household)
    else:
        resident["identity_status"] = "REJECTED"
        # account_status stays INACTIVE

    db.stamp_update(resident)
    return jsonify(success_response(resident)), 200


@bp.post("/communities/<community_id>/households/<household_id>/residents/<resident_id>/restrict")
@require_roles("CommunityAdmin")
def restrict_resident(community_id: str, household_id: str, resident_id: str):
    resident = get_resident(community_id, household_id, resident_id)
    body = get_json_body()
    check_version(body, resident)
    if "until" not in body or body["until"] is None:
        raise_api_error(ERR_VALIDATION, "Field 'until' is required.")
    until_utc = parse_iso8601_utc(body["until"])
    reason = require_str(body, "reason", min_len=1, max_len=500)

    if resident["identity_status"] != "VERIFIED":
        raise_api_error(ERR_INVALID_STATE, "Resident must be VERIFIED to be restricted.")

    resident["account_status"] = "RESTRICTED"
    from services.common import iso_z
    resident["restricted_until"] = iso_z(until_utc)
    db.stamp_update(resident)
    return jsonify(success_response(resident)), 200


@bp.get("/communities/<community_id>/households/<household_id>/residents/<resident_id>")
@require_roles("CommunityAdmin", "Resident")
def read_resident(community_id: str, household_id: str, resident_id: str):
    r = get_resident(community_id, household_id, resident_id)
    if g.user_role == "Resident":
        me = get_resident_by_id(g.user_id)
        if me is None or me.get("household_id") != household_id:
            raise_api_error(ERR_FORBIDDEN, "Resident may only read residents in their own household.")
    return jsonify(success_response(r)), 200
