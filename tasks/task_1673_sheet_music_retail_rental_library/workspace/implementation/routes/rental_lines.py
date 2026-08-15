"""Rental lines: reads plus the lost-copy report (PRD 3.5, 3.6)."""
from flask import Blueprint, request

from calc import damage_charge
from db import db
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_RENTAL_LINE_NOT_FOUND,
)
from middleware import require_auth
from response import success_object
from serializers import ser_line
from services import get_or_404
from util import new_record, touch
from routes.helpers import paginate

bp = Blueprint("rental_lines", __name__)

STAFF_ROLES = ("LibraryAdmin", "LibraryClerk", "ReturnsClerk", "BillingManager")


@bp.get("/library/rental-lines")
def list_lines():
    require_auth(*STAFF_ROLES)
    rows = list(db["rental_lines"].values())
    oid = request.args.get("rental_order_id")
    if oid is not None:
        rows = [ln for ln in rows if ln["rental_order_id"] == oid]
    return paginate(rows, ser_line)


@bp.get("/library/rental-lines/<lid>")
def get_line(lid):
    require_auth(*STAFF_ROLES)
    rec = get_or_404("rental_lines", lid, ERR_RENTAL_LINE_NOT_FOUND)
    return success_object(ser_line(rec))


@bp.post("/library/rental-lines/<lid>/report-lost")
def report_lost(lid):
    uid, _ = require_auth("LibraryClerk")
    line = get_or_404("rental_lines", lid, ERR_RENTAL_LINE_NOT_FOUND)
    if line["status"] not in ("ON_LOAN", "OVERDUE"):
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ON_LOAN or OVERDUE line may be reported lost")
    order = db["rental_orders"].get(line["rental_order_id"])
    rental_set = db["rental_sets"].get(order["rental_set_id"]) if order else None
    line["status"] = "LOST"
    line["return_condition"] = "LOST"
    touch(line)
    # Auto-file a LOST condition report at the per-copy replacement value. The
    # set's available_copy_count is pointedly NOT incremented.
    rep = new_record()
    rep.update(
        {
            "rental_line_id": line["id"],
            "assessor_user_id": uid,
            "observed_grade": "LOST",
            "findings": None,
            "assessed_charge_cents": damage_charge(line["checkout_condition"], "LOST", rental_set),
            "status": "FILED",
        }
    )
    db["condition_reports"][rep["id"]] = rep
    return success_object(ser_line(line))
