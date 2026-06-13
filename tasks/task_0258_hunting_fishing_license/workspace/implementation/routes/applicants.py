"""Applicant endpoints (PRD §3.1)."""
from flask import Blueprint, request

import serialize
from db import store
from middleware import require_roles
from response import success, success_list
from validation import (
    get_json_body, as_nonempty_str, as_int, parse_pagination, paginate,
)
from services.core import get_applicant_or_404

bp = Blueprint("applicants", __name__)


@bp.route("/applicants", methods=["POST"])
@require_roles("Applicant", "DrawOfficer")
def create_applicant():
    body = get_json_body()
    full_name = as_nonempty_str(body, "full_name", required=True)
    birth_date = as_nonempty_str(body, "birth_date", required=True)
    declared_state_code = as_nonempty_str(body, "declared_state_code", required=True)
    bonus_points = as_int(body, "bonus_points", required=False, default=0, minimum=0)

    record = {
        "full_name": full_name,
        "birth_date": birth_date,
        "declared_state_code": declared_state_code,
        "bonus_points": bonus_points,
        # System-computed initial values (PRD §3.1).
        "residency_status": "UNVERIFIED",
        "education_certified": False,
        "preference_points": 0,
    }
    store.stamp_new(record)
    store.applicants[record["id"]] = record
    return success(serialize.applicant(record), status=201, response_type="object")


@bp.route("/applicants/<id>", methods=["GET"])
@require_roles("Applicant", "DrawOfficer", "LicenseAgent", "GameWarden")
def get_applicant(id):
    record = get_applicant_or_404(id)
    return success(serialize.applicant(record), status=200, response_type="object")


@bp.route("/applicants", methods=["GET"])
@require_roles("DrawOfficer", "LicenseAgent")
def list_applicants():
    limit, offset = parse_pagination()
    items = list(store.applicants.values())
    state = request.args.get("declared_state_code")
    if state is not None:
        items = [r for r in items if r["declared_state_code"] == state]
    page, total = paginate(items, limit, offset)
    return success_list(
        [serialize.applicant(r) for r in page], limit, offset, total
    )
