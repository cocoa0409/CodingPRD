"""Aircraft endpoints."""
from flask import Blueprint, request

from db import STORE
from domain import new_entity, get_or_404, by_created, serialize_aircraft
from errors import ref_integrity
from middleware import auth
from response import success
from validation import get_body, field, paginate

bp = Blueprint("aircraft", __name__)


@bp.post("/aircraft")
def create_aircraft():
    auth("CenterAdmin")
    data = get_body(required=True)
    customer_id = field(data, "customer_id", "str")
    tail_number = field(data, "tail_number", "str")
    model = field(data, "model", "str")
    max_delta_lbs = field(data, "max_delta_lbs", "num")
    if customer_id not in STORE.customers:
        raise ref_integrity("customer_id does not reference an existing customer")
    ac = new_entity()
    ac.update({
        "customer_id": customer_id,
        "tail_number": tail_number,
        "model": model,
        "max_delta_lbs": max_delta_lbs,
        "status": "IN_SERVICE",
    })
    STORE.aircraft[ac["id"]] = ac
    return success(serialize_aircraft(ac), status=201)


@bp.get("/aircraft/<aid>")
def get_aircraft(aid):
    auth()
    ac = get_or_404(STORE.aircraft, aid, "Aircraft")
    return success(serialize_aircraft(ac))


@bp.get("/aircraft")
def list_aircraft():
    auth()
    items = by_created(list(STORE.aircraft.values()))
    customer_id = request.args.get("customer_id")
    if customer_id is not None:
        items = [a for a in items if a["customer_id"] == customer_id]
    return paginate(items, serialize_aircraft)
