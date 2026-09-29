"""Projects, the demand ledger record and review fee payments (PRD 3.1)."""
from flask import Blueprint

import db
import guards
import helpers
import ledger
import response
import validate
from errors import ApiError
from middleware import ALL_ROLES, authenticate
from utils import _dec, rhu

bp = Blueprint("projects", __name__)

OCCUPANCY_TYPES = ["STORAGE", "MERCANTILE", "INDUSTRIAL", "ASSEMBLY", "HEALTHCARE"]
PROJECT_STATUSES = [
    "DESIGN",
    "PERMIT_REVIEW",
    "PERMITTED",
    "ACCEPTANCE",
    "CORRECTIVE_ACTION",
    "CLOSED_OUT",
]


@bp.post("/projects")
def create_project():
    authenticate(["FirmAdmin"])
    data = validate.body()
    # admission step 5: body foreign keys, in the order the fields are listed
    guards.must_fk("engineer", validate.raw_fk(data, "lead_engineer_id"))
    guards.must_fk("reviewer", validate.raw_fk(data, "ahj_reviewer_id"))
    row = {
        "project_number": validate.req_str(data, "project_number"),
        "building_name": validate.req_str(data, "building_name"),
        "jurisdiction_code": validate.req_str(data, "jurisdiction_code"),
        "jurisdiction_state": validate.state_code(data, "jurisdiction_state"),
        "occupancy_type": validate.req_str(data, "occupancy_type", enum=OCCUPANCY_TYPES),
        "building_height_ft": validate.req_num(data, "building_height_ft", gt=0),
        "underground_lead_in_loss_psi": validate.opt_num(
            data, "underground_lead_in_loss_psi", ge=0, default=0.0
        ),
        "lead_engineer_id": validate.req_str(data, "lead_engineer_id"),
        "ahj_reviewer_id": validate.req_str(data, "ahj_reviewer_id"),
        "status": "DESIGN",
        "design_posture": "OPEN",
        "governing_hydraulic_calculation_id": None,
        "governing_demand_gpm": 0.0,
        "auxiliary_demand_gpm": 0.0,
        "total_system_demand_gpm": 0.0,
        "sealed_calculation_count": 0,
        "open_major_comment_count": 0,
        "submittal_cycle_count": 0,
        "review_fee_balance_usd": 0.00,
        "pump_required_flag": False,
    }
    db.stamp_create(row)
    db.projects[row["id"]] = row
    return response.created(response.public(row))


@bp.get("/projects/<project_id>")
def get_project(project_id):
    authenticate(ALL_ROLES)
    project = guards.must("project", project_id)
    return response.ok(response.public(project))


@bp.get("/projects")
def list_projects():
    authenticate(ALL_ROLES)
    rows = list(db.projects.values())
    rows = helpers.apply_filters(
        rows,
        [
            "lead_engineer_id",
            "ahj_reviewer_id",
            "governing_hydraulic_calculation_id",
            "status",
            "design_posture",
        ],
    )
    return helpers.list_response(rows)


@bp.post("/projects/<project_id>/fee-payments")
def pay_fee(project_id):
    authenticate(["FirmAdmin", "Contractor"])
    project = guards.must("project", project_id)
    data = validate.body()
    amount = validate.req_num(data, "amount_usd")
    guards.require_project_open(project)
    if _dec(amount) > _dec(project["review_fee_balance_usd"]):
        raise ApiError(
            "ERR_FEE_PAYMENT_EXCEEDS_BALANCE",
            "The payment exceeds the project's outstanding review fee balance.",
        )
    project["review_fee_balance_usd"] = rhu(
        _dec(project["review_fee_balance_usd"]) - _dec(amount), 2
    )
    ledger.recompute_posture(project)
    db.touch(project)
    return response.ok(response.public(project))
