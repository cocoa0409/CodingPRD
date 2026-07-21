"""Carrier endpoints (§3.1)."""
from flask import Blueprint, request

import serialize
from auth import authorize
from envelope import success
from helpers import lookup_or_404
from store import db, stamp, touch
import validate as v

bp = Blueprint("carriers", __name__)


@bp.route("/subro/carriers", methods=["POST"])
def create_carrier():
    authorize(request, {"RecoveryManager"})
    body = v.get_body(request)
    name = v.req_str(body, "name")
    naic_code = v.req_str(body, "naic_code")
    rate = v.req_int(body, "commission_rate_bps", min=1, max=10000)
    basis = v.opt_enum(body, "commission_basis", {"GROSS", "NET"}, "NET")
    carrier = stamp({
        "name": name,
        "naic_code": naic_code,
        "commission_rate_bps": rate,
        "commission_basis": basis,
        "status": "ACTIVE",
    })
    db.carriers[carrier["id"]] = carrier
    return success(serialize.carrier(carrier), "object", 201)


@bp.route("/subro/carriers/<carrier_id>", methods=["GET"])
def get_carrier(carrier_id):
    authorize(request, None)
    carrier = lookup_or_404(db.carriers, carrier_id)
    return success(serialize.carrier(carrier), "object", 200)


@bp.route("/subro/carriers/<carrier_id>/suspend", methods=["POST"])
def suspend_carrier(carrier_id):
    authorize(request, {"RecoveryManager"})
    carrier = lookup_or_404(db.carriers, carrier_id)
    carrier["status"] = "SUSPENDED"
    touch(carrier)
    return success(serialize.carrier(carrier), "object", 200)
