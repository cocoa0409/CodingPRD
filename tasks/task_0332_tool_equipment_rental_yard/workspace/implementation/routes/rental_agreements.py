"""RentalAgreement endpoints (PRD §3.6, §3.7)."""
from flask import Blueprint, request

import errors
from db import DB, LOCK
from middleware import require_auth
from services.common import clock_date_str, parse_date, get_or_404
from services.rentals import mark_return
from .helpers import get_json_body, list_response, single_response

bp = Blueprint("rental_agreements", __name__)


@bp.get("/rental-yard/rental-agreements/<rid>")
def get_agreement(rid):
    rec = get_or_404(DB.rental_agreements, rid)
    return single_response(rec)


@bp.get("/rental-yard/rental-agreements")
def list_agreements():
    filters = {
        "reservation_id": request.args.get("reservation_id"),
        "equipment_unit_id": request.args.get("equipment_unit_id"),
        "contractor_account_id": request.args.get("contractor_account_id"),
        "agreement_state": request.args.get("agreement_state"),
    }
    items = DB.rental_agreements.values()
    for field, val in filters.items():
        if val is not None:
            items = [a for a in items if a.get(field) == val]
    return list_response(items)


@bp.get("/rental-yard/rental-agreements/<rid>/ledger-entries")
def list_agreement_ledger(rid):
    get_or_404(DB.rental_agreements, rid)
    entry_type = request.args.get("entry_type")
    entries = [e for e in DB.ledger_entries.values()
               if e.get("rental_agreement_id") == rid]
    if entry_type is not None:
        entries = [e for e in entries if e["entry_type"] == entry_type]
    return list_response(entries)


@bp.post("/rental-yard/rental-agreements/<rid>/return")
def return_agreement(rid):
    require_auth({"RentalAgent"})
    with LOCK:
        agreement = get_or_404(DB.rental_agreements, rid)
        # State precondition: must be ON_RENT (PRD §3.6, priority 7).
        if agreement["agreement_state"] != "ON_RENT":
            raise errors.invalid_state()
        # Clock date must be on/after actual_start_date (PRD §3.6).
        if parse_date(clock_date_str()) < parse_date(agreement["actual_start_date"]):
            raise errors.invalid_state(
                "The yard clock current date is before actual_start_date.")
        unit = DB.equipment_units.get(agreement["equipment_unit_id"])
        catalog_item = DB.catalog_items.get(unit["catalog_item_id"])
        rate_card = DB.rate_cards.get(catalog_item["rate_card_id"])
        mark_return(agreement, rate_card)
    return single_response(agreement)
