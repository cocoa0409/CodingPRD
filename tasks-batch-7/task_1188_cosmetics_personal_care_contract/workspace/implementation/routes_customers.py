"""Customer endpoints."""
from flask import Blueprint, g

from core import (body, check_enum, check_int, check_string, err, get_required,
                  list_page, new_entity, require_roles, success)
from services import must_get, serialize_customer
from store import db

bp = Blueprint("customers", __name__)


@bp.post("/cosmfg/customers")
@require_roles("PlantDirector")
def create_customer():
    b = body()
    name = check_string(get_required(b, "name"), "name")
    tier = check_enum(get_required(b, "tier"), {"STANDARD", "PRESTIGE"}, "tier")
    mru = check_int(get_required(b, "minimum_run_units"), "minimum_run_units", minimum=1)
    credit = check_int(get_required(b, "credit_limit_cents"), "credit_limit_cents", minimum=0)
    c = new_entity()
    c.update({
        "name": name,
        "tier": tier,
        "minimum_run_units": mru,
        "credit_limit_cents": credit,
        "outstanding_balance_cents": 0,
    })
    db.customers[c["id"]] = c
    return success(serialize_customer(c), status=201)


@bp.get("/cosmfg/customers/<cid>")
@require_roles("PlantDirector", "ProductionPlanner", "QAManager",
               "FormulationChemist", "RegulatoryAffairs", "CustomerRep")
def get_customer(cid):
    c = must_get(db.customers, cid, "Customer")
    if g.user_role == "CustomerRep" and c["id"] != g.user_id:
        err("ERR_CONFIDENTIALITY_VIOLATION", 403,
            "CustomerRep may only read their own customer record")
    return success(serialize_customer(c))


@bp.get("/cosmfg/customers")
@require_roles("PlantDirector", "ProductionPlanner")
def list_customers():
    return list_page(list(db.customers.values()), serialize_customer)
