"""Corrections governance per PRD 3.6."""

from .auth import require
from .blueprint import bp
from .envelope import ok_obj
from .errors import ApiError, invalid_state, not_found
from .serialize import ser_correction
from .store import STORE, now, touch


def get_correction(cid):
    c = STORE.corrections.get(cid)
    if c is None:
        not_found("ERR_CORRECTION_NOT_FOUND", "Correction")
    return c


@bp.post("/newsroom/corrections/<cid>/approve")
def approve_correction(cid):
    uid, _role = require(["ManagingEditor"])
    c = get_correction(cid)
    if c["status"] != "PROPOSED":
        invalid_state("Correction is not PROPOSED")
    if uid == c["proposer_staff_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            422,
            "The approver must not be the correction's proposer",
        )
    c["status"] = "APPROVED"
    c["approver_staff_id"] = uid
    touch(c)
    return ok_obj(ser_correction(c))


@bp.post("/newsroom/corrections/<cid>/reject")
def reject_correction(cid):
    require(["ManagingEditor"])
    c = get_correction(cid)
    if c["status"] != "PROPOSED":
        invalid_state("Correction is not PROPOSED")
    c["status"] = "REJECTED"
    touch(c)
    return ok_obj(ser_correction(c))


@bp.post("/newsroom/corrections/<cid>/issue")
def issue_correction(cid):
    require(["ManagingEditor"])
    c = get_correction(cid)
    if c["status"] != "APPROVED":
        invalid_state("Correction is not APPROVED")
    story = STORE.stories.get(c["story_id"])
    if story is None:
        not_found("ERR_STORY_NOT_FOUND", "Story")
    if story["status"] != "PUBLISHED":
        raise ApiError(
            "ERR_STORY_NOT_PUBLISHED", 409, "Story is not PUBLISHED"
        )

    prior_issued = sum(
        1
        for x in STORE.corrections.values()
        if x["story_id"] == story["id"] and x["status"] == "ISSUED"
    )
    c["correction_number"] = prior_issued + 1
    c["issued_at"] = now()
    c["status"] = "ISSUED"
    touch(c)

    story["correction_count"] = story.get("correction_count", 0) + 1
    if c["severity"] == "RETRACTION":
        story["status"] = "RETRACTED"
        # Hop 2: every ACTIVE analytics report of the story -> VOID.
        for a in STORE.analytics.values():
            if a["story_id"] == story["id"] and a["status"] == "ACTIVE":
                a["status"] = "VOID"
    touch(story)
    return ok_obj(ser_correction(c))
