"""Benefits screenings and counselor caseloads (PRD 3.4)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_CLIENT_NOT_ACTIVE, ERR_ASSESSMENT_REQUIRED,
    ERR_SCREENING_NOT_ACTIONABLE, ERR_NO_COUNSELOR_AVAILABLE,
)
from middleware import (
    authenticate, authorize, check_client_scope, check_confidential_wall, check_actor_pin,
)
from response import success_object
from routes.helpers import list_response
from services import calculations as calc
from services.core import new_record, touch, public, verified_assessment
from util import CLOCK
from validate import get_body, req_enum, require_path_resource

bp = Blueprint("screenings", __name__)

PROGRAMS = ["SNAP", "CHILDCARE", "HOUSING"]
SCREENING_READ_ROLES = ["Client", "IntakeCoordinator", "BenefitsCounselor", "HubAdmin"]
PRE_TERMINAL = ("STARTED", "SCREENED", "APPLICATION_ASSISTED", "SUBMITTED")


@bp.post("/clients/<cid>/screenings")
def create_screening(cid):
    caller = authenticate()
    authorize(caller, ["IntakeCoordinator", "BenefitsCounselor"])
    client = require_path_resource("clients", cid, "client")
    body = get_body()
    program = req_enum(body, "program", PROGRAMS)
    if client["status"] != "ACTIVE":
        raise_error(ERR_CLIENT_NOT_ACTIVE, "screening creation requires an ACTIVE client")
    if verified_assessment(client["id"]) is None:
        raise_error(ERR_ASSESSMENT_REQUIRED, "client must hold a VERIFIED assessment")
    counselor = calc.select_counselor()
    if counselor is None:
        raise_error(ERR_NO_COUNSELOR_AVAILABLE, "no ACTIVE BENEFITS_COUNSELOR exists")
    rec = new_record("screenings", {
        "client_id": client["id"],
        "program": program,
        "status": "STARTED",
        "counselor_id": counselor["id"],
        "score": None,
        "result_band": None,
        "snap_estimate_cents": None,
        "determination_outcome": None,
        "determined_at": None,
    })
    touch(counselor)  # active_case_load += 1 on assignment (PRD 2.5)
    return success_object(public(rec), status=201)


@bp.get("/screenings")
def list_screenings():
    caller = authenticate()
    authorize(caller, SCREENING_READ_ROLES, confidential=True)
    check_confidential_wall(caller)
    filters = {
        "client_id": request.args.get("client_id"),
        "counselor_id": request.args.get("counselor_id"),
        "program": request.args.get("program"),
        "status": request.args.get("status"),
    }
    scope = None
    if caller.role == "Client":
        scope = lambda rec: rec["client_id"] == caller.user_id
    return list_response("screenings", filters, scope_fn=scope)


@bp.get("/screenings/<sid>")
def get_screening(sid):
    caller = authenticate()
    authorize(caller, SCREENING_READ_ROLES, confidential=True)
    screening = require_path_resource("screenings", sid, "screening")
    check_client_scope(caller, screening["client_id"])
    check_confidential_wall(caller)
    return success_object(public(screening))


def _owned_screening(caller, sid):
    screening = require_path_resource("screenings", sid, "screening")
    # Actor-pinned: only the assigned counselor may drive the screening (priority 4)
    check_actor_pin(caller, screening["counselor_id"])
    return screening


@bp.post("/screenings/<sid>/score")
def score_screening(sid):
    caller = authenticate()
    authorize(caller, ["BenefitsCounselor"])
    screening = _owned_screening(caller, sid)
    if screening["status"] != "STARTED":
        raise_error(ERR_SCREENING_NOT_ACTIONABLE, "only a STARTED screening can be scored")
    va = verified_assessment(screening["client_id"])
    if va is None:
        raise_error(ERR_ASSESSMENT_REQUIRED, "client must hold a VERIFIED assessment")
    score, band = calc.compute_screening_score(screening["program"], va)
    screening["score"] = score
    screening["result_band"] = band
    if screening["program"] == "SNAP":
        screening["snap_estimate_cents"] = calc.compute_snap_estimate(va)
    screening["status"] = "SCREENED"
    touch(screening)
    return success_object(public(screening))


@bp.post("/screenings/<sid>/assist")
def assist_screening(sid):
    caller = authenticate()
    authorize(caller, ["BenefitsCounselor"])
    screening = _owned_screening(caller, sid)
    if screening["status"] != "SCREENED":
        raise_error(ERR_SCREENING_NOT_ACTIONABLE, "only a SCREENED screening can be assisted")
    if screening["result_band"] not in ("LIKELY_ELIGIBLE", "POSSIBLY_ELIGIBLE"):
        raise_error(ERR_SCREENING_NOT_ACTIONABLE, "assistance requires an eligible result band")
    screening["status"] = "APPLICATION_ASSISTED"
    touch(screening)
    return success_object(public(screening))


@bp.post("/screenings/<sid>/submit-application")
def submit_application_screening(sid):
    caller = authenticate()
    authorize(caller, ["BenefitsCounselor"])
    screening = _owned_screening(caller, sid)
    if screening["status"] != "APPLICATION_ASSISTED":
        raise_error(ERR_SCREENING_NOT_ACTIONABLE, "only an APPLICATION_ASSISTED screening can be submitted")
    screening["status"] = "SUBMITTED"
    touch(screening)
    return success_object(public(screening))


@bp.post("/screenings/<sid>/determine")
def determine_screening(sid):
    caller = authenticate()
    authorize(caller, ["BenefitsCounselor"])
    screening = _owned_screening(caller, sid)
    if screening["status"] != "SUBMITTED":
        raise_error(ERR_SCREENING_NOT_ACTIONABLE, "only a SUBMITTED screening can be determined")
    body = get_body()
    outcome = req_enum(body, "outcome", ["APPROVED_BY_AGENCY", "DENIED_BY_AGENCY"])
    screening["determination_outcome"] = outcome
    screening["determined_at"] = CLOCK.now_iso()
    screening["status"] = "DETERMINED"
    touch(screening)
    return success_object(public(screening))


@bp.post("/screenings/<sid>/withdraw")
def withdraw_screening(sid):
    caller = authenticate()
    authorize(caller, ["BenefitsCounselor"])
    screening = _owned_screening(caller, sid)
    if screening["status"] not in PRE_TERMINAL:
        raise_error(ERR_SCREENING_NOT_ACTIONABLE, "screening is not in a withdrawable state")
    screening["status"] = "WITHDRAWN"
    touch(screening)
    return success_object(public(screening))
