"""Document template endpoints."""

from flask import Blueprint, request

import db
import errors
import helpers
import response
import serializers
from middleware import auth_required


bp = Blueprint("document_templates", __name__)


VALID_CASE_TYPES = {"CIVIL", "CRIMINAL", "ADMINISTRATIVE", "ARBITRATION"}


@bp.route("/document-templates", methods=["POST"])
@auth_required("PartnerLawyer")
def create_template():
    body = helpers.get_json_body()
    template_code = helpers.require_str(body, "template_code", min_len=1)
    case_type = helpers.require_enum(body, "case_type", VALID_CASE_TYPES)
    name = helpers.require_str(body, "name", min_len=1)
    variables = body.get("variables", []) or []
    if not isinstance(variables, list):
        errors.raise_error(errors.ERR_VALIDATION_FAILED, "variables must be an array.")
    body_template = helpers.require_str(body, "body_template")

    # Uniqueness on template_code
    for t in db.document_templates.values():
        if t["template_code"] == template_code:
            errors.raise_error(errors.ERR_VALIDATION_FAILED, "template_code must be unique.")

    tid = db.new_id()
    common = helpers.common_create()
    template = {
        "id": tid,
        "template_code": template_code,
        "case_type": case_type,
        "name": name,
        "variables": list(variables),
        "body_template": body_template,
        "status": "ACTIVE",
        **common,
    }
    db.document_templates[tid] = template
    return response.created(serializers.template_dict(template))


@bp.route("/document-templates", methods=["GET"])
@auth_required("PartnerLawyer", "SeniorLawyer", "JuniorLawyer")
def list_templates():
    limit, offset = helpers.parse_pagination()
    items = list(db.document_templates.values())
    if request.args.get("case_type"):
        items = [t for t in items if t["case_type"] == request.args["case_type"]]
    if request.args.get("status"):
        items = [t for t in items if t["status"] == request.args["status"]]
    items.sort(key=lambda t: t["created_at"])
    page, total = helpers.paginate(items, limit, offset)
    return response.list_ok(
        [serializers.template_dict(t) for t in page],
        limit=limit, offset=offset, total_count=total,
    )
