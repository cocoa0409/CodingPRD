"""Abstract endpoints: submission, revision, status, decision, reviews, press."""

from flask import Blueprint

from db import db, new_row, parse_dt, touch
from errors import fail
from middleware import (ROLE_ADMIN, ROLE_AUTHOR, ROLE_CHAIR, ROLE_PRESS,
                        ROLE_REVIEWER, endpoint)
from response import created, ok, ok_list
from routes.helpers import check_occ, filtered, lookup, resolve_fk
from services import calc, derive, logic
from validators import (body_json, paginate, present, q_bool, q_str, v_bool,
                        v_datetime, v_enum, v_int, v_str_list, v_string)

bp = Blueprint("abstracts", __name__)

FORMATS = ("ORAL", "POSTER", "WORKSHOP")
ABSTRACT_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "SCORED", "REVISION_REQUESTED",
                     "ACCEPTED", "WAITLISTED", "REJECTED", "CONFIRMED", "SCHEDULED",
                     "PRESENTED", "NO_SHOW", "WITHDRAWN")
DECISIONS = ("ORAL", "POSTER", "WORKSHOP", "REJECTED")

WITHDRAWABLE = {"SUBMITTED", "UNDER_REVIEW", "SCORED", "WAITLISTED", "ACCEPTED",
                "CONFIRMED", "SCHEDULED"}


def _check_formatting(category, body_word_count, body_structured):
    """Band 16 — ERR_ABSTRACT_FORMAT_INVALID."""
    if body_word_count > category["max_word_count"]:
        fail("ERR_ABSTRACT_FORMAT_INVALID",
             "body_word_count exceeds the category word ceiling.")
    if category["requires_structured_body"] and not body_structured:
        fail("ERR_ABSTRACT_FORMAT_INVALID",
             "This category requires a structured body.")


@bp.post("/abstracts")
@endpoint(ROLE_AUTHOR)
def create_abstract(actor):
    body = body_json()
    conference = resolve_fk(body, "conference_id")
    category = resolve_fk(body, "category_id")
    author = resolve_fk(body, "submitting_author_id")

    title = v_string(body, "title", required=True, min_len=1, max_len=300)
    body_word_count = v_int(body, "body_word_count", required=True, minimum=1)
    body_structured = v_bool(body, "body_structured", default=False)
    requested_format = v_enum(body, "requested_format", FORMATS, required=True)
    keywords = v_str_list(body, "keywords", required=True, min_items=1, max_items=5,
                          unique=True, lower=True)
    coauthor_emails = v_str_list(body, "coauthor_emails", min_items=0, max_items=10,
                                 lower=True, default=[])
    is_newsworthy = v_bool(body, "is_newsworthy", default=False)
    if conference is None:
        fail("ERR_VALIDATION", "conference_id is required.")
    if category is None:
        fail("ERR_VALIDATION", "category_id is required.")
    if author is None:
        fail("ERR_VALIDATION", "submitting_author_id is required.")
    if coauthor_emails is None:
        coauthor_emails = []
    if author["email"] in coauthor_emails:
        fail("ERR_VALIDATION",
             "coauthor_emails must not contain the submitting author's email.")

    # Band 9 — conference gate.
    if conference["status"] != "CFA_OPEN":
        fail("ERR_CONFERENCE_STATE_INVALID", "The call for abstracts is not open.")
    # Band 12 — sanctions.
    if derive.is_barred(author):
        fail("ERR_AUTHOR_BARRED")
    # Band 14 — referential coherence.
    if category["conference_id"] != conference["id"]:
        fail("ERR_CATEGORY_CONFERENCE_MISMATCH")
    if requested_format not in category["allowed_formats"]:
        fail("ERR_FORMAT_NOT_ALLOWED")
    # Band 15 — temporal.
    if db.now() > parse_dt(conference["abstract_deadline_utc"]):
        fail("ERR_CFA_DEADLINE_PASSED")
    # Band 16 — formatting.
    _check_formatting(category, body_word_count, body_structured)

    conference["abstract_sequence"] = conference["abstract_sequence"] + 1
    blind_code = "%s-B%04d" % (conference["code"], conference["abstract_sequence"])
    touch(conference)

    row = new_row({
        "conference_id": conference["id"],
        "category_id": category["id"],
        "submitting_author_id": author["id"],
        "title": title,
        "body_word_count": body_word_count,
        "body_structured": bool(body_structured),
        "requested_format": requested_format,
        "keywords": keywords,
        "coauthor_emails": coauthor_emails,
        "is_newsworthy": bool(is_newsworthy),
        "blind_code": blind_code,
        "status": "SUBMITTED",
        "revision_round": 0,
        "provisional_score": None,
        "final_score": None,
        "score_spread": None,
        "decision": None,
        "decision_downgraded": False,
        "decided_by_member_id": None,
        "embargo_status": "NONE",
        "embargo_until_utc": None,
        "press_outlet_name": None,
    })
    db.abstracts[row["id"]] = row
    return created(derive.abstract_out(row))


@bp.get("/abstracts")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_REVIEWER, ROLE_AUTHOR, ROLE_PRESS)
def list_abstracts(actor):
    rows = filtered(db.abstracts.values(), {
        "conference_id": q_str("conference_id"),
        "category_id": q_str("category_id"),
        "submitting_author_id": q_str("submitting_author_id"),
        "decided_by_member_id": q_str("decided_by_member_id"),
        "status": q_str("status"),
        "requested_format": q_str("requested_format"),
        "decision": q_str("decision"),
        "embargo_status": q_str("embargo_status"),
        "is_newsworthy": q_bool("is_newsworthy"),
    })
    page, meta = paginate(rows)
    return ok_list([derive.abstract_out(r) for r in page], meta)


@bp.get("/abstracts/<abstract_id>")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_REVIEWER, ROLE_AUTHOR, ROLE_PRESS)
def get_abstract(actor, abstract_id):
    row = lookup("abstracts", abstract_id, "ERR_ABSTRACT_NOT_FOUND")
    return ok(derive.abstract_out(row))


# ---------------------------------------------------------------------------
# revisions
# ---------------------------------------------------------------------------

@bp.post("/abstracts/<abstract_id>/revisions")
@endpoint(ROLE_AUTHOR)
def revise_abstract(actor, abstract_id):
    abstract = lookup("abstracts", abstract_id, "ERR_ABSTRACT_NOT_FOUND")
    # Band 6 — ownership.
    if actor.author_id != abstract["submitting_author_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")

    body = body_json()
    body_word_count = v_int(body, "body_word_count", required=True, minimum=1)
    title = v_string(body, "title", min_len=1, max_len=300)
    body_structured = v_bool(body, "body_structured")
    keywords = v_str_list(body, "keywords", min_items=1, max_items=5, unique=True,
                          lower=True)

    conference = logic.conference_of(abstract)
    category = logic.category_of(abstract)

    # Band 9 / 10.
    if conference["status"] != "REVIEW_OPEN":
        fail("ERR_CONFERENCE_STATE_INVALID", "Revisions are only accepted while review is open.")
    if abstract["status"] != "REVISION_REQUESTED":
        fail("ERR_ABSTRACT_STATE_INVALID")
    # Band 15.
    if db.now() > parse_dt(conference["review_deadline_utc"]):
        fail("ERR_CFA_DEADLINE_PASSED")
    # Band 16.
    effective_structured = abstract["body_structured"] if body_structured is None else body_structured
    _check_formatting(category, body_word_count, effective_structured)
    # Band 17.
    if abstract["revision_round"] >= 2:
        fail("ERR_REVISION_LIMIT_REACHED")

    abstract["body_word_count"] = body_word_count
    if title is not None:
        abstract["title"] = title
    if body_structured is not None:
        abstract["body_structured"] = body_structured
    if keywords is not None:
        abstract["keywords"] = keywords
    abstract["revision_round"] = abstract["revision_round"] + 1
    abstract["status"] = "SUBMITTED"
    abstract["provisional_score"] = None
    abstract["final_score"] = None
    abstract["score_spread"] = None
    touch(abstract)
    return ok(derive.abstract_out(abstract))


# ---------------------------------------------------------------------------
# status transitions
# ---------------------------------------------------------------------------

@bp.post("/abstracts/<abstract_id>/status-transitions")
@endpoint(ROLE_CHAIR, ROLE_AUTHOR)
def abstract_status_transition(actor, abstract_id):
    abstract = lookup("abstracts", abstract_id, "ERR_ABSTRACT_NOT_FOUND")
    conference = logic.conference_of(abstract)

    # Band 6 — ownership.
    if actor.is_author:
        if actor.author_id != abstract["submitting_author_id"]:
            fail("ERR_NOT_RESOURCE_OWNER")
    else:
        if actor.member["conference_id"] != abstract["conference_id"]:
            fail("ERR_NOT_RESOURCE_OWNER")

    body = body_json()
    to_status = v_enum(body, "to_status", ABSTRACT_STATUSES, required=True)
    if present(body, "reason"):
        v_string(body, "reason", min_len=1)

    if to_status == "REVISION_REQUESTED":
        if not actor.is_chair:
            fail("ERR_UNAUTHORIZED", "Only a program chair may request a revision.")
        if conference["status"] != "REVIEW_OPEN":
            fail("ERR_CONFERENCE_STATE_INVALID")
        if abstract["status"] != "SCORED":
            fail("ERR_ABSTRACT_STATE_INVALID")
        if abstract["revision_round"] >= 2:
            fail("ERR_REVISION_LIMIT_REACHED")
        if derive.open_case_for_abstract(abstract_id) is not None:
            fail("ERR_OPEN_DISCREPANCY")
        abstract["status"] = "REVISION_REQUESTED"
        touch(abstract)
        logic.void_assigned_reviews(derive.abstract_reviews(abstract_id))

    elif to_status == "CONFIRMED":
        if not actor.is_author:
            fail("ERR_UNAUTHORIZED", "Only the submitting author may confirm attendance.")
        if conference["status"] not in ("DECISIONS_RELEASED", "PROGRAM_PUBLISHED"):
            fail("ERR_CONFERENCE_STATE_INVALID")
        if abstract["status"] != "ACCEPTED":
            fail("ERR_ABSTRACT_STATE_INVALID")
        author = db.authors.get(abstract["submitting_author_id"])
        if derive.is_barred(author):
            fail("ERR_AUTHOR_BARRED")
        if not (author and author["is_registered"]):
            fail("ERR_AUTHOR_NOT_REGISTERED")
        abstract["status"] = "CONFIRMED"
        touch(abstract)

    elif to_status == "SCORED":
        if not actor.is_chair:
            fail("ERR_UNAUTHORIZED", "Only a program chair may rescind an acceptance.")
        if conference["status"] not in ("REVIEW_CLOSED", "DECISIONS_RELEASED"):
            fail("ERR_CONFERENCE_STATE_INVALID")
        if abstract["status"] != "ACCEPTED":
            fail("ERR_ABSTRACT_STATE_INVALID")
        for slot in derive.abstract_slots(abstract_id):
            if slot["status"] == "SCHEDULED":
                fail("ERR_ABSTRACT_STATE_INVALID",
                     "A scheduled session slot still references this abstract.")
        released_format = abstract["decision"]
        released_by = abstract["decided_by_member_id"]
        abstract["status"] = "SCORED"
        abstract["decision"] = None
        abstract["decision_downgraded"] = False
        abstract["decided_by_member_id"] = None
        touch(abstract)
        if released_format is not None and released_format != "REJECTED":
            touch(conference)
            logic.promote_from_waitlist(conference, released_format, released_by)

    elif to_status == "WITHDRAWN":
        if abstract["status"] not in WITHDRAWABLE:
            fail("ERR_ABSTRACT_STATE_INVALID")
        scheduled = [s for s in derive.abstract_slots(abstract_id)
                     if s["status"] == "SCHEDULED"]
        if scheduled and db.now() >= parse_dt(conference["program_freeze_utc"]):
            if not _has_applied_withdraw_request(scheduled):
                fail("ERR_PROGRAM_FROZEN")
        logic.withdraw_abstract(abstract)

    else:
        fail("ERR_ABSTRACT_STATE_INVALID",
             "Abstract cannot move from %s to %s." % (abstract["status"], to_status))

    return ok(derive.abstract_out(abstract))


def _has_applied_withdraw_request(slots):
    slot_ids = {s["id"] for s in slots}
    for request_row in db.change_requests.values():
        if (request_row["session_slot_id"] in slot_ids
                and request_row["change_type"] == "WITHDRAW"
                and request_row["status"] == "APPLIED"):
            return True
    return False


# ---------------------------------------------------------------------------
# decision — format capacity waterfall
# ---------------------------------------------------------------------------

@bp.post("/abstracts/<abstract_id>/decision")
@endpoint(ROLE_CHAIR)
def decide_abstract(actor, abstract_id):
    abstract = lookup("abstracts", abstract_id, "ERR_ABSTRACT_NOT_FOUND")
    conference = logic.conference_of(abstract)
    category = logic.category_of(abstract)

    body = body_json()
    decision = v_enum(body, "decision", DECISIONS, required=True)
    allow_downgrade = v_bool(body, "allow_format_downgrade", default=False)
    # Band 8 — optimistic concurrency on the conference ledger.
    check_occ(body, "expected_conference_version", conference["version"],
              "ERR_STALE_CONFERENCE_VERSION")

    # Band 9 / 10.
    if conference["status"] != "REVIEW_CLOSED":
        fail("ERR_CONFERENCE_STATE_INVALID", "Decisions are released from REVIEW_CLOSED.")
    if abstract["status"] != "SCORED":
        fail("ERR_ABSTRACT_STATE_INVALID")
    # Band 11 — segregation of duties.
    for review in derive.abstract_reviews(abstract_id):
        if review["reviewer_member_id"] == actor.member_id and review["status"] == "SUBMITTED":
            fail("ERR_SEGREGATION_VIOLATION")
    # Band 14 — referential coherence.
    if decision != "REJECTED" and decision not in category["allowed_formats"]:
        fail("ERR_FORMAT_NOT_ALLOWED")
    # Band 17 — review workflow.
    if derive.submitted_review_count(abstract) < category["min_reviews_required"]:
        fail("ERR_INSUFFICIENT_REVIEWS")
    if derive.open_case_for_abstract(abstract_id) is not None:
        fail("ERR_OPEN_DISCREPANCY")

    if decision == "REJECTED":
        abstract["status"] = "REJECTED"
        abstract["decision"] = "REJECTED"
        abstract["decision_downgraded"] = False
        abstract["decided_by_member_id"] = actor.member_id
        touch(abstract)
        touch(conference)
        return ok(derive.abstract_out(abstract))

    outcome, resolved = _waterfall(conference, category, decision, allow_downgrade)
    if outcome == "COMMIT":
        abstract["status"] = "ACCEPTED"
        abstract["decision"] = resolved
        abstract["decision_downgraded"] = resolved != decision
        abstract["decided_by_member_id"] = actor.member_id
    else:
        abstract["status"] = "WAITLISTED"
        abstract["decision"] = None
        abstract["decision_downgraded"] = False
        abstract["decided_by_member_id"] = actor.member_id
    touch(abstract)
    touch(conference)
    return ok(derive.abstract_out(abstract))


def _waterfall(conference, category, decision, allow_downgrade):
    """Band 21 — format_capacity_waterfall."""
    if decision == "WORKSHOP":
        if derive.remaining_capacity(conference, "WORKSHOP") >= 1:
            return "COMMIT", "WORKSHOP"
        fail("ERR_FORMAT_CAPACITY_EXHAUSTED")
    if decision == "ORAL":
        if derive.remaining_capacity(conference, "ORAL") >= 1:
            return "COMMIT", "ORAL"
        if not allow_downgrade:
            fail("ERR_FORMAT_CAPACITY_EXHAUSTED")
        if ("POSTER" in category["allowed_formats"]
                and derive.remaining_capacity(conference, "POSTER") >= 1):
            return "COMMIT", "POSTER"
        return "WAITLIST", None
    if decision == "POSTER":
        if derive.remaining_capacity(conference, "POSTER") >= 1:
            return "COMMIT", "POSTER"
        if not allow_downgrade:
            fail("ERR_FORMAT_CAPACITY_EXHAUSTED")
        return "WAITLIST", None
    fail("ERR_VALIDATION", "Unsupported decision value.")


# ---------------------------------------------------------------------------
# review assignments
# ---------------------------------------------------------------------------

@bp.post("/abstracts/<abstract_id>/review-assignments")
@endpoint(ROLE_CHAIR)
def assign_review(actor, abstract_id):
    abstract = lookup("abstracts", abstract_id, "ERR_ABSTRACT_NOT_FOUND")
    conference = logic.conference_of(abstract)

    body = body_json()
    reviewer = resolve_fk(body, "reviewer_member_id")
    due_utc = v_datetime(body, "due_utc")

    # Band 9 / 10.
    if conference["status"] != "REVIEW_OPEN":
        fail("ERR_CONFERENCE_STATE_INVALID", "Reviews are assigned while review is open.")
    if abstract["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        fail("ERR_ABSTRACT_STATE_INVALID")

    if reviewer is not None:
        if (reviewer["conference_id"] != abstract["conference_id"]
                or reviewer["status"] != "ACTIVE"
                or reviewer["coi_declaration_status"] != "SUBMITTED"):
            fail("ERR_MEMBER_STATE_INVALID")
        # Band 11 — conflict of interest.
        if (logic.member_has_conflict(reviewer["id"], abstract)
                or logic.member_is_author(reviewer, abstract)):
            fail("ERR_REVIEWER_CONFLICT")
        # Band 17 — duplicate assignment.
        if logic.member_holds_live_review(reviewer["id"], abstract_id):
            fail("ERR_DUPLICATE_REVIEW_ASSIGNMENT")
        # Band 21 — reviewer load ledger.
        if derive.current_review_load(reviewer["id"]) >= reviewer["max_review_load"]:
            fail("ERR_REVIEWER_LOAD_EXCEEDED")
    else:
        reviewer = logic.select_reviewer(abstract)
        if reviewer is None:
            fail("ERR_NO_ELIGIBLE_REVIEWER")

    review = logic.create_review(abstract, reviewer, due_utc=due_utc)
    return created(derive.review_out(review))


# ---------------------------------------------------------------------------
# press actions — embargo lifecycle
# ---------------------------------------------------------------------------

@bp.post("/abstracts/<abstract_id>/press-actions")
@endpoint(ROLE_PRESS)
def press_action(actor, abstract_id):
    abstract = lookup("abstracts", abstract_id, "ERR_ABSTRACT_NOT_FOUND")
    conference = logic.conference_of(abstract)

    body = body_json()
    action = v_enum(body, "action", ("SET_EMBARGO", "RELEASE"), required=True)
    embargo_until = v_datetime(body, "embargo_until_utc")
    outlet_name = v_string(body, "outlet_name", min_len=1, max_len=200)

    if action == "SET_EMBARGO":
        if abstract["embargo_status"] != "NONE":
            fail("ERR_ABSTRACT_STATE_INVALID", "An embargo decision already exists.")
        if abstract["status"] not in ("ACCEPTED", "CONFIRMED", "SCHEDULED"):
            fail("ERR_ABSTRACT_STATE_INVALID")
        if embargo_until is None:
            fail("ERR_EMBARGO_WINDOW_INVALID", "embargo_until_utc is required.")
        until = parse_dt(embargo_until)
        if not (until > db.now()):
            fail("ERR_EMBARGO_WINDOW_INVALID",
                 "embargo_until_utc must be later than the current instant.")
        if not (until <= parse_dt(conference["event_end_utc"])):
            fail("ERR_EMBARGO_WINDOW_INVALID",
                 "embargo_until_utc must not exceed event_end_utc.")
        if not abstract["is_newsworthy"]:
            fail("ERR_NOT_NEWSWORTHY")
        abstract["embargo_status"] = "EMBARGOED"
        abstract["embargo_until_utc"] = embargo_until
        if outlet_name is not None:
            abstract["press_outlet_name"] = outlet_name
        touch(abstract)
        return ok(derive.abstract_out(abstract))

    # RELEASE
    if abstract["embargo_status"] in ("RELEASED", "BREACHED"):
        fail("ERR_ABSTRACT_STATE_INVALID", "The embargo has already been resolved.")
    if abstract["embargo_status"] == "NONE":
        fail("ERR_EMBARGO_NOT_SET")
    if outlet_name is None:
        fail("ERR_VALIDATION", "outlet_name is required to release an embargo.")
    until = parse_dt(abstract["embargo_until_utc"])
    if db.now() >= until:
        abstract["embargo_status"] = "RELEASED"
        abstract["press_outlet_name"] = outlet_name
        touch(abstract)
    else:
        logic.record_embargo_breach(abstract, outlet_name)
    return ok(derive.abstract_out(abstract))
