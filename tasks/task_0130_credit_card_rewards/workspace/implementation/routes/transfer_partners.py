"""TransferPartner routes."""
from __future__ import annotations

import re

from flask import Blueprint, request

from auth import require_roles
from constants import ROLE_CARDHOLDER, ROLE_PLATFORM_ADMIN
from errors import err
from response import ok_array, ok_object
from serializers import transfer_partner_view
from store import store
from utils import get_body, paginate, parse_pagination, require_int, require_str

bp = Blueprint("transfer_partners", __name__)

_CODE_RE = re.compile(r"^[A-Z0-9_]+$")
_VALID_TYPES = {"AIRLINE", "HOTEL"}


@bp.post("/transfer-partners")
@require_roles(ROLE_PLATFORM_ADMIN)
def post_partner():
    body = get_body(request)
    code = require_str(body, "code")
    partner_type = require_str(body, "partner_type")
    conversion_ratio = require_int(body, "conversion_ratio_points_per_unit")
    min_increment = require_int(body, "min_transfer_increment")
    is_active = body.get("is_active", True)
    if not isinstance(is_active, bool):
        raise err("ERR_VALIDATION", "is_active must be a boolean")

    if not _CODE_RE.match(code):
        raise err("ERR_VALIDATION", "code must match /^[A-Z0-9_]+$/")
    if code in store.partner_codes:
        raise err("ERR_VALIDATION", "code already registered")
    if partner_type not in _VALID_TYPES:
        raise err("ERR_VALIDATION", f"partner_type must be one of {sorted(_VALID_TYPES)}")
    if conversion_ratio < 1:
        raise err("ERR_VALIDATION", "conversion_ratio_points_per_unit must be >= 1")
    if min_increment < 1:
        raise err("ERR_VALIDATION", "min_transfer_increment must be >= 1")

    with store.lock:
        if code in store.partner_codes:
            raise err("ERR_VALIDATION", "code already registered")
        pid = store.new_id()
        iso = store.now_iso()
        rec = {
            "id": pid,
            "code": code,
            "partner_type": partner_type,
            "conversion_ratio_points_per_unit": conversion_ratio,
            "min_transfer_increment": min_increment,
            "is_active": is_active,
            "created_at": iso,
            "updated_at": iso,
            "version": 1,
        }
        store.transfer_partners[pid] = rec
        store.partner_codes.add(code)

    return ok_object(transfer_partner_view(rec), status=201)


@bp.get("/transfer-partners")
@require_roles(ROLE_CARDHOLDER, ROLE_PLATFORM_ADMIN)
def list_partners():
    rows = list(store.transfer_partners.values())
    type_q = request.args.get("partner_type")
    active_q = request.args.get("is_active")
    if type_q:
        rows = [r for r in rows if r["partner_type"] == type_q]
    if active_q is not None:
        if active_q.lower() in ("true", "1"):
            rows = [r for r in rows if r["is_active"] is True]
        elif active_q.lower() in ("false", "0"):
            rows = [r for r in rows if r["is_active"] is False]
        else:
            raise err("ERR_VALIDATION", "is_active must be true or false")
    rows.sort(key=lambda r: (r["created_at"], r["id"]))

    limit, offset = parse_pagination(request.args)
    page, pagination = paginate(rows, limit, offset)
    return ok_array([transfer_partner_view(r) for r in page], pagination)
