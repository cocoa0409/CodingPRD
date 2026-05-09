"""Vendors — create, list, get, resubmit-qualification."""

from __future__ import annotations

from flask import Blueprint, g, request

from db import (
    db,
    filter_by_platform,
    order_by_seq,
    parse_iso,
    platform_clock,
    serialize,
    serialize_list,
    stamp_create,
    stamp_update,
)
from errors import err
from lookups import get_platform, get_vendor
from middleware import require_roles
from pagination import paginate, parse_limit_offset
from response import success_array, success_object
from validate import occ_check, require_field, require_json

bp = Blueprint("vendors", __name__)


@bp.post("/pharma-platforms/<pid>/vendors")
@require_roles("PlatformAdmin")
def create_vendor(pid: str):
    platform = get_platform(pid)
    body = require_json(request.get_json(silent=True))
    name = require_field(body, "name", kind=str)
    license_no = require_field(body, "business_license_no", kind=str)
    license_exp = require_field(body, "business_license_expires_at", kind=str)
    permit_no = require_field(body, "drug_operation_permit_no", kind=str)
    permit_exp = require_field(body, "drug_operation_permit_expires_at", kind=str)
    # Validate ISO format upfront
    try:
        parse_iso(license_exp)
        parse_iso(permit_exp)
    except Exception as exc:
        raise err("ERR_INVALID_REQUEST", f"Bad ISO date: {exc}")
    row = {
        "platform_id": pid,
        "name": name,
        "business_license_no": license_no,
        "business_license_expires_at": license_exp,
        "drug_operation_permit_no": permit_no,
        "drug_operation_permit_expires_at": permit_exp,
        "qualification_status": "ACTIVE",
        "latest_review_submitted_at": None,
    }
    stamp_create(row, platform)
    db.vendors[row["id"]] = row
    return success_object(serialize(row)), 201


@bp.get("/pharma-platforms/<pid>/vendors")
@require_roles("PlatformAdmin", "VendorAdmin", "RegulatoryGateway")
def list_vendors(pid: str):
    get_platform(pid)
    rows = filter_by_platform(db.vendors, pid)
    qual_filter = request.args.get("qualification_status")
    if qual_filter:
        rows = [r for r in rows if r.get("qualification_status") == qual_filter]
    rows = order_by_seq(rows)
    limit, offset = parse_limit_offset()
    page, total = paginate(rows, limit, offset)
    return success_array(serialize_list(page), limit, offset, total), 200


@bp.get("/pharma-platforms/<pid>/vendors/<vendor_id>")
@require_roles("PlatformAdmin", "VendorAdmin", "RegulatoryGateway")
def get_vendor_route(pid: str, vendor_id: str):
    _, v = get_vendor(pid, vendor_id)
    return success_object(serialize(v)), 200


@bp.post("/pharma-platforms/<pid>/vendors/<vendor_id>/resubmit-qualification")
@require_roles("VendorAdmin")
def resubmit_qualification(pid: str, vendor_id: str):
    platform, vendor = get_vendor(pid, vendor_id)
    # Optional ownership: PRD §2.1 says VendorAdmin's X-User-ID == vendor.id.
    if g.user_id != vendor["id"]:
        raise err(
            "ERR_INSUFFICIENT_PERMISSIONS",
            "VendorAdmin may only resubmit their own vendor qualification.",
        )
    body = require_json(request.get_json(silent=True))
    occ_check(body, vendor)
    if vendor.get("qualification_status") not in {"REVIEW_REQUIRED", "SUSPENDED"}:
        raise err(
            "ERR_VENDOR_NOT_IN_REVIEW",
            "Vendor must be REVIEW_REQUIRED or SUSPENDED to resubmit.",
        )
    license_exp = require_field(body, "business_license_expires_at", kind=str)
    permit_exp = require_field(body, "drug_operation_permit_expires_at", kind=str)
    try:
        l_dt = parse_iso(license_exp)
        p_dt = parse_iso(permit_exp)
    except Exception as exc:
        raise err("ERR_INVALID_REQUEST", f"Bad ISO date: {exc}")
    clock = parse_iso(platform_clock(platform))
    if l_dt <= clock or p_dt <= clock:
        raise err(
            "ERR_RENEWAL_DATE_NOT_FUTURE",
            "Renewal expiry must be strictly greater than platform clock.",
        )
    vendor["business_license_expires_at"] = license_exp
    vendor["drug_operation_permit_expires_at"] = permit_exp
    vendor["qualification_status"] = "ACTIVE"
    vendor["latest_review_submitted_at"] = platform_clock(platform)
    stamp_update(vendor, platform)
    return success_object(serialize(vendor)), 200
