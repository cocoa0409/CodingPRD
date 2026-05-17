"""Borrower routes."""
from __future__ import annotations

from flask import Blueprint, g

from db import store
from errors import ApiError, err_forbidden, err_resource_not_found
from middleware import require_auth
from response import success
from services.serializers import borrower_view
from utils import new_uuid

from routes._helpers import get_json

bp = Blueprint("borrowers", __name__)


@bp.post("/borrowers")
@require_auth(["Servicer", "PlatformAdmin"])
def create_borrower():
    body = get_json()
    full_name = body.get("full_name")
    email = body.get("email")
    if not isinstance(full_name, str) or not full_name.strip() or len(full_name) > 200:
        raise ApiError("ERR_INVALID_STATE", 409, "full_name must be non-empty and ≤200 chars")
    if not isinstance(email, str) or not email.strip():
        raise ApiError("ERR_INVALID_STATE", 409, "email must be a non-empty string")
    now = store.now()
    bid = new_uuid()
    record = {
        "id": bid,
        "full_name": full_name,
        "email": email,
        "hardship_attested_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.borrowers[bid] = record
    return success(borrower_view(record), 201)


@bp.post("/borrowers/<bid>/hardship-attestation")
@require_auth(["Servicer", "Borrower"])
def hardship_attestation(bid):
    b = store.borrowers.get(bid)
    if b is None:
        raise err_resource_not_found("Borrower not found.")
    if g.role == "Borrower" and g.user_id != bid:
        raise err_forbidden("Borrower can only attest their own affidavit.")
    now = store.now()
    b["hardship_attested_at"] = now
    b["updated_at"] = now
    b["version"] += 1
    return success(borrower_view(b), 200)


@bp.get("/borrowers/<bid>")
@require_auth(["Servicer", "PlatformAdmin", "Borrower"])
def get_borrower(bid):
    b = store.borrowers.get(bid)
    if b is None:
        raise err_resource_not_found("Borrower not found.")
    if g.role == "Borrower" and g.user_id != bid:
        raise err_forbidden("Borrower can only view their own record.")
    return success(borrower_view(b), 200)
