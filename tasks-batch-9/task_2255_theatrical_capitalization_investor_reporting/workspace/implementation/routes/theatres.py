"""Houses (PRD 3.1)."""

from flask import Blueprint

import db
import response
import validation as v
from middleware import GENERAL_MANAGER, OPERATOR_ROLES, endpoint, find_theatre

bp = Blueprint("theatres", __name__)


@bp.post("/theatres")
@endpoint((GENERAL_MANAGER,))
def create_theatre():
    data = v.body()
    fields = {
        "name": v.req_str(data, "name", 1, 120),
        "seat_count": v.req_int(data, "seat_count", 1),
        "top_ticket_price_cents": v.req_int(data, "top_ticket_price_cents", 1),
        "changeover_buffer_days": v.opt_int(data, "changeover_buffer_days", 3, 0),
        "weekly_fixed_rent_cents": v.opt_int(data, "weekly_fixed_rent_cents", 0, 0),
    }
    return response.obj(db.insert("theatres", fields), 201)


@bp.get("/theatres/<theatre_id>")
@endpoint(OPERATOR_ROLES)
def read_theatre(theatre_id):
    return response.obj(find_theatre(theatre_id))
