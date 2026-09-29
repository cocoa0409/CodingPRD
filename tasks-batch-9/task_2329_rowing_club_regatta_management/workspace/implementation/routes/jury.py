"""The jury: protests, deposits, review rounds and remedies."""
from flask import Blueprint

import auth
import calc
import clock
import db
import derive
import helpers
import response
import validate
from errors import fail

bp = Blueprint("jury", __name__)


def _regatta_of_heat(heat):
    return db.regattas.get(heat["regatta_id"])


def _recompute_places(heat_id):
    for lane in derive.recompute_places(heat_id):
        db.touch(lane)


@bp.post("/protests")
@auth.require("Member", "Coach")
def file_protest():
    data = validate.body()
    helpers.check_fk("heat", data, "heat_id")
    helpers.check_fk("member", data, "filed_by_member_id")
    helpers.check_fk("lane", data, "against_race_lane_id")
    heat_id = validate.string(data, "heat_id")
    filer_id = validate.string(data, "filed_by_member_id")
    lane_id = validate.string(data, "against_race_lane_id")
    ground_code = validate.enum(data, "ground_code", calc.GROUND_CODES)
    narrative = validate.string(data, "narrative")

    heat = db.heats[heat_id]
    if heat["status"] != "RESULTS_PROVISIONAL":
        fail("ERR_HEAT_NOT_PROVISIONAL",
             "Heat %s is %s, not RESULTS_PROVISIONAL." % (heat["id"], heat["status"]))

    helpers.member_active(db.members[filer_id], "filing member")

    closes = db.dt(heat, "protest_window_closes_at")
    if closes is None or clock.now() >= closes:
        fail("ERR_PROTEST_WINDOW_CLOSED",
             "The protest window on heat %s is closed." % heat["id"])

    lane = db.lanes[lane_id]
    if lane["heat_id"] != heat_id:
        fail("ERR_LANE_NOT_IN_HEAT",
             "Lane %s does not race in heat %s." % (lane_id, heat_id))

    protest = db.base_record()
    protest["heat_id"] = heat_id
    protest["filed_by_member_id"] = filer_id
    protest["against_race_lane_id"] = lane_id
    protest["ground_code"] = ground_code
    protest["narrative"] = narrative
    db.set_dt(protest, "filed_at", clock.now())
    protest["deposit_cents"] = calc.PROTEST_DEPOSIT_CENTS
    protest["deposit_refunded"] = False
    protest["review_round"] = 0
    protest["jury_user_id"] = None
    protest["status"] = "FILED"
    db.protests[protest["id"]] = protest

    db.touch(_regatta_of_heat(heat))
    return response.created(derive.protest_out(protest))


@bp.get("/protests/<ident>")
@auth.require("ClubAdmin", "Coach", "RaceOfficial", "JuryChair", "Member")
def get_protest(ident):
    protest = helpers.load("protest", ident)
    return response.ok(derive.protest_out(protest))


@bp.get("/protests")
@auth.require("ClubAdmin", "Coach", "RaceOfficial", "JuryChair", "Member")
def list_protests():
    wanted = response.filters("heat_id", "filed_by_member_id",
                              "against_race_lane_id", "status")
    rows = db.ordered(db.protests, lambda p: response.matches(p, wanted))
    return response.paginate(rows, derive.protest_out)


@bp.post("/protests/<ident>/open-review")
@auth.require("JuryChair")
def open_review(ident):
    protest = helpers.load("protest", ident)
    data = validate.body()
    validate.string(data, "note", required=False, nullable=True)

    helpers.not_terminal("protest", protest)

    # Rung 26: conflict-of-interest screening.
    actor = auth.actor_id()
    if actor == protest["filed_by_member_id"]:
        fail("ERR_JURY_CONFLICT_OF_INTEREST",
             "The filer of a protest may not sit on its jury.")
    if protest["status"] == "FILED":
        entry_ids = {lane["regatta_entry_id"] for lane in derive.heat_lanes(protest["heat_id"])
                     if lane["lane_status"] != "VOIDED"}
        for seat in db.seats.values():
            if seat["member_id"] == actor and seat["regatta_entry_id"] in entry_ids:
                fail("ERR_JURY_CONFLICT_OF_INTEREST",
                     "The acting chair is seated in a crew racing this heat.")

    # Rung 48: the two-round ceiling, on reopening a remand.
    if protest["status"] == "REMANDED" and protest["review_round"] >= calc.MAX_JURY_ROUNDS:
        fail("ERR_MAX_JURY_ROUNDS_EXCEEDED",
             "Protest %s has already used its %d review rounds."
             % (protest["id"], calc.MAX_JURY_ROUNDS))

    if protest["status"] not in ("FILED", "REMANDED"):
        helpers.invalid_transition(
            "Only a FILED or REMANDED protest may open a review round; this one is %s."
            % protest["status"])

    protest["review_round"] = protest["review_round"] + 1
    protest["jury_user_id"] = actor
    protest["status"] = "UNDER_JURY_REVIEW"
    db.touch(protest)
    return response.ok(derive.protest_out(protest))


@bp.post("/protests/<ident>/rule")
@auth.require("JuryChair")
def rule_protest(ident):
    protest = helpers.load("protest", ident)
    data = validate.body()
    decision = validate.enum(data, "decision", calc.DECISIONS)
    validate.string(data, "rationale")
    remedy = validate.enum(data, "remedy", calc.REMEDIES,
                           required=(decision == "UPHELD"), nullable=(decision != "UPHELD"),
                           default=None)

    helpers.not_terminal("protest", protest)

    heat = db.heats[protest["heat_id"]]
    if heat["status"] != "RESULTS_PROVISIONAL":
        fail("ERR_HEAT_NOT_PROVISIONAL",
             "Heat %s is %s, not RESULTS_PROVISIONAL." % (heat["id"], heat["status"]))
    if protest["status"] != "UNDER_JURY_REVIEW":
        fail("ERR_PROTEST_NOT_UNDER_REVIEW",
             "Protest %s is %s, not UNDER_JURY_REVIEW." % (protest["id"], protest["status"]))
    if decision == "REMAND" and protest["review_round"] >= calc.MAX_JURY_ROUNDS:
        fail("ERR_MAX_JURY_ROUNDS_EXCEEDED",
             "Protest %s has already used its %d review rounds."
             % (protest["id"], calc.MAX_JURY_ROUNDS))

    lane = db.lanes.get(protest["against_race_lane_id"])

    if decision == "REMAND":
        protest["status"] = "REMANDED"
        db.touch(protest)
    elif decision == "UPHELD":
        protest["status"] = "UPHELD"
        protest["deposit_refunded"] = True
        db.touch(protest)
        db.touch(_regatta_of_heat(heat))
        if remedy == "DISQUALIFY":
            if lane is not None and lane["lane_status"] == "PROVISIONAL":
                lane["lane_status"] = "DISQUALIFIED"
                lane["place"] = None
                db.touch(lane)
            _recompute_places(heat["id"])
        else:
            for other in derive.heat_lanes(heat["id"]):
                if other["lane_status"] != "PROVISIONAL":
                    continue
                other["lane_status"] = "PENDING"
                other["elapsed_seconds"] = None
                other["place"] = None
                db.touch(other)
            db.set_dt(heat, "protest_window_closes_at", None)
            heat["status"] = "LANES_ASSIGNED"
            db.touch(heat)
    else:
        protest["status"] = "DENIED"
        db.touch(protest)
        # A denial can restore a lane an earlier ruling disqualified.
        if lane is not None and lane["lane_status"] == "DISQUALIFIED":
            upheld = any(p["id"] != protest["id"]
                         and p["against_race_lane_id"] == lane["id"]
                         and p["status"] == "UPHELD"
                         for p in db.protests.values())
            if not upheld:
                lane["lane_status"] = "PROVISIONAL"
                db.touch(lane)
                _recompute_places(heat["id"])
    return response.ok(derive.protest_out(protest))


@bp.post("/protests/<ident>/withdraw")
@auth.require("Member")
def withdraw_protest(ident):
    protest = helpers.load("protest", ident)
    if auth.actor_id() != protest["filed_by_member_id"]:
        fail("ERR_UNAUTHORIZED", "Only the filer may withdraw this protest.")

    data = validate.body()
    validate.string(data, "reason")

    helpers.not_terminal("protest", protest)
    if protest["status"] != "FILED":
        helpers.invalid_transition(
            "Only a FILED protest may be withdrawn; this one is %s." % protest["status"])

    protest["status"] = "WITHDRAWN"
    protest["deposit_refunded"] = True
    db.touch(protest)
    heat = db.heats.get(protest["heat_id"])
    if heat is not None:
        db.touch(_regatta_of_heat(heat))
    return response.ok(derive.protest_out(protest))
