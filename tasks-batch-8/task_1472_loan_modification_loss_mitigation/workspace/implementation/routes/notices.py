from flask import Blueprint, request

import clock
import store
from auth import ALL_ROLES, NON_BORROWER_ROLES, authenticate, authorize, check_borrower_ownership
from errors import (
    ERR_APPEAL_ALREADY_DECIDED,
    ERR_APPEAL_NOT_AVAILABLE,
    ERR_APPEAL_NOT_FOUND,
    ERR_APPEAL_WINDOW_EXPIRED,
    ERR_DENIAL_NOTICE_NOT_FOUND,
    ERR_NOTICE_ALREADY_APPEALED,
    ERR_NOTICE_NOT_APPEALABLE_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    raise_err,
)
from services import (
    APPEAL_OUTCOMES,
    appeal_out,
    latest_active_case,
    loan_of_appeal,
    loan_of_notice,
    maybe_revert_workout,
    notice_out,
)
from util import body_json, bump, get_or_404, list_response, new_record, req_enum, req_str, success_object

bp = Blueprint("notices", __name__)


@bp.route("/denial-notices/<rid>", methods=["GET"])
def get_notice(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.notices, rid, ERR_DENIAL_NOTICE_NOT_FOUND, "DenialNotice")
    return success_object(notice_out(rec))


@bp.route("/denial-notices", methods=["GET"])
def list_notices():
    _, role = authenticate()
    authorize(role, NON_BORROWER_ROLES)
    records = list(store.notices.values())
    application_id = request.args.get("application_id")
    evaluation_id = request.args.get("evaluation_id")
    if application_id is not None:
        records = [n for n in records if n["application_id"] == application_id]
    if evaluation_id is not None:
        records = [n for n in records if n.get("evaluation_id") == evaluation_id]
    return list_response(records, notice_out)


@bp.route("/denial-notices/<rid>/appeals", methods=["POST"])
def create_appeal(rid):
    uid, role = authenticate()
    authorize(role, ["Borrower"])
    body = body_json()
    grounds = req_str(body, "grounds")

    notice = get_or_404(store.notices, rid, ERR_DENIAL_NOTICE_NOT_FOUND, "DenialNotice")
    check_borrower_ownership(uid, loan_of_notice(notice))

    # state (priority 7)
    if notice["status"] == "APPEALED":
        raise_err(ERR_NOTICE_ALREADY_APPEALED, "Denial notice already appealed")
    if notice["status"] != "ISSUED":
        raise_err(ERR_NOTICE_NOT_APPEALABLE_STATE,
                  "Denial notice in %s is not appealable" % notice["status"])

    # temporal gates (priority 9): window first, then eligibility
    if clock.now() > notice["appeal_deadline"]:
        raise_err(ERR_APPEAL_WINDOW_EXPIRED, "Appeal window has expired")
    if not notice["appeal_eligible"]:
        raise_err(ERR_APPEAL_NOT_AVAILABLE,
                  "Appeal not available (complete application received fewer than "
                  "90 days before the scheduled sale)")

    appeal = new_record()
    appeal.update({
        "denial_notice_id": notice["id"],
        "grounds": grounds,
        "submitted_at": clock.now(),
        "reviewer_user_id": None,
        "decided_at": None,
        "status": "SUBMITTED",
    })
    store.appeals[appeal["id"]] = appeal

    notice["status"] = "APPEALED"
    bump(notice)
    app = store.applications[notice["application_id"]]
    if app["status"] == "EVALUATED_DENIAL":
        app["status"] = "APPEAL_REVIEW"
        bump(app)
    return success_object(appeal_out(appeal), 201)


@bp.route("/appeals/<rid>", methods=["GET"])
def get_appeal(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.appeals, rid, ERR_APPEAL_NOT_FOUND, "Appeal")
    return success_object(appeal_out(rec))


@bp.route("/appeals", methods=["GET"])
def list_appeals():
    _, role = authenticate()
    authorize(role, NON_BORROWER_ROLES)
    records = list(store.appeals.values())
    denial_notice_id = request.args.get("denial_notice_id")
    status = request.args.get("status")
    if denial_notice_id is not None:
        records = [a for a in records if a["denial_notice_id"] == denial_notice_id]
    if status is not None:
        records = [a for a in records if a["status"] == status]
    return list_response(records, appeal_out)


@bp.route("/denial-notices/<rid>/appeals", methods=["GET"])
def list_notice_appeals(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    notice = get_or_404(store.notices, rid, ERR_DENIAL_NOTICE_NOT_FOUND, "DenialNotice")
    records = [a for a in store.appeals.values() if a["denial_notice_id"] == notice["id"]]
    return list_response(records, appeal_out)


@bp.route("/appeals/<rid>/decision", methods=["POST"])
def decide_appeal(rid):
    uid, role = authenticate()
    authorize(role, ["AppealReviewer"])
    body = body_json()
    outcome = req_enum(body, "outcome", APPEAL_OUTCOMES)

    appeal = get_or_404(store.appeals, rid, ERR_APPEAL_NOT_FOUND, "Appeal")

    # state (priority 7)
    if appeal["status"] != "SUBMITTED":
        raise_err(ERR_APPEAL_ALREADY_DECIDED,
                  "Appeal in %s has already been decided" % appeal["status"])

    # compliance: segregation of duties (priority 8)
    notice = store.notices[appeal["denial_notice_id"]]
    if uid == notice["underwriter_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "Appeal reviewer must differ from the denying underwriter")

    appeal["status"] = outcome
    appeal["reviewer_user_id"] = uid
    appeal["decided_at"] = clock.now()
    bump(appeal)

    app = store.applications[notice["application_id"]]
    loan = loan_of_appeal(appeal)

    if outcome == "AFFIRMED":
        # notice APPEALED -> AFFIRMED; application APPEAL_REVIEW -> CLOSED_DENIED
        notice["status"] = "AFFIRMED"
        bump(notice)
        if app["status"] == "APPEAL_REVIEW":
            app["status"] = "CLOSED_DENIED"
            bump(app)
        if loan is not None:
            maybe_revert_workout(loan)
    else:
        # OVERTURNED 3-level cascade
        # L1: notice APPEALED -> SUPERSEDED
        notice["status"] = "SUPERSEDED"
        bump(notice)
        # L2: application APPEAL_REVIEW -> COMPLETE_PACKAGE (re-enters blocking state)
        if app["status"] == "APPEAL_REVIEW":
            app["status"] = "COMPLETE_PACKAGE"
            bump(app)
        # L3: foreclosure case SALE_SCHEDULED -> SALE_HOLD (caused by L2)
        if loan is not None:
            case = latest_active_case(loan["id"])
            if case is not None and case["status"] == "SALE_SCHEDULED":
                case["status"] = "SALE_HOLD"
                bump(case)
    return success_object(appeal_out(appeal))
