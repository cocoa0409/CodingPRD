from flask import Blueprint

import errors
from errors import err
from db import db
from models import make_common, touch, serialize
from middleware import get_identity, require_role
from helpers import get_json_body, lookup, parse_pagination
from response import success
from services import domain

bp = Blueprint("facilities", __name__)


@bp.post("/facilities")
def create_facility():
    _, role = get_identity()
    require_role(role, {"FacilityManager"})
    body = get_json_body()

    name = body.get("name")
    state_code = body.get("state_code")
    if not isinstance(name, str) or not name:
        raise err(errors.ERR_INVALID_REQUEST, "name is required")
    if not isinstance(state_code, str) or not state_code:
        raise err(errors.ERR_INVALID_REQUEST, "state_code is required")

    climate_premium_pct = body.get("climate_premium_pct", 0.20)
    lien_default_days = body.get("lien_default_days", 90)
    late_fee_grace_days = body.get("late_fee_grace_days", 5)
    late_fee_cents = body.get("late_fee_cents", 2000)

    if isinstance(climate_premium_pct, bool) or not isinstance(climate_premium_pct, (int, float)):
        raise err(errors.ERR_INVALID_REQUEST, "climate_premium_pct must be a number")
    if climate_premium_pct < 0 or climate_premium_pct > 1:
        raise err(errors.ERR_INVALID_REQUEST, "climate_premium_pct must be within [0, 1]")
    for fld, val, lo in (("lien_default_days", lien_default_days, 1),
                         ("late_fee_grace_days", late_fee_grace_days, 0),
                         ("late_fee_cents", late_fee_cents, 0)):
        if isinstance(val, bool) or not isinstance(val, int):
            raise err(errors.ERR_INVALID_REQUEST, f"{fld} must be an integer")
        if val < lo:
            raise err(errors.ERR_INVALID_REQUEST, f"{fld} must be >= {lo}")

    fac = make_common()
    fac.update({
        "name": name,
        "state_code": state_code,
        "climate_premium_pct": climate_premium_pct,
        "lien_default_days": lien_default_days,
        "late_fee_grace_days": late_fee_grace_days,
        "late_fee_cents": late_fee_cents,
        "occupied_unit_count": 0,
    })
    db.facilities[fac["id"]] = fac
    return success(serialize(fac), 201)


@bp.get("/facilities/<facility_id>")
def get_facility(facility_id):
    get_identity()
    fac = lookup(db.facilities, facility_id, "facility")
    return success(serialize(fac), 200)


@bp.post("/facilities/<facility_id>/billing-cycles")
def run_billing(facility_id):
    _, role = get_identity()
    require_role(role, {"FacilityManager"})
    fac = lookup(db.facilities, facility_id, "facility")
    domain.run_billing_cycle(fac)
    return success(serialize(fac), 200)
