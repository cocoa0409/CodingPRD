"""Publisher governance (PRD 3.1)."""
from flask import Blueprint

from db import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_PUBLISHER_NOT_FOUND,
)
from middleware import require_auth
from response import success_object
from serializers import ser_publisher
from services import get_or_404
from util import is_bool, is_num, is_str, new_record, touch
from routes.helpers import body, paginate

bp = Blueprint("publishers", __name__)

ALL_ROLES = ("LibraryAdmin", "LibraryClerk", "ReturnsClerk", "BillingManager", "RightsAdvisor", "Customer")


def _validate_discount(value):
    if not is_num(value) or value < 0 or value > 0.60:
        raise ApiError(ERR_INVALID_REQUEST, 400, "rental_discount_pct must be in [0, 0.60]")


@bp.post("/library/publishers")
def create_publisher():
    require_auth("LibraryAdmin")
    data = body()
    name = data.get("name")
    if not is_str(name):
        raise ApiError(ERR_INVALID_REQUEST, 400, "name is required")
    discount = data.get("rental_discount_pct", 0)
    _validate_discount(discount)
    flags = {}
    for f in ("allows_digital_perusal", "print_only_rental", "out_of_print"):
        v = data.get(f, False)
        if not is_bool(v):
            raise ApiError(ERR_INVALID_REQUEST, 400, "%s must be a boolean" % f)
        flags[f] = v
    rec = new_record()
    rec.update(
        {
            "name": name,
            "rental_discount_pct": discount,
            "allows_digital_perusal": flags["allows_digital_perusal"],
            "print_only_rental": flags["print_only_rental"],
            "out_of_print": flags["out_of_print"],
            "status": "ACTIVE",
        }
    )
    db["publishers"][rec["id"]] = rec
    return success_object(ser_publisher(rec), status=201)


@bp.get("/library/publishers")
def list_publishers():
    require_auth(*ALL_ROLES)
    return paginate(list(db["publishers"].values()), ser_publisher)


@bp.get("/library/publishers/<pid>")
def get_publisher(pid):
    require_auth(*ALL_ROLES)
    rec = get_or_404("publishers", pid, ERR_PUBLISHER_NOT_FOUND)
    return success_object(ser_publisher(rec))


@bp.patch("/library/publishers/<pid>")
def update_publisher(pid):
    require_auth("LibraryAdmin")
    rec = get_or_404("publishers", pid, ERR_PUBLISHER_NOT_FOUND)
    data = body()

    # State-transition admissibility (tier 4) runs before payload-shape (tier 19).
    new_status = data.get("status")
    if new_status is not None:
        if new_status not in ("ACTIVE", "SUSPENDED"):
            raise ApiError(ERR_INVALID_REQUEST, 400, "status must be ACTIVE or SUSPENDED")
        if new_status == rec["status"]:
            raise ApiError(ERR_INVALID_STATE, 409, "Illegal publisher status transition")

    changed = False
    if "rental_discount_pct" in data and data["rental_discount_pct"] is not None:
        _validate_discount(data["rental_discount_pct"])
        rec["rental_discount_pct"] = data["rental_discount_pct"]
        changed = True
    for f in ("allows_digital_perusal", "print_only_rental", "out_of_print"):
        if f in data and data[f] is not None:
            if not is_bool(data[f]):
                raise ApiError(ERR_INVALID_REQUEST, 400, "%s must be a boolean" % f)
            rec[f] = data[f]
            changed = True
    if new_status is not None:
        rec["status"] = new_status
        changed = True
    if changed:
        touch(rec)
    return success_object(ser_publisher(rec))
