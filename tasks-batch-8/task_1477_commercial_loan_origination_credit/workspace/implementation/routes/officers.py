"""Bank officers and officer-scoped reverse lookups (audit spine)."""
from flask import Blueprint

import serialize
from db import STORE, new_entity
from middleware import require_roles, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list
from validation import get_body, req_str

bp = Blueprint("officers", __name__)


@bp.post("/credit/bank-officers")
def create_officer():
    require_roles("BankAdmin")
    body = get_body()
    full_name = req_str(body, "full_name")
    officer = new_entity()
    officer['full_name'] = full_name
    STORE.bank_officers[officer['id']] = officer
    return success_object(serialize.bank_officer(officer), status=201)


@bp.get("/credit/bank-officers/<oid>")
def get_officer(oid):
    require_roles(*ALL_ROLES)
    officer = get_or_404(STORE.bank_officers, oid, "BankOfficer")
    return success_object(serialize.bank_officer(officer))


@bp.get("/credit/bank-officers/<oid>/policy-exceptions")
def officer_policy_exceptions(oid):
    require_roles(*ALL_ROLES)
    get_or_404(STORE.bank_officers, oid, "BankOfficer")
    items = [e for e in STORE.policy_exceptions.values() if e['waived_by_officer_id'] == oid]
    return render_list(items, serialize.policy_exception)


@bp.get("/credit/bank-officers/<oid>/document-checklist-items")
def officer_checklist_items(oid):
    require_roles(*ALL_ROLES)
    get_or_404(STORE.bank_officers, oid, "BankOfficer")
    items = [i for i in STORE.document_checklist_items.values() if i['waived_by_officer_id'] == oid]
    return render_list(items, serialize.document_checklist_item)


@bp.get("/credit/bank-officers/<oid>/funding-authorizations")
def officer_funding_authorizations(oid):
    require_roles(*ALL_ROLES)
    get_or_404(STORE.bank_officers, oid, "BankOfficer")
    items = [f for f in STORE.funding_authorizations.values()
             if f['requested_by_officer_id'] == oid or f['authorized_by_officer_id'] == oid]
    return render_list(items, serialize.funding_authorization)
