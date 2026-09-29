"""Adoption endpoints (PRD 3.3) including the title-change cascade of PRD 3.7."""

from datetime import timedelta

from flask import Blueprint

from auth import (ROLE_BURSAR, ROLE_COMPLIANCE, ROLE_FACULTY, ROLE_PROGRAM_ADMIN,
                  ROLE_REGISTRAR, authenticate)
from domain import (adoption_json, adoptions_of_section, agreement_of_adoption,
                    approved_adoptions, get_adoption, get_section, get_term,
                    get_title, mark_agreement_stale, rebill, recompute_section,
                    tiers_of_title, title_of_adoption)
from errors import fail
from response import apply_filters, object_response, paginate
from store import base_record, db, in_order, now, today, touch
from validate import f_date, f_int, f_str, get_body

bp = Blueprint("adoptions", __name__)

READ_ROLES = (ROLE_PROGRAM_ADMIN, ROLE_FACULTY, ROLE_REGISTRAR, ROLE_BURSAR,
              ROLE_COMPLIANCE)

APPROVE_EVENT = "POST /adoptions/{adoption_id}/approve"


def _validate_access_window(term, start, end):
    if end <= start:
        fail("ERR_ACCESS_WINDOW_INVALID")
    if start < term["term_start_date"]:
        fail("ERR_ACCESS_WINDOW_INVALID")
    if end > term["term_end_date"] + timedelta(days=1):
        fail("ERR_ACCESS_WINDOW_INVALID")


@bp.post("/adoptions")
def create_adoption():
    actor = authenticate(ROLE_FACULTY)
    body = get_body(("section_id", "title_id", "access_start_date", "access_end_date",
                     "expected_section_version", "supersedes_adoption_id"))
    section_id = f_str(body, "section_id")
    title_id = f_str(body, "title_id")
    access_start = f_date(body, "access_start_date")
    access_end = f_date(body, "access_end_date")
    expected_version = f_int(body, "expected_section_version")
    supersedes_id = f_str(body, "supersedes_adoption_id", required=False, default=None)

    # Body foreign keys resolve in declaration order: title_id, then section_id,
    # then supersedes_adoption_id (PRD 2.11).
    title = get_title(title_id)
    section = get_section(section_id)
    superseded = get_adoption(supersedes_id) if supersedes_id is not None else None
    term = get_term(section["term_id"])

    if actor.user_id != section["instructor_user_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")
    if expected_version != section["version"]:
        fail("ERR_STALE_SECTION_VERSION")

    if superseded is not None:
        if (superseded["section_id"] != section["id"]
                or superseded["status"] != "APPROVED"
                or superseded["title_id"] == title["id"]):
            fail("ERR_SUPERSEDE_TARGET_INVALID")

    _validate_access_window(term, access_start, access_end)

    adoption = base_record()
    adoption.update({
        "section_id": section["id"],
        "title_id": title["id"],
        "supersedes_adoption_id": superseded["id"] if superseded is not None else None,
        "status": "DRAFT",
        "access_start_date": access_start,
        "access_end_date": access_end,
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "submitted_at": None,
        "approved_at": None,
        "locked_list_price_cents": None,
        "change_note": None,
        "revision_count": 0,
        "requires_rebill": False,
    })
    db.adoptions[adoption["id"]] = adoption
    return object_response(adoption_json(adoption), 201)


@bp.get("/adoptions/<adoption_id>")
def read_adoption(adoption_id):
    authenticate(*READ_ROLES)
    return object_response(adoption_json(get_adoption(adoption_id)))


@bp.get("/adoptions")
def list_adoptions():
    authenticate(*READ_ROLES)
    items = apply_filters(in_order(db.adoptions.values()), [
        ("section_id", "section_id"),
        ("title_id", "title_id"),
        ("supersedes_adoption_id", "supersedes_adoption_id"),
        ("status", "status"),
    ])
    return paginate(items, adoption_json)


@bp.post("/adoptions/<adoption_id>/submit")
def submit_adoption(adoption_id):
    actor = authenticate(ROLE_FACULTY)
    get_body(())
    adoption = get_adoption(adoption_id)
    section = get_section(adoption["section_id"])
    term = get_term(section["term_id"])

    if actor.user_id != section["instructor_user_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")
    if adoption["status"] not in ("DRAFT", "CHANGE_REQUESTED"):
        fail("ERR_INVALID_STATE")
    if term["status"] not in ("PLANNING", "OPEN"):
        fail("ERR_TERM_NOT_OPEN")
    if adoption["supersedes_adoption_id"] is None:
        if today() > term["adoption_deadline_date"]:
            fail("ERR_ADOPTION_DEADLINE_PASSED")

    if adoption["status"] == "CHANGE_REQUESTED":
        adoption["revision_count"] += 1
    adoption["status"] = "SUBMITTED"
    adoption["submitted_by_user_id"] = actor.user_id
    adoption["submitted_at"] = now()
    touch(adoption)
    return object_response(adoption_json(adoption))


@bp.post("/adoptions/<adoption_id>/request-change")
def request_change(adoption_id):
    authenticate(ROLE_PROGRAM_ADMIN)
    body = get_body(("change_note",))
    note = f_str(body, "change_note")
    adoption = get_adoption(adoption_id)
    if adoption["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE")
    adoption["status"] = "CHANGE_REQUESTED"
    adoption["change_note"] = note
    touch(adoption)
    return object_response(adoption_json(adoption))


def _concurrent_title_limit_ok(section, candidate):
    """Per-date test over the candidate's half-open window."""
    others = [a for a in adoptions_of_section(section["id"])
              if a["status"] == "APPROVED" and a["id"] != candidate["id"]]
    day = candidate["access_start_date"]
    while day < candidate["access_end_date"]:
        count = 1  # the candidate itself
        for other in others:
            if other["access_start_date"] <= day < other["access_end_date"]:
                count += 1
        if count > section["max_concurrent_titles"]:
            return False
        day = day + timedelta(days=1)
    return True


@bp.post("/adoptions/<adoption_id>/approve")
def approve_adoption(adoption_id):
    actor = authenticate(ROLE_PROGRAM_ADMIN)
    get_body(())
    adoption = get_adoption(adoption_id)
    section = get_section(adoption["section_id"])
    term = get_term(section["term_id"])
    title = title_of_adoption(adoption)
    agreement = agreement_of_adoption(adoption)

    if adoption["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE")
    if term["status"] not in ("PLANNING", "OPEN"):
        fail("ERR_TERM_NOT_OPEN")
    if actor.user_id == adoption["submitted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    if agreement["status"] != "ACTIVE":
        fail("ERR_AGREEMENT_NOT_ACTIVE")
    if title["status"] != "ACTIVE":
        fail("ERR_TITLE_WITHDRAWN")
    if (agreement["effective_from"] > term["term_start_date"]
            or agreement["effective_to"] <= term["term_end_date"]):
        fail("ERR_AGREEMENT_WINDOW_MISMATCH")

    superseded = None
    if adoption["supersedes_adoption_id"] is not None:
        superseded = db.adoptions.get(adoption["supersedes_adoption_id"])
        if (superseded is None
                or superseded["section_id"] != section["id"]
                or superseded["status"] != "APPROVED"
                or superseded["title_id"] == adoption["title_id"]):
            fail("ERR_SUPERSEDE_TARGET_INVALID")

    if not _concurrent_title_limit_ok(section, adoption):
        fail("ERR_CONCURRENT_TITLE_LIMIT")
    if not tiers_of_title(title["id"]):
        fail("ERR_NO_PRICING_TIER")

    adoption["status"] = "APPROVED"
    adoption["locked_list_price_cents"] = title["list_price_cents"]
    adoption["approved_by_user_id"] = actor.user_id
    adoption["approved_at"] = now()
    touch(adoption)

    if superseded is not None:
        old_agreement = agreement_of_adoption(superseded)
        # Hop one: the superseded adoption leaves APPROVED.
        superseded["status"] = "SUPERSEDED"
        touch(superseded)
        # Hop two: the rebill proper.
        rebilled = rebill(adoption, superseded, section, APPROVE_EVENT)
        if rebilled:
            adoption["requires_rebill"] = True
        # Hop three: the section's derived fields.
        recompute_section(section)
        # Hop four: the pricing agreement goes stale.
        mark_agreement_stale(old_agreement)
        mark_agreement_stale(agreement)

    return object_response(adoption_json(adoption))


@bp.post("/adoptions/<adoption_id>/withdraw")
def withdraw_adoption(adoption_id):
    authenticate(ROLE_PROGRAM_ADMIN)
    get_body(())
    adoption = get_adoption(adoption_id)
    section = get_section(adoption["section_id"])
    term = get_term(section["term_id"])

    if adoption["status"] != "APPROVED":
        fail("ERR_INVALID_STATE")
    if section["ia_status"] not in ("NOT_FLAGGED", "FLAGGED"):
        fail("ERR_INVALID_STATE")

    adoption["status"] = "WITHDRAWN"
    touch(adoption)

    if not approved_adoptions(section["id"]):
        if section["inclusive_access_flag"] or section["ia_status"] != "NOT_FLAGGED":
            section["inclusive_access_flag"] = False
            section["ia_status"] = "NOT_FLAGGED"
            touch(section)
            touch(term)
    return object_response(adoption_json(adoption))
