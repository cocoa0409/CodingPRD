"""Rank lists, their entries, committee ballots and certification."""

from flask import Blueprint

import calc
import helpers
import serializers
from auth import (
    acting_faculty,
    acting_id,
    endpoint,
    require_acting_faculty,
    require_faculty_program,
    require_program_director,
)
from envelope import object_response
from errors import ApiError
from store import (
    CERT_DEADLINE_UTC,
    MIN_SCORECARDS_PER_ENTRY,
    find,
    insert,
    must_find,
    new_row,
    now,
    now_iso,
    rows,
    touch,
)
from validators import body, fk, opt_str, q_enum, q_int, q_str, req_enum, req_int, req_str
from routes.common import keep, listing

bp = Blueprint("ranklists", __name__)

LIST_STATUSES = (
    "DRAFT",
    "COMMITTEE_REVIEW",
    "RETURNED",
    "APPROVED",
    "CERTIFIED",
    "WITHDRAWN",
)
BALLOTS = ("APPROVE", "RETURN")


def _by_position(entry):
    return (entry["rank_position"], entry["created_at"], entry["_seq"])


# ================================================================== RankList
@bp.post("/rank-lists")
@endpoint("ProgramDirector")
def create_rank_list():
    data = body()
    program = fk(data, "program_id", "programs")
    if program is None:
        req_str(data, "program_id")
        raise ApiError("ERR_RESOURCE_NOT_FOUND")

    faculty = require_acting_faculty()
    require_faculty_program(faculty, program["id"])

    if helpers.live_rank_list(program["id"]) is not None:
        raise ApiError(
            "ERR_DUPLICATE_RESOURCE", "The program already holds a live rank list."
        )

    row = new_row(
        program_id=program["id"],
        status="DRAFT",
        review_round=0,
        approved_at=None,
        certified_by_faculty_id=None,
    )
    insert("rank_lists", row)
    return object_response(serializers.rank_list(row), 201)


@bp.get("/rank-lists")
@endpoint("ProgramDirector", "CommitteeMember", "ProgramCoordinator", "NrmpAdmin")
def list_rank_lists():
    items = rows("rank_lists")
    items = keep(items, "program_id", q_str("program_id"))
    items = keep(items, "status", q_enum("status", LIST_STATUSES))
    items = keep(items, "certified_by_faculty_id", q_str("certified_by_faculty_id"))
    return listing(items, serializers.rank_list)


@bp.get("/rank-lists/<rank_list_id>")
@endpoint("ProgramDirector", "CommitteeMember", "ProgramCoordinator", "NrmpAdmin")
def read_rank_list(rank_list_id):
    return object_response(serializers.rank_list(must_find("rank_lists", rank_list_id)))


# ============================================================= RankListEntry
@bp.post("/rank-lists/<rank_list_id>/entries")
@endpoint("ProgramDirector")
def create_entry(rank_list_id):
    rank_list = must_find("rank_lists", rank_list_id)
    data = body()
    application = fk(data, "application_id", "applications")
    anchor = fk(data, "tie_group_anchor_entry_id", "rank_list_entries")
    if application is None:
        req_str(data, "application_id")
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    rank_position = req_int(data, "rank_position", minimum=1)
    expected_version = req_int(data, "expected_rank_list_version", minimum=0)

    helpers.require_state(rank_list, "status", ("DRAFT",))

    # priority 6 - optimistic concurrency on the list
    if expected_version != rank_list["version"]:
        raise ApiError("ERR_STALE_RANK_LIST_VERSION")

    faculty = require_acting_faculty()
    require_faculty_program(faculty, rank_list["program_id"])

    if anchor is not None and anchor["rank_list_id"] != rank_list["id"]:
        raise ApiError(
            "ERR_CROSS_REFERENCE_MISMATCH",
            "The tie-group anchor belongs to another rank list.",
        )
    if application["program_id"] != rank_list["program_id"]:
        raise ApiError(
            "ERR_CROSS_REFERENCE_MISMATCH", "The application belongs to another program."
        )

    entries = calc.list_entries(rank_list["id"])
    for other in entries:
        if other["application_id"] == application["id"]:
            raise ApiError("ERR_DUPLICATE_RESOURCE", "The application is already ranked.")
    for other in entries:
        if other["rank_position"] == rank_position:
            raise ApiError("ERR_DUPLICATE_RESOURCE", "That rank_position is already taken.")

    if rank_position != len(entries) + 1:
        raise ApiError(
            "ERR_RANK_POSITION_SEQUENCE",
            "rank_position must equal the list's entry_count plus one.",
        )

    program = find("programs", rank_list["program_id"])
    if len(entries) + 1 > calc.rank_list_capacity(program):
        raise ApiError("ERR_RANK_LIST_TOO_LONG")

    row = new_row(
        rank_list_id=rank_list["id"],
        application_id=application["id"],
        rank_position=rank_position,
        tie_group_anchor_entry_id=anchor["id"] if anchor else None,
    )
    insert("rank_list_entries", row)
    touch(rank_list)
    return object_response(serializers.rank_list_entry(row), 201)


@bp.get("/rank-lists/<rank_list_id>/entries")
@endpoint("ProgramDirector", "CommitteeMember", "ProgramCoordinator", "NrmpAdmin")
def list_entries_of_list(rank_list_id):
    rank_list = must_find("rank_lists", rank_list_id)
    return listing(
        calc.list_entries(rank_list["id"]), serializers.rank_list_entry, sort_key=_by_position
    )


@bp.get("/rank-list-entries")
@endpoint("ProgramDirector", "CommitteeMember", "ProgramCoordinator", "NrmpAdmin")
def list_all_entries():
    items = rows("rank_list_entries")
    items = keep(items, "application_id", q_str("application_id"))
    items = keep(items, "tie_group_anchor_entry_id", q_str("tie_group_anchor_entry_id"))
    return listing(items, serializers.rank_list_entry)


@bp.get("/rank-list-entries/<entry_id>")
@endpoint("ProgramDirector", "CommitteeMember", "ProgramCoordinator", "NrmpAdmin")
def read_entry(entry_id):
    return object_response(
        serializers.rank_list_entry(must_find("rank_list_entries", entry_id))
    )


# ========================================================= committee workflow
@bp.post("/rank-lists/<rank_list_id>/submit-to-committee")
@endpoint("ProgramDirector")
def submit_to_committee(rank_list_id):
    rank_list = must_find("rank_lists", rank_list_id)
    program = find("programs", rank_list["program_id"])

    helpers.require_state(rank_list, "status", ("DRAFT",))
    helpers.require_phase(program, ("RANKING",))
    entries = calc.list_entries(rank_list["id"])
    if not entries:
        helpers.invalid_state("The list holds no entry.")

    faculty = require_acting_faculty()
    require_program_director(faculty)
    require_faculty_program(faculty, rank_list["program_id"])

    for entry in entries:
        application = find("applications", entry["application_id"])
        if application is None:
            continue
        usable = [
            card
            for card in calc.application_cards(application["id"])
            if card["status"] in ("SUBMITTED", "LOCKED")
        ]
        if len(usable) < MIN_SCORECARDS_PER_ENTRY:
            raise ApiError(
                "ERR_INSUFFICIENT_EVALUATIONS",
                "Every ranked application needs at least %d submitted score cards."
                % MIN_SCORECARDS_PER_ENTRY,
            )

    positions = sorted(entry["rank_position"] for entry in entries)
    if positions != list(range(1, len(entries) + 1)):
        raise ApiError(
            "ERR_RANK_POSITION_SEQUENCE",
            "rank_position values must be exactly 1..entry_count.",
        )

    if len(entries) > calc.rank_list_capacity(program):
        raise ApiError("ERR_RANK_LIST_TOO_LONG")

    rank_list["status"] = "COMMITTEE_REVIEW"
    rank_list["review_round"] = rank_list["review_round"] + 1
    touch(rank_list)
    return object_response(serializers.rank_list(rank_list))


@bp.post("/rank-lists/<rank_list_id>/votes")
@endpoint("CommitteeMember")
def cast_vote(rank_list_id):
    rank_list = must_find("rank_lists", rank_list_id)
    data = body()
    faculty = fk(data, "faculty_member_id", "faculty_members")
    if faculty is None:
        req_str(data, "faculty_member_id")
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    ballot = req_enum(data, "ballot", BALLOTS)
    comment = opt_str(data, "comment", max_len=2000)

    helpers.require_state(rank_list, "status", ("COMMITTEE_REVIEW",))

    if faculty["id"] != acting_id():
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
    if not faculty.get("is_committee_member"):
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
    require_faculty_program(faculty, rank_list["program_id"])

    current_round = rank_list["review_round"]
    for other in calc.list_votes(rank_list["id"]):
        if (
            other["faculty_member_id"] == faculty["id"]
            and other["review_round"] == current_round
        ):
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE", "This member already balloted in this round."
            )

    vote = new_row(
        rank_list_id=rank_list["id"],
        faculty_member_id=faculty["id"],
        review_round=current_round,
        ballot=ballot,
        comment=comment,
    )
    insert("committee_votes", vote)

    threshold = calc.quorum_threshold(rank_list["program_id"])
    ballots = [
        v for v in calc.list_votes(rank_list["id"]) if v["review_round"] == current_round
    ]
    approve = len([v for v in ballots if v["ballot"] == "APPROVE"])
    returns = len([v for v in ballots if v["ballot"] == "RETURN"])
    if approve >= threshold:
        rank_list["status"] = "APPROVED"
        rank_list["approved_at"] = now_iso()
    elif returns >= threshold:
        rank_list["status"] = "RETURNED"
    touch(rank_list)

    return object_response(serializers.committee_vote(vote), 201)


@bp.get("/rank-lists/<rank_list_id>/votes")
@endpoint("ProgramDirector", "CommitteeMember", "ProgramCoordinator", "NrmpAdmin")
def list_votes_of_list(rank_list_id):
    rank_list = must_find("rank_lists", rank_list_id)
    items = calc.list_votes(rank_list["id"])
    items = keep(items, "review_round", q_int("review_round", minimum=0))
    items = keep(items, "ballot", q_enum("ballot", BALLOTS))
    return listing(items, serializers.committee_vote)


@bp.get("/committee-votes")
@endpoint("ProgramDirector", "CommitteeMember", "ComplianceOfficer", "NrmpAdmin")
def list_committee_votes():
    items = rows("committee_votes")
    items = keep(items, "faculty_member_id", q_str("faculty_member_id"))
    items = keep(items, "rank_list_id", q_str("rank_list_id"))
    return listing(items, serializers.committee_vote)


@bp.get("/committee-votes/<vote_id>")
@endpoint("ProgramDirector", "CommitteeMember", "ComplianceOfficer", "NrmpAdmin")
def read_committee_vote(vote_id):
    return object_response(serializers.committee_vote(must_find("committee_votes", vote_id)))


@bp.post("/rank-lists/<rank_list_id>/revise")
@endpoint("ProgramDirector")
def revise_rank_list(rank_list_id):
    rank_list = must_find("rank_lists", rank_list_id)
    helpers.require_state(rank_list, "status", ("RETURNED",))

    faculty = require_acting_faculty()
    require_faculty_program(faculty, rank_list["program_id"])

    rank_list["status"] = "DRAFT"
    touch(rank_list)
    return object_response(serializers.rank_list(rank_list))


@bp.post("/rank-lists/<rank_list_id>/certify")
@endpoint("ProgramDirector")
def certify_rank_list(rank_list_id):
    rank_list = must_find("rank_lists", rank_list_id)
    data = body()
    certifier = fk(data, "certified_by_faculty_id", "faculty_members")
    if certifier is None:
        req_str(data, "certified_by_faculty_id")
        raise ApiError("ERR_RESOURCE_NOT_FOUND")

    helpers.require_state(rank_list, "status", ("APPROVED",))

    entries = calc.list_entries(rank_list["id"])
    ranked_ids = set(entry["application_id"] for entry in entries)

    # priority 7 - segregation of duties for the acting director
    for card in rows("score_cards"):
        if card["application_id"] not in ranked_ids:
            continue
        assignment = find("interview_assignments", card["assignment_id"])
        if assignment is not None and assignment["faculty_member_id"] == acting_id():
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "The certifying director authored a score card for a ranked application.",
            )
    for vote in calc.list_votes(rank_list["id"]):
        if (
            vote["faculty_member_id"] == acting_id()
            and vote["review_round"] == rank_list["review_round"]
        ):
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "The certifying director balloted on this review round.",
            )

    faculty = acting_faculty()
    require_program_director(faculty)
    require_faculty_program(faculty, rank_list["program_id"])
    if certifier["id"] != acting_id():
        raise ApiError("ERR_OWNERSHIP_MISMATCH")

    if now() > CERT_DEADLINE_UTC:
        raise ApiError("ERR_CERTIFICATION_DEADLINE_PASSED")

    rank_list["status"] = "CERTIFIED"
    rank_list["certified_by_faculty_id"] = certifier["id"]
    touch(rank_list)

    for card in rows("score_cards"):
        if card["application_id"] in ranked_ids and card["status"] == "SUBMITTED":
            card["status"] = "LOCKED"
            touch(card)

    program = find("programs", rank_list["program_id"])
    if program is not None:
        program["rank_list_certified_at"] = now_iso()
        if program["season_phase"] == "RANKING":
            program["season_phase"] = "LIST_CERTIFIED"
        touch(program)

    return object_response(serializers.rank_list(rank_list))


@bp.post("/rank-lists/<rank_list_id>/withdraw")
@endpoint("ProgramDirector")
def withdraw_rank_list(rank_list_id):
    rank_list = must_find("rank_lists", rank_list_id)
    helpers.require_state(rank_list, "status", ("DRAFT", "COMMITTEE_REVIEW"))

    faculty = require_acting_faculty()
    require_faculty_program(faculty, rank_list["program_id"])

    rank_list["status"] = "WITHDRAWN"
    touch(rank_list)
    return object_response(serializers.rank_list(rank_list))
