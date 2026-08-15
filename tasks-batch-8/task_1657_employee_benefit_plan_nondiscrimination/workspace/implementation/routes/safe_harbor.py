"""SafeHarborElection and SafeHarborNotice routes (PRD §3.8)."""

from datetime import date

from flask import Blueprint, request

from db import clock, store
from errors import (
    ApiError, ERR_DUPLICATE, ERR_ELECTION_LOCKED, ERR_INVALID_DATE_RANGE,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOTICE_WINDOW_CLOSED,
    ERR_STALE_VERSION,
)
from middleware import READ_ROLES, ROLE_PLAN_ADMINISTRATOR, require_roles
from response import success_list, success_object
from services import safe_harbor as sh_svc
from services.common import (
    bump, fmt_dt, get_body, get_election, get_notice, get_plan_year, new_entity,
    opt_filter, page_slice, pagination_params, req_date, req_enum, req_string,
    opt_string, supersede_terminal_test_runs,
)

bp = Blueprint("safe_harbor", __name__)

ELECTION_DESIGNS = {"BASIC_MATCH", "ENHANCED_MATCH", "QNEC_3PCT", "QACA"}
ELECTION_PROPOSE_STATES = {
    "DRAFT", "CENSUS_COLLECTING", "CENSUS_LOCKED", "TESTING", "RESULTS_REVIEW",
}


def election_out(e):
    return {
        "id": e["id"], "plan_year_id": e["plan_year_id"],
        "design": e["design"], "elected_on": e["elected_on"],
        "status": e["status"],
        "suspension_reason": e["suspension_reason"],
        "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"],
    }


def notice_out(n):
    return {
        "id": n["id"], "election_id": n["election_id"],
        "notice_period_start": n["notice_period_start"],
        "notice_period_end": n["notice_period_end"],
        "distributed_at": n["distributed_at"],
        "status": n["status"], "created_at": n["created_at"],
        "updated_at": n["updated_at"], "version": n["version"],
    }


@bp.route("/ndt/plan-years/<pyid>/safe-harbor-elections", methods=["GET"])
def list_elections(pyid):
    require_roles(READ_ROLES)
    get_plan_year(pyid)
    limit, offset = pagination_params()
    status = opt_filter(request.args, "status")
    items = [e for e in store.safe_harbor_elections.values()
             if e["plan_year_id"] == pyid]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, total = page_slice(items, limit, offset)
    return success_list([election_out(e) for e in page], limit, offset, total)


@bp.route("/ndt/plan-years/<pyid>/safe-harbor-elections", methods=["POST"])
def propose_election(pyid):
    require_roles({ROLE_PLAN_ADMINISTRATOR})
    py = get_plan_year(pyid)
    if py["status"] not in ELECTION_PROPOSE_STATES:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "A safe harbor election cannot be proposed in the plan "
                       "year's current state")
    body = get_body()
    design = req_enum(body, "design", ELECTION_DESIGNS)
    elected_on = req_date(body, "elected_on")
    for existing in store.safe_harbor_elections.values():
        if (existing["plan_year_id"] == pyid
                and existing["status"] in ("PROPOSED", "EFFECTIVE")):
            raise ApiError(ERR_DUPLICATE, 409,
                           "Only one live (PROPOSED or EFFECTIVE) election is "
                           "allowed per plan year")
    election = new_entity({
        "plan_year_id": pyid, "design": design,
        "elected_on": elected_on.isoformat(),
        "status": "PROPOSED", "suspension_reason": None,
    })
    store.safe_harbor_elections[election["id"]] = election
    bump(py)
    return success_object(election_out(election), status=201)


@bp.route("/ndt/safe-harbor-elections/<eid>", methods=["GET"])
def fetch_election(eid):
    require_roles(READ_ROLES)
    return success_object(election_out(get_election(eid)))


@bp.route("/ndt/safe-harbor-elections/<eid>/suspend", methods=["POST"])
def suspend_election(eid):
    require_roles({ROLE_PLAN_ADMINISTRATOR})
    election = get_election(eid)
    if election["status"] != "EFFECTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an EFFECTIVE election can be suspended")
    py = store.plan_years[election["plan_year_id"]]
    body = get_body()
    expected = body.get("expected_election_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "expected_election_version must be an integer")
        if expected != election["version"]:
            raise ApiError(ERR_STALE_VERSION, 412,
                           "Election version has advanced since the caller's view")
    suspension_reason = opt_string(body, "suspension_reason")
    if not suspension_reason:
        raise ApiError(ERR_ELECTION_LOCKED, 409,
                       "suspension_reason is required to suspend an election")
    if py["status"] == "FILED":
        raise ApiError(ERR_ELECTION_LOCKED, 409,
                       "A safe harbor election cannot be suspended after filing")
    election["suspension_reason"] = suspension_reason
    election["status"] = "SUSPENDED"
    bump(election)
    sh_svc.strip_governing_design(py)
    supersede_terminal_test_runs(py["id"])
    return success_object(election_out(election))


@bp.route("/ndt/safe-harbor-elections/<eid>/revoke", methods=["POST"])
def revoke_election(eid):
    require_roles({ROLE_PLAN_ADMINISTRATOR})
    election = get_election(eid)
    if election["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a PROPOSED election can be revoked")
    election["status"] = "REVOKED"
    bump(election)
    return success_object(election_out(election))


@bp.route("/ndt/safe-harbor-elections/<eid>/notices", methods=["POST"])
def create_notice(eid):
    require_roles({ROLE_PLAN_ADMINISTRATOR})
    election = get_election(eid)
    body = get_body()
    notice_period_start = req_date(body, "notice_period_start")
    notice_period_end = req_date(body, "notice_period_end")
    if not notice_period_start <= notice_period_end:
        raise ApiError(ERR_INVALID_DATE_RANGE, 422,
                       "notice_period_start must be on or before notice_period_end")
    notice = new_entity({
        "election_id": eid,
        "notice_period_start": notice_period_start.isoformat(),
        "notice_period_end": notice_period_end.isoformat(),
        "distributed_at": None,
        "status": "DRAFT",
    })
    store.safe_harbor_notices[notice["id"]] = notice
    return success_object(notice_out(notice), status=201)


@bp.route("/ndt/safe-harbor-elections/<eid>/notice-list", methods=["GET"])
def list_notices(eid):
    require_roles(READ_ROLES)
    get_election(eid)
    limit, offset = pagination_params()
    status = opt_filter(request.args, "status")
    items = [n for n in store.safe_harbor_notices.values()
             if n["election_id"] == eid]
    if status is not None:
        items = [n for n in items if n["status"] == status]
    page, total = page_slice(items, limit, offset)
    return success_list([notice_out(n) for n in page], limit, offset, total)


@bp.route("/ndt/safe-harbor-notices/<nid>", methods=["GET"])
def fetch_notice(nid):
    require_roles(READ_ROLES)
    return success_object(notice_out(get_notice(nid)))


@bp.route("/ndt/safe-harbor-notices/<nid>/distribute", methods=["POST"])
def distribute_notice(nid):
    require_roles({ROLE_PLAN_ADMINISTRATOR})
    notice = get_notice(nid)
    if notice["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a DRAFT notice can be distributed")
    election = store.safe_harbor_elections.get(notice["election_id"])
    py = store.plan_years.get(election["plan_year_id"]) if election else None
    if py is None or not sh_svc.notice_window_valid(notice, py):
        raise ApiError(ERR_NOTICE_WINDOW_CLOSED, 422,
                       "The logical clock is outside the notice window or the "
                       "window fails the notice-timing rule")
    notice["distributed_at"] = clock.now_iso()
    notice["status"] = "DISTRIBUTED"
    bump(notice)
    if election is not None:
        sh_svc.evaluate_election_effectiveness(election)
    return success_object(notice_out(notice))


@bp.route("/ndt/safe-harbor-notices/<nid>/acknowledge", methods=["POST"])
def acknowledge_notice(nid):
    require_roles({ROLE_PLAN_ADMINISTRATOR})
    notice = get_notice(nid)
    if notice["status"] != "DISTRIBUTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a DISTRIBUTED notice can be acknowledged")
    notice["status"] = "ACKNOWLEDGED"
    bump(notice)
    election = store.safe_harbor_elections.get(notice["election_id"])
    if election is not None:
        sh_svc.evaluate_election_effectiveness(election)
    return success_object(notice_out(notice))
