from flask import Blueprint, request

import db
from errors import raise_err
from middleware import (
    MISSING, get_auth, require_role, actor_member, require_active,
    validate, v_str, v_nullable_enum,
)
from response import ok, get_body, paginate, no_body_fields
from services import CATEGORIES, WISHLIST_TTL, new_entity, touch, ser_wishlist

bp = Blueprint("wishlists", __name__)

READ_ROLES = ("Member", "GroupModerator", "PlatformAdmin")


@bp.post("/v1/wishlists")
def create_wishlist():
    role, uid = get_auth()
    require_role(role, ("Member",))
    body = get_body()
    fields = validate(body, {
        "group_id": (True, v_str),
        "keyword": (True, v_str),
        "category": (False, v_nullable_enum(*CATEGORIES)),
    })
    member = actor_member(role, uid)
    group = db.store.groups.get(fields["group_id"])
    if group is None:
        raise_err("ERR_GROUP_NOT_FOUND", "no group with the given id")
    require_active(member)
    category = fields["category"]
    if category is MISSING:
        category = None
    w = new_entity()
    w.update({
        "member_id": member["id"],
        "group_id": group["id"],
        "keyword": fields["keyword"],
        "category": category,
        "status": "ACTIVE",
        "matched_post_id": None,
        "expires_at": w["created_at"] + WISHLIST_TTL,
    })
    db.store.wishlists[w["id"]] = w
    return ok(ser_wishlist(w), status=201)


@bp.get("/v1/wishlists/<wishlist_id>")
def get_wishlist(wishlist_id):
    role, uid = get_auth()
    require_role(role, READ_ROLES)
    actor_member(role, uid)
    w = db.store.wishlists.get(wishlist_id)
    if w is None:
        raise_err("ERR_WISHLIST_NOT_FOUND", "no wishlist with the given id")
    return ok(ser_wishlist(w))


@bp.get("/v1/wishlists")
def list_wishlists():
    role, uid = get_auth()
    require_role(role, READ_ROLES)
    actor_member(role, uid)
    items = list(db.store.wishlists.values())
    member_id = request.args.get("member_id")
    group_id = request.args.get("group_id")
    matched_post_id = request.args.get("matched_post_id")
    status = request.args.get("status")
    if member_id is not None:
        items = [w for w in items if w["member_id"] == member_id]
    if group_id is not None:
        items = [w for w in items if w["group_id"] == group_id]
    if matched_post_id is not None:
        items = [w for w in items if w["matched_post_id"] == matched_post_id]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    items.sort(key=lambda w: (w["created_at"], w["_seq"]))
    page, meta = paginate(items)
    return ok([ser_wishlist(w) for w in page], response_type="array", pagination=meta)


@bp.post("/v1/wishlists/<wishlist_id>/cancel")
def cancel_wishlist(wishlist_id):
    role, uid = get_auth()
    require_role(role, ("Member",))
    no_body_fields()
    member = actor_member(role, uid)
    w = db.store.wishlists.get(wishlist_id)
    if w is None:
        raise_err("ERR_WISHLIST_NOT_FOUND", "no wishlist with the given id")
    if w["status"] not in ("ACTIVE", "MATCHED"):
        raise_err("ERR_WISHLIST_NOT_ACTIVE", "wishlist is in a terminal state")
    if w["member_id"] != member["id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "only the wishing member may cancel the entry")
    w["status"] = "CANCELLED"
    touch(w)
    return ok(ser_wishlist(w))
