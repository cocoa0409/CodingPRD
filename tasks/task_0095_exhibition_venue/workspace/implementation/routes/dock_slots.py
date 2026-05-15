"""DockSlot / SafetyInspection routes (§3.5)."""

from flask import Blueprint, g

import response as resp
from middleware import require_roles
from services import dock_service
from services.common import serialize


bp = Blueprint("dock_slots", __name__)


@bp.route("/exhibitions/<exhibition_id>/dock-slots", methods=["POST"])
def create_dock_slot(exhibition_id):
    require_roles("Exhibitor")
    row = dock_service.create_dock_slot(exhibition_id, g.body)
    return resp.created(serialize(row))


@bp.route("/dock-slots/<slot_id>/complete", methods=["POST"])
def complete_slot(slot_id):
    require_roles("VenueOps")
    row = dock_service.complete_dock_slot(slot_id, g.body)
    return resp.success(serialize(row))


@bp.route("/dock-slots/<slot_id>/cancel", methods=["POST"])
def cancel_slot(slot_id):
    require_roles("Exhibitor")
    row = dock_service.cancel_dock_slot(slot_id, g.body)
    return resp.success(serialize(row))


@bp.route("/exhibitions/<exhibition_id>/safety-inspections", methods=["POST"])
def create_safety_inspection(exhibition_id):
    require_roles("VenueOps")
    row = dock_service.create_safety_inspection(exhibition_id, g.body)
    return resp.created(serialize(row))
