"""Tax bracket table routes."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import (
    ROLE_PAYROLL_MANAGER,
    ROLE_PAYROLL_SPECIALIST,
    ROLE_TREASURER,
    require_roles,
)
from ..clock import now_iso
from ..errors import err_invalid_request
from ..helpers import (
    assert_enum,
    assert_integer,
    new_uuid,
    paginate,
    parse_pagination,
    require_json_object,
)
from ..responses import created, listing
from ..services.serialize import serialize_tax_bracket
from ..store import store

bp = Blueprint("tax_brackets", __name__)

JURISDICTIONS = ["FEDERAL", "CA", "NY", "TX", "IL", "PA", "NYC", "PHL"]
FILING_STATUSES = ["SINGLE", "MARRIED_JOINT", "HEAD_OF_HOUSEHOLD", "ANY"]


@bp.post("/tax-bracket-tables")
@require_roles(ROLE_PAYROLL_MANAGER)
def create_tax_bracket(**_kw):
    body = require_json_object()
    jurisdiction = assert_enum(body.get("jurisdiction"), "jurisdiction", JURISDICTIONS)
    filing_status = assert_enum(body.get("filing_status"), "filing_status", FILING_STATUSES)
    tax_year = assert_integer(body.get("tax_year"), "tax_year", minimum=1900, maximum=9999)
    brackets = body.get("brackets")
    if not isinstance(brackets, list) or not brackets:
        raise err_invalid_request("brackets must be a non-empty array")
    # Lightly validate bracket shapes
    normalized = []
    for b in brackets:
        if not isinstance(b, dict):
            raise err_invalid_request("each bracket must be an object")
        lo = b.get("lower_cents")
        hi = b.get("upper_cents_or_null")
        rate = b.get("rate_bps")
        if not isinstance(lo, int) or isinstance(lo, bool):
            raise err_invalid_request("bracket.lower_cents must be an integer")
        if hi is not None and (not isinstance(hi, int) or isinstance(hi, bool)):
            raise err_invalid_request("bracket.upper_cents_or_null must be an integer or null")
        if not isinstance(rate, int) or isinstance(rate, bool):
            raise err_invalid_request("bracket.rate_bps must be an integer")
        normalized.append({"lower_cents": lo, "upper_cents_or_null": hi, "rate_bps": rate})

    s = store()
    with s.lock:
        ts = now_iso()
        t_id = new_uuid()
        t = {
            "id": t_id,
            "jurisdiction": jurisdiction,
            "filing_status": filing_status,
            "tax_year": tax_year,
            "brackets": normalized,
            "created_at": ts,
            "created_seq": s.next_seq(),
        }
        s.tax_brackets[t_id] = t
    return created(serialize_tax_bracket(t))


@bp.get("/tax-bracket-tables")
@require_roles(ROLE_PAYROLL_SPECIALIST, ROLE_PAYROLL_MANAGER, ROLE_TREASURER)
def list_tax_brackets(**_kw):
    limit, offset = parse_pagination()
    jur = request.args.get("jurisdiction")
    ty = request.args.get("tax_year")
    with store().lock:
        items = list(store().tax_brackets.values())
        if jur:
            items = [t for t in items if t["jurisdiction"] == jur]
        if ty is not None:
            try:
                tyi = int(ty)
                items = [t for t in items if t["tax_year"] == tyi]
            except (TypeError, ValueError):
                pass
        items.sort(key=lambda t: (t["created_at"], t["created_seq"]))
        total = len(items)
        page = paginate(items, limit, offset)
        return listing([serialize_tax_bracket(t) for t in page], total, limit, offset)
