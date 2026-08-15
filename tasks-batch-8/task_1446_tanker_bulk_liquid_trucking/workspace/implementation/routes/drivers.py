"""Drivers: CDL registry and endorsement records (PRD 3.1)."""
from flask import Blueprint, request

from authz import ALL_ROLES, FLEET_ADMIN, require_roles
from db import store
from errors import err
from respond import success
from serialize import ser_driver
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, paginate,
    reject_unknown, req_bool, req_date, req_str, sorted_by_creation, touch,
)

bp = Blueprint("drivers", __name__)


@bp.route("/drivers", methods=["POST"])
def create_driver():
    require_roles([FLEET_ADMIN])
    data = json_body()
    reject_unknown(data, {"full_name", "cdl_number", "tanker_endorsement",
                          "hazmat_endorsement", "endorsement_expires_on"})
    full_name = req_str(data, "full_name")
    cdl_number = req_str(data, "cdl_number")
    tanker = req_bool(data, "tanker_endorsement")
    hazmat = req_bool(data, "hazmat_endorsement")
    expires_on = req_date(data, "endorsement_expires_on")
    # Priority 9: cdl_number unique across all drivers.
    for d in store.drivers.values():
        if d["cdl_number"] == cdl_number:
            raise err("ERR_DUPLICATE_CDL_NUMBER",
                      "cdl_number %s already exists" % cdl_number)
    d = {
        "id": new_id(),
        "_seq": next(store.seq),
        "full_name": full_name,
        "cdl_number": cdl_number,
        "tanker_endorsement": tanker,
        "hazmat_endorsement": hazmat,
        "endorsement_expires_on": expires_on,
        "status": "ACTIVE",
    }
    d.update(new_common_fields())
    store.drivers[d["id"]] = d
    return success(ser_driver(d), status=201)


@bp.route("/drivers", methods=["GET"])
def list_drivers():
    require_roles(ALL_ROLES)
    status = request.args.get("status")
    items = [d for d in store.drivers.values()
             if status is None or d["status"] == status]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_driver(d) for d in page],
                   response_type="array", pagination=pagination)


@bp.route("/drivers/<did>", methods=["GET"])
def get_driver(did):
    require_roles(ALL_ROLES)
    return success(ser_driver(get_or_404(store.drivers, "drivers", did)))


@bp.route("/drivers/<did>/deactivate", methods=["POST"])
def deactivate_driver(did):
    require_roles([FLEET_ADMIN])
    d = get_or_404(store.drivers, "drivers", did)
    reject_unknown(json_body(), set())
    if d["status"] != "ACTIVE":
        raise err("ERR_DRIVER_NOT_ACTIVE",
                  "Deactivate requires the driver to be ACTIVE")
    d["status"] = "INACTIVE"
    touch(d)
    return success(ser_driver(d))
