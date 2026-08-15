"""FindingAid routes (PRD §3.3) — review loop with origin-stamped return routing."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE
from middleware import require_roles, ANY_ROLE
from response import success_object, success_list
from services.rollup import recompute_collection
from util import get_json_body, as_str, paginate, public_view

bp = Blueprint("finding_aids", __name__)


def serialize_aid(fa: dict) -> dict:
    return public_view(fa)


def _get_aid(fid: str) -> dict:
    fa = db.finding_aids.get(fid)
    if fa is None:
        raise_err(ERR_NOT_FOUND, f"FindingAid not found: {fid}")
    return fa


@bp.route("/finding-aids", methods=["POST"])
@require_roles("Archivist")
def create_finding_aid(_user_id: str, _role: str):
    body = get_json_body()
    collection_id = as_str(body, "collection_id", required=True)
    title = as_str(body, "title", required=True)
    summary = as_str(body, "summary", required=True)
    scope_note = as_str(body, "scope_note", required=False, default=None)

    coll = db.collections.get(collection_id)
    if coll is None:
        raise_err(ERR_NOT_FOUND, f"Collection not found: {collection_id}")
    if coll["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Finding aids may be created only for ACTIVE collections")

    fa = {
        **db.make_common_fields(),
        "collection_id": collection_id,
        "title": title,
        "summary": summary,
        "scope_note": scope_note,
        "status": "DRAFT",
        "review_origin": None,
        "published_revision_count": 0,
        "published_at": None,
    }
    db.finding_aids[fa["id"]] = fa
    return success_object(serialize_aid(fa), 201)


@bp.route("/finding-aids", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_finding_aids(_user_id: str, _role: str):
    collection_id = request.args.get("collection_id")
    status = request.args.get("status")
    rows = list(db.finding_aids.values())
    if collection_id is not None:
        rows = [f for f in rows if f["collection_id"] == collection_id]
    if status is not None:
        rows = [f for f in rows if f["status"] == status]
    page, limit, offset, total = paginate(rows)
    return success_list([serialize_aid(f) for f in page], limit, offset, total)


@bp.route("/finding-aids/<fid>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_finding_aid(fid: str, _user_id: str, _role: str):
    return success_object(serialize_aid(_get_aid(fid)))


@bp.route("/finding-aids/<fid>/submit-review", methods=["POST"])
@require_roles("Archivist")
def submit_review(fid: str, _user_id: str, _role: str):
    fa = _get_aid(fid)
    if fa["status"] not in ("DRAFT", "IN_REVISION"):
        raise_err(ERR_INVALID_STATE, "Only DRAFT or IN_REVISION aids may be submitted for review")
    fa["review_origin"] = fa["status"]
    fa["status"] = "IN_REVIEW"
    db.touch(fa)
    return success_object(serialize_aid(fa))


@bp.route("/finding-aids/<fid>/publish", methods=["POST"])
@require_roles("Archivist")
def publish(fid: str, _user_id: str, _role: str):
    fa = _get_aid(fid)
    if fa["status"] != "IN_REVIEW":
        raise_err(ERR_INVALID_STATE, "Only an IN_REVIEW finding aid may be published")
    fa["status"] = "PUBLISHED"
    fa["published_revision_count"] += 1
    fa["published_at"] = db.now_iso()
    db.touch(fa)
    coll = db.collections.get(fa["collection_id"])
    if coll is not None:
        recompute_collection(coll)
    return success_object(serialize_aid(fa))


@bp.route("/finding-aids/<fid>/return", methods=["POST"])
@require_roles("Archivist")
def return_aid(fid: str, _user_id: str, _role: str):
    fa = _get_aid(fid)
    if fa["status"] != "IN_REVIEW":
        raise_err(ERR_INVALID_STATE, "Only an IN_REVIEW finding aid may be returned")
    # origin-dependent routing: back to the stamped origin state
    fa["status"] = fa["review_origin"] if fa["review_origin"] in ("DRAFT", "IN_REVISION") else "DRAFT"
    fa["review_origin"] = None
    db.touch(fa)
    return success_object(serialize_aid(fa))


@bp.route("/finding-aids/<fid>/open-revision", methods=["POST"])
@require_roles("Archivist")
def open_revision(fid: str, _user_id: str, _role: str):
    fa = _get_aid(fid)
    if fa["status"] != "PUBLISHED":
        raise_err(ERR_INVALID_STATE, "Only a PUBLISHED finding aid may be reopened for revision")
    fa["status"] = "IN_REVISION"
    db.touch(fa)
    coll = db.collections.get(fa["collection_id"])
    if coll is not None:
        recompute_collection(coll)
    return success_object(serialize_aid(fa))
