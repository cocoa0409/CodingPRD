"""Dispute routes: the employee challenge that defers cash at payout time."""

from flask import Blueprint

import db
from errors import ApiError
from middleware import (COMPENSATION_COMMITTEE, EMPLOYEE, FINANCE_CONTROLLER,
                        HR_BUSINESS_PARTNER, PLAN_ADMIN, authenticate, get_body,
                        opt_int, opt_string, query_param, req_enum, req_id,
                        req_int, req_string)
from response import object_response
from routes.common import paginated
from serialize import dispute_out
from services import lookup, rollup

bp = Blueprint("disputes", __name__)

DETAIL_ROLES = [PLAN_ADMIN, COMPENSATION_COMMITTEE, HR_BUSINESS_PARTNER,
                FINANCE_CONTROLLER, EMPLOYEE]
LIST_ROLES = [PLAN_ADMIN, COMPENSATION_COMMITTEE, HR_BUSINESS_PARTNER,
              FINANCE_CONTROLLER]
RESOLUTIONS = {"UPHOLD", "ADJUST"}


@bp.route("/disputes", methods=["POST"])
def create_dispute():
    caller = authenticate([EMPLOYEE])
    body = get_body()

    plan_id = req_id(body, "plan_id")
    award_id = req_id(body, "award_id")
    participant_id = req_id(body, "participant_id")
    dispute_reason = req_string(body, "dispute_reason")
    claimed_amount_cents = opt_int(body, "claimed_amount_cents", minimum=0)

    plan = lookup.plan(plan_id)
    lookup.participant(participant_id)
    award = lookup.award(award_id)

    if caller.user_id != award["participant_id"]:
        raise ApiError("ERR_FORBIDDEN_RESOURCE_OWNERSHIP",
                       "An employee may only dispute their own award")
    if plan["status"] not in ("LOCKED", "PAID_OUT"):
        raise ApiError("ERR_DISPUTE_NOT_ALLOWED_YET")
    if award["plan_id"] != plan_id or award["participant_id"] != participant_id:
        raise ApiError("ERR_PLAN_SCOPE_MISMATCH",
                       "The award does not belong to this plan and participant")

    dispute = db.base_record()
    dispute.update({
        "plan_id": plan_id,
        "award_id": award_id,
        "participant_id": participant_id,
        "dispute_reason": dispute_reason,
        "claimed_amount_cents": claimed_amount_cents,
        "status": "OPEN",
        "reviewer_note": None,
        "resolution": None,
        "adjusted_amount_cents": None,
        "resolution_note": None,
        "assigned_by_user_id": None,
        "resolved_by_user_id": None,
    })
    db.disputes[dispute["id"]] = dispute
    return object_response(dispute_out(dispute), 201)


@bp.route("/disputes/<dispute_id>/assign-review", methods=["POST"])
def assign_review(dispute_id):
    caller = authenticate([HR_BUSINESS_PARTNER])
    dispute = lookup.dispute(dispute_id)
    body = get_body()
    reviewer_note = opt_string(body, "reviewer_note")

    if dispute["status"] != "OPEN":
        raise ApiError("ERR_DISPUTE_NOT_UNDER_REVIEW",
                       "Assignment requires a dispute in OPEN")

    dispute["assigned_by_user_id"] = caller.user_id
    if reviewer_note is not None:
        dispute["reviewer_note"] = reviewer_note
    dispute["status"] = "UNDER_REVIEW"
    db.touch(dispute)
    return object_response(dispute_out(dispute))


@bp.route("/disputes/<dispute_id>/resolve", methods=["POST"])
def resolve_dispute(dispute_id):
    caller = authenticate([HR_BUSINESS_PARTNER])
    dispute = lookup.dispute(dispute_id)
    body = get_body()
    resolution = req_enum(body, "resolution", RESOLUTIONS)
    adjusted_amount_cents = None
    if resolution == "ADJUST":
        adjusted_amount_cents = req_int(body, "adjusted_amount_cents", minimum=0)
    resolution_note = opt_string(body, "resolution_note")

    plan = lookup.plan(dispute["plan_id"])
    award = lookup.award(dispute["award_id"])

    if dispute["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_DISPUTE_NOT_UNDER_REVIEW",
                       "Resolution requires a dispute in UNDER_REVIEW")
    if resolution == "ADJUST" \
            and adjusted_amount_cents > 2 * award["final_award_cents"]:
        raise ApiError("ERR_DISPUTE_ADJUSTMENT_EXCEEDS_LIMIT")

    award_before = db.snapshot(award)
    if resolution == "UPHOLD":
        if award["payment_status"] == "DEFERRED":
            award["payment_status"] = ("PAID" if award["payout_amount_cents"] > 0
                                       else "FORFEITED")
        dispute["resolution"] = "UPHOLD"
        dispute["status"] = "RESOLVED_UPHELD"
    else:
        plan["dispute_adjustment_cents"] += (adjusted_amount_cents
                                             - award["final_award_cents"])
        award["payout_amount_cents"] = adjusted_amount_cents
        award["payment_status"] = "PAID"
        dispute["resolution"] = "ADJUST"
        dispute["adjusted_amount_cents"] = adjusted_amount_cents
        dispute["status"] = "RESOLVED_ADJUSTED"

    db.bump_if_changed(award, award_before)
    if resolution_note is not None:
        dispute["resolution_note"] = resolution_note
    dispute["resolved_by_user_id"] = caller.user_id
    db.touch(dispute)

    plan_before = db.snapshot(plan)
    rollup.refresh_payout_totals(plan)
    db.bump_if_changed(plan, plan_before)
    return object_response(dispute_out(dispute))


@bp.route("/disputes/<dispute_id>", methods=["GET"])
def get_dispute(dispute_id):
    authenticate(DETAIL_ROLES)
    return object_response(dispute_out(lookup.dispute(dispute_id)))


@bp.route("/disputes", methods=["GET"])
def list_disputes():
    authenticate(LIST_ROLES)
    records = db.ordered(db.disputes)
    for param in ("plan_id", "award_id", "participant_id", "status"):
        value = query_param(param)
        if value is not None:
            records = [r for r in records if r[param] == value]
    return paginated(records, dispute_out)
