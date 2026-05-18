"""Taxpayer routes (PRD §3.1, §3.11)."""
from __future__ import annotations

import re

from flask import Blueprint, g

from config import (
    ACCOUNT_ACTIVE,
    ACCOUNT_LOCKED,
    ROLE_IRSADJUDICATOR,
    ROLE_TAXPAYER,
)
from db import store
from errors import (
    err_invalid_input,
    err_invalid_state,
)
from middleware import require_auth
from response import success
from services import engine
from services.audit import append_audit
from utils import is_nonempty_str, new_uuid

from routes._helpers import (
    enforce_taxpayer_self,
    get_json,
    get_taxpayer_or_404,
)


bp = Blueprint("taxpayers", __name__)


_SSN4_RE = re.compile(r"^\d{4}$")
_DOB_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_filing_address(addr):
    if not isinstance(addr, dict):
        raise err_invalid_input("filing_address must be an object with street, city, state, zip")
    for field in ("street", "city", "state", "zip"):
        if not is_nonempty_str(addr.get(field)):
            raise err_invalid_input(f"filing_address.{field} is required")


def _serialize_taxpayer(tp: dict) -> dict:
    return {
        "id": tp["id"],
        "created_at": tp["created_at"],
        "updated_at": tp["updated_at"],
        "version": tp["version"],
        "ssn_last4": tp["ssn_last4"],
        "full_name": tp["full_name"],
        "date_of_birth": tp["date_of_birth"],
        "filing_address": tp["filing_address"],
        "is_blind": tp["is_blind"],
        "account_status": tp["account_status"],
    }


# ── POST /taxpayers ─────────────────────────────────────────────────────


@bp.post("/taxpayers")
@require_auth([ROLE_TAXPAYER, ROLE_IRSADJUDICATOR])
def create_taxpayer():
    body = get_json()
    ssn4 = body.get("ssn_last4")
    full_name = body.get("full_name")
    dob = body.get("date_of_birth")
    addr = body.get("filing_address")
    is_blind = body.get("is_blind", False)

    if not isinstance(ssn4, str) or not _SSN4_RE.fullmatch(ssn4):
        raise err_invalid_input("ssn_last4 must be exactly 4 digits")
    if not is_nonempty_str(full_name):
        raise err_invalid_input("full_name is required")
    if not isinstance(dob, str) or not _DOB_RE.fullmatch(dob):
        raise err_invalid_input("date_of_birth must be in YYYY-MM-DD form")
    _validate_filing_address(addr)
    if not isinstance(is_blind, bool):
        raise err_invalid_input("is_blind must be a boolean")

    with store.lock:
        tp = {
            "id": new_uuid(),
            "ssn_last4": ssn4,
            "full_name": full_name,
            "date_of_birth": dob,
            "filing_address": addr,
            "is_blind": is_blind,
            "account_status": ACCOUNT_ACTIVE,
        }
        engine.stamp_create(tp)
        store.taxpayers[tp["id"]] = tp

    return success(_serialize_taxpayer(tp), 201)


# ── GET /taxpayers/{id} ─────────────────────────────────────────────────


@bp.get("/taxpayers/<taxpayer_id>")
@require_auth([ROLE_TAXPAYER, ROLE_IRSADJUDICATOR])
def get_taxpayer(taxpayer_id):
    tp = get_taxpayer_or_404(taxpayer_id)
    enforce_taxpayer_self(tp)
    return success(_serialize_taxpayer(tp), 200)


# ── POST /taxpayers/{id}/compliance-lock ────────────────────────────────


@bp.post("/taxpayers/<taxpayer_id>/compliance-lock")
@require_auth([ROLE_IRSADJUDICATOR])
def compliance_lock(taxpayer_id):
    body = get_json()
    reason = body.get("reason")

    with store.lock:
        tp = get_taxpayer_or_404(taxpayer_id)
        if tp["account_status"] != ACCOUNT_ACTIVE:
            raise err_invalid_state("Taxpayer is not ACTIVE.")
        tp["account_status"] = ACCOUNT_LOCKED
        engine.stamp_update(tp)

        cancelled = engine.cascade_compliance_lock(tp)

        append_audit(
            actor_role=g.role,
            actor_id=g.user_id,
            action="COMPLIANCE_LOCK",
            target_entity="Taxpayer",
            target_id=tp["id"],
            payload={
                "reason": reason,
                "cancelled_payment_ids": [p["id"] for p in cancelled],
            },
        )

    return success(_serialize_taxpayer(tp), 200)


# ── POST /taxpayers/{id}/compliance-unlock ──────────────────────────────


@bp.post("/taxpayers/<taxpayer_id>/compliance-unlock")
@require_auth([ROLE_IRSADJUDICATOR])
def compliance_unlock(taxpayer_id):
    with store.lock:
        tp = get_taxpayer_or_404(taxpayer_id)
        if tp["account_status"] != ACCOUNT_LOCKED:
            raise err_invalid_state("Taxpayer is not LOCKED.")
        tp["account_status"] = ACCOUNT_ACTIVE
        engine.stamp_update(tp)

        append_audit(
            actor_role=g.role,
            actor_id=g.user_id,
            action="COMPLIANCE_UNLOCK",
            target_entity="Taxpayer",
            target_id=tp["id"],
            payload={},
        )

    return success(_serialize_taxpayer(tp), 200)
