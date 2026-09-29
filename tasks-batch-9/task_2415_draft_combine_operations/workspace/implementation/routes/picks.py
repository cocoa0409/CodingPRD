"""Draft picks: reads, selections and the four clock actions (PRD 3.5, 3.7)."""

from flask import Blueprint

import auth
import constants as K
import derive
import logic
import respond
import validate
from db import db
from errors import ApiError
from timeutil import add_minutes

bp = Blueprint("picks", __name__)

READ_ROLES = ["LeagueDraftAdmin", "ClubGM", "ProspectAgent"]

CLOCK_ACTION_ROLES = {
    "PASS": ("ClubGM",),
    "TIMEOUT": ("ClubGM",),
    "FORFEIT": ("LeagueDraftAdmin",),
    "AUTHORIZE_OUT_OF_ORDER": ("LeagueDraftAdmin",),
}


@bp.get("/draft-picks/<pick_id>")
def get_pick(pick_id):
    auth.begin(READ_ROLES)
    return respond.one(logic.path_lookup(db.draft_picks, pick_id))


@bp.get("/draft-picks")
def list_picks():
    auth.begin(READ_ROLES)
    limit, offset = validate.pagination()
    cycle_id = validate.query_str("draft_cycle_id")
    owning_club_id = validate.query_str("owning_club_id")
    original_club_id = validate.query_str("original_club_id")
    selected_prospect_id = validate.query_str("selected_prospect_id")
    round_number = validate.query_int("round_number", minimum=1, maximum=7)
    status = validate.query_enum("status", K.PICK_STATUSES)

    rows = list(db.draft_picks.values())
    if cycle_id is not None:
        rows = [r for r in rows if r["draft_cycle_id"] == cycle_id]
    if owning_club_id is not None:
        rows = [r for r in rows if r["owning_club_id"] == owning_club_id]
    if original_club_id is not None:
        rows = [r for r in rows if r["original_club_id"] == original_club_id]
    if selected_prospect_id is not None:
        rows = [r for r in rows if r["selected_prospect_id"] == selected_prospect_id]
    if round_number is not None:
        rows = [r for r in rows if r["round_number"] == round_number]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return respond.listing(logic.by_overall(rows), limit, offset)


@bp.post("/draft-picks/<pick_id>/selections")
def make_selection(pick_id):
    user_id, role = auth.begin(["ClubGM"])
    data = validate.body()
    prospect_id = validate.string(data, "prospect_id")
    ack = validate.boolean(data, "out_of_order_ack", required=False, default=False)

    pick = logic.path_lookup(db.draft_picks, pick_id)
    prospect = logic.fk_lookup(db.prospects, prospect_id, "prospect")
    logic.own_club(role, user_id, pick["owning_club_id"])

    cycle = db.draft_cycles.get(pick["draft_cycle_id"])
    logic.require_phase(cycle, ("DRAFT_LIVE",))
    logic.require_unfrozen(cycle)

    source = pick["status"]
    if source not in ("ON_CLOCK", "PASSED", "PENDING"):
        raise logic.invalid_transition(
            "A %s pick may not be used for a selection." % source
        )

    if source == "ON_CLOCK":
        if pick["deadline_at"] is None or db.now >= pick["deadline_at"]:
            raise ApiError(
                "ERR_CLOCK_ALREADY_EXPIRED", "The selection clock has already expired."
            )

    if (
        prospect["eligibility_status"] != "ELIGIBLE"
        or prospect["medical_clearance_status"] == "FAILED"
        or prospect["declaration_status"] != "DECLARED"
        or prospect["drafted_pick_overall_number"] != 0
    ):
        raise ApiError(
            "ERR_PROSPECT_NOT_SELECTABLE", "This prospect may not be selected."
        )

    if source == "PENDING":
        holder = derive.on_clock_pick(cycle["id"])
        if (
            not pick["out_of_order_authorized"]
            or not ack
            or holder is None
            or holder["id"] == pick["id"]
        ):
            raise ApiError(
                "ERR_OUT_OF_ORDER_NOT_AUTHORIZED",
                "This pick is not authorized for an out-of-order selection.",
            )

    pick["status"] = "USED"
    pick["selected_prospect_id"] = prospect["id"]
    prospect["drafted_pick_overall_number"] = pick["overall_number"]

    if source == "ON_CLOCK":
        pick["selection_source"] = "ON_TIME"
        logic.leave_clock(pick)
        logic.advance_after_use(cycle, db.now)
    elif source == "PASSED":
        pick["selection_source"] = "AFTER_PASS"
        pick["pass_reason"] = None
    else:
        pick["selection_source"] = "OUT_OF_ORDER"
    return respond.ok(pick)


@bp.post("/draft-picks/<pick_id>/clock-action")
def clock_action(pick_id):
    user_id, role = auth.actor()
    auth.require(role, ["ClubGM", "LeagueDraftAdmin"])
    auth.require_action_role(role, validate.peek("action"), CLOCK_ACTION_ROLES)

    data = validate.body()
    action = validate.enum(
        data, "action", ("PASS", "TIMEOUT", "FORFEIT", "AUTHORIZE_OUT_OF_ORDER")
    )
    pick = logic.path_lookup(db.draft_picks, pick_id)
    logic.own_club(role, user_id, pick["owning_club_id"])

    cycle = db.draft_cycles.get(pick["draft_cycle_id"])
    if action == "FORFEIT":
        logic.require_phase(cycle, ("ORDER_FINAL", "DRAFT_LIVE"))
    else:
        logic.require_phase(cycle, ("DRAFT_LIVE",))
    logic.require_unfrozen(cycle)

    if action in ("PASS", "TIMEOUT"):
        if pick["status"] != "ON_CLOCK":
            raise logic.invalid_transition(
                "Only a pick on the clock may be passed or paused."
            )
        if pick["deadline_at"] is None or db.now >= pick["deadline_at"]:
            raise ApiError(
                "ERR_CLOCK_ALREADY_EXPIRED", "The selection clock has already expired."
            )
        if action == "PASS":
            pick["status"] = "PASSED"
            pick["pass_reason"] = "VOLUNTARY"
            logic.leave_clock(pick)
            logic.advance_after_use(cycle, db.now)
            return respond.ok(pick)

        club = db.clubs.get(pick["owning_club_id"])
        if club is None or club["timeouts_remaining"] <= 0:
            raise ApiError(
                "ERR_NO_TIMEOUTS_REMAINING",
                "The owning club has no timeouts remaining.",
            )
        pick["deadline_at"] = add_minutes(
            pick["deadline_at"], K.TIMEOUT_EXTENSION_MINUTES
        )
        pick["timeouts_used"] += 1
        club["timeouts_remaining"] -= 1
        return respond.ok(pick)

    if action == "FORFEIT":
        if pick["status"] != "PENDING":
            raise logic.invalid_transition("Only a PENDING pick may be forfeited.")
        logic.forfeit_pick(cycle, pick)
        return respond.ok(pick)

    # AUTHORIZE_OUT_OF_ORDER
    if pick["status"] != "PENDING":
        raise logic.invalid_transition(
            "Only a PENDING pick may be authorized out of order."
        )
    if pick["out_of_order_authorized"]:
        raise logic.invalid_transition(
            "This pick is already authorized for an out-of-order selection."
        )
    pick["out_of_order_authorized"] = True
    return respond.ok(pick)
