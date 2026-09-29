"""Committee selection reviews."""
from decimal import Decimal

from flask import Blueprint, request

import calc
import cascade
import derive
from common import API, created, get_household, get_review, listing, match, okay
from errors import fail
from payload import body, qenum, qid, qstring, vdecimal, venum, vstring
from rbac import auth
from store import bump, db, stamp

bp = Blueprint("reviews", __name__)

DIMENSIONS = ("NEED", "ABILITY", "WILLINGNESS")
RECOMMENDATIONS = ("ADVANCE", "ABSTAIN", "VETO_WILLINGNESS")


def refresh_committee_figures(household):
    program = derive.program_of_household(household)
    _, willingness, _ = calc.committee_state(household, program)
    household["willingness_score"] = willingness
    household["composite_selection_score"] = calc.composite_score(
        household.get("need_score") or 0,
        household.get("ability_to_pay_score") or 0,
        willingness,
    )
    bump(household)


@bp.post(API + "/selection-reviews")
def create_review():
    actor = auth("SelectionCommitteeMember")
    data = body()
    raw = data.get("household_id")
    household = get_household(raw) if isinstance(raw, str) and raw else None

    household_id = vstring(data, "household_id", 1, None, required=True)
    dimension = venum(data, "dimension", DIMENSIONS, required=True)
    score = vdecimal(data, "score", minimum=0, maximum=100, required=True)
    recommendation = venum(data, "recommendation", RECOMMENDATIONS, required=True)
    reason = vstring(data, "documented_reason", 10, 500, default=None, nullable=True)
    if household is None:
        household = get_household(household_id)

    if household.get("selection_status") != "COMMITTEE_REVIEW":
        fail("ERR_TRANSITION_NOT_ALLOWED",
             "Reviews may only be filed on a household under committee review.")
    cascade.guard_not_frozen(derive.program_of_household(household))

    for existing in db.reviews.values():
        if existing.get("household_id") != household["id"]:
            continue
        if existing.get("status") != "SUBMITTED":
            continue
        if existing.get("dimension") != dimension:
            continue
        if existing.get("reviewer_user_id") != actor.user_id:
            continue
        fail("ERR_DUPLICATE_REVIEW")

    if recommendation == "VETO_WILLINGNESS":
        if dimension != "WILLINGNESS" or reason is None or len(reason) < 10:
            fail("ERR_VETO_REASON_REQUIRED")

    row = {
        "household_id": household["id"],
        "reviewer_user_id": actor.user_id,
        "dimension": dimension,
        "score": score,
        "recommendation": recommendation,
        "documented_reason": reason,
        "status": "SUBMITTED",
    }
    stamp(row)
    db.reviews[row["id"]] = row

    refresh_committee_figures(household)
    return created(derive.public_review(row))


@bp.get(API + "/selection-reviews")
def list_reviews():
    auth("ProgramAdmin", "FamilyServicesCoordinator", "SelectionCommitteeMember",
         "MortgageOfficer")
    household_id = qid("household_id")
    dimension = qenum("dimension", DIMENSIONS)
    status = qenum("status", ("SUBMITTED", "RETRACTED"))
    reviewer = qstring("reviewer_user_id")
    rows = [r for r in db.reviews.values()
            if match(r, "household_id", household_id)
            and match(r, "dimension", dimension)
            and match(r, "status", status)
            and match(r, "reviewer_user_id", reviewer)]
    return listing(rows, derive.public_review)


@bp.get(API + "/selection-reviews/<rid>")
def read_review(rid):
    auth("ProgramAdmin", "FamilyServicesCoordinator", "SelectionCommitteeMember",
         "MortgageOfficer")
    review = get_review(rid)
    return okay(derive.public_review(review))


@bp.post(API + "/selection-reviews/<rid>/retract")
def retract_review(rid):
    auth("SelectionCommitteeMember")
    review = get_review(rid)
    data = body()
    vstring(data, "retraction_reason", 1, None, default=None, nullable=True)

    cascade.state_gate(review, "status", ("SUBMITTED",), ())
    household = db.households.get(review.get("household_id"))
    if household is not None:
        cascade.guard_not_frozen(derive.program_of_household(household))

    review["status"] = "RETRACTED"
    bump(review)
    if household is not None:
        refresh_committee_figures(household)
    return okay(derive.public_review(review))
