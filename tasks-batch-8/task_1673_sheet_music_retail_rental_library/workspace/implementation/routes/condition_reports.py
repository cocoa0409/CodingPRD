"""Condition reports: list/get plus manual re-assessment filing (PRD 3.6)."""
from flask import Blueprint, request

from calc import damage_charge
from db import db
from errors import (
    ApiError,
    ERR_CONDITION_REPORT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_RENTAL_LINE_NOT_FOUND,
)
from middleware import require_auth
from response import success_object
from serializers import ser_report
from services import get_or_404
from util import is_str, new_record
from routes.helpers import body, paginate, require_fields

bp = Blueprint("condition_reports", __name__)

STAFF_ROLES = ("LibraryAdmin", "LibraryClerk", "ReturnsClerk", "BillingManager")
OBSERVED_GRADES = ("A", "B", "C", "D", "LOST")
FINDINGS_REQUIRED = ("C", "D", "LOST")


@bp.get("/library/condition-reports")
def list_reports():
    require_auth(*STAFF_ROLES)
    rows = list(db["condition_reports"].values())
    lid = request.args.get("rental_line_id")
    if lid is not None:
        rows = [r for r in rows if r["rental_line_id"] == lid]
    return paginate(rows, ser_report)


@bp.get("/library/condition-reports/<rid>")
def get_report(rid):
    require_auth(*STAFF_ROLES)
    rec = get_or_404("condition_reports", rid, ERR_CONDITION_REPORT_NOT_FOUND)
    return success_object(ser_report(rec))


@bp.post("/library/condition-reports")
def file_report():
    """File a re-assessment during a dispute; priced by the same damage_charge
    rule; later supersedes the original when billing re-issues against it."""
    uid, _ = require_auth("ReturnsClerk")
    data = body()
    require_fields(data, ["rental_line_id", "observed_grade"])
    line = db["rental_lines"].get(data["rental_line_id"])
    if line is None:
        raise ApiError(ERR_RENTAL_LINE_NOT_FOUND, 404, "RentalLine not found")
    grade = data["observed_grade"]
    if grade not in OBSERVED_GRADES:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid observed_grade")
    findings = data.get("findings")
    if grade in FINDINGS_REQUIRED and not is_str(findings):
        raise ApiError(ERR_INVALID_REQUEST, 400, "findings is required for grade %s" % grade)
    order = db["rental_orders"].get(line["rental_order_id"])
    rental_set = db["rental_sets"].get(order["rental_set_id"]) if order else None
    charge = damage_charge(line["checkout_condition"], grade, rental_set)
    rec = new_record()
    rec.update(
        {
            "rental_line_id": line["id"],
            "assessor_user_id": uid,
            "observed_grade": grade,
            "findings": findings,
            "assessed_charge_cents": charge,
            "status": "FILED",
        }
    )
    db["condition_reports"][rec["id"]] = rec
    return success_object(ser_report(rec), status=201)
