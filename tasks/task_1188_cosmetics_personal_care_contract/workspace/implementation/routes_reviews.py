"""RegulatoryReview lifecycle endpoints."""
from flask import Blueprint, g

from core import (body, err, require_roles, success, touch)
from services import (formula_hold_cascade, must_get, serialize_review)
from store import db

bp = Blueprint("reviews", __name__)

REVIEW_READ_ROLES = ("RegulatoryAffairs", "FormulationChemist", "PlantDirector")


@bp.get("/cosmfg/reviews/<rid>")
@require_roles(*REVIEW_READ_ROLES)
def get_review(rid):
    return success(serialize_review(must_get(db.reviews, rid, "RegulatoryReview")))


@bp.post("/cosmfg/reviews/<rid>/claim")
@require_roles("RegulatoryAffairs")
def claim_review(rid):
    r = must_get(db.reviews, rid, "RegulatoryReview")
    if r["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "Only a SUBMITTED review may be claimed")
    r["status"] = "UNDER_REVIEW"
    r["reviewer_user_id"] = g.user_id
    touch(r)
    return success(serialize_review(r))


@bp.post("/cosmfg/reviews/<rid>/approve")
@require_roles("RegulatoryAffairs")
def approve_review(rid):
    r = must_get(db.reviews, rid, "RegulatoryReview")
    if r["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", 409, "Only an UNDER_REVIEW review may be approved")
    r["status"] = "APPROVED"
    touch(r)
    formula = db.formulas.get(r["formula_id"])
    if r["review_scope"] == "INCI_LIST":
        if formula is not None and formula["status"] == "IN_REVIEW":
            formula["status"] = "APPROVED"
            touch(formula)
    else:  # LABEL_ARTWORK
        for o in db.orders.values():
            if (o["formula_id"] == r["formula_id"] and o["status"] == "FILLING"
                    and o["filled_units"] >= o["requested_units"]):
                o["status"] = "COMPLETED"
                touch(o)
                customer = db.customers.get(o["customer_id"])
                if customer is not None:
                    customer["outstanding_balance_cents"] = (
                        customer["outstanding_balance_cents"] - o["quote_total_cents"])
                    touch(customer)
    return success(serialize_review(r))


@bp.post("/cosmfg/reviews/<rid>/request-changes")
@require_roles("RegulatoryAffairs")
def request_changes(rid):
    r = must_get(db.reviews, rid, "RegulatoryReview")
    if r["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", 409,
            "Only an UNDER_REVIEW review may be sent back for changes")
    b = body()
    comment = b.get("comment")
    if comment is not None and not isinstance(comment, str):
        err("ERR_VALIDATION", 400, "comment must be a string")
    r["status"] = "CHANGES_REQUESTED"
    r["comment"] = comment
    touch(r)
    formula = db.formulas.get(r["formula_id"])
    if formula is not None and formula["status"] in ("IN_REVIEW", "ACTIVE"):
        formula["status"] = "CHANGES_REQUESTED"
        touch(formula)
        formula_hold_cascade(formula)
    return success(serialize_review(r))


@bp.post("/cosmfg/reviews/<rid>/resubmit")
@require_roles("FormulationChemist")
def resubmit_review(rid):
    r = must_get(db.reviews, rid, "RegulatoryReview")
    if r["status"] != "CHANGES_REQUESTED":
        err("ERR_INVALID_STATE", 409,
            "Only a CHANGES_REQUESTED review may be resubmitted")
    formula = db.formulas.get(r["formula_id"])
    if formula is None or formula["status"] != "IN_REVIEW":
        err("ERR_INVALID_STATE", 409,
            "The referenced formula must be back IN_REVIEW before resubmission")
    r["status"] = "SUBMITTED"
    touch(r)
    return success(serialize_review(r))
