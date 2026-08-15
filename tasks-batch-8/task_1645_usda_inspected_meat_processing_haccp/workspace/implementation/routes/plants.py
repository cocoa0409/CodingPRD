"""Plant endpoints + clock."""

from flask import Blueprint

from db import store, new_id
from middleware import require_roles
from response import success_object, parse_pagination, success_list
from validation import get_body, req_string, req_number
from errors import raise_error, ERR_NOT_FOUND
from serializers import plant_out

bp = Blueprint("plants", __name__)

READ_ROLES = ("PlantAdmin", "QAManager", "QATech", "LabAnalyst", "Inspector", "ProductionManager")


@bp.route("/plants", methods=["POST"])
def create_plant():
    user_id, _ = require_roles("PlantAdmin")
    body = get_body()
    establishment_number = req_string(body, "establishment_number")
    name = req_string(body, "name")
    district_code = req_string(body, "district_code")
    cooler_capacity_lbs = req_number(body, "cooler_capacity_lbs", gt=0)

    # Uniqueness of establishment_number
    for p in store.plants.values():
        if p["establishment_number"] == establishment_number:
            from errors import ERR_INVALID_REQUEST
            raise_error(ERR_INVALID_REQUEST, "establishment_number must be unique across plants")

    now = store.now_iso()
    plant = {
        "id": new_id(),
        "establishment_number": establishment_number,
        "name": name,
        "district_code": district_code,
        "cooler_capacity_lbs": cooler_capacity_lbs,
        "cooler_occupied_lbs": 0,
        "provisional_compliance_score": 100,
        "official_compliance_score": 100,
        "operating_status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.plants[plant["id"]] = plant
    return success_object(plant_out(plant), 201)


@bp.route("/plants/<pid>", methods=["GET"])
def get_plant(pid):
    require_roles(*READ_ROLES)
    plant = store.plants.get(pid)
    if not plant:
        raise_error(ERR_NOT_FOUND, "Plant not found")
    return success_object(plant_out(plant))
