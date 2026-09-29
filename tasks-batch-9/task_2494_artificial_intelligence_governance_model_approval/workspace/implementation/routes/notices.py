"""Disclosure notice withdrawal."""
from flask import Blueprint

import clock
import constants
import db
import errors
import response
from errors import ApiError
from middleware import authorize, current_role, current_user_id
from services import guards

bp = Blueprint("notices", __name__)


# --- 32. POST /disclosure-notices/{id}/withdraw ------------------------
@bp.post("/disclosure-notices/<notice_id>/withdraw")
@authorize(constants.REQUESTER, constants.GOVERNANCE_OFFICER)
def withdraw_notice(notice_id):
    notice = guards.get_record(                                     # step 6
        db.disclosure_notices, notice_id, "disclosure notice"
    )
    use_case = db.use_cases.get(notice["use_case_id"])
    if current_role() == constants.REQUESTER:
        if use_case is None or current_user_id() != use_case["requester_user_id"]:
            raise ApiError(
                errors.ERR_UNAUTHORIZED,
                "only the use case's own Requester may withdraw this notice",
            )
    guards.check_not_terminal(use_case)                             # step 10
    if notice["status"] != "PUBLISHED":                              # step 19
        raise ApiError(
            errors.ERR_NOTICE_ALREADY_WITHDRAWN,
            "notice %s is already WITHDRAWN" % notice_id,
        )
    notice["status"] = "WITHDRAWN"
    notice["withdrawn_at"] = clock.now()
    db.touch(notice)
    return response.object_response(notice)
