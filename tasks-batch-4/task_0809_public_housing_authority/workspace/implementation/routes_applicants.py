"""Applicants, household members, preference claims, applicant sub-lists."""
from flask import Blueprint

import db
import domain
from core import (
    ApiError, authenticate, authorize, require_ownership, get_or_404,
    owner_applicant_id, json_body, need_str, need_enum, opt_int_nonneg,
    opt_bool, pagination, ok, ok_list,
)

bp = Blueprint("applicants", __name__)

RELATIONSHIPS = {"HEAD", "SPOUSE", "DEPENDENT", "OTHER_ADULT"}
PREFERENCE_TYPES = {
    "VETERAN", "ELDERLY", "DISABLED",
    "INVOLUNTARY_DISPLACEMENT", "LOCAL_RESIDENT", "WORKING_FAMILY",
}


def _paged(records):
    limit, offset = pagination()
    ordered = db.sorted_by_created(records)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [db.serialize(r) for r in page], limit, offset, total


# ---------------------------------------------------------------------------
# Applicants
# ---------------------------------------------------------------------------
@bp.route("/pha/applicants", methods=["POST"])
def create_applicant():
    uid, role = authenticate()
    authorize(role, {"IntakeClerk"})
    body = json_body()
    household_name = need_str(body, "household_name")
    applicant = db.create(
        db.applicants,
        household_name=household_name,
        application_date=db.now(),
        status="APPLIED",
        annual_gross_income_cents=0,
        household_size=0,
    )
    return ok(db.serialize(applicant), 201)


@bp.route("/pha/applicants/<aid>", methods=["GET"])
def get_applicant(aid):
    uid, role = authenticate()
    authorize(role, {"IntakeClerk", "HousingSpecialist", "PropertyManager", "Applicant"})
    applicant = get_or_404(db.applicants, aid, "ERR_APPLICANT_NOT_FOUND")
    require_ownership(role, uid, owner_applicant_id("applicant", applicant))
    return ok(db.serialize(applicant))


# ---------------------------------------------------------------------------
# Household members
# ---------------------------------------------------------------------------
@bp.route("/pha/applicants/<aid>/members", methods=["POST"])
def add_member(aid):
    uid, role = authenticate()
    authorize(role, {"IntakeClerk"})
    applicant = get_or_404(db.applicants, aid, "ERR_APPLICANT_NOT_FOUND")
    body = json_body()
    full_name = need_str(body, "full_name")
    relationship = need_enum(body, "relationship", RELATIONSHIPS)
    member = db.create(
        db.members,
        applicant_id=applicant["id"],
        full_name=full_name,
        relationship=relationship,
        annual_income_cents=opt_int_nonneg(body, "annual_income_cents", 0),
        nonrecurring_income_cents=opt_int_nonneg(body, "nonrecurring_income_cents", 0),
        is_dependent=opt_bool(body, "is_dependent", False),
        is_elderly=opt_bool(body, "is_elderly", False),
        is_disabled=opt_bool(body, "is_disabled", False),
    )
    domain.recompute_applicant_denorm(applicant)
    return ok(db.serialize(member), 201)


@bp.route("/pha/applicants/<aid>/members", methods=["GET"])
def list_members(aid):
    uid, role = authenticate()
    authorize(role, {"IntakeClerk", "HousingSpecialist", "PropertyManager", "Applicant"})
    applicant = get_or_404(db.applicants, aid, "ERR_APPLICANT_NOT_FOUND")
    require_ownership(role, uid, owner_applicant_id("applicant", applicant))
    records = [m for m in db.members.values() if m["applicant_id"] == aid]
    items, limit, offset, total = _paged(records)
    return ok_list(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Preference claims
# ---------------------------------------------------------------------------
@bp.route("/pha/applicants/<aid>/preference-claims", methods=["POST"])
def claim_preference(aid):
    uid, role = authenticate()
    authorize(role, {"IntakeClerk", "Applicant"})
    applicant = get_or_404(db.applicants, aid, "ERR_APPLICANT_NOT_FOUND")
    require_ownership(role, uid, owner_applicant_id("applicant", applicant))
    body = json_body()
    preference_type = need_enum(body, "preference_type", PREFERENCE_TYPES)
    claim = db.create(
        db.preference_claims,
        applicant_id=applicant["id"],
        preference_type=preference_type,
        status="CLAIMED",
        points_awarded=0,
    )
    return ok(db.serialize(claim), 201)


@bp.route("/pha/applicants/<aid>/preference-claims", methods=["GET"])
def list_preference_claims(aid):
    uid, role = authenticate()
    authorize(role, {"IntakeClerk", "HousingSpecialist", "PropertyManager", "Applicant"})
    applicant = get_or_404(db.applicants, aid, "ERR_APPLICANT_NOT_FOUND")
    require_ownership(role, uid, owner_applicant_id("applicant", applicant))
    records = [c for c in db.preference_claims.values() if c["applicant_id"] == aid]
    items, limit, offset, total = _paged(records)
    return ok_list(items, limit, offset, total)


@bp.route("/pha/preference-claims/<cid>/verify", methods=["POST"])
def verify_claim(cid):
    uid, role = authenticate()
    authorize(role, {"IntakeClerk"})
    claim = get_or_404(db.preference_claims, cid, "ERR_PREFERENCE_CLAIM_NOT_FOUND")
    if claim["status"] != "CLAIMED":
        raise ApiError("ERR_INVALID_STATE", "claim is not CLAIMED")
    body = json_body()
    decision = need_enum(body, "decision", {"VERIFY", "DENY"})
    if decision == "VERIFY":
        db.touch(
            claim,
            status="VERIFIED",
            points_awarded=domain.PREFERENCE_POINTS[claim["preference_type"]],
        )
        domain.recompute_total_points(claim["applicant_id"])
    else:
        db.touch(claim, status="DENIED", points_awarded=0)
    return ok(db.serialize(claim))


@bp.route("/pha/preference-claims/<cid>/revoke", methods=["POST"])
def revoke_claim(cid):
    uid, role = authenticate()
    authorize(role, {"IntakeClerk"})
    claim = get_or_404(db.preference_claims, cid, "ERR_PREFERENCE_CLAIM_NOT_FOUND")
    if claim["status"] != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE", "claim is not VERIFIED")
    db.touch(claim, status="CLAIMED", points_awarded=0)
    domain.recompute_total_points(claim["applicant_id"])
    return ok(db.serialize(claim))


# ---------------------------------------------------------------------------
# Applicant waitlist entries
# ---------------------------------------------------------------------------
@bp.route("/pha/applicants/<aid>/waitlist-entries", methods=["GET"])
def list_applicant_entries(aid):
    uid, role = authenticate()
    authorize(role, {"IntakeClerk", "HousingSpecialist", "PropertyManager", "Applicant"})
    applicant = get_or_404(db.applicants, aid, "ERR_APPLICANT_NOT_FOUND")
    require_ownership(role, uid, owner_applicant_id("applicant", applicant))
    records = [e for e in db.waitlist_entries.values() if e["applicant_id"] == aid]
    items, limit, offset, total = _paged(records)
    return ok_list(items, limit, offset, total)
