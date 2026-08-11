from flask import Blueprint, request

import db
from errors import raise_err
from middleware import (
    get_auth, require_role, actor_member, require_active, is_approved_member,
    validate, v_str,
)
from response import ok, get_body, paginate, no_body_fields
from services import new_entity, touch, ser_claim, vacancy_cascade

bp = Blueprint("claims", __name__)

READ_ROLES = ("Member", "GroupModerator", "PlatformAdmin")


def _get_claim(claim_id):
    claim = db.store.claims.get(claim_id)
    if claim is None:
        raise_err("ERR_CLAIM_NOT_FOUND", "no claim with the given id")
    return claim


@bp.post("/v1/claims")
def create_claim():
    role, uid = get_auth()
    require_role(role, ("Member",))
    body = get_body()
    fields = validate(body, {"post_id": (True, v_str)})
    member = actor_member(role, uid)
    post = db.store.posts.get(fields["post_id"])
    if post is None:
        raise_err("ERR_GIFT_POST_NOT_FOUND", "no gift post with the given id")
    if post["status"] != "OPEN":
        raise_err("ERR_POST_NOT_OPEN", "post is not OPEN")
    require_active(member)
    if not is_approved_member(member["id"], post["group_id"]):
        raise_err("ERR_NOT_GROUP_MEMBER", "actor lacks an APPROVED membership in the group")
    if post["giver_id"] == member["id"]:
        raise_err("ERR_SELF_CLAIM", "the giver cannot claim their own post")
    for c in db.store.claims.values():
        if (c["post_id"] == post["id"] and c["claimer_id"] == member["id"]
                and c["status"] in ("QUEUED", "OFFERED", "ACCEPTED")):
            raise_err("ERR_DUPLICATE_CLAIM", "a live claim by this member already exists on the post")
    claim = new_entity()
    seq = max(
        (c["claim_seq"] for c in db.store.claims.values() if c["post_id"] == post["id"]),
        default=0,
    ) + 1
    claim.update({
        "post_id": post["id"],
        "claimer_id": member["id"],
        "status": "QUEUED",
        "claim_seq": seq,
        "offered_at": None,
        "offer_expires_at": None,
        "fulfilled_at": None,
    })
    db.store.claims[claim["id"]] = claim
    if post["claim_mode"] != "GIVER_PICK":
        # Auto-promote in the same request when the head slot is vacant.
        vacancy_cascade(post)
    return ok(ser_claim(claim), status=201)


@bp.get("/v1/claims/<claim_id>")
def get_claim(claim_id):
    role, uid = get_auth()
    require_role(role, READ_ROLES)
    actor_member(role, uid)
    return ok(ser_claim(_get_claim(claim_id)))


@bp.get("/v1/claims")
def list_claims():
    role, uid = get_auth()
    require_role(role, READ_ROLES)
    actor_member(role, uid)
    items = list(db.store.claims.values())
    post_id = request.args.get("post_id")
    claimer_id = request.args.get("claimer_id")
    status = request.args.get("status")
    if post_id is not None:
        items = [c for c in items if c["post_id"] == post_id]
    if claimer_id is not None:
        items = [c for c in items if c["claimer_id"] == claimer_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    page, meta = paginate(items)
    return ok([ser_claim(c) for c in page], response_type="array", pagination=meta)


@bp.post("/v1/claims/<claim_id>/accept")
def accept_claim(claim_id):
    role, uid = get_auth()
    require_role(role, ("Member",))
    no_body_fields()
    member = actor_member(role, uid)
    claim = _get_claim(claim_id)
    if claim["status"] != "OFFERED" or db.now() >= claim["offer_expires_at"]:
        raise_err("ERR_CLAIM_NOT_OFFERED", "claim is not in OFFERED")
    if claim["claimer_id"] != member["id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "only the claimer may accept the offer")
    claim["status"] = "ACCEPTED"
    touch(claim)
    return ok(ser_claim(claim))


@bp.post("/v1/claims/<claim_id>/decline")
def decline_claim(claim_id):
    role, uid = get_auth()
    require_role(role, ("Member",))
    no_body_fields()
    member = actor_member(role, uid)
    claim = _get_claim(claim_id)
    if claim["status"] != "OFFERED":
        raise_err("ERR_CLAIM_NOT_OFFERED", "claim is not in OFFERED")
    if claim["claimer_id"] != member["id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "only the claimer may decline the offer")
    claim["status"] = "DECLINED"
    touch(claim)
    post = db.store.posts.get(claim["post_id"])
    if post is not None:
        vacancy_cascade(post)
    return ok(ser_claim(claim))


@bp.post("/v1/claims/<claim_id>/withdraw")
def withdraw_claim(claim_id):
    role, uid = get_auth()
    require_role(role, ("Member",))
    no_body_fields()
    member = actor_member(role, uid)
    claim = _get_claim(claim_id)
    if claim["status"] not in ("QUEUED", "OFFERED"):
        raise_err("ERR_CLAIM_NOT_WITHDRAWABLE", "claim is not in QUEUED or OFFERED")
    if claim["claimer_id"] != member["id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "only the claimer may withdraw the claim")
    was_head = claim["status"] == "OFFERED"
    claim["status"] = "WITHDRAWN"
    touch(claim)
    if was_head:
        post = db.store.posts.get(claim["post_id"])
        if post is not None:
            vacancy_cascade(post)
    return ok(ser_claim(claim))
