"""Distributor CRUD + close_box_office_week."""
from flask import Blueprint

from db import db
from middleware import require_roles
from response import success_object
from services.core import (
    serialize_distributor, get_distributor, new_entity_common, touch,
)
from services.settlement import run_weekly_close
from services.clock import get_logical_clock
from util import iso_from_dt
from ._helpers import get_json_body, require_fields, paginate_list

bp = Blueprint("distributors", __name__)


@bp.route("/distributors", methods=["POST"])
@require_roles("PlatformAdmin")
def create_distributor(_user_id, _role):
    body = get_json_body()
    require_fields(body, ["name", "territory"])
    if not isinstance(body["name"], str) or not isinstance(body["territory"], str):
        from errors import err_invalid_request
        raise err_invalid_request("name and territory must be strings")
    common = new_entity_common()
    d = {
        **common,
        "name": body["name"],
        "territory": body["territory"],
        "week_epoch": 0,
        "logical_clock_utc": iso_from_dt(get_logical_clock()),
    }
    db.distributors[d["id"]] = d
    return success_object(serialize_distributor(d), 201)


@bp.route("/distributors/<did>", methods=["GET"])
@require_roles("Any")
def read_distributor(did, _user_id, _role):
    d = get_distributor(did)
    # Refresh logical clock
    d["logical_clock_utc"] = iso_from_dt(get_logical_clock())
    return success_object(serialize_distributor(d))


@bp.route("/distributors", methods=["GET"])
@require_roles("Any")
def list_distributors(_user_id, _role):
    items = list(db.distributors.values())
    for d in items:
        d["logical_clock_utc"] = iso_from_dt(get_logical_clock())
    return paginate_list(items, serialize_distributor)


@bp.route("/distributors/<did>/close_box_office_week", methods=["POST"])
@require_roles("SettlementClerk")
def close_box_office_week(did, _user_id, _role):
    d = get_distributor(did)
    run_weekly_close(d)
    d["logical_clock_utc"] = iso_from_dt(get_logical_clock())
    return success_object(serialize_distributor(d), 200)
