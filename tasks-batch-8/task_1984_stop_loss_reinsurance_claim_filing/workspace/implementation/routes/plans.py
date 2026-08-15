"""Plan endpoints (PRD §3.1)."""
from flask import Blueprint

from middleware import authorized
from response import success_object
from routes.helpers import READ_ALL, get_one, list_response
from services.core import new_record, public
from validate import get_body, req_str

bp = Blueprint("plans", __name__)


@bp.post("/stop-loss/plans")
def create_plan():
    authorized(["PlanAdministrator"])
    body = get_body()
    plan_name = req_str(body, "plan_name")
    sponsor_tax_id = req_str(body, "sponsor_tax_id")
    rec = new_record("plans", {
        "plan_name": plan_name,
        "sponsor_tax_id": sponsor_tax_id,
        "status": "ACTIVE",
    })
    return success_object(public(rec), status=201)


@bp.get("/stop-loss/plans/<rid>")
def get_plan(rid):
    return get_one("plans", rid, READ_ALL)


@bp.get("/stop-loss/plans")
def list_plans():
    return list_response("plans", READ_ALL)
