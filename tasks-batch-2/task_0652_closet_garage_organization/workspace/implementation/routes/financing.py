"""FinancingApplication routes and lender decision webhook."""
from flask import Blueprint, request

import db
import serialize
from errors import err
from response import object_response, array_response
from middleware import get_identity, require_roles
from validate import (get_body, require_str, require_int, require_enum,
                      parse_pagination, paginate)
from services import calc, domain

bp = Blueprint("financing", __name__)

TERM_MONTHS = {12, 24, 36, 48}


@bp.post("/financing-applications")
def create_application():
    user_id, role = get_identity()
    require_roles(role, {"Customer"})
    body = get_body()
    project_id = require_str(body, "project_id")
    quote_id = require_str(body, "quote_id")
    requested_amount_cents = require_int(body, "requested_amount_cents", minimum=1)
    term_months = require_int(body, "term_months")
    if term_months not in TERM_MONTHS:
        raise err("ERR_VALIDATION", "term_months must be one of 12, 24, 36, 48.")
    project = db.projects.get(project_id)
    if project is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    quote = db.quotes.get(quote_id)
    if quote is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    domain.check_project_owner(project, user_id, role)
    rec = db.stamp_new({
        "project_id": project_id,
        "quote_id": quote_id,
        "requested_amount_cents": requested_amount_cents,
        "term_months": term_months,
        "status": "DRAFT",
        "approved_amount_cents": 0,
        "monthly_payment_cents": 0,
    })
    db.financing_applications[rec["id"]] = rec
    return object_response(serialize.financing_application(rec), 201)


@bp.get("/financing-applications/<fid>")
def get_application(fid):
    _, role = get_identity()
    require_roles(role, {"Customer", "PlatformAdmin"})
    rec = db.financing_applications.get(fid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    return object_response(serialize.financing_application(rec))


@bp.get("/financing-applications")
def list_applications():
    _, role = get_identity()
    require_roles(role, {"Customer", "PlatformAdmin"})
    limit, offset = parse_pagination()
    project_id = request.args.get("project_id")
    quote_id = request.args.get("quote_id")
    status = request.args.get("status")
    items = []
    for f in db.financing_applications.values():
        if project_id is not None and f["project_id"] != project_id:
            continue
        if quote_id is not None and f["quote_id"] != quote_id:
            continue
        if status is not None and f["status"] != status:
            continue
        items.append(f)
    page, total = paginate(items, limit, offset)
    return array_response([serialize.financing_application(f) for f in page],
                          limit, offset, total)


@bp.post("/financing-applications/<fid>/submit")
def submit_application(fid):
    user_id, role = get_identity()
    require_roles(role, {"Customer"})
    rec = db.financing_applications.get(fid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    project = db.projects.get(rec["project_id"])
    quote = db.quotes.get(rec["quote_id"])
    if project is None or quote is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    domain.check_project_owner(project, user_id, role)
    if rec["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE")
    if quote["status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE")
    if rec["requested_amount_cents"] > quote["total_cents"]:
        raise err("ERR_FINANCE_EXCEEDS_TOTAL")
    rec["status"] = "SUBMITTED"
    db.touch(rec)
    return object_response(serialize.financing_application(rec))


@bp.post("/financing-applications/<fid>/fund")
def fund_application(fid):
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin"})
    rec = db.financing_applications.get(fid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    project = db.projects.get(rec["project_id"])
    if project is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    if rec["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE")
    if project["status"] not in {"DEPOSIT_PAID", "IN_MANUFACTURE", "READY_TO_INSTALL"}:
        raise err("ERR_INVALID_STATE")
    # Only one funded financing application per project.
    if project.get("financing_application_id"):
        existing = db.financing_applications.get(project["financing_application_id"])
        if existing is not None and existing["status"] == "FUNDED":
            raise err("ERR_FINANCE_ALREADY_LINKED")
    rec["status"] = "FUNDED"
    db.touch(rec)
    project["financing_application_id"] = rec["id"]
    domain.recompute_balance(project)
    return object_response(serialize.financing_application(rec))


@bp.post("/_financing/decision")
def financing_decision():
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin"})
    body = get_body()
    financing_application_id = require_str(body, "financing_application_id")
    decision = require_enum(body, "decision", {"APPROVE", "DECLINE"})
    rec = db.financing_applications.get(financing_application_id)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    if rec["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE")
    if decision == "APPROVE":
        quote = db.quotes.get(rec["quote_id"])
        approved, monthly = calc.financing_approval(
            quote["total_cents"], rec["requested_amount_cents"], rec["term_months"])
        rec["approved_amount_cents"] = approved
        rec["monthly_payment_cents"] = monthly
        rec["status"] = "APPROVED"
    else:
        rec["status"] = "DECLINED"
    db.touch(rec)
    return object_response(serialize.financing_application(rec))
