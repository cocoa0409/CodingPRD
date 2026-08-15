"""FundingRequest endpoints: filing, PIA review loop, decision, service start (PRD 3.5)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE_TRANSITION, ERR_FILING_WINDOW_CLOSED,
    ERR_EMPTY_REQUEST, ERR_DISCOUNT_SNAPSHOT_MISSING, ERR_STALE_VERSION,
    ERR_SOD_COMMITMENT_OFFICER,
)
from middleware import get_caller, check_role, check_applicant_scope
from response import success_object
from routes.helpers import public, list_collection, get_one
from services.calcs import discount_rate, run_line_commitment
from services.core import (
    new_record, touch, retain_document, latest_snapshot, lines_of_request,
)
from util import CLOCK, parse_date
from validate import (
    get_body, check_allowed, req_str, req_int, req_enum, opt_str,
    require_ref, require_path_resource,
)

bp = Blueprint("funding_requests", __name__, url_prefix="/erate")

CREATE_FIELDS = {"applicant_id", "funding_cycle_id"}


def _scope_existing_request(caller, req):
    if req is not None:
        check_applicant_scope(caller, req["applicant_id"])


@bp.post("/funding-requests")
def create_request():
    caller = get_caller()
    check_role(caller, ["ApplicantCoordinator"])
    body = get_body()
    raw_applicant = body.get("applicant_id")
    if isinstance(raw_applicant, str):
        check_applicant_scope(caller, raw_applicant)
    check_allowed(body, CREATE_FIELDS)
    applicant_id = req_str(body, "applicant_id")
    funding_cycle_id = req_str(body, "funding_cycle_id")
    require_ref("applicants", applicant_id, "applicant_id")
    require_ref("funding_cycles", funding_cycle_id, "funding_cycle_id")
    rec = new_record("funding_requests", {
        "applicant_id": applicant_id,
        "funding_cycle_id": funding_cycle_id,
        "status": "DRAFT",
        "nslp_share_pct": None,
        "discount_rate_c1_pct": None,
        "discount_rate_c2_pct": None,
        "committed_total_share_cents": 0,
        "services_started": False,
        "service_start_date": None,
        "pia_reviewer_user_ids": [],
        "decision_date": None,
        "decided_by_user_id": None,
    })
    return success_object(public(rec), 201)


@bp.get("/funding-requests")
def list_requests():
    return list_collection("funding_requests", {
        "applicant_id": request.args.get("applicant_id"),
        "funding_cycle_id": request.args.get("funding_cycle_id"),
        "status": request.args.get("status"),
    })


@bp.get("/funding-requests/<rid>")
def get_request(rid):
    return get_one("funding_requests", rid)


@bp.post("/funding-requests/<rid>/certify")
def certify(rid):
    caller = get_caller()
    check_role(caller, ["ApplicantCertifier"])
    _scope_existing_request(caller, db["funding_requests"].get(rid))
    body = get_body()
    check_allowed(body, set())
    freq = require_path_resource("funding_requests", rid)
    if freq["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE_TRANSITION, "funding request is not DRAFT")
    cycle = db["funding_cycles"][freq["funding_cycle_id"]]
    today = CLOCK.today()
    # Filing window is the closed interval [window_open_date, window_close_date].
    if not (parse_date(cycle["window_open_date"]) <= today
            <= parse_date(cycle["window_close_date"])):
        raise_error(ERR_FILING_WINDOW_CLOSED,
                    "clock date is outside the cycle's filing window")
    pending = [l for l in lines_of_request(rid) if l["status"] == "PENDING"]
    if not pending:
        raise_error(ERR_EMPTY_REQUEST, "the request has no lines")
    snapshot = latest_snapshot(freq["applicant_id"], freq["funding_cycle_id"])
    if snapshot is None:
        raise_error(ERR_DISCOUNT_SNAPSHOT_MISSING,
                    "no NSLP snapshot exists for this applicant and funding cycle")
    applicant = db["applicants"][freq["applicant_id"]]
    share = snapshot["effective_share_pct"]
    freq["nslp_share_pct"] = share
    freq["discount_rate_c1_pct"] = discount_rate("CATEGORY_ONE",
                                                 applicant["urban_rural"], share)
    freq["discount_rate_c2_pct"] = discount_rate("CATEGORY_TWO",
                                                 applicant["urban_rural"], share)
    freq["status"] = "FILED"
    retain_document("FUNDING_REQUEST", rid, freq["funding_cycle_id"],
                    "REQUEST_CERTIFICATION")
    touch(freq)
    return success_object(public(freq))


@bp.post("/funding-requests/<rid>/begin-review")
def begin_review(rid):
    caller = get_caller()
    check_role(caller, ["PIAReviewer"])
    body = get_body()
    check_allowed(body, set())
    freq = require_path_resource("funding_requests", rid)
    if freq["status"] != "FILED":
        raise_error(ERR_INVALID_STATE_TRANSITION, "funding request is not FILED")
    freq["status"] = "PIA_REVIEW"
    freq["pia_reviewer_user_ids"].append(caller.user_id)
    touch(freq)
    return success_object(public(freq))


@bp.post("/funding-requests/<rid>/request-info")
def request_info(rid):
    caller = get_caller()
    check_role(caller, ["PIAReviewer"])
    body = get_body()
    check_allowed(body, {"info_request_text"})
    req_str(body, "info_request_text")
    freq = require_path_resource("funding_requests", rid)
    if freq["status"] not in ("PIA_REVIEW", "INFORMATION_REQUESTED"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    "funding request is not in PIA review")
    # Self-loop from INFORMATION_REQUESTED: status unchanged, version advances.
    freq["status"] = "INFORMATION_REQUESTED"
    freq["pia_reviewer_user_ids"].append(caller.user_id)
    touch(freq)
    return success_object(public(freq))


@bp.post("/funding-requests/<rid>/pia-responses")
def pia_response(rid):
    caller = get_caller()
    check_role(caller, ["ApplicantCoordinator"])
    _scope_existing_request(caller, db["funding_requests"].get(rid))
    body = get_body()
    check_allowed(body, {"response_text", "expected_request_version"})
    req_str(body, "response_text")
    expected_request_version = req_int(body, "expected_request_version")
    freq = require_path_resource("funding_requests", rid)
    if freq["status"] != "INFORMATION_REQUESTED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    "no information request is outstanding")
    # OCC rule pia-response-stale-request.
    if expected_request_version != freq["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_request_version does not match the request's current version")
    freq["status"] = "PIA_REVIEW"
    touch(freq)
    return success_object(public(freq))


@bp.post("/funding-requests/<rid>/decide")
def decide(rid):
    caller = get_caller()
    check_role(caller, ["CommitmentOfficer"])
    body = get_body()
    check_allowed(body, {"outcome", "rationale"})
    outcome = req_enum(body, "outcome", ("COMMITTED", "DENIED"))
    opt_str(body, "rationale")
    freq = require_path_resource("funding_requests", rid)
    if freq["status"] != "PIA_REVIEW":
        # An outstanding INFORMATION_REQUESTED blocks any decision.
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    "funding request is not in PIA_REVIEW")
    # Segregation of duties: the decider must not have reviewed this request.
    if caller.user_id in freq["pia_reviewer_user_ids"]:
        raise_error(ERR_SOD_COMMITMENT_OFFICER,
                    "commitment officer appears among the request's PIA reviewers")
    if outcome == "COMMITTED":
        run_line_commitment(freq, [l for l in lines_of_request(rid)
                                   if l["status"] == "PENDING"])
    else:
        for line in lines_of_request(rid):
            if line["status"] != "PENDING":
                continue
            line["status"] = "DENIED"
            line["denial_reason"] = "REQUEST_DENIED"
            touch(line)
    freq["status"] = outcome
    freq["decision_date"] = CLOCK.today().isoformat()
    freq["decided_by_user_id"] = caller.user_id
    retain_document("FUNDING_REQUEST", rid, freq["funding_cycle_id"],
                    "COMMITMENT_DECISION")
    touch(freq)
    return success_object(public(freq))


@bp.post("/funding-requests/<rid>/service-start")
def service_start(rid):
    caller = get_caller()
    check_role(caller, ["ApplicantCoordinator"])
    _scope_existing_request(caller, db["funding_requests"].get(rid))
    body = get_body()
    check_allowed(body, set())
    freq = require_path_resource("funding_requests", rid)
    if freq["status"] != "COMMITTED" or freq["services_started"]:
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    "service start requires a COMMITTED request that has not started")
    freq["services_started"] = True
    freq["service_start_date"] = CLOCK.today().isoformat()
    touch(freq)
    return success_object(public(freq))
