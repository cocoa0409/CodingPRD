"""TallyTeam endpoints."""

from flask import Blueprint

from db import db, insert, touch
from errors import fail
from middleware import (
    ROLE_AUDIT_MANAGER,
    ROLE_CANVASSING_BOARD_MEMBER,
    ROLE_CUSTODY_OFFICER,
    ROLE_ELECTIONS_DIRECTOR,
    ROLE_TALLY_TEAM_LEAD,
    guard,
)
from routes.common import list_endpoint, lookup, single
from services.domain import tallies_of_team
from validate import body, req_enum, req_list, req_str

bp = Blueprint("teams", __name__)

TEAM_STATUSES = ("FORMING", "READY", "DISBANDED")
PARTIES = ("DEM", "REP", "UNAFFILIATED")
SEAT_ROLES = ("LEAD", "COUNTER", "LIAISON")
MAX_MEMBERS = 6
TEAM_READ_ROLES = (
    ROLE_ELECTIONS_DIRECTOR,
    ROLE_AUDIT_MANAGER,
    ROLE_CUSTODY_OFFICER,
    ROLE_TALLY_TEAM_LEAD,
    ROLE_CANVASSING_BOARD_MEMBER,
)
BLOCKING_TALLY_STATES = ("DRAFT", "PENDING_ADJUDICATION")


def _derive(team):
    counts = {}
    for member in team["members"]:
        counts[member["party"]] = counts.get(member["party"], 0) + 1
    team["party_counts"] = counts
    team["is_bipartisan"] = counts.get("DEM", 0) >= 1 and counts.get("REP", 0) >= 1
    if team["status"] == "FORMING" and team["is_bipartisan"]:
        team["status"] = "READY"
    elif team["status"] == "READY" and not team["is_bipartisan"]:
        team["status"] = "FORMING"


@bp.post("/tally-teams")
@guard([ROLE_ELECTIONS_DIRECTOR])
def create_tally_team():
    data = body()
    election_id = req_str(data, "election_id", 1, None)
    team_label = req_str(data, "team_label", 1, 32)
    room_code = req_str(data, "room_code", 1, None)

    election = lookup("elections", election_id)

    for team in db.tally_teams.values():
        if team["election_id"] == election_id and team["team_label"] == team_label:
            fail("ERR_DUPLICATE_TEAM_LABEL")

    row = insert(
        "tally_teams",
        {
            "election_id": election_id,
            "team_label": team_label,
            "room_code": room_code,
            "members": [],
            "party_counts": {},
            "is_bipartisan": False,
            "status": "FORMING",
        },
    )
    return single(row, 201)


@bp.get("/tally-teams")
@guard(TEAM_READ_ROLES)
def list_tally_teams():
    return list_endpoint(
        "tally_teams",
        {
            "election_id": ("election_id", None),
            "status": ("status", TEAM_STATUSES),
            "room_code": ("room_code", None),
        },
        sort_keys=("team_label",),
    )


@bp.get("/tally-teams/<team_id>")
@guard(TEAM_READ_ROLES)
def get_tally_team(team_id):
    return single(lookup("tally_teams", team_id))


@bp.post("/tally-teams/<team_id>/members")
@guard([ROLE_ELECTIONS_DIRECTOR])
def replace_team_members(team_id):
    data = body()
    raw_members = req_list(data, "members", 0, MAX_MEMBERS)
    members = []
    seen = set()
    for entry in raw_members:
        if not isinstance(entry, dict):
            fail("ERR_VALIDATION", "Each entry of 'members' must be an object.")
        user_id = req_str(entry, "user_id", 1, None)
        party = req_enum(entry, "party", PARTIES)
        seat_role = req_enum(entry, "seat_role", SEAT_ROLES)
        if user_id in seen:
            fail("ERR_VALIDATION", "Member user_id values must be unique.")
        seen.add(user_id)
        members.append(
            {"user_id": user_id, "party": party, "seat_role": seat_role}
        )

    team = lookup("tally_teams", team_id)
    if team["status"] == "DISBANDED":
        fail("ERR_INVALID_TEAM_STATE")

    team["members"] = members
    _derive(team)
    touch(team)
    return single(team)


@bp.post("/tally-teams/<team_id>/disband")
@guard([ROLE_ELECTIONS_DIRECTOR])
def disband_tally_team(team_id):
    team = lookup("tally_teams", team_id)
    if team["status"] == "DISBANDED":
        fail("ERR_INVALID_TEAM_STATE")

    tallies = tallies_of_team(team)
    if team["status"] == "READY":
        for tally in tallies:
            if tally["status"] in BLOCKING_TALLY_STATES:
                fail("ERR_INVALID_TALLY_STATE")
    else:
        if tallies:
            fail("ERR_INVALID_TALLY_STATE")

    team["status"] = "DISBANDED"
    touch(team)
    return single(team)
