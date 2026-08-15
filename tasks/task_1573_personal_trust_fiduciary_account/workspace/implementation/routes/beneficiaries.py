"""Beneficiary enrollment + mark-deceased with cascades."""

from flask import Blueprint, request

import db
import serialize
from errors import (ApiError, ERR_INVALID_STATE, ERR_TRUST_NOT_ACTIVE,
                    ERR_RESOURCE_NOT_FOUND)
from middleware import authenticate, require_role
from response import ok, ok_list
from serialize import beneficiary_json
from services import workflow, calc
from services.workflow import find_or_404
from validation import get_body, validate, parse_pagination

bp = Blueprint("beneficiaries", __name__)

READ_ROLES = {"TrustOfficer", "TrustExecutive", "InvestmentManager",
              "TrustOperationsOfficer", "TaxSpecialist"}
CLASSES = {"INCOME", "REMAINDER"}


@bp.route("/trusts/beneficiaries", methods=["POST"])
def create_beneficiary():
    _, role = authenticate()
    data = get_body()
    v = validate(data, [
        ("trust_id", "str", True),
        ("full_name", "str", True),
        ("beneficiary_class", "str", True, CLASSES),
        ("share_bps", "int", True),
        ("date_of_birth", "date", True),
    ])
    if not (1 <= v["share_bps"] <= 10000):
        from errors import ERR_VALIDATION
        raise ApiError(ERR_VALIDATION, 400, "share_bps must be within 1..10000")
    require_role(role, {"TrustOfficer"})
    trust = db.trusts.get(v["trust_id"])
    if trust is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404,
                       "Trust not found: %s" % v["trust_id"])
    if trust["status"] not in ("DRAFT", "UNDER_ACCEPTANCE_REVIEW", "ACTIVE"):
        raise ApiError(ERR_TRUST_NOT_ACTIVE, 409,
                       "Trust is not accepting new beneficiaries in its status")
    b = workflow.new_entity()
    b.update({
        "trust_id": trust["id"],
        "full_name": v["full_name"],
        "beneficiary_class": v["beneficiary_class"],
        "share_bps": v["share_bps"],
        "date_of_birth": v["date_of_birth"],
        "status": "ACTIVE",
        "deceased_at": None,
    })
    db.beneficiaries[b["id"]] = b
    return ok(beneficiary_json(b), status=201)


@bp.route("/trusts/beneficiaries", methods=["GET"])
def list_beneficiaries():
    _, role = authenticate()
    limit, offset = parse_pagination()
    require_role(role, READ_ROLES)
    filters = []
    for param in ("trust_id", "status", "beneficiary_class"):
        val = request.args.get(param)
        if val is not None:
            filters.append((param, val))
    items, total = workflow.list_page(db.beneficiaries, filters,
                                      beneficiary_json, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/trusts/beneficiaries/<bid>", methods=["GET"])
def get_beneficiary(bid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    b = find_or_404(db.beneficiaries, bid, "Beneficiary")
    return ok(beneficiary_json(b))


@bp.route("/trusts/beneficiaries/<bid>/mark-deceased", methods=["POST"])
def mark_deceased(bid):
    _, role = authenticate()
    data = get_body()
    v = validate(data, [("deceased_at", "date", True)])
    require_role(role, {"TrustOfficer"})
    b = find_or_404(db.beneficiaries, bid, "Beneficiary")
    if b["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Beneficiary must be ACTIVE to mark deceased")
    b["status"] = "DECEASED"
    b["deceased_at"] = v["deceased_at"]
    workflow.touch(b)
    trust = db.trusts.get(b["trust_id"])
    # Cascade 1+2: cancel the beneficiary's non-terminal requests (reservation
    # release is automatic since reserved_* derives from request status).
    cancelled = 0
    for r in db.distribution_requests.values():
        if r["beneficiary_id"] == bid and r["status"] in serialize.PENDING_STATES:
            r["status"] = "CANCELLED"
            r["cancelled_reason"] = "BENEFICIARY_DECEASED"
            workflow.touch(r)
            cancelled += 1
    if cancelled and trust is not None:
        workflow.bump_trust(trust)
    # Cascade 3: share reallocation when the APPROVED instrument is not per stirpes
    approved_doc = None
    for d in db.documents.values():
        if d["trust_id"] == b["trust_id"] and d["status"] == "APPROVED":
            approved_doc = d
            break
    if approved_doc is not None and approved_doc["per_stirpes"] is False:
        calc.reallocate_shares(b)
        if b["share_bps"] == 0:
            workflow.touch(b)  # share zeroed after the status touch
    return ok(beneficiary_json(b))
