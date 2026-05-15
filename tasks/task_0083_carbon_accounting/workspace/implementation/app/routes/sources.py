"""EmissionSource endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import require_auth
from ..errors import api_error
from ..response import list_envelope, success_envelope
from ..services.calculations import derive_scope
from ..store import store, now_ts
from ..utils import (
    check_version,
    get_json_body,
    page_slice,
    parse_pagination,
    require_enum,
    require_str,
    validate_code,
)
from ._helpers import (
    get_facility_or_404,
    get_org_or_404,
    get_source_or_404,
    sort_by_created,
)


sources_bp = Blueprint("sources", __name__)


CATEGORIES = {"STATIONARY_COMBUSTION", "MOBILE_COMBUSTION", "PROCESS", "FUGITIVE", "PURCHASED_ENERGY", "VALUE_CHAIN"}
GAS_TYPES = {"CO2", "CH4", "N2O", "HFC", "PFC", "SF6", "NF3"}


def _validate_scope3(category: str, scope3_category) -> int | None:
    if category == "VALUE_CHAIN":
        if not isinstance(scope3_category, int) or isinstance(scope3_category, bool):
            raise api_error("ERR_SCOPE3_CATEGORY_MISMATCH", "scope3_category required for VALUE_CHAIN sources")
        if scope3_category < 1 or scope3_category > 15:
            raise api_error("ERR_SCOPE3_CATEGORY_MISMATCH", "scope3_category must be in 1..15")
        return scope3_category
    if scope3_category is not None:
        raise api_error("ERR_SCOPE3_CATEGORY_MISMATCH", "scope3_category must be null for non-VALUE_CHAIN sources")
    return None


def _bump(row: dict) -> None:
    row["updated_at"] = now_ts()
    row["version"] = row.get("version", 0) + 1


@sources_bp.route("/organizations/<org_id>/sources", methods=["POST"])
@require_auth(["DataSteward"])
def create_source(org_id):
    get_org_or_404(org_id)
    body = get_json_body()
    facility_id = body.get("facility_id")
    if not isinstance(facility_id, str) or not facility_id:
        raise api_error("ERR_VALIDATION_FAILED", "facility_id is required")
    # Existence then cross-org
    f = store.facilities.get(facility_id)
    if not f:
        raise api_error("ERR_NOT_FOUND", "facility_id not found")
    if f.get("organization_id") != org_id:
        raise api_error("ERR_CROSS_ORG_REFERENCE", "facility_id belongs to a different organization")

    code = require_str(body, "code", min_len=1, max_len=50)
    validate_code(code, "code")
    category = require_enum(body, "category", CATEGORIES)
    scope3 = _validate_scope3(category, body.get("scope3_category"))
    gas_type = require_enum(body, "gas_type", GAS_TYPES)
    factor_code = require_str(body, "factor_code", min_len=1, max_len=50)
    validate_code(factor_code, "factor_code")

    # Boundary check
    if not (f.get("included_in_boundary") and f.get("status") == "ACTIVE"):
        raise api_error("ERR_FACILITY_OUT_OF_BOUNDARY", "Facility is not in boundary or not ACTIVE")

    # Code unique within organization
    for s in store.emission_sources.values():
        if s.get("organization_id") == org_id and s.get("code") == code:
            raise api_error("ERR_VALIDATION_FAILED", "code must be unique within organization")

    # PRD §3.3: "factor_code that points at an emission-factor family the
    # source resolves to at activity-entry time. The factor family must
    # belong to the same organization and its gas_type must equal the
    # source's gas_type." Resolution to a specific factor version happens
    # at activity-entry — so we do NOT require the family to exist at
    # source-create time. However, if any factor version with that code
    # already exists in this organization, its gas_type must match the
    # source's gas_type; otherwise the family/source association would be
    # internally inconsistent.
    for ef in store.emission_factors.values():
        if ef.get("organization_id") != org_id:
            continue
        if ef.get("code") != factor_code:
            continue
        if ef.get("gas_type") != gas_type:
            raise api_error(
                "ERR_VALIDATION_FAILED",
                "factor_code refers to a factor family with a different gas_type",
            )

    scope = derive_scope(category)

    payload = {
        "organization_id": org_id,
        "facility_id": facility_id,
        "code": code,
        "category": category,
        "scope": scope,
        "scope3_category": scope3,
        "gas_type": gas_type,
        "factor_code": factor_code,
        "status": "ACTIVE",
    }
    with store.lock:
        store.stamp_create(payload)
        store.emission_sources[payload["id"]] = payload
    return success_envelope(payload, status=201)


@sources_bp.route("/organizations/<org_id>/sources/<source_id>", methods=["PATCH"])
@require_auth(["DataSteward"])
def update_source(org_id, source_id):
    get_org_or_404(org_id)
    src = get_source_or_404(org_id, source_id)
    body = get_json_body()
    check_version(body, src)

    if "category" in body:
        if body["category"] not in CATEGORIES:
            raise api_error("ERR_VALIDATION_FAILED", "Invalid category")
        src["category"] = body["category"]
        src["scope"] = derive_scope(body["category"])

    new_scope3 = body.get("scope3_category", src.get("scope3_category"))
    # Re-validate the pair
    src["scope3_category"] = _validate_scope3(src["category"], new_scope3)

    if "gas_type" in body:
        if body["gas_type"] not in GAS_TYPES:
            raise api_error("ERR_VALIDATION_FAILED", "Invalid gas_type")
        src["gas_type"] = body["gas_type"]

    if "factor_code" in body:
        fc = body["factor_code"]
        if not isinstance(fc, str):
            raise api_error("ERR_VALIDATION_FAILED", "factor_code must be a string")
        validate_code(fc, "factor_code")
        src["factor_code"] = fc

    with store.lock:
        _bump(src)
    return success_envelope(src)


@sources_bp.route("/organizations/<org_id>/sources", methods=["GET"])
@require_auth(["DataSteward", "FactorManager", "Verifier", "Discloser"])
def list_sources(org_id):
    get_org_or_404(org_id)
    limit, offset = parse_pagination()
    facility_id_f = request.args.get("facility_id")
    category_f = request.args.get("category")
    status_f = request.args.get("status")
    items = [
        s for s in store.emission_sources.values()
        if s.get("organization_id") == org_id
        and (facility_id_f is None or s.get("facility_id") == facility_id_f)
        and (category_f is None or s.get("category") == category_f)
        and (status_f is None or s.get("status") == status_f)
    ]
    items = sort_by_created(items)
    page, total = page_slice(items, limit, offset)
    return list_envelope(page, total, limit, offset)
