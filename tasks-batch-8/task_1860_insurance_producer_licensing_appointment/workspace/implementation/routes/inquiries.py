"""Regulatory inquiry endpoints (PRD 3.8): open, respond (OCC-guarded), close."""

from flask import Blueprint

from core import constants as K
from core.clock import add_days
from core.envelope import filter_exact, object_response, paginate
from core.errors import fail
from core.pipeline import (
    authorize, producer_scope, req_int, req_str, require_exactly_one_subject,
    resolve, resolve_subject_refs, subject_ids,
)
from core.serialize import inquiry as serialize_inquiry
from core.store import db, new_row, bump

bp = Blueprint("inquiries", __name__)

_READ_ROLES = ("LicensingCoordinator", "ComplianceOfficer", "CarrierAdmin", "Producer")
_LIST_ROLES = ("LicensingCoordinator", "ComplianceOfficer", "CarrierAdmin")


@bp.route("/api/inquiries", methods=["POST"])
def create_inquiry():
    ctx = authorize("ComplianceOfficer")
    producer_id, agency_id = subject_ids(ctx)
    state_code = req_str(ctx.body, "state_code")
    reference_number = req_str(ctx.body, "reference_number")
    resolve_subject_refs(ctx, producer_id, agency_id)
    require_exactly_one_subject(producer_id, agency_id)
    if any(i["reference_number"] == reference_number for i in db.inquiries.values()):
        fail("ERR_INVALID_REQUEST", "An inquiry with this reference_number already exists.")
    received_at = db.now
    row = new_row("inquiries", {
        "producer_id": producer_id,
        "agency_id": agency_id,
        "state_code": state_code,
        "reference_number": reference_number,
        "received_at": received_at,
        "response_due_at": add_days(received_at, K.INQUIRY_RESPONSE_DAYS),
        "status": "OPEN",
        "response_text": None,
        "responded_at": None,
    })
    return object_response(serialize_inquiry(row), 201)


@bp.route("/api/inquiries/<inquiryId>", methods=["GET"])
def get_inquiry(inquiryId):
    ctx = authorize(*_READ_ROLES)
    row = resolve("inquiries", inquiryId)
    producer_scope(ctx, row["producer_id"])
    return object_response(serialize_inquiry(row), 200)


@bp.route("/api/inquiries", methods=["GET"])
def list_inquiries():
    authorize(*_LIST_ROLES)
    rows = db.ordered("inquiries")
    rows = filter_exact(rows, "producer_id")
    rows = filter_exact(rows, "agency_id")
    rows = filter_exact(rows, "status")
    return paginate(rows, serialize_inquiry)


@bp.route("/api/inquiries/<inquiryId>/response", methods=["POST"])
def respond_inquiry(inquiryId):
    ctx = authorize("LicensingCoordinator", "ComplianceOfficer")
    inquiry = resolve("inquiries", inquiryId)
    response_text = req_str(ctx.body, "response_text")
    expected = req_int(ctx.body, "expected_inquiry_version")
    if inquiry["status"] not in ("OPEN", "OVERDUE"):
        fail(
            "ERR_INVALID_STATE",
            "Inquiry in status {} cannot accept a response.".format(inquiry["status"]),
        )
    if expected != inquiry["version"]:
        fail("ERR_STALE_VERSION", "expected_inquiry_version does not match the inquiry version.")
    inquiry["status"] = "RESPONSE_SUBMITTED"
    inquiry["response_text"] = response_text
    inquiry["responded_at"] = db.now
    bump(inquiry)
    # A late response does NOT auto-reinstate a suspended producer.
    return object_response(serialize_inquiry(inquiry), 200)


@bp.route("/api/inquiries/<inquiryId>/close", methods=["POST"])
def close_inquiry(inquiryId):
    authorize("ComplianceOfficer")
    inquiry = resolve("inquiries", inquiryId)
    if inquiry["status"] != "RESPONSE_SUBMITTED":
        fail(
            "ERR_INVALID_STATE",
            "Inquiry in status {} cannot be closed.".format(inquiry["status"]),
        )
    inquiry["status"] = "CLOSED"
    bump(inquiry)
    return object_response(serialize_inquiry(inquiry), 200)
