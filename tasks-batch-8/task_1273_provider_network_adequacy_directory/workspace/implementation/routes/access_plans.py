"""AccessPlanRequest endpoints: create (OCC on deficiency), submit, decide."""

from flask import Blueprint

import db
import errors
import helpers
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list

bp = Blueprint("access_plans", __name__)

APR_STATUSES = {"DRAFT", "SUBMITTED", "APPROVED", "DENIED", "SUPERSEDED"}


@bp.route("/network/deficiencies/<did>/access-plan-requests", methods=["POST"])
@require_roles("NetworkManager")
def create_access_plan(user_id, role, did):
    deficiency = db.deficiencies.get(did)
    if deficiency is None:
        raise errors.err_deficiency_not_found()
    body = helpers.get_body()
    # OCC check runs before any business logic
    expected = helpers.req_int(body, "expected_deficiency_version")
    if expected != deficiency["version"]:
        raise errors.err_stale_deficiency()
    if deficiency["status"] != "OPEN":
        raise errors.err_deficiency_not_open()
    remedy_summary = helpers.req_str(body, "remedy_summary")
    excuse_start_date = helpers.req_str(body, "excuse_start_date")
    excuse_through_date = helpers.req_str(body, "excuse_through_date")
    es = helpers.parse_date(excuse_start_date, "excuse_start_date")
    et = helpers.parse_date(excuse_through_date, "excuse_through_date")
    if et < es:
        raise errors.err_excuse_window_invalid()
    if es < helpers.clock_date():
        raise errors.err_excuse_window_invalid()
    # supersede any existing DRAFT on this deficiency
    max_seq = 0
    for apr in db.access_plan_requests.values():
        if apr["deficiency_id"] != did:
            continue
        max_seq = max(max_seq, apr["submission_seq"])
        if apr["status"] == "DRAFT":
            apr["status"] = "SUPERSEDED"
            helpers.touch(apr)
    rec = {
        "deficiency_id": did, "remedy_summary": remedy_summary,
        "excuse_start_date": excuse_start_date, "excuse_through_date": excuse_through_date,
        "status": "DRAFT", "submission_seq": max_seq + 1,
        "decided_at": None, "decision_notes": None,
    }
    helpers.stamp_new(rec)
    db.access_plan_requests[rec["id"]] = rec
    # creating a request bumps the deficiency version (observed by the OCC field)
    helpers.touch(deficiency)
    return success_object(helpers.ser_apr(rec), 201)


@bp.route("/network/access-plan-requests", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_access_plans(user_id, role):
    limit, offset = helpers.get_pagination()
    deficiency_id = helpers.query_str("deficiency_id")
    status = helpers.query_enum("status", APR_STATUSES)
    items = list(db.access_plan_requests.values())
    if deficiency_id is not None:
        items = [a for a in items if a["deficiency_id"] == deficiency_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, total = helpers.paginate(items, limit, offset)
    return success_list([helpers.ser_apr(a) for a in page], limit, offset, total)


@bp.route("/network/access-plan-requests/<aid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_access_plan(user_id, role, aid):
    rec = db.access_plan_requests.get(aid)
    if rec is None:
        raise errors.err_apr_not_found()
    return success_object(helpers.ser_apr(rec))


@bp.route("/network/access-plan-requests/<aid>/submit", methods=["POST"])
@require_roles("NetworkManager")
def submit_access_plan(user_id, role, aid):
    rec = db.access_plan_requests.get(aid)
    if rec is None:
        raise errors.err_apr_not_found()
    if rec["status"] not in ("DRAFT", "DENIED"):
        raise errors.err_request_not_submittable()
    rec["status"] = "SUBMITTED"
    if rec["decided_at"] is not None:
        rec["decided_at"] = None  # resubmission from DENIED resets decided_at
    helpers.touch(rec)
    return success_object(helpers.ser_apr(rec))


@bp.route("/network/access-plan-requests/<aid>/decide", methods=["POST"])
@require_roles("Regulator")
def decide_access_plan(user_id, role, aid):
    rec = db.access_plan_requests.get(aid)
    if rec is None:
        raise errors.err_apr_not_found()
    body = helpers.get_body()
    decision = helpers.req_enum(body, "decision", helpers.DECISIONS)
    notes = helpers.opt_str(body, "notes")
    if rec["status"] != "SUBMITTED":
        raise errors.err_request_not_decidable()
    deficiency = db.deficiencies.get(rec["deficiency_id"])
    if decision == "APPROVED":
        if deficiency is None or deficiency["status"] != "OPEN":
            raise errors.err_deficiency_not_open()
        # closed-interval excuse-window non-overlap vs other APPROVED requests
        es = helpers.parse_date(rec["excuse_start_date"], "excuse_start_date")
        et = helpers.parse_date(rec["excuse_through_date"], "excuse_through_date")
        for other in db.access_plan_requests.values():
            if other["id"] == rec["id"]:
                continue
            if other["deficiency_id"] != rec["deficiency_id"]:
                continue
            if other["status"] != "APPROVED":
                continue
            o_es = helpers.parse_date(other["excuse_start_date"], "excuse_start_date")
            o_et = helpers.parse_date(other["excuse_through_date"], "excuse_through_date")
            if es <= o_et and o_es <= et:
                raise errors.err_excuse_window_overlap()
        rec["status"] = "APPROVED"
        rec["decided_at"] = helpers.now_iso()
        rec["decision_notes"] = notes
        helpers.touch(rec)
        # cascade: deficiency -> EXCUSED; outstanding penalty reversed; rollup decremented
        outstanding = deficiency["accrued_penalty_cents"] - deficiency["reversed_penalty_cents"]
        deficiency["status"] = "EXCUSED"
        deficiency["reversed_penalty_cents"] += outstanding
        helpers.touch(deficiency)
        evaluation = db.evaluations.get(deficiency["evaluation_id"])
        if evaluation is not None:
            evaluation["total_penalty_cents"] -= outstanding
            evaluation["deficiency_penalties_cents"] = max(
                0, evaluation.get("deficiency_penalties_cents", 0) - outstanding)
            helpers.touch(evaluation)
    else:  # DENIED
        rec["status"] = "DENIED"
        rec["decided_at"] = helpers.now_iso()
        rec["decision_notes"] = notes
        helpers.touch(rec)
    return success_object(helpers.ser_apr(rec))
