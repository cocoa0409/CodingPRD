"""Distributor endpoints (PRD §3.1). Distributor is a lean entity: id + created_at."""
from __future__ import annotations

from flask import Blueprint

import db
import errors as E
from middleware import authenticate, authorize, CINEMA_MANAGER, DISTRIBUTOR
import response
from services import common as C
from routes._helpers import get_or_404, require_distributor_owns_distributor

bp = Blueprint("distributors", __name__)


@bp.route("/distributors", methods=["POST"])
def create_distributor():
    role = authenticate()
    authorize(role, {CINEMA_MANAGER})
    body = C.get_body()
    C.require_fields(body, ["name"])
    name = C.require_str(body, "name")

    mg = body.get("minimum_guarantee_cents", 0)
    if mg is None:
        mg = 0
    if not C.is_int(mg) or mg < 0:
        raise E.invalid_request("minimum_guarantee_cents must be an integer >= 0")

    dist = C.new_lean_fields()
    dist.update({
        "name": name,
        "minimum_guarantee_cents": mg,
    })
    db.distributors[dist["id"]] = dist
    return response.ok_object(C.serialize(dist), 201)


@bp.route("/distributors/<dist_id>", methods=["GET"])
def get_distributor(dist_id):
    role = authenticate()
    authorize(role, {CINEMA_MANAGER, DISTRIBUTOR})
    dist = get_or_404(db.distributors, dist_id, "Distributor")
    require_distributor_owns_distributor(dist_id)
    return response.ok_object(C.serialize(dist), 200)
