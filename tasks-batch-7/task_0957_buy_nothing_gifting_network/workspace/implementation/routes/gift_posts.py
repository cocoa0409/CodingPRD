from flask import Blueprint, request

import db
from errors import raise_err
from middleware import (
    MISSING, get_auth, require_role, actor_member, require_active,
    is_approved_member, validate, v_str, v_str_empty_ok, v_enum, v_int,
    v_datetime,
)
from response import ok, get_body, paginate, no_body_fields
from services import (
    CATEGORIES, CLAIM_MODES, new_entity, touch, ser_post, ser_claim,
    match_wishlists_on_publish, withdraw_post, vacancy_cascade, promote_claim,
)

bp = Blueprint("gift_posts", __name__)

READ_ROLES = ("Member", "GroupModerator", "PlatformAdmin")


def _get_post(post_id):
    post = db.store.posts.get(post_id)
    if post is None:
        raise_err("ERR_GIFT_POST_NOT_FOUND", "no gift post with the given id")
    return post


@bp.post("/v1/gift-posts")
def create_post():
    role, uid = get_auth()
    require_role(role, ("Member",))
    body = get_body()
    fields = validate(body, {
        "group_id": (True, v_str),
        "title": (True, v_str),
        "category": (True, v_enum(*CATEGORIES)),
        "claim_mode": (True, v_enum(*CLAIM_MODES)),
        "expires_at": (True, v_datetime),
        "description": (False, v_str_empty_ok),
    })
    member = actor_member(role, uid)
    group = db.store.groups.get(fields["group_id"])
    if group is None:
        raise_err("ERR_GROUP_NOT_FOUND", "no group with the given id")
    require_active(member)
    if fields["expires_at"] <= db.now():
        raise_err("ERR_INVALID_TIME_RANGE", "expires_at must lie strictly in the future")
    post = new_entity()
    post.update({
        "group_id": group["id"],
        "giver_id": member["id"],
        "title": fields["title"],
        "description": fields["description"] if fields["description"] is not MISSING else "",
        "category": fields["category"],
        "claim_mode": fields["claim_mode"],
        "status": "DRAFT",
        "expires_at": fields["expires_at"],
        "current_claim_id": None,
        "current_offer_expires_at": None,
        "fulfilled_at": None,
    })
    db.store.posts[post["id"]] = post
    return ok(ser_post(post), status=201)


@bp.get("/v1/gift-posts/<post_id>")
def get_post(post_id):
    role, uid = get_auth()
    require_role(role, READ_ROLES)
    actor_member(role, uid)
    return ok(ser_post(_get_post(post_id)))


@bp.get("/v1/gift-posts")
def list_posts():
    role, uid = get_auth()
    require_role(role, READ_ROLES)
    actor_member(role, uid)
    items = list(db.store.posts.values())
    group_id = request.args.get("group_id")
    giver_id = request.args.get("giver_id")
    status = request.args.get("status")
    category = request.args.get("category")
    if group_id is not None:
        items = [p for p in items if p["group_id"] == group_id]
    if giver_id is not None:
        items = [p for p in items if p["giver_id"] == giver_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if category is not None:
        items = [p for p in items if p["category"] == category]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    page, meta = paginate(items)
    return ok([ser_post(p) for p in page], response_type="array", pagination=meta)


@bp.put("/v1/gift-posts/<post_id>")
def update_post(post_id):
    role, uid = get_auth()
    require_role(role, ("Member",))
    body = get_body()
    fields = validate(body, {
        "title": (False, v_str),
        "description": (False, v_str_empty_ok),
        "category": (False, v_enum(*CATEGORIES)),
        "expires_at": (False, v_datetime),
        "expected_gift_post_version": (True, v_int()),
    })
    member = actor_member(role, uid)
    post = _get_post(post_id)
    if fields["expected_gift_post_version"] != post["version"]:
        raise_err("ERR_STALE_VERSION", "post version has advanced; re-read and resubmit")
    if post["status"] not in ("DRAFT", "OPEN"):
        raise_err("ERR_VALIDATION", "only DRAFT or OPEN posts can be edited")
    if post["giver_id"] != member["id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "only the giver may edit the post")
    if fields["expires_at"] is not MISSING and fields["expires_at"] <= db.now():
        raise_err("ERR_INVALID_TIME_RANGE", "expires_at must lie strictly in the future")
    if fields["title"] is not MISSING:
        post["title"] = fields["title"]
    if fields["description"] is not MISSING:
        post["description"] = fields["description"]
    if fields["category"] is not MISSING:
        post["category"] = fields["category"]
    if fields["expires_at"] is not MISSING:
        post["expires_at"] = fields["expires_at"]
    touch(post)
    return ok(ser_post(post))


@bp.post("/v1/gift-posts/<post_id>/publish")
def publish_post(post_id):
    role, uid = get_auth()
    require_role(role, ("Member",))
    no_body_fields()
    member = actor_member(role, uid)
    post = _get_post(post_id)
    if post["status"] != "DRAFT":
        raise_err("ERR_POST_NOT_DRAFT", "post is not in DRAFT")
    require_active(member)
    if post["giver_id"] != member["id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "only the giver may publish the post")
    post["status"] = "OPEN"
    touch(post)
    match_wishlists_on_publish(post)
    return ok(ser_post(post))


@bp.post("/v1/gift-posts/<post_id>/withdraw")
def withdraw_post_route(post_id):
    role, uid = get_auth()
    require_role(role, ("Member",))
    no_body_fields()
    member = actor_member(role, uid)
    post = _get_post(post_id)
    if post["status"] in ("WITHDRAWN", "EXPIRED", "FULFILLED"):
        raise_err("ERR_POST_NOT_WITHDRAWABLE", "post is in a terminal state")
    if post["status"] == "RESERVED":
        accepted = any(
            c["post_id"] == post["id"] and c["status"] == "ACCEPTED"
            for c in db.store.claims.values()
        )
        if accepted:
            raise_err("ERR_POST_NOT_WITHDRAWABLE", "post has an ACCEPTED claim")
    if post["giver_id"] != member["id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "only the giver may withdraw the post")
    withdraw_post(post)
    return ok(ser_post(post))


@bp.post("/v1/gift-posts/<post_id>/offer")
def offer_post(post_id):
    role, uid = get_auth()
    require_role(role, ("Member",))
    body = get_body()
    fields = validate(body, {"claim_id": (True, v_str)})
    member = actor_member(role, uid)
    post = _get_post(post_id)
    claim = db.store.claims.get(fields["claim_id"])
    if claim is None:
        raise_err("ERR_CLAIM_NOT_FOUND", "no claim with the given id")
    if post["status"] != "OPEN":
        raise_err("ERR_POST_NOT_OPEN", "post is not OPEN")
    if not is_approved_member(member["id"], post["group_id"]):
        raise_err("ERR_NOT_GROUP_MEMBER", "actor lacks an APPROVED membership in the group")
    if post["giver_id"] != member["id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "only the giver may offer the item")
    if claim["post_id"] != post["id"] or claim["status"] != "QUEUED":
        raise_err("ERR_CLAIM_NOT_QUEUED", "claim is not a QUEUED claim of this post")
    promote_claim(claim, post)
    return ok(ser_claim(claim))
