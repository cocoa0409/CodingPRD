"""Trustee endpoints."""
from __future__ import annotations

from flask import Blueprint

from db import store
from middleware import require_auth
from response import success
from services.serializers import trustee_view
from services.trust_engine import add_trustee

from routes._helpers import (
    enforce_grantor_owns_trust,
    enforce_trustee_is_under_trust,
    get_json,
    get_trust_or_404,
    get_trustee_or_404,
    require_bool,
    require_string,
)

bp = Blueprint("trustees", __name__)


@bp.post("/trusts/<trust_id>/trustees")
@require_auth(["Grantor"])
def create_trustee(trust_id):
    body = get_json()
    user_id = require_string(body, "user_id")
    full_name = require_string(body, "full_name")
    is_primary = require_bool(body, "is_primary", default=False)
    with store.lock:
        t = get_trust_or_404(trust_id)
        enforce_grantor_owns_trust(t)
        tr = add_trustee(t, user_id=user_id, full_name=full_name, is_primary=is_primary)
        return success(trustee_view(tr), 201)


@bp.get("/trusts/<trust_id>/trustees/<trustee_id>")
@require_auth(["Grantor", "Trustee", "TaxPreparer", "Auditor"])
def read_trustee(trust_id, trustee_id):
    with store.lock:
        t = get_trust_or_404(trust_id)
        from flask import g
        if g.role == "Grantor":
            enforce_grantor_owns_trust(t)
        if g.role == "Trustee":
            enforce_trustee_is_under_trust(t)
        tr = get_trustee_or_404(t, trustee_id)
        return success(trustee_view(tr), 200)
