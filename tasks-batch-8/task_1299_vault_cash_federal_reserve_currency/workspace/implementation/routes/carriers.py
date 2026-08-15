"""Carrier endpoints."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import auth, ALL_ROLES
from response import ok, ok_list
from services import stamp_new, touch, public
from util import body, required, as_int, as_str, as_enum, pagination_args

bp = Blueprint("carriers", __name__)

CARRIER_STATUSES = {"ACTIVE", "SUSPENDED"}


def _get_carrier_or_404(carrier_id):
    carrier = DB["carriers"].get(carrier_id)
    if carrier is None:
        raise ApiError("ERR_CARRIER_NOT_FOUND", 404, "Carrier not found")
    return carrier


@bp.post("/vault-cash/carriers")
def create_carrier():
    auth(["CashOperationsAdmin"])
    data = body()
    name = as_str(required(data, "name"), "name")
    cap = as_int(
        required(data, "liability_cap_per_truck_cents"),
        "liability_cap_per_truck_cents",
    )
    carrier = stamp_new({
        "id": new_id(),
        "name": name,
        "liability_cap_per_truck_cents": cap,
        "status": "ACTIVE",
    })
    DB["carriers"][carrier["id"]] = carrier
    return ok(public(carrier), status=201)


@bp.get("/vault-cash/carriers")
def list_carriers():
    auth(ALL_ROLES)
    limit, offset = pagination_args()
    status = request.args.get("status")
    rows = list(DB["carriers"].values())
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    rows.sort(key=lambda c: (c["created_at"], c["_seq"]))
    total = len(rows)
    return ok_list([public(c) for c in rows[offset:offset + limit]], total, limit, offset)


@bp.patch("/vault-cash/carriers/<carrierId>")
def patch_carrier(carrierId):
    auth(["CashOperationsAdmin"])
    carrier = _get_carrier_or_404(carrierId)
    data = body()
    status = as_enum(required(data, "status"), "status", CARRIER_STATUSES)
    carrier["status"] = status
    touch(carrier)
    return ok(public(carrier))
