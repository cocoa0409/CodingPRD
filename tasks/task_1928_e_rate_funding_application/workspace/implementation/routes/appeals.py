"""Appeal endpoints: filing inside the closed 60-day window, review, decision with
the GRANTED recommit cascade (PRD 3.8)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE_TRANSITION, ERR_APPEAL_WINDOW_PASSED,
    ERR_APPEAL_ALREADY_ACTIVE,
)
from middleware import get_caller, check_role, check_applicant_scope
from response import success_object
from routes.helpers import public, list_collection, get_one
from services.calcs import run_line_commitment
from services.core import (
    new_record, touch, retain_document, lines_of_request,
)
from util import CLOCK, parse_date, add_days
from validate import (
    get_body, check_allowed, req_str, req_enum, opt_str,
    require_ref, require_path_resource,
)

bp = Blueprint("appeals", __name__, url_prefix="/erate")

APPEAL_WINDOW_DAYS = 60


@bp.post("/appeals")
def create_appeal():
    caller = get_caller()
    check_role(caller, ["ApplicantCoordinator"])
    body = get_body()
    raw_request_id = body.get("funding_request_id")
    if isinstance(raw_request_id, str):
        req_peek = db["funding_requests"].get(raw_request_id)
        if req_peek is not None:
            check_applicant_scope(caller, req_peek["applicant_id"])
    check_allowed(body, {"funding_request_id", "grounds"})
    funding_request_id = req_str(body, "funding_request_id")
    grounds = req_str(body, "grounds")
    freq = require_ref("funding_requests", funding_request_id, "funding_request_id")
    if freq["status"] != "DENIED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    "only a DENIED funding request may be appealed")
    # Appeal window: closed interval [decision_date, decision_date + 60 days];
    # filing on day 60 is allowed, day 61 is rejected.
    today = CLOCK.today()
    decision_date = parse_date(freq["decision_date"])
    if not (decision_date <= today <= add_days(decision_date, APPEAL_WINDOW_DAYS)):
        raise_error(ERR_APPEAL_WINDOW_PASSED,
                    "the 60-day appeal window has passed")
    active = [a for a in db["appeals"].values()
              if a["funding_request_id"] == funding_request_id
              and a["status"] in ("FILED", "UNDER_REVIEW")]
    if active:
        raise_error(ERR_APPEAL_ALREADY_ACTIVE,
                    "a non-terminal appeal already exists for this request")
    rec = new_record("appeals", {
        "funding_request_id": funding_request_id,
        "grounds": grounds,
        "filed_date": today.isoformat(),
        "status": "FILED",
        "outcome_date": None,
    })
    return success_object(public(rec), 201)


@bp.get("/appeals")
def list_appeals():
    return list_collection("appeals", {
        "funding_request_id": request.args.get("funding_request_id"),
        "status": request.args.get("status"),
    })


@bp.get("/appeals/<rid>")
def get_appeal(rid):
    return get_one("appeals", rid)


@bp.post("/appeals/<rid>/begin-review")
def begin_review(rid):
    caller = get_caller()
    check_role(caller, ["AppealOfficer"])
    body = get_body()
    check_allowed(body, set())
    appeal = require_path_resource("appeals", rid)
    if appeal["status"] != "FILED":
        raise_error(ERR_INVALID_STATE_TRANSITION, "appeal is not FILED")
    appeal["status"] = "UNDER_REVIEW"
    touch(appeal)
    return success_object(public(appeal))


@bp.post("/appeals/<rid>/decide")
def decide(rid):
    caller = get_caller()
    check_role(caller, ["AppealOfficer"])
    body = get_body()
    check_allowed(body, {"outcome", "rationale"})
    outcome = req_enum(body, "outcome", ("GRANTED", "DENIED"))
    opt_str(body, "rationale")
    appeal = require_path_resource("appeals", rid)
    if appeal["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE_TRANSITION, "appeal is not UNDER_REVIEW")
    appeal["status"] = outcome
    appeal["outcome_date"] = CLOCK.today().isoformat()
    freq = db["funding_requests"][appeal["funding_request_id"]]
    if outcome == "GRANTED":
        # LINK1: request DENIED -> COMMITTED.
        freq["status"] = "COMMITTED"
        # LINK2: each DENIED line re-runs the commitment machinery against the
        # budget as it stands now (created_at ASC); zero-draw lines stay DENIED
        # with INSUFFICIENT_BUDGET. LINK3: the committed ledger derives from
        # COMMITTED lines and the request total is recomputed inside.
        run_line_commitment(freq, [l for l in lines_of_request(freq["id"])
                                   if l["status"] == "DENIED"])
        touch(freq)
    retain_document("APPEAL", rid, freq["funding_cycle_id"], "APPEAL_DECISION")
    touch(appeal)
    return success_object(public(appeal))
