"""Property endpoints."""

from decimal import Decimal

from flask import Blueprint

from db import store
from errors import raise_error
from middleware import require_roles
from response import success
from routes._helpers import (
    bump,
    check_version,
    get_json_body,
    parse_number,
    require_field,
    require_owner,
    require_property,
)
from services.calculations import compute_tax_bill_fields
from services.serializers import serialize_property
from utils import new_uuid, round_half_up

properties_bp = Blueprint("properties", __name__)


@properties_bp.post("/properties")
def create_property():
    require_roles({"Assessor"})
    body = get_json_body()
    owner_id = require_field(body, "owner_id")
    if not isinstance(owner_id, str):
        raise_error("ERR_VALIDATION_FAILED", "owner_id must be a string")
    require_owner(owner_id)

    parcel_number = require_field(body, "parcel_number")
    if not isinstance(parcel_number, str) or not parcel_number.strip():
        raise_error("ERR_VALIDATION_FAILED", "parcel_number must be a non-empty string")

    market_value_raw = require_field(body, "market_value")
    market_value = parse_number(market_value_raw, "market_value")
    if market_value < Decimal("0"):
        raise_error("ERR_VALIDATION_FAILED", "market_value must be non-negative")
    market_value = round_half_up(market_value, 2)

    now = store.clock.now()
    rec = {
        "id": new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "owner_id": owner_id,
        "parcel_number": parcel_number,
        "market_value": market_value,
        "capped_value": market_value,
        "ownership_change_date": now,
        "current_assessment_year": None,
    }
    with store.lock:
        store.properties[rec["id"]] = rec
    return success(serialize_property(rec), status_code=201)


@properties_bp.get("/properties/<property_id>")
def get_property(property_id):
    require_roles({"Assessor", "Treasurer", "HearingOfficer", "Owner"})
    rec = require_property(property_id)
    return success(serialize_property(rec))


@properties_bp.patch("/properties/<property_id>/owner")
def transfer_owner(property_id):
    require_roles({"Assessor"})
    rec = require_property(property_id)
    body = get_json_body()
    new_owner_id = require_field(body, "new_owner_id")
    if not isinstance(new_owner_id, str):
        raise_error("ERR_VALIDATION_FAILED", "new_owner_id must be a string")
    require_owner(new_owner_id)
    check_version(rec, body)

    with store.lock:
        rec["owner_id"] = new_owner_id
        rec["ownership_change_date"] = store.clock.now()
        bump(rec)

        # Cascade: auto-revoke APPROVED ExemptionApplications for current roll_year
        current_year = rec.get("current_assessment_year")
        if current_year is not None:
            affected_bills = set()
            for app in store.exemption_applications.values():
                if app["property_id"] != property_id:
                    continue
                if app["effective_roll_year"] != current_year:
                    continue
                if app["status"] != "APPROVED":
                    continue
                app["status"] = "REVOKED"
                app["revoked_reason"] = "OWNERSHIP_CHANGE"
                bump(app)
                # collect bills to recompute
            for tb in store.tax_bills.values():
                if tb["property_id"] != property_id:
                    continue
                if tb["roll_year"] != current_year:
                    continue
                if tb["status"] in ("PAID",):
                    continue
                affected_bills.add(tb["id"])
            for bill_id in affected_bills:
                bill = store.tax_bills[bill_id]
                old_status = bill["status"]
                compute_tax_bill_fields(bill, recompute_stack=True)
                # If bill is ISSUED/PARTIALLY_PAID, recompute may flip status
                if old_status in ("ISSUED", "PARTIALLY_PAID"):
                    if bill["total_payments_applied"] > Decimal("0") and bill["amount_due"] > Decimal("0"):
                        bill["status"] = "PARTIALLY_PAID"
                    elif bill["total_payments_applied"] >= bill["base_tax_amount"]:
                        # Already paid in full
                        bill["status"] = "PAID"
                bump(bill)

    return success(serialize_property(rec))
