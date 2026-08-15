"""CE credit endpoints (PRD 3.2)."""

from flask import Blueprint

from core import calc, constants as K
from core.envelope import filter_exact, object_response, paginate
from core.errors import fail
from core.pipeline import (
    authorize, producer_scope, req_dt, req_enum, req_hours, req_str, resolve,
)
from core.serialize import ce_credit as serialize_credit
from core.store import db, new_row, bump

bp = Blueprint("ce_credits", __name__)

_READ_ROLES = ("LicensingCoordinator", "ComplianceOfficer", "CarrierAdmin", "Producer")
_LIST_ROLES = ("LicensingCoordinator", "ComplianceOfficer", "CarrierAdmin")


@bp.route("/api/ce-credits", methods=["POST"])
def create_ce_credit():
    ctx = authorize("Producer", "LicensingCoordinator")
    license_id = ctx.body.get("license_id")
    if not isinstance(license_id, str) or license_id == "":
        fail("ERR_INVALID_REQUEST", "Field 'license_id' is required and must be a string id.")
    provider_name = req_str(ctx.body, "provider_name")
    course_title = req_str(ctx.body, "course_title")
    category = req_enum(ctx.body, "category", K.CE_CATEGORIES)
    credit_hours = req_hours(ctx.body, "credit_hours")
    completed_on = req_dt(ctx.body, "completed_on")
    lic = resolve("licenses", license_id)
    producer_scope(ctx, lic["producer_id"])
    if lic["producer_id"] is None:
        fail("ERR_CE_NOT_APPLICABLE", "CE credits apply only to producer-held licenses.")
    row = new_row("ce_credits", {
        "license_id": lic["id"],
        "provider_name": provider_name,
        "course_title": course_title,
        "category": category,
        "credit_hours": credit_hours,
        "completed_on": completed_on,
        "status": "REPORTED",
        "reviewed_by_user_id": None,
    })
    return object_response(serialize_credit(row), 201)


@bp.route("/api/ce-credits/<ceCreditId>", methods=["GET"])
def get_ce_credit(ceCreditId):
    ctx = authorize(*_READ_ROLES)
    row = resolve("ce_credits", ceCreditId)
    lic = db.licenses.get(row["license_id"])
    producer_scope(ctx, lic["producer_id"] if lic is not None else None)
    return object_response(serialize_credit(row), 200)


@bp.route("/api/ce-credits", methods=["GET"])
def list_ce_credits():
    authorize(*_LIST_ROLES)
    rows = db.ordered("ce_credits")
    rows = filter_exact(rows, "license_id")
    rows = filter_exact(rows, "status")
    return paginate(rows, serialize_credit)


@bp.route("/api/ce-credits/<ceCreditId>/review", methods=["POST"])
def review_ce_credit(ceCreditId):
    ctx = authorize("LicensingCoordinator")
    row = resolve("ce_credits", ceCreditId)
    decision = req_enum(ctx.body, "decision", ("ACCEPT", "REJECT"))
    if row["status"] != "REPORTED":
        fail("ERR_INVALID_STATE", "Only a REPORTED CE credit can be reviewed.")
    row["status"] = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    row["reviewed_by_user_id"] = ctx.user_id
    bump(row)
    lic = db.licenses.get(row["license_id"])
    if lic is not None:
        calc.recompute_license_ce(lic)
        if decision == "ACCEPT":
            # An acceptance can change the license's CE counters and therefore
            # increments the license's version; a rejection never counts.
            bump(lic)
    return object_response(serialize_credit(row), 200)
