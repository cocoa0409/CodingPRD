"""The periodic performance review self-assessment (PRD 3.9)."""

from flask import Blueprint, g, request

import calc
import cascade
import serialize
from auth import ALL_ROLES, require_roles
from envelope import array_response, object_response
from errors import ApiError
from helpers import body, get_chapter, get_ppr, opt_str, page, pagination, req_str
from store import base_entity, db, rows, touch

bp = Blueprint("ppr", __name__)


def _parse_self_ratings(b):
    """Rung 3 shape validation, including the duplicate-standard_id rule."""
    raw = b.get("self_ratings")
    if not isinstance(raw, list):
        raise ApiError("ERR_INVALID_REQUEST", message="'self_ratings' must be an array.")
    parsed = []
    seen = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise ApiError(
                "ERR_INVALID_REQUEST", message="'self_ratings' entries must be objects."
            )
        standard_id = entry.get("standard_id")
        rating = entry.get("rating")
        if not isinstance(standard_id, str) or not standard_id.strip():
            raise ApiError(
                "ERR_INVALID_REQUEST",
                message="'self_ratings[].standard_id' must be a non-empty string.",
            )
        if rating not in calc.RATINGS:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                message="'self_ratings[].rating' must be one of %s." % ", ".join(calc.RATINGS),
            )
        if standard_id in seen:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                message="'self_ratings' contains a repeated standard_id.",
            )
        seen.add(standard_id)
        parsed.append({"standard_id": standard_id, "rating": rating})
    return parsed


def _check_chapter_membership(chapter, self_ratings):
    """Rung 43."""
    member_ids = {s["id"] for s in cascade.standards_of_chapter(chapter["id"])}
    for entry in self_ratings:
        if entry["standard_id"] not in member_ids:
            raise ApiError("ERR_STANDARD_CHAPTER_MISMATCH")


def _apply_scores(assessment, chapter, self_ratings):
    self_score, verified_score, gap = cascade.compute_ppr_scores(chapter, self_ratings)
    assessment["self_ratings"] = self_ratings
    assessment["self_score"] = self_score
    assessment["verified_score"] = verified_score
    assessment["gap"] = gap
    return gap >= calc.OVERSTATEMENT_THRESHOLD


@bp.post("/accreditation/chapters/<chapter_id>/ppr-self-assessments")
def file_assessment(chapter_id):
    require_roles("AccreditationDirector")
    b = body()
    period_label = req_str(b, "period_label")
    self_ratings = _parse_self_ratings(b)

    # Rung 5
    chapter = get_chapter(chapter_id)

    # Rung 11
    for existing in db.pprs.values():
        if existing["chapter_id"] == chapter["id"] and existing["period_label"] == period_label:
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE", message="period_label already filed for this chapter."
            )

    # Rung 43
    _check_chapter_membership(chapter, self_ratings)

    assessment = base_entity("PprSelfAssessment")
    assessment.update(
        {
            "chapter_id": chapter["id"],
            "period_label": period_label,
            "self_ratings": [],
            "self_score": None,
            "verified_score": None,
            "gap": None,
            "flagged_overstatement": False,
            "requires_reassessment": False,
            "state": "SUBMITTED",
            "attested_by_user_id": None,
        }
    )
    flagged = _apply_scores(assessment, chapter, self_ratings)
    assessment["flagged_overstatement"] = flagged
    db.pprs[assessment["id"]] = assessment

    if flagged:
        chapter["ppr_escalation_count"] += 1
        touch(chapter)
        cascade.refresh_chapter_flag(chapter, exclude_ppr_id=assessment["id"])

    return object_response(serialize.ppr(assessment), 201)


@bp.get("/accreditation/chapters/<chapter_id>/ppr-self-assessments")
def list_assessments(chapter_id):
    require_roles(*ALL_ROLES)
    limit, offset = pagination()
    chapter = get_chapter(chapter_id)
    result = [p for p in rows(db.pprs) if p["chapter_id"] == chapter["id"]]
    state = request.args.get("state")
    if state:
        result = [p for p in result if p["state"] == state]
    items, total = page(result, limit, offset)
    return array_response([serialize.ppr(p) for p in items], limit, offset, total)


@bp.post("/accreditation/ppr-self-assessments/<ppr_id>/revise")
def revise_assessment(ppr_id):
    require_roles("AccreditationDirector")
    b = body()
    self_ratings = _parse_self_ratings(b)

    # Rung 5
    assessment = get_ppr(ppr_id)

    # Rung 13
    if assessment["state"] != "RETURNED_FOR_REASSESSMENT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    chapter = db.chapters[assessment["chapter_id"]]

    # Rung 43
    _check_chapter_membership(chapter, self_ratings)

    was_flagged = assessment["flagged_overstatement"]
    flagged = _apply_scores(assessment, chapter, self_ratings)
    assessment["flagged_overstatement"] = flagged
    assessment["requires_reassessment"] = False
    assessment["state"] = "SUBMITTED"
    touch(assessment)

    # A chapter is never charged twice for the same overstatement.
    if flagged and not was_flagged:
        chapter["ppr_escalation_count"] += 1
        touch(chapter)
        cascade.refresh_chapter_flag(chapter, exclude_ppr_id=assessment["id"])

    return object_response(serialize.ppr(assessment))


@bp.post("/accreditation/ppr-self-assessments/<ppr_id>/attest")
def attest_assessment(ppr_id):
    require_roles("AccreditationDirector")
    b = body()
    opt_str(b, "attestation_note")

    assessment = get_ppr(ppr_id)

    # Rung 21
    if assessment["state"] == "ATTESTED":
        raise ApiError("ERR_PPR_ALREADY_ATTESTED")
    if assessment["requires_reassessment"] or assessment["state"] != "SUBMITTED":
        raise ApiError("ERR_PPR_REASSESSMENT_REQUIRED")

    assessment["state"] = "ATTESTED"
    assessment["attested_by_user_id"] = g.user_id
    touch(assessment)
    return object_response(serialize.ppr(assessment))
