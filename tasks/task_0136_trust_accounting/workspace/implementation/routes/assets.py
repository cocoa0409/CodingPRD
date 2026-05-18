"""Asset endpoints."""
from __future__ import annotations

from flask import Blueprint, g

from db import store
from middleware import require_auth
from response import success
from services.serializers import asset_view
from services.trust_engine import add_asset

from routes._helpers import (
    ASSET_CLASSES,
    ASSET_CLASSIFICATIONS,
    enforce_grantor_owns_trust,
    enforce_trustee_is_under_trust,
    get_asset_or_404,
    get_json,
    get_trust_or_404,
    require_enum,
    require_money,
    require_string,
)

bp = Blueprint("assets", __name__)


@bp.post("/trusts/<trust_id>/assets")
@require_auth(["Grantor", "Trustee"])
def create_asset(trust_id):
    body = get_json()
    description = require_string(body, "description")
    asset_class = require_enum(body, "asset_class", ASSET_CLASSES)
    book_value = require_money(body, "book_value")
    classification = require_enum(body, "classification", ASSET_CLASSIFICATIONS)
    with store.lock:
        t = get_trust_or_404(trust_id)
        if g.role == "Grantor":
            enforce_grantor_owns_trust(t)
        if g.role == "Trustee":
            enforce_trustee_is_under_trust(t)
        a = add_asset(
            t,
            description=description,
            asset_class=asset_class,
            book_value=book_value,
            classification=classification,
        )
        return success(asset_view(a), 201)


@bp.get("/trusts/<trust_id>/assets/<asset_id>")
@require_auth(["Grantor", "Trustee", "TaxPreparer", "Auditor"])
def read_asset(trust_id, asset_id):
    with store.lock:
        t = get_trust_or_404(trust_id)
        if g.role == "Grantor":
            enforce_grantor_owns_trust(t)
        if g.role == "Trustee":
            enforce_trustee_is_under_trust(t)
        a = get_asset_or_404(t, asset_id)
        return success(asset_view(a), 200)
