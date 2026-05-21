"""Lien endpoints — create against a Title, release."""

from decimal import Decimal

from flask import Blueprint

from config import (
    LIEN_RECORD_ACTIVE,
    LIEN_RECORD_RELEASED,
    LIEN_STATUS_ACTIVE,
    LIEN_STATUS_RELEASED,
    ROLE_LIEN_CLERK,
)
from db import store
from errors import make_error
from middleware import parse_json_body, require_auth
from response import success
from routes._helpers import check_occ, require_decimal, require_field, require_str
from services.engine import stamp_create, stamp_update
from services.serializers import serialize_lien_record
from utils import iso_format

liens_bp = Blueprint("liens", __name__)


@liens_bp.route("/titles/<title_id>/lien-records", methods=["POST"])
@require_auth(allowed_roles=[ROLE_LIEN_CLERK])
def create_lien(title_id: str):
    body = parse_json_body()
    lienholder_name = require_str(require_field(body, "lienholder_name"),
                                  "lienholder_name", min_len=1, max_len=120)
    principal_amount = require_decimal(require_field(body, "principal_amount"),
                                       "principal_amount",
                                       min_value=Decimal("0.01"),
                                       max_value=Decimal("2000000.00"))

    with store.lock:
        title = store.titles.get(title_id)
        if title is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")
        # Lien creation requires the underlying Title.is_active == True
        if not title.get("is_active"):
            raise make_error("ERR_INVALID_STATE",
                             "Lien can only be created on an active Title.")

        vehicle = store.vehicles.get(title["vehicle_id"])
        if vehicle is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")

        lien = {
            "title_id": title_id,
            "lienholder_name": lienholder_name,
            "principal_amount": principal_amount,
            "status": LIEN_RECORD_ACTIVE,
            "released_at": None,
            "release_reference": None,
        }
        stamp_create(lien, now=store.now())
        store.lien_records[lien["id"]] = lien

        # Side effect: Vehicle.lien_status := ACTIVE
        vehicle["lien_status"] = LIEN_STATUS_ACTIVE
        stamp_update(vehicle, now=store.now())

    return success(serialize_lien_record(lien), status=201)


@liens_bp.route("/lien-records/<lien_id>/release", methods=["PATCH"])
@require_auth(allowed_roles=[ROLE_LIEN_CLERK])
def release_lien(lien_id: str):
    body = parse_json_body()
    # Priority 19: release_reference required (before OCC priority 20)
    release_reference = body.get("release_reference")
    if not isinstance(release_reference, str) or not release_reference.strip():
        raise make_error("ERR_RELEASE_REFERENCE_REQUIRED")

    with store.lock:
        lien = store.lien_records.get(lien_id)
        if lien is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")
        # Already-released winner: ERR_LIEN_ALREADY_RELEASED
        if lien["status"] == LIEN_RECORD_RELEASED:
            raise make_error("ERR_LIEN_ALREADY_RELEASED")
        if lien["status"] != LIEN_RECORD_ACTIVE:
            raise make_error("ERR_INVALID_STATE")

        check_occ(body, lien)

        lien["status"] = LIEN_RECORD_RELEASED
        lien["released_at"] = iso_format(store.now())
        lien["release_reference"] = release_reference
        stamp_update(lien, now=store.now())

        # If no other ACTIVE LienRecord remains on the same title, flip vehicle.lien_status
        title = store.titles.get(lien["title_id"])
        if title is not None:
            any_active = False
            for other in store.lien_records.values():
                if other["id"] == lien["id"]:
                    continue
                if other["title_id"] == title["id"] and other["status"] == LIEN_RECORD_ACTIVE:
                    any_active = True
                    break
            if not any_active:
                vehicle = store.vehicles.get(title["vehicle_id"])
                if vehicle is not None:
                    vehicle["lien_status"] = LIEN_STATUS_RELEASED
                    stamp_update(vehicle, now=store.now())

    return success(serialize_lien_record(lien))
