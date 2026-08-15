"""Taxpayer registration and identity verification (PRD §3.3)."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles
from response import created, ok
from services.serialize import taxpayer_json
from validation import parse_body, require_entity

bp = Blueprint("taxpayers", __name__)

CREATE_SCHEMA = {
    "full_name": {"kind": "string", "required": True},
    "ssn_token": {"kind": "string", "required": True},
    "phone": {"kind": "string", "required": True},
    "email": {"kind": "string", "allow_null": True},
    "preferred_language": {"kind": "enum", "values": ["EN", "ES", "OTHER"]},
}

VERIFY_SCHEMA = {
    "id_document_type": {"kind": "enum", "required": True,
                         "values": ["DRIVERS_LICENSE", "PASSPORT", "STATE_ID",
                                    "MILITARY_ID"]},
}


@bp.post("/taxpayers")
def create_taxpayer():
    get_context()
    require_roles(["Screener", "SiteCoordinator"])
    body = parse_body(CREATE_SCHEMA)
    # Uniqueness (tier 7): ssn_token unique across all taxpayers.
    if any(t["ssn_token"] == body["ssn_token"] for t in store.taxpayers.values()):
        raise ApiError("ERR_TAXPAYER_DUPLICATE_SSN", 409,
                       "ssn_token is already registered")
    tp = db.new_common({
        "full_name": body["full_name"],
        "ssn_token": body["ssn_token"],
        "phone": body["phone"],
        "email": body.get("email"),
        "preferred_language": body.get("preferred_language", "EN"),
        "identity_status": "UNVERIFIED",
        "id_document_type": None,
    })
    store.taxpayers[tp["id"]] = tp
    return created(taxpayer_json(tp))


@bp.get("/taxpayers/<taxpayer_id>")
def get_taxpayer(taxpayer_id):
    get_context()
    tp = require_entity(store.taxpayers, taxpayer_id)
    return ok(taxpayer_json(tp))


@bp.post("/taxpayers/<taxpayer_id>/verify-identity")
def verify_identity(taxpayer_id):
    get_context()
    require_roles(["Screener", "SiteCoordinator"])
    tp = require_entity(store.taxpayers, taxpayer_id)
    body = parse_body(VERIFY_SCHEMA)
    if tp["identity_status"] != "UNVERIFIED":
        # VERIFIED is terminal for identity (PRD §3.3).
        raise ApiError("ERR_INVALID_TRANSITION", 409,
                       "Taxpayer identity is already VERIFIED")
    tp["identity_status"] = "VERIFIED"
    tp["id_document_type"] = body["id_document_type"]
    db.touch(tp)
    return ok(taxpayer_json(tp))
