"""K-1 read endpoints (list + single read)."""
from __future__ import annotations

from flask import Blueprint, g, request

from db import store
from errors import err_forbidden
from middleware import require_auth
from response import list_success, success
from services.serializers import k1_view

from routes._helpers import (
    enforce_grantor_owns_trust,
    enforce_trustee_is_under_trust,
    get_k1_or_404,
    get_tax_year_or_404,
    get_trust_or_404,
    paginate,
    parse_pagination,
    sort_by_created_at,
)

bp = Blueprint("k1s", __name__)


@bp.get("/trusts/<trust_id>/tax-years/<tax_year_id>/k1s")
@require_auth(["Grantor", "Trustee", "TaxPreparer", "Auditor", "Beneficiary"])
def list_k1s(trust_id, tax_year_id):
    with store.lock:
        t = get_trust_or_404(trust_id)
        if g.role == "Grantor":
            enforce_grantor_owns_trust(t)
        if g.role == "Trustee":
            enforce_trustee_is_under_trust(t)
        ty = get_tax_year_or_404(t, tax_year_id)
        items = [k for k in store.k1s.values() if k["tax_year_id"] == ty["id"]]
        # Beneficiary role: server-side filter to their own K-1s.
        if g.role == "Beneficiary":
            items = [k for k in items if k["beneficiary_id"] == g.user_id]
        # Filters.
        status_q = request.args.get("status")
        if status_q:
            items = [k for k in items if k["status"] == status_q]
        bene_q = request.args.get("beneficiary_id")
        if bene_q:
            items = [k for k in items if k["beneficiary_id"] == bene_q]
        items = sort_by_created_at(items)
        limit, offset = parse_pagination()
        total = len(items)
        page = paginate(items, limit, offset)
        return list_success([k1_view(k) for k in page], limit, offset, total, 200)


@bp.get("/trusts/<trust_id>/tax-years/<tax_year_id>/k1s/<k1_id>")
@require_auth(["Grantor", "Trustee", "TaxPreparer", "Auditor", "Beneficiary"])
def read_k1(trust_id, tax_year_id, k1_id):
    with store.lock:
        t = get_trust_or_404(trust_id)
        if g.role == "Grantor":
            enforce_grantor_owns_trust(t)
        if g.role == "Trustee":
            enforce_trustee_is_under_trust(t)
        ty = get_tax_year_or_404(t, tax_year_id)
        k = get_k1_or_404(ty, k1_id)
        if g.role == "Beneficiary" and k["beneficiary_id"] != g.user_id:
            raise err_forbidden("Beneficiary may only read own K-1.")
        return success(k1_view(k), 200)
