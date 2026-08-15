"""OwnerOperator routes."""

from flask import Blueprint

import errors
import middleware
from db import db
from response import success
from services.core import base_entity, recompute_classification, evaluate_doc_expiry
from services.serialize import serialize_operator
from util import get_body, req_str

bp = Blueprint("operators", __name__)


@bp.post("/owner-operators")
def create_operator():
    middleware.require_roles({"LeaseAdmin"})
    body = get_body()
    legal_name = req_str(body, "legal_name")
    cdl_number = req_str(body, "cdl_number")

    for o in db.owner_operators.values():
        if o["cdl_number"] == cdl_number:
            raise errors.err(errors.ERR_DUPLICATE_VALUE, "cdl_number must be unique", 409)

    op = base_entity()
    op.update({
        "legal_name": legal_name,
        "cdl_number": cdl_number,
        "classification_status": "PENDING_REVIEW",
    })
    db.owner_operators[op["id"]] = op
    return success(serialize_operator(op), "object", 201)


@bp.get("/owner-operators/<op_id>")
def get_operator(op_id):
    middleware.require_roles(middleware.ALL_ROLES)
    op = db.owner_operators.get(op_id)
    if op is None:
        raise errors.err(errors.ERR_OPERATOR_NOT_FOUND, "OwnerOperator not found", 404)
    # classification is re-evaluated for doc expiry against the logical clock on read
    recompute_classification(op)
    return success(serialize_operator(op), "object", 200)
