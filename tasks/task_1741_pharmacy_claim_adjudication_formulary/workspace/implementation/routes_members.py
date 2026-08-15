from flask import Blueprint, request

import db
from errors import ApiError
from middleware import require_roles
from response import ok, ok_list
from validation import body, opt_int, paginate, parse_date, req_date, req_str

bp = Blueprint("members", __name__)


@bp.route("/members", methods=["POST"])
def create_member():
    require_roles("PbmAdmin")
    b = body()
    # Pipeline stage 4: body FK existence (plan, then card drug), left to right.
    plan_id = b.get("plan_id")
    if plan_id is not None and plan_id not in db.plans:
        raise ApiError("ERR_PLAN_NOT_FOUND", "Plan not found", 404)
    card_drug_id = b.get("card_drug_id")
    if card_drug_id is not None and card_drug_id not in db.drugs:
        raise ApiError("ERR_DRUG_NOT_FOUND", "Card drug not found", 404)
    # Pipeline stage 7: request shape.
    if not isinstance(plan_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'plan_id' is required and must be a string", 400)
    external_ref = req_str(b, "external_ref")
    full_name = req_str(b, "full_name")
    start = req_date(b, "eligibility_start_date")
    end = req_date(b, "eligibility_end_date")
    if parse_date(end) < parse_date(start):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "eligibility_end_date must be on or after eligibility_start_date",
            400,
        )
    if card_drug_id is not None and not isinstance(card_drug_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'card_drug_id' must be a string or null", 400)
    card_balance = opt_int(b, "card_balance_cents", minimum=0, default=0)
    # Pipeline stage 8: external_ref unique within the plan.
    if any(
        m["plan_id"] == plan_id and m["external_ref"] == external_ref
        for m in db.members.values()
    ):
        raise ApiError("ERR_INVALID_REQUEST", "A member with this external_ref already exists in the plan", 400)
    rec = db.base_record()
    rec.update(
        {
            "plan_id": plan_id,
            "external_ref": external_ref,
            "full_name": full_name,
            "eligibility_start_date": start,
            "eligibility_end_date": end,
            "status": "ACTIVE",
            "deductible_paid_cents": 0,
            "oop_paid_cents": 0,
            "oop_max_reached": False,
            "card_drug_id": card_drug_id,
            "card_balance_cents": card_balance,
        }
    )
    db.members[rec["id"]] = rec
    return ok(db.public(rec), 201)


@bp.route("/members", methods=["GET"])
def list_members():
    require_roles("PbmAdmin", "ClinicalReviewer", "Auditor")
    rows = list(db.members.values())
    plan_id = request.args.get("plan_id")
    card_drug_id = request.args.get("card_drug_id")
    if plan_id is not None:
        rows = [r for r in rows if r["plan_id"] == plan_id]
    if card_drug_id is not None:
        rows = [r for r in rows if r["card_drug_id"] == card_drug_id]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


@bp.route("/members/<member_id>", methods=["GET"])
def get_member(member_id):
    uid, role = require_roles("PbmAdmin", "Member", "ClinicalReviewer", "Auditor")
    # Pipeline stage 3: a Member caller may read only their own record.
    if role == "Member" and uid != member_id:
        raise ApiError("ERR_MEMBER_MISMATCH", "Members may read only their own record", 403)
    member = db.members.get(member_id)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "Member not found", 404)
    return ok(db.public(member), 200)
