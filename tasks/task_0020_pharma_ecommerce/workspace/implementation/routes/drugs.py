"""Drugs — create, list, get, shelve, off-shelve."""

from __future__ import annotations

import re

from flask import Blueprint, g, request

from db import db, filter_by_platform, order_by_seq, serialize, serialize_list, stamp_create, stamp_update
from errors import err
from lookups import get_drug, get_platform, get_vendor
from middleware import require_roles
from pagination import paginate, parse_limit_offset
from response import success_array, success_object
from services.cascades import cascade_off_shelve_to_orders
from validate import (
    occ_check,
    optional_field,
    require_enum,
    require_field,
    require_json,
    require_pos_int,
    require_str_array,
)

bp = Blueprint("drugs", __name__)

NDC_RE = re.compile(r"^\d{4,5}-\d{3,4}-\d{1,2}$")
CLASSIFICATIONS = {"OTC", "PRESCRIPTION"}
CONTROL_CATS = {"NONE", "NARCOTIC", "PSYCHOTROPIC_I", "PSYCHOTROPIC_II", "TOXIC"}


def _ndc_in_use(platform_id: str, ndc: str, exclude_id: str | None = None) -> bool:
    for d in db.drugs.values():
        if d.get("platform_id") != platform_id:
            continue
        if exclude_id and d["id"] == exclude_id:
            continue
        if d.get("ndc") == ndc and d.get("status") != "OFF_SHELF":
            return True
    return False


@bp.post("/pharma-platforms/<pid>/drugs")
@require_roles("PlatformAdmin", "VendorAdmin")
def create_drug(pid: str):
    platform = get_platform(pid)
    body = require_json(request.get_json(silent=True))

    ndc = require_field(body, "ndc", kind=str)
    if not NDC_RE.match(ndc):
        raise err("ERR_NDC_INVALID_FORMAT", "ndc must match the NDC regex.")

    name = require_field(body, "name", kind=str)
    classification = require_enum(body, "classification", CLASSIFICATIONS)
    control_category = require_enum(body, "control_category", CONTROL_CATS)
    if control_category != "NONE" and classification != "PRESCRIPTION":
        raise err(
            "ERR_CONTROL_CATEGORY_REQUIRES_PRESCRIPTION",
            "Drug with control_category != NONE must have classification=PRESCRIPTION.",
        )
    cold_chain_required = optional_field(body, "cold_chain_required", kind=bool, default=False)
    indications = require_str_array(body, "indications", allow_empty=True)
    contraindications = require_str_array(body, "contraindications", allow_empty=True)
    per_order_qty_cap = require_pos_int(body, "per_order_qty_cap", min_val=1)
    per_period_qty_cap = require_pos_int(body, "per_period_qty_cap", min_val=1)
    vendor_id = require_field(body, "vendor_id", kind=str)
    # Vendor existence check (shelve also enforces ACTIVE; create doesn't require active per scaffold).
    if vendor_id not in db.vendors or db.vendors[vendor_id].get("platform_id") != pid:
        raise err("ERR_VENDOR_NOT_FOUND", f"Vendor '{vendor_id}' not found.")

    if _ndc_in_use(pid, ndc):
        raise err("ERR_NDC_DUPLICATE", f"ndc {ndc} already in use on platform.")

    row = {
        "platform_id": pid,
        "ndc": ndc,
        "name": name,
        "classification": classification,
        "control_category": control_category,
        "cold_chain_required": bool(cold_chain_required),
        "indications": indications,
        "contraindications": contraindications,
        "per_order_qty_cap": per_order_qty_cap,
        "per_period_qty_cap": per_period_qty_cap,
        "vendor_id": vendor_id,
        "status": "PENDING_REVIEW",
    }
    stamp_create(row, platform)
    db.drugs[row["id"]] = row
    return success_object(serialize(row)), 201


@bp.get("/pharma-platforms/<pid>/drugs")
@require_roles(
    "PlatformAdmin",
    "VendorAdmin",
    "PrescriptionReviewer",
    "PharmacistReReviewer",
    "Customer",
    "RegulatoryGateway",
)
def list_drugs(pid: str):
    get_platform(pid)
    rows = filter_by_platform(db.drugs, pid)
    status_filter = request.args.get("status")
    classification_filter = request.args.get("classification")
    control_filter = request.args.get("control_category")
    if status_filter:
        rows = [r for r in rows if r.get("status") == status_filter]
    if classification_filter:
        rows = [r for r in rows if r.get("classification") == classification_filter]
    if control_filter:
        rows = [r for r in rows if r.get("control_category") == control_filter]
    rows = order_by_seq(rows)
    limit, offset = parse_limit_offset()
    page, total = paginate(rows, limit, offset)
    return success_array(serialize_list(page), limit, offset, total), 200


@bp.get("/pharma-platforms/<pid>/drugs/<drug_id>")
@require_roles(
    "PlatformAdmin",
    "VendorAdmin",
    "PrescriptionReviewer",
    "PharmacistReReviewer",
    "Customer",
    "RegulatoryGateway",
)
def get_drug_route(pid: str, drug_id: str):
    _, d = get_drug(pid, drug_id)
    return success_object(serialize(d)), 200


@bp.post("/pharma-platforms/<pid>/drugs/<drug_id>/shelve")
@require_roles("PlatformAdmin")
def shelve_drug(pid: str, drug_id: str):
    platform, drug = get_drug(pid, drug_id)
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        occ_check(body, drug)

    cur = drug.get("status")
    if cur not in {"PENDING_REVIEW", "OFF_SHELF"}:
        # The same endpoint covers both shelve and re-shelve. The state-error
        # surfaces as ERR_DRUG_NOT_PENDING_REVIEW per concurrency rule.
        raise err("ERR_DRUG_NOT_PENDING_REVIEW", "Drug must be PENDING_REVIEW or OFF_SHELF.")

    # Vendor must be ACTIVE
    vendor = db.vendors.get(drug["vendor_id"])
    if not vendor or vendor.get("qualification_status") != "ACTIVE":
        raise err("ERR_VENDOR_NOT_ACTIVE", "Vendor must be ACTIVE to shelve.")

    # NDC uniqueness (excluding this drug)
    if _ndc_in_use(pid, drug["ndc"], exclude_id=drug["id"]):
        raise err("ERR_NDC_DUPLICATE", f"ndc {drug['ndc']} already in use on platform.")

    # Control category implies PRESCRIPTION
    if drug.get("control_category") != "NONE" and drug.get("classification") != "PRESCRIPTION":
        raise err(
            "ERR_CONTROL_CATEGORY_REQUIRES_PRESCRIPTION",
            "Drug with control_category != NONE must be PRESCRIPTION.",
        )

    drug["status"] = "ON_SHELF"
    stamp_update(drug, platform)
    return success_object(serialize(drug)), 200


@bp.post("/pharma-platforms/<pid>/drugs/<drug_id>/off-shelve")
@require_roles("PlatformAdmin")
def off_shelve_drug(pid: str, drug_id: str):
    platform, drug = get_drug(pid, drug_id)
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        occ_check(body, drug)
    if drug.get("status") != "ON_SHELF":
        raise err("ERR_DRUG_NOT_ON_SHELF", "Drug must be ON_SHELF.")
    drug["status"] = "OFF_SHELF"
    stamp_update(drug, platform)
    cascade_off_shelve_to_orders(platform, drug["id"])
    return success_object(serialize(drug)), 200
