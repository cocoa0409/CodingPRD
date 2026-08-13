"""DocketEntry and OfficeAction routes (PRD §3.3)."""

from flask import Blueprint, request

import db as dbmod
import serialize
from errors import (
    raise_err,
    ERR_INVALID_STATE,
    ERR_CLIENT_SUSPENDED,
    ERR_APPLICATION_NOT_OPEN,
    ERR_DEADLINE_PASSED,
    ERR_EXTENSION_NOT_ALLOWED_TYPE,
    ERR_EXTENSION_LIMIT_REACHED,
    ERR_ENTRY_NOT_CANCELLABLE,
)
from middleware import require_roles, get_json_body, parse_pagination, ALL_ROLES
from response import success_object, success_list, success_list_all
from services.common import (
    new_id, stamp_new, bump, get_application, get_entry, get_office_action,
    application_of_entry, client_of_application, rule_for_jurisdiction,
    check_allowed_fields, req_str, req_enum, req_date, ensure_transition,
    ENTRY_TYPES, ACTION_TYPES,
)
from services import calc
from services.cascade import (
    office_action_of_entry, instructions_of_entry, INSTRUCTION_NONTERMINAL,
)

bp = Blueprint("docket", __name__)

APP_OPEN_FOR_ENTRY_CREATE = {"DRAFT", "PENDING", "GRANTED"}
APP_OPEN_FOR_START_AND_EXTENSION = {"PENDING", "GRANTED"}


def _require_client_active(app):
    client = client_of_application(app)
    if client["status"] == "SUSPENDED":
        raise_err(ERR_CLIENT_SUSPENDED, "Client is SUSPENDED")


def _require_application_open(app, allowed):
    if app["status"] not in allowed:
        raise_err(
            ERR_APPLICATION_NOT_OPEN,
            f"Application in state {app['status']} does not permit this operation",
        )


# --- DocketEntry -------------------------------------------------------------

@bp.post("/applications/<application_id>/docket-entries")
def create_entry(application_id):
    require_roles(["DocketingClerk"])
    app = get_application(application_id)
    body = get_json_body()
    check_allowed_fields(body, {"entry_type", "title", "base_due_date"})
    entry_type = req_enum(body, "entry_type", ENTRY_TYPES)
    title = req_str(body, "title")
    base_due_date = req_date(body, "base_due_date")
    _require_client_active(app)
    _require_application_open(app, APP_OPEN_FOR_ENTRY_CREATE)
    rec = stamp_new({
        "id": new_id(),
        "application_id": app["id"],
        "entry_type": entry_type,
        "title": title,
        "base_due_date": base_due_date,
        "extension_count": 0,
        "extension_fees_total_cents": 0,
        "current_due_date": base_due_date,
        "status": "PENDING",
    })
    dbmod.DB["docket_entries"][rec["id"]] = rec
    app["open_docket_count"] += 1
    bump(app)
    return success_object(serialize.docket_entry(rec), 201)


@bp.get("/applications/<application_id>/docket-entries")
def list_application_entries(application_id):
    require_roles(ALL_ROLES)
    app = get_application(application_id)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    entry_type = request.args.get("entry_type")
    items = [e for e in dbmod.DB["docket_entries"].values() if e["application_id"] == app["id"]]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if entry_type is not None:
        items = [e for e in items if e["entry_type"] == entry_type]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize.docket_entry(r) for r in page], total, limit, offset)


@bp.get("/docket-entries/<entry_id>")
def get_entry_route(entry_id):
    require_roles(ALL_ROLES)
    return success_object(serialize.docket_entry(get_entry(entry_id)))


@bp.post("/docket-entries/<entry_id>/start")
def start_entry(entry_id):
    require_roles(["DocketingClerk"])
    rec = get_entry(entry_id)
    ensure_transition(rec, {"PENDING"}, "docket_entries", "DocketEntry")
    app = application_of_entry(rec)
    _require_application_open(app, APP_OPEN_FOR_START_AND_EXTENSION)
    rec["status"] = "IN_PROGRESS"
    bump(rec)
    oa = office_action_of_entry(rec["id"])
    if oa is not None and oa["status"] == "RECEIVED":
        oa["status"] = "UNDER_RESPONSE"
        bump(oa)
    return success_object(serialize.docket_entry(rec))


@bp.post("/docket-entries/<entry_id>/request-extension")
def request_extension(entry_id):
    require_roles(["DocketingClerk"])
    rec = get_entry(entry_id)
    ensure_transition(rec, {"PENDING", "IN_PROGRESS"}, "docket_entries", "DocketEntry")
    app = application_of_entry(rec)
    rule = rule_for_jurisdiction(app["jurisdiction"])
    # Business order: deadline discipline (11), then extension policy (15),
    # then the application-open gate (26).
    if rec["current_due_date"] < dbmod.current_date():
        raise_err(ERR_DEADLINE_PASSED, "current_due_date has passed")
    if rec["entry_type"] != "OFFICE_ACTION_RESPONSE":
        raise_err(ERR_EXTENSION_NOT_ALLOWED_TYPE, "Extensions apply only to OFFICE_ACTION_RESPONSE entries")
    if rec["extension_count"] >= rule["max_extensions"]:
        raise_err(ERR_EXTENSION_LIMIT_REACHED, "extension_count already equals max_extensions")
    _require_application_open(app, APP_OPEN_FOR_START_AND_EXTENSION)
    rec["extension_count"] += 1
    rec["current_due_date"] = calc.add_months(
        rec["base_due_date"], rec["extension_count"] * rule["extension_months"]
    )
    rec["extension_fees_total_cents"] += rule["extension_fee_cents"]
    bump(rec)
    return success_object(serialize.docket_entry(rec))


@bp.post("/docket-entries/<entry_id>/record-response")
def record_response(entry_id):
    require_roles(["DocketingClerk"])
    rec = get_entry(entry_id)
    body = get_json_body()
    check_allowed_fields(body, {"response_filed_date"})
    response_filed_date = req_date(body, "response_filed_date")
    ensure_transition(rec, {"IN_PROGRESS"}, "docket_entries", "DocketEntry")
    # Deadline discipline (11) precedes the application-open gate (26).
    if response_filed_date > rec["current_due_date"]:
        raise_err(ERR_DEADLINE_PASSED, "response_filed_date is after current_due_date")
    app = application_of_entry(rec)
    _require_application_open(app, {"PENDING"})
    rec["status"] = "RESPONSE_FILED"
    bump(rec)
    return success_object(serialize.docket_entry(rec))


@bp.post("/docket-entries/<entry_id>/record-rejection")
def record_rejection(entry_id):
    require_roles(["DocketingClerk"])
    rec = get_entry(entry_id)
    body = get_json_body()
    check_allowed_fields(body, {"new_base_due_date"})
    new_base_due_date = req_date(body, "new_base_due_date")
    ensure_transition(rec, {"RESPONSE_FILED"}, "docket_entries", "DocketEntry")
    rec["status"] = "IN_PROGRESS"
    rec["base_due_date"] = new_base_due_date
    rec["current_due_date"] = new_base_due_date
    rec["extension_count"] = 0
    bump(rec)
    return success_object(serialize.docket_entry(rec))


@bp.post("/docket-entries/<entry_id>/complete")
def complete_entry(entry_id):
    require_roles(["DocketingClerk"])
    rec = get_entry(entry_id)
    ensure_transition(rec, {"RESPONSE_FILED"}, "docket_entries", "DocketEntry")
    rec["status"] = "COMPLETED"
    bump(rec)
    app = application_of_entry(rec)
    app["open_docket_count"] -= 1
    bump(app)
    oa = office_action_of_entry(rec["id"])
    if oa is not None and oa["status"] == "UNDER_RESPONSE":
        oa["status"] = "CLOSED"
        bump(oa)
    return success_object(serialize.docket_entry(rec))


@bp.post("/docket-entries/<entry_id>/cancel")
def cancel_entry_route(entry_id):
    require_roles(["DocketingManager"])
    rec = get_entry(entry_id)
    ensure_transition(rec, {"PENDING", "IN_PROGRESS"}, "docket_entries", "DocketEntry")
    blocked = any(
        ins["status"] in INSTRUCTION_NONTERMINAL for ins in instructions_of_entry(rec["id"])
    )
    if blocked:
        raise_err(ERR_ENTRY_NOT_CANCELLABLE, "A linked OutsideCounselInstruction is non-terminal")
    rec["status"] = "CANCELLED"
    bump(rec)
    app = application_of_entry(rec)
    app["open_docket_count"] -= 1
    bump(app)
    return success_object(serialize.docket_entry(rec))


@bp.get("/docket-entries/<entry_id>/office-actions")
def list_entry_office_actions(entry_id):
    require_roles(ALL_ROLES)
    entry = get_entry(entry_id)
    items = [
        oa for oa in dbmod.DB["office_actions"].values()
        if oa.get("docket_entry_id") == entry["id"]
    ]
    items.sort(key=lambda r: r["created_at"])
    return success_list_all([serialize.office_action(r) for r in items])


@bp.get("/docket-entries/<entry_id>/instructions")
def list_entry_instructions(entry_id):
    require_roles(ALL_ROLES)
    entry = get_entry(entry_id)
    items = [
        ins for ins in dbmod.DB["instructions"].values()
        if ins.get("docket_entry_id") == entry["id"]
    ]
    items.sort(key=lambda r: r["created_at"])
    return success_list_all([serialize.instruction(r) for r in items])


# --- OfficeAction -------------------------------------------------------------

@bp.post("/applications/<application_id>/office-actions")
def create_office_action(application_id):
    require_roles(["DocketingClerk"])
    app = get_application(application_id)
    body = get_json_body()
    check_allowed_fields(body, {"action_type", "mail_date"})
    action_type = req_enum(body, "action_type", ACTION_TYPES)
    mail_date = req_date(body, "mail_date")
    _require_client_active(app)
    docket_entry_id = None
    if action_type in ("NON_FINAL_REJECTION", "FINAL_REJECTION"):
        rule = rule_for_jurisdiction(app["jurisdiction"])
        base_due = calc.add_months(mail_date, rule["oa_response_months"])
        entry = stamp_new({
            "id": new_id(),
            "application_id": app["id"],
            "entry_type": "OFFICE_ACTION_RESPONSE",
            "title": f"Office Action Response ({action_type})",
            "base_due_date": base_due,
            "extension_count": 0,
            "extension_fees_total_cents": 0,
            "current_due_date": base_due,
            "status": "PENDING",
        })
        dbmod.DB["docket_entries"][entry["id"]] = entry
        app["open_docket_count"] += 1
        bump(app)
        docket_entry_id = entry["id"]
    rec = stamp_new({
        "id": new_id(),
        "application_id": app["id"],
        "action_type": action_type,
        "mail_date": mail_date,
        "docket_entry_id": docket_entry_id,
        "status": "RECEIVED",
    })
    dbmod.DB["office_actions"][rec["id"]] = rec
    return success_object(serialize.office_action(rec), 201)


@bp.get("/applications/<application_id>/office-actions")
def list_application_office_actions(application_id):
    require_roles(ALL_ROLES)
    app = get_application(application_id)
    limit, offset = parse_pagination()
    items = [
        oa for oa in dbmod.DB["office_actions"].values() if oa["application_id"] == app["id"]
    ]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize.office_action(r) for r in page], total, limit, offset)


@bp.get("/office-actions/<office_action_id>")
def get_office_action_route(office_action_id):
    require_roles(ALL_ROLES)
    return success_object(serialize.office_action(get_office_action(office_action_id)))


@bp.post("/office-actions/<office_action_id>/close-informational")
def close_informational(office_action_id):
    require_roles(["DocketingClerk"])
    rec = get_office_action(office_action_id)
    ensure_transition(rec, {"RECEIVED"}, "office_actions", "OfficeAction")
    if rec["action_type"] not in ("INFORMATIONAL", "NOTICE_OF_ALLOWANCE"):
        raise_err(ERR_INVALID_STATE, "Only INFORMATIONAL or NOTICE_OF_ALLOWANCE actions close directly")
    rec["status"] = "CLOSED"
    bump(rec)
    return success_object(serialize.office_action(rec))
