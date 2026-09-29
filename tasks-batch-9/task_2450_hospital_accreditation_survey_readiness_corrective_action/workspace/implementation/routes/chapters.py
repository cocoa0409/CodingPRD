"""Chapters and their standards (PRD 3.1)."""

import re

from flask import Blueprint, request

import calc
import cascade
import serialize
from auth import ALL_ROLES, require_roles
from envelope import array_response, object_response
from errors import ApiError
from helpers import (
    body,
    get_chapter,
    opt_int,
    page,
    pagination,
    req_enum,
    req_number,
    req_str,
)
from store import base_entity, db, rows, touch

bp = Blueprint("chapters", __name__)

CODE_RE = re.compile(r"^[A-Z]{2,4}$")


@bp.post("/accreditation/chapters")
def create_chapter():
    require_roles("AccreditationDirector")
    b = body()
    code = req_str(b, "code")
    if not CODE_RE.match(code):
        raise ApiError(
            "ERR_INVALID_REQUEST", message="'code' must be 2 to 4 uppercase letters."
        )
    name = req_str(b, "name")
    weight_pct = req_number(b, "weight_pct", gt=0, le=100)
    evidence_min_count = opt_int(b, "evidence_min_count", default=2, minimum=1)

    for existing in db.chapters.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_RESOURCE", message="Chapter code already registered.")

    chapter = base_entity("Chapter")
    chapter.update(
        {
            "code": code,
            "name": name,
            "weight_pct": calc.q2(weight_pct),
            "evidence_min_count": evidence_min_count,
            "standard_count": 0,
            "mapped_standard_count": 0,
            "evidence_complete_standard_count": 0,
            "deficient_standard_count": 0,
            "ppr_escalation_count": 0,
            "readiness_flag": "ON_TRACK",
        }
    )
    db.chapters[chapter["id"]] = chapter
    return object_response(serialize.chapter(chapter), 201)


@bp.get("/accreditation/chapters/<chapter_id>")
def read_chapter(chapter_id):
    require_roles(*ALL_ROLES)
    chapter = get_chapter(chapter_id)
    return object_response(serialize.chapter(chapter))


@bp.post("/accreditation/chapters/<chapter_id>/standards")
def create_standard(chapter_id):
    require_roles("AccreditationDirector")
    b = body()
    standard_code = req_str(b, "standard_code")
    title = req_str(b, "title")
    risk_tier = req_enum(b, "risk_tier", calc.RISK_TIERS)

    chapter = get_chapter(chapter_id)

    for existing in db.standards.values():
        if existing["chapter_id"] == chapter["id"] and existing["standard_code"] == standard_code:
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE", message="standard_code already exists in this chapter."
            )

    standard = base_entity("Standard")
    standard.update(
        {
            "chapter_id": chapter["id"],
            "standard_code": standard_code,
            "title": title,
            "risk_tier": risk_tier,
            "compliance_state": "UNMAPPED",
            "active_owner_count": 0,
            "validated_evidence_count": 0,
            "last_noncompliant_observed_at": None,
        }
    )
    db.standards[standard["id"]] = standard

    chapter["standard_count"] += 1
    touch(chapter)

    return object_response(serialize.standard(standard), 201)


@bp.get("/accreditation/chapters/<chapter_id>/standards")
def list_standards(chapter_id):
    require_roles(*ALL_ROLES)
    limit, offset = pagination()
    chapter = get_chapter(chapter_id)
    state_filter = request.args.get("compliance_state")
    result = [s for s in rows(db.standards) if s["chapter_id"] == chapter["id"]]
    if state_filter:
        result = [s for s in result if s["compliance_state"] == state_filter]
    items, total = page(result, limit, offset)
    return array_response([serialize.standard(s) for s in items], limit, offset, total)
