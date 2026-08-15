"""InspectionItem read endpoints (PRD §3.2)."""
from flask import Blueprint, request

from routes.helpers import get_one, list_response

bp = Blueprint("inspection_items", __name__)


@bp.get("/pm/inspection-items/<rid>")
def get_inspection_item(rid):
    return get_one("inspection_items", rid)


@bp.get("/pm/inspection-items")
def list_inspection_items():
    return list_response("inspection_items", {
        "inspection_id": request.args.get("inspection_id"),
        "linked_move_in_item_id": request.args.get("linked_move_in_item_id"),
    })
