"""AcademicTerm endpoints (PRD 3.1)."""

from flask import Blueprint

from auth import (ROLE_BURSAR, ROLE_COMPLIANCE, ROLE_FACULTY, ROLE_PROGRAM_ADMIN,
                  ROLE_REGISTRAR, authenticate)
from calc import total_term_days
from domain import (get_term, report_json, section_json, sections_of_term,
                    term_json)
from errors import fail
from response import apply_filters, object_response, paginate
from store import base_record, db, in_order, touch
from validate import bad, f_date, f_int, f_str, get_body

bp = Blueprint("terms", __name__)

READ_ROLES = (ROLE_PROGRAM_ADMIN, ROLE_FACULTY, ROLE_REGISTRAR, ROLE_BURSAR,
              ROLE_COMPLIANCE)

TERM_FIELDS = ("code", "name", "term_start_date", "term_end_date",
               "instructional_days", "census_date", "add_drop_deadline",
               "late_registration_cutoff_date", "adoption_deadline_date",
               "disclosure_deadline_date", "opt_out_window_days")


@bp.post("/terms")
def create_term():
    authenticate(ROLE_PROGRAM_ADMIN)
    body = get_body(TERM_FIELDS)
    code = f_str(body, "code", min_len=1, max_len=16)
    name = f_str(body, "name")
    start = f_date(body, "term_start_date")
    end = f_date(body, "term_end_date")
    instructional_days = f_int(body, "instructional_days", minimum=1)
    census = f_date(body, "census_date")
    add_drop = f_date(body, "add_drop_deadline")
    late_cutoff = f_date(body, "late_registration_cutoff_date")
    adoption_deadline = f_date(body, "adoption_deadline_date")
    disclosure_deadline = f_date(body, "disclosure_deadline_date")
    window_days = f_int(body, "opt_out_window_days", required=False, default=14, minimum=1)

    if end <= start:
        bad("term_end_date must be strictly later than term_start_date")

    for existing in db.terms.values():
        if existing["code"] == code:
            fail("ERR_DUPLICATE_RESOURCE_KEY")

    term = base_record()
    term.update({
        "code": code,
        "name": name,
        "term_start_date": start,
        "term_end_date": end,
        "total_term_days": total_term_days(start, end),
        "instructional_days": instructional_days,
        "census_date": census,
        "add_drop_deadline": add_drop,
        "late_registration_cutoff_date": late_cutoff,
        "adoption_deadline_date": adoption_deadline,
        "disclosure_deadline_date": disclosure_deadline,
        "opt_out_window_days": window_days,
        "status": "PLANNING",
        "closed_at": None,
    })
    db.terms[term["id"]] = term
    return object_response(term_json(term), 201)


@bp.get("/terms/<term_id>")
def read_term(term_id):
    authenticate(*READ_ROLES)
    return object_response(term_json(get_term(term_id)))


@bp.get("/terms")
def list_terms():
    authenticate(*READ_ROLES)
    items = apply_filters(in_order(db.terms.values()),
                          [("code", "code"), ("status", "status")])
    return paginate(items, term_json)


@bp.post("/terms/<term_id>/open")
def open_term(term_id):
    authenticate(ROLE_PROGRAM_ADMIN)
    get_body(())
    term = get_term(term_id)
    if term["status"] != "PLANNING":
        fail("ERR_INVALID_STATE")
    term["status"] = "OPEN"
    touch(term)
    return object_response(term_json(term))


@bp.post("/terms/<term_id>/lock-billing")
def lock_term(term_id):
    authenticate(ROLE_PROGRAM_ADMIN)
    get_body(())
    term = get_term(term_id)
    if term["status"] != "OPEN":
        fail("ERR_INVALID_STATE")
    term["status"] = "BILLING_LOCKED"
    touch(term)
    return object_response(term_json(term))


@bp.get("/terms/<term_id>/sections")
def list_term_sections(term_id):
    authenticate(*READ_ROLES)
    term = get_term(term_id)
    items = apply_filters(sections_of_term(term["id"]), [("ia_status", "ia_status")])
    return paginate(items, section_json)


@bp.get("/terms/<term_id>/disclosure-reports")
def list_term_reports(term_id):
    authenticate(ROLE_PROGRAM_ADMIN, ROLE_COMPLIANCE)
    term = get_term(term_id)
    items = in_order([r for r in db.reports.values() if r["term_id"] == term["id"]])
    items = apply_filters(items, [("status", "status")])
    return paginate(items, report_json)
