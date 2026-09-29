"""Insurer endpoints (PRD §3.4)."""

from flask import Blueprint

import serializers
from db import base_row, db
from middleware import authenticate
from response import object_response
from routes.common import get_insurer
from validation import json_body, req_bool, req_string

bp = Blueprint("insurers", __name__)

READ_ROLES = ("CatastropheDirector", "ShopEstimator", "InsurerAdjuster", "BillingCoordinator")


@bp.post("/hail-ops/insurers")
def create_insurer():
    authenticate(("CatastropheDirector",))
    body = json_body()
    name = req_string(body, "name")
    naic_code = req_string(body, "naic_code")
    direct_bill_enabled = req_bool(body, "direct_bill_enabled")

    row = base_row()
    row.update({
        "name": name,
        "naic_code": naic_code,
        "direct_bill_enabled": direct_bill_enabled,
    })
    db.insurers[row["id"]] = row
    return object_response(serializers.insurer(row), 201)


@bp.get("/hail-ops/insurers/<identifier>")
def read_insurer(identifier):
    authenticate(READ_ROLES)
    insurer = get_insurer(identifier)
    return object_response(serializers.insurer(insurer))
