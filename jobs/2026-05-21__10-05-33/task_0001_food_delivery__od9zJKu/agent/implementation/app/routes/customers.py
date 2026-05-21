from __future__ import annotations

from flask import Blueprint, g

from .. import projections, resolvers
from ..auth import require_role
from ..entities import bump, init_versioned
from ..envelope import err_forbidden, err_validation, success
from ..store import store
from ..validators import get_json, require_number, require_str

bp = Blueprint("customers", __name__)


def _serialize(c: dict) -> dict:
    return projections.customer(c)


@bp.route("/api/customers", methods=["POST"])
def register_customer():
    require_role("PlatformAdmin", "CustomerService")
    body = get_json()
    name = require_str(body, "name", max_len=200)
    phone = require_str(body, "phone", max_len=40)
    for c in store.customers.values():
        if c.get("phone") == phone:
            raise err_validation("phone must be unique among customers")
    address = require_str(body, "address", max_len=500)
    lat = require_number(body, "lat", minv=-90, maxv=90)
    lng = require_number(body, "lng", minv=-180, maxv=180)
    c = init_versioned("Customer")
    c.update(
        {
            "name": name,
            "phone": phone,
            "address": address,
            "lat": lat,
            "lng": lng,
            "credit_balance_cents": 0,
            "trust_score": 1.0,
        }
    )
    store.customers[c["id"]] = c
    return success(_serialize(c), status=201)


@bp.route("/api/customers/<cid>", methods=["GET"])
def read_customer(cid: str):
    require_role("PlatformAdmin", "Customer", "CustomerService")
    c = resolvers.customer(cid)
    if g.user_role == "Customer" and g.user_id != c["id"]:
        raise err_forbidden("Customer identity mismatch")
    return success(_serialize(c))
