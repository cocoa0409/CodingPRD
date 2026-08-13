"""SapEvaluation read endpoints (evaluations are created only by the pipeline)."""

from flask import Blueprint, g, request

import errors
from db import store
from middleware import (
    authenticate,
    check_student_ownership,
    paginate,
    pagination_params,
    require_roles,
)
from response import success
from serializers import pub_evaluation

bp = Blueprint("evaluations", __name__)

ANY_ROLE = ("Student", "Registrar", "AidOfficer", "CommitteeMember", "Auditor", "AidAdministrator")


@bp.get("/sap/evaluations/<eid>")
def get_evaluation(eid):
    authenticate()
    require_roles(*ANY_ROLE)
    row = store.evaluations.get(eid)
    if row is None:
        errors.fail(errors.ERR_NOT_FOUND, "SapEvaluation %s does not exist" % eid)
    check_student_ownership(row["student_id"])
    return success(pub_evaluation(row))


@bp.get("/sap/evaluations")
def list_evaluations():
    authenticate()
    require_roles(*ANY_ROLE)
    limit, offset = pagination_params()
    rows = list(store.evaluations.values())
    if g.user_role == "Student":
        rows = [e for e in rows if e["student_id"] == g.user_id]
    student_id = request.args.get("student_id")
    if student_id is not None:
        rows = [e for e in rows if e["student_id"] == student_id]
    term_id = request.args.get("term_id")
    if term_id is not None:
        rows = [e for e in rows if e["term_id"] == term_id]
    status = request.args.get("status")
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    result_standing = request.args.get("result_standing")
    if result_standing is not None:
        rows = [e for e in rows if e["result_standing"] == result_standing]
    page, meta = paginate(rows, limit, offset)
    return success([pub_evaluation(e) for e in page], response_type="array", pagination=meta)
