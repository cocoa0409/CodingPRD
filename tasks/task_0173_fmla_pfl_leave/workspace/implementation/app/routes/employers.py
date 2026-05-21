"""Employer and employer-scoped sub-route handlers."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import require_roles
from ..clock import format_datetime_ms, get_clock
from ..common import (
    parse_json_body,
    require_enum,
    require_int,
    require_str,
    strip_internal,
)
from ..errors import err_not_found
from ..response import make_object_envelope
from ..store import get_store, new_id


bp_employers = Blueprint("employers", __name__)


LEAVE_YEAR_BASES = {"CALENDAR", "ROLLING_BACKWARD"}
STATE_PFL_PROGRAMS = {"NONE", "STATE_PFL_8WEEK"}


@bp_employers.route("/employers", methods=["POST"])
@require_roles("ComplianceOfficer")
def create_employer(user_id: str, role: str):
    body = parse_json_body()
    legal_name = require_str(body, "legal_name")
    leave_year_basis = require_enum(body, "leave_year_basis", LEAVE_YEAR_BASES)
    state_pfl_program = require_enum(body, "state_pfl_program", STATE_PFL_PROGRAMS)
    benefit_premium_share_cents = require_int(body, "benefit_premium_share_cents", minimum=0)

    store = get_store()
    now_iso = format_datetime_ms(get_clock().get())
    eid = new_id()
    row = {
        "id": eid,
        "legal_name": legal_name,
        "leave_year_basis": leave_year_basis,
        "state_pfl_program": state_pfl_program,
        "benefit_premium_share_cents": benefit_premium_share_cents,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.employers[eid] = row
    return jsonify(make_object_envelope(strip_internal(row))), 201


@bp_employers.route("/employers/<employer_id>", methods=["GET"])
@require_roles("ComplianceOfficer", "HRSpecialist")
def get_employer(user_id: str, role: str, employer_id: str):
    store = get_store()
    row = store.employers.get(employer_id)
    if row is None:
        raise err_not_found("Employer not found.")
    return jsonify(make_object_envelope(strip_internal(row))), 200
