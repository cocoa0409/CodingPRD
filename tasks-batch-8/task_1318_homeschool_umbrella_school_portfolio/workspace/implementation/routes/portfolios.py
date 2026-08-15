"""Portfolio and evaluation endpoints."""
from datetime import date as _date
from datetime import datetime, time, timezone

from flask import Blueprint, request

import clock
import db
from errors import raise_err
from middleware import route, ALL_ROLES
from response import success_object, success_list
from serializers import ser_portfolio, ser_evaluation
from services import core
from services import coop as coop_svc
from validation import (
    get_body, req_enum, opt_string, req_subject_scores, EVALUATION_OUTCOMES,
)

bp = Blueprint("portfolios", __name__)


def _portfolio_family_id(portfolio):
    en = core.enrollment_of_portfolio(portfolio)
    st = core.student_of_enrollment(en) if en else None
    return st["family_id"] if st else None


@bp.route("/enrollments/<enrollment_id>/portfolios", methods=["POST"])
@route(["Parent"], ownership=("enrollment", "enrollment_id"),
       parent_chain=(("enrollment", "enrollment_id", db.enrollments),))
def create_portfolio(enrollment_id):
    get_body()
    for p in db.portfolios.values():
        if p["enrollment_id"] == enrollment_id:
            raise_err("ERR_PORTFOLIO_ALREADY_EXISTS",
                      "Enrollment already has a portfolio")
    rec = core.make_record({
        "enrollment_id": enrollment_id,
        "status": "DRAFT",
        "attempt_count": 0,
        "submitted_at": None,
        "decided_at": None,
    })
    db.portfolios[rec["id"]] = rec
    return success_object(ser_portfolio(rec), status=201)


@bp.route("/portfolios/<portfolio_id>", methods=["GET"])
@route(ALL_ROLES, ownership=("portfolio", "portfolio_id"),
       parent_chain=(("portfolio", "portfolio_id", db.portfolios),))
def get_portfolio(portfolio_id):
    return success_object(ser_portfolio(db.portfolios[portfolio_id]))


@bp.route("/portfolios/<portfolio_id>/submit", methods=["POST"])
@route(["Parent"], ownership=("portfolio", "portfolio_id"),
       parent_chain=(("portfolio", "portfolio_id", db.portfolios),))
def submit_portfolio(portfolio_id):
    pf = db.portfolios[portfolio_id]
    if pf["status"] not in ("DRAFT", "REMEDIATION_REQUIRED"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only DRAFT or REMEDIATION_REQUIRED portfolios may be submitted")
    en = db.enrollments.get(pf["enrollment_id"])
    if en["enrollment_status"] != "ACTIVE":
        raise_err("ERR_ENROLLMENT_NOT_ACTIVE", "Enrollment must be ACTIVE to submit")
    year = core.year_of_enrollment(en)
    y, m, dd = (int(x) for x in year["end_date"].split("-"))
    end_of_day = datetime.combine(_date(y, m, dd), time(23, 59, 59, 999999),
                                  tzinfo=timezone.utc)
    if clock.now() > end_of_day:
        raise_err("ERR_PORTFOLIO_WINDOW_CLOSED",
                  "Portfolio submission window has closed")
    pf["status"] = "SUBMITTED"
    pf["attempt_count"] += 1
    pf["submitted_at"] = clock.now_iso()
    core.touch(pf)
    return success_object(ser_portfolio(pf))


@bp.route("/portfolios/<portfolio_id>/evaluations", methods=["POST"])
@route(["Reviewer"], parent_chain=(("portfolio", "portfolio_id", db.portfolios),))
def create_evaluation(portfolio_id):
    pf = db.portfolios[portfolio_id]
    body = get_body()
    outcome = req_enum(body, "overall_outcome", EVALUATION_OUTCOMES)
    subject_scores = req_subject_scores(body, "subject_scores")
    notes = opt_string(body, "notes")
    if pf["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only SUBMITTED portfolios may be evaluated")
    if request.user_id == _portfolio_family_id(pf):
        raise_err("ERR_REVIEWER_CONFLICT_OF_INTEREST",
                  "A parent may not evaluate their own child's portfolio")
    if outcome == "ACCEPTED":
        if any(s["score"] < 2 for s in subject_scores):
            raise_err("ERR_EVALUATION_SCORE_OUTCOME_MISMATCH",
                      "ACCEPTED requires every subject score >= 2")

    # Immutable evaluation row: only id + created_at among the common fields
    rec = {
        "id": core.new_id(),
        "created_at": clock.now_iso(),
        "portfolio_id": portfolio_id,
        "reviewer_id": request.user_id,
        "attempt_number": pf["attempt_count"],
        "overall_outcome": outcome,
        "subject_scores": [dict(s) for s in subject_scores],
        "notes": notes,
    }
    db.evaluations[rec["id"]] = rec

    if outcome == "ACCEPTED":
        pf["status"] = "ACCEPTED"
        pf["decided_at"] = clock.now_iso()
        core.touch(pf)
    elif outcome == "REMEDIATION_REQUIRED":
        if pf["attempt_count"] < 3:
            pf["status"] = "REMEDIATION_REQUIRED"
            core.touch(pf)
        else:
            # forced rejection at the third attempt
            pf["status"] = "REJECTED"
            pf["decided_at"] = clock.now_iso()
            core.touch(pf)
            _fire_noncompliant(pf)
    else:  # REJECTED
        pf["status"] = "REJECTED"
        pf["decided_at"] = clock.now_iso()
        core.touch(pf)
        _fire_noncompliant(pf)

    return success_object(ser_evaluation(rec), status=201)


def _fire_noncompliant(portfolio):
    en = db.enrollments.get(portfolio["enrollment_id"])
    if en is None:
        return
    if en["standing_locked"]:
        return
    if en["compliance_standing"] == "NONCOMPLIANT":
        return
    en["compliance_standing"] = "NONCOMPLIANT"
    core.touch(en)
    coop_svc.noncompliant_cascade(en)


@bp.route("/portfolios/<portfolio_id>/evaluations", methods=["GET"])
@route(ALL_ROLES, ownership=("portfolio", "portfolio_id"),
       parent_chain=(("portfolio", "portfolio_id", db.portfolios),))
def list_evaluations(portfolio_id):
    recs = [e for e in db.evaluations.values() if e["portfolio_id"] == portfolio_id]
    recs = core.sorted_by_created(recs)
    page, limit, offset, total = core.paginate(recs)
    return success_list([ser_evaluation(e) for e in page], limit, offset, total)


@bp.route("/evaluations/<evaluation_id>", methods=["GET"])
@route(ALL_ROLES, ownership=("evaluation", "evaluation_id"),
       parent_chain=(("evaluation", "evaluation_id", db.evaluations),))
def get_evaluation(evaluation_id):
    return success_object(ser_evaluation(db.evaluations[evaluation_id]))
