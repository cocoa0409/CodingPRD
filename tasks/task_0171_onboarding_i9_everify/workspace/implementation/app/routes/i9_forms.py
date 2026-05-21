"""I9Form routes."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import require_roles
from ..pagination import paginate, parse_pagination
from ..response import make_array_envelope, make_object_envelope
from ..serializers import view_i9_form
from ..services.i9_forms import (
    create_form,
    list_forms,
    section1_attest,
    section2_sign,
    void_form,
)
from ._helpers import enforce_employee_ownership, parse_json_body


bp_i9_forms = Blueprint("i9_forms", __name__)


@bp_i9_forms.route("/employees/<employee_id>/i9-forms", methods=["POST"])
@require_roles("HRStaff")
def create_form_route(user_id, role, employee_id):
    body = parse_json_body()
    row = create_form(employee_id, body, actor_user_id=user_id, actor_role=role)
    return jsonify(make_object_envelope(view_i9_form(row))), 201


@bp_i9_forms.route("/employees/<employee_id>/i9-forms", methods=["GET"])
@require_roles("HRStaff", "EmployerRep", "Employee")
def list_forms_route(user_id, role, employee_id):
    limit, offset = parse_pagination()
    enforce_employee_ownership(role, user_id, employee_id)
    filters = {
        "form_status": request.args.get("form_status"),
        "form_kind": request.args.get("form_kind"),
    }
    items = list_forms(employee_id, filters)
    total = len(items)
    page = paginate(items, limit, offset)
    return jsonify(make_array_envelope([view_i9_form(f) for f in page], limit=limit, offset=offset, total_count=total)), 200


@bp_i9_forms.route("/employees/<employee_id>/i9-forms/<form_id>/section1", methods=["POST"])
@require_roles("Employee")
def section1_route(user_id, role, employee_id, form_id):
    body = parse_json_body()
    row = section1_attest(employee_id, form_id, body, actor_user_id=user_id, actor_role=role)
    return jsonify(make_object_envelope(view_i9_form(row))), 200


@bp_i9_forms.route("/employees/<employee_id>/i9-forms/<form_id>/section2", methods=["POST"])
@require_roles("EmployerRep")
def section2_route(user_id, role, employee_id, form_id):
    body = parse_json_body()
    row = section2_sign(employee_id, form_id, body, actor_user_id=user_id, actor_role=role)
    return jsonify(make_object_envelope(view_i9_form(row))), 200


@bp_i9_forms.route("/i9-forms/<form_id>/void", methods=["POST"])
@require_roles("HRStaff")
def void_route(user_id, role, form_id):
    body = parse_json_body()
    row = void_form(form_id, body, actor_user_id=user_id, actor_role=role)
    return jsonify(make_object_envelope(view_i9_form(row))), 200
