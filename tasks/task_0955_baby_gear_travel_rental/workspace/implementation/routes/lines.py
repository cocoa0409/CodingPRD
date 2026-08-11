from flask import Blueprint, request

import services
from db import sorted_ords, store
from errors import ApiError
from middleware import require_roles
from response import ok_obj, paginate
from serialize import ser_claim, ser_line

bp = Blueprint("lines", __name__)


def _get_line(lid):
    l = store.lines.get(lid)
    if l is None:
        raise ApiError("ERR_LINE_NOT_FOUND", 404, "Reservation line not found")
    return l


def _check_line_access(line, uid, role):
    if role == "Customer":
        res = store.reservations[line["reservation_id"]]
        if res["customer_id"] != uid:
            raise ApiError("ERR_FORBIDDEN", 403, "Not the reservation owner")


@bp.get("/reservation-lines/<lid>")
def get_line(lid):
    uid, role = require_roles("Customer", "Inspector", "OperationsAdmin")
    line = _get_line(lid)
    _check_line_access(line, uid, role)
    return ok_obj(ser_line(line))


@bp.get("/reservation-lines/<lid>/damage-claims")
def line_claims(lid):
    uid, role = require_roles("Customer", "Inspector", "OperationsAdmin")
    line = _get_line(lid)
    _check_line_access(line, uid, role)
    recs = sorted_ords([c for c in store.claims.values()
                        if c["reservation_line_id"] == line["id"]])
    status = request.args.get("status")
    if status is not None:
        recs = [c for c in recs if c["status"] == status]
    return paginate(recs, ser_claim)


@bp.post("/reservation-lines/<lid>/reallocate")
def reallocate(lid):
    require_roles("OperationsAdmin")
    line = _get_line(lid)
    services.reallocate_line(line)
    return ok_obj(ser_line(line))
