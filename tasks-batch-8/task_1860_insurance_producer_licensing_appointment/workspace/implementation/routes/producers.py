"""Producer endpoints (PRD 3.1) plus the eligibility computed read (PRD 3.9)."""

from flask import Blueprint, request

from core import calc, constants as K
from core.envelope import filter_exact, object_response, paginate
from core.errors import fail
from core.pipeline import (
    authorize, producer_scope, req_str, resolve, resolve_body_ref,
)
from core.serialize import producer as serialize_producer
from core.store import db, new_row, bump

bp = Blueprint("producers", __name__)

_READ_ROLES = (
    "LicensingCoordinator", "ComplianceOfficer", "FinanceOps",
    "CarrierAdmin", "Producer",
)
_LIST_ROLES = ("LicensingCoordinator", "ComplianceOfficer", "FinanceOps", "CarrierAdmin")


@bp.route("/api/producers", methods=["POST"])
def create_producer():
    ctx = authorize("LicensingCoordinator")
    npn = req_str(ctx.body, "npn")
    full_name = req_str(ctx.body, "full_name")
    resident_state_code = req_str(ctx.body, "resident_state_code")
    agency = resolve_body_ref(ctx, "agency_id", "agencies")
    if any(p["npn"] == npn for p in db.producers.values()):
        fail("ERR_INVALID_REQUEST", "A producer with this npn already exists.")
    row = new_row("producers", {
        "npn": npn,
        "full_name": full_name,
        "resident_state_code": resident_state_code,
        "agency_id": agency["id"] if agency is not None else None,
        "status": "ACTIVE",
        "ytd_issued_premium_cents": 0,
        "commission_held_cents": 0,
    })
    return object_response(serialize_producer(row), 201)


@bp.route("/api/producers/<producerId>", methods=["GET"])
def get_producer(producerId):
    ctx = authorize(*_READ_ROLES)
    row = resolve("producers", producerId)
    producer_scope(ctx, row["id"])
    return object_response(serialize_producer(row), 200)


@bp.route("/api/producers", methods=["GET"])
def list_producers():
    authorize(*_LIST_ROLES)
    rows = db.ordered("producers")
    rows = filter_exact(rows, "agency_id")
    rows = filter_exact(rows, "status")
    return paginate(rows, serialize_producer)


@bp.route("/api/producers/<producerId>/reinstate", methods=["POST"])
def reinstate_producer(producerId):
    authorize("ComplianceOfficer")
    row = resolve("producers", producerId)
    if row["status"] != "SUSPENDED":
        fail("ERR_INVALID_STATE", "Only a SUSPENDED producer can be reinstated.")
    overdue = any(
        i for i in db.inquiries.values()
        if i["producer_id"] == row["id"] and i["status"] == "OVERDUE"
    )
    if overdue:
        fail(
            "ERR_OVERDUE_INQUIRY_EXISTS",
            "An inquiry naming this producer is still OVERDUE.",
        )
    row["status"] = "ACTIVE"
    bump(row)
    return object_response(serialize_producer(row), 200)


@bp.route("/api/producers/<producerId>/eligibility", methods=["GET"])
def producer_eligibility(producerId):
    ctx = authorize(*_READ_ROLES)
    row = resolve("producers", producerId)
    producer_scope(ctx, row["id"])
    state_code = request.args.get("state_code")
    loa = request.args.get("line_of_authority")
    if not state_code:
        fail("ERR_INVALID_REQUEST", "Query parameter 'state_code' is required.")
    if loa not in K.LOAS:
        fail(
            "ERR_INVALID_REQUEST",
            "Query parameter 'line_of_authority' must be one of {}.".format(", ".join(K.LOAS)),
        )
    posture = calc.eligibility_posture(row, state_code, loa)
    return object_response(posture, 200)
