"""Distributor endpoints."""

from flask import Blueprint

from db import db, new_id
from clock import now_iso
from middleware import (
    require_roles,
    get_auth,
    parse_json_body,
    require_fields,
    require_int,
    require_str,
)
from response import success_object
from errors import ERR_NOT_FOUND, raise_error

bp = Blueprint("distributors", __name__)


def _serialize(d):
    return dict(d)


@bp.route("/distributors", methods=["POST"])
@require_roles({"PlatformAdmin"})
def create_distributor():
    body = parse_json_body()
    require_fields(body, ["name", "contact_email", "default_split_ratio_bps", "min_show_count_per_week"])
    name = require_str(body.get("name"), "name")
    contact_email = require_str(body.get("contact_email"), "contact_email")
    default_split_ratio_bps = require_int(
        body.get("default_split_ratio_bps"), "default_split_ratio_bps", min_v=0, max_v=10000
    )
    min_show_count_per_week = require_int(
        body.get("min_show_count_per_week"), "min_show_count_per_week", min_v=0
    )
    now = now_iso()
    new_distributor = {
        "id": new_id(),
        "name": name,
        "contact_email": contact_email,
        "default_split_ratio_bps": default_split_ratio_bps,
        "min_show_count_per_week": min_show_count_per_week,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.distributors[new_distributor["id"]] = new_distributor
    return success_object(_serialize(new_distributor), http_status=201)


@bp.route("/distributors/<distributor_id>", methods=["GET"])
@require_roles({"PlatformAdmin", "DistributorOps", "CinemaOps", "FinanceOps", "Auditor"})
def get_distributor(distributor_id):
    d = db.distributors.get(distributor_id)
    if not d:
        raise_error(ERR_NOT_FOUND, "distributor not found")
    return success_object(_serialize(d))
