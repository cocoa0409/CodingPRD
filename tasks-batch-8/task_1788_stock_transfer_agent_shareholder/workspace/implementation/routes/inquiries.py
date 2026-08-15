"""Shareholder inquiry endpoints."""
from flask import Blueprint, request

from db import STORE
from errors import fail
from helpers import get_body, req_str, req_enum, pagination_params
from middleware import auth, require_role, shareholder_owns
from response import success_list, success_object
from services import stamp_new, touch, audit, sorted_recs, inquiry_view, reactivate_account

bp = Blueprint("inquiries", __name__)

INQUIRY_READ_ROLES = {"ServiceAgent", "AgentAdmin", "Shareholder"}


def get_inquiry_or_404(inquiry_id):
    inquiry = STORE["inquiries"].get(inquiry_id)
    if inquiry is None:
        fail("ERR_INQUIRY_NOT_FOUND", "inquiry %s does not exist" % inquiry_id)
    return inquiry


@bp.post("/inquiries")
def create_inquiry():
    user_id, role = auth()
    require_role(role, {"Shareholder"})
    body = get_body()
    if body.get("account_id") is not None:
        shareholder_owns(user_id, body.get("account_id"))
    account_id = req_str(body, "account_id")
    account = STORE["accounts"].get(account_id)
    if account is None:
        fail("ERR_ACCOUNT_NOT_FOUND", "account %s does not exist" % account_id)
    if account["account_status"] == "ESCHEATED":
        fail("ERR_ACCOUNT_ESCHEATED", "account %s is escheated and terminal" % account_id)
    channel = req_enum(body, "channel", {"PHONE", "MAIL", "EMAIL"})
    subject = req_str(body, "subject")
    inquiry = stamp_new({
        "account_id": account["id"],
        "channel": channel,
        "subject": subject,
        "status": "OPEN",
        "claimed_by_agent_id": None,
        "answer_text": None,
    })
    STORE["inquiries"][inquiry["id"]] = inquiry
    # opening an inquiry is a qualifying owner contact (may reactivate dormancy)
    reactivate_account(account, role, user_id)
    audit("ShareholderInquiry", inquiry["id"], role, user_id, "inquiry.create",
          "", "OPEN", "shareholder inquiry opened")
    return success_object(inquiry_view(inquiry), 201)


@bp.get("/inquiries")
def list_inquiries():
    user_id, role = auth()
    require_role(role, INQUIRY_READ_ROLES)
    account_filter = request.args.get("account_id")
    status_filter = request.args.get("status")
    if role == "Shareholder" and account_filter is not None:
        shareholder_owns(user_id, account_filter)
    items = sorted_recs("inquiries")
    if account_filter is not None:
        items = [i for i in items if i["account_id"] == account_filter]
    if status_filter is not None:
        items = [i for i in items if i["status"] == status_filter]
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([inquiry_view(i) for i in page], limit, offset, total)


@bp.get("/inquiries/<inquiry_id>")
def read_inquiry(inquiry_id):
    user_id, role = auth()
    require_role(role, INQUIRY_READ_ROLES)
    inquiry = get_inquiry_or_404(inquiry_id)
    if role == "Shareholder":
        shareholder_owns(user_id, inquiry["account_id"])
    return success_object(inquiry_view(inquiry))


@bp.post("/inquiries/<inquiry_id>/claim")
def claim_inquiry(inquiry_id):
    user_id, role = auth()
    require_role(role, {"ServiceAgent"})
    inquiry = get_inquiry_or_404(inquiry_id)
    if inquiry["status"] not in ("OPEN", "ANSWERED"):
        fail("ERR_INVALID_STATE", "only an OPEN or ANSWERED inquiry can be claimed")
    frm = inquiry["status"]
    inquiry["status"] = "IN_REVIEW"
    inquiry["claimed_by_agent_id"] = user_id
    touch(inquiry)
    audit("ShareholderInquiry", inquiry["id"], role, user_id, "inquiry.claim",
          frm, "IN_REVIEW", "inquiry claimed by service agent")
    return success_object(inquiry_view(inquiry))


@bp.post("/inquiries/<inquiry_id>/answer")
def answer_inquiry(inquiry_id):
    user_id, role = auth()
    require_role(role, {"ServiceAgent"})
    inquiry = get_inquiry_or_404(inquiry_id)
    if inquiry["status"] != "IN_REVIEW":
        fail("ERR_INVALID_STATE", "only an IN_REVIEW inquiry can be answered")
    if user_id != inquiry["claimed_by_agent_id"]:
        fail("ERR_INQUIRY_CLAIMED_BY_OTHER",
             "only the claiming agent may answer this inquiry")
    body = get_body()
    answer_text = req_str(body, "answer_text")
    inquiry["answer_text"] = answer_text
    inquiry["status"] = "ANSWERED"
    touch(inquiry)
    audit("ShareholderInquiry", inquiry["id"], role, user_id, "inquiry.answer",
          "IN_REVIEW", "ANSWERED", "inquiry answered")
    return success_object(inquiry_view(inquiry))


@bp.post("/inquiries/<inquiry_id>/close")
def close_inquiry(inquiry_id):
    user_id, role = auth()
    require_role(role, {"ServiceAgent", "Shareholder"})
    inquiry = get_inquiry_or_404(inquiry_id)
    if role == "Shareholder":
        shareholder_owns(user_id, inquiry["account_id"])
    if inquiry["status"] != "ANSWERED":
        fail("ERR_INVALID_STATE", "only an ANSWERED inquiry can be closed")
    inquiry["status"] = "CLOSED"
    touch(inquiry)
    audit("ShareholderInquiry", inquiry["id"], role, user_id, "inquiry.close",
          "ANSWERED", "CLOSED", "inquiry closed")
    return success_object(inquiry_view(inquiry))
