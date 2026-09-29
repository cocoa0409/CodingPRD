from flask import Blueprint

import config
from db import db
from middleware import endpoint, body
from response import created, ok
from routes.common import get_dairy, paged_list
from services import derive

bp = Blueprint("dairies", __name__)

READ_ONE_ROLES = ["PlatformAdmin", "ProjectOperator", "DairyPartner",
                  "ProgramAdministrator", "CreditVerifier", "FinanceController"]


@bp.post("/dairies")
@endpoint(["PlatformAdmin"])
def create_dairy():
    b = body()
    row = db.new_row({
        "name": b.string("name"),
        "county": b.string("county"),
        "herd_size": b.integer("herd_size", gt=0),
        "manure_management_baseline": b.enum("manure_management_baseline",
                                             ("LAGOON", "SOLID_STORAGE", "DAILY_SPREAD")),
        "haul_distance_km": b.number("haul_distance_km", 1, ge=0),
        "annual_nitrogen_budget_kg": b.number("annual_nitrogen_budget_kg", 3, gt=0),
    })
    db.dairies[row["id"]] = row
    return created(derive.ser_dairy(row))


@bp.get("/dairies")
@endpoint(list(config.ROLES))
def list_dairies():
    return paged_list(db.dairies, derive.ser_dairy, ("status", "county"))


@bp.get("/dairies/<dairy_id>")
@endpoint(READ_ONE_ROLES)
def read_dairy(dairy_id):
    return ok(derive.ser_dairy(get_dairy(dairy_id)))
