from flask import Blueprint, request

import db
from errors import raise_err
from middleware import (
    MISSING, get_auth, require_role, actor_member, require_active,
    is_approved_member, validate, v_str, v_str_empty_ok, v_datetime,
)
from response import ok, get_body, paginate, no_body_fields
from services import (
    new_entity, touch, ser_plan, vacancy_cascade, add_event,
    fulfill_wishlists, pickup_window_conflict,
)

bp = Blueprint("pickup_plans", __name__)

READ_ROLES = ("Member", "GroupModerator", "PlatformAdmin")


def _get_plan(plan_id):
    plan = db.store.plans.get(plan_id)
    if plan is None:
        raise_err("ERR_PICKUP_PLAN_NOT_FOUND", "no pickup plan with the given id")
    return plan


def _claim_and_post(plan):
    claim = db.store.claims.get(plan["claim_id"])
    post = db.store.posts.get(claim["post_id"]) if claim else None
    return claim, post


def _is_party(member_id, claim, post):
    return member_id in (claim["claimer_id"], post["giver_id"])


@bp.post("/v1/pickup-plans")
def create_plan():
    role, uid = get_auth()
    require_role(role, ("Member",))
    body = get_body()
    fields = validate(body, {
        "claim_id": (True, v_str),
        "window_start": (True, v_datetime),
        "window_end": (True, v_datetime),
        "location_note": (False, v_str_empty_ok),
    })
    member = actor_member(role, uid)
    claim = db.store.claims.get(fields["claim_id"])
    if claim is None:
        raise_err("ERR_CLAIM_NOT_FOUND", "no claim with the given id")
    if claim["status"] != "ACCEPTED":
        raise_err("ERR_CLAIM_NOT_ACCEPTED", "claim is not in ACCEPTED")
    require_active(member)
    post = db.store.posts.get(claim["post_id"])
    if not is_approved_member(member["id"], post["group_id"]):
        raise_err("ERR_NOT_GROUP_MEMBER", "actor lacks an APPROVED membership in the group")
    if not _is_party(member["id"], claim, post):
        raise_err("ERR_NOT_COUNTERPARTY", "only the giver or the claimer may propose a plan")
    if fields["window_end"] <= fields["window_start"]:
        raise_err("ERR_INVALID_TIME_RANGE", "window_end must be strictly after window_start")
    if pickup_window_conflict(post["giver_id"], fields["window_start"], fields["window_end"]):
        raise_err("ERR_PICKUP_WINDOW_CONFLICT", "window collides with a confirmed window on the giver's porch")
    plan = new_entity()
    plan.update({
        "claim_id": claim["id"],
        "proposer_id": member["id"],
        "last_proposer_id": member["id"],
        "window_start": fields["window_start"],
        "window_end": fields["window_end"],
        "location_note": fields["location_note"] if fields["location_note"] is not MISSING else "",
        "round_number": 1,
        "status": "PROPOSED",
    })
    db.store.plans[plan["id"]] = plan
    return ok(ser_plan(plan), status=201)


@bp.get("/v1/pickup-plans/<plan_id>")
def get_plan(plan_id):
    role, uid = get_auth()
    require_role(role, READ_ROLES)
    actor_member(role, uid)
    return ok(ser_plan(_get_plan(plan_id)))


@bp.get("/v1/pickup-plans")
def list_plans():
    role, uid = get_auth()
    require_role(role, READ_ROLES)
    actor_member(role, uid)
    items = list(db.store.plans.values())
    claim_id = request.args.get("claim_id")
    proposer_id = request.args.get("proposer_id")
    status = request.args.get("status")
    if claim_id is not None:
        items = [p for p in items if p["claim_id"] == claim_id]
    if proposer_id is not None:
        items = [p for p in items if p["proposer_id"] == proposer_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    page, meta = paginate(items)
    return ok([ser_plan(p) for p in page], response_type="array", pagination=meta)


@bp.post("/v1/pickup-plans/<plan_id>/counter")
def counter_plan(plan_id):
    role, uid = get_auth()
    require_role(role, ("Member",))
    body = get_body()
    fields = validate(body, {
        "window_start": (True, v_datetime),
        "window_end": (True, v_datetime),
        "location_note": (False, v_str_empty_ok),
    })
    member = actor_member(role, uid)
    plan = _get_plan(plan_id)
    claim, post = _claim_and_post(plan)
    if plan["status"] not in ("PROPOSED", "COUNTERED"):
        raise_err("ERR_PICKUP_NOT_NEGOTIABLE", "plan is not in PROPOSED or COUNTERED")
    if not _is_party(member["id"], claim, post) or member["id"] == plan["last_proposer_id"]:
        raise_err("ERR_NOT_COUNTERPARTY", "counter must come from the party who did not make the latest proposal")
    if plan["round_number"] >= 3:
        raise_err("ERR_MAX_NEGOTIATION_ROUNDS", "negotiation is capped at 3 rounds")
    if fields["window_end"] <= fields["window_start"]:
        raise_err("ERR_INVALID_TIME_RANGE", "window_end must be strictly after window_start")
    if pickup_window_conflict(post["giver_id"], fields["window_start"], fields["window_end"]):
        raise_err("ERR_PICKUP_WINDOW_CONFLICT", "window collides with a confirmed window on the giver's porch")
    plan["window_start"] = fields["window_start"]
    plan["window_end"] = fields["window_end"]
    if fields["location_note"] is not MISSING:
        plan["location_note"] = fields["location_note"]
    plan["round_number"] += 1
    plan["last_proposer_id"] = member["id"]
    plan["status"] = "COUNTERED"
    touch(plan)
    return ok(ser_plan(plan))


@bp.post("/v1/pickup-plans/<plan_id>/confirm")
def confirm_plan(plan_id):
    role, uid = get_auth()
    require_role(role, ("Member",))
    no_body_fields()
    member = actor_member(role, uid)
    plan = _get_plan(plan_id)
    claim, post = _claim_and_post(plan)
    if plan["status"] not in ("PROPOSED", "COUNTERED"):
        raise_err("ERR_PICKUP_NOT_NEGOTIABLE", "plan is not in PROPOSED or COUNTERED")
    if not _is_party(member["id"], claim, post) or member["id"] == plan["last_proposer_id"]:
        raise_err("ERR_NOT_COUNTERPARTY", "confirm must come from the party who did not make the latest proposal")
    if pickup_window_conflict(post["giver_id"], plan["window_start"], plan["window_end"]):
        raise_err("ERR_PICKUP_WINDOW_CONFLICT", "window collides with a confirmed window on the giver's porch")
    plan["status"] = "CONFIRMED"
    touch(plan)
    return ok(ser_plan(plan))


@bp.post("/v1/pickup-plans/<plan_id>/cancel")
def cancel_plan(plan_id):
    role, uid = get_auth()
    require_role(role, ("Member",))
    no_body_fields()
    member = actor_member(role, uid)
    plan = _get_plan(plan_id)
    claim, post = _claim_and_post(plan)
    if plan["status"] not in ("PROPOSED", "COUNTERED"):
        raise_err("ERR_PICKUP_NOT_NEGOTIABLE", "plan is not in PROPOSED or COUNTERED")
    if not _is_party(member["id"], claim, post):
        raise_err("ERR_NOT_COUNTERPARTY", "only the giver or the claimer may cancel the plan")
    plan["status"] = "CANCELLED"
    touch(plan)
    return ok(ser_plan(plan))


@bp.post("/v1/pickup-plans/<plan_id>/complete")
def complete_plan(plan_id):
    role, uid = get_auth()
    require_role(role, ("Member",))
    no_body_fields()
    member = actor_member(role, uid)
    plan = _get_plan(plan_id)
    claim, post = _claim_and_post(plan)
    if plan["status"] != "CONFIRMED":
        raise_err("ERR_PICKUP_NOT_CONFIRMED", "plan is not in CONFIRMED")
    if post["giver_id"] != member["id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "only the giver may complete the plan")
    plan["status"] = "COMPLETED"
    touch(plan)
    claim["status"] = "FULFILLED"
    claim["fulfilled_at"] = db.now()
    touch(claim)
    post["status"] = "FULFILLED"
    post["fulfilled_at"] = db.now()
    post["current_claim_id"] = None
    post["current_offer_expires_at"] = None
    touch(post)
    add_event(post["giver_id"], "GIFT_COMPLETED", 10)
    add_event(claim["claimer_id"], "RECEIVE_COMPLETED", 3)
    fulfill_wishlists(claim["claimer_id"], post)
    return ok(ser_plan(plan))


@bp.post("/v1/pickup-plans/<plan_id>/miss")
def miss_plan(plan_id):
    role, uid = get_auth()
    require_role(role, ("Member",))
    no_body_fields()
    member = actor_member(role, uid)
    plan = _get_plan(plan_id)
    claim, post = _claim_and_post(plan)
    if plan["status"] != "CONFIRMED":
        raise_err("ERR_PICKUP_NOT_CONFIRMED", "plan is not in CONFIRMED")
    if db.now() <= plan["window_end"]:
        raise_err("ERR_PICKUP_WINDOW_NOT_PASSED", "the pickup window has not passed yet")
    if post["giver_id"] != member["id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "only the giver may report a no-show")
    plan["status"] = "MISSED"
    touch(plan)
    claim["status"] = "NO_SHOW"
    touch(claim)
    add_event(claim["claimer_id"], "NO_SHOW_PENALTY", -8)
    vacancy_cascade(post)
    return ok(ser_plan(plan))
