"""Contractor endpoints."""
from flask import Blueprint

import db
from errors import ApiError, ERR_DUPLICATE
from middleware import authenticate, authorize, require_owner
from response import success
from serializers import contractor as ser
from services import core
from utils import StructErrors, check_unknown_fields, get_str, get_enum, touch
from routes.common import body, get_path, new_common, list_response

bp = Blueprint("contractors", __name__)

READ_ROLES = {"DistributorAdmin", "ContractorUser", "WarrantyProcessor",
              "ComplianceOfficer", "TrainingCoordinator"}
LIST_ROLES = {"DistributorAdmin", "WarrantyProcessor", "ComplianceOfficer",
              "TrainingCoordinator"}


@bp.post("/contractors")
def create_contractor():
    user_id, role = authenticate()
    authorize({"DistributorAdmin"}, role)
    data = body()
    struct = StructErrors()
    # PRD §2.9 / §3.1: the contractor's derived fields are server-managed; a
    # supplied value for any of them is ignored (never rejected as "unknown").
    check_unknown_fields(data, {"company_name", "license_number", "credit_hold",
                                "status", "tier", "ytd_purchase_cents",
                                "coop_accrual_provisional_cents",
                                "coop_accrual_final_cents",
                                "training_credit_balance_hours",
                                "compliance_standing",
                                "heel_violation_count_12m"}, struct)
    company_name = get_str(data, "company_name", struct)
    license_number = get_str(data, "license_number", struct)
    status = get_enum(data, "status", struct, {"ACTIVE", "SUSPENDED"},
                      required=False, default="ACTIVE")
    credit_hold = data.get("credit_hold", False)
    if "credit_hold" in data and not isinstance(data["credit_hold"], bool):
        struct.add("Field credit_hold must be a boolean")

    # Uniqueness (priority 14) precedes structural validity (priority 22).
    if isinstance(license_number, str):
        for c in db.contractors.values():
            if c["license_number"] == license_number:
                raise ApiError(ERR_DUPLICATE, 409,
                               "license_number already exists")
    struct.raise_if_bad()

    c = new_common()
    c.update({
        "company_name": company_name,
        "license_number": license_number,
        "tier": "STANDARD",
        "ytd_purchase_cents": 0,
        "coop_accrual_provisional_cents": 0,
        "coop_accrual_final_cents": 0,
        "training_credit_balance_hours": 0,
        "compliance_standing": "GOOD",
        "heel_violation_count_12m": 0,
        "credit_hold": credit_hold if isinstance(credit_hold, bool) else False,
        "status": status or "ACTIVE",
    })
    db.contractors[c["id"]] = c
    return success(ser(c), 201)


@bp.get("/contractors/<cid>")
def get_contractor(cid):
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    c = get_path(db.contractors, cid)
    require_owner(c["id"], role, user_id)
    core.refresh_training_balance(c)
    return success(ser(c))


@bp.get("/contractors")
def list_contractors():
    user_id, role = authenticate()
    authorize(LIST_ROLES, role)
    from flask import request
    filters = {"status": request.args.get("status"),
               "tier": request.args.get("tier")}
    return list_response(db.contractors.values(), ser, filters)


@bp.patch("/contractors/<cid>")
def patch_contractor(cid):
    user_id, role = authenticate()
    authorize({"DistributorAdmin"}, role)
    c = get_path(db.contractors, cid)
    data = body()
    struct = StructErrors()
    check_unknown_fields(data, {"credit_hold", "status"}, struct)
    changed = False
    if "credit_hold" in data:
        if not isinstance(data["credit_hold"], bool):
            struct.add("Field credit_hold must be a boolean")
        elif data["credit_hold"] != c["credit_hold"]:
            c["credit_hold"] = data["credit_hold"]
            changed = True
    if "status" in data:
        v = data["status"]
        if v not in ("ACTIVE", "SUSPENDED"):
            struct.add("Field status must be ACTIVE or SUSPENDED")
        elif v != c["status"]:
            c["status"] = v
            changed = True
    struct.raise_if_bad()
    touch(c)  # every update request increments version
    return success(ser(c))
