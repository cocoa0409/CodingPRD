"""Capital assessment endpoints (PRD §3.5)."""
from flask import Blueprint, request

import db
import errors
import common
import computed
import calculations as calc
from middleware import get_auth, require_roles
from response import success_object, success_array
from serializers import assessment_out, assessment_charge_out

bp = Blueprint("assessments", __name__)

READ_ROLES = ["ClubManager", "BillingClerk", "Member"]
_BASES = {"EQUAL", "DUES_WEIGHTED"}


@bp.post("/capital-assessments")
def create_assessment():
    role, _ = get_auth()
    require_roles(role, ["ClubManager"])
    body = common.get_body()
    common.require_fields(body, ["club_id", "description", "total_target_cents", "allocation_basis"])
    club_id = common.require_string(body, "club_id")
    common.get_club(club_id)
    description = common.require_string(body, "description")
    total_target = common.require_positive_int(body, "total_target_cents")
    basis = common.require_enum(body, "allocation_basis", _BASES)

    rec = db.base_record(common_fields=True)
    rec.update(
        {
            "club_id": club_id,
            "description": description,
            "total_target_cents": total_target,
            "allocation_basis": basis,
            "status": "DRAFT",
            "levied_amount_cents": 0,
            "levied_period_index": None,
        }
    )
    db.assessments[rec["id"]] = rec
    return success_object(assessment_out(rec), status=201)


@bp.get("/capital-assessments/<aid>")
def get_assessment(aid):
    role, _ = get_auth()
    require_roles(role, READ_ROLES)
    rec = common.get_assessment(aid)
    return success_object(assessment_out(rec), status=200)


@bp.get("/capital-assessments")
def list_assessments():
    role, _ = get_auth()
    require_roles(role, READ_ROLES)
    limit, offset = common.pagination_params()
    records = list(db.assessments.values())
    club_id = request.args.get("club_id")
    if club_id is not None:
        records = [r for r in records if r["club_id"] == club_id]
    page, total = common.sort_and_page(records, limit, offset)
    data = [assessment_out(r) for r in page]
    return success_array(data, limit, offset, total)


@bp.post("/capital-assessments/<aid>/levy")
def levy(aid):
    role, _ = get_auth()
    require_roles(role, ["ClubManager"])
    rec = common.get_assessment(aid)
    if rec["status"] != "DRAFT":
        raise errors.invalid_state("Assessment is not DRAFT")
    club = db.clubs[rec["club_id"]]
    # Eligible: ACTIVE/SUSPENDED memberships of this club, created_at ASC.
    eligible = [
        m
        for m in db.memberships.values()
        if m["club_id"] == rec["club_id"]
        and m["account_status"] in ("ACTIVE", "SUSPENDED")
    ]
    if not eligible:
        raise errors.no_eligible_members()
    eligible.sort(key=lambda m: m["_seq"])

    if rec["allocation_basis"] == "EQUAL":
        shares = calc.allocate_equal(rec["total_target_cents"], eligible)
    else:
        shares = calc.allocate_dues_weighted(rec["total_target_cents"], eligible)

    levied_total = 0
    for m in eligible:
        share = shares[m["id"]]
        charge = db.base_record(common_fields=False)  # immutable: id + created_at only
        charge.update(
            {
                "assessment_id": rec["id"],
                "membership_id": m["id"],
                "amount_cents": share,
            }
        )
        db.assessment_charges[charge["id"]] = charge
        levied_total += share
        # Cascade: each charge debits the member's balance.
        computed.refresh_membership_computeds(m["id"])
        db.touch(m)

    rec["status"] = "LEVIED"
    rec["levied_amount_cents"] = levied_total
    rec["levied_period_index"] = club["billing_period_index"]
    db.touch(rec)
    return success_object(assessment_out(rec), status=200)


@bp.post("/capital-assessments/<aid>/cancel")
def cancel(aid):
    role, _ = get_auth()
    require_roles(role, ["ClubManager"])
    rec = common.get_assessment(aid)
    if rec["status"] != "DRAFT":
        raise errors.invalid_state("Assessment is not DRAFT")
    rec["status"] = "CANCELLED"
    db.touch(rec)
    return success_object(assessment_out(rec), status=200)


@bp.get("/capital-assessments/<aid>/charges")
def list_charges(aid):
    role, _ = get_auth()
    require_roles(role, READ_ROLES)
    common.get_assessment(aid)
    limit, offset = common.pagination_params()
    records = [c for c in db.assessment_charges.values() if c["assessment_id"] == aid]
    page, total = common.sort_and_page(records, limit, offset)
    data = [assessment_charge_out(c) for c in page]
    return success_array(data, limit, offset, total)


@bp.get("/assessment-charges/<cid>")
def get_charge(cid):
    role, _ = get_auth()
    require_roles(role, READ_ROLES)
    rec = common.get_assessment_charge(cid)
    return success_object(assessment_charge_out(rec), status=200)


@bp.get("/assessment-charges")
def list_assessment_charges():
    role, _ = get_auth()
    require_roles(role, READ_ROLES)
    limit, offset = common.pagination_params()
    records = list(db.assessment_charges.values())
    membership_id = request.args.get("membership_id")
    assessment_id = request.args.get("assessment_id")
    if membership_id is not None:
        records = [r for r in records if r["membership_id"] == membership_id]
    if assessment_id is not None:
        records = [r for r in records if r["assessment_id"] == assessment_id]
    page, total = common.sort_and_page(records, limit, offset)
    data = [assessment_charge_out(c) for c in page]
    return success_array(data, limit, offset, total)
