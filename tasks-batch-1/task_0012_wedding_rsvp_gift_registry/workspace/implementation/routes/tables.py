"""GET /tables/{id}."""
from __future__ import annotations

from flask import Blueprint

import db
from middleware import require_auth, current_role
from response import ok_object
from services.wedding import get_table_or_404, assert_couple_owns

bp = Blueprint("tables", __name__)


@bp.route("/tables/<tid>", methods=["GET"])
def get_table(tid):
    require_auth(["Couple", "PlatformAdmin"])()
    t = get_table_or_404(tid)
    if current_role() == "Couple":
        w = db.weddings.get(t["wedding_id"])
        if w:
            assert_couple_owns(w)
    return ok_object(t)
