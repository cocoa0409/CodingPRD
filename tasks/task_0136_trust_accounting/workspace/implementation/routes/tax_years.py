"""TaxYear endpoints + closing/amend lifecycle."""
from __future__ import annotations

from flask import Blueprint, g

from db import store
from middleware import require_auth
from response import success
from services.serializers import tax_year_view
from services.trust_engine import (
    amend_tax_year,
    begin_close_tax_year,
    finalize_tax_year,
    open_tax_year,
)

from routes._helpers import (
    enforce_grantor_owns_trust,
    enforce_trustee_is_under_trust,
    get_json,
    get_tax_year_or_404,
    get_trust_or_404,
    require_int,
)

bp = Blueprint("tax_years", __name__)


@bp.post("/trusts/<trust_id>/tax-years")
@require_auth(["Trustee", "TaxPreparer"])
def open_year_route(trust_id):
    body = get_json()
    calendar_year = require_int(body, "calendar_year")
    with store.lock:
        t = get_trust_or_404(trust_id)
        if g.role == "Trustee":
            enforce_trustee_is_under_trust(t)
        ty = open_tax_year(t, calendar_year=calendar_year)
        return success(tax_year_view(ty), 201)


@bp.get("/trusts/<trust_id>/tax-years/<tax_year_id>")
@require_auth(["Grantor", "Trustee", "TaxPreparer", "Auditor"])
def read_tax_year(trust_id, tax_year_id):
    with store.lock:
        t = get_trust_or_404(trust_id)
        if g.role == "Grantor":
            enforce_grantor_owns_trust(t)
        if g.role == "Trustee":
            enforce_trustee_is_under_trust(t)
        ty = get_tax_year_or_404(t, tax_year_id)
        return success(tax_year_view(ty), 200)


@bp.post("/trusts/<trust_id>/tax-years/<tax_year_id>/begin-close")
@require_auth(["TaxPreparer"])
def begin_close_route(trust_id, tax_year_id):
    with store.lock:
        t = get_trust_or_404(trust_id)
        ty = get_tax_year_or_404(t, tax_year_id)
        begin_close_tax_year(t, ty)
        return success(tax_year_view(ty), 200)


@bp.post("/trusts/<trust_id>/tax-years/<tax_year_id>/finalize")
@require_auth(["TaxPreparer"])
def finalize_route(trust_id, tax_year_id):
    with store.lock:
        t = get_trust_or_404(trust_id)
        ty = get_tax_year_or_404(t, tax_year_id)
        finalize_tax_year(t, ty)
        return success(tax_year_view(ty), 200)


@bp.post("/trusts/<trust_id>/tax-years/<tax_year_id>/amend")
@require_auth(["TaxPreparer"])
def amend_route(trust_id, tax_year_id):
    with store.lock:
        t = get_trust_or_404(trust_id)
        ty = get_tax_year_or_404(t, tax_year_id)
        amend_tax_year(t, ty)
        return success(tax_year_view(ty), 200)
