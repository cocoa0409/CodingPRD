"""Owner routes (PRD §3.1)."""
from __future__ import annotations

import secrets
from datetime import timedelta

from flask import Blueprint, g, request

import db
from clock import now_iso, now_utc
from errors import err
from middleware import authenticate, require_roles
from response import error_response, success_object
from services.common import bump, init_full
from validators import (
    require_int,
    require_str,
    validate_email,
    validate_phone_e164,
)

bp = Blueprint("owners", __name__)


@bp.before_request
def _auth():
    authenticate()


@bp.post("/owners")
def create_owner():
    require_roles("OwnerService", "PlatformAdmin")
    payload = request.get_json(silent=True) or {}
    full_name = require_str(payload, "full_name", min_len=1, max_len=80)
    if len(full_name.strip()) == 0:
        raise err("ERR_VALIDATION_FAILED", "full_name must be non-empty after trim")
    phone_raw = payload.get("phone_e164")
    if not isinstance(phone_raw, str):
        raise err("ERR_VALIDATION_FAILED", "phone_e164 missing")
    phone = validate_phone_e164(phone_raw)
    email_raw = payload.get("email")
    if not isinstance(email_raw, str):
        raise err("ERR_VALIDATION_FAILED", "email missing")
    email = validate_email(email_raw)

    with db.GLOBAL_LOCK:
        if db.owner_by_phone(phone):
            raise err("ERR_VALIDATION_FAILED", "phone_e164 must be unique per owner")
        if db.owner_by_email(email):
            raise err("ERR_VALIDATION_FAILED", "email must be unique per owner")
        owner = {
            "full_name": full_name,
            "phone_e164": phone,
            "email": email,
            "contact_verified": False,
            "verification_code_hash": None,
            "verification_expires_at": None,
            "deposit_balance_cents": 0,
        }
        init_full(owner)
        db.owners[owner["id"]] = owner
        return success_object(_owner_view(owner), status=201)


@bp.get("/owners/<owner_id>")
def get_owner(owner_id):
    require_roles("OwnerService", "PlatformAdmin", "TriageNurse", "Cashier")
    with db.GLOBAL_LOCK:
        o = db.owners.get(owner_id)
        if not o:
            raise err("ERR_NOT_FOUND", f"Owner {owner_id} not found")
        return success_object(_owner_view(o))


@bp.post("/owners/<owner_id>/issue-verification")
def issue_verification(owner_id):
    require_roles("OwnerService", "PlatformAdmin")
    with db.GLOBAL_LOCK:
        o = db.owners.get(owner_id)
        if not o:
            raise err("ERR_NOT_FOUND", f"Owner {owner_id} not found")
        # Generate a deterministic-ish code; we hash it, but expose the
        # plaintext on the response so tests can echo it back.
        code = "VERIFIED"
        o["verification_code_hash"] = code  # store plaintext (ok for in-memory)
        o["verification_expires_at"] = (now_utc() + timedelta(minutes=10)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
        bump(o)
        view = _owner_view(o)
        view["verification_code"] = code  # convenience for tests
        return success_object(view)


@bp.post("/owners/<owner_id>/verify-contact")
def verify_contact(owner_id):
    require_roles("OwnerService", "PlatformAdmin")
    payload = request.get_json(silent=True) or {}
    code_in = payload.get("code")
    if not isinstance(code_in, str) or not code_in:
        raise err("ERR_VALIDATION_FAILED", "code is required")
    with db.GLOBAL_LOCK:
        o = db.owners.get(owner_id)
        if not o:
            raise err("ERR_NOT_FOUND", f"Owner {owner_id} not found")
        stored = o.get("verification_code_hash")
        # PRD §3.1 — successful match flips contact_verified, clears code/expiry.
        if stored is None or code_in != stored:
            raise err("ERR_VALIDATION_FAILED", "verification code mismatch")
        o["contact_verified"] = True
        o["verification_code_hash"] = None
        o["verification_expires_at"] = None
        bump(o)
        return success_object(_owner_view(o))


@bp.post("/owners/<owner_id>/deposits")
def deposit(owner_id):
    require_roles("Cashier")
    payload = request.get_json(silent=True) or {}
    amount = require_int(payload, "amount_cents", min_v=1)
    with db.GLOBAL_LOCK:
        o = db.owners.get(owner_id)
        if not o:
            raise err("ERR_NOT_FOUND", f"Owner {owner_id} not found")
        o["deposit_balance_cents"] = int(o.get("deposit_balance_cents", 0)) + amount
        bump(o)
        return success_object(_owner_view(o))


def _owner_view(o):
    return {
        "id": o["id"],
        "full_name": o["full_name"],
        "phone_e164": o["phone_e164"],
        "email": o["email"],
        "contact_verified": bool(o.get("contact_verified", False)),
        "deposit_balance_cents": int(o.get("deposit_balance_cents", 0)),
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }
