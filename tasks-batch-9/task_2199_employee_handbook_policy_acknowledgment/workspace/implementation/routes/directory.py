"""Jurisdictions, legal reviewers and the people directory."""
from flask import Blueprint, request

import auth
import db
import validate
import web
from errors import fail

bp = Blueprint("directory", __name__)

EMPLOYMENT_STATUSES = ["ACTIVE", "ON_LEAVE", "TERMINATED"]
READ_ANY = auth.ALL_ROLES


@bp.post("/jurisdictions")
def create_jurisdiction():
    auth.authorize(["HRComplianceAdmin"])
    data = validate.body()
    state_code = validate.req_str(data, "state_code")
    if len(state_code) != 2 or not state_code.isalpha() or state_code != state_code.upper():
        fail("ERR_VALIDATION", "state_code must be exactly 2 uppercase characters")
    display_name = validate.req_str(data, "display_name")
    min_legal_review_days = validate.req_int(data, "min_legal_review_days", 0, 120)
    ack_deadline_days = validate.req_int(data, "ack_deadline_days", 1, 180)
    retention_years = validate.req_int(data, "retention_years", 1, 30)
    langs = validate.req_id_array(data, "required_language_codes")
    for code in langs:
        if len(code) != 2 or not code.isalpha() or code != code.lower():
            fail("ERR_VALIDATION", "required_language_codes entries must be 2 lowercase characters")
    if "en" not in langs:
        fail("ERR_VALIDATION", "required_language_codes must contain 'en'")
    esign = validate.opt_bool(data, "esign_permitted", True)
    proxy = validate.opt_bool(data, "proxy_ack_permitted", False)
    buffer_days = validate.opt_int(data, "ack_window_buffer_days", 3, 0, 30)
    for row in db.all_rows("jurisdictions"):
        if row["state_code"] == state_code:
            fail("ERR_DUPLICATE_RESOURCE", "state_code %s already registered" % state_code)
    row = db.base_row()
    row.update({
        "state_code": state_code,
        "display_name": display_name,
        "min_legal_review_days": min_legal_review_days,
        "ack_deadline_days": ack_deadline_days,
        "esign_permitted": esign,
        "proxy_ack_permitted": proxy,
        "retention_years": retention_years,
        "required_language_codes": langs,
        "ack_window_buffer_days": buffer_days,
    })
    db.insert("jurisdictions", row)
    return web.created("jurisdictions", row)


@bp.get("/jurisdictions")
def list_jurisdictions():
    auth.authorize(READ_ANY)
    rows = validate.query_filter(db.all_rows("jurisdictions"), "state_code")
    return web.paged("jurisdictions", rows)


@bp.get("/jurisdictions/<jurisdiction_id>")
def read_jurisdiction(jurisdiction_id):
    auth.authorize(READ_ANY)
    row = validate.path_row("jurisdictions", jurisdiction_id)
    return web.one("jurisdictions", row)


@bp.post("/legal-reviewers")
def create_reviewer():
    auth.authorize(["HRComplianceAdmin"])
    data = validate.body()
    if "jurisdiction_id" in data:
        validate.fk("jurisdictions", data.get("jurisdiction_id"))
    jurisdiction_id = validate.req_str(data, "jurisdiction_id")
    full_name = validate.req_str(data, "full_name")
    bar_number = validate.req_str(data, "bar_number")
    limit = validate.opt_int(data, "concurrent_review_limit", 2, 1, 10)
    is_active = validate.opt_bool(data, "is_active", True)
    for row in db.all_rows("legal_reviewers"):
        if row["jurisdiction_id"] == jurisdiction_id and row["bar_number"] == bar_number:
            fail("ERR_DUPLICATE_RESOURCE", "bar_number already registered in this jurisdiction")
    row = db.base_row()
    row.update({
        "jurisdiction_id": jurisdiction_id,
        "full_name": full_name,
        "bar_number": bar_number,
        "concurrent_review_limit": limit,
        "open_review_count": 0,
        "is_active": is_active,
    })
    db.insert("legal_reviewers", row)
    return web.created("legal_reviewers", row)


@bp.get("/legal-reviewers")
def list_reviewers():
    auth.authorize(["HRComplianceAdmin", "PolicyAuthor", "LegalCounsel"])
    rows = db.all_rows("legal_reviewers")
    rows = validate.query_filter(rows, "jurisdiction_id")
    rows = validate.query_filter(rows, "is_active", cast="bool")
    return web.paged("legal_reviewers", rows)


@bp.get("/legal-reviewers/<legal_reviewer_id>")
def read_reviewer(legal_reviewer_id):
    auth.authorize(["HRComplianceAdmin", "PolicyAuthor", "LegalCounsel"])
    row = validate.path_row("legal_reviewers", legal_reviewer_id)
    return web.one("legal_reviewers", row)


@bp.post("/employees")
def create_employee():
    auth.authorize(["HRComplianceAdmin"])
    data = validate.body()
    if "jurisdiction_id" in data:
        validate.fk("jurisdictions", data.get("jurisdiction_id"))
    if data.get("manager_id") is not None:
        validate.fk("employees", data.get("manager_id"))
    jurisdiction_id = validate.req_str(data, "jurisdiction_id")
    work_email = validate.req_str(data, "work_email")
    if "@" not in work_email:
        fail("ERR_VALIDATION", "work_email must contain '@'")
    full_name = validate.req_str(data, "full_name")
    manager_id = validate.opt_str(data, "manager_id", None)
    language = validate.opt_lang(data, "preferred_language_code", "en")
    needs_accessible = validate.opt_bool(data, "needs_accessible_format", False)
    employment_status = validate.opt_enum(data, "employment_status", EMPLOYMENT_STATUSES, "ACTIVE")
    for row in db.all_rows("employees"):
        if row["work_email"] == work_email:
            fail("ERR_DUPLICATE_RESOURCE", "work_email already registered")
    row = db.base_row()
    row.update({
        "jurisdiction_id": jurisdiction_id,
        "manager_id": manager_id,
        "work_email": work_email,
        "full_name": full_name,
        "preferred_language_code": language,
        "needs_accessible_format": needs_accessible,
        "employment_status": employment_status,
        "open_ack_count": 0,
        "open_escalation_count": 0,
    })
    db.insert("employees", row)
    return web.created("employees", row)


@bp.get("/employees")
def list_employees():
    auth.authorize(["HRComplianceAdmin", "PeopleManager", "PolicyAuthor"])
    rows = db.all_rows("employees")
    rows = validate.query_filter(rows, "jurisdiction_id")
    rows = validate.query_filter(rows, "manager_id")
    rows = validate.query_filter(rows, "employment_status")
    return web.paged("employees", rows)


@bp.get("/employees/<employee_id>")
def read_employee(employee_id):
    auth.authorize(["HRComplianceAdmin", "PeopleManager", "Employee"])
    row = validate.path_row("employees", employee_id)
    return web.one("employees", row)


@bp.patch("/employees/<employee_id>")
def patch_employee(employee_id):
    auth.authorize(["HRComplianceAdmin"])
    row = validate.path_row("employees", employee_id)
    data = validate.body()
    if data.get("manager_id") is not None:
        validate.fk("employees", data.get("manager_id"))
    if "employment_status" in data and data["employment_status"] is not None:
        row["employment_status"] = validate.req_enum(data, "employment_status", EMPLOYMENT_STATUSES)
    if "preferred_language_code" in data and data["preferred_language_code"] is not None:
        row["preferred_language_code"] = validate.req_lang(data, "preferred_language_code")
    if "needs_accessible_format" in data and data["needs_accessible_format"] is not None:
        row["needs_accessible_format"] = validate.req_bool(data, "needs_accessible_format")
    if "manager_id" in data:
        row["manager_id"] = validate.opt_str(data, "manager_id", None)
    db.touch(row)
    return web.one("employees", row)
