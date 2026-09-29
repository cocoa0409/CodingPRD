"""Confidential vote casting and withdrawal (PRD 3.6)."""
from flask import Blueprint

import auth
import clock
import db
import derive
import lookup
import payload
import response
import serialize
from auth import ROLE_ADMIN, ROLE_AUDITOR, ROLE_ELECTOR, ROLE_SCREENER
from errors import fail

bp = Blueprint("votes", __name__)


def _reveal(actor):
    """Ballot secrecy: only the IndependentAuditor sees the selections."""
    return actor.is_auditor


@bp.route("/vote-submissions", methods=["POST"])
def cast_vote():
    actor = auth.caller(ROLE_ELECTOR, ROLE_SCREENER)
    data = payload.body()
    ballot_id = payload.req_id(data, "ballot_id")
    expected_ballot_version = payload.req_int(data, "expected_ballot_version")
    selected_slot_ids = payload.opt_id_list(data, "selected_slot_ids", default=[])
    is_abstention = payload.opt_bool(data, "is_abstention", default=False)

    elector = auth.acting_elector(actor)
    ballot = lookup.ballot(ballot_id)

    if ballot["voting_status"] != "OPEN":
        fail("ERR_INVALID_BALLOT_STATE", "A submission requires an OPEN ballot.")

    if expected_ballot_version != ballot["version"]:
        fail("ERR_STALE_BALLOT_VERSION", "The ballot has advanced since it was read.")

    if elector["status"] != "CREDENTIALED":
        fail("ERR_ELECTOR_NOT_CREDENTIALED", "The elector is not CREDENTIALED.")
    if elector["credential_expires_on"] < clock.now():
        fail("ERR_CREDENTIAL_EXPIRED", "The elector's credential has expired.")

    if clock.now() >= ballot["closes_at"]:
        fail("ERR_VOTING_WINDOW_CLOSED", "The voting window has closed.")

    slots = {}
    for slot_id in selected_slot_ids:
        slot = db.ballot_slots.get(slot_id)
        if slot is None or slot["ballot_id"] != ballot["id"]:
            fail("ERR_SLOT_NOT_ON_BALLOT", "Slot '%s' is not printed on this ballot." % slot_id)
        slots[slot_id] = slot
    for slot_id in selected_slot_ids:
        if slots[slot_id]["status"] == "STRUCK":
            fail("ERR_SLOT_STRUCK", "Slot '%s' has been struck." % slot_id)

    for other in db.vote_submissions.values():
        if (
            other["ballot_id"] == ballot["id"]
            and other["elector_id"] == elector["id"]
            and other["status"] in ("COUNTED", "INVALIDATED")
        ):
            fail("ERR_DUPLICATE_SUBMISSION", "This elector already holds a submission here.")

    selection_count = len(selected_slot_ids)
    if selection_count > ballot["max_votes_per_elector"]:
        fail("ERR_MAX_VOTES_EXCEEDED", "The selection count exceeds this ballot's cap.")
    if is_abstention and selection_count != 0:
        fail("ERR_MAX_VOTES_EXCEEDED", "An abstention may not name any slot.")
    if not is_abstention and selection_count == 0:
        fail("ERR_MAX_VOTES_EXCEEDED", "An empty ballot must declare 'is_abstention'.")

    row = db.stamp(
        {
            "ballot_id": ballot["id"],
            "elector_id": elector["id"],
            "selected_slot_ids": list(selected_slot_ids),
            "selection_count": selection_count,
            "is_abstention": is_abstention,
            "status": "COUNTED",
            "ballot_version_after": ballot["version"],
            "cast_at": clock.now(),
            "invalidated_reason": None,
        }
    )
    db.vote_submissions[row["id"]] = row

    derive.recompute_ballot_counters(ballot, bump=False)
    db.touch(ballot)
    row["ballot_version_after"] = ballot["version"]

    cycle = db.cycles.get(ballot["cycle_id"])
    if cycle is not None:
        changed = (
            elector["last_participated_cycle_year"] != cycle["cycle_year"]
            or elector["consecutive_missed_cycles"] != 0
        )
        elector["last_participated_cycle_year"] = cycle["cycle_year"]
        elector["consecutive_missed_cycles"] = 0
        if changed:
            db.touch(elector)

    return response.created(serialize.vote_submission(row, _reveal(actor)))


@bp.route("/vote-submissions", methods=["GET"])
def list_votes():
    actor = auth.caller(ROLE_ADMIN, ROLE_ELECTOR, ROLE_AUDITOR)
    reveal = _reveal(actor)
    response.page_params()
    rows = lookup.apply_filters(
        list(db.vote_submissions.values()),
        [
            ("ballot_id", "ballot_id", "str"),
            ("elector_id", "elector_id", "str"),
            ("status", "status", "str"),
        ],
    )
    return response.paginate(
        db.sort_rows(rows), lambda row: serialize.vote_submission(row, reveal)
    )


@bp.route("/vote-submissions/<row_id>", methods=["GET"])
def read_vote(row_id):
    actor = auth.caller(ROLE_ADMIN, ROLE_ELECTOR, ROLE_AUDITOR)
    row = lookup.vote_submission(row_id)
    return response.ok(serialize.vote_submission(row, _reveal(actor)))


@bp.route("/vote-submissions/<row_id>/withdraw", methods=["POST"])
def withdraw_vote(row_id):
    """COUNTED -> WITHDRAWN while the window is still open."""
    actor = auth.caller(ROLE_ELECTOR, ROLE_SCREENER)
    auth.acting_elector(actor)
    row = lookup.vote_submission(row_id)
    ballot = lookup.ballot(row["ballot_id"])

    if ballot["voting_status"] != "OPEN":
        fail("ERR_INVALID_BALLOT_STATE", "A withdrawal requires an OPEN ballot.")
    if row["status"] != "COUNTED":
        fail("ERR_INVALID_BALLOT_STATE", "Only a COUNTED submission may be withdrawn.")

    if actor.user_id != row["elector_id"]:
        fail("ERR_NOMINATOR_IDENTITY_MISMATCH", "An elector may only withdraw their own vote.")

    if clock.now() >= ballot["closes_at"]:
        fail("ERR_VOTING_WINDOW_CLOSED", "The voting window has closed.")

    row["status"] = "WITHDRAWN"
    derive.recompute_ballot_counters(ballot, bump=False)
    db.touch(ballot)
    row["ballot_version_after"] = ballot["version"]
    db.touch(row)
    return response.ok(serialize.vote_submission(row, _reveal(actor)))
