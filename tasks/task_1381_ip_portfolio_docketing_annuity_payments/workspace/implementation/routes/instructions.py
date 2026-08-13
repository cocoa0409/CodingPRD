"""OutsideCounselInstruction routes (PRD §3.7) with the closed exclusivity window."""

from flask import Blueprint, request

import db as dbmod
import serialize
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_SCOPE_VIOLATION,
    ERR_CLIENT_SUSPENDED,
    ERR_APPLICATION_NOT_OPEN,
    ERR_COUNSEL_NOT_ACCREDITED,
    ERR_INSTRUCTION_EXCLUSIVE_CONFLICT,
)
from middleware import require_roles, get_json_body, parse_pagination, ALL_ROLES
from response import success_object, success_list
from services.common import (
    new_id, stamp_new, bump, get_application, get_firm, get_entry, get_instruction,
    client_of_application, check_allowed_fields, req_enum, req_date, ensure_transition,
    INSTRUCTION_TYPES,
)
from services.cascade import INSTRUCTION_NONTERMINAL

bp = Blueprint("instructions", __name__)

_CREATE_FIELDS = {"counsel_firm_id", "instruction_type", "due_date", "docket_entry_id"}


@bp.post("/applications/<application_id>/instructions")
def create_instruction(application_id):
    require_roles(["DocketingClerk", "DocketingManager"])
    app = get_application(application_id)
    body = get_json_body()
    # Existence (priority 4): body FKs resolve.
    firm_id = body.get("counsel_firm_id")
    if isinstance(firm_id, str):
        firm = get_firm(firm_id)
    else:
        firm = None
    entry_id = body.get("docket_entry_id")
    if entry_id is not None and isinstance(entry_id, str):
        get_entry(entry_id)
    # Body shape (priority 6).
    check_allowed_fields(body, _CREATE_FIELDS)
    if firm is None:
        if not isinstance(firm_id, str):
            raise_err(ERR_INVALID_REQUEST, "counsel_firm_id is required and must be a string id")
        firm = get_firm(firm_id)
    instruction_type = req_enum(body, "instruction_type", INSTRUCTION_TYPES)
    due_date = req_date(body, "due_date")
    if entry_id is not None and not isinstance(entry_id, str):
        raise_err(ERR_INVALID_REQUEST, "docket_entry_id must be a string id")
    # Business rules in PRD §2.9 order: accreditation (9), exclusivity (14),
    # suspended client (24).
    if app["jurisdiction"] not in firm["accredited_jurisdictions"]:
        raise_err(ERR_COUNSEL_NOT_ACCREDITED, "Counsel firm is not accredited for this jurisdiction")
    created_date = dbmod.current_date()
    for other in dbmod.DB["instructions"].values():
        if (
            other["application_id"] == app["id"]
            and other["instruction_type"] == instruction_type
            and other["status"] in INSTRUCTION_NONTERMINAL
        ):
            # Closed windows: [created date, due_date] on both sides; touching
            # endpoints already conflict.
            if created_date <= other["due_date"] and other["_created_date"] <= due_date:
                raise_err(
                    ERR_INSTRUCTION_EXCLUSIVE_CONFLICT,
                    "Instruction exclusivity window collides with an existing instruction",
                )
    client = client_of_application(app)
    if client["status"] == "SUSPENDED":
        raise_err(ERR_CLIENT_SUSPENDED, "Client is SUSPENDED")
    rec = stamp_new({
        "id": new_id(),
        "application_id": app["id"],
        "counsel_firm_id": firm["id"],
        "docket_entry_id": entry_id,
        "instruction_type": instruction_type,
        "due_date": due_date,
        "status": "DRAFT",
        "_created_date": created_date,
    })
    dbmod.DB["instructions"][rec["id"]] = rec
    return success_object(serialize.instruction(rec), 201)


@bp.get("/applications/<application_id>/instructions")
def list_application_instructions(application_id):
    require_roles(ALL_ROLES)
    app = get_application(application_id)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [i for i in dbmod.DB["instructions"].values() if i["application_id"] == app["id"]]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize.instruction(r) for r in page], total, limit, offset)


@bp.get("/instructions/<instruction_id>")
def get_instruction_route(instruction_id):
    require_roles(ALL_ROLES)
    return success_object(serialize.instruction(get_instruction(instruction_id)))


@bp.post("/instructions/<instruction_id>/send")
def send_instruction(instruction_id):
    require_roles(["DocketingClerk"])
    rec = get_instruction(instruction_id)
    ensure_transition(rec, {"DRAFT"}, "instructions", "OutsideCounselInstruction")
    app = dbmod.DB["applications"][rec["application_id"]]
    if app["status"] not in ("DRAFT", "PENDING", "GRANTED"):
        raise_err(ERR_APPLICATION_NOT_OPEN, "Application does not permit sending instructions")
    rec["status"] = "SENT"
    bump(rec)
    return success_object(serialize.instruction(rec))


def _counsel_scope_check(user_id, rec):
    """Priority 3: acting CounselFirm id must equal instruction.counsel_firm_id."""
    if user_id != rec["counsel_firm_id"]:
        raise_err(ERR_SCOPE_VIOLATION, "Acting counsel firm is not the instructed firm")


@bp.post("/instructions/<instruction_id>/acknowledge")
def acknowledge_instruction(instruction_id):
    user_id, _ = require_roles(["OutsideCounsel"])
    rec = get_instruction(instruction_id)
    _counsel_scope_check(user_id, rec)
    ensure_transition(rec, {"SENT"}, "instructions", "OutsideCounselInstruction")
    rec["status"] = "ACKNOWLEDGED"
    bump(rec)
    return success_object(serialize.instruction(rec))


@bp.post("/instructions/<instruction_id>/confirm")
def confirm_instruction(instruction_id):
    user_id, _ = require_roles(["OutsideCounsel"])
    rec = get_instruction(instruction_id)
    _counsel_scope_check(user_id, rec)
    ensure_transition(rec, {"ACKNOWLEDGED"}, "instructions", "OutsideCounselInstruction")
    rec["status"] = "CONFIRMED"
    bump(rec)
    return success_object(serialize.instruction(rec))


@bp.post("/instructions/<instruction_id>/decline")
def decline_instruction(instruction_id):
    user_id, _ = require_roles(["OutsideCounsel"])
    rec = get_instruction(instruction_id)
    _counsel_scope_check(user_id, rec)
    ensure_transition(rec, {"SENT"}, "instructions", "OutsideCounselInstruction")
    rec["status"] = "DECLINED"
    bump(rec)
    return success_object(serialize.instruction(rec))


@bp.post("/instructions/<instruction_id>/complete")
def complete_instruction(instruction_id):
    require_roles(["DocketingClerk"])
    rec = get_instruction(instruction_id)
    ensure_transition(rec, {"CONFIRMED"}, "instructions", "OutsideCounselInstruction")
    rec["status"] = "COMPLETED"
    bump(rec)
    return success_object(serialize.instruction(rec))


@bp.post("/instructions/<instruction_id>/cancel")
def cancel_instruction_route(instruction_id):
    require_roles(["DocketingClerk", "DocketingManager"])
    rec = get_instruction(instruction_id)
    ensure_transition(rec, {"DRAFT", "SENT"}, "instructions", "OutsideCounselInstruction")
    rec["status"] = "CANCELLED"
    bump(rec)
    return success_object(serialize.instruction(rec))
