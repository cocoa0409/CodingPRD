"""Player endpoints: golfers, the confirmation snapshot and index updates."""

from flask import Blueprint

import calc
import derive
import enums
import serial
import store
import validate
from auth import (COURSE_OPERATIONS, PARTICIPANT, SPONSORSHIP_MANAGER,
                  TOURNAMENT_DIRECTOR, auth, own_player_only)
from envelope import created, ok, paginate
from errors import fail
from lookup import player as get_player
from lookup import registration as get_registration
from store import touch

bp = Blueprint("players", __name__)

READ_ROLES = (TOURNAMENT_DIRECTOR, COURSE_OPERATIONS, SPONSORSHIP_MANAGER,
              PARTICIPANT)


@bp.post("/outing-ops/players")
def create_player():
    auth((TOURNAMENT_DIRECTOR, SPONSORSHIP_MANAGER, PARTICIPANT))
    body = validate.body()
    validate.only_fields(body, ("registration_id", "full_name", "handicap_index",
                                "amateur_status"))
    registration_id = validate.req_ref(body, "registration_id")
    full_name = validate.req_str(body, "full_name")
    index = validate.req_number(body, "handicap_index", minimum=0,
                                maximum=calc.MAX_HANDICAP_INDEX)
    amateur_status = validate.opt_enum(body, "amateur_status",
                                       enums.AMATEUR_STATUS, default="AMATEUR")
    reg = get_registration(registration_id)
    if len(derive.players_of_registration(registration_id)) >= reg["player_count"]:
        fail("ERR_PLAYER_SLOTS_EXCEEDED",
             "The registration holds only %d player slots." % reg["player_count"])
    row = store.new_row("Player", {
        "registration_id": registration_id,
        "team_id": None,
        "full_name": full_name,
        "handicap_index": index,
        "amateur_status": amateur_status,
        "handicap_index_at_confirm": None,
        "effective_handicap_index": None,
        "course_handicap": None,
        "checked_in": False,
    })
    if derive.is_revenue(reg):
        row["handicap_index_at_confirm"] = row["handicap_index"]
        derive.rederive_player_handicap(row, use_effective=False)
    return created(serial.dump(row))


@bp.get("/outing-ops/players/<row_id>")
def read_player(row_id):
    # §2.1: "addressing any other player's row is refused with
    # ERR_UNAUTHORIZED", and §2.6 puts that ownership check in the
    # authorization tier, ahead of path existence — so it covers reads too.
    user_id, role = auth(READ_ROLES)
    own_player_only(user_id, role, row_id)
    return ok(serial.dump(get_player(row_id)))


@bp.get("/outing-ops/players")
def list_players():
    auth(READ_ROLES)
    limit, offset = validate.page_params()
    registration_id = validate.q_str("registration_id")
    team_id = validate.q_str("team_id")
    amateur_status = validate.q_enum("amateur_status", enums.AMATEUR_STATUS)
    checked_in = validate.q_bool("checked_in")
    rows = store.sorted_rows(store.players.values())
    if registration_id is not None:
        rows = [r for r in rows if r["registration_id"] == registration_id]
    if team_id is not None:
        rows = [r for r in rows if r["team_id"] == team_id]
    if amateur_status is not None:
        rows = [r for r in rows if r["amateur_status"] == amateur_status]
    if checked_in is not None:
        rows = [r for r in rows if r["checked_in"] == checked_in]
    return paginate(rows, limit, offset, serial.dump)


LOCKED_STATES = ("FIELD_LOCKED", "IN_PLAY", "SCORED")


@bp.post("/outing-ops/players/<row_id>/handicap-index")
def update_handicap_index(row_id):
    user_id, role = auth((TOURNAMENT_DIRECTOR, PARTICIPANT))
    own_player_only(user_id, role, row_id)
    body = validate.body()
    validate.only_fields(body, ("handicap_index",))
    index = validate.req_number(body, "handicap_index", minimum=0,
                                maximum=calc.MAX_HANDICAP_INDEX)
    player = get_player(row_id)
    outing = derive.outing_of_player(player)
    if outing is not None and outing["play_status"] in LOCKED_STATES:
        fail("ERR_INVALID_STATE_TRANSITION",
             "The field is locked; the index on file can no longer move.")
    player["handicap_index"] = index
    touch(player)
    derive.rederive_player_handicap(player, None, use_effective=False)
    if player["team_id"] is not None:
        team = store.teams.get(player["team_id"])
        if team is not None:
            derive.rederive_team_handicap(team, "PROVISIONAL")
    return ok(serial.dump(player))
