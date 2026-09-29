"""External directorships: the source data for overboarding and interlock."""

from flask import Blueprint

from authz import (
    COMMITTEE_CHAIR,
    COMMITTEE_MEMBER,
    CORPORATE_SECRETARY,
    GOVERNANCE_STAFF,
    require,
)
from calc import governing_policy, overboarding_limit, parse_iso_date, public_company_ids
from derive import (
    _apply,
    recompute_candidate_boards,
    recompute_compliance,
    recompute_director_boards,
)
from errors import fail
from payload import body, check_enum, check_interval_on_or_after, optional, parse_date, required
from store import db, new_row, touch
from vocab import DIRECTORSHIP_SEAT_ROLE

from routes.common import apply_filters, by_created_at, emit, emit_list, need

bp = Blueprint("directorship", __name__)

READ_ROLES = (GOVERNANCE_STAFF, CORPORATE_SECRETARY, COMMITTEE_CHAIR, COMMITTEE_MEMBER)
STAFF = (GOVERNANCE_STAFF, CORPORATE_SECRETARY)


def _subject_ids(row):
    return row.get("director_id"), row.get("candidate_id")


def _resettle(row):
    """Re-derive the subject's public board count and, for a director, compliance."""
    director_id, candidate_id = _subject_ids(row)
    if director_id is not None:
        director = db.directors.get(director_id)
        if director is not None:
            recompute_director_boards(director)
            recompute_compliance(director)
    elif candidate_id is not None:
        candidate = db.candidates.get(candidate_id)
        if candidate is not None:
            recompute_candidate_boards(candidate)


@bp.post("/external-directorships")
def record_directorship():
    require(*STAFF)
    b = body()
    company_id = required(b, "external_company_id", "string")
    start_on = required(b, "start_on", "string")
    director_id = optional(b, "director_id", "string")
    candidate_id = optional(b, "candidate_id", "string")
    seat_role = check_enum("seat_role", optional(b, "seat_role", "string", "DIRECTOR"),
                           DIRECTORSHIP_SEAT_ROLE)
    is_audit_chair = optional(b, "is_audit_chair", "boolean", False)
    parse_date(start_on, "start_on")
    if (director_id is None) == (candidate_id is None):
        fail("ERR_DIRECTORSHIP_SUBJECT_INVALID",
             "Exactly one of director_id or candidate_id must be supplied.")
    need("external_company", company_id)
    director = need("director", director_id) if director_id is not None else None
    if candidate_id is not None:
        need("candidate", candidate_id)

    if director is not None:
        policy = governing_policy()
        if policy is not None:
            held = len(public_company_ids(
                [d for d in db.directorships.values() if d.get("director_id") == director_id]))
            limit = overboarding_limit(policy, director["is_sitting_ceo_elsewhere"])
            if held + 1 > limit:
                fail("ERR_OVERBOARDING_LIMIT_EXCEEDED",
                     "The director already holds %s outside public boards against a limit of %s."
                     % (held, limit))

    for row in db.directorships.values():
        if row["status"] != "ACTIVE" or row["external_company_id"] != company_id:
            continue
        if row.get("director_id") == director_id and row.get("candidate_id") == candidate_id:
            fail("ERR_DUPLICATE_RESOURCE",
                 "That subject already holds an ACTIVE seat on this company's board.")

    row = new_row({
        "director_id": director_id,
        "candidate_id": candidate_id,
        "external_company_id": company_id,
        "seat_role": seat_role,
        "is_audit_chair": is_audit_chair,
        "start_on": start_on,
        "end_on": None,
        "status": "ACTIVE",
    })
    db.directorships[row["id"]] = row
    _resettle(row)
    return emit(row, 201)


@bp.get("/external-directorships/<directorship_id>")
def read_directorship(directorship_id):
    require(*READ_ROLES)
    return emit(need("directorship", directorship_id))


@bp.get("/external-directorships")
def list_directorships():
    require(*READ_ROLES)
    rows = apply_filters(list(db.directorships.values()), {
        "director_id": ("director_id", "str"),
        "candidate_id": ("candidate_id", "str"),
        "external_company_id": ("external_company_id", "str"),
        "status": ("status", "str"),
    })
    return emit_list(by_created_at(rows))


@bp.post("/external-directorships/<directorship_id>/end")
def end_directorship(directorship_id):
    require(*STAFF)
    b = body()
    end_on = required(b, "end_on", "string")
    parsed_end = parse_date(end_on, "end_on")
    row = need("directorship", directorship_id)
    check_interval_on_or_after(parsed_end, parse_iso_date(row["start_on"]),
                               "end_on must fall on or after start_on.")
    if row["status"] != "ACTIVE":
        fail("ERR_DIRECTORSHIP_STATE_INVALID",
             "Only an ACTIVE outside seat may be ended; this one is %s." % row["status"])
    row["status"] = "ENDED"
    row["end_on"] = end_on
    touch(row)
    _resettle(row)
    return emit(row)
