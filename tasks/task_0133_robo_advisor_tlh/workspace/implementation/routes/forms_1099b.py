"""1099-B form endpoints."""
from __future__ import annotations

from flask import Blueprint, g

from db import store
from errors import (
    err_auth_forbidden,
    err_form_already_exists,
    err_invalid_state,
    err_resource_not_found,
)
from middleware import require_auth
from response import success
from routes._helpers import get_json
from services.engine import (
    assemble_1099b,
    issue_1099b,
    stamp_create,
    void_1099b,
)
from services.serializers import serialize_form_1099b

bp = Blueprint("forms_1099b", __name__)


def _get_client_or_404(client_id):
    c = store.clients.get(client_id)
    if c is None:
        raise err_resource_not_found("Client not found.")
    return c


def _get_form_under_client_or_404(client_id, form_id):
    f = store.forms_1099b.get(form_id)
    if not f or f["client_id"] != client_id:
        raise err_resource_not_found("Form1099B not found under this client.")
    return f


@bp.post("/clients/<client_id>/forms-1099b")
@require_auth(["TaxAdmin"])
def create_form(client_id):
    _get_client_or_404(client_id)
    body = get_json()
    tax_year = body.get("tax_year")
    if tax_year is None or isinstance(tax_year, bool) or not isinstance(tax_year, int):
        raise err_invalid_state("tax_year must be an integer.")
    # Uniqueness on (client_id, tax_year).
    for f in store.forms_1099b.values():
        if f["client_id"] == client_id and f["tax_year"] == tax_year:
            raise err_form_already_exists()

    with store.lock:
        f = {
            "client_id": client_id,
            "tax_year": tax_year,
            "short_term_proceeds_cents": 0,
            "short_term_cost_basis_cents": 0,
            "short_term_realized_gain_loss_cents": 0,
            "long_term_proceeds_cents": 0,
            "long_term_cost_basis_cents": 0,
            "long_term_realized_gain_loss_cents": 0,
            "total_disallowed_wash_sale_cents": 0,
            "status": "DRAFT",
            "issued_at": None,
        }
        stamp_create(f)
        store.forms_1099b[f["id"]] = f
        assemble_1099b(f)
    return success(serialize_form_1099b(f), 201)


@bp.get("/clients/<client_id>/forms-1099b/<form_id>")
@require_auth(["TaxAdmin", "ClientUser"])
def get_form(client_id, form_id):
    c = _get_client_or_404(client_id)
    if g.role == "ClientUser" and g.user_id != client_id:
        raise err_auth_forbidden("ClientUser may only access their own forms.")
    f = _get_form_under_client_or_404(client_id, form_id)
    if f["status"] == "DRAFT":
        with store.lock:
            assemble_1099b(f)
    return success(serialize_form_1099b(f))


@bp.post("/clients/<client_id>/forms-1099b/<form_id>/issue")
@require_auth(["TaxAdmin"])
def issue_form(client_id, form_id):
    c = _get_client_or_404(client_id)
    f = _get_form_under_client_or_404(client_id, form_id)
    with store.lock:
        issue_1099b(f, c)
    return success(serialize_form_1099b(f))


@bp.post("/clients/<client_id>/forms-1099b/<form_id>/void")
@require_auth(["TaxAdmin"])
def void_form(client_id, form_id):
    _get_client_or_404(client_id)
    f = _get_form_under_client_or_404(client_id, form_id)
    with store.lock:
        void_1099b(f)
    return success(serialize_form_1099b(f))
