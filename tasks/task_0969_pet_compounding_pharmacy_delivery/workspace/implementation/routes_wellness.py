from flask import Blueprint, request

import db
from errors import ApiError
from middleware import auth, body, require_ownership
from response import success, paged
from services import get_or_404, cancel_schedules_for_enrollment
from util import (new_resource, touch, req, as_str, as_int, as_num, as_bool,
                  as_enum, clock_date)

bp = Blueprint("wellness", __name__)

PLAN_READ = ("Owner", "Pharmacist", "PharmacyTech", "PharmacyAdmin")
ENR_READ = ("Owner", "Pharmacist", "PharmacyAdmin")


def _filter(items, names):
    out = []
    for it in items:
        ok = True
        for n in names:
            v = request.args.get(n)
            if v is not None and str(it.get(n)) != v:
                ok = False
                break
        if ok:
            out.append(it)
    return out


# ---- Wellness plans ----

@bp.route("/wellness-plans", methods=["POST"])
def create_plan():
    auth("PharmacyAdmin")
    d = body()
    name = as_str(req(d, "name"), "name")
    fee = as_int(req(d, "monthly_fee_cents"), "monthly_fee_cents")
    if fee < 0:
        raise ApiError("ERR_INVALID_REQUEST", "monthly_fee_cents must be >= 0", 400)
    credits = as_int(req(d, "included_refill_credits"), "included_refill_credits")
    if credits < 0:
        raise ApiError("ERR_INVALID_REQUEST", "included_refill_credits must be >= 0",
                       400)
    value = as_int(req(d, "credit_value_cents"), "credit_value_cents")
    if value <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "credit_value_cents must be > 0", 400)
    discount = as_num(req(d, "discount_pct"), "discount_pct")
    if discount < 0 or discount >= 1:
        raise ApiError("ERR_INVALID_REQUEST", "discount_pct must be in [0, 1)", 400)
    covers = as_bool(req(d, "covers_controlled"), "covers_controlled")
    p = new_resource({
        "name": name, "monthly_fee_cents": fee,
        "included_refill_credits": credits, "credit_value_cents": value,
        "discount_pct": discount, "covers_controlled": covers, "status": "ACTIVE",
    })
    db.wellness_plans[p["id"]] = p
    return success(p, 201)


@bp.route("/wellness-plans", methods=["GET"])
def list_plans():
    auth(*PLAN_READ)
    return paged(_filter(list(db.wellness_plans.values()), ["status"]))


@bp.route("/wellness-plans/<rid>", methods=["GET"])
def get_plan(rid):
    auth(*PLAN_READ)
    return success(get_or_404(db.wellness_plans, rid, "wellness plan"))


@bp.route("/wellness-plans/<rid>", methods=["PATCH"])
def patch_plan(rid):
    auth("PharmacyAdmin")
    p = get_or_404(db.wellness_plans, rid, "wellness plan")
    d = body()
    if "status" in d and d["status"] is not None:
        p["status"] = as_enum(d["status"], "status", {"ACTIVE", "RETIRED"})
    touch(p)
    return success(p)


# ---- Enrollments ----

@bp.route("/enrollments", methods=["POST"])
def create_enrollment():
    _, user_id = auth("Owner")
    d = body()
    pet_id = d.get("pet_id")
    plan_id = d.get("plan_id")
    if pet_id is not None:
        get_or_404(db.pets, pet_id, "pet")
    if plan_id is not None:
        get_or_404(db.wellness_plans, plan_id, "wellness plan")
    pet_id = as_str(req(d, "pet_id"), "pet_id")
    plan_id = as_str(req(d, "plan_id"), "plan_id")
    expected = as_int(req(d, "expected_owner_version"), "expected_owner_version")
    pet = db.pets[pet_id]
    require_ownership(user_id, pet["owner_id"])
    owner = db.owners[pet["owner_id"]]
    if expected != owner["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_owner_version does not match the owner's current "
                       "version", 412)
    plan = db.wellness_plans[plan_id]
    # supersede the pet's existing ACTIVE/SUSPENDED enrollment
    for e in sorted(db.enrollments.values(), key=lambda x: x["_seq"]):
        if e["pet_id"] == pet_id and e["status"] in ("ACTIVE", "SUSPENDED"):
            e["status"] = "CANCELLED"
            cancel_schedules_for_enrollment(e["id"])
            touch(e)
    e = new_resource({
        "owner_id": pet["owner_id"], "pet_id": pet_id, "plan_id": plan_id,
        "status": "ACTIVE", "credits_remaining": plan["included_refill_credits"],
        "credits_consumed": 0, "cycle_anchor_date": clock_date().isoformat(),
    })
    db.enrollments[e["id"]] = e
    touch(owner)
    return success(e, 201)


@bp.route("/enrollments/<rid>", methods=["GET"])
def get_enrollment(rid):
    auth(*ENR_READ)
    return success(get_or_404(db.enrollments, rid, "enrollment"))


@bp.route("/enrollments", methods=["GET"])
def list_enrollments():
    auth(*ENR_READ)
    return paged(_filter(list(db.enrollments.values()),
                         ["owner_id", "pet_id", "plan_id", "status"]))


def _enrollment_action(rid, from_states, to_state, cascade=False):
    role, user_id = auth("Owner", "PharmacyAdmin")
    e = get_or_404(db.enrollments, rid, "enrollment")
    if role == "Owner":
        require_ownership(user_id, e["owner_id"])
    if e["status"] not in from_states:
        raise ApiError("ERR_INVALID_STATE",
                       "enrollment is not in a permitted source state", 409)
    e["status"] = to_state
    if cascade:
        cancel_schedules_for_enrollment(e["id"])
    touch(e)
    return success(e)


@bp.route("/enrollments/<rid>/suspend", methods=["POST"])
def suspend_enrollment(rid):
    return _enrollment_action(rid, ("ACTIVE",), "SUSPENDED")


@bp.route("/enrollments/<rid>/resume", methods=["POST"])
def resume_enrollment(rid):
    return _enrollment_action(rid, ("SUSPENDED",), "ACTIVE")


@bp.route("/enrollments/<rid>/cancel", methods=["POST"])
def cancel_enrollment(rid):
    return _enrollment_action(rid, ("ACTIVE", "SUSPENDED"), "CANCELLED", cascade=True)
