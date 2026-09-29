"""Contract evaluators (PRD §3.1, last paragraph)."""
from flask import Blueprint

import db
import response
import serializers
import validators as v
from constants import ALL_ROLES, EVALUATOR_STATUSES, ROLE_ADMIN
from middleware import authenticate
from services import lookups

bp = Blueprint("evaluators", __name__)


@bp.post("/licensure/evaluators")
def create_evaluator():
    authenticate([ROLE_ADMIN])
    body = v.body()
    full_name = v.f_string(body, "full_name")
    profession_code = v.f_string(body, "profession_code")
    status = v.f_enum(body, "status", EVALUATOR_STATUSES, required=False,
                      default="ACTIVE")
    max_concurrent_reviews = v.f_int(body, "max_concurrent_reviews",
                                    required=False, default=2, minimum=1)

    row = db.make_row({
        "full_name": full_name,
        "profession_code": profession_code,
        "status": status,
        "max_concurrent_reviews": max_concurrent_reviews,
        "open_assignment_count": 0,
    })
    db.evaluators[row["id"]] = row
    return response.object_response(serializers.evaluator(row), 201)


@bp.get("/licensure/evaluators/<evaluator_id>")
def read_evaluator(evaluator_id):
    authenticate(ALL_ROLES)
    row = lookups.evaluator(evaluator_id)
    return response.object_response(serializers.evaluator(row))
