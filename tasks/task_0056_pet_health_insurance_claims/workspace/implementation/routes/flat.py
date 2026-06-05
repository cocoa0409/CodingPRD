"""Flat fetch + filtered list routes for nested resources (PRD §4)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from middleware import require_auth
from response import ok_object, ok_array, paginate_params, slice_page
from services.common import get_or_404, sorted_by_creation
from services import calculations

bp = Blueprint("flat", __name__)

ALL_ROLES = ["PolicyHolder", "Underwriter", "ClaimsAdjuster"]


# ---- Policies --------------------------------------------------------------
@bp.get("/policies/<pid>")
def get_policy(pid):
    require_auth(ALL_ROLES)()
    pol = get_or_404(db.policies, pid, "Policy")
    return ok_object(pol, 200)


@bp.get("/policies")
def list_policies():
    require_auth(ALL_ROLES)()
    limit, offset = paginate_params(request.args)
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    items = list(db.policies.values())
    if account_id is not None:
        items = [p for p in items if p.get("account_id") == account_id]
    if status is not None:
        items = [p for p in items if p.get("status") == status]
    items = sorted_by_creation(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


# ---- PolicyYears -----------------------------------------------------------
@bp.get("/policy-years/<yid>")
def get_policy_year(yid):
    require_auth(ALL_ROLES)()
    py = get_or_404(db.policy_years, yid, "PolicyYear")
    return ok_object(py, 200)


@bp.get("/policy-years")
def list_policy_years():
    require_auth(ALL_ROLES)()
    limit, offset = paginate_params(request.args)
    policy_id = request.args.get("policy_id")
    items = list(db.policy_years.values())
    if policy_id is not None:
        items = [y for y in items if y.get("policy_id") == policy_id]
    items = sorted_by_creation(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


# ---- Conditions ------------------------------------------------------------
@bp.get("/conditions/<coid>")
def get_condition(coid):
    require_auth(ALL_ROLES)()
    cond = get_or_404(db.conditions, coid, "MedicalCondition")
    pol = db.policies.get(cond.get("policy_id"))
    if pol is not None:
        cond["exclusion_status"] = calculations.compute_exclusion_status(cond, pol)
    return ok_object(cond, 200)


@bp.get("/conditions")
def list_conditions():
    require_auth(ALL_ROLES)()
    limit, offset = paginate_params(request.args)
    policy_id = request.args.get("policy_id")
    items = list(db.conditions.values())
    if policy_id is not None:
        items = [c for c in items if c.get("policy_id") == policy_id]
    for c in items:
        pol = db.policies.get(c.get("policy_id"))
        if pol is not None:
            c["exclusion_status"] = calculations.compute_exclusion_status(c, pol)
    items = sorted_by_creation(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


# ---- ClaimLines ------------------------------------------------------------
@bp.get("/claim-lines/<lid>")
def get_claim_line(lid):
    require_auth(ALL_ROLES)()
    line = get_or_404(db.claim_lines, lid, "ClaimLine")
    return ok_object(line, 200)


@bp.get("/claim-lines")
def list_claim_lines():
    require_auth(ALL_ROLES)()
    limit, offset = paginate_params(request.args)
    claim_id = request.args.get("claim_id")
    items = list(db.claim_lines.values())
    if claim_id is not None:
        items = [l for l in items if l.get("claim_id") == claim_id]
    items = sorted_by_creation(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


# ---- Invoices --------------------------------------------------------------
@bp.get("/invoices/<iid>")
def get_invoice(iid):
    require_auth(ALL_ROLES)()
    inv = get_or_404(db.invoices, iid, "InvoiceDocument")
    return ok_object(inv, 200)


@bp.get("/invoices")
def list_invoices_flat():
    require_auth(ALL_ROLES)()
    limit, offset = paginate_params(request.args)
    claim_id = request.args.get("claim_id")
    items = list(db.invoices.values())
    if claim_id is not None:
        items = [i for i in items if i.get("claim_id") == claim_id]
    items = sorted_by_creation(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)
