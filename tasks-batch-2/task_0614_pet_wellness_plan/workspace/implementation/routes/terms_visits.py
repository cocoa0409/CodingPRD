"""Read endpoints for contract terms, credits, visits, billing cycles, and
plan-change requests; plus visit recording/voiding. (PRD §3.3–§3.9)."""
from flask import Blueprint, request

from db import db
from errors import err, ERR_REFERENCE_NOT_FOUND
from middleware import authenticate, require_role
from response import success, list_success
from common import (
    parse_pagination, paginate, sort_by_created, get_json, public,
    require_str, require_enum,
)
from lookup import get_or_404
from services.visits import record_visit, void_visit

bp = Blueprint("terms_visits", __name__)

READ_ROLES = {"Member", "PlanAdmin", "BillingAdmin"}
ALL_ROLES = {"Member", "PlanAdmin", "BillingAdmin", "ClinicStaff"}
SERVICE_CODES = {"EXAM", "VACCINE", "DENTAL"}


# --------------------------------------------------------------------------
# Contract terms
# --------------------------------------------------------------------------
@bp.get("/wellness/contract-terms")
def list_contract_terms():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    rows = list(db.contract_terms.values())
    for f in ("membership_id", "plan_id", "status"):
        v = request.args.get(f)
        if v is not None:
            rows = [r for r in rows if r[f] == v]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)


@bp.get("/wellness/contract-terms/<tid>")
def get_contract_term(tid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    term = get_or_404(db.contract_terms, tid)
    return success(public(term))


@bp.get("/wellness/contract-terms/<tid>/credits")
def list_term_credits(tid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    get_or_404(db.contract_terms, tid)
    limit, offset = parse_pagination()
    rows = [c for c in db.service_credits.values()
            if c["contract_term_id"] == tid]
    for f in ("service_code", "status"):
        v = request.args.get(f)
        if v is not None:
            rows = [r for r in rows if r[f] == v]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)


@bp.get("/wellness/service-credits/<cid>")
def get_service_credit(cid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    credit = get_or_404(db.service_credits, cid)
    return success(public(credit))


# --------------------------------------------------------------------------
# Visits
# --------------------------------------------------------------------------
@bp.post("/wellness/memberships/<mid>/visits")
def create_visit(mid):
    _, role = authenticate()
    require_role(role, {"ClinicStaff"})
    membership = get_or_404(db.memberships, mid)
    body = get_json()
    enrolled_pet_id = require_str(body, "enrolled_pet_id")
    clinic_id = require_str(body, "clinic_id")
    service_code = require_enum(body, "service_code", SERVICE_CODES)
    visit = record_visit(membership, enrolled_pet_id, clinic_id, service_code)
    return success(public(visit), 201)


@bp.get("/wellness/visits")
def list_visits():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    rows = list(db.service_visits.values())
    for f in ("membership_id", "enrolled_pet_id", "clinic_id",
              "contract_term_id", "service_code", "status"):
        v = request.args.get(f)
        if v is not None:
            rows = [r for r in rows if r[f] == v]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)


@bp.get("/wellness/visits/<vid>")
def get_visit(vid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    visit = get_or_404(db.service_visits, vid)
    return success(public(visit))


@bp.post("/wellness/visits/<vid>/void")
def void(vid):
    _, role = authenticate()
    require_role(role, {"ClinicStaff"})
    visit = get_or_404(db.service_visits, vid)
    void_visit(visit)
    return success(public(visit))


# --------------------------------------------------------------------------
# Billing cycles
# --------------------------------------------------------------------------
@bp.get("/wellness/billing-cycles")
def list_billing_cycles():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    rows = list(db.billing_cycles.values())
    for f in ("membership_id", "status"):
        v = request.args.get(f)
        if v is not None:
            rows = [r for r in rows if r[f] == v]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)


@bp.get("/wellness/billing-cycles/<bid>")
def get_billing_cycle(bid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    cycle = get_or_404(db.billing_cycles, bid)
    return success(public(cycle))


# --------------------------------------------------------------------------
# Plan-change requests (global)
# --------------------------------------------------------------------------
@bp.get("/wellness/plan-changes")
def list_plan_changes():
    user_id, role = authenticate()
    require_role(role, {"PlanAdmin", "BillingAdmin", "Member"})
    limit, offset = parse_pagination()
    rows = list(db.plan_change_requests.values())
    if role == "Member":
        owned = {m["id"] for m in db.memberships.values()
                 if m["member_account_id"] == user_id}
        rows = [r for r in rows if r["membership_id"] in owned]
    for f in ("membership_id", "from_plan_id", "to_plan_id", "status"):
        v = request.args.get(f)
        if v is not None:
            rows = [r for r in rows if r[f] == v]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)


@bp.get("/wellness/plan-changes/<pid>")
def get_plan_change(pid):
    user_id, role = authenticate()
    require_role(role, {"PlanAdmin", "BillingAdmin", "Member"})
    pcr = get_or_404(db.plan_change_requests, pid)
    if role == "Member":
        membership = db.memberships.get(pcr["membership_id"])
        if membership is None or membership["member_account_id"] != user_id:
            from errors import ERR_NOT_RESOURCE_OWNER
            raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner")
    return success(public(pcr))