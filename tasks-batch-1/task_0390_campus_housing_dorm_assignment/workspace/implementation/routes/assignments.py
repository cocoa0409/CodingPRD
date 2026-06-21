"""Assignment routes: get, list, propose/confirm/cancel swap, vacate, check-out."""

from flask import Blueprint, request

import db
import errors
import response
import common
from middleware import authenticate, require_role
from services import core, lottery

bp = Blueprint("assignments", __name__)

ALL_ROLES = ("HousingOfficer", "Student", "ResidentAdvisor")


def _own(principal, student_id):
    if principal.user_id != student_id:
        raise errors.forbidden("Caller does not own this assignment.")


@bp.route("/assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    with db.LOCK:
        rec = core.get_or_404(db.assignments, assignment_id)
        return response.object_response(core.serialize(rec))


@bp.route("/assignments", methods=["GET"])
def list_assignments():
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    with db.LOCK:
        limit, offset = common.parse_pagination()
        items = list(db.assignments.values())
        for key in ("room_id", "student_id", "application_id",
                    "swap_counterparty_assignment_id"):
            val = request.args.get(key)
            if val is not None:
                items = [a for a in items if a.get(key) == val]
        items = common.sort_by_created(items)
        page, total = common.paginate(items, limit, offset)
        return response.array_response(
            [core.serialize(a) for a in page], limit, offset, total
        )


@bp.route("/assignments/<assignment_id>/propose-swap", methods=["POST"])
def propose_swap(assignment_id):
    principal = authenticate()
    require_role(principal, ("Student",))
    with db.LOCK:
        assignment = core.get_or_404(db.assignments, assignment_id)
        _own(principal, assignment["student_id"])
        body = common.get_body()
        common.require_fields(body, ["counterparty_assignment_id"])
        counterparty_id = body["counterparty_assignment_id"]
        counterparty = core.get_or_404(db.assignments, counterparty_id)

        cycle = _cycle_for_assignment(assignment)

        # State: this assignment must be ACTIVE.
        if assignment["status"] != "ACTIVE":
            raise errors.invalid_state("Assignment is not ACTIVE.")
        # Precondition: cycle ASSIGNMENT_OPEN, counterparty exists and ACTIVE.
        if cycle is None or cycle["phase"] != "ASSIGNMENT_OPEN":
            raise errors.precondition_not_met("Cycle is not in ASSIGNMENT_OPEN.")
        if counterparty["status"] != "ACTIVE":
            raise errors.precondition_not_met("Counterparty assignment is not ACTIVE.")

        # Gender compatibility: each student must fit the room they would move
        # into, excluding the resident currently leaving that room.
        this_student = db.students[assignment["student_id"]]
        other_student = db.students[counterparty["student_id"]]
        this_room = db.rooms[assignment["room_id"]]
        other_room = db.rooms[counterparty["room_id"]]
        if not lottery.gender_compatible(
            other_room, this_student, exclude_student_id=other_student["id"]
        ):
            raise errors.gender_incompatible()
        if not lottery.gender_compatible(
            this_room, other_student, exclude_student_id=this_student["id"]
        ):
            raise errors.gender_incompatible()

        assignment["status"] = "SWAP_PENDING"
        assignment["swap_counterparty_assignment_id"] = counterparty["id"]
        core.touch(assignment)
        counterparty["status"] = "SWAP_PENDING"
        counterparty["swap_counterparty_assignment_id"] = assignment["id"]
        core.touch(counterparty)
        return response.object_response(core.serialize(assignment))


@bp.route("/assignments/<assignment_id>/confirm-swap", methods=["POST"])
def confirm_swap(assignment_id):
    principal = authenticate()
    require_role(principal, ("Student",))
    with db.LOCK:
        assignment = core.get_or_404(db.assignments, assignment_id)
        _own(principal, assignment["student_id"])
        body = common.get_body()

        if assignment["status"] != "SWAP_PENDING" or not assignment["swap_counterparty_assignment_id"]:
            raise errors.invalid_state("Assignment is not a confirmable SWAP_PENDING leg.")
        counterparty = db.assignments.get(assignment["swap_counterparty_assignment_id"])
        if counterparty is None:
            raise errors.invalid_state("Counterparty assignment missing.")

        # OCC: expected_assignment_version must match this assignment's version.
        common.require_fields(body, ["expected_assignment_version"])
        expected = body["expected_assignment_version"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise errors.invalid_request("expected_assignment_version must be an integer.")
        if expected != assignment["version"]:
            raise errors.stale_version("expected_assignment_version does not match.")

        # Exchange rooms.
        room_a = db.rooms.get(assignment["room_id"])
        room_b = db.rooms.get(counterparty["room_id"])
        assignment["room_id"], counterparty["room_id"] = (
            counterparty["room_id"], assignment["room_id"]
        )
        assignment["status"] = "ACTIVE"
        assignment["swap_counterparty_assignment_id"] = None
        core.touch(assignment)
        counterparty["status"] = "ACTIVE"
        counterparty["swap_counterparty_assignment_id"] = None
        core.touch(counterparty)

        # Re-derive both rooms' status (bed counts unchanged in total).
        for room in {id(room_a): room_a, id(room_b): room_b}.values():
            if room is not None:
                core.reconcile_room(room)
        return response.object_response(core.serialize(assignment))


@bp.route("/assignments/<assignment_id>/cancel-swap", methods=["POST"])
def cancel_swap(assignment_id):
    principal = authenticate()
    require_role(principal, ("Student",))
    with db.LOCK:
        assignment = core.get_or_404(db.assignments, assignment_id)
        if assignment["status"] != "SWAP_PENDING" or not assignment["swap_counterparty_assignment_id"]:
            # Resolve ownership before reporting state for a clean error order:
            # either party may cancel, so we must look at the counterparty too.
            _own_either(principal, assignment, None)
            raise errors.invalid_state("Assignment is not in SWAP_PENDING.")
        counterparty = db.assignments.get(assignment["swap_counterparty_assignment_id"])
        _own_either(principal, assignment, counterparty)

        assignment["status"] = "ACTIVE"
        assignment["swap_counterparty_assignment_id"] = None
        core.touch(assignment)
        if counterparty is not None:
            counterparty["status"] = "ACTIVE"
            counterparty["swap_counterparty_assignment_id"] = None
            core.touch(counterparty)
        return response.object_response(core.serialize(assignment))


@bp.route("/assignments/<assignment_id>/vacate", methods=["POST"])
def vacate_assignment(assignment_id):
    principal = authenticate()
    require_role(principal, ("HousingOfficer",))
    with db.LOCK:
        assignment = core.get_or_404(db.assignments, assignment_id)
        if assignment["status"] != "ACTIVE":
            raise errors.invalid_state("Assignment is not ACTIVE.")
        assignment["status"] = "VACATED"
        core.touch(assignment)
        room = db.rooms.get(assignment["room_id"])
        if room is not None:
            core.reconcile_room(room)
        _cancel_meal_plan(assignment["id"])
        return response.object_response(core.serialize(assignment))


@bp.route("/assignments/<assignment_id>/check-out", methods=["POST"])
def check_out_assignment(assignment_id):
    principal = authenticate()
    require_role(principal, ("HousingOfficer",))
    with db.LOCK:
        assignment = core.get_or_404(db.assignments, assignment_id)
        if assignment["status"] not in ("ACTIVE", "VACATED"):
            raise errors.invalid_state("Assignment is not ACTIVE or VACATED.")
        # Blocked while any PENDING charge remains.
        for c in db.damage_charges.values():
            if c["assignment_id"] == assignment["id"] and c["status"] == "PENDING":
                raise errors.unsettled_charges()

        was_active = assignment["status"] == "ACTIVE"
        # checkout_total_cents = sum of amount_cents on BILLED/PAID charges.
        total = 0
        for c in db.damage_charges.values():
            if c["assignment_id"] == assignment["id"] and c["status"] in ("BILLED", "PAID"):
                total += c["amount_cents"] or 0
        assignment["checkout_total_cents"] = total
        assignment["status"] = "CHECKED_OUT"
        core.touch(assignment)

        if was_active:
            room = db.rooms.get(assignment["room_id"])
            if room is not None:
                core.reconcile_room(room)
            _cancel_meal_plan(assignment["id"])
        return response.object_response(core.serialize(assignment))


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _cycle_for_assignment(assignment):
    app = db.applications.get(assignment["application_id"])
    if app is None:
        return None
    return db.housing_cycles.get(app["cycle_id"])


def _own_either(principal, assignment, counterparty):
    """Allow if caller owns either leg of the swap."""
    ids = {assignment["student_id"]}
    if counterparty is not None:
        ids.add(counterparty["student_id"])
    if principal.user_id not in ids:
        raise errors.forbidden("Caller does not own either swap leg.")


def _cancel_meal_plan(assignment_id):
    for mp in db.meal_plans.values():
        if mp["assignment_id"] == assignment_id and mp["status"] == "ACTIVE":
            mp["status"] = "CANCELLED"
            core.touch(mp)
