"""ManualTally endpoints (the hand count)."""

from datetime import timedelta

from flask import Blueprint, g

from db import clock_now, db, dt_of, insert, iso, now_iso, set_fields, touch
from errors import fail
from middleware import ROLE_TALLY_TEAM_LEAD, SIX_ROLES, guard
from routes.common import list_endpoint, lookup, single
from services import calc
from services.domain import (
    TERMINAL_AUDIT_STATES,
    audit_batch_chain,
    cascade_round,
    discrepancies_of_tally,
    machine_margin_of,
    project_audit_timeline,
    recompute_election,
    recompute_tally_figures,
    sync_discrepancy_for_tally,
    tallies_of_audit_batch,
    tally_chain,
)
from validate import (
    body,
    opt_int,
    opt_str,
    opt_vote_map,
    req_dt,
    req_int,
    req_str,
    req_vote_map,
)

bp = Blueprint("tallies", __name__)

TALLY_STATUSES = ("DRAFT", "SUBMITTED", "PENDING_ADJUDICATION", "CERTIFIED", "VOIDED")
LIVE_SESSION_STATES = ("DRAFT", "SUBMITTED", "PENDING_ADJUDICATION")
BLOCKING_TALLY_STATES = ("DRAFT", "SUBMITTED", "PENDING_ADJUDICATION", "CERTIFIED")


def _acting_team():
    """Tier 6: the acting X-User-ID must resolve to a TallyTeam."""
    team = db.tally_teams.get(g.user_id)
    if team is None:
        fail("ERR_TALLY_TEAM_MISMATCH")
    return team


def _owned(tally):
    team = _acting_team()
    if tally["tally_team_id"] != team["id"]:
        fail("ERR_TALLY_TEAM_MISMATCH")
    return team


def _batch_of(audit_batch):
    ballot_batch = db.ballot_batches.get(audit_batch["ballot_batch_id"])
    if ballot_batch is None:
        fail("ERR_BALLOT_BATCH_NOT_FOUND")
    return ballot_batch


@bp.post("/manual-tallies")
@guard([ROLE_TALLY_TEAM_LEAD])
def create_manual_tally():
    data = body()
    audit_batch_id = req_str(data, "audit_batch_id", 1, None)
    tally_team_id = req_str(data, "tally_team_id", 1, None)
    session_start_at = req_dt(data, "session_start_at")
    session_end_at = req_dt(data, "session_end_at")
    room_code = opt_str(data, "room_code", 1, None)
    counted_votes = opt_vote_map(data, "counted_votes")
    ambiguous_ballot_count = opt_int(data, "ambiguous_ballot_count", 0, None, 0)
    no_vote_count = opt_int(data, "no_vote_count", 0, None, 0)

    audit_batch = lookup("audit_batches", audit_batch_id)
    team = lookup("tally_teams", tally_team_id)

    acting = _acting_team()
    if acting["id"] != tally_team_id:
        fail("ERR_TALLY_TEAM_MISMATCH")

    rnd, audit, contest, election = audit_batch_chain(audit_batch)
    if election is not None and election["status"] == "CERTIFIED":
        fail("ERR_ELECTION_ALREADY_CERTIFIED")
    if team["status"] != "READY":
        fail("ERR_TALLY_TEAM_NOT_READY")

    ballot_batch = _batch_of(audit_batch)
    if ballot_batch["custody_status"] == "QUARANTINED":
        fail("ERR_BATCH_QUARANTINED")
    if ballot_batch["custody_status"] != "CHECKED_OUT":
        fail("ERR_BATCH_NOT_CHECKED_OUT")

    if election is not None and team["election_id"] != election["id"]:
        fail("ERR_CROSS_ELECTION_REFERENCE")

    if counted_votes is not None and set(counted_votes.keys()) != set(
        contest["candidate_names"]
    ):
        fail("ERR_CANDIDATE_NAME_UNKNOWN")

    if session_start_at >= session_end_at:
        fail("ERR_INVALID_TIME_WINDOW")

    buffer = timedelta(minutes=calc.RESEAL_BUFFER_MINUTES)
    for other in db.manual_tallies.values():
        if other["status"] not in LIVE_SESSION_STATES:
            continue
        if other["tally_team_id"] != tally_team_id:
            continue
        other_start = dt_of(other["session_start_at"])
        other_end = dt_of(other["session_end_at"])
        if session_start_at < other_end and other_start < session_end_at:
            fail("ERR_TEAM_SESSION_OVERLAP")

    for other in db.manual_tallies.values():
        if other["status"] not in LIVE_SESSION_STATES:
            continue
        other_batch = db.audit_batches.get(other["audit_batch_id"])
        if other_batch is None:
            continue
        if other_batch["ballot_batch_id"] != ballot_batch["id"]:
            continue
        other_start = dt_of(other["session_start_at"])
        other_end = dt_of(other["session_end_at"])
        if session_start_at < other_end + buffer and other_start < session_end_at + buffer:
            fail("ERR_BATCH_SESSION_OVERLAP")

    for other in tallies_of_audit_batch(audit_batch):
        if other["status"] in BLOCKING_TALLY_STATES:
            fail("ERR_DUPLICATE_TALLY")

    row = insert(
        "manual_tallies",
        {
            "audit_batch_id": audit_batch_id,
            "tally_team_id": tally_team_id,
            "session_start_at": iso(session_start_at),
            "session_end_at": iso(session_end_at),
            "room_code": room_code if room_code is not None else team["room_code"],
            "counted_votes": dict(counted_votes) if counted_votes is not None else None,
            "ambiguous_ballot_count": ambiguous_ballot_count,
            "no_vote_count": no_vote_count,
            "machine_margin_votes": machine_margin_of(contest, ballot_batch),
            "manual_margin_votes": None,
            "net_error_votes": None,
            "relative_taint": None,
            "status": "DRAFT",
            "reopen_count": 0,
            "submitted_at": None,
            "submitted_by_user_id": None,
        },
    )

    if audit_batch["tally_status"] == "NOT_STARTED":
        audit_batch["tally_status"] = "IN_PROGRESS"
        touch(audit_batch)
    if rnd["status"] == "SELECTED":
        rnd["status"] = "TALLYING"
        touch(rnd)
    if audit["status"] == "SAMPLING":
        audit["status"] = "TALLYING"
        touch(audit)
        project_audit_timeline(audit)
        recompute_election(election)
    return single(row, 201)


@bp.get("/manual-tallies")
@guard(SIX_ROLES)
def list_manual_tallies():
    return list_endpoint(
        "manual_tallies",
        {
            "audit_batch_id": ("audit_batch_id", None),
            "tally_team_id": ("tally_team_id", None),
            "status": ("status", TALLY_STATUSES),
        },
    )


@bp.get("/manual-tallies/<tally_id>")
@guard(SIX_ROLES)
def get_manual_tally(tally_id):
    return single(lookup("manual_tallies", tally_id))


@bp.patch("/manual-tallies/<tally_id>")
@guard([ROLE_TALLY_TEAM_LEAD])
def patch_manual_tally(tally_id):
    data = body()
    counted_votes = opt_vote_map(data, "counted_votes")
    ambiguous_ballot_count = opt_int(data, "ambiguous_ballot_count", 0, None)
    no_vote_count = opt_int(data, "no_vote_count", 0, None)

    tally = lookup("manual_tallies", tally_id)
    _owned(tally)

    if tally["status"] != "DRAFT":
        fail("ERR_INVALID_TALLY_STATE")

    audit_batch, rnd, audit, contest, election = tally_chain(tally)
    ballot_batch = _batch_of(audit_batch)
    if ballot_batch["custody_status"] == "QUARANTINED":
        fail("ERR_BATCH_QUARANTINED")
    if ballot_batch["custody_status"] != "CHECKED_OUT":
        fail("ERR_BATCH_NOT_CHECKED_OUT")

    if counted_votes is not None and set(counted_votes.keys()) != set(
        contest["candidate_names"]
    ):
        fail("ERR_CANDIDATE_NAME_UNKNOWN")

    updates = {}
    if counted_votes is not None:
        updates["counted_votes"] = dict(counted_votes)
    if ambiguous_ballot_count is not None:
        updates["ambiguous_ballot_count"] = ambiguous_ballot_count
    if no_vote_count is not None:
        updates["no_vote_count"] = no_vote_count
    if set_fields(tally, updates):
        touch(tally)
    return single(tally)


@bp.post("/manual-tallies/<tally_id>/submit")
@guard([ROLE_TALLY_TEAM_LEAD])
def submit_manual_tally(tally_id):
    tally = lookup("manual_tallies", tally_id)
    team = _owned(tally)

    if tally["status"] != "DRAFT" or tally["counted_votes"] is None:
        fail("ERR_INVALID_TALLY_STATE")

    audit_batch, rnd, audit, contest, election = tally_chain(tally)
    ballot_batch = _batch_of(audit_batch)
    if ballot_batch["custody_status"] == "QUARANTINED":
        fail("ERR_BATCH_QUARANTINED")
    if ballot_batch["custody_status"] != "CHECKED_OUT":
        fail("ERR_BATCH_NOT_CHECKED_OUT")

    if not team["is_bipartisan"]:
        fail("ERR_TEAM_NOT_BIPARTISAN")

    total = (
        sum(tally["counted_votes"].values())
        + tally["ambiguous_ballot_count"]
        + tally["no_vote_count"]
    )
    if total != audit_batch["ballot_count"]:
        fail("ERR_TALLY_BALLOT_COUNT_MISMATCH")

    recompute_tally_figures(tally, contest, audit_batch, ballot_batch)
    tally["status"] = "SUBMITTED"
    tally["submitted_at"] = now_iso()
    tally["submitted_by_user_id"] = g.user_id
    touch(tally)

    if audit_batch["tally_status"] == "IN_PROGRESS":
        audit_batch["tally_status"] = "COUNTED"
        touch(audit_batch)

    created = sync_discrepancy_for_tally(tally, contest, audit_batch)
    cascade_round(rnd, audit, discrepancy_created=created)
    return single(tally)


@bp.post("/manual-tallies/<tally_id>/reopen")
@guard([ROLE_TALLY_TEAM_LEAD])
def reopen_manual_tally(tally_id):
    data = body()
    reason = req_str(data, "reason", 1, None)

    tally = lookup("manual_tallies", tally_id)
    _owned(tally)

    if tally["status"] != "SUBMITTED":
        fail("ERR_INVALID_TALLY_STATE")

    audit_batch, rnd, audit, contest, election = tally_chain(tally)
    if audit["status"] in TERMINAL_AUDIT_STATES:
        fail("ERR_INVALID_AUDIT_STATE")
    for row in discrepancies_of_tally(tally):
        if row["status"] in ("ESCALATED", "RESOLVED"):
            fail("ERR_INVALID_DISCREPANCY_STATE")

    if tally["reopen_count"] >= calc.MAX_TALLY_REOPENS:
        fail("ERR_REOPEN_LIMIT_EXCEEDED")

    tally["status"] = "DRAFT"
    tally["reopen_count"] = tally["reopen_count"] + 1
    tally["net_error_votes"] = None
    tally["relative_taint"] = None
    touch(tally)

    if audit_batch["tally_status"] == "COUNTED":
        audit_batch["tally_status"] = "IN_PROGRESS"
        touch(audit_batch)

    for row in discrepancies_of_tally(tally):
        if row["status"] in ("OPEN", "DOCUMENTED"):
            row["status"] = "VOIDED"
            touch(row)

    cascade_round(rnd, audit)
    return single(tally)
