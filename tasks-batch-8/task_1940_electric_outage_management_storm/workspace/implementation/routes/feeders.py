"""Feeder endpoints: register (EmergencyDirector) and get."""
from flask import Blueprint

from db import db
from middleware import require_roles, ALL_ROLES
from response import success_object
from services.core import (
    get_body, req_string, req_int, opt_int, new_common,
    get_feeder, serialize_feeder,
)

bp = Blueprint("feeders", __name__)


@bp.route("/om/feeders", methods=["POST"])
def create_feeder():
    require_roles(["EmergencyDirector"])
    body = get_body()
    code = req_string(body, "feeder_code")
    county = req_string(body, "county_code")
    scc = req_int(body, "service_customer_count", minimum=1)
    sig_thresh = opt_int(body, "cluster_signal_threshold", minimum=1, default=3)
    call_thresh = opt_int(body, "cluster_call_threshold", minimum=1, default=5)
    f = new_common()
    f.update({
        "feeder_code": code,
        "county_code": county,
        "service_customer_count": scc,
        "cluster_signal_threshold": sig_thresh,
        "cluster_call_threshold": call_thresh,
    })
    db.feeders[f["id"]] = f
    return success_object(serialize_feeder(f), status=201)


@bp.route("/om/feeders/<fid>", methods=["GET"])
def get_one_feeder(fid):
    require_roles(ALL_ROLES)
    f = get_feeder(fid)
    return success_object(serialize_feeder(f))
