"""Grant funds and emergency grant applications (PRD 3.5)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_CLIENT_NOT_ACTIVE, ERR_ASSESSMENT_REQUIRED,
    ERR_GRANT_NOT_REVIEWABLE, ERR_SOD_CONFLICT, ERR_AWARD_CAP_EXHAUSTED, ERR_FUND_CLOSED,
    ERR_FUND_HAS_OPEN_APPLICATIONS, ERR_DISBURSE_WINDOW_LAPSED, ERR_DUPLICATE_FUND,
    ERR_STALE_VERSION, ERR_INVALID_STATE, ERR_FORBIDDEN_OWNERSHIP,
)
from middleware import (
    authenticate, authorize, check_client_scope, check_actor_pin,
)
from response import success_object
from routes.helpers import list_response
from services import calculations as calc
from services.core import (
    new_record, touch, public, serialize_fund, verified_assessment,
    recompute_fund, fund_remaining_committed, maybe_reopen_fund, promote_queued_application,
)
from util import CLOCK, parse_datetime
from validate import (
    get_body, req_int, req_enum, req_str, require_path_resource, require_body_ref,
)

bp = Blueprint("grants", __name__)

CATEGORIES = ["RENT", "UTILITY", "FOOD", "MEDICAL", "TRANSPORT", "CHILDCARE"]
OPEN_APP_STATES = ("SUBMITTED", "QUEUED", "UNDER_REVIEW", "MORE_INFO_REQUESTED", "APPROVED")
GRANT_READ_ROLES = ["Client", "IntakeCoordinator", "GrantReviewer", "HubAdmin"]


# ---------------------------------------------------------------------------
# Funds
# ---------------------------------------------------------------------------

@bp.post("/grant-funds")
def create_fund():
    caller = authenticate()
    authorize(caller, ["HubAdmin"])
    body = get_body()
    fund_name = req_str(body, "fund_name")
    fiscal_year = req_int(body, "fiscal_year")
    allocated_cents = req_int(body, "allocated_cents")
    if allocated_cents <= 0:
        raise_error(ERR_INVALID_REQUEST, "allocated_cents must be > 0")
    for f in db["grant_funds"].values():
        if f["fund_name"] == fund_name and f["fiscal_year"] == fiscal_year:
            raise_error(ERR_DUPLICATE_FUND, "(fund_name, fiscal_year) already exists")
    rec = new_record("grant_funds", {
        "fund_name": fund_name,
        "fiscal_year": fiscal_year,
        "allocated_cents": allocated_cents,
        "committed_cents": 0,
        "disbursed_cents": 0,
        "status": "OPEN",
    })
    return success_object(serialize_fund(rec), status=201)


@bp.get("/grant-funds/<fid>")
def get_fund(fid):
    caller = authenticate()
    authorize(caller, ["GrantReviewer", "HubAdmin"])
    fund = require_path_resource("grant_funds", fid, "grant fund")
    return success_object(serialize_fund(fund))


@bp.post("/grant-funds/<fid>/close")
def close_fund(fid):
    caller = authenticate()
    authorize(caller, ["HubAdmin"])
    fund = require_path_resource("grant_funds", fid, "grant fund")
    if fund["status"] == "CLOSED":
        raise_error(ERR_INVALID_STATE, "fund is already CLOSED")
    for g in db["grant_applications"].values():
        if g["fund_id"] == fund["id"] and g["status"] in OPEN_APP_STATES:
            raise_error(ERR_FUND_HAS_OPEN_APPLICATIONS,
                        "applications still occupy open states against this fund")
    fund["status"] = "CLOSED"
    touch(fund)
    return success_object(serialize_fund(fund))


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

@bp.post("/clients/<cid>/grant-applications")
def create_application(cid):
    caller = authenticate()
    authorize(caller, ["Client", "IntakeCoordinator", "GrantReviewer"])
    client = require_path_resource("clients", cid, "client")
    check_client_scope(caller, client["id"])
    body = get_body()
    fund_id = req_str(body, "fund_id")
    category = req_enum(body, "category", CATEGORIES)
    requested_cents = req_int(body, "requested_cents")
    hardship_statement = req_str(body, "hardship_statement")
    if requested_cents < 100 or requested_cents > calc.PER_AWARD_CAP_CENTS:
        raise_error(ERR_INVALID_REQUEST, "requested_cents must be within [100, 150000]")
    if client["status"] != "ACTIVE":
        raise_error(ERR_CLIENT_NOT_ACTIVE, "grant creation requires an ACTIVE client")
    if verified_assessment(client["id"]) is None:
        raise_error(ERR_ASSESSMENT_REQUIRED, "client must hold a VERIFIED assessment")
    fund = require_body_ref("grant_funds", fund_id, "fund_id")
    if fund["status"] == "CLOSED":
        raise_error(ERR_FUND_CLOSED, "cannot create an application against a CLOSED fund")
    rec = new_record("grant_applications", {
        "client_id": client["id"],
        "fund_id": fund["id"],
        "category": category,
        "requested_cents": requested_cents,
        "hardship_statement": hardship_statement,
        "created_by_user_id": caller.user_id,
        "status": "DRAFT",
        "reviewed_by": None,
        "info_request_notes": None,
        "decision_rationale": None,
        "approved_cents": 0,
        "approved_at": None,
        "disbursed_at": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/grant-applications")
def list_applications():
    caller = authenticate()
    authorize(caller, GRANT_READ_ROLES)
    filters = {
        "client_id": request.args.get("client_id"),
        "fund_id": request.args.get("fund_id"),
        "reviewed_by": request.args.get("reviewed_by"),
        "status": request.args.get("status"),
    }
    scope = None
    if caller.role == "Client":
        scope = lambda rec: rec["client_id"] == caller.user_id
    return list_response("grant_applications", filters, scope_fn=scope)


@bp.get("/grant-applications/<gid>")
def get_application(gid):
    caller = authenticate()
    authorize(caller, GRANT_READ_ROLES)
    app = require_path_resource("grant_applications", gid, "grant application")
    check_client_scope(caller, app["client_id"])
    return success_object(public(app))


def _check_applicant_scope(caller, app):
    """Client role must be the owning client AND the recorded creator."""
    if caller.role == "Client":
        if caller.user_id != app["client_id"] or caller.user_id != app["created_by_user_id"]:
            raise_error(ERR_FORBIDDEN_OWNERSHIP,
                        "only the creating client may drive this application")


@bp.post("/grant-applications/<gid>/submit")
def submit_application(gid):
    caller = authenticate()
    authorize(caller, ["Client", "IntakeCoordinator"])
    app = require_path_resource("grant_applications", gid, "grant application")
    _check_applicant_scope(caller, app)
    if app["status"] not in ("DRAFT", "MORE_INFO_REQUESTED"):
        raise_error(ERR_GRANT_NOT_REVIEWABLE, "application is not in a submittable state")
    client = db["clients"].get(app["client_id"])
    if client is None or client["status"] != "ACTIVE":
        raise_error(ERR_CLIENT_NOT_ACTIVE, "submission requires an ACTIVE client")
    if verified_assessment(app["client_id"]) is None:
        raise_error(ERR_ASSESSMENT_REQUIRED, "client must hold a VERIFIED assessment")
    fund = db["grant_funds"].get(app["fund_id"])
    if fund is not None and fund["status"] == "CLOSED":
        raise_error(ERR_FUND_CLOSED, "cannot submit against a CLOSED fund")
    if app["status"] == "MORE_INFO_REQUESTED":
        # Resubmission cycle: clear the claim and re-enter the review pool
        app["reviewed_by"] = None
        app["status"] = "SUBMITTED"
    else:
        # DRAFT: OPEN fund -> SUBMITTED; EXHAUSTED fund parks as QUEUED
        app["status"] = "QUEUED" if (fund is not None and fund["status"] == "EXHAUSTED") else "SUBMITTED"
    touch(app)
    return success_object(public(app))


@bp.post("/grant-applications/<gid>/begin-review")
def begin_review(gid):
    caller = authenticate()
    authorize(caller, ["GrantReviewer"])
    app = require_path_resource("grant_applications", gid, "grant application")
    if app["status"] != "SUBMITTED":
        raise_error(ERR_GRANT_NOT_REVIEWABLE, "only a SUBMITTED application can be claimed")
    if caller.user_id == app["created_by_user_id"]:
        raise_error(ERR_SOD_CONFLICT, "the reviewer who assisted the intake may not review it")
    app["reviewed_by"] = caller.user_id
    app["status"] = "UNDER_REVIEW"
    touch(app)
    return success_object(public(app))


@bp.post("/grant-applications/<gid>/request-info")
def request_info(gid):
    caller = authenticate()
    authorize(caller, ["GrantReviewer"])
    app = require_path_resource("grant_applications", gid, "grant application")
    check_actor_pin(caller, app["reviewed_by"])
    if app["status"] != "UNDER_REVIEW":
        raise_error(ERR_GRANT_NOT_REVIEWABLE, "only an UNDER_REVIEW application can be sent back")
    body = get_body()
    notes = req_str(body, "info_request_notes")
    app["info_request_notes"] = notes
    app["status"] = "MORE_INFO_REQUESTED"
    touch(app)
    return success_object(public(app))


@bp.post("/grant-applications/<gid>/approve")
def approve_application(gid):
    caller = authenticate()
    authorize(caller, ["GrantReviewer"])
    app = require_path_resource("grant_applications", gid, "grant application")
    check_actor_pin(caller, app["reviewed_by"])
    if app["status"] != "UNDER_REVIEW":
        raise_error(ERR_GRANT_NOT_REVIEWABLE, "only an UNDER_REVIEW application can be approved")
    fund = db["grant_funds"].get(app["fund_id"])
    body = get_body()
    # OCC on GrantFund.version: after state admission, before award sizing
    expected = body.get("expected_fund_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise_error(ERR_INVALID_REQUEST, "expected_fund_version is required")
    if fund is None or expected != fund["version"]:
        raise_error(ERR_STALE_VERSION, "expected_fund_version does not match the fund's current version")
    lifetime = calc.lifetime_grant_cents(app["client_id"])
    award = calc.size_award(app, fund, lifetime)
    if award <= 0:
        raise_error(ERR_AWARD_CAP_EXHAUSTED, "award sizing yields a non-positive amount")
    app["approved_cents"] = award
    app["approved_at"] = CLOCK.now_iso()
    app["status"] = "APPROVED"
    touch(app)
    # Commit against the fund: counters recompute, one version advance
    recompute_fund(fund, bump=False)
    remaining = fund_remaining_committed(fund)
    if fund["status"] == "OPEN" and remaining == 0 and fund["committed_cents"] > 0:
        fund["status"] = "EXHAUSTED"  # subsequent submissions park as QUEUED
    touch(fund)
    return success_object(public(app))


@bp.post("/grant-applications/<gid>/deny")
def deny_application(gid):
    caller = authenticate()
    authorize(caller, ["GrantReviewer"])
    app = require_path_resource("grant_applications", gid, "grant application")
    check_actor_pin(caller, app["reviewed_by"])
    if app["status"] != "UNDER_REVIEW":
        raise_error(ERR_GRANT_NOT_REVIEWABLE, "only an UNDER_REVIEW application can be denied")
    body = get_body()
    rationale = req_str(body, "decision_rationale")
    app["decision_rationale"] = rationale
    app["status"] = "DENIED"
    touch(app)
    return success_object(public(app))


@bp.post("/grant-applications/<gid>/disburse")
def disburse_application(gid):
    caller = authenticate()
    authorize(caller, ["HubAdmin"])
    app = require_path_resource("grant_applications", gid, "grant application")
    if app["status"] != "APPROVED":
        raise_error(ERR_GRANT_NOT_REVIEWABLE, "only an APPROVED application can be disbursed")
    # Two-person rule: the disbursing admin must differ from the recorded reviewer
    if caller.user_id == app["reviewed_by"]:
        raise_error(ERR_SOD_CONFLICT, "disburser must differ from reviewed_by")
    now = CLOCK.now()
    if now > parse_datetime(app["approved_at"]) + timedelta(hours=72):
        raise_error(ERR_DISBURSE_WINDOW_LAPSED, "past the approved_at + 72h window")
    app["disbursed_at"] = CLOCK.now_iso()
    app["status"] = "DISBURSED"
    touch(app)
    fund = db["grant_funds"].get(app["fund_id"])
    if fund is not None:
        recompute_fund(fund, bump=False)  # committed -= approved; disbursed += approved
        reopened = maybe_reopen_fund(fund)
        touch(fund)
        if reopened:
            promote_queued_application(fund)  # oldest QUEUED -> SUBMITTED
    client = db["clients"].get(app["client_id"])
    if client is not None:
        touch(client)  # lifetime_grant_cents recompute (PRD 2.5)
    return success_object(public(app))


@bp.post("/grant-applications/<gid>/withdraw")
def withdraw_application(gid):
    caller = authenticate()
    authorize(caller, ["Client", "IntakeCoordinator"])
    app = require_path_resource("grant_applications", gid, "grant application")
    _check_applicant_scope(caller, app)
    if app["status"] not in ("DRAFT", "SUBMITTED", "QUEUED"):
        raise_error(ERR_GRANT_NOT_REVIEWABLE, "application is not in a withdrawable state")
    app["status"] = "WITHDRAWN"
    touch(app)
    return success_object(public(app))
