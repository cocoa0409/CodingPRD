"""Assignments: read, acceptance by the servicing carrier and rescission by the plan."""

from flask import Blueprint, request

import calc
import domain
import guards
from envelope import ok, ok_list
from errors import fail
from store import db, touch

bp = Blueprint("assignments", __name__)

READ_ROLES = (
    "PlanAdministrator",
    "ComplianceExaminer",
    "ServicingCarrier",
    "ProducerAgent",
)
RESCISSION_REASONS = ("ISSUANCE_DEADLINE_MISSED", "CARRIER_INELIGIBLE", "ASSIGNMENT_ERROR")


@bp.get("/plan/assignments")
def list_assignments():
    guards.authenticate(READ_ROLES)
    limit, offset = guards.pagination()
    application_id = request.args.get("application_id")
    carrier_id = request.args.get("carrier_id")
    assignment_cycle_id = request.args.get("assignment_cycle_id")
    predecessor_assignment_id = request.args.get("predecessor_assignment_id")
    status = request.args.get("status")

    rows = list(db.assignments.values())
    if application_id is not None:
        rows = [r for r in rows if r["application_id"] == application_id]
    if carrier_id is not None:
        rows = [r for r in rows if r["carrier_id"] == carrier_id]
    if assignment_cycle_id is not None:
        rows = [r for r in rows if r["assignment_cycle_id"] == assignment_cycle_id]
    if predecessor_assignment_id is not None:
        rows = [
            r for r in rows if r["predecessor_assignment_id"] == predecessor_assignment_id
        ]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    rows = domain.sort_assignments(rows)
    page, total = domain.paginate(rows, limit, offset)
    return ok_list([domain.assignment_out(r) for r in page], limit, offset, total)


@bp.get("/plan/assignments/<assignment_id>")
def read_assignment(assignment_id):
    guards.authenticate(READ_ROLES)
    assignment = guards.need_assignment(assignment_id)
    return ok(domain.assignment_out(assignment))


def _reassigned_policy(assignment):
    predecessor_id = assignment["predecessor_assignment_id"]
    for policy in db.policies.values():
        if policy["_current_assignment_id"] == predecessor_id:
            return policy
    for policy in db.policies.values():
        if (
            policy["_application_id"] == assignment["application_id"]
            and policy["policy_status"] == "REASSIGNMENT_PENDING"
        ):
            return policy
    return None


@bp.post("/plan/assignments/<assignment_id>/acceptance")
def accept_assignment(assignment_id):
    user_id, role = guards.authenticate(("ServicingCarrier",))
    guards.body()
    assignment = guards.need_assignment(assignment_id)
    guards.carrier_scope(role, user_id, assignment["carrier_id"])

    if assignment["status"] != "PENDING_ACCEPTANCE":
        fail("ERR_INVALID_ASSIGNMENT_STATE")
    carrier = db.carriers[assignment["carrier_id"]]
    if domain.carrier_posture(carrier) == "SUSPENDED":
        fail("ERR_CARRIER_SUSPENDED")
    if db.clock > assignment["acceptance_deadline"]:
        fail("ERR_ACCEPTANCE_WINDOW_EXPIRED")

    assignment["accepted_at"] = db.clock

    if assignment["assignment_kind"] == "INITIAL":
        assignment["status"] = "ACCEPTED"
        touch(assignment)
        return ok(domain.assignment_out(assignment))

    # A reassignment lands on POLICY_ISSUED directly: the policy already exists.
    assignment["status"] = "POLICY_ISSUED"
    touch(assignment)
    policy = _reassigned_policy(assignment)
    if policy is not None:
        policy["carrier_id"] = carrier["id"]
        policy["policy_status"] = "IN_FORCE"
        policy["reassignment_required"] = False
        policy["_current_assignment_id"] = assignment["id"]
        touch(policy)
    predecessor = db.assignments.get(assignment["predecessor_assignment_id"])
    if predecessor is not None:
        predecessor["status"] = "REASSIGNED"
        touch(predecessor)
        old_carrier = db.carriers.get(predecessor["carrier_id"])
        touch(old_carrier)
        domain.bubble_exit_complete(old_carrier)
    touch(carrier)
    return ok(domain.assignment_out(assignment))


@bp.post("/plan/assignments/<assignment_id>/rescission")
def rescind_assignment(assignment_id):
    guards.authenticate(("PlanAdministrator",))
    data = guards.body()
    reason_code = guards.req_enum(data, "reason_code", RESCISSION_REASONS)
    assignment = guards.need_assignment(assignment_id)

    if assignment["status"] not in ("PENDING_ACCEPTANCE", "ACCEPTED"):
        fail("ERR_INVALID_ASSIGNMENT_STATE")
    if (
        reason_code == "ISSUANCE_DEADLINE_MISSED"
        and db.clock <= assignment["acceptance_deadline"]
    ):
        fail(
            "ERR_INVALID_ASSIGNMENT_STATE",
            "The acceptance deadline has not passed, so it cannot have been missed.",
        )

    assignment["status"] = "RESCINDED"
    assignment["rescission_reason_code"] = reason_code
    touch(assignment)

    application = db.applications.get(assignment["application_id"])
    if application is not None:
        application["status"] = "CERTIFIED_AWAITING_ASSIGNMENT"
        touch(application)

    carrier = db.carriers.get(assignment["carrier_id"])
    if carrier is not None:
        touch(carrier)
        if reason_code == "ISSUANCE_DEADLINE_MISSED":
            domain.adjust_score(carrier, -calc.MISSED_ISSUANCE_DEDUCTION)
            domain.apply_suspension_cascade(carrier)
    return ok(domain.assignment_out(assignment))
