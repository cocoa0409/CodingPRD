"""Member endpoints (PRD §3.1, §3.4): enroll, terminate, file-notice, reads."""
from flask import Blueprint, request

from errors import raise_error, ERR_INVALID_STATE, ERR_INVALID_DATE_RANGE
from middleware import authorized
from response import success_object
from routes.helpers import READ_ALL, get_one, list_response
from services.accumulation import applicable_specific_deductible
from services.core import (
    new_record, public, touch, in_force_contracts_for_plan,
)
from util import norm_dt, parse_dt
from validate import (
    get_body, req_str, req_date, req_datetime, opt_datetime,
    require_path_resource, require_ref,
)

bp = Blueprint("members", __name__)


@bp.post("/stop-loss/members")
def create_member():
    authorized(["PlanAdministrator"])
    body = get_body()
    plan_id = req_str(body, "plan_id")
    member_external_id = req_str(body, "member_external_id")
    date_of_birth = req_date(body, "date_of_birth")
    coverage_start = req_datetime(body, "coverage_start")
    coverage_end = opt_datetime(body, "coverage_end", None)

    plan = require_ref("plans", plan_id, "plan_id")
    # Temporal check: coverage_start strictly earlier than coverage_end.
    if coverage_end is not None and not (parse_dt(coverage_start) < parse_dt(coverage_end)):
        raise_error(ERR_INVALID_DATE_RANGE,
                    "coverage_start must be strictly earlier than coverage_end")

    rec = new_record("members", {
        "plan_id": plan_id,
        "member_external_id": member_external_id,
        "date_of_birth": date_of_birth,
        "coverage_start": norm_dt(coverage_start),
        "coverage_end": norm_dt(coverage_end) if coverage_end is not None else None,
        "notice_status": "NONE",
        "status": "ACTIVE",
    })
    # Ledger side effect: an IN_FORCE contract materializes the member's
    # SPECIFIC accumulation row immediately at enrollment.
    for contract in in_force_contracts_for_plan(plan["id"]):
        new_record("accumulations", {
            "contract_id": contract["id"],
            "member_id": rec["id"],
            "scope": "SPECIFIC",
            "accumulated_cents": 0,
            "excess_cents": 0,
            "applicable_deductible_cents": applicable_specific_deductible(
                contract, rec["id"]),
            "notice_triggered": False,
        })
    return success_object(public(rec), status=201)


@bp.get("/stop-loss/members/<rid>")
def get_member(rid):
    return get_one("members", rid, READ_ALL)


@bp.get("/stop-loss/members")
def list_members():
    return list_response("members", READ_ALL,
                         {"plan_id": request.args.get("plan_id")})


@bp.post("/stop-loss/members/<rid>/terminate")
def terminate_member(rid):
    authorized(["PlanAdministrator"])
    body = get_body()
    coverage_end = req_datetime(body, "coverage_end")
    member = require_path_resource("members", rid)
    if member["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE,
                    f"member in {member['status']} cannot be terminated")
    member["coverage_end"] = norm_dt(coverage_end)
    touch(member)
    member["status"] = "TERMINATED"
    return success_object(public(member))


@bp.post("/stop-loss/members/<rid>/file-notice")
def file_notice(rid):
    authorized(["PlanAdministrator"])
    get_body()
    member = require_path_resource("members", rid)
    if member["notice_status"] != "NOTICE_PENDING":
        raise_error(ERR_INVALID_STATE,
                    f"member notice_status is {member['notice_status']}, not NOTICE_PENDING")
    if not in_force_contracts_for_plan(member["plan_id"]):
        raise_error(ERR_INVALID_STATE,
                    "no IN_FORCE contract exists for the member's plan")
    touch(member)
    member["notice_status"] = "NOTICE_FILED"
    return success_object(public(member))
