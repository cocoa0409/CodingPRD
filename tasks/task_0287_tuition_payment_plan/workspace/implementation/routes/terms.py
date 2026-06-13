"""AcademicTerm routes (PRD §3.1)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import get_user_context, require_role
from response import success
from services import dates, validate, domain
from services.listing import paginate_and_render
from services.serialize import term_view

bp = Blueprint("terms", __name__)

ALL_ROLES = ("Registrar", "Bursar", "Student")


def _require_date(body, field):
    raw = body.get(field)
    parsed = dates.parse_iso(raw)
    if parsed is None:
        raise err("ERR_INVALID_REQUEST", "Missing or invalid date field: %s" % field)
    return parsed


@bp.route("/institutions/terms", methods=["POST"])
def create_term():
    _, role = get_user_context()
    require_role(role, ("Registrar",))
    body = validate.get_body()

    institution_id = validate.require_string(body, "institution_id")
    institution = db.institutions.get(institution_id)
    if institution is None:
        raise err("ERR_NOT_FOUND", "Institution not found")

    code = validate.require_string(body, "code")
    term_start = _require_date(body, "term_start")
    term_end = _require_date(body, "term_end")
    enroll_open = _require_date(body, "enroll_open")
    enroll_close = _require_date(body, "enroll_close")

    # term_total_days = floor((term_end - term_start)/1 day) + 1, must be >= 1.
    total_days = (dates.day_number(term_end) - dates.day_number(term_start)) + 1
    if total_days < 1:
        raise err("ERR_INVALID_TERM_WINDOW", "term_end precedes term_start")
    # enroll_open <= enroll_close <= term_end (PRD §3.1).
    if not (enroll_open <= enroll_close <= term_end):
        raise err("ERR_INVALID_TERM_WINDOW", "Malformed enrollment window")

    # code unique among OPEN/LOCKED terms for the institution (PRD §3.1).
    for t in db.terms.values():
        if (t["institution_id"] == institution_id and t["code"] == code
                and t["status"] in ("OPEN", "LOCKED")):
            raise err("ERR_INVALID_REQUEST", "Term code already in use")

    record = db.stamp_new({
        "institution_id": institution_id,
        "code": code,
        "term_start": dates.to_iso(term_start),
        "term_end": dates.to_iso(term_end),
        "enroll_open": dates.to_iso(enroll_open),
        "enroll_close": dates.to_iso(enroll_close),
        "status": "OPEN",
    })
    db.terms[record["id"]] = record
    return success(term_view(record), status=201)


@bp.route("/institutions/terms/<term_id>", methods=["GET"])
def get_term(term_id):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    record = db.terms.get(term_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Term not found")
    return success(term_view(record), status=200)


@bp.route("/institutions/terms", methods=["GET"])
def list_terms():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    institution_id = request.args.get("institution_id")
    status = request.args.get("status")
    records = list(db.terms.values())
    if institution_id is not None:
        records = [r for r in records if r["institution_id"] == institution_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginate_and_render(records, term_view)


@bp.route("/institutions/terms/<term_id>/lock", methods=["POST"])
def lock_term(term_id):
    _, role = get_user_context()
    require_role(role, ("Registrar",))
    record = db.terms.get(term_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Term not found")
    if record["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Term must be OPEN to lock")
    record["status"] = "LOCKED"
    db.touch(record)
    return success(term_view(record), status=200)


@bp.route("/institutions/terms/<term_id>/close", methods=["POST"])
def close_term(term_id):
    _, role = get_user_context()
    require_role(role, ("Registrar",))
    record = db.terms.get(term_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Term not found")
    if record["status"] != "LOCKED":
        raise err("ERR_INVALID_STATE", "Term must be LOCKED to close")
    # No PENDING/ACTIVE enrollment on this term with scheduled_balance_cents > 0.
    for e in db.enrollments.values():
        if e["term_id"] == term_id and e["status"] in ("PENDING", "ACTIVE") \
                and e["scheduled_balance_cents"] > 0:
            raise err("ERR_TERM_HAS_OPEN_BALANCES",
                      "An enrollment retains an open scheduled balance")
    record["status"] = "CLOSED"
    db.touch(record)
    return success(term_view(record), status=200)
