"""Studio endpoints (PRD §3.1)."""
from flask import Blueprint

from db import db
from middleware import authenticate
from helpers import (
    require_role, get_json_body, require_fields, as_string, as_number,
    get_studio,
)
from response import success
from serialize import view

bp = Blueprint("studios", __name__)


@bp.route("/studios", methods=["POST"])
def create_studio():
    caller = authenticate()
    require_role(caller, "StudioOps")
    body = get_json_body()
    require_fields(body, "name")
    name = as_string(body["name"], "name")

    tax_rate = 0.0
    if "tax_rate" in body and body["tax_rate"] is not None:
        tax_rate = as_number(body["tax_rate"], "tax_rate")
    markup = 0.0
    if "license_markup_pct" in body and body["license_markup_pct"] is not None:
        markup = as_number(body["license_markup_pct"], "license_markup_pct")

    rec = db.create(db.studios, {
        "name": name,
        "tax_rate": tax_rate,
        "license_markup_pct": markup,
    })
    return success(view(rec), status=201)


@bp.route("/studios/<studio_id>", methods=["GET"])
def get_studio_ep(studio_id):
    caller = authenticate()
    require_role(caller, "StudioOps", "BillingOps", "Designer", "Client")
    rec = get_studio(studio_id)
    return success(view(rec), status=200)
