"""BallotInterpretation endpoints (voter-intent adjudication)."""

from flask import Blueprint, g

from db import db, insert, touch
from errors import fail
from middleware import (
    ROLE_AUDIT_MANAGER,
    ROLE_CANDIDATE_REPRESENTATIVE,
    ROLE_CANVASSING_BOARD_MEMBER,
    ROLE_ELECTIONS_DIRECTOR,
    ROLE_TALLY_TEAM_LEAD,
    guard,
)
from routes.common import list_endpoint, lookup, single
from services import calc
from services.domain import (
    cascade_round,
    interpretations_of_tally,
    recompute_tally_figures,
    sync_discrepancy_for_tally,
    tally_chain,
)
from validate import body, req_enum, req_str

bp = Blueprint("interpretations", __name__)

AMBIGUITY_TYPES = (
    "OVERVOTE",
    "STRAY_MARK",
    "WRITE_IN_INTENT",
    "DAMAGED",
    "PARTIAL_MARK",
)
INTERPRETATION_STATUSES = ("PENDING", "ADJUDICATED", "DEADLOCKED")
PARTIES = ("DEM", "REP", "UNAFFILIATED")
VOTES = ("ACCEPT", "REJECT", "ABSTAIN")
READ_ROLES = (
    ROLE_ELECTIONS_DIRECTOR,
    ROLE_AUDIT_MANAGER,
    ROLE_TALLY_TEAM_LEAD,
    ROLE_CANVASSING_BOARD_MEMBER,
    ROLE_CANDIDATE_REPRESENTATIVE,
)


@bp.post("/ballot-interpretations")
@guard([ROLE_TALLY_TEAM_LEAD])
def create_ballot_interpretation():
    data = body()
    manual_tally_id = req_str(data, "manual_tally_id", 1, None)
    ballot_ref = req_str(data, "ballot_ref", 1, 32)
    ambiguity_type = req_enum(data, "ambiguity_type", AMBIGUITY_TYPES)
    proposed_determination = req_str(data, "proposed_determination", 1, None)

    tally = lookup("manual_tallies", manual_tally_id)

    team = db.tally_teams.get(g.user_id)
    if team is None or tally["tally_team_id"] != team["id"]:
        fail("ERR_TALLY_TEAM_MISMATCH")

    audit_batch, rnd, audit, contest, election = tally_chain(tally)
    if proposed_determination != "NO_VOTE" and proposed_determination not in contest[
        "candidate_names"
    ]:
        fail("ERR_CANDIDATE_NAME_UNKNOWN")

    existing = interpretations_of_tally(tally)
    pending = [r for r in existing if r["status"] == "PENDING"]
    if tally["ambiguous_ballot_count"] <= len(pending):
        fail("ERR_INTERPRETATION_LIMIT_EXCEEDED")
    for row in existing:
        if row["ballot_ref"] == ballot_ref:
            fail("ERR_DUPLICATE_BALLOT_REF")

    row = insert(
        "ballot_interpretations",
        {
            "manual_tally_id": manual_tally_id,
            "ballot_ref": ballot_ref,
            "ambiguity_type": ambiguity_type,
            "proposed_determination": proposed_determination,
            "board_votes": [],
            "votes_cast": 0,
            "accept_count": 0,
            "reject_count": 0,
            "quorum_met": False,
            "final_determination": None,
            "status": "PENDING",
        },
    )

    if tally["status"] == "SUBMITTED":
        tally["status"] = "PENDING_ADJUDICATION"
        touch(tally)
    return single(row, 201)


@bp.get("/ballot-interpretations")
@guard(READ_ROLES)
def list_ballot_interpretations():
    return list_endpoint(
        "ballot_interpretations",
        {
            "manual_tally_id": ("manual_tally_id", None),
            "status": ("status", INTERPRETATION_STATUSES),
            "ambiguity_type": ("ambiguity_type", AMBIGUITY_TYPES),
        },
    )


@bp.get("/ballot-interpretations/<interpretation_id>")
@guard(READ_ROLES)
def get_ballot_interpretation(interpretation_id):
    return single(lookup("ballot_interpretations", interpretation_id))


@bp.post("/ballot-interpretations/<interpretation_id>/votes")
@guard([ROLE_CANVASSING_BOARD_MEMBER])
def cast_board_vote(interpretation_id):
    data = body()
    party = req_enum(data, "party", PARTIES)
    vote = req_enum(data, "vote", VOTES)

    row = lookup("ballot_interpretations", interpretation_id)
    if row["status"] != "PENDING":
        fail("ERR_INVALID_INTERPRETATION_STATE")

    tally = db.manual_tallies.get(row["manual_tally_id"])
    audit_batch, rnd, audit, contest, election = tally_chain(tally)
    team = db.tally_teams.get(tally["tally_team_id"])
    if team is not None:
        for member in team["members"]:
            if member["user_id"] == g.user_id:
                fail("ERR_SEGREGATION_OF_DUTIES")

    for entry in row["board_votes"]:
        if entry["member_user_id"] == g.user_id:
            fail("ERR_DUPLICATE_BOARD_VOTE")

    row["board_votes"] = list(row["board_votes"]) + [
        {"member_user_id": g.user_id, "party": party, "vote": vote}
    ]
    outcome = calc.board_outcome(row["board_votes"], row["proposed_determination"])
    row["votes_cast"] = outcome["votes_cast"]
    row["accept_count"] = outcome["accept_count"]
    row["reject_count"] = outcome["reject_count"]
    row["quorum_met"] = outcome["quorum_met"]
    row["status"] = outcome["status"]
    row["final_determination"] = outcome["final_determination"]
    touch(row)

    if outcome["status"] == "ADJUDICATED":
        _apply_determination(tally, row, contest, audit_batch, rnd, audit)

    if row["status"] != "PENDING" and tally["status"] == "PENDING_ADJUDICATION":
        if not [
            i for i in interpretations_of_tally(tally) if i["status"] == "PENDING"
        ]:
            tally["status"] = "SUBMITTED"
            touch(tally)
    return single(row)


def _apply_determination(tally, interpretation, contest, audit_batch, rnd, audit):
    final = interpretation["final_determination"]
    tally["ambiguous_ballot_count"] = max(0, tally["ambiguous_ballot_count"] - 1)
    if final == "NO_VOTE":
        tally["no_vote_count"] = tally["no_vote_count"] + 1
    else:
        counted = tally.get("counted_votes")
        if counted is None:
            counted = {name: 0 for name in contest["candidate_names"]}
        else:
            counted = dict(counted)
        counted[final] = int(counted.get(final, 0)) + 1
        tally["counted_votes"] = counted

    ballot_batch = db.ballot_batches.get(audit_batch["ballot_batch_id"])
    if ballot_batch is not None:
        recompute_tally_figures(tally, contest, audit_batch, ballot_batch)
    touch(tally)

    created = sync_discrepancy_for_tally(tally, contest, audit_batch)
    cascade_round(rnd, audit, discrepancy_created=created)
