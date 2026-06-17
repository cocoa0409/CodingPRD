"""ReturnInspection endpoints (PRD §3.6)."""
from flask import Blueprint, request

import errors
from db import DB, LOCK
from middleware import require_auth
from services.common import (
    new_record, require_body, req_int, req_enum, get_or_404,
)
from services.rentals import close_agreement
from .helpers import get_json_body, list_response, single_response

bp = Blueprint("return_inspections", __name__)

CLEANLINESS = {"CLEAN", "DIRTY"}


@bp.post("/rental-yard/return-inspections")
def create_inspection():
    require_auth({"Inspector"})
    body = require_body(get_json_body())

    # Existence (PRD §2.5): rental_agreement_id.
    rental_agreement_id = body.get("rental_agreement_id")
    if not isinstance(rental_agreement_id, str):
        raise errors.invalid_request("Field 'rental_agreement_id' must be a string.")

    with LOCK:
        agreement = DB.rental_agreements.get(rental_agreement_id)
        if agreement is None:
            raise errors.not_found()

        # Body shape (PRD §3.6, priority 5).
        return_fuel = req_int(body, "return_fuel_level_liters", 0)
        cleanliness = req_enum(body, "cleanliness", CLEANLINESS)
        damage_assessed = req_int(body, "damage_assessed_cents", 0)

        # State precondition: agreement must be RETURNED_PENDING_INSPECTION
        # (PRD §3.6, priority 7). Exactly one inspection per agreement.
        if agreement["agreement_state"] != "RETURNED_PENDING_INSPECTION":
            raise errors.invalid_state()

        reservation = DB.reservations.get(agreement["reservation_id"])
        unit = DB.equipment_units.get(agreement["equipment_unit_id"])
        catalog_item = DB.catalog_items.get(unit["catalog_item_id"])
        rate_card = DB.rate_cards.get(catalog_item["rate_card_id"])

        inspection = new_record({
            "rental_agreement_id": rental_agreement_id,
            "return_fuel_level_liters": return_fuel,
            "cleanliness": cleanliness,
            "damage_assessed_cents": damage_assessed,
            "fuel_refill_cents": None,
            "net_damage_cents": None,
        })
        DB.return_inspections[inspection["id"]] = inspection

        # Close the agreement, settle the account, reconcile the unit (PRD §3.6).
        close_agreement(agreement, reservation, inspection, unit,
                        catalog_item, rate_card)

    return single_response(inspection, 201)


@bp.get("/rental-yard/return-inspections/<rid>")
def get_inspection(rid):
    rec = get_or_404(DB.return_inspections, rid)
    return single_response(rec)


@bp.get("/rental-yard/return-inspections")
def list_inspections():
    rental_agreement_id = request.args.get("rental_agreement_id")
    items = DB.return_inspections.values()
    if rental_agreement_id is not None:
        items = [i for i in items if i["rental_agreement_id"] == rental_agreement_id]
    return list_response(items)
