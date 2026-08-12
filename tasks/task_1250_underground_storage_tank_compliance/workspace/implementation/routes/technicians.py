"""Technician registration and directory (PRD 3.4)."""
from flask import Blueprint

from authz import CONTRACTOR_ADMIN, READ_ROLES, require_roles
from db import store
from errors import invalid_request, technician_not_found
from respond import success
from serialize import ser_technician
from store_ops import (
    check_closed, get_or_404, json_body, new_common_fields, new_id, opt_bool,
    paginate, qparam, qparam_bool, req_list, req_str, sorted_by_creation,
)

bp = Blueprint("technicians", __name__)

ENDORSEMENTS = ["TIGHTNESS_TESTER", "LLD_TESTER", "CP_TESTER", "INSPECTOR"]


def get_technician_or_404(tech_id):
    return get_or_404(store.technicians, tech_id, technician_not_found)


@bp.route("/technicians", methods=["POST"])
def create_technician():
    require_roles([CONTRACTOR_ADMIN])
    data = json_body()
    check_closed(data, {"full_name", "endorsements", "trainer"})
    full_name = req_str(data, "full_name")
    endorsements = req_list(data, "endorsements")
    for e in endorsements:
        if e not in ENDORSEMENTS:
            raise invalid_request("Field endorsements must contain only %s" % ", ".join(ENDORSEMENTS))
    trainer = opt_bool(data, "trainer", default=False)
    t = {
        "id": new_id(),
        "_seq": next(store.seq),
        "full_name": full_name,
        "endorsements": list(endorsements),
        "trainer": trainer,
        "active": True,
    }
    t.update(new_common_fields())
    store.technicians[t["id"]] = t
    return success(ser_technician(t), status=201)


@bp.route("/technicians", methods=["GET"])
def list_technicians():
    require_roles(READ_ROLES)
    endorsement = qparam("endorsement")
    active = qparam_bool("active")
    items = store.technicians.values()
    if endorsement is not None:
        items = [t for t in items if endorsement in t["endorsements"]]
    if active is not None:
        items = [t for t in items if t["active"] == active]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_technician(t) for t in page], response_type="array", pagination=pagination)


@bp.route("/technicians/<tech_id>", methods=["GET"])
def get_technician(tech_id):
    require_roles(READ_ROLES)
    return success(ser_technician(get_technician_or_404(tech_id)))
