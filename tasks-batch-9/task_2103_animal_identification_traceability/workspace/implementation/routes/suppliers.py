"""Device supplier approval and conformance policing (PRD 3.2)."""
from decimal import Decimal

from flask import Blueprint

import derive
import shape
from authz import PROGRAM_ADMIN, STATE_OFFICIAL, SUPPLIER_REP, require_roles
from db import base_record, store, touch
from errors import conflict, invalid_state, segregation_of_duties
from respond import success
from routes._common import supplier_or_404
from serialize import public

bp = Blueprint("suppliers", __name__)


@bp.post("/device-suppliers")
def create_supplier():
    uid, role = require_roles(PROGRAM_ADMIN)
    body = shape.body()
    company_name = shape.s_str(body, "company_name")
    supplier_code = shape.s_str(body, "supplier_code", pattern=shape.SUPPLIER_CODE_RE)
    aid_prefix = shape.s_str(body, "aid_prefix", required=False,
                             pattern=shape.AID_PREFIX_RE) or "840"
    # Band 15 - the supplier code is globally unique.
    if any(s["supplier_code"] == supplier_code for s in store.suppliers.values()):
        raise conflict("ERR_DUPLICATE_SUPPLIER_CODE",
                       "Another device supplier already uses this supplier_code")

    rec = base_record()
    rec.update({
        "company_name": company_name,
        "supplier_code": supplier_code,
        "aid_prefix": aid_prefix,
        "status": "PENDING_REVIEW",
        "registered_by_user_id": uid,
        "approved_by_user_id": None,
        "defect_report_count": 0,
        "issued_tag_count": 0,
        "retired_tag_count": 0,
        "retired_returned_count": 0,
        "conformance_score": Decimal("100.00"),
        "probation": False,
        "issuance_cap": 10000,
    })
    store.suppliers[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.get("/device-suppliers/<supplier_id>")
def read_supplier(supplier_id):
    require_roles(PROGRAM_ADMIN, SUPPLIER_REP)
    return success(public(supplier_or_404(supplier_id)))


@bp.post("/device-suppliers/<supplier_id>/approve")
def approve_supplier(supplier_id):
    uid, role = require_roles(PROGRAM_ADMIN)
    supplier = supplier_or_404(supplier_id)
    # Band 8 - segregation of duties precedes the own-state gate.
    if uid == supplier["registered_by_user_id"]:
        raise segregation_of_duties(
            "The approving administrator must differ from the registering administrator")
    if supplier["status"] != "PENDING_REVIEW":
        raise invalid_state("Supplier is not PENDING_REVIEW")
    supplier["status"] = "APPROVED"
    supplier["approved_by_user_id"] = uid
    derive.recompute_supplier(supplier, bump_version=True)
    return success(public(supplier))


@bp.post("/device-suppliers/<supplier_id>/defect-reports")
def report_defects(supplier_id):
    require_roles(STATE_OFFICIAL, PROGRAM_ADMIN)
    body = shape.body()
    defect_count = shape.s_int(body, "defect_count", minimum=1)
    shape.s_str(body, "note", required=False)
    supplier = supplier_or_404(supplier_id)
    supplier["defect_report_count"] += defect_count
    derive.recompute_supplier(supplier, apply_status_transitions=True, bump_version=True)
    return success(public(supplier))


@bp.post("/device-suppliers/<supplier_id>/reinstate")
def reinstate_supplier(supplier_id):
    require_roles(PROGRAM_ADMIN)
    body = shape.body()
    forgiven = shape.s_int(body, "forgiven_defects", minimum=0)
    supplier = supplier_or_404(supplier_id)
    if supplier["status"] != "SUSPENDED":
        raise invalid_state("Only a SUSPENDED supplier may be reinstated")
    supplier["defect_report_count"] = max(0, supplier["defect_report_count"] - forgiven)
    metrics = derive.supplier_metrics(supplier)
    derive.assign_supplier_metrics(supplier, metrics)
    if metrics["conformance_score"] >= Decimal("70.00"):
        supplier["status"] = "APPROVED"
    touch(supplier)
    return success(public(supplier))
