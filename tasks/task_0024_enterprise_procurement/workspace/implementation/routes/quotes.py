"""Quote retrieval endpoint (creation lives under requirements)."""

from __future__ import annotations

from flask import Blueprint, jsonify

from db import serialize
from middleware import enforce_role, require_roles
from response import success_object
from services.lookups import find_quote

bp = Blueprint("quotes", __name__)


@bp.get("/quotes/<rid>")
@require_roles("Buyer", "FinanceApprover")
def get_quote(rid: str):
    row = find_quote(rid)
    enforce_role()
    return jsonify(success_object(serialize(row))), 200
