"""Organization endpoints."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, g

from ..auth import require_auth
from ..errors import api_error
from ..response import success_envelope
from ..services.boundary import resolve_org_boundary
from ..store import store
from ..utils import (
    check_max_decimals,
    check_version,
    decimal_places,
    get_json_body,
    require_enum,
    require_int,
    require_str,
    to_decimal,
    validate_currency,
)
from ._helpers import get_org_or_404


organizations_bp = Blueprint("organizations", __name__)


CONSOLIDATION_APPROACHES = {"EQUITY_SHARE", "FINANCIAL_CONTROL", "OPERATIONAL_CONTROL"}


def _validate_materiality(val) -> Decimal:
    if val is None:
        return Decimal("1.00")
    d = to_decimal(val, "materiality_threshold_pct", err="ERR_MATERIALITY_OUT_OF_RANGE")
    if decimal_places(d) > 2:
        raise api_error("ERR_MATERIALITY_OUT_OF_RANGE", "materiality_threshold_pct must have at most 2 decimal places")
    if d < Decimal("0") or d > Decimal("5"):
        raise api_error("ERR_MATERIALITY_OUT_OF_RANGE", "materiality_threshold_pct must be in [0.0, 5.0]")
    return d


@organizations_bp.route("/organizations", methods=["POST"])
@require_auth(["PlatformAdmin"])
def create_organization():
    body = get_json_body()
    legal_name = require_str(body, "legal_name", min_len=1, max_len=200)
    if not legal_name.strip():
        raise api_error("ERR_VALIDATION_FAILED", "legal_name must be non-empty after trim")
    approach = require_enum(body, "consolidation_approach", CONSOLIDATION_APPROACHES)
    base_year = require_int(body, "base_year", min_val=1990, max_val=2100)
    functional_currency = require_str(body, "functional_currency", min_len=3, max_len=3)
    validate_currency(functional_currency)
    materiality = _validate_materiality(body.get("materiality_threshold_pct"))

    payload = {
        "legal_name": legal_name,
        "consolidation_approach": approach,
        "base_year": base_year,
        "functional_currency": functional_currency,
        "materiality_threshold_pct": float(materiality),
        "status": "ACTIVE",
    }
    with store.lock:
        store.stamp_create(payload)
        store.organizations[payload["id"]] = payload
    return success_envelope(payload, status=201)


@organizations_bp.route("/organizations/<org_id>", methods=["GET"])
@require_auth(["PlatformAdmin", "DataSteward", "FactorManager", "Verifier", "Discloser"])
def read_organization(org_id):
    org = get_org_or_404(org_id)
    return success_envelope(org)


@organizations_bp.route("/organizations/<org_id>", methods=["PATCH"])
@require_auth(["PlatformAdmin"])
def update_organization(org_id):
    org = get_org_or_404(org_id)
    body = get_json_body()
    check_version(body, org)

    if "legal_name" in body:
        ln = body["legal_name"]
        if not isinstance(ln, str) or not ln.strip() or len(ln) > 200:
            raise api_error("ERR_VALIDATION_FAILED", "legal_name must be 1..200 chars")
        org["legal_name"] = ln
    if "consolidation_approach" in body:
        if body["consolidation_approach"] not in CONSOLIDATION_APPROACHES:
            raise api_error("ERR_VALIDATION_FAILED", "Invalid consolidation_approach")
        org["consolidation_approach"] = body["consolidation_approach"]
    if "materiality_threshold_pct" in body:
        org["materiality_threshold_pct"] = float(_validate_materiality(body["materiality_threshold_pct"]))

    with store.lock:
        store.stamp_update(org)
        resolve_org_boundary(org_id)
    return success_envelope(org)
