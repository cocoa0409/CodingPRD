"""Pharmacists — create, list, get, renew, suspend."""

from __future__ import annotations

from flask import Blueprint, request

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
from lookups import get_pharmacist, get_platform
from middleware import require_roles
from pagination import paginate, parse_limit_offset
from response import success_array, success_object
from validate import occ_check, optional_field, require_field, require_json

bp = Blueprint("pharmacists", __name__)


@bp.post("/pharma-platforms/<pid>/pharmacists")
@require_roles("PlatformAdmin")
def create_pharmacist(pid: str):
    platform = get_platform(pid)
    body = require_json(request.get_json(silent=True))
    full_name = require_field(body, "full_name", kind=str)
    cert_no = require_field(body, "certificate_no", kind=str)
    cert_exp = require_field(body, "certificate_expires_at", kind=str)
    courier_qualified = optional_field(body, "courier_qualified", kind=bool, default=False)
    try:
        parse_iso(cert_exp)
    except Exception as exc:
        raise err("ERR_INVALID_REQUEST", f"Bad ISO date: {exc}")
    row = {
        "platform_id": pid,
        "full_name": full_name,
        "certificate_no": cert_no,
        "certificate_expires_at": cert_exp,
        "qualification_status": "ACTIVE",
        "courier_qualified": bool(courier_qualified),
    }
    stamp_create(row, platform)
    db.pharmacists[row["id"]] = row
    return success_object(serialize(row)), 201


@bp.get("/pharma-platforms/<pid>/pharmacists")
@require_roles("PlatformAdmin", "VendorAdmin", "PharmacistReReviewer", "PrescriptionReviewer")
def list_pharmacists(pid: str):
    get_platform(pid)
    rows = filter_by_platform(db.pharmacists, pid)
    qual_filter = request.args.get("qualification_status")
    if qual_filter:
        rows = [r for r in rows if r.get("qualification_status") == qual_filter]
    rows = order_by_seq(rows)
    limit, offset = parse_limit_offset()
    page, total = paginate(rows, limit, offset)
    return success_array(serialize_list(page), limit, offset, total), 200


@bp.get("/pharma-platforms/<pid>/pharmacists/<pharmacist_id>")
@require_roles("PlatformAdmin", "VendorAdmin", "PharmacistReReviewer", "PrescriptionReviewer")
def get_pharmacist_route(pid: str, pharmacist_id: str):
    _, ph = get_pharmacist(pid, pharmacist_id)
    return success_object(serialize(ph)), 200


@bp.post("/pharma-platforms/<pid>/pharmacists/<pharmacist_id>/renew-certificate")
@require_roles("PlatformAdmin")
def renew_certificate(pid: str, pharmacist_id: str):
    platform, ph = get_pharmacist(pid, pharmacist_id)
    body = require_json(request.get_json(silent=True))
    occ_check(body, ph)
    cert_exp = require_field(body, "certificate_expires_at", kind=str)
    try:
        new_dt = parse_iso(cert_exp)
    except Exception as exc:
        raise err("ERR_INVALID_REQUEST", f"Bad ISO date: {exc}")
    if new_dt <= parse_iso(platform_clock(platform)):
        raise err(
            "ERR_RENEWAL_DATE_NOT_FUTURE",
            "certificate_expires_at must be strictly greater than platform clock.",
        )
    ph["certificate_expires_at"] = cert_exp
    ph["qualification_status"] = "ACTIVE"
    stamp_update(ph, platform)
    return success_object(serialize(ph)), 200


@bp.post("/pharma-platforms/<pid>/pharmacists/<pharmacist_id>/suspend")
@require_roles("PlatformAdmin")
def suspend_pharmacist(pid: str, pharmacist_id: str):
    platform, ph = get_pharmacist(pid, pharmacist_id)
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        occ_check(body, ph)
    ph["qualification_status"] = "SUSPENDED"
    stamp_update(ph, platform)
    return success_object(serialize(ph)), 200
