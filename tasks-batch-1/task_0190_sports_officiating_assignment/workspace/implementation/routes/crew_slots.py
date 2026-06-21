"""CrewSlot read + offer endpoints (PRD §3.4, §3.5).

GET    /crew-slots/{id}
GET    /crew-slots/{id}/assignments
POST   /crew-slots/{id}/offer   VACANT -> OFFERED (eligibility gauntlet + OCC)
"""
from flask import Blueprint

import db
import lookup
import serialize
from errors import (
    err, ERR_SLOT_NOT_VACANT, ERR_GAME_NOT_OPEN, ERR_STALE_GAME_VERSION,
    ERR_INVALID_REQUEST,
)
from middleware import get_user_context, require_role
from pagination import get_pagination, paginate
from response import object_response, array_response
from services import validate, calc, eligibility

bp = Blueprint("crew_slots", __name__)

READ_ROLES = {"LeagueAdmin", "Assignor", "Official", "Evaluator"}


@bp.route("/crew-slots/<slot_id>", methods=["GET"])
def get_crew_slot(slot_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    with db.lock:
        rec = lookup.crew_slot(slot_id)
        return object_response(serialize.crew_slot(rec))


@bp.route("/crew-slots/<slot_id>/assignments", methods=["GET"])
def list_slot_assignments(slot_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    with db.lock:
        lookup.crew_slot(slot_id)
        rows = [a for a in db.assignments.values() if a["crew_slot_id"] == slot_id]
        page, total = paginate(rows, limit, offset)
        items = [serialize.assignment(r) for r in page]
    return array_response(items, limit, offset, total)


@bp.route("/crew-slots/<slot_id>/offer", methods=["POST"])
def offer_slot(slot_id):
    _, role = get_user_context()
    require_role(role, {"Assignor"})
    data = validate.body()
    with db.lock:
        slot = lookup.crew_slot(slot_id)
        official_id = data.get("official_id")
        if official_id is None:
            err(ERR_INVALID_REQUEST, "official_id is required")
        official = lookup.official(official_id)
        game = lookup.game(slot["game_id"])
        # State gates (priority 4 group): slot VACANT, game OPEN.
        if slot["status"] != "VACANT":
            err(ERR_SLOT_NOT_VACANT, "slot is not VACANT")
        if game["status"] != "OPEN":
            err(ERR_GAME_NOT_OPEN, "game is not OPEN")
        # Business eligibility gauntlet (priorities 6-12, PRD §3.4 order).
        distance_miles = eligibility.run_offer_gauntlet(official, slot, game)
        # OCC on game version (priority 15).
        if "expected_game_version" not in data or data["expected_game_version"] is None:
            err(ERR_INVALID_REQUEST, "expected_game_version is required")
        expected = data["expected_game_version"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            err(ERR_INVALID_REQUEST, "expected_game_version must be an integer")
        if expected != game["version"]:
            err(ERR_STALE_GAME_VERSION, "game version mismatch")
        # Create the Assignment in OFFERED with frozen distance + provisional pay.
        league = db.leagues.get(game["league_id"])
        mileage = calc.mileage_cents(distance_miles,
                                     league["mileage_rate_cents_per_mile"])
        provisional = calc.provisional_game_pay(
            official["rank"], league["base_game_fee_cents"],
            slot["slot_fee_multiplier"], bool(game.get("is_postseason")),
            distance_miles, league["mileage_rate_cents_per_mile"])
        assignment = {
            "crew_slot_id": slot_id,
            "game_id": game["id"],
            "official_id": official_id,
            "status": "OFFERED",
            "distance_miles": distance_miles,
            "provisional_pay_cents": provisional,
            "final_pay_cents": 0,
            "mileage_cents": mileage,
            "penalty_assessed_points": 0,
        }
        db.stamp_create(assignment)
        db.assignments[assignment["id"]] = assignment
        slot["current_assignment_id"] = assignment["id"]
        slot["status"] = "OFFERED"
        db.touch(slot)
        # Offer increments the game's version by one (PRD §3.4).
        db.touch(game)
        return object_response(serialize.assignment(assignment), 201)
