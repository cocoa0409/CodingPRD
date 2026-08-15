"""Tank trailers: fleet records with the weight skeleton (PRD 3.1)."""
from flask import Blueprint, request

from authz import ALL_ROLES, FLEET_ADMIN, require_roles
from db import store
from errors import err
from respond import success
from serialize import ser_trailer
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, paginate,
    reject_unknown, req_int, req_str, sorted_by_creation,
)

bp = Blueprint("trailers", __name__)

TARE_FIELDS = ("tare_weight_lb", "tare_steer_lb", "tare_drive_lb", "tare_trailer_lb")
RATING_FIELDS = ("steer_axle_rating_lb", "drive_axle_rating_lb", "trailer_axle_rating_lb", "gvwr_lb")


@bp.route("/trailers", methods=["POST"])
def create_trailer():
    require_roles([FLEET_ADMIN])
    data = json_body()
    reject_unknown(data, {"unit_number", "capacity_gallons"} | set(TARE_FIELDS) | set(RATING_FIELDS))
    unit_number = req_str(data, "unit_number")
    capacity = req_int(data, "capacity_gallons", minimum=1)
    vals = {f: req_int(data, f, minimum=0) for f in TARE_FIELDS + RATING_FIELDS}
    # Priority 4 shape: tare axle components must sum to the stated tare weight.
    if (vals["tare_steer_lb"] + vals["tare_drive_lb"] + vals["tare_trailer_lb"]
            != vals["tare_weight_lb"]):
        raise err("ERR_TARE_AXLE_MISMATCH",
                  "tare_steer_lb + tare_drive_lb + tare_trailer_lb must equal tare_weight_lb")
    # Priority 9: unit_number unique across all trailers.
    for t in store.trailers.values():
        if t["unit_number"] == unit_number:
            raise err("ERR_DUPLICATE_UNIT_NUMBER",
                      "unit_number %s already exists" % unit_number)
    t = {
        "id": new_id(),
        "_seq": next(store.seq),
        "unit_number": unit_number,
        "capacity_gallons": capacity,
        "last_product_group": None,
        "last_wash_cert_id": None,
        "dedicated_customer_id": None,
        "status": "AVAILABLE",
    }
    t.update(vals)
    t.update(new_common_fields())
    store.trailers[t["id"]] = t
    return success(ser_trailer(t), status=201)


@bp.route("/trailers", methods=["GET"])
def list_trailers():
    require_roles(ALL_ROLES)
    status = request.args.get("status")
    dedicated = request.args.get("dedicated_customer_id")
    last_cert = request.args.get("last_wash_cert_id")
    items = [t for t in store.trailers.values()
             if (status is None or t["status"] == status)
             and (dedicated is None or t["dedicated_customer_id"] == dedicated)
             and (last_cert is None or t["last_wash_cert_id"] == last_cert)]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_trailer(t) for t in page],
                   response_type="array", pagination=pagination)


@bp.route("/trailers/<tid>", methods=["GET"])
def get_trailer(tid):
    require_roles(ALL_ROLES)
    return success(ser_trailer(get_or_404(store.trailers, "trailers", tid)))
