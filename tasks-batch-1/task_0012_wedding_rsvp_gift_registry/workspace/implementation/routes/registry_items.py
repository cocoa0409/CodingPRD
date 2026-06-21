"""RegistryItem routes: GET /registry-items/{id}."""
from __future__ import annotations

from flask import Blueprint

import db
from middleware import require_auth, current_role
from response import ok_object
from services.wedding import get_registry_item_or_404, assert_couple_owns

bp = Blueprint("registry_items", __name__)


@bp.route("/registry-items/<rid>", methods=["GET"])
def get_registry_item(rid):
    require_auth(["Couple", "PlatformIntegration", "PlatformAdmin"])()
    ri = get_registry_item_or_404(rid)
    if current_role() == "Couple":
        w = db.weddings.get(ri["wedding_id"])
        if w:
            assert_couple_owns(w)
    # "Settled view": omit pending_quantity per PRD §3.5.
    out = dict(ri)
    out.pop("pending_quantity", None)
    return ok_object(out)
