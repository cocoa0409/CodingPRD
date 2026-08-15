"""Performer endpoints."""

from flask import Blueprint, request

import db
from helpers import new_id, now_timestamp, require_enum, require_string, err_validation
from middleware import require_roles, ALL_ROLES
from response import success_object
from serializers import serialize, get_or_404

bp = Blueprint("performers", __name__)

UNION_CODES = {"SAG_AFTRA", "WGA", "DGA", "AFM", "IATSE"}


@bp.post("/payroll/performers")
def create_performer():
    require_roles({"PayrollAdmin"})
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_validation("Request body must be a JSON object")

    legal_name = require_string(body, "legal_name")
    primary_union_code = require_enum(body, "primary_union_code", UNION_CODES)
    tax_residency_state = require_string(body, "tax_residency_state")

    now = now_timestamp()
    record = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "legal_name": legal_name,
        "primary_union_code": primary_union_code,
        "tax_residency_state": tax_residency_state,
        "ytd_gross_cents": 0,
        "ytd_garnished_cents": 0,
    }
    db.performers[record["id"]] = record
    return success_object(serialize(record), 201)


@bp.get("/payroll/performers/<performer_id>")
def get_performer(performer_id):
    require_roles(ALL_ROLES)
    performer = get_or_404(db.performers, performer_id, "Performer")
    return success_object(serialize(performer), 200)
