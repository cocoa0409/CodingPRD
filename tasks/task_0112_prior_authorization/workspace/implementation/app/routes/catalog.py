"""ServiceCatalogItem routes."""
from flask import Blueprint, jsonify

from ..auth import require_auth
from ..errors import APIError
from ..helpers import check_version, get_json_body, optional_field, require_field
from ..responses import success_response
from ..services.lookups import get_catalog_or_404
from ..services.serialize import serialize_catalog_item
from ..store import get_lock, get_store, stamp_create, stamp_update


bp = Blueprint("catalog", __name__)


VALID_KINDS = {"SERVICE", "DRUG"}
VALID_EVIDENCE_CATEGORIES = {"LAB", "IMAGING", "NOTES", "MED_HISTORY", "OTHER"}


def _validate_sla_fields(standard_sla_hours, expedited_sla_hours, approval_validity_days):
    if not isinstance(standard_sla_hours, int) or isinstance(standard_sla_hours, bool):
        raise APIError("ERR_VALIDATION", "standard_sla_hours must be integer")
    if standard_sla_hours < 24:
        raise APIError("ERR_VALIDATION", "standard_sla_hours must be >= 24")
    if not isinstance(expedited_sla_hours, int) or isinstance(expedited_sla_hours, bool):
        raise APIError("ERR_VALIDATION", "expedited_sla_hours must be integer")
    if expedited_sla_hours < 4 or expedited_sla_hours >= standard_sla_hours:
        raise APIError(
            "ERR_VALIDATION",
            "expedited_sla_hours must be >= 4 and strictly less than standard_sla_hours",
        )
    if not isinstance(approval_validity_days, int) or isinstance(approval_validity_days, bool):
        raise APIError("ERR_VALIDATION", "approval_validity_days must be integer")
    if approval_validity_days < 1:
        raise APIError("ERR_VALIDATION", "approval_validity_days must be >= 1")


def _validate_categories(cats):
    if cats is None:
        return []
    if not isinstance(cats, list):
        raise APIError("ERR_VALIDATION", "required_evidence_categories must be a list")
    for c in cats:
        if c not in VALID_EVIDENCE_CATEGORIES:
            raise APIError(
                "ERR_VALIDATION",
                f"unknown evidence category {c}; allowed: {sorted(VALID_EVIDENCE_CATEGORIES)}",
            )
    return cats


@bp.post("/service-catalog-items")
@require_auth("PlatformAdmin")
def create_catalog_item():
    body = get_json_body()
    code = require_field(body, "code")
    kind = require_field(body, "kind")
    name = require_field(body, "name")
    if kind not in VALID_KINDS:
        raise APIError("ERR_VALIDATION", f"kind must be one of {sorted(VALID_KINDS)}")
    if not isinstance(code, str) or not code:
        raise APIError("ERR_VALIDATION", "code must be a non-empty string")

    requires_pa = optional_field(body, "requires_pa", True)
    if not isinstance(requires_pa, bool):
        raise APIError("ERR_VALIDATION", "requires_pa must be a boolean")
    standard_sla_hours = optional_field(body, "standard_sla_hours", 336)
    expedited_sla_hours = optional_field(body, "expedited_sla_hours", 72)
    approval_validity_days = optional_field(body, "approval_validity_days", 90)
    _validate_sla_fields(standard_sla_hours, expedited_sla_hours, approval_validity_days)
    required_evidence_categories = _validate_categories(
        optional_field(body, "required_evidence_categories", [])
    )

    with get_lock():
        store = get_store()
        for existing in store.catalog_items.values():
            if existing["code"] == code:
                raise APIError("ERR_VALIDATION", "code already exists")
        rec = {
            "code": code,
            "kind": kind,
            "name": name,
            "requires_pa": requires_pa,
            "standard_sla_hours": standard_sla_hours,
            "expedited_sla_hours": expedited_sla_hours,
            "approval_validity_days": approval_validity_days,
            "required_evidence_categories": list(required_evidence_categories),
            "status": "ACTIVE",
        }
        stamp_create(rec)
        store.catalog_items[rec["id"]] = rec

    body_out, status = success_response(serialize_catalog_item(rec), status=201)
    return jsonify(body_out), status


@bp.get("/service-catalog-items/<item_id>")
@require_auth("PlatformAdmin", "Provider", "InitialReviewer", "MedicalDirector", "ExternalReviewer")
def get_catalog_item(item_id: str):
    rec = get_catalog_or_404(item_id)
    body_out, status = success_response(serialize_catalog_item(rec))
    return jsonify(body_out), status


@bp.patch("/service-catalog-items/<item_id>")
@require_auth("PlatformAdmin")
def update_catalog_item(item_id: str):
    with get_lock():
        rec = get_catalog_or_404(item_id)
        body = get_json_body()
        check_version(rec, body.get("version"))

        new_name = body.get("name", rec["name"])
        new_std = body.get("standard_sla_hours", rec["standard_sla_hours"])
        new_exp = body.get("expedited_sla_hours", rec["expedited_sla_hours"])
        new_validity = body.get("approval_validity_days", rec["approval_validity_days"])
        _validate_sla_fields(new_std, new_exp, new_validity)
        if "required_evidence_categories" in body:
            new_cats = _validate_categories(body["required_evidence_categories"])
        else:
            new_cats = rec["required_evidence_categories"]

        # status transitions (optional): allow ACTIVE | RETIRED.
        if "status" in body:
            new_status = body["status"]
            if new_status not in {"ACTIVE", "RETIRED"}:
                raise APIError("ERR_VALIDATION", "status must be ACTIVE or RETIRED")
            rec["status"] = new_status

        rec["name"] = new_name
        rec["standard_sla_hours"] = new_std
        rec["expedited_sla_hours"] = new_exp
        rec["approval_validity_days"] = new_validity
        rec["required_evidence_categories"] = list(new_cats)
        stamp_update(rec)

    body_out, status = success_response(serialize_catalog_item(rec))
    return jsonify(body_out), status
