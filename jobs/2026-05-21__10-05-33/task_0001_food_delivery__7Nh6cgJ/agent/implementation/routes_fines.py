"""Fine endpoints."""

from __future__ import annotations

from flask import request

from auth import require_role
from envelope import list_success, success
from errors import APIError
from fines_logic import waive_fine
from store import STORE
from validation import parse_pagination

VALID_SUBJECT_TYPES = {"RIDER", "RESTAURANT", "CUSTOMER"}
VALID_SETTLEMENT = {"PENDING", "SETTLED", "WAIVED"}


def _serialize(f: dict) -> dict:
    return {
        "id": f["id"],
        "subject_type": f["subject_type"],
        "subject_id": f["subject_id"],
        "reason": f["reason"],
        "amount_cents": f["amount_cents"],
        "settlement_status": f["settlement_status"],
        "created_at": f["created_at"],
    }


def _can_read_subject(role: str, user_id: str, fine: dict) -> bool:
    if role in ("PlatformAdmin", "CustomerService"):
        return True
    if role == "Rider":
        return fine["subject_type"] == "RIDER" and fine["subject_id"] == user_id
    if role == "Restaurant":
        return fine["subject_type"] == "RESTAURANT" and fine["subject_id"] == user_id
    if role == "Customer":
        return fine["subject_type"] == "CUSTOMER" and fine["subject_id"] == user_id
    return False


def register(app):
    @app.get("/api/fines/<fid>")
    def read_fine(fid: str):
        user_id, role = require_role({"PlatformAdmin", "CustomerService", "Rider", "Restaurant", "Customer"})
        with STORE.lock:
            f = STORE.fines.get(fid)
            if f is None:
                raise APIError("ERR_NOT_FOUND", "No such fine.")
            if not _can_read_subject(role, user_id, f):
                raise APIError("ERR_FORBIDDEN")
            return success(_serialize(f))

    @app.get("/api/fines")
    def list_fines():
        user_id, role = require_role({"PlatformAdmin", "CustomerService", "Rider", "Restaurant", "Customer"})
        limit, offset = parse_pagination()
        subject_type = request.args.get("subject_type")
        subject_id = request.args.get("subject_id")
        settlement_status = request.args.get("settlement_status")
        if subject_type is not None and subject_type not in VALID_SUBJECT_TYPES:
            raise APIError("ERR_VALIDATION", "Invalid subject_type filter.")
        if settlement_status is not None and settlement_status not in VALID_SETTLEMENT:
            raise APIError("ERR_VALIDATION", "Invalid settlement_status filter.")

        # Restricted roles must filter to themselves.
        if role in ("Rider", "Restaurant", "Customer"):
            self_subject = {"Rider": "RIDER", "Restaurant": "RESTAURANT", "Customer": "CUSTOMER"}[role]
            if subject_type and subject_type != self_subject:
                raise APIError("ERR_FORBIDDEN")
            if subject_id and subject_id != user_id:
                raise APIError("ERR_FORBIDDEN")
            subject_type = self_subject
            subject_id = user_id

        with STORE.lock:
            items = list(STORE.fines.values())
            if subject_type:
                items = [f for f in items if f["subject_type"] == subject_type]
            if subject_id:
                items = [f for f in items if f["subject_id"] == subject_id]
            if settlement_status:
                items = [f for f in items if f["settlement_status"] == settlement_status]
            items.sort(key=lambda f: f["created_at"])
            page = items[offset:offset + limit]
            return list_success([_serialize(f) for f in page], limit, offset, len(items))

    @app.post("/api/fines/<fid>/waive")
    def waive(fid: str):
        require_role({"CustomerService", "PlatformAdmin"})
        with STORE.lock:
            f = STORE.fines.get(fid)
            if f is None:
                raise APIError("ERR_NOT_FOUND", "No such fine.")
            waive_fine(f)
            return success(_serialize(f))
