"""Ballot construction, lines, locking and publication (PRD 3.6)."""
from flask import Blueprint

import auth
import constants
import db
import errors
import listing
import lookup
import response
import serialize
import validation

bp = Blueprint("ballots", __name__)


def _void_ballot(ballot):
    """A superseded DRAFT ballot is voided together with every one of its lines."""
    for line in lookup.lines_of_ballot(ballot["id"]):
        if line["status"] == "ACTIVE":
            db.set_fields(line, status="VOIDED")
            db.set_fields(ballot, active_line_count=max(0, ballot["active_line_count"] - 1))
    db.set_fields(ballot, status="VOIDED")
    db.touch(ballot)


@bp.post("/ballots")
def create_ballot():
    auth.require(constants.ELECTION_COMMISSIONER)
    body = validation.get_body()

    # rule 4 — body foreign key
    election = lookup.fk_election(body)

    # rule 5 — schema
    validation.req_str(body, "election_id")
    round_number = validation.req_int(body, "round", minimum=1)
    expected_version = validation.req_int(body, "expected_election_version")

    # rule 9 — the election must be in a state that admits a ballot create
    status = election["status"]
    existing = [b for b in lookup.ballots_of(election["id"])
                if b["round"] == round_number and b["status"] != "VOIDED"]
    if status == "PETITIONING":
        if round_number != 1:
            errors.fail(errors.ERR_INVALID_STATE,
                        "Only a round-1 ballot may be created out of PETITIONING.")
        if not db.now() >= election["petition_deadline"]:
            errors.fail(errors.ERR_INVALID_STATE,
                        "The logical clock has not reached the petition deadline.")
    elif status == "RUNOFF_SCHEDULED":
        if round_number != 2:
            errors.fail(errors.ERR_INVALID_STATE,
                        "Only a round-2 ballot may be created out of RUNOFF_SCHEDULED.")
        if election["runoff_required_office_count"] < 1:
            errors.fail(errors.ERR_INVALID_STATE,
                        "No office requires a runoff.")
    elif status == "BALLOT_BUILDING":
        if any(b["status"] != "DRAFT" for b in existing):
            errors.fail(errors.ERR_INVALID_STATE,
                        "The existing ballot for this round is no longer a DRAFT.")
    else:
        errors.fail(errors.ERR_INVALID_STATE,
                    "A ballot may not be created while the election is %s." % status)

    # rule 11 — optimistic concurrency on the election version
    if expected_version != election["version"]:
        errors.fail(errors.ERR_STALE_ELECTION_VERSION,
                    "expected_election_version does not match the election version.")

    for ballot in existing:
        if ballot["status"] == "DRAFT":
            _void_ballot(ballot)

    row = db.new_row(db.store.ballots, {
        "election_id": election["id"],
        "round": round_number,
        "status": "DRAFT",
        "line_count": 0,
        "active_line_count": 0,
        "locked_at": None,
        "published_at": None,
        "_snapshot": [],
    })

    if status == "PETITIONING":
        db.set_fields(election, status="BALLOT_BUILDING")
    elif status == "RUNOFF_SCHEDULED":
        db.set_fields(election, status="BALLOT_BUILDING", current_round=2)
    db.touch(election)

    return response.object_response(serialize.ballot(row), 201)


@bp.get("/ballots")
def list_ballots():
    auth.require_any()
    rows = listing.filtered(db.store.ballots, {
        "election_id": ("election_id", None),
        "round": ("round", listing.as_int),
        "status": ("status", None),
    })
    return listing.list_response(rows, serialize.ballot)


@bp.get("/ballots/<ballot_id>")
def read_ballot(ballot_id):
    auth.require_any()
    row = lookup.ballot(ballot_id)
    return response.object_response(serialize.ballot(row))


@bp.post("/ballots/<ballot_id>/lines")
def create_line(ballot_id):
    auth.require(constants.ELECTION_COMMISSIONER)
    ballot = lookup.ballot(ballot_id)
    election = db.store.elections[ballot["election_id"]]
    body = validation.get_body()

    # rule 4 — body foreign keys, in input-list order
    office = lookup.fk_office(body)
    candidacy = lookup.fk_candidacy(body)
    referendum = lookup.fk_referendum(body)

    # rule 5 — schema
    line_type = validation.req_enum(body, "line_type", constants.LINE_TYPES)

    # rule 9 — lines are added to a DRAFT ballot only
    if ballot["status"] != "DRAFT":
        errors.fail(errors.ERR_INVALID_STATE, "Lines may only be added to a DRAFT ballot.")
    # rule 10 — election phase
    if election["status"] != "BALLOT_BUILDING":
        errors.fail(errors.ERR_ELECTION_PHASE_INVALID,
                    "Ballot lines may only be added while the election is BALLOT_BUILDING.")

    # rule 26 — shape and referenced-resource state
    if line_type == "CANDIDATE":
        if office is None or candidacy is None or validation.present(body, "referendum_id"):
            errors.fail(errors.ERR_INVALID_BALLOT_LINE,
                        "A CANDIDATE line supplies office_id and candidacy_id and omits referendum_id.")
        if candidacy["status"] not in ("ELIGIBLE", "RUNOFF_QUALIFIED"):
            errors.fail(errors.ERR_INVALID_BALLOT_LINE,
                        "The referenced candidacy is neither ELIGIBLE nor RUNOFF_QUALIFIED.")
    else:
        if referendum is None or validation.present(body, "office_id") or validation.present(body, "candidacy_id"):
            errors.fail(errors.ERR_INVALID_BALLOT_LINE,
                        "A REFERENDUM line supplies referendum_id and omits office_id and candidacy_id.")
        if referendum["drafting_status"] != "APPROVED_FOR_BALLOT":
            errors.fail(errors.ERR_INVALID_BALLOT_LINE,
                        "The referenced referendum is not APPROVED_FOR_BALLOT.")

    siblings = lookup.lines_of_ballot(ballot["id"])
    if line_type == "CANDIDATE":
        position = 1 + sum(1 for l in siblings
                           if l["line_type"] == "CANDIDATE" and l["office_id"] == office["id"])
    else:
        position = 1 + sum(1 for l in siblings if l["line_type"] == "REFERENDUM")

    row = db.new_row(db.store.ballot_lines, {
        "ballot_id": ballot["id"],
        "office_id": office["id"] if line_type == "CANDIDATE" else None,
        "candidacy_id": candidacy["id"] if line_type == "CANDIDATE" else None,
        "referendum_id": referendum["id"] if line_type == "REFERENDUM" else None,
        "line_type": line_type,
        "position": position,
        "status": "ACTIVE",
    })
    db.set_fields(ballot,
                  line_count=ballot["line_count"] + 1,
                  active_line_count=ballot["active_line_count"] + 1)
    db.touch(ballot)
    return response.object_response(serialize.ballot_line(row), 201)


@bp.get("/ballot-lines")
def list_lines():
    auth.require_any()
    rows = listing.filtered(db.store.ballot_lines, {
        "ballot_id": ("ballot_id", None),
        "office_id": ("office_id", None),
        "candidacy_id": ("candidacy_id", None),
        "referendum_id": ("referendum_id", None),
        "line_type": ("line_type", None),
        "status": ("status", None),
    })
    return listing.list_response(rows, serialize.ballot_line)


@bp.get("/ballot-lines/<ballot_line_id>")
def read_line(ballot_line_id):
    auth.require_any()
    row = lookup.ballot_line(ballot_line_id)
    return response.object_response(serialize.ballot_line(row))


@bp.post("/ballots/<ballot_id>/lock")
def lock_ballot(ballot_id):
    auth.require(constants.ELECTION_COMMISSIONER)
    ballot = lookup.ballot(ballot_id)
    election = db.store.elections[ballot["election_id"]]

    if ballot["status"] != "DRAFT":
        errors.fail(errors.ERR_INVALID_STATE, "Only a DRAFT ballot may be locked.")
    if election["status"] != "BALLOT_BUILDING":
        errors.fail(errors.ERR_ELECTION_PHASE_INVALID,
                    "Ballots may only be locked while the election is BALLOT_BUILDING.")

    lines = lookup.lines_of_ballot(ballot["id"])
    active_candidate_lines = [l for l in lines
                              if l["status"] == "ACTIVE" and l["line_type"] == "CANDIDATE"]
    covered = {l["office_id"] for l in active_candidate_lines}
    for office in lookup.offices_of(election["id"]):
        if office["id"] not in covered:
            errors.fail(errors.ERR_OFFICE_HAS_NO_CANDIDATE,
                        "Office %s carries no active candidate line." % office["id"])

    db.set_fields(ballot, status="LOCKED", locked_at=db.now())
    db.touch(ballot)

    for line in active_candidate_lines:
        candidacy = db.store.candidacies.get(line["candidacy_id"])
        if candidacy is None:
            continue
        if ballot["round"] == 1 and candidacy["status"] == "ELIGIBLE":
            db.set_fields(candidacy, status="ON_BALLOT")
        elif ballot["round"] != 1 and candidacy["status"] == "RUNOFF_QUALIFIED":
            db.set_fields(candidacy, status="ON_BALLOT")
        else:
            continue
        office = db.store.offices.get(candidacy["office_id"])
        if office is not None and office["status"] == "OPEN":
            db.set_fields(office, status="CONTESTED")

    for line in lines:
        if line["status"] != "ACTIVE" or line["line_type"] != "REFERENDUM":
            continue
        referendum = db.store.referenda.get(line["referendum_id"])
        if referendum is not None and referendum["drafting_status"] == "APPROVED_FOR_BALLOT":
            db.set_fields(referendum, drafting_status="ON_BALLOT")

    # the lock instant is the snapshot of record for STEP 1 of the tally
    snapshot = []
    for candidacy in lookup.candidacies_of(election["id"]):
        if candidacy["status"] == "ON_BALLOT":
            snapshot.append({
                "id": candidacy["id"],
                "leader": candidacy["slate_leader_candidacy_id"],
            })
    ballot["_snapshot"] = snapshot

    return response.object_response(serialize.ballot(ballot))


@bp.post("/ballots/<ballot_id>/publish")
def publish_ballot(ballot_id):
    auth.require(constants.ELECTION_COMMISSIONER)
    ballot = lookup.ballot(ballot_id)
    election = db.store.elections[ballot["election_id"]]

    if ballot["status"] != "LOCKED":
        errors.fail(errors.ERR_INVALID_STATE, "Only a LOCKED ballot may be published.")
    if election["status"] != "BALLOT_BUILDING":
        errors.fail(errors.ERR_INVALID_STATE,
                    "Ballots may only be published while the election is BALLOT_BUILDING.")
    if ballot["round"] != election["current_round"]:
        errors.fail(errors.ERR_INVALID_STATE,
                    "Only the ballot of the current round may be published.")

    db.set_fields(ballot, status="PUBLISHED", published_at=db.now())
    db.touch(ballot)

    by_office = {}
    for line in lookup.lines_of_ballot(ballot["id"]):
        if line["status"] != "ACTIVE" or line["line_type"] != "CANDIDATE":
            continue
        by_office.setdefault(line["office_id"], []).append(line)
    for office_id, lines in by_office.items():
        candidacies = []
        for line in lines:
            candidacy = db.store.candidacies.get(line["candidacy_id"])
            if candidacy is not None:
                candidacies.append(candidacy)
        for index, candidacy in enumerate(db.by_seq(candidacies), start=1):
            db.set_fields(candidacy, ballot_position=index)

    db.set_fields(election, status="BALLOT_PUBLISHED")
    db.touch(election)
    return response.object_response(serialize.ballot(ballot))
