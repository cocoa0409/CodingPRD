"""I9Document routes."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import require_roles
from ..pagination import paginate, parse_pagination
from ..response import make_array_envelope, make_object_envelope
from ..serializers import view_i9_document
from ..services.i9_documents import create_document, list_documents
from ._helpers import enforce_employee_ownership, parse_json_body


bp_i9_documents = Blueprint("i9_documents", __name__)


@bp_i9_documents.route("/employees/<employee_id>/i9-documents", methods=["POST"])
@require_roles("HRStaff", "EmployerRep")
def create_document_route(user_id, role, employee_id):
    body = parse_json_body()
    row = create_document(employee_id, body, actor_user_id=user_id, actor_role=role)
    return jsonify(make_object_envelope(view_i9_document(row))), 201


@bp_i9_documents.route("/employees/<employee_id>/i9-documents", methods=["GET"])
@require_roles("HRStaff", "EmployerRep", "Employee")
def list_documents_route(user_id, role, employee_id):
    limit, offset = parse_pagination()
    enforce_employee_ownership(role, user_id, employee_id)
    filters = {"category": request.args.get("category")}
    items = list_documents(employee_id, filters)
    total = len(items)
    page = paginate(items, limit, offset)
    views = [view_i9_document(d) for d in page]
    return jsonify(make_array_envelope(views, limit=limit, offset=offset, total_count=total)), 200
