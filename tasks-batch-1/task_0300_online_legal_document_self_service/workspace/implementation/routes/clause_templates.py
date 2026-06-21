"""ClauseTemplate (clause library) routes."""

from flask import Blueprint, request

import constants
import validators
from common import base_entity, get_or_404, list_collection, serialize
from db import store
from middleware import get_json_body, parse_pagination, roles
from response import array_response, object_response

bp = Blueprint("clause_templates", __name__)


@bp.route("/legal/clause-templates", methods=["POST"])
@roles("PlatformAdmin")
def create_clause_template():
    body = get_json_body()
    clause_key = validators.require_string(body, "clause_key")
    doc_type = validators.require_enum(body, "document_type", constants.DOCUMENT_TYPES)
    state = validators.require_enum(body, "state_code", constants.STATE_CODES)
    is_mandatory = validators.require_bool(body, "is_mandatory")
    body_text = validators.require_string(body, "body_text", allow_empty=True)

    ent = base_entity()
    ent.update({
        "clause_key": clause_key,
        "document_type": doc_type,
        "state_code": state,
        "is_mandatory": is_mandatory,
        "body_text": body_text,
    })
    store.clause_templates[ent["id"]] = ent
    return object_response(serialize(ent), 201)


@bp.route("/legal/clause-templates/<tid>", methods=["GET"])
@roles("Customer", "Attorney", "PlatformAdmin")
def get_clause_template(tid):
    ent = get_or_404(store.clause_templates, tid)
    return object_response(serialize(ent), 200)


@bp.route("/legal/clause-templates", methods=["GET"])
@roles("Customer", "Attorney", "PlatformAdmin")
def list_clause_templates():
    limit, offset = parse_pagination()
    doc_type = request.args.get("document_type")
    state = request.args.get("state_code")

    def predicate(e):
        if doc_type is not None and e["document_type"] != doc_type:
            return False
        if state is not None and e["state_code"] != state:
            return False
        return True

    page, total = list_collection(store.clause_templates, predicate, limit, offset)
    return array_response(page, limit, offset, total, 200)
