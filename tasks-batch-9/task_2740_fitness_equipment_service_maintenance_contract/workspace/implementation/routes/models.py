"""Equipment models and their inherited checklist templates."""
from flask import Blueprint

import db
import middleware
import response
from services import calc, domain, validate

bp = Blueprint("equipment_models", __name__)


@bp.post("/fleetcare/equipment-models")
def create_model():
    middleware.auth(middleware.CONTRACT_ADMIN, middleware.PARTS_PLANNER)
    body = middleware.body()
    manufacturer = validate.string(body, "manufacturer", min_len=1, max_len=80)
    model_code = validate.string(body, "model_code", min_len=1, max_len=40)
    category = validate.enum(body, "category", calc.CATEGORIES)
    model_year = validate.integer(body, "model_year", minimum=1990, maximum=2100)
    pm_interval = validate.integer(body, "pm_interval_hours", minimum=1)
    service_life = validate.integer(body, "expected_service_life_hours", minimum=1)
    base_annual = validate.integer(body, "base_annual_service_cents", minimum=0)
    template = validate.checklist_template(body, "checklist_template")

    row = db.base_row()
    row.update({
        "manufacturer": manufacturer,
        "model_code": model_code,
        "category": category,
        "model_year": model_year,
        "pm_interval_hours": pm_interval,
        "expected_service_life_hours": service_life,
        "base_annual_service_cents": base_annual,
        "checklist_template": template,
    })
    db.equipment_models[row["id"]] = row
    return response.created_response(row)


@bp.get("/fleetcare/equipment-models")
def list_models():
    middleware.auth(*middleware.ALL_ROLES)
    return response.listing(db.equipment_models, {
        "category": response.arg("category"),
        "manufacturer": response.arg("manufacturer"),
    })


@bp.get("/fleetcare/equipment-models/<model_id>")
def read_model(model_id):
    middleware.auth(*middleware.ALL_ROLES)
    return response.object_response(domain.need_model(model_id))
