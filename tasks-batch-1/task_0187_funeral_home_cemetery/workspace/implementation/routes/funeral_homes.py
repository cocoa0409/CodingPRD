from flask import Blueprint

import db
import validate
import serialize
from response import ok_object
from middleware import require
from services import lookup

bp = Blueprint("funeral_homes", __name__)


@bp.post("/funeral-homes")
@require("Admin")
def create_funeral_home():
    body = validate.get_json()
    name = validate.require_string(body, "name")
    # sales_tax_pct: 0 <= x < 1
    sales_tax_pct = validate.require_number(body, "sales_tax_pct", minimum=0, maximum=1,
                                            min_inclusive=True, max_inclusive=False)
    # state_trust_pct: 0 < x <= 1
    state_trust_pct = validate.require_number(body, "state_trust_pct", minimum=0, maximum=1,
                                              min_inclusive=False, max_inclusive=True)
    admin_retention = validate.optional_int(body, "trust_admin_retention_cents",
                                            default=0, minimum=0)
    chapel_buffer = validate.optional_int(body, "chapel_buffer_minutes",
                                          default=30, minimum=0)

    home = {
        "id": db.new_id(),
        "name": name,
        "sales_tax_pct": sales_tax_pct,
        "state_trust_pct": state_trust_pct,
        "trust_admin_retention_cents": admin_retention,
        "chapel_buffer_minutes": chapel_buffer,
    }
    db.stamp_create(home)
    db.funeral_homes[home["id"]] = home
    return ok_object(serialize.funeral_home(home), 201)


@bp.get("/funeral-homes/<home_id>")
@require("Admin", "Arranger", "TrustOfficer", "CemeteryClerk", "Registrar")
def get_funeral_home(home_id):
    home = lookup.funeral_home(home_id)
    return ok_object(serialize.funeral_home(home), 200)
