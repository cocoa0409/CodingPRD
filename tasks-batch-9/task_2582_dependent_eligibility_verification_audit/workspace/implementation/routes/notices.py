"""Termination notices and continuation coverage elections (section 3.7)."""

from flask import Blueprint

import auth
import calc
import clock
import constants as K
import db
import derive
import response
import serialize
import validate
from auth import endpoint
from errors import ApiError

bp = Blueprint("notices", __name__)

LIST_ROLES = ("ProgramAdmin", "VerificationAnalyst", "AppealReviewer", "RecoveryAgent")
READ_ROLES = LIST_ROLES + ("Employee",)


def _notice_or_404(notice_id):
    notice = db.get("notices", notice_id)
    if notice is None:
        raise ApiError("ERR_NOTICE_NOT_FOUND")
    return notice


@bp.route("/termination-notices/<notice_id>", methods=["GET"])
@endpoint(*READ_ROLES)
def read_notice(notice_id):
    notice = _notice_or_404(notice_id)
    auth.require_owns_dependent(db.get("dependents", notice["dependent_id"]))
    return response.obj_out(serialize.notice, notice)


@bp.route("/termination-notices", methods=["GET"])
@endpoint(*LIST_ROLES)
def list_notices():
    dependent_id = validate.query_filter("dependent_id")
    case_id = validate.query_filter("case_id")
    status = validate.query_filter("status")
    origin = validate.query_filter("origin")
    rows = db.ordered(
        "notices",
        lambda n: (dependent_id is None or n["dependent_id"] == dependent_id)
        and (case_id is None or n.get("case_id") == case_id)
        and (status is None or n["status"] == status)
        and (origin is None or n["origin"] == origin),
    )
    return response.arr_out(serialize.notice, rows, validate.paginate(rows))


@bp.route("/termination-notices/<notice_id>/continuation-election", methods=["POST"])
@endpoint("Employee", "ProgramAdmin")
def record_continuation_election(notice_id):
    notice = _notice_or_404(notice_id)
    dependent = db.get("dependents", notice["dependent_id"])
    auth.require_owns_dependent(dependent)

    payload = validate.body()
    election = validate.req_enum(payload, "election", K.CONTINUATION_ELECTIONS)

    if notice["status"] not in ("ISSUED", "FINAL") or notice[
        "continuation_election_status"
    ] != "NOT_ELECTED":
        raise ApiError("ERR_NOTICE_STATE_INVALID")

    now = clock.now()
    deadline = notice.get("continuation_election_deadline")
    if deadline is not None and now > deadline:
        raise ApiError("ERR_CONTINUATION_ELECTION_WINDOW_CLOSED")

    if election == "WAIVE":
        # The premium stays at zero and both continuation dates stay null.
        db.set_fields(
            notice,
            continuation_election_status="WAIVED",
            continuation_elected_at=now,
        )
    else:
        start, end = calc.continuation_dates(notice["effective_date"])
        premium = calc.continuation_premium(
            dependent["relationship_type"] if dependent is not None else None
        )
        db.set_fields(
            notice,
            continuation_election_status="ELECTED",
            continuation_elected_at=now,
            continuation_start_date=start,
            continuation_end_date=end,
            continuation_monthly_premium_cents=premium,
        )

    derive.refresh_all()
    return response.obj_out(serialize.notice, notice)
