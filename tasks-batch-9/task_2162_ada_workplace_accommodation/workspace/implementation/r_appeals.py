"""Denial records, appeals and the segregation-of-duties guard."""
from flask import Blueprint, g, request as flask_request

import calc
import domain
from authz import (endpoint, need_appeal, need_denial, require_case_owner,
                   require_not_sealed)
from envelope import created, listing, ok, read_pagination, touch
from errors import ApiError
from store import by_created, parse_date, store
from validation import F, raw_body, validate

bp = Blueprint("appeals", __name__)

NOT_ACTIONABLE = "ERR_APPEAL_NOT_ACTIONABLE"


def require_segregation(denial, req):
    """Ladder step 13 (PRD 3.8)."""
    if g.role != "AppealOfficer":
        return
    if g.user_id == denial["issued_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The appeal officer issued the denial under appeal.")
    for analysis in domain.analyses_of(req["id"]):
        if analysis["status"] == "RECORDED" and analysis["manager_id"] == g.user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "The appeal officer signed a function analysis on this case.")


@bp.get("/denial-records/<denial_id>")
@endpoint(["Employee", "Manager", "AccommodationCoordinator", "AppealOfficer",
           "ComplianceAuditor"])
def get_denial(denial_id):
    return ok(need_denial(denial_id))


@bp.get("/denial-records")
@endpoint(["Employee", "AccommodationCoordinator", "AppealOfficer", "ComplianceAuditor"])
def list_denials():
    limit, offset = read_pagination()
    rows = list(store.denials.values())
    for key in ("request_id", "alternative_option_id", "status"):
        value = flask_request.args.get(key)
        if value is not None:
            rows = [d for d in rows if d.get(key) == value]
    return listing(by_created(rows), limit, offset)


@bp.post("/denial-records/<denial_id>/appeals")
@endpoint(["Employee"])
def file_appeal(denial_id):
    data = validate(raw_body(), [F("grounds_text", "string", required=True,
                                   non_empty=True)])
    denial = need_denial(denial_id)
    req = store.requests.get(denial["request_id"])
    require_case_owner(req)
    if denial["status"] != "ISSUED":
        raise ApiError("ERR_DENIAL_NOT_APPEALABLE", "The denial is not appealable.")
    require_not_sealed(req)
    if store.today() > parse_date(denial["appeal_deadline_date"]):
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED", "The appeal window has closed.")
    row = store.new_row("Appeal", {
        "denial_record_id": denial["id"],
        "grounds_text": data["grounds_text"],
        "filed_by_user_id": g.user_id,
        "filed_at": store.now_iso(),
        "appeal_officer_user_id": None,
        "supplement_count": 0,
        "stay_count": 0,
        "outcome": "PENDING",
        "status": "FILED",
    })
    store.appeals[row["id"]] = row
    domain.assign(denial, status="APPEALED", appeal_count=denial["appeal_count"] + 1)
    domain.assign(req, stage="UNDER_APPEAL")
    return created(row)


@bp.get("/denial-records/<denial_id>/appeals")
@endpoint(["Employee", "AccommodationCoordinator", "AppealOfficer", "ComplianceAuditor"])
def list_appeals(denial_id):
    limit, offset = read_pagination()
    need_denial(denial_id)
    rows = domain.appeals_of_denial(denial_id)
    status = flask_request.args.get("status")
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    return listing(by_created(rows), limit, offset)


@bp.get("/appeals/<appeal_id>")
@endpoint(["Employee", "AccommodationCoordinator", "AppealOfficer", "ComplianceAuditor"])
def get_appeal(appeal_id):
    return ok(need_appeal(appeal_id))


@bp.post("/appeals/<appeal_id>/transition")
@endpoint(["AppealOfficer", "Employee"])
def transition_appeal(appeal_id):
    data = validate(raw_body(), [F("action", "enum", required=True,
                                   enum=("START_REVIEW", "REQUEST_SUPPLEMENT",
                                         "SUBMIT_SUPPLEMENT"))])
    appeal = need_appeal(appeal_id)
    denial, req = domain.case_of_appeal(appeal)
    require_case_owner(req)
    action = data["action"]
    status = appeal["status"]

    if action == "START_REVIEW":
        if status != "FILED" or g.role != "AppealOfficer":
            raise ApiError(NOT_ACTIONABLE, "START_REVIEW is not available here.")
    elif action == "REQUEST_SUPPLEMENT":
        if status != "UNDER_REVIEW" or g.role != "AppealOfficer":
            raise ApiError(NOT_ACTIONABLE, "REQUEST_SUPPLEMENT is not available here.")
    else:
        if status != "SUPPLEMENT_REQUESTED" or g.role != "Employee":
            raise ApiError(NOT_ACTIONABLE, "SUBMIT_SUPPLEMENT is not available here.")

    require_not_sealed(req)
    require_segregation(denial, req)

    if action == "START_REVIEW":
        appeal["status"] = "UNDER_REVIEW"
        appeal["appeal_officer_user_id"] = g.user_id
        touch(appeal)
        return ok(appeal)
    if appeal["supplement_count"] + 1 > calc.MAX_APPEAL_SUPPLEMENTS:
        raise ApiError("ERR_APPEAL_SUPPLEMENT_LIMIT",
                       "The appeal supplement allowance is exhausted.")
    if action == "REQUEST_SUPPLEMENT":
        appeal["status"] = "SUPPLEMENT_REQUESTED"
    else:
        appeal["supplement_count"] = appeal["supplement_count"] + 1
        appeal["status"] = "UNDER_REVIEW"
    touch(appeal)
    return ok(appeal)


@bp.post("/appeals/<appeal_id>/decide")
@endpoint(["AppealOfficer"])
def decide_appeal(appeal_id):
    data = validate(raw_body(), [F("outcome", "enum", required=True,
                                   enum=("UPHOLD", "REVERSE", "REMAND", "DISMISS"))])
    appeal = need_appeal(appeal_id)
    denial, req = domain.case_of_appeal(appeal)
    outcome = data["outcome"]
    status = appeal["status"]
    alternative = store.options.get(denial.get("alternative_option_id") or "")

    if outcome == "DISMISS":
        if status not in ("FILED", "UNDER_REVIEW"):
            raise ApiError(NOT_ACTIONABLE, "DISMISS is not available here.")
    else:
        if status != "UNDER_REVIEW" or g.user_id != appeal["appeal_officer_user_id"]:
            raise ApiError(NOT_ACTIONABLE, "That decision is not available here.")
        if outcome == "REVERSE":
            if alternative is None or alternative["status"] not in ("CLEARED", "SHELVED"):
                raise ApiError(NOT_ACTIONABLE,
                               "The denial carries no reversible alternative option.")

    require_not_sealed(req)
    require_segregation(denial, req)

    if outcome == "UPHOLD":
        if req["interactive_process_integrity_score"] < calc.APPEAL_MANDATORY_REMAND_THRESHOLD:
            raise ApiError("ERR_APPEAL_MUST_REMAND",
                           "The process integrity score forbids upholding the denial.")
    if outcome == "REMAND":
        if req["interactive_round_count"] + 1 > calc.MAX_INTERACTIVE_ROUNDS:
            raise ApiError("ERR_INTERACTIVE_ROUND_LIMIT",
                           "The interactive-round allowance is exhausted.")

    employee = store.employees.get(req["employee_id"])
    if outcome == "UPHOLD":
        appeal["status"] = "UPHELD"
        appeal["outcome"] = "UPHELD"
        touch(appeal)
        domain.assign(denial, status="FINAL")
        domain.assign(req, stage="DENIED_FINAL")
        if employee is not None:
            domain.recompute_open_case_count(employee)
    elif outcome == "DISMISS":
        appeal["status"] = "DISMISSED"
        appeal["outcome"] = "DISMISSED"
        touch(appeal)
        domain.assign(denial, status="FINAL")
        domain.assign(req, stage="DENIED")
    elif outcome == "REVERSE":
        appeal["status"] = "REVERSED"
        appeal["outcome"] = "REVERSED"
        touch(appeal)
        domain.assign(denial, status="VACATED")
        if employee is not None:
            domain.recompute_denial_count(employee)
        domain.assign(alternative, status="IMPLEMENTED")
        domain.ledger_commit(alternative, req)
        domain.assign(req, stage="GRANTED_PERMANENT", decision="GRANT_PERMANENT",
                      selected_option_id=alternative["id"])
        cadence, due = calc.renewal_cadence(req)
        domain.assign(req, review_cadence_days=cadence, review_due_date=due)
    else:
        appeal["status"] = "REMANDED"
        appeal["outcome"] = "REMANDED"
        touch(appeal)
        domain.assign(denial, status="VACATED")
        if employee is not None:
            domain.recompute_denial_count(employee)
        domain.assign(req, stage="OPTION_EXPLORATION",
                      interactive_round_count=req["interactive_round_count"] + 1)
        for option in by_created(domain.options_of(req["id"])):
            if option["status"] != "HARDSHIP_BLOCKED":
                continue
            domain.assign(option, status="PROPOSED")
            current = domain.current_assessment(option["id"])
            if current is not None:
                domain.assign(current, status="SUPERSEDED")
        domain.assign(req, blocked_option_count=0)
    return ok(appeal)
