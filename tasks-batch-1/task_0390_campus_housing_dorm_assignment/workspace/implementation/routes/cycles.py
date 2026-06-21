"""Housing cycle routes (create, get, run-lottery, open-assignment, close)."""

from flask import Blueprint

import db
import errors
import response
import common
from middleware import authenticate, require_role
from services import core, lottery

bp = Blueprint("cycles", __name__)

ALL_ROLES = ("HousingOfficer", "Student", "ResidentAdvisor")


@bp.route("/housing-cycles", methods=["POST"])
def create_cycle():
    principal = authenticate()
    require_role(principal, ("HousingOfficer",))
    body = common.get_body()
    common.require_fields(body, ["term_label"])
    with db.LOCK:
        rec = core.init_record({
            "term_label": body["term_label"],
            "phase": "APPLICATION_OPEN",
            "lottery_run_index": 0,
        })
        db.housing_cycles[rec["id"]] = rec
        return response.object_response(core.serialize(rec), status=201)


@bp.route("/housing-cycles/<cycle_id>", methods=["GET"])
def get_cycle(cycle_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    with db.LOCK:
        rec = core.get_or_404(db.housing_cycles, cycle_id)
        return response.object_response(core.serialize(rec))


@bp.route("/housing-cycles/<cycle_id>/run-lottery", methods=["POST"])
def run_lottery(cycle_id):
    principal = authenticate()
    require_role(principal, ("HousingOfficer",))
    with db.LOCK:
        cycle = core.get_or_404(db.housing_cycles, cycle_id)
        if cycle["phase"] != "APPLICATION_OPEN":
            raise errors.invalid_state("Cycle is not in APPLICATION_OPEN.")
        cycle["phase"] = "LOTTERY_RUN"
        cycle["lottery_run_index"] += 1
        core.touch(cycle)
        lottery.run_lottery(cycle)
        return response.object_response(core.serialize(cycle))


@bp.route("/housing-cycles/<cycle_id>/open-assignment", methods=["POST"])
def open_assignment(cycle_id):
    principal = authenticate()
    require_role(principal, ("HousingOfficer",))
    with db.LOCK:
        cycle = core.get_or_404(db.housing_cycles, cycle_id)
        if cycle["phase"] != "LOTTERY_RUN":
            raise errors.invalid_state("Cycle is not in LOTTERY_RUN.")
        cycle["phase"] = "ASSIGNMENT_OPEN"
        core.touch(cycle)
        return response.object_response(core.serialize(cycle))


@bp.route("/housing-cycles/<cycle_id>/close", methods=["POST"])
def close_cycle(cycle_id):
    principal = authenticate()
    require_role(principal, ("HousingOfficer",))
    with db.LOCK:
        cycle = core.get_or_404(db.housing_cycles, cycle_id)
        if cycle["phase"] != "ASSIGNMENT_OPEN":
            raise errors.invalid_state("Cycle is not in ASSIGNMENT_OPEN.")
        cycle["phase"] = "CLOSED"
        core.touch(cycle)
        # Cascade: expire outstanding OFFERED applications, release their beds.
        offered = [
            a for a in db.applications.values()
            if a["cycle_id"] == cycle["id"] and a["status"] == "OFFERED"
        ]
        for app in offered:
            room = db.rooms.get(app["offered_room_id"])
            app["status"] = "EXPIRED"
            app["offered_room_id"] = None
            app["offer_lottery_index"] = None
            core.touch(app)
            if room is not None:
                core.reconcile_room(room)
        return response.object_response(core.serialize(cycle))
