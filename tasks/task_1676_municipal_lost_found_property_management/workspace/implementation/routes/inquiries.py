"""Public inquiries (PRD 3.3)."""
from datetime import timedelta

from flask import Blueprint

from db import db
from errors import raise_error, ERR_INVALID_STATE
from middleware import authorized, STAFF_ROLES
from response import success_object, success_list
from services import core
from util import CLOCK, fmt_sec
from validate import (
    get_body, req_str, opt_str, require_path, require_ref,
    pagination_params, opt_query_enum, opt_query_str, paginate,
)

bp = Blueprint("inquiries", __name__)

INTAKE = {"IntakeOfficer"}


@bp.post("/inquiries")
def create_inquiry():
    body = get_body()
    contact_email = req_str(body, "contact_email")
    subject = req_str(body, "subject")
    message = req_str(body, "message")
    item_id = opt_str(body, "item_id", None)
    program_id = opt_str(body, "program_id", None)
    authorized({"PublicUser"})
    # Body-referenced FK existence (PRD 2.8), when present.
    program = None
    if program_id is not None:
        program = require_ref("programs", program_id, "program_id")
    item = None
    if item_id is not None:
        item = require_ref("items", item_id, "item_id")
    # SLA variant: item's program governs when item_id present; else program_id;
    # else no program context -> FACILITY variant (3.3).
    if item is not None:
        program = db["programs"].get(item["program_id"])
    hours = 24 if (program is not None and program["program_type"] == "TRANSIT") else 72
    sla_deadline = fmt_sec(CLOCK.now() + timedelta(hours=hours))
    rec = core.new_record("inquiries", {
        "item_id": item_id,
        "program_id": program_id,
        "contact_email": contact_email,
        "subject": subject,
        "message": message,
        "status": "OPEN",
        "sla_deadline": sla_deadline,
        "answer_text": None,
        "answered_by": None,
    })
    return success_object(rec, 201)


@bp.get("/inquiries")
def list_inquiries():
    limit, offset = pagination_params()
    item_id = opt_query_str("item_id")
    program_id = opt_query_str("program_id")
    status = opt_query_enum("status", core.INQUIRY_STATUSES)
    authorized(STAFF_ROLES)
    recs = list(db["inquiries"].values())
    if item_id is not None:
        recs = [r for r in recs if r["item_id"] == item_id]
    if program_id is not None:
        recs = [r for r in recs if r["program_id"] == program_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, total = paginate(recs, limit, offset)
    return success_list(page, total, limit, offset)


@bp.get("/inquiries/<inquiry_id>")
def get_inquiry(inquiry_id):
    authorized(STAFF_ROLES)
    rec = require_path("inquiries", inquiry_id)
    return success_object(rec)


@bp.post("/inquiries/<inquiry_id>/answer")
def answer_inquiry(inquiry_id):
    body = get_body()
    answer_text = req_str(body, "answer_text")
    caller = authorized(INTAKE)
    rec = require_path("inquiries", inquiry_id)
    if rec["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "only an OPEN inquiry can be answered")
    rec["answer_text"] = answer_text
    rec["answered_by"] = caller.user_id
    rec["status"] = "ANSWERED"
    core.touch(rec)
    return success_object(rec)


@bp.post("/inquiries/<inquiry_id>/close")
def close_inquiry(inquiry_id):
    authorized(INTAKE)
    rec = require_path("inquiries", inquiry_id)
    if rec["status"] not in ("OPEN", "ANSWERED"):
        raise_error(ERR_INVALID_STATE, "only an OPEN or ANSWERED inquiry can be closed")
    rec["status"] = "CLOSED"
    core.touch(rec)
    return success_object(rec)
