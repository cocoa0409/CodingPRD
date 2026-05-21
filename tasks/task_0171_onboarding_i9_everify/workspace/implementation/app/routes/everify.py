"""E-Verify case routes."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import require_roles
from ..errors import err_not_found
from ..response import make_object_envelope
from ..serializers import view_everify_case
from ..services.everify import (
    close_case,
    deliver_result,
    submit_case,
    tnc_decision,
)
from ..store import get_store
from ._helpers import enforce_employee_ownership, parse_json_body


bp_everify = Blueprint("everify", __name__)


@bp_everify.route("/employees/<employee_id>/everify-cases", methods=["POST"])
@require_roles("EmployerRep")
def submit_case_route(user_id, role, employee_id):
    body = parse_json_body()
    row, is_replay = submit_case(employee_id, body, actor_user_id=user_id, actor_role=role)
    code = 200 if is_replay else 201
    return jsonify(make_object_envelope(view_everify_case(row))), code


@bp_everify.route("/everify-cases/<case_id>", methods=["GET"])
@require_roles("EmployerRep", "HRStaff", "Employee")
def read_case_route(user_id, role, case_id):
    store = get_store()
    case = store.everify_cases.get(case_id)
    if case is None:
        raise err_not_found("EVerifyCase not found.")
    if role == "Employee":
        enforce_employee_ownership(role, user_id, case["employee_id"])
    return jsonify(make_object_envelope(view_everify_case(case))), 200


@bp_everify.route("/everify-cases/<case_id>/result", methods=["POST"])
@require_roles("System")
def deliver_result_route(user_id, role, case_id):
    body = parse_json_body()
    row = deliver_result(case_id, body, actor_user_id=user_id, actor_role=role)
    return jsonify(make_object_envelope(view_everify_case(row))), 200


@bp_everify.route("/everify-cases/<case_id>/tnc-decision", methods=["POST"])
@require_roles("Employee")
def tnc_decision_route(user_id, role, case_id):
    body = parse_json_body()
    row = tnc_decision(case_id, body, actor_user_id=user_id, actor_role=role)
    return jsonify(make_object_envelope(view_everify_case(row))), 200


@bp_everify.route("/everify-cases/<case_id>/close", methods=["POST"])
@require_roles("EmployerRep")
def close_case_route(user_id, role, case_id):
    row = close_case(case_id, actor_user_id=user_id, actor_role=role)
    return jsonify(make_object_envelope(view_everify_case(row))), 200
