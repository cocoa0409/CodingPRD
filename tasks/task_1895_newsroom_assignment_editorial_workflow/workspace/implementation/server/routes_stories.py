"""Story workflow per PRD 3.4-3.7 (pipeline, scheduling, kill, supersede,
correction proposals, analytics ingestion)."""

from flask import request

from .auth import require, require_owner
from .blueprint import bp
from .calc import (
    performance_score,
    priority_score,
    recompute_active_assignment_count,
    recompute_slot_reserved_count,
)
from .envelope import ok_list, ok_obj
from .errors import ApiError, bad_request, invalid_state, not_found
from .serialize import (
    ser_analytics,
    ser_assignment,
    ser_correction,
    ser_review,
    ser_story,
)
from .store import STORE, new_entity, new_measurement, touch
from .util import (
    body,
    opt_dt,
    opt_int,
    opt_str,
    paged,
    pagination_params,
    req_enum,
    req_int,
    req_str,
    sort_created,
)

STORY_READ_ROLES = [
    "Reporter",
    "Photographer",
    "CopyEditor",
    "FactChecker",
    "LegalReviewer",
    "AssignmentEditor",
    "ManagingEditor",
    "NewsDirector",
    "AnalyticsProducer",
]
AUTHOR_ROLES = [
    "Reporter",
    "Photographer",
    "CopyEditor",
    "FactChecker",
    "LegalReviewer",
    "AssignmentEditor",
    "ManagingEditor",
]
DESK_ROLES = ["AssignmentEditor", "ManagingEditor", "NewsDirector"]
REVIEW_TYPES = ("FACT_CHECK", "LEGAL")
VERDICTS = ("PASS", "FAIL")
SEVERITIES = ("MINOR", "MAJOR", "RETRACTION")
ANALYTICS_VARIANTS = ("REALTIME", "SETTLED")

PRE_PUBLICATION_STATES = (
    "DRAFT",
    "IN_EDIT",
    "FACT_CHECK",
    "LEGAL_REVIEW",
    "CLEARED",
    "SCHEDULED",
    "ON_HOLD",
)


def get_story(sid):
    s = STORE.stories.get(sid)
    if s is None:
        not_found("ERR_STORY_NOT_FOUND", "Story")
    return s


@bp.get("/newsroom/stories")
def list_stories():
    require(STORY_READ_ROLES)
    items = list(STORE.stories.values())
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    desk = request.args.get("desk")
    if desk:
        items = [s for s in items if s["desk"] == desk]
    author = request.args.get("author_staff_id")
    if author:
        items = [s for s in items if s["author_staff_id"] == author]
    sup = request.args.get("superseded_by_story_id")
    if sup:
        items = [s for s in items if s["superseded_by_story_id"] == sup]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_story(s) for s in page], limit, offset, total)


@bp.get("/newsroom/stories/<sid>")
def read_story(sid):
    require(STORY_READ_ROLES)
    return ok_obj(ser_story(get_story(sid)))


@bp.patch("/newsroom/stories/<sid>")
def patch_story(sid):
    uid, _role = require(AUTHOR_ROLES)
    s = get_story(sid)
    b = body()
    if "word_count" in b and b["word_count"] is not None:
        word_count = req_int(b, "word_count", minimum=0)
    else:
        word_count = None
    embargo_provided = "embargo_until" in b
    embargo = opt_dt(b, "embargo_until", None) if embargo_provided else None

    # Ownership (priority 6) before state (priority 8).
    require_owner(uid, s["author_staff_id"])
    if s["status"] not in ("DRAFT", "IN_EDIT"):
        invalid_state("Story fields are editable only in DRAFT or IN_EDIT")

    if word_count is not None:
        s["word_count"] = word_count
    if embargo_provided:
        s["embargo_until"] = embargo  # explicit null clears the embargo
    touch(s)
    return ok_obj(ser_story(s))


@bp.post("/newsroom/stories/<sid>/submit-edit")
def submit_edit(sid):
    uid, _role = require(AUTHOR_ROLES)
    s = get_story(sid)
    require_owner(uid, s["author_staff_id"])
    if s["status"] != "DRAFT":
        invalid_state("Story is not in DRAFT")
    has_reporter = any(
        a["story_id"] == s["id"]
        and a["assignment_role"] == "REPORTER"
        and a["status"] in ("ACCEPTED", "COMPLETED")
        for a in STORE.assignments.values()
    )
    if not has_reporter:
        raise ApiError(
            "ERR_NO_REPORTING_ASSIGNMENT",
            422,
            "Story has no ACCEPTED/COMPLETED reporter assignment",
        )
    s["status"] = "IN_EDIT"
    touch(s)
    return ok_obj(ser_story(s))


@bp.post("/newsroom/stories/<sid>/complete-edit")
def complete_edit(sid):
    uid, _role = require(["CopyEditor"])
    s = get_story(sid)
    if s["status"] != "IN_EDIT":
        invalid_state("Story is not in IN_EDIT")
    if uid == s["author_staff_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            422,
            "The copy editor completing an edit must not be the story's author",
        )
    s["status"] = "FACT_CHECK"
    touch(s)
    return ok_obj(ser_story(s))


@bp.post("/newsroom/stories/<sid>/reviews")
def file_review(sid):
    uid, role = require(["FactChecker", "LegalReviewer"])
    s = get_story(sid)
    b = body()
    review_type = req_enum(b, "review_type", REVIEW_TYPES)
    verdict = req_enum(b, "verdict", VERDICTS)
    notes = opt_str(b, "notes", None)
    expected_story_version = req_int(b, "expected_story_version")

    # Role-vs-review_type alignment.
    if role == "FactChecker" and review_type != "FACT_CHECK":
        raise ApiError(
            "ERR_FORBIDDEN", 403, "FactChecker may only file FACT_CHECK reviews"
        )
    if role == "LegalReviewer" and review_type != "LEGAL":
        raise ApiError(
            "ERR_FORBIDDEN", 403, "LegalReviewer may only file LEGAL reviews"
        )

    # OCC (priority 7) before from-state (priority 8).
    if expected_story_version != s["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_story_version does not equal the story's current version",
        )

    expected_state = "FACT_CHECK" if review_type == "FACT_CHECK" else "LEGAL_REVIEW"
    if s["status"] != expected_state:
        invalid_state(
            f"A {review_type} verdict requires the story to be in {expected_state}"
        )

    if uid == s["author_staff_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            422,
            "The reviewer must not be the story's author",
        )

    prior_same_type = [
        r
        for r in STORE.reviews.values()
        if r["story_id"] == s["id"] and r["review_type"] == review_type
    ]
    for r in prior_same_type:
        r["is_current"] = False
    rec = new_measurement()
    rec.update({
        "story_id": s["id"],
        "reviewer_staff_id": uid,
        "review_type": review_type,
        "verdict": verdict,
        "notes": notes,
        "reviewed_story_version": expected_story_version,
        "review_round": len(prior_same_type) + 1,
        "is_current": True,
    })
    STORE.reviews[rec["id"]] = rec

    if verdict == "PASS":
        s["status"] = "LEGAL_REVIEW" if review_type == "FACT_CHECK" else "CLEARED"
    else:
        s["status"] = "IN_EDIT"
    touch(s)
    return ok_obj(ser_review(rec), 201)


@bp.post("/newsroom/stories/<sid>/schedule")
def schedule_story(sid):
    require(["AssignmentEditor"])
    s = get_story(sid)
    b = body()
    slot_id = req_str(b, "slot_id")
    expected_story_version = req_int(b, "expected_story_version")
    slot = STORE.slots.get(slot_id)
    if slot is None:
        not_found("ERR_SLOT_NOT_FOUND", "PublicationSlot")

    # OCC (priority 7) before from-state (priority 8).
    if expected_story_version != s["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_story_version does not equal the story's current version",
        )
    if s["status"] != "CLEARED":
        invalid_state("Story is not CLEARED")
    if slot["status"] != "ACTIVE":
        invalid_state("Slot is not ACTIVE")
    if s["story_type"] != slot["channel"]:
        raise ApiError(
            "ERR_CHANNEL_MISMATCH",
            422,
            "story_type does not match the slot channel",
        )
    if s["embargo_until"] is not None and s["embargo_until"] > slot["window_end"]:
        raise ApiError(
            "ERR_EMBARGO_BEYOND_SLOT",
            422,
            "Story embargo falls after the slot window end",
        )
    if slot["reserved_count"] >= slot["capacity"]:
        raise ApiError(
            "ERR_SLOT_CAPACITY_EXCEEDED", 422, "Slot has no remaining capacity"
        )

    s["slot_id"] = slot["id"]
    s["status"] = "SCHEDULED"
    touch(s)
    recompute_slot_reserved_count(slot["id"])
    return ok_obj(ser_story(s))


@bp.post("/newsroom/stories/<sid>/unschedule")
def unschedule_story(sid):
    require(["AssignmentEditor"])
    s = get_story(sid)
    if s["status"] != "SCHEDULED":
        invalid_state("Story is not SCHEDULED")
    slot_id = s["slot_id"]
    s["slot_id"] = None
    s["status"] = "CLEARED"
    touch(s)
    if slot_id is not None:
        recompute_slot_reserved_count(slot_id)
    return ok_obj(ser_story(s))


@bp.post("/newsroom/stories/<sid>/reopen")
def reopen_story(sid):
    require(["ManagingEditor"])
    s = get_story(sid)
    if s["status"] != "CLEARED":
        invalid_state("Story is not CLEARED")
    s["status"] = "IN_EDIT"
    touch(s)
    return ok_obj(ser_story(s))


@bp.post("/newsroom/stories/<sid>/kill")
def kill_story(sid):
    require(["ManagingEditor"])
    s = get_story(sid)
    if s["status"] not in PRE_PUBLICATION_STATES:
        invalid_state("Only a pre-publication story can be killed")

    was_scheduled = s["status"] == "SCHEDULED"
    slot_id = s["slot_id"]
    affected_staff = set()
    for a in STORE.assignments.values():
        if a["story_id"] == s["id"] and a["status"] in ("PROPOSED", "ACCEPTED"):
            a["status"] = "CANCELLED"
            touch(a)
            affected_staff.add(a["staff_id"])
    for staff_id in affected_staff:
        recompute_active_assignment_count(staff_id)
    if was_scheduled:
        s["slot_id"] = None
    s["status"] = "KILLED"
    touch(s)
    if was_scheduled and slot_id is not None:
        recompute_slot_reserved_count(slot_id)
    return ok_obj(ser_story(s))


@bp.post("/newsroom/stories/<sid>/supersede")
def supersede_story(sid):
    require(["AssignmentEditor"])
    s = get_story(sid)
    b = body()
    superseding_story_id = req_str(b, "superseding_story_id")
    target = STORE.stories.get(superseding_story_id)
    if target is None:
        not_found("ERR_STORY_NOT_FOUND", "Story")
    # Body-schema violations (priority 3) before from-state (priority 8).
    if superseding_story_id == s["id"]:
        bad_request("superseding_story_id must differ from the story being linked")
    if target["status"] in ("RETRACTED", "KILLED"):
        bad_request("superseding_story_id must reference a non-terminal story")
    if s["status"] not in ("PUBLISHED", "RETRACTED"):
        invalid_state("Only a PUBLISHED or RETRACTED story can be superseded")
    s["superseded_by_story_id"] = superseding_story_id
    touch(s)
    return ok_obj(ser_story(s))


@bp.get("/newsroom/stories/<sid>/priority-score")
def story_priority_score(sid):
    require(DESK_ROLES)
    s = get_story(sid)
    variant = request.args.get("variant", "DESK")
    if variant not in ("DESK", "ANALYTICS"):
        bad_request("variant must be DESK or ANALYTICS")
    pitch = STORE.pitches.get(s["pitch_id"])
    if pitch is None:
        not_found("ERR_PITCH_NOT_FOUND", "Pitch")
    return ok_obj({"variant": variant, "score": priority_score(pitch, variant)})


@bp.get("/newsroom/stories/<sid>/assignments")
def story_assignments(sid):
    require(DESK_ROLES)
    get_story(sid)
    items = [a for a in STORE.assignments.values() if a["story_id"] == sid]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_assignment(a) for a in page], limit, offset, total)


@bp.get("/newsroom/stories/<sid>/reviews")
def story_reviews(sid):
    require([
        "CopyEditor",
        "FactChecker",
        "LegalReviewer",
        "AssignmentEditor",
        "ManagingEditor",
        "NewsDirector",
    ])
    get_story(sid)
    items = [r for r in STORE.reviews.values() if r["story_id"] == sid]
    rt = request.args.get("review_type")
    if rt:
        items = [r for r in items if r["review_type"] == rt]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_review(r) for r in page], limit, offset, total)


@bp.get("/newsroom/stories/<sid>/corrections")
def story_corrections(sid):
    require(STORY_READ_ROLES)
    get_story(sid)
    items = [c for c in STORE.corrections.values() if c["story_id"] == sid]
    status = request.args.get("status")
    if status:
        items = [c for c in items if c["status"] == status]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_correction(c) for c in page], limit, offset, total)


@bp.post("/newsroom/stories/<sid>/corrections")
def propose_correction(sid):
    uid, _role = require(AUTHOR_ROLES)
    s = get_story(sid)
    b = body()
    severity = req_enum(b, "severity", SEVERITIES)
    correction_text = req_str(b, "correction_text")
    if s["status"] != "PUBLISHED":
        raise ApiError(
            "ERR_STORY_NOT_PUBLISHED", 409, "Story is not PUBLISHED"
        )
    c = new_entity()
    c.update({
        "story_id": s["id"],
        "proposer_staff_id": uid,
        "severity": severity,
        "correction_text": correction_text,
        "status": "PROPOSED",
        "approver_staff_id": None,
        "correction_number": None,
        "issued_at": None,
    })
    STORE.corrections[c["id"]] = c
    return ok_obj(ser_correction(c), 201)


@bp.get("/newsroom/stories/<sid>/analytics-reports")
def story_analytics(sid):
    require(["AnalyticsProducer", "AssignmentEditor", "ManagingEditor", "NewsDirector"])
    get_story(sid)
    items = [a for a in STORE.analytics.values() if a["story_id"] == sid]
    variant = request.args.get("variant")
    if variant:
        items = [a for a in items if a["variant"] == variant]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_analytics(a) for a in page], limit, offset, total)


@bp.post("/newsroom/stories/<sid>/analytics-reports")
def ingest_analytics(sid):
    require(["AnalyticsProducer"])
    s = get_story(sid)
    b = body()
    variant = req_enum(b, "variant", ANALYTICS_VARIANTS)
    window_start = None
    from .util import req_dt

    window_start = req_dt(b, "window_start")
    window_end = req_dt(b, "window_end")
    views = req_int(b, "views", minimum=0)
    engagement_minutes = req_int(b, "engagement_minutes", minimum=0)

    if s["status"] != "PUBLISHED":
        raise ApiError(
            "ERR_STORY_NOT_PUBLISHED", 409, "Story is not PUBLISHED"
        )
    if window_end <= window_start:
        raise ApiError(
            "ERR_INVALID_INTERVAL", 422, "window_end must be after window_start"
        )
    for a in STORE.analytics.values():
        if (
            a["story_id"] == s["id"]
            and a["variant"] == variant
            and a["window_end"] == window_end
        ):
            raise ApiError(
                "ERR_DUPLICATE_ANALYTICS_WINDOW",
                409,
                "An analytics report already exists for (story_id, variant, window_end)",
            )

    raw, tier, score = performance_score(views, engagement_minutes, variant)
    rec = new_measurement()
    rec.update({
        "story_id": s["id"],
        "variant": variant,
        "window_start": window_start,
        "window_end": window_end,
        "views": views,
        "engagement_minutes": engagement_minutes,
        "raw_score": raw,
        "tier": tier,
        "performance_score": score,
        "status": "ACTIVE",
    })
    STORE.analytics[rec["id"]] = rec
    return ok_obj(ser_analytics(rec), 201)
