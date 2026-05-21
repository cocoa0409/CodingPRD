"""PfLClaim routes."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import ensure_employee_owns, require_roles
from ..clock import format_datetime_ms, get_clock
from ..common import (
    parse_json_body,
    require_enum,
    require_int,
    require_str,
    strip_internal,
)
from ..errors import (
    err_employee_terminated,
    err_not_found,
    err_pfl_not_available,
)
from ..response import make_object_envelope
from ..services.calculations import pfl_weekly_benefit
from ..store import get_store, new_id


bp_pfl_claims = Blueprint("pfl_claims", __name__)


PFL_CLAIM_TYPES = {"FAMILY_CARE", "BABY_BONDING"}


@bp_pfl_claims.route("/pfl-claims", methods=["POST"])
@require_roles("Employee", "HRSpecialist")
def create_pfl_claim(user_id: str, role: str):
    store = get_store()
    body = parse_json_body()
    employee_id = require_str(body, "employee_id")
    emp = store.employees.get(employee_id)
    if emp is None:
        raise err_not_found("Employee not found.")
    ensure_employee_owns(user_id, role, employee_id)
    if emp["employment_status"] == "TERMINATED":
        raise err_employee_terminated()
    employer = store.employers.get(emp["employer_id"])
    if employer is None:
        raise err_not_found("Employer not found.")
    if employer.get("state_pfl_program") != "STATE_PFL_8WEEK":
        raise err_pfl_not_available()

    claim_type = require_enum(body, "claim_type", PFL_CLAIM_TYPES)
    weeks_authorized_raw = require_int(body, "weeks_authorized")
    if weeks_authorized_raw < 1 or weeks_authorized_raw > 8:
        raise err_pfl_not_available()

    weekly_benefit = pfl_weekly_benefit(int(emp.get("monthly_wage_cents", 0)))
    now_iso = format_datetime_ms(get_clock().get())
    cid = new_id()
    claim = {
        "id": cid,
        "employee_id": employee_id,
        "claim_type": claim_type,
        "claim_status": "SUBMITTED",
        "weeks_authorized": weeks_authorized_raw,
        "weeks_paid": 0,
        "weekly_benefit_cents": weekly_benefit,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.pfl_claims[cid] = claim
    return jsonify(make_object_envelope(strip_internal(claim))), 201


@bp_pfl_claims.route("/pfl-claims/<pfl_claim_id>", methods=["GET"])
@require_roles("Employee", "HRSpecialist", "ComplianceOfficer")
def get_pfl_claim(user_id: str, role: str, pfl_claim_id: str):
    store = get_store()
    claim = store.pfl_claims.get(pfl_claim_id)
    if claim is None:
        raise err_not_found("PfLClaim not found.")
    ensure_employee_owns(user_id, role, claim["employee_id"])
    return jsonify(make_object_envelope(strip_internal(claim))), 200
