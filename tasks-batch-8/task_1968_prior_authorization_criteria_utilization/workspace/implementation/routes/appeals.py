"""Appeal lifecycle: begin-review, decide, withdraw — plus the overturn cascade."""

from flask import request as flask_request

import clock
from db import db, touch
from errors import (
    ApiError,
    ERR_INVALID_APPEAL_STATE,
    ERR_NOT_ASSIGNED_REVIEWER,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import (
    ALL_ROLES,
    ROLE_APPEALS_CLERK,
    ROLE_APPEALS_REVIEWER,
    authorize,
    get_or_404,
    json_body,
    opt_str,
    req_enum,
)
from response import ok, serialize
from services import EV_APPEAL_OVERTURNED, add_event, recompute_provider_stats
from . import make_blueprint

bp = make_blueprint("appeals")


@bp.route("/appeals/<aid>", methods=["GET"])
def get_appeal(aid):
    authorize(*ALL_ROLES)
    rec = get_or_404(db.appeals, aid, "appeal")
    return ok(serialize(rec))


@bp.route("/appeals/<aid>/begin-review", methods=["POST"])
def begin_review(aid):
    authorize(ROLE_APPEALS_REVIEWER)
    rec = get_or_404(db.appeals, aid, "appeal")
    if rec["status"] != "RECEIVED":
        raise ApiError(
            ERR_INVALID_APPEAL_STATE,
            409,
            "begin-review requires appeal status RECEIVED",
        )
    uid = flask_request.headers.get("X-User-ID")
    det = db.determinations[rec["determination_id"]]
    # segregation of duties: the issuer of the appealed determination may not
    # review it; a system-issued (null decider) determination imposes no bar
    if det["decided_by_user_id"] is not None and uid == det["decided_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            403,
            "Appeal reviewer issued the appealed determination",
        )
    rec["status"] = "IN_REVIEW"
    rec["reviewer_id"] = uid
    touch(rec)
    return ok(serialize(rec))


@bp.route("/appeals/<aid>/decide", methods=["POST"])
def decide_appeal(aid):
    authorize(ROLE_APPEALS_REVIEWER)
    rec = get_or_404(db.appeals, aid, "appeal")
    body = json_body()
    outcome = req_enum(body, "outcome", ("UPHELD", "OVERTURNED"))
    opt_str(body, "rationale")  # accepted, not persisted (no such field)

    if rec["status"] != "IN_REVIEW":
        raise ApiError(
            ERR_INVALID_APPEAL_STATE,
            409,
            "decide requires appeal status IN_REVIEW",
        )
    uid = flask_request.headers.get("X-User-ID")
    if uid != rec["reviewer_id"]:
        raise ApiError(
            ERR_NOT_ASSIGNED_REVIEWER,
            403,
            "Appeal decide caller is not the assigned reviewer_id",
        )

    now = clock.now()
    rec["status"] = outcome
    rec["decided_at"] = now
    touch(rec)

    if outcome == "OVERTURNED":
        det = db.determinations[rec["determination_id"]]
        det["status"] = "OVERTURNED"  # recorded outcome is kept (DENIED)
        touch(det)
        req = db.requests[det["request_id"]]
        if req["status"] == "DENIED":
            req["status"] = "APPROVED"
            touch(req)
        recompute_provider_stats(req["provider_id"], run_suspend_check=False)
        add_event(
            EV_APPEAL_OVERTURNED,
            req["id"],
            req["provider_id"],
            f"Appeal {rec['id']} overturned determination {det['id']}",
        )
    return ok(serialize(rec))


@bp.route("/appeals/<aid>/withdraw", methods=["POST"])
def withdraw_appeal(aid):
    authorize(ROLE_APPEALS_CLERK)
    rec = get_or_404(db.appeals, aid, "appeal")
    if rec["status"] not in ("RECEIVED", "IN_REVIEW"):
        raise ApiError(
            ERR_INVALID_APPEAL_STATE,
            409,
            "withdraw requires appeal status RECEIVED or IN_REVIEW",
        )
    rec["status"] = "WITHDRAWN"
    touch(rec)
    return ok(serialize(rec))
