"""Sites endpoints."""
from flask import Blueprint

import errors
from db import store, new_id, now_iso
from middleware import require_auth, require_role
from response import success_object
from services import serialize
from services.validate import (get_json_body, reject_unknown_fields, require_fields,
                               as_string, as_bool, as_number, check_range, as_int)

bp = Blueprint("sites", __name__)


@bp.route("/sites", methods=["POST"])
def create_site():
    ctx = require_auth()
    body = get_json_body()
    reject_unknown_fields(body, {"name", "state_code", "contract_discount_pct",
                                 "capital_threshold_cents", "credit_hold"})
    require_fields(body, ["name", "state_code"])
    name = as_string(body["name"], "name")
    state_code = as_string(body["state_code"], "state_code")
    discount = 0
    if "contract_discount_pct" in body:
        discount = as_number(body["contract_discount_pct"], "contract_discount_pct")
        check_range(discount, "contract_discount_pct", 0, 100)
    capital = 500000
    if "capital_threshold_cents" in body:
        capital = as_int(body["capital_threshold_cents"], "capital_threshold_cents")
    credit_hold = False
    if "credit_hold" in body:
        credit_hold = as_bool(body["credit_hold"], "credit_hold")

    require_role(ctx, {"ServiceManager"})

    ts = now_iso()
    site = {
        "id": new_id(),
        "name": name,
        "state_code": state_code,
        "contract_discount_pct": discount,
        "capital_threshold_cents": capital,
        "credit_hold": credit_hold,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.sites[site["id"]] = site
    return success_object(serialize.serialize_site(site), status=201)


@bp.route("/sites/<site_id>", methods=["GET"])
def get_site(site_id):
    require_auth()
    site = store.sites.get(site_id)
    if site is None:
        raise errors.not_found(errors.ERR_SITE_NOT_FOUND, "Site not found")
    return success_object(serialize.serialize_site(site))
