"""Conference endpoints."""

import re

from flask import Blueprint

from db import db, new_row, parse_dt, touch
from errors import fail
from middleware import (ROLE_ADMIN, ROLE_AUTHOR, ROLE_CHAIR, ROLE_PRESS,
                        ROLE_REVIEWER, endpoint)
from response import created, ok, ok_list
from routes.helpers import filtered, lookup
from services import calc, derive, logic
from validators import (body_json, paginate, present, q_str, v_datetime, v_enum,
                        v_int, v_string)

bp = Blueprint("conferences", __name__)

CODE_RE = re.compile(r"^[A-Z0-9]{2,12}$")

STATUSES = ("DRAFT", "CFA_OPEN", "CFA_CLOSED", "REVIEW_OPEN", "REVIEW_CLOSED",
            "DECISIONS_RELEASED", "PROGRAM_PUBLISHED")

TRANSITIONS = {
    ("DRAFT", "CFA_OPEN"),
    ("CFA_OPEN", "CFA_CLOSED"),
    ("CFA_CLOSED", "CFA_OPEN"),
    ("CFA_CLOSED", "REVIEW_OPEN"),
    ("REVIEW_OPEN", "REVIEW_CLOSED"),
    ("REVIEW_CLOSED", "REVIEW_OPEN"),
    ("REVIEW_CLOSED", "DECISIONS_RELEASED"),
    ("DECISIONS_RELEASED", "PROGRAM_PUBLISHED"),
}


@bp.post("/conferences")
@endpoint(ROLE_ADMIN)
def create_conference(actor):
    body = body_json()
    name = v_string(body, "name", required=True, min_len=1, max_len=200)
    code = v_string(body, "code", required=True, min_len=2, max_len=12, pattern=CODE_RE)
    event_start = v_datetime(body, "event_start_utc", required=True)
    event_end = v_datetime(body, "event_end_utc", required=True)
    abstract_deadline = v_datetime(body, "abstract_deadline_utc", required=True)
    review_deadline = v_datetime(body, "review_deadline_utc", required=True)
    program_freeze = v_datetime(body, "program_freeze_utc", required=True)
    oral = v_int(body, "oral_slot_capacity", required=True, minimum=0)
    poster = v_int(body, "poster_slot_capacity", required=True, minimum=0)
    workshop = v_int(body, "workshop_slot_capacity", required=True, minimum=0)
    pool = v_int(body, "cme_minutes_pool_total", minimum=0, default=0)

    # Band 15 — temporal coherence of the declared window.
    es, ee = parse_dt(event_start), parse_dt(event_end)
    ad, rd, pf = parse_dt(abstract_deadline), parse_dt(review_deadline), parse_dt(program_freeze)
    if not (ee > es):
        fail("ERR_INVALID_DATE_RANGE", "event_end_utc must be after event_start_utc.")
    if not (ad < es):
        fail("ERR_INVALID_DATE_RANGE", "abstract_deadline_utc must precede event_start_utc.")
    if not (rd > ad):
        fail("ERR_INVALID_DATE_RANGE", "review_deadline_utc must be after abstract_deadline_utc.")
    if not (pf > rd and pf < es):
        fail("ERR_INVALID_DATE_RANGE",
             "program_freeze_utc must be after review_deadline_utc and before event_start_utc.")

    row = new_row({
        "name": name,
        "code": code,
        "status": "DRAFT",
        "event_start_utc": event_start,
        "event_end_utc": event_end,
        "abstract_deadline_utc": abstract_deadline,
        "review_deadline_utc": review_deadline,
        "program_freeze_utc": program_freeze,
        "oral_slot_capacity": oral,
        "poster_slot_capacity": poster,
        "workshop_slot_capacity": workshop,
        "cme_minutes_pool_total": pool,
        "cfa_extension_count": 0,
        "review_reopen_count": 0,
        "abstract_sequence": 0,
    })
    db.conferences[row["id"]] = row
    return created(derive.conference_out(row))


@bp.get("/conferences")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_REVIEWER, ROLE_AUTHOR, ROLE_PRESS)
def list_conferences(actor):
    rows = filtered(db.conferences.values(), {"status": q_str("status")})
    page, meta = paginate(rows)
    return ok_list([derive.conference_out(r) for r in page], meta)


@bp.get("/conferences/<conference_id>")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_REVIEWER, ROLE_AUTHOR, ROLE_PRESS)
def get_conference(actor, conference_id):
    row = lookup("conferences", conference_id, "ERR_CONFERENCE_NOT_FOUND")
    return ok(derive.conference_out(row))


@bp.get("/conferences/<conference_id>/capacity-summary")
@endpoint(ROLE_ADMIN, ROLE_CHAIR)
def capacity_summary(actor, conference_id):
    conference = lookup("conferences", conference_id, "ERR_CONFERENCE_NOT_FOUND")
    accreditations = derive.conference_accreditations(conference_id)
    validated_minutes = [a["content_minutes"] for a in accreditations
                         if a["validation_status"] == "VALIDATED"]
    awarded_sum = sum((derive.awarded_credits(a) for a in accreditations),
                      calc.Decimal("0.00"))
    accredited_sessions = sum(
        1 for s in derive.conference_sessions(conference_id)
        if derive.session_posture(s) == "COMPLIANT")
    return ok({
        "conference_id": conference_id,
        "oral_remaining": derive.remaining_capacity(conference, "ORAL"),
        "poster_remaining": derive.remaining_capacity(conference, "POSTER"),
        "workshop_remaining": derive.remaining_capacity(conference, "WORKSHOP"),
        "waitlisted_count": derive.waitlisted_count(conference_id),
        "cme_minutes_available": derive.cme_minutes_available(conference),
        "cme_bundle_credits": calc.bundle_credits(validated_minutes),
        "awarded_credits_sum": awarded_sum,
        "accredited_session_count": accredited_sessions,
    })


@bp.post("/conferences/<conference_id>/status-transitions")
@endpoint(ROLE_ADMIN)
def conference_status_transition(actor, conference_id):
    conference = lookup("conferences", conference_id, "ERR_CONFERENCE_NOT_FOUND")
    body = body_json()
    to_status = v_enum(body, "to_status", STATUSES, required=True)
    new_deadline = v_datetime(body, "new_abstract_deadline_utc")
    reopen_reason = None
    if present(body, "reopen_reason"):
        reopen_reason = v_string(body, "reopen_reason", min_len=1)

    current = conference["status"]
    if (current, to_status) not in TRANSITIONS:
        fail("ERR_CONFERENCE_STATE_INVALID",
             "Conference cannot move from %s to %s." % (current, to_status))

    now = db.now()

    if to_status == "CFA_OPEN" and current == "DRAFT":
        has_category = any(c["conference_id"] == conference_id for c in db.categories.values())
        if not has_category:
            fail("ERR_CONFERENCE_STATE_INVALID",
                 "At least one submission category must exist before the call for abstracts opens.")
        if not (now < parse_dt(conference["abstract_deadline_utc"])):
            fail("ERR_CFA_DEADLINE_PASSED")
        conference["status"] = "CFA_OPEN"
        touch(conference)

    elif to_status == "CFA_CLOSED":
        conference["status"] = "CFA_CLOSED"
        touch(conference)

    elif to_status == "CFA_OPEN" and current == "CFA_CLOSED":
        if conference["cfa_extension_count"] != 0:
            fail("ERR_CFA_EXTENSION_LIMIT")
        if new_deadline is None:
            fail("ERR_VALIDATION", "new_abstract_deadline_utc is required for a call-for-abstracts extension.")
        nd = parse_dt(new_deadline)
        if not (nd > now):
            fail("ERR_INVALID_DATE_RANGE", "new_abstract_deadline_utc must be in the future.")
        if not (nd > parse_dt(conference["abstract_deadline_utc"])):
            fail("ERR_INVALID_DATE_RANGE",
                 "new_abstract_deadline_utc must be later than the current abstract deadline.")
        if not (nd < parse_dt(conference["review_deadline_utc"])):
            fail("ERR_INVALID_DATE_RANGE",
                 "new_abstract_deadline_utc must precede review_deadline_utc.")
        conference["status"] = "CFA_OPEN"
        conference["abstract_deadline_utc"] = new_deadline
        conference["cfa_extension_count"] = conference["cfa_extension_count"] + 1
        touch(conference)

    elif to_status == "REVIEW_OPEN" and current == "CFA_CLOSED":
        has_submitted = any(a["status"] == "SUBMITTED"
                            for a in derive.conference_abstracts(conference_id))
        if not has_submitted:
            fail("ERR_CONFERENCE_STATE_INVALID",
                 "At least one submitted abstract is required before review opens.")
        conference["status"] = "REVIEW_OPEN"
        touch(conference)

    elif to_status == "REVIEW_CLOSED":
        for case in derive.conference_cases(conference_id):
            if case["status"] in derive.NON_TERMINAL_CASE_STATUSES:
                fail("ERR_OPEN_DISCREPANCY")
        conference["status"] = "REVIEW_CLOSED"
        touch(conference)
        logic.close_review_round(conference)

    elif to_status == "REVIEW_OPEN" and current == "REVIEW_CLOSED":
        if conference["review_reopen_count"] != 0:
            fail("ERR_REVIEW_REOPEN_LIMIT")
        if not reopen_reason:
            fail("ERR_VALIDATION", "reopen_reason is required to reopen review.")
        conference["status"] = "REVIEW_OPEN"
        conference["review_reopen_count"] = conference["review_reopen_count"] + 1
        touch(conference)
        logic.reopen_review_round(conference)

    elif to_status == "DECISIONS_RELEASED":
        for abstract in derive.conference_abstracts(conference_id):
            if abstract["status"] == "SCORED":
                fail("ERR_UNDECIDED_ABSTRACTS_REMAIN")
        conference["status"] = "DECISIONS_RELEASED"
        touch(conference)

    elif to_status == "PROGRAM_PUBLISHED":
        sessions = derive.conference_sessions(conference_id)
        published = [s for s in sessions if s["status"] == "PUBLISHED"]
        if any(s["status"] not in ("PUBLISHED", "CANCELLED") for s in sessions):
            fail("ERR_CONFERENCE_STATE_INVALID",
                 "Every session must be published or cancelled before the program is published.")
        if not published:
            fail("ERR_CONFERENCE_STATE_INVALID",
                 "At least one published session is required before the program is published.")
        conference["status"] = "PROGRAM_PUBLISHED"
        touch(conference)
        logic.lock_published_sessions(conference)

    return ok(derive.conference_out(conference))
