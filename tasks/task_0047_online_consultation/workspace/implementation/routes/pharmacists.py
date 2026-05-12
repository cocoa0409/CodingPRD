"""Pharmacist endpoints."""

from __future__ import annotations

from flask import Blueprint, request, g

import db
from middleware import require_role
from response import success
from errors import AppError, ERR_NOT_FOUND, ERR_FORBIDDEN
from config import ROLE_PHARMACIST, ROLE_ADMIN
from services.serializers import serialize


bp = Blueprint("pharmacists", __name__, url_prefix="/consultation/pharmacists")


def _pharm_or_404(pid):
    row = db.find_by_id("pharmacists", pid)
    if not row:
        raise AppError(ERR_NOT_FOUND, "Pharmacist not found.", 404)
    return row


@bp.post("")
def create_pharmacist():
    require_role(ROLE_ADMIN)
    body = request.get_json(silent=True) or {}
    record = {
        "full_name": body.get("full_name"),
        "license_number": body.get("license_number"),
        "status": body.get("status") or "ACTIVE",
    }
    row = db.insert("pharmacists", record)
    return success(serialize(row), 201)


@bp.get("/<pid>")
def get_pharmacist(pid):
    require_role(ROLE_PHARMACIST, ROLE_ADMIN)
    row = _pharm_or_404(pid)
    return success(serialize(row), 200)
