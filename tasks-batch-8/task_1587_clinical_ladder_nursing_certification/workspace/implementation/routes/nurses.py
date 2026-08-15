"""Nurse directory endpoints."""

from flask import Blueprint, request

from clock import clock
from db import db
from errors import err_invalid_request, err_not_found
from middleware import require_roles
from response import success_list, success_object, parse_pagination
from serializers import (nurse_view, participation_event_view, certification_view,
                         application_view, review_view)
from util import parse_datetime, require_fields, require_string

bp = Blueprint("nurses", __name__)


@bp.route("/clinical-ladder/nurses", methods=["POST"])
def create_nurse():
    require_roles("ProgramAdmin")
    payload = request.get_json(silent=True)
    require_fields(payload, ["employee_code", "full_name", "hire_date", "home_unit"])
    employee_code = require_string(payload, "employee_code")
    full_name = require_string(payload, "full_name")
    home_unit = require_string(payload, "home_unit")
    hire_date = parse_datetime(payload.get("hire_date"), "hire_date")

    for n in db.nurses.values():
        if n["employee_code"] == employee_code:
            raise err_invalid_request("employee_code must be unique across all nurses")

    now = clock.now()
    nurse = {
        "id": db.new_id(),
        "employee_code": employee_code,
        "full_name": full_name,
        "hire_date": hire_date,
        "home_unit": home_unit,
        "current_level": "CN_I",
        "differential_status": "INACTIVE",
        "differential_activated_at": None,
        "retention_risk_score": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.nurses[nurse["id"]] = nurse
    return success_object(nurse_view(nurse), status=201)


def _get_nurse_or_404(nurse_id):
    nurse = db.nurses.get(nurse_id)
    if nurse is None:
        raise err_not_found("Nurse not found")
    return nurse


@bp.route("/clinical-ladder/nurses", methods=["GET"])
def list_nurses():
    require_roles("ProgramAdmin", "PayrollOfficer", "RetentionAnalyst")
    limit, offset = parse_pagination(request.args)
    home_unit = request.args.get("home_unit")
    current_level = request.args.get("current_level")
    differential_status = request.args.get("differential_status")
    rows = sorted(db.nurses.values(), key=lambda n: n["created_at"])
    if home_unit is not None:
        rows = [n for n in rows if n["home_unit"] == home_unit]
    if current_level is not None:
        rows = [n for n in rows if n["current_level"] == current_level]
    if differential_status is not None:
        rows = [n for n in rows if n["differential_status"] == differential_status]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([nurse_view(n) for n in page], limit, offset, total)


@bp.route("/clinical-ladder/nurses/<nid>", methods=["GET"])
def get_nurse(nid):
    require_roles("ProgramAdmin", "PayrollOfficer", "RetentionAnalyst", "Nurse")
    nurse = _get_nurse_or_404(nid)
    return success_object(nurse_view(nurse))


@bp.route("/clinical-ladder/nurses/<nid>/participation-events", methods=["GET"])
def nurse_participation_events(nid):
    require_roles("ProgramAdmin", "Nurse", "RetentionAnalyst")
    nurse = _get_nurse_or_404(nid)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    rows = sorted([e for e in db.participation_events.values() if e["nurse_id"] == nurse["id"]],
                  key=lambda e: e["created_at"])
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([participation_event_view(e) for e in page], limit, offset, total)


@bp.route("/clinical-ladder/nurses/<nid>/certifications", methods=["GET"])
def nurse_certifications(nid):
    require_roles("ProgramAdmin", "Nurse")
    nurse = _get_nurse_or_404(nid)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    rows = sorted([c for c in db.certifications.values() if c["nurse_id"] == nurse["id"]],
                  key=lambda c: c["created_at"])
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([certification_view(c) for c in page], limit, offset, total)


@bp.route("/clinical-ladder/nurses/<nid>/applications", methods=["GET"])
def nurse_applications(nid):
    require_roles("ProgramAdmin", "Nurse")
    nurse = _get_nurse_or_404(nid)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    rows = sorted([a for a in db.applications.values() if a["nurse_id"] == nurse["id"]],
                  key=lambda a: a["created_at"])
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([application_view(a) for a in page], limit, offset, total)


@bp.route("/clinical-ladder/nurses/<nid>/anniversary-reviews", methods=["GET"])
def nurse_anniversary_reviews(nid):
    require_roles("ProgramAdmin", "Nurse")
    nurse = _get_nurse_or_404(nid)
    limit, offset = parse_pagination(request.args)
    outcome = request.args.get("outcome")
    rows = sorted([r for r in db.anniversary_reviews.values() if r["nurse_id"] == nurse["id"]],
                  key=lambda r: r["created_at"])
    if outcome is not None:
        rows = [r for r in rows if r["outcome"] == outcome]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([review_view(r) for r in page], limit, offset, total)
