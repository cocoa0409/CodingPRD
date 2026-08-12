"""Law-enforcement inquiries: register, link-case, respond, close."""
from flask import Blueprint, request

import db
import response
from errors import ApiError
from middleware import ALL_ROLES, authn, authz, get_body, pagination_params
from services.core import recompute_customer_risk
from util import base_entity, req_str, serialize, sort_created, touch

bp = Blueprint("inquiries", __name__)


def _get(store, rid, label):
    entity = store.get(rid)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", f"{label} '{rid}' does not exist", 404)
    return entity


@bp.route("/law-enforcement-inquiries", methods=["POST"])
def create_inquiry():
    body = get_body()
    agency_name = req_str(body, "agency_name")
    inquiry_reference = req_str(body, "inquiry_reference")
    subject_customer_id = req_str(body, "subject_customer_id")
    _, role = authn()
    authz(role, ["ComplianceAdmin"])
    customer = _get(db.customers, subject_customer_id, "Customer")
    inquiry = base_entity()
    inquiry.update({
        "agency_name": agency_name,
        "inquiry_reference": inquiry_reference,
        "subject_customer_id": customer["id"],
        "case_id": None,
        "received_at": db.now(),
        "status": "RECEIVED",
        "response_summary": None,
        "responded_at": None,
    })
    db.inquiries[inquiry["id"]] = inquiry
    recompute_customer_risk(customer)  # open_le_inquiry_count counts from creation
    return response.success(serialize(inquiry), status=201)


@bp.route("/law-enforcement-inquiries", methods=["GET"])
def list_inquiries():
    _, role = authn()
    authz(role, ALL_ROLES)
    limit, offset = pagination_params()
    items = list(db.inquiries.values())
    for field in ("subject_customer_id", "case_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [i for i in items if i.get(field) == value]
    items = sort_created(items)
    return response.paginated([serialize(i) for i in items], limit, offset)


@bp.route("/law-enforcement-inquiries/<rid>", methods=["GET"])
def get_inquiry(rid):
    _, role = authn()
    authz(role, ALL_ROLES)
    inquiry = _get(db.inquiries, rid, "LawEnforcementInquiry")
    return response.success(serialize(inquiry), status=200)


@bp.route("/law-enforcement-inquiries/<rid>/link-case", methods=["POST"])
def link_case(rid):
    body = get_body()
    case_id = req_str(body, "case_id")
    _, role = authn()
    authz(role, ["ComplianceAdmin"])
    inquiry = _get(db.inquiries, rid, "LawEnforcementInquiry")
    case = _get(db.cases, case_id, "Case")
    if inquiry["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE",
                       f"Inquiry in status {inquiry['status']} cannot be linked", 409)
    if inquiry["subject_customer_id"] != case["customer_id"]:
        raise ApiError("ERR_SUBJECT_MISMATCH",
                       "Inquiry subject and case customer differ", 422)
    inquiry["case_id"] = case["id"]
    inquiry["status"] = "UNDER_REVIEW"
    touch(inquiry)
    if case["status"] == "INVESTIGATING":
        case["status"] = "ON_HOLD"
        case["on_hold_inquiry_id"] = inquiry["id"]
        touch(case, bump_version=False)
    customer = db.customers.get(inquiry["subject_customer_id"])
    if customer is not None:
        recompute_customer_risk(customer)
    return response.success(serialize(inquiry), status=200)


@bp.route("/law-enforcement-inquiries/<rid>/respond", methods=["POST"])
def respond_inquiry(rid):
    body = get_body()
    summary = req_str(body, "response_summary")
    _, role = authn()
    authz(role, ["BSAManager"])
    inquiry = _get(db.inquiries, rid, "LawEnforcementInquiry")
    if inquiry["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE",
                       f"Inquiry in status {inquiry['status']} cannot be responded", 409)
    inquiry["response_summary"] = summary
    inquiry["responded_at"] = db.now()
    inquiry["status"] = "RESPONDED"
    touch(inquiry)
    return response.success(serialize(inquiry), status=200)


@bp.route("/law-enforcement-inquiries/<rid>/close", methods=["POST"])
def close_inquiry(rid):
    _, role = authn()
    authz(role, ["BSAManager"])
    inquiry = _get(db.inquiries, rid, "LawEnforcementInquiry")
    if inquiry["status"] != "RESPONDED":
        raise ApiError("ERR_INVALID_STATE",
                       f"Inquiry in status {inquiry['status']} cannot be closed", 409)
    inquiry["status"] = "CLOSED"
    touch(inquiry)
    case = db.cases.get(inquiry["case_id"]) if inquiry["case_id"] else None
    if (case is not None and case["status"] == "ON_HOLD"
            and case["on_hold_inquiry_id"] == inquiry["id"]):
        case["status"] = "INVESTIGATING"
        case["on_hold_inquiry_id"] = None
        touch(case, bump_version=False)
    customer = db.customers.get(inquiry["subject_customer_id"])
    if customer is not None:
        recompute_customer_risk(customer)  # open_le_inquiry_count -= 1
    return response.success(serialize(inquiry), status=200)
