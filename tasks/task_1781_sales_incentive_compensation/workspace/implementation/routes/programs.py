"""Program routes: create, get, close-period, payroll-exports listing."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_NOT_FOUND,
    ERR_OPEN_DISPUTES_EXIST,
    ERR_STALE_PROGRAM_VERSION,
)
from middleware import authorized
from response import success_object, success_list
from util import new_entity, touch, serialize
from validate import get_body, req_str, req_int, parse_pagination, require_path_resource
from services.calculations import period_settlement, recompute_assignment_indicators

bp = Blueprint("programs", __name__)

ADMIN_ONLY = ["CompAdmin"]
ALL_ROLES = ["CompAdmin", "CompAnalyst", "CompManager", "Rep"]


@bp.route("/programs", methods=["POST"])
def create_program():
    caller = authorized(ADMIN_ONLY)
    body = get_body()
    name = req_str(body, "name")

    program = new_entity({
        "name": name,
        "current_period_index": 1,
        "accrued_balance_cents": 0,
    })
    db["programs"][program["id"]] = program
    return success_object(serialize(program), 201)


@bp.route("/programs/<programId>", methods=["GET"])
def get_program(programId):
    caller = authorized(ALL_ROLES)
    program = require_path_resource("programs", programId)
    return success_object(serialize(program))


@bp.route("/programs/<programId>/close-period", methods=["POST"])
def close_period(programId):
    caller = authorized(ADMIN_ONLY)
    body = get_body()
    program = require_path_resource("programs", programId)

    expected_program_version = req_int(body, "expected_program_version")

    # Business guard: open disputes block close (before OCC per concurrency_rules)
    open_disputes = [
        d for d in db["disputes"].values()
        if d["status"] in ("SUBMITTED", "UNDER_REVIEW")
        and _dispute_in_program(d, programId)
    ]
    if open_disputes:
        raise_error(ERR_OPEN_DISPUTES_EXIST,
                    "open disputes exist in this program")

    # OCC check (after business guards per concurrency_rules)
    if expected_program_version != program["version"]:
        raise_error(ERR_STALE_PROGRAM_VERSION,
                    f"expected_program_version {expected_program_version} != current {program['version']}")

    closing_period = program["current_period_index"]

    # Generate DRAFT statements per ACTIVE assignment
    active_assignments = [
        a for a in db["assignments"].values()
        if a["program_id"] == programId and a["status"] == "ACTIVE"
    ]
    total_net_payable = 0
    for assignment in active_assignments:
        stmt = period_settlement(assignment, program, closing_period)
        total_net_payable += stmt["net_payable_cents"]

    # Lock POSTED credits of the closing period
    for entry in db["credit_entries"].values():
        if (entry["status"] == "POSTED"
                and entry["posted_period_index"] == closing_period
                and _entry_in_program(entry, programId)):
            entry["status"] = "LOCKED"
            touch(entry)

    # Reset earned counters per settled assignment, then refresh the live
    # indicators: PENDING credits survive the close and still count toward
    # the provisional estimate (earned reset alone does not zero it).
    for assignment in active_assignments:
        assignment["current_period_earned_cents"] = 0
        assignment["_rollup_earned_cents"] = 0
        touch(assignment)
        recompute_assignment_indicators(assignment)

    # Advance program
    program["current_period_index"] += 1
    program["accrued_balance_cents"] += total_net_payable
    touch(program)

    return success_object(serialize(program))


@bp.route("/programs/<id>/payroll-exports", methods=["GET"])
def list_payroll_exports(id):
    caller = authorized(ALL_ROLES)
    program = require_path_resource("programs", id)
    limit, offset = parse_pagination()

    items = [
        e for e in db["payroll_exports"].values()
        if e["program_id"] == id
    ]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(e) for e in page], total, limit, offset)


def _dispute_in_program(dispute, program_id):
    """Check if a dispute belongs to the given program (via assignment)."""
    asg = db["assignments"].get(dispute["assignment_id"])
    return asg is not None and asg["program_id"] == program_id


def _entry_in_program(entry, program_id):
    """Check if a credit entry belongs to the given program (via assignment)."""
    asg = db["assignments"].get(entry["assignment_id"])
    return asg is not None and asg["program_id"] == program_id
