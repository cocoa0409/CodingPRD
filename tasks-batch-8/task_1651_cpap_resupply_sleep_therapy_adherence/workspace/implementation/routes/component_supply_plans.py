"""Component supply plan read endpoints (PRD 3.3). Plans are created only by
the complete-setup cascade; no POST endpoint exists."""
from flask import Blueprint, request

from routes.helpers import get_one, list_response

bp = Blueprint("component_supply_plans", __name__, url_prefix="/sleep-therapy")


@bp.get("/component-supply-plans")
def list_component_supply_plans():
    filters = {
        "patient_id": request.args.get("patient_id"),
        "component_type": request.args.get("component_type"),
        "plan_status": request.args.get("plan_status"),
    }
    return list_response("component_supply_plans", filters)


@bp.get("/component-supply-plans/<rid>")
def get_component_supply_plan(rid):
    return get_one("component_supply_plans", rid)
