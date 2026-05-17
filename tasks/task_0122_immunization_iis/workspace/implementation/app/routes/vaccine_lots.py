"""VaccineLot routes: create, read, recall."""
from __future__ import annotations

from flask import Blueprint, jsonify

from .. import store
from ..auth import require_roles
from ..clock import format_iso, now
from ..errors import APIError
from ..helpers import (
    check_version_conflict,
    ensure_enum,
    is_int,
    parse_iso_date_or_400,
    parse_json_body,
    require_field,
)
from ..responses import build_envelope
from ..services.cascades import cascade_lot_recall


bp = Blueprint("vaccine_lots", __name__)


RECALL_REASONS = {"MANUFACTURER_DEFECT", "CONTAMINATION", "EXPIRED"}
LOT_STATUSES = {"AVAILABLE", "RECALLED", "EXHAUSTED"}


def _serialize(lot: dict) -> dict:
    return {
        "id": lot["id"],
        "vaccine_product_id": lot["vaccine_product_id"],
        "provider_organization_id": lot["provider_organization_id"],
        "lot_number": lot["lot_number"],
        "expiration_date": lot["expiration_date"],
        "doses_on_hand": lot["doses_on_hand"],
        "status": lot["status"],
        "recall_reason": lot.get("recall_reason"),
        "recalled_at": lot.get("recalled_at"),
        "created_at": lot["created_at"],
        "updated_at": lot["updated_at"],
        "version": lot["version"],
    }


@bp.post("/vaccine-lots")
@require_roles(["ProviderClinician", "PublicHealthOfficer"])
def create_lot():
    body = parse_json_body()
    product_id = require_field(body, "vaccine_product_id")
    if product_id not in store.vaccine_products:
        raise APIError("ERR_PRODUCT_NOT_FOUND", f"VaccineProduct {product_id} not found.")
    provider_id = require_field(body, "provider_organization_id")
    if provider_id not in store.provider_organizations:
        raise APIError("ERR_PROVIDER_NOT_FOUND", f"ProviderOrganization {provider_id} not found.")
    lot_number = require_field(body, "lot_number")
    if not isinstance(lot_number, str) or not lot_number:
        raise APIError("ERR_VALIDATION", "lot_number must be a non-empty string.")
    expiration = require_field(body, "expiration_date")
    parse_iso_date_or_400(expiration, "expiration_date")
    doses = require_field(body, "doses_on_hand", type_check=lambda v: is_int(v) and v >= 0)

    # Uniqueness: lot_number unique within (vaccine_product_id)
    for existing in store.vaccine_lots.values():
        if existing["vaccine_product_id"] == product_id and existing["lot_number"] == lot_number:
            raise APIError("ERR_VALIDATION", "lot_number must be unique within a vaccine product.")

    with store.lock:
        rec = {
            "vaccine_product_id": product_id,
            "provider_organization_id": provider_id,
            "lot_number": lot_number,
            "expiration_date": expiration,
            "doses_on_hand": doses,
            "status": "AVAILABLE" if doses > 0 else "EXHAUSTED",
            "recall_reason": None,
            "recalled_at": None,
        }
        store.stamp_create(rec)
        store.vaccine_lots[rec["id"]] = rec

    return jsonify(build_envelope(_serialize(rec), "object")), 201


@bp.get("/vaccine-lots/<lot_id>")
@require_roles(["ProviderClinician", "PublicHealthOfficer"])
def read_lot(lot_id: str):
    lot = store.vaccine_lots.get(lot_id)
    if not lot:
        raise APIError("ERR_LOT_NOT_FOUND", f"VaccineLot {lot_id} not found.")
    return jsonify(build_envelope(_serialize(lot), "object")), 200


@bp.post("/vaccine-lots/<lot_id>/recall")
@require_roles(["PublicHealthOfficer"])
def recall_lot(lot_id: str):
    body = parse_json_body(required=True)
    lot = store.vaccine_lots.get(lot_id)
    if not lot:
        raise APIError("ERR_LOT_NOT_FOUND", f"VaccineLot {lot_id} not found.")
    # State precondition: must be AVAILABLE or EXHAUSTED — already RECALLED is invalid.
    if lot["status"] == "RECALLED":
        raise APIError("ERR_INVALID_STATE", "Lot is already RECALLED.")
    reason = ensure_enum(require_field(body, "reason"), RECALL_REASONS, "reason")
    check_version_conflict(body, lot)

    with store.lock:
        pre_status = lot["status"]
        lot["status"] = "RECALLED"
        lot["recall_reason"] = reason
        lot["recalled_at"] = format_iso(now())
        store.stamp_update(lot)
        # Three-hop cascade
        cascade_lot_recall(lot, pre_status)
        # After inventory restoration, if lot now has >=1 and status would have been
        # EXHAUSTED — irrelevant since status is now RECALLED. Status remains RECALLED.

    return jsonify(build_envelope(_serialize(lot), "object")), 200
