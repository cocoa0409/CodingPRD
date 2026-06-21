"""Quote routes (read-only; PRD §3.4)."""
from flask import Blueprint, request

from db import db
from middleware import require_roles
from response import success
from services.common import get_or_404, parse_pagination, paginate
from services.models import serialize

bp = Blueprint("quotes", __name__)


@bp.get("/quotes")
@require_roles("Admin", "Agent", "Underwriter")
def list_quotes():
    limit, offset = parse_pagination()
    application_id = request.args.get("application_id")
    with db.lock:
        items = list(db.quotes.values())
        if application_id is not None:
            items = [q for q in items if q["application_id"] == application_id]
        window, meta = paginate(items, limit, offset)
        data = [serialize(q) for q in window]
    return success(data, status=200, list_meta=meta)


@bp.get("/quotes/<rid>")
@require_roles("Admin", "Agent", "Underwriter")
def get_quote(rid):
    with db.lock:
        rec = get_or_404("quote", rid)
        return success(serialize(rec), status=200)
