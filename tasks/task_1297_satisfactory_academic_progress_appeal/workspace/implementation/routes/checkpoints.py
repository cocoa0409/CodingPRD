"""PlanCheckpoint read endpoints (checkpoints are created with their plan and
evaluated only by the term pipeline)."""

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
from serializers import pub_checkpoint

bp = Blueprint("checkpoints", __name__)

ANY_ROLE = ("Student", "Registrar", "AidOfficer", "CommitteeMember", "Auditor", "AidAdministrator")


def _checkpoint_student_id(cp):
    plan = store.plans.get(cp["plan_id"])
    return plan["student_id"] if plan is not None else None


@bp.get("/sap/checkpoints/<cid>")
def get_checkpoint(cid):
    authenticate()
    require_roles(*ANY_ROLE)
    row = store.checkpoints.get(cid)
    if row is None:
        errors.fail(errors.ERR_NOT_FOUND, "PlanCheckpoint %s does not exist" % cid)
    check_student_ownership(_checkpoint_student_id(row))
    return success(pub_checkpoint(row))


@bp.get("/sap/checkpoints")
def list_checkpoints():
    authenticate()
    require_roles(*ANY_ROLE)
    limit, offset = pagination_params()
    rows = list(store.checkpoints.values())
    if g.user_role == "Student":
        rows = [c for c in rows if _checkpoint_student_id(c) == g.user_id]
    plan_id = request.args.get("plan_id")
    if plan_id is not None:
        rows = [c for c in rows if c["plan_id"] == plan_id]
    term_id = request.args.get("term_id")
    if term_id is not None:
        rows = [c for c in rows if c["term_id"] == term_id]
    outcome = request.args.get("outcome")
    if outcome is not None:
        rows = [c for c in rows if c["outcome"] == outcome]
    page, meta = paginate(rows, limit, offset)
    return success([pub_checkpoint(c) for c in page], response_type="array", pagination=meta)
