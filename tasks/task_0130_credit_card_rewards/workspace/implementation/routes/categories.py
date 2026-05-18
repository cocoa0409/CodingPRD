"""CashbackCategory routes."""
from __future__ import annotations

import re

from flask import Blueprint, request

from auth import require_roles
from constants import ROLE_CARDHOLDER, ROLE_PLATFORM_ADMIN
from errors import err
from response import ok_array, ok_object
from serializers import cashback_category_view
from store import store
from utils import get_body, paginate, parse_pagination, require_int, require_str

bp = Blueprint("categories", __name__)

_CODE_RE = re.compile(r"^[A-Z_]+$")
_VALID_TYPES = {"BASELINE", "FIXED_BONUS", "ROTATING_QUARTERLY"}


@bp.post("/cashback-categories")
@require_roles(ROLE_PLATFORM_ADMIN)
def post_category():
    body = get_body(request)
    code = require_str(body, "code")
    category_type = require_str(body, "category_type")
    base_rate_bps = require_int(body, "base_rate_bps")

    if not _CODE_RE.match(code):
        raise err("ERR_VALIDATION", "code must match /^[A-Z_]+$/")
    if code in store.category_codes:
        raise err("ERR_VALIDATION", "code already registered")
    if category_type not in _VALID_TYPES:
        raise err("ERR_VALIDATION", f"category_type must be one of {sorted(_VALID_TYPES)}")
    if not (0 <= base_rate_bps <= 10_000):
        raise err("ERR_VALIDATION", "base_rate_bps must be in [0, 10000]")

    with store.lock:
        if code in store.category_codes:
            raise err("ERR_VALIDATION", "code already registered")
        cid = store.new_id()
        iso = store.now_iso()
        rec = {
            "id": cid,
            "code": code,
            "category_type": category_type,
            "base_rate_bps": base_rate_bps,
            "requires_activation": category_type == "ROTATING_QUARTERLY",
            "created_at": iso,
            "updated_at": iso,
            "version": 1,
        }
        store.cashback_categories[cid] = rec
        store.category_codes.add(code)

    return ok_object(cashback_category_view(rec), status=201)


@bp.get("/cashback-categories")
@require_roles(ROLE_CARDHOLDER, ROLE_PLATFORM_ADMIN)
def list_categories():
    type_q = request.args.get("category_type")
    rows = list(store.cashback_categories.values())
    if type_q:
        rows = [r for r in rows if r["category_type"] == type_q]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))

    limit, offset = parse_pagination(request.args)
    page, pagination = paginate(rows, limit, offset)
    return ok_array([cashback_category_view(r) for r in page], pagination)
