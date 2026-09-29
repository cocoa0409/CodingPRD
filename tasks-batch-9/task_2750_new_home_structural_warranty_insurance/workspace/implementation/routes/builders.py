"""Builder enrollment, underwriting, monitoring and default (PRD 3.1, 3.2)."""

from flask import Blueprint

import calc
import db
import listing
import response
import store
import validators as v
from errors import err
from middleware import (ROLE_ADJUSTER, ROLE_BUILDER, ROLE_COMPLIANCE,
                        ROLE_UNDERWRITER, endpoint)

bp = Blueprint("builders", __name__)

DECISIONS = ("APPROVE", "DECLINE", "REFER")
RESULTING_STATUS = {"APPROVE": "APPROVED", "DECLINE": "DECLINED", "REFER": "REFERRED"}


def _bad_builder_state(builder):
    return err("ERR_INVALID_BUILDER_STATE",
               "builder is in underwriting_status '%s'" % builder["underwriting_status"])


@bp.post("/builders")
@endpoint(ROLE_UNDERWRITER)
def create_builder(user_id, role):
    body = v.body()
    row = {
        "company_name": v.req_str(body, "company_name", 1, 120),
        "state_code": v.req_enum(body, "state_code", calc.STATE_CODES),
        "years_in_business": v.req_int(body, "years_in_business", 0, 100),
        "homes_closed_last_year": v.req_int(body, "homes_closed_last_year", 0, 5000),
        "claims_history_score": v.req_int(body, "claims_history_score", 0, 100),
        "financial_strength_tier": v.req_enum(body, "financial_strength_tier",
                                              calc.FINANCIAL_TIERS),
        "underwriting_status": "DRAFT",
        "risk_score": None,
        "risk_class": None,
        "risk_basis": None,
        "obligation_period_years": 2,
        "earned_premium_cents": 0,
        "incurred_loss_cents": 0,
        "loss_ratio": calc.round_places(0, 4),
        "monitoring_posture": "OPEN",
        "default_declared_at": None,
    }
    db.stamp_create(row)
    db.builders[row["id"]] = row
    return response.object_response(db.public(row), 201)


@bp.post("/builders/<builder_id>/submission")
@endpoint(ROLE_BUILDER)
def submit_builder(builder_id, user_id, role):
    # Rung 3 sits ahead of path existence and the subject is the path id itself.
    if user_id != builder_id:
        raise err("ERR_NOT_BUILDER_PRINCIPAL",
                  "X-User-ID does not match the addressed builder")
    builder = store.get_builder(builder_id)
    body = v.body()
    v.req_bool(body, "attestation_signed")
    if builder["underwriting_status"] != "DRAFT":
        raise _bad_builder_state(builder)
    builder["underwriting_status"] = "SUBMITTED"
    db.mark(builder)
    return response.object_response(db.public(builder))


@bp.post("/builders/<builder_id>/review-intake")
@endpoint(ROLE_UNDERWRITER)
def review_intake(builder_id, user_id, role):
    builder = store.get_builder(builder_id)
    body = v.body()
    v.opt_str(body, "intake_note", non_blank=False)
    if builder["underwriting_status"] not in ("SUBMITTED", "REFERRED"):
        raise _bad_builder_state(builder)
    score = calc.risk_score(builder["claims_history_score"],
                            builder["homes_closed_last_year"],
                            builder["years_in_business"],
                            builder["financial_strength_tier"])
    builder["risk_score"] = score
    builder["risk_class"] = calc.risk_class_for(score)
    builder["risk_basis"] = "INITIAL_UNDERWRITING"
    builder["underwriting_status"] = "UNDER_REVIEW"
    db.mark(builder)
    return response.object_response(db.public(builder))


@bp.post("/builders/<builder_id>/underwriting-reviews")
@endpoint(ROLE_UNDERWRITER)
def record_review(builder_id, user_id, role):
    builder = store.get_builder(builder_id)
    body = v.body()
    decision = v.req_enum(body, "decision", DECISIONS)
    notes = v.opt_str(body, "reviewer_notes", 1, 500)
    if builder["underwriting_status"] != "UNDER_REVIEW":
        raise _bad_builder_state(builder)
    if decision == "APPROVE" and builder["risk_class"] == "D":
        raise err("ERR_RISK_CLASS_INELIGIBLE",
                  "a class D builder may not be approved")
    resulting = RESULTING_STATUS[decision]
    review = {
        "builder_id": builder["id"],
        "decision": decision,
        "reviewer_notes": notes,
        "reviewer_user_id": user_id,
        "risk_score_snapshot": builder["risk_score"],
        "risk_class_snapshot": builder["risk_class"],
        "resulting_underwriting_status": resulting,
    }
    db.stamp_create(review, versioned=False)
    db.underwriting_reviews[review["id"]] = review
    builder["underwriting_status"] = resulting
    db.mark(builder)
    return response.object_response(db.public(review), 201)


@bp.post("/builders/<builder_id>/reassessment")
@endpoint(ROLE_UNDERWRITER)
def reassess_builder(builder_id, user_id, role):
    builder = store.get_builder(builder_id)
    body = v.body()
    years = v.opt_int(body, "years_in_business", 0, 100)
    homes = v.opt_int(body, "homes_closed_last_year", 0, 5000)
    history = v.opt_int(body, "claims_history_score", 0, 100)
    tier = v.opt_enum(body, "financial_strength_tier", calc.FINANCIAL_TIERS)
    if builder["underwriting_status"] != "APPROVED":
        raise _bad_builder_state(builder)
    if years is not None:
        builder["years_in_business"] = years
    if homes is not None:
        builder["homes_closed_last_year"] = homes
    if history is not None:
        builder["claims_history_score"] = history
    if tier is not None:
        builder["financial_strength_tier"] = tier
    effective_score = calc.observed_claims_score(builder["loss_ratio"])
    effective_volume = store.enrolled_policy_count(builder["id"])
    score = calc.risk_score(effective_score, effective_volume,
                            builder["years_in_business"],
                            builder["financial_strength_tier"])
    builder["risk_score"] = score
    builder["risk_class"] = calc.risk_class_for(score)
    builder["risk_basis"] = "RENEWAL_REASSESSMENT"
    if builder["risk_class"] == "D":
        builder["underwriting_status"] = "SUSPENDED"
    db.mark(builder)
    return response.object_response(db.public(builder))


@bp.post("/builders/<builder_id>/suspension")
@endpoint(ROLE_COMPLIANCE)
def suspend_builder(builder_id, user_id, role):
    builder = store.get_builder(builder_id)
    v.req_str(v.body(), "reason")
    if builder["underwriting_status"] != "APPROVED":
        raise _bad_builder_state(builder)
    builder["underwriting_status"] = "SUSPENDED"
    db.mark(builder)
    return response.object_response(db.public(builder))


@bp.post("/builders/<builder_id>/reinstatement")
@endpoint(ROLE_UNDERWRITER)
def reinstate_builder(builder_id, user_id, role):
    builder = store.get_builder(builder_id)
    v.req_str(v.body(), "reason")
    if builder["underwriting_status"] != "SUSPENDED":
        raise _bad_builder_state(builder)
    if builder["monitoring_posture"] == "FROZEN":
        raise err("ERR_BUILDER_POSTURE_FROZEN",
                  "a builder whose monitoring posture is FROZEN may not be reinstated")
    builder["underwriting_status"] = "APPROVED"
    db.mark(builder)
    return response.object_response(db.public(builder))


@bp.post("/builders/<builder_id>/default-declaration")
@endpoint(ROLE_COMPLIANCE)
def declare_default(builder_id, user_id, role):
    builder = store.get_builder(builder_id)
    v.req_str(v.body(), "reason")
    if builder["underwriting_status"] not in ("APPROVED", "SUSPENDED"):
        raise _bad_builder_state(builder)
    builder["underwriting_status"] = "DEFAULTED"
    builder["default_declared_at"] = db.iso_ms(db.clock_now())
    store.builder_default_cascade(builder)
    db.mark(builder)
    return response.object_response(db.public(builder))


@bp.get("/builders/<builder_id>")
@endpoint(ROLE_UNDERWRITER, ROLE_COMPLIANCE, ROLE_ADJUSTER, ROLE_BUILDER)
def read_builder(builder_id, user_id, role):
    return response.object_response(db.public(store.get_builder(builder_id)))


@bp.get("/builders")
@endpoint(ROLE_UNDERWRITER, ROLE_COMPLIANCE)
def list_builders(user_id, role):
    rows = store.all_rows(db.builders)
    rows = listing.eq_filter(rows, "underwriting_status")
    rows = listing.eq_filter(rows, "risk_class")
    rows = listing.eq_filter(rows, "monitoring_posture")
    return response.paginate(rows)


@bp.get("/builders/<builder_id>/underwriting-reviews")
@endpoint(ROLE_UNDERWRITER, ROLE_COMPLIANCE)
def list_reviews(builder_id, user_id, role):
    store.get_builder(builder_id)
    rows = [r for r in store.all_rows(db.underwriting_reviews)
            if r["builder_id"] == builder_id]
    rows = listing.eq_filter(rows, "decision")
    rows.sort(key=db.sort_key_created, reverse=True)   # newest first
    return response.paginate(rows)


@bp.get("/builders/<builder_id>/loss-monitor")
@endpoint(ROLE_UNDERWRITER, ROLE_COMPLIANCE)
def loss_monitor(builder_id, user_id, role):
    builder = store.get_builder(builder_id)
    return response.object_response({
        "earned_premium_cents": builder["earned_premium_cents"],
        "incurred_loss_cents": builder["incurred_loss_cents"],
        "loss_ratio": builder["loss_ratio"],
        "monitoring_posture": builder["monitoring_posture"],
        "policy_count": sum(
            1 for p in store.policies_of_builder(builder_id)
            if p["coverage_status"] in store.DENOMINATOR_COVERAGE_STATES
            and p["premium_status"] == "PAID"),
        "open_claim_count": store.open_claim_count(builder_id),
    })
