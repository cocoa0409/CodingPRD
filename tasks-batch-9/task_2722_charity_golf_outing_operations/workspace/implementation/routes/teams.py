"""Team endpoints: grouping foursomes, the tee sheet and score posting."""

from flask import Blueprint

import calc
import derive
import enums
import serial
import store
import validate
from auth import (CHARITY_TREASURER, COURSE_OPERATIONS, PARTICIPANT,
                  TOURNAMENT_DIRECTOR, auth)
from envelope import created, ok, paginate
from errors import fail
from lookup import outing as get_outing
from lookup import player as get_player
from lookup import team as get_team
from store import touch

bp = Blueprint("teams", __name__)

READ_ROLES = (TOURNAMENT_DIRECTOR, COURSE_OPERATIONS, CHARITY_TREASURER,
              PARTICIPANT)

NULL_COMPETITIVE = ("gross_score", "gross_back_9", "gross_back_6",
                    "gross_back_3", "gross_hole_18", "net_score", "net_back_9",
                    "net_back_6", "net_back_3", "net_hole_18", "rank_position",
                    "score_posted_at", "wave", "starting_hole", "tee_time",
                    "cart_number", "slot_occupancy_start", "slot_occupancy_end")


@bp.post("/outing-ops/teams")
def create_team():
    auth((TOURNAMENT_DIRECTOR,))
    body = validate.body()
    validate.only_fields(body, ("outing_id", "team_name", "player_ids"))
    outing_id = validate.req_ref(body, "outing_id")
    team_name = validate.req_str(body, "team_name")
    player_ids = _player_ids(body)
    outing = get_outing(outing_id)
    players = [get_player(pid) for pid in player_ids]
    for player in players:
        reg = derive.registration_of_player(player)
        if reg is None or reg["outing_id"] != outing_id:
            fail("ERR_CROSS_OUTING_REFERENCE",
                 "Player %s belongs to another outing." % player["id"])
    if outing["play_status"] != "OPEN":
        fail("ERR_REGISTRATION_CLOSED", "The outing's field is not open.")
    for player in players:
        if player["team_id"] is not None:
            fail("ERR_PLAYER_ALREADY_ASSIGNED",
                 "Player %s already carries a team." % player["id"])
        if not derive.is_revenue(derive.registration_of_player(player)):
            fail("ERR_PLAYER_ALREADY_ASSIGNED",
                 "Player %s is not funded by a revenue-recognized registration."
                 % player["id"])
    if len(player_ids) < 1 or len(player_ids) > calc.PLAYER_SLOTS_PER_TEAM:
        fail("ERR_TEAM_SIZE_INVALID", "A team holds between one and four golfers.")
    per_registration = {}
    for player in players:
        key = player["registration_id"]
        per_registration[key] = per_registration.get(key, 0) + 1
    for registration_id, count in per_registration.items():
        reg = store.registrations.get(registration_id)
        if reg is not None and count > reg["player_count"]:
            fail("ERR_TEAM_SIZE_INVALID",
                 "The funding registration holds only %d slots."
                 % reg["player_count"])
    fields = {
        "outing_id": outing_id,
        "team_name": team_name,
        "player_count": 0,
        "team_playing_handicap": None,
        "handicap_variant": "PROVISIONAL",
        "prize_eligible": True,
        "prize_award_cents": 0,
        "tee_assignment_count": 0,
    }
    for name in NULL_COMPETITIVE:
        fields[name] = None
    row = store.new_row("Team", fields)
    for player in players:
        player["team_id"] = row["id"]
        touch(player)
    row["player_count"] = len(derive.players_of_team(row["id"]))
    derive.rederive_team_handicap(row, "PROVISIONAL")
    return created(serial.dump(row))


def _player_ids(body):
    # §2.5 lists "an array that must be non-empty is empty" among the schema
    # faults, and §2.6 evaluates the schema tier (3) ahead of the business
    # constraint tier (12) where ERR_TEAM_SIZE_INVALID lives, so an empty
    # roster is reported as ERR_INVALID_REQUEST.
    return validate.req_id_list(body, "player_ids")


@bp.get("/outing-ops/teams/<row_id>")
def read_team(row_id):
    auth(READ_ROLES)
    return ok(serial.dump(get_team(row_id)))


@bp.get("/outing-ops/teams")
def list_teams():
    auth(READ_ROLES)
    limit, offset = validate.page_params()
    outing_id = validate.q_str("outing_id")
    wave = validate.q_enum("wave", enums.WAVE)
    starting_hole = validate.q_int("starting_hole")
    rows = store.sorted_rows(store.teams.values())
    if outing_id is not None:
        rows = [r for r in rows if r["outing_id"] == outing_id]
    if wave is not None:
        rows = [r for r in rows if r["wave"] == wave]
    if starting_hole is not None:
        rows = [r for r in rows if r["starting_hole"] == starting_hole]
    return paginate(rows, limit, offset, serial.dump)


# --------------------------------------------------------------------------
# The tee sheet (PRD 3.5)
# --------------------------------------------------------------------------
def _wave_window(outing, wave):
    if outing is None or wave is None:
        return None, None
    if wave == "A":
        start, end = outing["wave_a_start"], outing["wave_a_end"]
    else:
        start, end = outing["wave_b_start"], outing["wave_b_end"]
    if start is None or end is None:
        return None, None
    return store.parse_ts(start), store.parse_ts(end)


@bp.post("/outing-ops/teams/<row_id>/tee-assignment")
def tee_assignment(row_id):
    auth((TOURNAMENT_DIRECTOR, COURSE_OPERATIONS))
    body = validate.body()
    validate.only_fields(body, ("wave", "starting_hole", "tee_time",
                                "cart_number", "expected_team_version"))
    wave = validate.req_enum(body, "wave", enums.WAVE)
    starting_hole = validate.req_int(body, "starting_hole", minimum=1, maximum=18)
    tee_time = validate.req_ts(body, "tee_time")
    cart_number = validate.req_int(body, "cart_number", minimum=1)
    expected = validate.req_int(body, "expected_team_version")
    team = get_team(row_id)
    if expected != team["version"]:
        fail("ERR_STALE_TEAM_VERSION",
             "The team has moved to version %d." % team["version"])
    outing = store.outings.get(team["outing_id"])
    contract = derive.contract_of(team["outing_id"])
    interval = contract["tee_interval_minutes"] if contract is not None else 10
    allowance = contract["cart_allowance_count"] if contract is not None else 40
    start = store.parse_ts(tee_time)
    end = start + store.minutes(interval)
    others = [t for t in derive.teams_of(team["outing_id"]) if t["id"] != team["id"]]

    # check 1 - the half-open tee-sheet slot
    for other in others:
        if other["starting_hole"] != starting_hole or other["tee_time"] is None:
            continue
        o_start = store.parse_ts(other["slot_occupancy_start"] or other["tee_time"])
        if other["slot_occupancy_end"] is not None:
            o_end = store.parse_ts(other["slot_occupancy_end"])
        else:
            o_end = o_start + store.minutes(interval)
        if start < o_end and o_start < end:
            fail("ERR_TEE_SLOT_CONFLICT",
                 "Hole %d already holds a group in that slot." % starting_hole)

    # check 2 - the cart turnaround
    wave_start, wave_end = _wave_window(outing, wave)
    gap = store.minutes(calc.CART_TURNAROUND_MINUTES)
    for other in others:
        if other["cart_number"] != cart_number or other["wave"] is None:
            continue
        if other["wave"] == wave:
            continue
        o_start, o_end = _wave_window(outing, other["wave"])
        if wave_start is None or o_start is None:
            continue
        if o_end <= wave_start:
            if wave_start - o_end < gap:
                fail("ERR_CART_DOUBLE_BOOKED",
                     "Cart %d has not had its turnaround time." % cart_number)
        elif wave_end <= o_start:
            if o_start - wave_end < gap:
                fail("ERR_CART_DOUBLE_BOOKED",
                     "Cart %d has not had its turnaround time." % cart_number)
        else:
            fail("ERR_CART_DOUBLE_BOOKED",
                 "Cart %d is held across overlapping waves." % cart_number)
    if wave_start is not None:
        if store.now_dt() > wave_start - store.minutes(calc.CART_PREP_MINUTES):
            fail("ERR_CART_DOUBLE_BOOKED",
                 "A cart may not be issued inside the fifteen minute prep window.")

    # check 3 - the wave window
    if wave_start is None or wave_end is None:
        fail("ERR_WAVE_WINDOW_VIOLATION", "Wave %s has no window." % wave)
    if start < wave_start or start > wave_end:
        fail("ERR_WAVE_WINDOW_VIOLATION",
             "The tee time falls outside wave %s." % wave)
    if outing["start_format"] == "SHOTGUN" and start != wave_start:
        fail("ERR_WAVE_WINDOW_VIOLATION",
             "A shotgun group must tee off at its wave's start instant.")

    # check 4 - the cart allowance
    if cart_number > allowance:
        fail("ERR_CART_ALLOWANCE_EXCEEDED",
             "The course supplies only %d carts." % allowance)
    carts = set()
    for other in others:
        if other["wave"] == wave and other["cart_number"] is not None:
            carts.add(other["cart_number"])
    carts.add(cart_number)
    if len(carts) > allowance:
        fail("ERR_CART_ALLOWANCE_EXCEEDED",
             "Wave %s would hold more than %d distinct carts." % (wave, allowance))

    team["wave"] = wave
    team["starting_hole"] = starting_hole
    team["tee_time"] = tee_time
    team["cart_number"] = cart_number
    team["slot_occupancy_start"] = tee_time
    team["slot_occupancy_end"] = store.fmt_ts(end)
    team["tee_assignment_count"] = team["tee_assignment_count"] + 1
    touch(team)
    return ok(serial.dump(team))


# --------------------------------------------------------------------------
# Score posting (PRD 3.8)
# --------------------------------------------------------------------------
SCORE_FIELDS = ("gross_score", "gross_back_9", "gross_back_6", "gross_back_3",
                "gross_hole_18")


@bp.post("/outing-ops/teams/<row_id>/score")
def post_score(row_id):
    auth((TOURNAMENT_DIRECTOR, COURSE_OPERATIONS))
    body = validate.body()
    validate.only_fields(body, SCORE_FIELDS)
    values = {}
    for name in SCORE_FIELDS:
        values[name] = validate.req_int(body, name, minimum=0)
    team = get_team(row_id)
    outing = store.outings.get(team["outing_id"])
    if outing is None or outing["play_status"] != "IN_PLAY":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Scores are only posted while the outing is IN_PLAY.")
    team.update(values)
    team["score_posted_at"] = store.now_iso()
    touch(team)
    derive.rederive_team_net(team)
    return ok(serial.dump(team))
