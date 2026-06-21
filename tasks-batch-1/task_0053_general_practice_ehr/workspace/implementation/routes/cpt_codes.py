"""CPT/HCPCS billing code endpoints (PRD §3.3)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from db import now_iso, new_uuid
from errors import APIError, ERR_DUPLICATE_CPT_CODE, ERR_INVALID_REQUEST
from middleware import require
from response import ok_array, ok_object
from routes.common import lookup_or_404, paginate, parse_pagination, sort_by_created
from services import derive
from validation import get_body, optional_bool, require_enum, require_int, require_str

bp = Blueprint("cpt_codes", __name__)

CATEGORIES = {"EM", "PREVENTIVE", "VACCINE_ADMIN", "PROCEDURE"}


@bp.route("/cpt-codes", methods=["POST"])
def create_cpt_code():
    require(["Biller"])
    body = get_body()
    code = require_str(body, "code")
    short_description = require_str(body, "short_description")
    category = require_enum(body, "category", CATEGORIES)
    base_fee_cents = require_int(body, "base_fee_cents", minimum=0)
    requires_em_level = optional_bool(body, "requires_em_level", default=False)

    if len(code) != 5:
        raise APIError(ERR_INVALID_REQUEST, 422, "code must be exactly 5 characters")

    # Uniqueness (priority 16) — ERR_DUPLICATE_CPT_CODE.
    for c in db.cpt_codes.values():
        if c["code"] == code:
            raise APIError(ERR_DUPLICATE_CPT_CODE, 409, "code already registered")

    # CptCode carries only id and created_at (no version / updated_at) — PRD §2.4.
    rec = {
        "id": new_uuid(),
        "created_at": now_iso(),
        "code": code,
        "short_description": short_description,
        "category": category,
        "base_fee_cents": base_fee_cents,
        "requires_em_level": requires_em_level,
    }
    db.cpt_codes[rec["id"]] = rec
    return ok_object(derive.serialize_cpt_code(rec), 201)


@bp.route("/cpt-codes/<cid>", methods=["GET"])
def get_cpt_code(cid):
    require(["Biller", "Provider", "FrontDesk"])
    rec = lookup_or_404(db.cpt_codes, cid, "CptCode")
    return ok_object(derive.serialize_cpt_code(rec), 200)


@bp.route("/cpt-codes", methods=["GET"])
def list_cpt_codes():
    require(["Biller", "Provider", "FrontDesk"])
    limit, offset = parse_pagination()
    items = list(db.cpt_codes.values())
    category = request.args.get("category")
    if category is not None:
        items = [c for c in items if c["category"] == category]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return ok_array([derive.serialize_cpt_code(c) for c in window], limit, offset, total)
