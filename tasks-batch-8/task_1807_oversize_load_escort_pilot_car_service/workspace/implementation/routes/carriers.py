"""Carrier registration and reads."""

from flask import Blueprint, request

import db
from errors import ERR_CARRIER_NOT_FOUND, raise_err
from middleware import require_roles, ALL_ROLES
from response import success_object, paginate
from serializers import ser_carrier
from util import body_json, req_string, req_int, new_id

bp = Blueprint("carriers", __name__)


@bp.post("/carriers")
def create_carrier():
    require_roles("Dispatcher")
    data = body_json(request)
    name = req_string(data, "carrier_name")
    credit_limit = req_int(data, "credit_limit_cents", min_v=1)
    n = db.now()
    carrier = {
        "id": new_id(),
        "created_at": n,
        "updated_at": n,
        "version": 1,
        "_seq": db.next_seq(),
        "carrier_name": name,
        "credit_limit_cents": credit_limit,
    }
    db.carriers[carrier["id"]] = carrier
    return success_object(ser_carrier(carrier), status=201)


@bp.get("/carriers")
def list_carriers():
    require_roles(*ALL_ROLES)
    rows = sorted(db.carriers.values(), key=lambda c: (c["created_at"], c["_seq"]))
    return paginate(request, [ser_carrier(c) for c in rows])


@bp.get("/carriers/<id>")
def get_carrier(id):
    require_roles(*ALL_ROLES)
    carrier = db.carriers.get(id)
    if carrier is None:
        raise_err(ERR_CARRIER_NOT_FOUND, f"Carrier {id} not found")
    return success_object(ser_carrier(carrier))
