"""Facility endpoints."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, request

from ..auth import require_auth
from ..errors import api_error
from ..response import list_envelope, success_envelope
from ..services.boundary import compute_included, resolve_org_boundary
from ..store import store
from ..utils import (
    check_version,
    decimal_places,
    get_json_body,
    page_slice,
    parse_pagination,
    require_bool,
    require_str,
    to_decimal,
    validate_country,
)
from ._helpers import get_facility_or_404, get_org_or_404, sort_by_created


facilities_bp = Blueprint("facilities", __name__)


def _validate_share(val) -> Decimal:
    d = to_decimal(val, "ownership_share_pct")
    if decimal_places(d) > 2:
        raise api_error("ERR_VALIDATION_FAILED", "ownership_share_pct must have at most 2 decimal places")
    if d < Decimal("0") or d > Decimal("100"):
        raise api_error("ERR_VALIDATION_FAILED", "ownership_share_pct must be in [0.0, 100.0]")
    return d


@facilities_bp.route("/organizations/<org_id>/facilities", methods=["POST"])
@require_auth(["PlatformAdmin"])
def create_facility(org_id):
    org = get_org_or_404(org_id)
    body = get_json_body()
    name = require_str(body, "name", min_len=1, max_len=200)
    country_code = require_str(body, "country_code", min_len=2, max_len=2)
    validate_country(country_code)
    share = _validate_share(body.get("ownership_share_pct"))
    fin_ctrl = require_bool(body, "financial_control")
    op_ctrl = require_bool(body, "operational_control")

    payload = {
        "organization_id": org_id,
        "name": name,
        "country_code": country_code,
        "ownership_share_pct": float(share),
        "financial_control": fin_ctrl,
        "operational_control": op_ctrl,
        "included_in_boundary": False,
        "status": "ACTIVE",
    }
    payload["included_in_boundary"] = compute_included(org["consolidation_approach"], payload)

    with store.lock:
        store.stamp_create(payload)
        store.facilities[payload["id"]] = payload
        resolve_org_boundary(org_id)
    return success_envelope(payload, status=201)


@facilities_bp.route("/organizations/<org_id>/facilities/<facility_id>", methods=["PATCH"])
@require_auth(["PlatformAdmin"])
def update_facility(org_id, facility_id):
    get_org_or_404(org_id)
    f = get_facility_or_404(org_id, facility_id)
    body = get_json_body()
    check_version(body, f)

    if "name" in body:
        n = body["name"]
        if not isinstance(n, str) or not n.strip() or len(n) > 200:
            raise api_error("ERR_VALIDATION_FAILED", "name must be 1..200 chars")
        f["name"] = n
    if "ownership_share_pct" in body:
        f["ownership_share_pct"] = float(_validate_share(body["ownership_share_pct"]))
    if "financial_control" in body:
        if not isinstance(body["financial_control"], bool):
            raise api_error("ERR_VALIDATION_FAILED", "financial_control must be boolean")
        f["financial_control"] = body["financial_control"]
    if "operational_control" in body:
        if not isinstance(body["operational_control"], bool):
            raise api_error("ERR_VALIDATION_FAILED", "operational_control must be boolean")
        f["operational_control"] = body["operational_control"]

    with store.lock:
        store.stamp_update(f)
        resolve_org_boundary(org_id)
    return success_envelope(f)


@facilities_bp.route("/organizations/<org_id>/facilities", methods=["GET"])
@require_auth(["PlatformAdmin", "DataSteward", "FactorManager", "Verifier", "Discloser"])
def list_facilities(org_id):
    get_org_or_404(org_id)
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    items = [
        f for f in store.facilities.values()
        if f.get("organization_id") == org_id
        and (status_filter is None or f.get("status") == status_filter)
    ]
    items = sort_by_created(items)
    page, total = page_slice(items, limit, offset)
    return list_envelope(page, total, limit, offset)
