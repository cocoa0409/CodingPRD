"""LicenseApprovalRequest endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from db import store, touch, iso_fmt
from errors import (
    err, ERR_PRODUCT_NOT_FOUND, ERR_APPROVAL_REQUEST_NOT_FOUND,
    ERR_REQUEST_NOT_PENDING, ERR_REQUEST_NOT_IN_LEGAL_REVIEW,
    ERR_REQUEST_NOT_IN_ENGINEERING_REVIEW, ERR_REQUEST_NOT_WITHDRAWABLE,
    ERR_INVALID_LICENSE_DECISION, ERR_INVALID_ENGINEERING_DECISION,
)
from middleware import require_roles, get_auth, get_json_body
from response import success_obj, success_list, parse_pagination
from services import engine

bp = Blueprint("approvals", __name__)


def approval_view(a):
    return {k: v for k, v in a.items() if not k.startswith("_")}


def _resolve(productId, requestId=None):
    p = store.products.get(productId)
    if not p:
        raise err(ERR_PRODUCT_NOT_FOUND, "Product not found")
    a = None
    if requestId is not None:
        a = store.approvals.get(requestId)
        if not a or a["product_id"] != productId:
            raise err(ERR_APPROVAL_REQUEST_NOT_FOUND, "LicenseApprovalRequest not found")
    return p, a


@bp.route("/oss-products/<productId>/license-approvals", methods=["GET"])
def list_approvals(productId):
    get_auth()
    _resolve(productId)
    limit, offset = parse_pagination(request.args)
    items = [a for a in store.approvals.values() if a["product_id"] == productId]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([approval_view(a) for a in page], limit, offset, total)


@bp.route("/oss-products/<productId>/license-approvals/<requestId>", methods=["GET"])
def get_approval(productId, requestId):
    get_auth()
    _, a = _resolve(productId, requestId)
    return success_obj(approval_view(a))


@bp.route("/oss-products/<productId>/license-approvals/<requestId>/assign-legal", methods=["POST"])
def assign_legal(productId, requestId):
    user_id, _ = require_roles("LegalCounsel")
    _, a = _resolve(productId, requestId)
    if a["status"] != "PENDING":
        raise err(ERR_REQUEST_NOT_PENDING, "LicenseApprovalRequest must be in PENDING state")
    a["status"] = "LEGAL_REVIEW"
    a["legal_reviewer_id"] = user_id
    touch(a)
    return success_obj(approval_view(a))


@bp.route("/oss-products/<productId>/license-approvals/<requestId>/legal-decision", methods=["POST"])
def legal_decision(productId, requestId):
    user_id, _ = require_roles("LegalCounsel")
    _, a = _resolve(productId, requestId)
    body = get_json_body()
    decision = body.get("legal_decision")
    if decision not in ("APPROVE", "REJECT", "CONDITIONAL"):
        raise err(ERR_INVALID_LICENSE_DECISION, "legal_decision must be APPROVE, REJECT, or CONDITIONAL")
    if a["status"] != "LEGAL_REVIEW":
        raise err(ERR_REQUEST_NOT_IN_LEGAL_REVIEW, "LicenseApprovalRequest must be in LEGAL_REVIEW state")
    a["legal_decision"] = decision
    if decision == "CONDITIONAL":
        a["legal_conditions"] = body.get("legal_conditions")
    if decision == "REJECT":
        a["status"] = "REJECTED"
        a["final_decision"] = "REJECTED"
    else:
        a["status"] = "ENGINEERING_REVIEW"
    touch(a)
    return success_obj(approval_view(a))


@bp.route("/oss-products/<productId>/license-approvals/<requestId>/engineering-decision", methods=["POST"])
def engineering_decision(productId, requestId):
    user_id, _ = require_roles("EngineeringManager")
    p, a = _resolve(productId, requestId)
    body = get_json_body()
    decision = body.get("engineering_decision")
    if decision not in ("APPROVE", "REJECT"):
        raise err(ERR_INVALID_ENGINEERING_DECISION, "engineering_decision must be APPROVE or REJECT")
    if a["status"] != "ENGINEERING_REVIEW":
        raise err(ERR_REQUEST_NOT_IN_ENGINEERING_REVIEW,
                  "LicenseApprovalRequest must be in ENGINEERING_REVIEW state")
    a["engineering_decision"] = decision
    a["engineering_reviewer_id"] = user_id
    now = store.now()
    if decision == "APPROVE":
        a["status"] = "APPROVED"
        a["final_decision"] = "APPROVED"
        a["decision_effective_at"] = iso_fmt(now)
        a["expiry_at"] = iso_fmt(now + timedelta(days=90))
        # Linked BomEntry: obligation_fulfilled = true
        entry = store.bom_entries.get(a["bom_entry_id"])
        if entry:
            entry["obligation_fulfilled"] = True
            touch(entry)
    else:
        a["status"] = "REJECTED"
        a["final_decision"] = "REJECTED"
    touch(a)
    engine.reevaluate_product_posture(p)
    return success_obj(approval_view(a))


@bp.route("/oss-products/<productId>/license-approvals/<requestId>/withdraw", methods=["POST"])
def withdraw(productId, requestId):
    user_id, _ = require_roles("ComplianceAnalyst")
    _, a = _resolve(productId, requestId)
    if a["status"] not in ("PENDING", "LEGAL_REVIEW"):
        raise err(ERR_REQUEST_NOT_WITHDRAWABLE, "LicenseApprovalRequest cannot be withdrawn in current state")
    requester = a.get("requested_by")
    if requester is not None and requester != user_id:
        raise err(ERR_REQUEST_NOT_WITHDRAWABLE,
                  "LicenseApprovalRequest cannot be withdrawn in current state")
    a["status"] = "WITHDRAWN"
    touch(a)
    return success_obj(approval_view(a))
