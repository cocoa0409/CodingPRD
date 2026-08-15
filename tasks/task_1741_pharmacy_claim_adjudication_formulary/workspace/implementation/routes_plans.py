from flask import Blueprint

import db
from errors import ApiError
from middleware import require_roles
from response import ok
from validation import body, req_enum, req_int, req_str

bp = Blueprint("plans", __name__)

ALL_ROLES = ("PbmAdmin", "Pharmacist", "Member", "ClinicalReviewer", "Auditor")


@bp.route("/plans", methods=["POST"])
def create_plan():
    require_roles("PbmAdmin")
    b = body()
    rec = db.base_record()
    rec.update(
        {
            "name": req_str(b, "name"),
            "deductible_cents": req_int(b, "deductible_cents", minimum=0),
            "oop_max_cents": req_int(b, "oop_max_cents", minimum=0),
            "assistance_model": req_enum(b, "assistance_model", ("ACCUMULATOR", "MAXIMIZER")),
            "member_min_pay_cents": req_int(b, "member_min_pay_cents", minimum=0),
            "card_fill_cap_cents": req_int(b, "card_fill_cap_cents", minimum=0),
            "dispensing_fee_cents": req_int(b, "dispensing_fee_cents", minimum=0),
            "status": "DRAFT",
        }
    )
    db.plans[rec["id"]] = rec
    return ok(db.public(rec), 201)


def get_plan_or_404(plan_id):
    plan = db.plans.get(plan_id)
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", "Plan not found", 404)
    return plan


@bp.route("/plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    require_roles(*ALL_ROLES)
    return ok(db.public(get_plan_or_404(plan_id)), 200)


@bp.route("/plans/<plan_id>/activate", methods=["POST"])
def activate_plan(plan_id):
    require_roles("PbmAdmin")
    plan = get_plan_or_404(plan_id)
    # Pinned stage-5 order: DRAFT state before counting formulary entries.
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_INVALID_STATE", "Only a DRAFT plan can be activated", 409)
    has_entries = any(e["plan_id"] == plan["id"] for e in db.formulary_entries.values())
    if not has_entries:
        raise ApiError(
            "ERR_PLAN_NO_FORMULARY_ENTRIES",
            "Plan must have at least one formulary entry to activate",
            409,
        )
    plan["status"] = "ACTIVE"
    db.touch(plan)
    return ok(db.public(plan), 200)


@bp.route("/plans/<plan_id>/retire", methods=["POST"])
def retire_plan(plan_id):
    require_roles("PbmAdmin")
    plan = get_plan_or_404(plan_id)
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_INVALID_STATE", "Only an ACTIVE plan can be retired", 409)
    plan["status"] = "RETIRED"
    db.touch(plan)
    # Cascade link 1: formulary entries -> INACTIVE, members -> TERMINATED.
    for entry in db.formulary_entries.values():
        if entry["plan_id"] == plan["id"] and entry["status"] == "ACTIVE":
            entry["status"] = "INACTIVE"
            db.touch(entry)
    for member in db.members.values():
        if member["plan_id"] == plan["id"] and member["status"] == "ACTIVE":
            member["status"] = "TERMINATED"
            db.touch(member)
            # Cascade link 2 (caused by the member termination): live PAs -> CANCELLED.
            for pa in db.prior_authorizations.values():
                if pa["member_id"] == member["id"] and pa["status"] in ("PENDING", "APPROVED"):
                    pa["status"] = "CANCELLED"
                    db.touch(pa)
    return ok(db.public(plan), 200)
