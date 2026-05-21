"""Worksite routes."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import require_roles
from ..clock import format_datetime_ms, get_clock
from ..common import (
    optional_int,
    parse_json_body,
    require_int,
    require_str,
    strip_internal,
)
from ..errors import err_not_found, err_version_conflict
from ..response import make_object_envelope
from ..store import get_store, new_id


bp_worksites = Blueprint("worksites", __name__)


@bp_worksites.route("/employers/<employer_id>/worksites", methods=["POST"])
@require_roles("ComplianceOfficer")
def create_worksite(user_id: str, role: str, employer_id: str):
    store = get_store()
    if employer_id not in store.employers:
        raise err_not_found("Employer not found.")
    body = parse_json_body()
    address_line = require_str(body, "address_line")
    headcount = require_int(body, "employee_count_within_75_miles", minimum=0)
    now_iso = format_datetime_ms(get_clock().get())
    wid = new_id()
    row = {
        "id": wid,
        "employer_id": employer_id,
        "address_line": address_line,
        "employee_count_within_75_miles": headcount,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.worksites[wid] = row
    return jsonify(make_object_envelope(strip_internal(row))), 201


@bp_worksites.route("/worksites/<worksite_id>", methods=["PATCH"])
@require_roles("ComplianceOfficer")
def patch_worksite(user_id: str, role: str, worksite_id: str):
    store = get_store()
    row = store.worksites.get(worksite_id)
    if row is None:
        raise err_not_found("Worksite not found.")
    body = parse_json_body()
    # OCC version check
    if "version" in body and body["version"] is not None:
        if not isinstance(body["version"], int) or body["version"] != int(row["version"]):
            raise err_version_conflict()
    if "employee_count_within_75_miles" in body:
        headcount = require_int(body, "employee_count_within_75_miles", minimum=0)
        row["employee_count_within_75_miles"] = headcount
    row["version"] = int(row["version"]) + 1
    row["updated_at"] = format_datetime_ms(get_clock().get())
    return jsonify(make_object_envelope(strip_internal(row))), 200
