"""Collection routes (PRD §3.2) — self-referential hierarchy, rollups."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_COLLECTION_CODE_EXISTS, ERR_COLLECTION_CYCLE,
)
from middleware import require_roles, ANY_ROLE
from response import success_object, success_list
from util import get_json_body, as_str, paginate, public_view

bp = Blueprint("collections", __name__)


def serialize_collection(coll: dict) -> dict:
    return public_view(coll)


def _get_collection(cid: str) -> dict:
    coll = db.collections.get(cid)
    if coll is None:
        raise_err(ERR_NOT_FOUND, f"Collection not found: {cid}")
    return coll


def _is_descendant_or_self(collection_id: str, candidate_parent_id: str) -> bool:
    """True if candidate_parent_id == collection_id or is one of its descendants."""
    if candidate_parent_id == collection_id:
        return True
    # walk down from collection_id
    stack = [collection_id]
    seen = set()
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for c in db.collections.values():
            if c.get("parent_collection_id") == cur:
                if c["id"] == candidate_parent_id:
                    return True
                stack.append(c["id"])
    return False


@bp.route("/collections", methods=["POST"])
@require_roles("Registrar")
def create_collection(_user_id: str, _role: str):
    body = get_json_body()
    title = as_str(body, "title", required=True)
    collection_code = as_str(body, "collection_code", required=True)
    storage_zone_id = as_str(body, "storage_zone_id", required=True)
    parent_collection_id = as_str(body, "parent_collection_id", required=False, default=None)

    # existence (priority 4), body order: storage_zone_id then parent
    zone = db.zones.get(storage_zone_id)
    if zone is None:
        raise_err(ERR_NOT_FOUND, f"StorageZone not found: {storage_zone_id}")
    if parent_collection_id is not None and parent_collection_id not in db.collections:
        raise_err(ERR_NOT_FOUND, f"Collection not found: {parent_collection_id}")

    # uniqueness (priority 10)
    if any(c["collection_code"] == collection_code for c in db.collections.values()):
        raise_err(ERR_COLLECTION_CODE_EXISTS, f"collection_code already in use: {collection_code}")

    coll = {
        **db.make_common_fields(),
        "title": title,
        "collection_code": collection_code,
        "parent_collection_id": parent_collection_id,
        "storage_zone_id": storage_zone_id,
        "status": "ACTIVE",
        "item_count": 0,
        "published_finding_aid_present": False,
    }
    db.collections[coll["id"]] = coll
    return success_object(serialize_collection(coll), 201)


@bp.route("/collections", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_collections(_user_id: str, _role: str):
    parent = request.args.get("parent_collection_id")
    zone_id = request.args.get("storage_zone_id")
    status = request.args.get("status")
    items = list(db.collections.values())
    if parent is not None:
        items = [c for c in items if c.get("parent_collection_id") == parent]
    if zone_id is not None:
        items = [c for c in items if c["storage_zone_id"] == zone_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_collection(c) for c in page], limit, offset, total)


@bp.route("/collections/<cid>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_collection(cid: str, _user_id: str, _role: str):
    return success_object(serialize_collection(_get_collection(cid)))


@bp.route("/collections/<cid>", methods=["PATCH"])
@require_roles("Registrar")
def reparent_collection(cid: str, _user_id: str, _role: str):
    body = get_json_body()
    if "parent_collection_id" not in body or body["parent_collection_id"] is None \
            or not isinstance(body["parent_collection_id"], str):
        raise_err(ERR_INVALID_REQUEST, "Field 'parent_collection_id' is required")

    coll = _get_collection(cid)  # path id first (priority 4)

    new_parent_id = body["parent_collection_id"]
    if new_parent_id not in db.collections:
        raise_err(ERR_NOT_FOUND, f"Collection not found: {new_parent_id}")

    if coll["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE collection may be reparented")

    if _is_descendant_or_self(cid, new_parent_id):
        raise_err(ERR_COLLECTION_CYCLE, "parent_collection_id would create a cycle")

    coll["parent_collection_id"] = new_parent_id
    db.touch(coll)
    return success_object(serialize_collection(coll))
