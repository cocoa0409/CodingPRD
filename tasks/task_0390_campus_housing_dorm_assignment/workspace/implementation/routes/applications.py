"""Application routes: create, get, list, submit, withdraw, accept, decline."""

from flask import Blueprint, request

import db
import errors
import response
import common
from middleware import authenticate, require_role
from services import core, lottery

bp = Blueprint("applications", __name__)

ALL_ROLES = ("HousingOfficer", "Student", "ResidentAdvisor")
BUILDING_PREFS = {"TRADITIONAL", "SUITE", "APARTMENT", "NO_PREFERENCE"}
ROOM_PREFS = {"SINGLE", "DOUBLE", "TRIPLE", "SUITE_DOUBLE", "NO_PREFERENCE"}
NON_TERMINAL = {"DRAFT", "SUBMITTED", "OFFERED", "ACCEPTED", "WAITLISTED"}


def _own(principal, student_id):
    """Ownership check for Student-acting endpoints."""
    if principal.user_id != student_id:
        raise errors.forbidden("Caller does not own this resource.")


@bp.route("/applications", methods=["POST"])
def create_application():
    principal = authenticate()
    require_role(principal, ("Student",))
    body = common.get_body()

    common.require_fields(
        body, ["cycle_id", "student_id", "preferred_building_type", "preferred_room_type"]
    )
    cycle_id = body["cycle_id"]
    student_id = body["student_id"]
    pref_bt = common.require_enum(body, "preferred_building_type", BUILDING_PREFS)
    pref_rt = common.require_enum(body, "preferred_room_type", ROOM_PREFS)
    roommate_group_id = body.get("roommate_group_id")

    with db.LOCK:
        # Ownership: a student creates only their own application.
        _own(principal, student_id)
        # Existence (left-to-right): cycle, student, optional group.
        cycle = core.get_or_404(db.housing_cycles, cycle_id)
        student = core.get_or_404(db.students, student_id)
        if roommate_group_id is not None:
            core.get_or_404(db.roommate_groups, roommate_group_id)

        # Duplicate: at most one non-terminal application per cycle.
        for a in db.applications.values():
            if (a["cycle_id"] == cycle_id and a["student_id"] == student_id
                    and a["status"] in NON_TERMINAL):
                raise errors.duplicate_application()

        rec = core.init_record({
            "cycle_id": cycle_id,
            "student_id": student_id,
            "roommate_group_id": roommate_group_id,
            "preferred_building_type": pref_bt,
            "preferred_room_type": pref_rt,
            "priority_rank": None,
            "status": "DRAFT",
            "offered_room_id": None,
            "offer_lottery_index": None,
        })
        db.applications[rec["id"]] = rec
        return response.object_response(core.serialize(rec), status=201)


@bp.route("/applications/<application_id>", methods=["GET"])
def get_application(application_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    with db.LOCK:
        rec = core.get_or_404(db.applications, application_id)
        return response.object_response(core.serialize(rec))


@bp.route("/applications", methods=["GET"])
def list_applications():
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    with db.LOCK:
        limit, offset = common.parse_pagination()
        items = list(db.applications.values())
        for key in ("cycle_id", "student_id", "roommate_group_id", "offered_room_id"):
            val = request.args.get(key)
            if val is not None:
                items = [a for a in items if a.get(key) == val]
        items = common.sort_by_created(items)
        page, total = common.paginate(items, limit, offset)
        return response.array_response(
            [core.serialize(a) for a in page], limit, offset, total
        )


@bp.route("/applications/<application_id>/submit", methods=["POST"])
def submit_application(application_id):
    principal = authenticate()
    require_role(principal, ("Student",))
    with db.LOCK:
        app = core.get_or_404(db.applications, application_id)
        _own(principal, app["student_id"])
        cycle = db.housing_cycles[app["cycle_id"]]
        student = db.students[app["student_id"]]

        if app["status"] != "DRAFT":
            raise errors.invalid_state("Application is not in DRAFT.")
        if cycle["phase"] != "APPLICATION_OPEN":
            raise errors.invalid_state("Cycle is not in APPLICATION_OPEN.")
        # Precondition: roommate group must be LOCKED with student as ACCEPTED member.
        if app["roommate_group_id"] is not None:
            group = db.roommate_groups.get(app["roommate_group_id"])
            if group is None or group["status"] != "LOCKED":
                raise errors.precondition_not_met("Roommate group is not LOCKED.")
            accepted = any(
                m["group_id"] == group["id"]
                and m["student_id"] == app["student_id"]
                and m["membership_status"] == "ACCEPTED"
                for m in db.roommate_memberships.values()
            )
            if not accepted:
                raise errors.precondition_not_met(
                    "Submitting student is not an ACCEPTED member."
                )
        # Hold check.
        if student["status"] == "HOLD":
            raise errors.student_on_hold()

        app["status"] = "SUBMITTED"
        app["priority_rank"] = core.CLASS_YEAR_RANK[student["class_year"]]
        core.touch(app)
        return response.object_response(core.serialize(app))


@bp.route("/applications/<application_id>/withdraw", methods=["POST"])
def withdraw_application(application_id):
    principal = authenticate()
    require_role(principal, ("Student",))
    with db.LOCK:
        app = core.get_or_404(db.applications, application_id)
        _own(principal, app["student_id"])
        cycle = db.housing_cycles[app["cycle_id"]]
        if app["status"] != "SUBMITTED":
            raise errors.invalid_state("Application is not in SUBMITTED.")
        if cycle["phase"] not in ("APPLICATION_OPEN", "LOTTERY_RUN"):
            raise errors.invalid_state("Cycle phase does not allow withdrawal.")
        app["status"] = "WITHDRAWN"
        core.touch(app)
        return response.object_response(core.serialize(app))


@bp.route("/applications/<application_id>/accept", methods=["POST"])
def accept_application(application_id):
    principal = authenticate()
    require_role(principal, ("Student",))
    with db.LOCK:
        app = core.get_or_404(db.applications, application_id)
        _own(principal, app["student_id"])
        body = common.get_body()
        cycle = db.housing_cycles[app["cycle_id"]]
        student = db.students[app["student_id"]]

        # State: must be OFFERED and cycle ASSIGNMENT_OPEN.
        if app["status"] != "OFFERED":
            raise errors.invalid_state("Application is not in OFFERED.")
        if cycle["phase"] != "ASSIGNMENT_OPEN":
            raise errors.invalid_state("Cycle is not in ASSIGNMENT_OPEN.")
        # Precondition: offer not stale.
        if app["offer_lottery_index"] != cycle["lottery_run_index"]:
            raise errors.precondition_not_met("Offer epoch is stale.")
        # Gender compatibility with the offered room.
        room = db.rooms[app["offered_room_id"]]
        if not lottery.gender_compatible(room, student):
            raise errors.gender_incompatible()
        # Hold check.
        if student["status"] == "HOLD":
            raise errors.student_on_hold()
        # OCC: expected_application_version must match (checked last, priority 18).
        common.require_fields(body, ["expected_application_version"])
        expected = body["expected_application_version"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise errors.invalid_request("expected_application_version must be an integer.")
        if expected != app["version"]:
            raise errors.stale_version("expected_application_version does not match.")

        # Mint the assignment (ACTIVE) and the meal plan (STANDARD, ACTIVE).
        app["status"] = "ACCEPTED"
        core.touch(app)

        assignment = core.init_record({
            "room_id": room["id"],
            "student_id": student["id"],
            "application_id": app["id"],
            "swap_counterparty_assignment_id": None,
            "status": "ACTIVE",
            "checkout_total_cents": None,
        })
        db.assignments[assignment["id"]] = assignment

        meal_plan = core.init_record({
            "assignment_id": assignment["id"],
            "tier": "STANDARD",
            "weekly_fee_cents": core.TIER_FEE["STANDARD"],
            "status": "ACTIVE",
        })
        db.meal_plans[meal_plan["id"]] = meal_plan

        # Offer reservation became a live assignment: net room count unchanged,
        # but reconcile to be safe (no-op when unchanged).
        core.reconcile_room(room)
        return response.object_response(core.serialize(app))


@bp.route("/applications/<application_id>/decline", methods=["POST"])
def decline_application(application_id):
    principal = authenticate()
    require_role(principal, ("Student",))
    with db.LOCK:
        app = core.get_or_404(db.applications, application_id)
        _own(principal, app["student_id"])
        cycle = db.housing_cycles[app["cycle_id"]]

        if app["status"] != "OFFERED":
            raise errors.invalid_state("Application is not in OFFERED.")
        if cycle["phase"] != "ASSIGNMENT_OPEN":
            raise errors.invalid_state("Cycle is not in ASSIGNMENT_OPEN.")

        room = db.rooms.get(app["offered_room_id"])
        app["status"] = "DECLINED"
        app["offered_room_id"] = None
        app["offer_lottery_index"] = None
        core.touch(app)
        # Release the bed: reconcile the freed room.
        if room is not None:
            core.reconcile_room(room)
            # Promote the waitlist onto the freed room.
            lottery.promote_waitlist(cycle, room)
        return response.object_response(core.serialize(app))
