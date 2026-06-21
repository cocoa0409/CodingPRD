"""DamageCharge endpoints (PRD §3.6, §3.7)."""
from flask import Blueprint, request

from db import DB
from services.common import get_or_404
from .helpers import list_response, single_response

bp = Blueprint("damage_charges", __name__)


@bp.get("/rental-yard/damage-charges/<rid>")
def get_damage_charge(rid):
    rec = get_or_404(DB.damage_charges, rid)
    return single_response(rec)


@bp.get("/rental-yard/damage-charges")
def list_damage_charges():
    rental_agreement_id = request.args.get("rental_agreement_id")
    return_inspection_id = request.args.get("return_inspection_id")
    items = DB.damage_charges.values()
    if rental_agreement_id is not None:
        items = [d for d in items if d["rental_agreement_id"] == rental_agreement_id]
    if return_inspection_id is not None:
        items = [d for d in items if d["return_inspection_id"] == return_inspection_id]
    return list_response(items)
