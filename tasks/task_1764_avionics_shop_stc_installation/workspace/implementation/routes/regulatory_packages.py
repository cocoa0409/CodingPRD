"""Regulatory package endpoints: STC conformity-review path and field-approval
FAA path, with rejection loops back to DRAFT."""
import uuid

from flask import Blueprint, request

import db
import errors
from db import touch
from middleware import (
    authenticate,
    body,
    opt_str,
    pagination_args,
    paginate,
    req_enum,
    req_str,
    require_role,
)
from response import success
from serializers import ser_regulatory_package

bp = Blueprint("regulatory_packages", __name__)

APPROVAL_PATHS = {"STC", "FIELD_APPROVAL"}
OPENABLE_WO_STATES = ("PENDING_APPROVAL", "APPROVED", "PARTS_PENDING", "INSTALLATION", "TESTING")


def _get_package(regulatoryPackageId):
    p = db.regulatory_packages.get(regulatoryPackageId)
    if p is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "Regulatory package not found")
    return p


@bp.post("/avionics/regulatory-packages")
def create_regulatory_package():
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    b = body()
    work_order_id = req_str(b, "work_order_id")
    approval_path = req_enum(b, "approval_path", APPROVAL_PATHS)
    stc_number = opt_str(b, "stc_number", None)
    # stc_number present exactly when approval_path is STC
    if approval_path == "STC" and stc_number is None:
        errors.raise_err(
            errors.ERR_STC_NUMBER_REQUIRED, "stc_number is required for the STC path"
        )
    if approval_path == "FIELD_APPROVAL" and stc_number is not None:
        errors.raise_err(
            errors.ERR_STC_NUMBER_REQUIRED,
            "stc_number must be absent for the FIELD_APPROVAL path",
        )

    wo = db.work_orders.get(work_order_id)
    if wo is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "Work order not found")
    if wo.status not in OPENABLE_WO_STATES:
        errors.raise_err(
            errors.ERR_INVALID_STATE,
            "Work order state does not allow opening a regulatory package",
        )
    if any(p.work_order_id == wo.id for p in db.regulatory_packages.values()):
        errors.raise_err(
            errors.ERR_PACKAGE_ALREADY_EXISTS,
            "A regulatory package already exists for this work order",
        )

    p = db.new_entity(
        work_order_id=wo.id,
        approval_path=approval_path,
        stc_number=stc_number,
        faa_tracking_number=None,
        decided_by_user_id=None,
        status="DRAFT",
    )
    db.regulatory_packages[p.id] = p
    return success(ser_regulatory_package(p), 201)


@bp.get("/avionics/regulatory-packages/<regulatoryPackageId>")
def get_regulatory_package(regulatoryPackageId):
    authenticate()
    return success(ser_regulatory_package(_get_package(regulatoryPackageId)), 200)


@bp.get("/avionics/regulatory-packages")
def list_regulatory_packages():
    authenticate()
    limit, offset = pagination_args()
    work_order_id = request.args.get("work_order_id")
    items = sorted(db.regulatory_packages.values(), key=lambda p: p._seq)
    if work_order_id is not None:
        items = [p for p in items if p.work_order_id == work_order_id]
    page, meta = paginate([ser_regulatory_package(p) for p in items], limit, offset)
    return success(page, 200, meta)


@bp.post("/avionics/regulatory-packages/<regulatoryPackageId>/submit")
def submit_package(regulatoryPackageId):
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    p = _get_package(regulatoryPackageId)
    if p.status != "DRAFT":
        errors.raise_err(errors.ERR_INVALID_STATE, "Only a DRAFT package can be submitted")
    if p.approval_path == "STC":
        p.status = "CONFORMITY_REVIEW"
    else:
        p.status = "FAA_SUBMITTED"
        if p.faa_tracking_number is None:
            # minted on first submit, retained unchanged across resubmits
            p.faa_tracking_number = "FAA-" + uuid.uuid4().hex[:12].upper()
    touch(p)
    return success(ser_regulatory_package(p), 200)


@bp.post("/avionics/regulatory-packages/<regulatoryPackageId>/record-decision")
def record_decision(regulatoryPackageId):
    uid, role = authenticate()
    require_role(role, {"Inspector"})
    b = body()
    decision = req_enum(b, "decision", {"APPROVED", "REJECTED"})
    p = _get_package(regulatoryPackageId)
    if p.status not in ("CONFORMITY_REVIEW", "FAA_SUBMITTED"):
        errors.raise_err(
            errors.ERR_INVALID_STATE,
            "Only a package under review can receive a decision",
        )
    if decision == "APPROVED":
        p.status = "APPROVED"
        p.decided_by_user_id = uid
    else:
        # rejection loops back to DRAFT for correction and resubmission
        p.status = "DRAFT"
    touch(p)
    return success(ser_regulatory_package(p), 200)
