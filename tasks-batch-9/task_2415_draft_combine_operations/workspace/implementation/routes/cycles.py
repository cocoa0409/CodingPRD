"""Draft cycle endpoints (PRD 3.1, 3.3, 3.5, 3.7)."""

from flask import Blueprint

import auth
import calc
import constants as K
import derive
import logic
import respond
import validate
from db import db

bp = Blueprint("cycles", __name__)

ALL_ROLES = list(K.ROLES)


@bp.post("/draft-cycles")
def create_cycle():
    auth.begin(["LeagueDraftAdmin"])
    data = validate.body()
    season_year = validate.integer(data, "season_year", minimum=2000, maximum=2100)
    declaration_deadline_at = validate.instant(data, "declaration_deadline_at")
    combine_week_start_at = validate.instant(data, "combine_week_start_at")
    combine_week_end_at = validate.instant(data, "combine_week_end_at")
    draft_start_at = validate.instant(data, "draft_start_at")
    rounds_count = validate.integer(
        data, "rounds_count", required=False, minimum=1, maximum=7
    )
    compressed_final_day = validate.boolean(
        data, "compressed_final_day", required=False, default=False
    )
    if combine_week_end_at <= combine_week_start_at:
        validate.bad("combine_week_end_at must be strictly after combine_week_start_at.")
    if draft_start_at <= combine_week_end_at:
        validate.bad("draft_start_at must be strictly after combine_week_end_at.")

    rec = db.insert(
        db.draft_cycles,
        "DraftCycle",
        {
            "season_year": season_year,
            "declaration_deadline_at": declaration_deadline_at,
            "combine_week_start_at": combine_week_start_at,
            "combine_week_end_at": combine_week_end_at,
            "draft_start_at": draft_start_at,
            "rounds_count": 7 if rounds_count is None else rounds_count,
            "compressed_final_day": bool(compressed_final_day),
            "status": "SETUP",
            "lottery_completed": False,
            "lottery_slot_club_ids": [],
            "order_finalized_at": None,
            "udfa_window_close_at": None,
        },
    )
    return respond.created(rec)


@bp.get("/draft-cycles/<cycle_id>")
def get_cycle(cycle_id):
    auth.begin(ALL_ROLES)
    return respond.one(logic.path_lookup(db.draft_cycles, cycle_id))


@bp.post("/draft-cycles/<cycle_id>/phase")
def set_phase(cycle_id):
    auth.begin(["LeagueDraftAdmin"])
    data = validate.body()
    target = validate.enum(data, "target_status", K.CYCLE_STATUSES)
    cycle = logic.path_lookup(db.draft_cycles, cycle_id)
    logic.apply_phase(cycle, target)
    return respond.ok(cycle)


@bp.post("/draft-cycles/<cycle_id>/lottery")
def run_lottery(cycle_id):
    auth.begin(["LeagueDraftAdmin"])
    data = validate.body()
    sequence = validate.int_list(data, "drawn_combination_sequence")
    cycle = logic.path_lookup(db.draft_cycles, cycle_id)
    logic.require_phase(cycle, ("ORDER_PENDING",))
    logic.require_unfrozen(cycle)
    if cycle["lottery_completed"]:
        raise logic.invalid_transition("The lottery has already been run.")
    if derive.club_count(cycle["id"]) < 2:
        raise logic.invalid_transition("At least two registered clubs are required.")
    logic.run_lottery(cycle, sequence)
    return respond.ok(cycle)


@bp.post("/draft-cycles/<cycle_id>/draft-order/finalize")
def finalize_order(cycle_id):
    auth.begin(["LeagueDraftAdmin"])
    validate.body()
    cycle = logic.path_lookup(db.draft_cycles, cycle_id)
    logic.require_phase(cycle, ("ORDER_PENDING",))
    logic.require_unfrozen(cycle)
    if not cycle["lottery_completed"]:
        raise logic.invalid_transition("The lottery has not been run yet.")
    if cycle["order_finalized_at"] is not None:
        raise logic.invalid_transition("The draft order has already been minted.")
    result = logic.finalize_order(cycle)
    return respond.payload(result)


@bp.post("/draft-cycles/<cycle_id>/clock/advance")
def clock_advance(cycle_id):
    auth.begin(["LeagueDraftAdmin"])
    validate.body()
    cycle = logic.path_lookup(db.draft_cycles, cycle_id)
    logic.require_phase(cycle, ("DRAFT_LIVE",))
    logic.require_unfrozen(cycle)
    result = logic.clock_advance(cycle)
    return respond.payload(result)


@bp.post("/draft-cycles/<cycle_id>/combine-invitations/select")
def select_invitations(cycle_id):
    auth.begin(["LeagueDraftAdmin"])
    data = validate.body()
    target_count = validate.integer(
        data, "target_count", minimum=1, maximum=K.INVITATION_MAX_TARGET_COUNT
    )
    cycle = logic.path_lookup(db.draft_cycles, cycle_id)
    logic.require_phase(cycle, ("DECLARATION_OPEN", "COMBINE_WEEK"))
    logic.require_unfrozen(cycle)

    pool = [
        p
        for p in derive.cycle_prospects(cycle["id"])
        if p["declaration_status"] == "DECLARED"
        and p["eligibility_status"] != "INELIGIBLE"
        and p["invitation_status"] == "NOT_INVITED"
    ]
    if not pool:
        from errors import ApiError

        raise ApiError(
            "ERR_NO_ELIGIBLE_PROSPECTS",
            "No prospect of this cycle is available for invitation.",
        )
    pool.sort(
        key=lambda p: (
            -calc.q2(p["scouting_grade"]),
            p["position_group_scarcity_rank"],
            p["created_at"],
            p["_seq"],
        )
    )
    chosen = pool[:target_count]
    for prospect in chosen:
        prospect["invitation_status"] = "INVITED"
    return respond.payload(
        {
            "invited_count": len(chosen),
            "invited_prospect_ids": [p["id"] for p in chosen],
        }
    )


@bp.get("/draft-cycles/<cycle_id>/clubs")
def list_cycle_clubs(cycle_id):
    auth.begin(["LeagueDraftAdmin", "ClubGM", "EligibilityCommittee"])
    limit, offset = validate.pagination()
    registration_status = validate.query_enum(
        "registration_status", K.REGISTRATION_STATUSES
    )
    cycle = logic.path_lookup(db.draft_cycles, cycle_id)
    rows = derive.cycle_clubs(cycle["id"])
    if registration_status is not None:
        rows = [r for r in rows if r["registration_status"] == registration_status]
    return respond.listing(logic.by_club_order(rows), limit, offset)


@bp.get("/draft-cycles/<cycle_id>/prospects")
def list_cycle_prospects(cycle_id):
    auth.begin(
        [
            "LeagueDraftAdmin",
            "ClubGM",
            "EligibilityCommittee",
            "CombineMedicalExaminer",
        ]
    )
    limit, offset = validate.pagination()
    declaration_status = validate.query_enum(
        "declaration_status", K.DECLARATION_STATUSES
    )
    eligibility_status = validate.query_enum(
        "eligibility_status", K.ELIGIBILITY_STATUSES
    )
    invitation_status = validate.query_enum("invitation_status", K.INVITATION_STATUSES)
    cycle = logic.path_lookup(db.draft_cycles, cycle_id)
    rows = derive.cycle_prospects(cycle["id"])
    if declaration_status is not None:
        rows = [r for r in rows if r["declaration_status"] == declaration_status]
    if eligibility_status is not None:
        rows = [r for r in rows if r["eligibility_status"] == eligibility_status]
    if invitation_status is not None:
        rows = [r for r in rows if r["invitation_status"] == invitation_status]
    return respond.listing(logic.by_created(rows), limit, offset)
