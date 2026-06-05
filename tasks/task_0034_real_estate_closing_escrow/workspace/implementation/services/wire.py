"""WireInstruction service — PROVIDED -> VERIFIED -> LOCKED (or -> REJECTED)."""
from __future__ import annotations

from typing import Any

from flask import g

from clock import CLOCK
from db import DB_INSTANCE, new_id
from errors import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_WIRE_SOD_VIOLATION,
    err,
)
from lookup import get_fk_agreement, get_wire_or_404
from validation import require_enum, require_fields, require_str


WIRE_PARTIES = {"BUYER", "SELLER", "LENDER", "EXCHANGE_ACCOMMODATOR"}


def create_wire(body: dict) -> dict:
    require_fields(body, [
        "agreement_id",
        "party",
        "beneficiary_bank_name",
        "beneficiary_account_last4",
        "routing_number",
    ])
    agreement_id = require_str(body, "agreement_id")
    party = require_enum(body, "party", WIRE_PARTIES)
    bank = require_str(body, "beneficiary_bank_name")
    last4 = require_str(body, "beneficiary_account_last4")
    routing = require_str(body, "routing_number")

    get_fk_agreement(agreement_id)

    now = CLOCK.now()
    w = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "agreement_id": agreement_id,
        "party": party,
        "beneficiary_bank_name": bank,
        "beneficiary_account_last4": last4,
        "routing_number": routing,
        "voice_callback_completed": False,
        "callback_verified_at": None,
        "callback_verifier_id": None,
        "status": "PROVIDED",
    }
    DB_INSTANCE.wire_instructions[w["id"]] = w
    return w


def callback_verify(w_id: str, body: dict) -> dict:
    w = get_wire_or_404(w_id)
    if w["status"] != "PROVIDED":
        raise err(ERR_INVALID_STATE, "wire instruction is not in PROVIDED")
    require_fields(body, ["verifier_id", "voice_callback_reference"])
    verifier_id = require_str(body, "verifier_id")
    voice_ref = require_str(body, "voice_callback_reference")
    # PRD §2.6: verifier_id must equal the acting X-User-ID.
    if verifier_id != g.user_id:
        raise err(ERR_INVALID_REQUEST, "verifier_id must equal the acting X-User-ID")
    if not voice_ref:
        raise err(ERR_INVALID_REQUEST, "voice_callback_reference must be non-empty")
    w["voice_callback_completed"] = True
    w["callback_verified_at"] = CLOCK.now()
    w["callback_verifier_id"] = g.user_id
    w["status"] = "VERIFIED"
    w["updated_at"] = CLOCK.now()
    w["version"] += 1
    return w


def lock_wire(w_id: str) -> dict:
    w = get_wire_or_404(w_id)
    if w["status"] != "VERIFIED":
        raise err(ERR_INVALID_STATE, "wire instruction is not in VERIFIED")
    # Priority 8 SoD: acting X-User-ID != callback_verifier_id.
    if w["callback_verifier_id"] == g.user_id:
        raise err(ERR_WIRE_SOD_VIOLATION, "verifier cannot lock their own callback")
    w["status"] = "LOCKED"
    w["updated_at"] = CLOCK.now()
    w["version"] += 1
    return w


def reject_wire(w_id: str) -> dict:
    w = get_wire_or_404(w_id)
    if w["status"] not in ("PROVIDED", "VERIFIED"):
        raise err(ERR_INVALID_STATE, "wire instruction must be PROVIDED or VERIFIED to reject")
    if w["status"] == "VERIFIED":
        # Compensating action: clear callback evidence.
        w["voice_callback_completed"] = False
        w["callback_verified_at"] = None
        w["callback_verifier_id"] = None
    w["status"] = "REJECTED"
    w["updated_at"] = CLOCK.now()
    w["version"] += 1
    return w


def list_wires(filters: dict[str, Any]) -> list[dict]:
    items = list(DB_INSTANCE.wire_instructions.values())
    if filters.get("agreement_id"):
        items = [w for w in items if w["agreement_id"] == filters["agreement_id"]]
    if filters.get("party"):
        items = [w for w in items if w["party"] == filters["party"]]
    if filters.get("status"):
        items = [w for w in items if w["status"] == filters["status"]]
    items.sort(key=lambda w: w["created_at"])
    return items
