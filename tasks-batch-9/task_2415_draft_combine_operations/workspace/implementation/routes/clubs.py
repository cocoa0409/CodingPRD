"""Club registration and retrieval (PRD 3.1)."""

from flask import Blueprint

import auth
import constants as K
import derive
import logic
import respond
import validate
from db import db
from errors import ApiError

bp = Blueprint("clubs", __name__)


def _valid_code(code):
    return len(code) == 3 and code.isalpha() and code.isupper()


@bp.post("/clubs")
def create_club():
    auth.begin(["LeagueDraftAdmin"])
    data = validate.body()
    draft_cycle_id = validate.string(data, "draft_cycle_id")
    club_code = validate.string(data, "club_code")
    if not _valid_code(club_code):
        validate.bad("club_code must be exactly three uppercase letters.")
    market_name = validate.string(data, "market_name")
    prior_season_win_pct = validate.number(
        data, "prior_season_win_pct", minimum=0, maximum=1
    )
    strength_of_schedule = validate.number(
        data, "strength_of_schedule", minimum=0, maximum=1
    )
    head_to_head_rank = validate.integer(data, "head_to_head_rank", minimum=1)
    rookie_pool_total_cents = validate.integer(
        data, "rookie_pool_total_cents", minimum=0
    )
    registration_status = validate.enum(
        data,
        "registration_status",
        K.REGISTRATION_STATUSES,
        required=False,
        default="REGISTERED",
    )
    playoff_qualified = validate.boolean(
        data, "playoff_qualified", required=False, default=False
    )
    playoff_exit_round = validate.integer(
        data, "playoff_exit_round", required=False, minimum=0, maximum=4
    )
    lottery_combinations = validate.integer(
        data, "lottery_combinations", required=False, minimum=0
    )

    cycle = logic.fk_lookup(db.draft_cycles, draft_cycle_id, "draft cycle")
    logic.require_unfrozen(cycle)

    for existing in derive.cycle_clubs(cycle["id"]):
        if existing["club_code"] == club_code:
            raise ApiError(
                "ERR_CLUB_CODE_DUPLICATE",
                "Club code %s is already registered in this cycle." % club_code,
            )

    rec = db.insert(
        db.clubs,
        "Club",
        {
            "draft_cycle_id": cycle["id"],
            "club_code": club_code,
            "market_name": market_name,
            "registration_status": registration_status,
            "playoff_qualified": bool(playoff_qualified),
            "playoff_exit_round": 0 if playoff_exit_round is None else playoff_exit_round,
            "prior_season_win_pct": prior_season_win_pct,
            "strength_of_schedule": strength_of_schedule,
            "head_to_head_rank": head_to_head_rank,
            "lottery_combinations": (
                0 if lottery_combinations is None else lottery_combinations
            ),
            "forfeited_round_numbers": [],
            "pre_lottery_rank": 0,
            "draft_order_index": 0,
            "rookie_pool_total_cents": rookie_pool_total_cents,
            "timeouts_remaining": K.CLUB_TIMEOUTS_PER_CYCLE,
            "udfa_pool_total_cents": 0,
        },
    )
    return respond.created(rec)


@bp.get("/clubs/<club_id>")
def get_club(club_id):
    auth.begin(["LeagueDraftAdmin", "ClubGM", "ClubMedicalDirector"])
    return respond.one(logic.path_lookup(db.clubs, club_id))
