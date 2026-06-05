"""ContractPackage routes (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import (
    require_fields,
    require_int,
    require_number,
    require_string,
    require_package_code,
    lookup_or_404,
)


bp = Blueprint("contract_packages", __name__)


VIEW_ROLES = ["PlatformAdmin", "Customer", "Dispatcher"]


@bp.post("/contract-packages")
def create_package():
    require_auth(["PlatformAdmin"])()
    body = get_json_body()
    require_fields(
        body,
        [
            "code",
            "name",
            "annual_premium_cents",
            "service_fee_cents",
            "copay_cap_cents",
            "copay_share_pct",
            "return_visit_window_days",
            "max_covered_items",
        ],
    )
    code = require_package_code(body["code"], "code")
    name = body["name"]
    require_string(name, "name")
    annual_premium_cents = require_int(body["annual_premium_cents"], "annual_premium_cents", min_value=0)
    service_fee_cents = require_int(body["service_fee_cents"], "service_fee_cents", min_value=0)
    copay_cap_cents = require_int(body["copay_cap_cents"], "copay_cap_cents", min_value=0)
    copay_share_pct = require_number(body["copay_share_pct"], "copay_share_pct", min_value=0, max_value=1)
    return_visit_window_days = require_int(
        body["return_visit_window_days"], "return_visit_window_days", min_value=0
    )
    max_covered_items = require_int(body["max_covered_items"], "max_covered_items", min_value=1)

    # Uniqueness of code across the catalog.
    for p in db.contract_packages.values():
        if p["code"] == code:
            raise APIError(ERR_INVALID_REQUEST, 400, f"code already exists: {code}")

    pkg = {
        "code": code,
        "name": name,
        "annual_premium_cents": annual_premium_cents,
        "service_fee_cents": service_fee_cents,
        "copay_cap_cents": copay_cap_cents,
        "copay_share_pct": copay_share_pct,
        "return_visit_window_days": return_visit_window_days,
        "max_covered_items": max_covered_items,
        "status": "ACTIVE",
    }
    db.stamp_common(pkg)
    db.contract_packages[pkg["id"]] = pkg
    return ok_object(pkg, 201)


@bp.get("/contract-packages")
def list_packages():
    require_auth(VIEW_ROLES)()
    limit, offset = paginate_params(request.args)
    status_filter = request.args.get("status")

    items = list(db.contract_packages.values())
    if status_filter:
        items = [p for p in items if p["status"] == status_filter]
    items.sort(key=lambda p: p["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


@bp.get("/contract-packages/<pid>")
def get_package(pid: str):
    require_auth(VIEW_ROLES)()
    pkg = lookup_or_404(db.contract_packages, pid, "ContractPackage")
    return ok_object(pkg, 200)


@bp.post("/contract-packages/<pid>/retire")
def retire_package(pid: str):
    require_auth(["PlatformAdmin"])()
    pkg = lookup_or_404(db.contract_packages, pid, "ContractPackage")
    if pkg["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, 409, f"Cannot retire package in status {pkg['status']}")
    pkg["status"] = "RETIRED"
    db.bump(pkg)
    return ok_object(pkg, 200)
