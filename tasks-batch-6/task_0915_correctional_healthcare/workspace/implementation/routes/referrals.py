"""Off-site specialty referrals and the utilization-review gate."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import serializers
import store
from constants import (
    DECISION, PEER_DECISION, SPECIALTY, UR_DEFER_EXTENSION_HOURS, UR_MAX_DEFERRALS,
    UR_PEER_REVIEW_WINDOW_HOURS, URGENCY,
)
from envelope import created, listing, ok, page_params
from errors import ApiError
from ladder import Ctx
from routes.chronic import intake_gate
from timeutil import add_hours

bp = Blueprint("referrals", __name__)

NOT_FOUND = "ERR_REFERRAL_RECORD_NOT_FOUND"


@bp.post("/specialty-referrals")
def request_referral():
    ctx = Ctx(roles=("Provider",))
    ctx.body_inmate("inmate_id")
    ctx.freeze_gate()
    ctx.custody_gate()
    ctx.require("inmate_id", "specialty", "urgency")
    ctx.check_type("inmate_id", "string")
    ctx.enum("specialty", SPECIALTY)
    ctx.enum("urgency", URGENCY)
    intake_gate(ctx)
    ctx.run()

    row = store.base_row()
    row.update({
        "inmate_id": ctx.inmate["id"],
        "specialty": ctx.body["specialty"],
        "urgency": ctx.body["urgency"],
        "requested_at": store.now(),
        "status": "REQUESTED",
        "no_show_count": 0,
        "authorized_at": None,
    })
    store.specialty_referrals[row["id"]] = row
    return created(serializers.specialty_referral(row))


@bp.get("/specialty-referrals")
def list_referrals():
    ctx = Ctx(roles=("Provider", "UtilizationReviewer", "PeerReviewer", "CustodyOfficer",
                     "HealthServicesAdmin"))
    ctx.run()

    limit, offset = page_params(request.args)
    rows = list(store.specialty_referrals.values())
    for field in ("inmate_id", "status", "urgency"):
        wanted = request.args.get(field)
        if wanted:
            rows = [r for r in rows if r[field] == wanted]
    rows = store.sort_rows(rows)
    return listing(serializers.many(serializers.specialty_referral, rows), limit, offset)


@bp.get("/specialty-referrals/<referral_id>")
def read_referral(referral_id):
    ctx = Ctx(roles=("Provider", "UtilizationReviewer", "PeerReviewer", "CustodyOfficer",
                     "HealthServicesAdmin"))
    ctx.need("referral", store.specialty_referrals, referral_id, NOT_FOUND)
    ctx.run()
    return ok(serializers.specialty_referral(ctx.row("referral")))


def _bind_referral(ctx, referral_id):
    def bind(row):
        ctx.inmate = store.inmates.get(row["inmate_id"])
    ctx.need("referral", store.specialty_referrals, referral_id, NOT_FOUND, on_found=bind)


@bp.post("/specialty-referrals/<referral_id>/submit-for-review")
def submit_for_review(referral_id):
    ctx = Ctx(roles=("Provider",))
    _bind_referral(ctx, referral_id)
    ctx.freeze_gate()
    ctx.check_type("retrospective", "boolean")
    ctx.status_in(lambda: ctx.row("referral"), ("REQUESTED",))
    ctx.run()

    referral = ctx.row("referral")
    review = store.base_row()
    review.update({
        "referral_id": referral["id"],
        "opened_at": store.now(),
        "decision": None,
        "decided_at": None,
        "decided_by_user_id": None,
        "peer_reviewer_user_id": None,
        "defer_count": 0,
        "retrospective": bool(ctx.body.get("retrospective") or False),
        "status": "OPEN",
    })
    review["turnaround_deadline_at"] = calc.ur_turnaround_deadline(review, referral)
    store.utilization_reviews[review["id"]] = review

    referral["status"] = "PENDING_UR"
    store.touch(referral)
    return created(serializers.utilization_review(review))


@bp.get("/specialty-referrals/<referral_id>/utilization-reviews")
def list_reviews(referral_id):
    ctx = Ctx(roles=("Provider", "UtilizationReviewer", "PeerReviewer", "HealthServicesAdmin"))
    ctx.need("referral", store.specialty_referrals, referral_id, NOT_FOUND)
    ctx.run()

    limit, offset = page_params(request.args)
    rows = [r for r in store.utilization_reviews.values() if r["referral_id"] == referral_id]
    if request.args.get("status"):
        rows = [r for r in rows if r["status"] == request.args["status"]]
    rows = store.sort_rows(rows, key="opened_at")
    return listing(serializers.many(serializers.utilization_review, rows), limit, offset)


def _bind_review(ctx, review_id):
    def bind(row):
        referral = store.specialty_referrals.get(row["referral_id"])
        ctx.rows["referral"] = referral
        if referral is not None:
            ctx.inmate = store.inmates.get(referral["inmate_id"])
    ctx.need("review", store.utilization_reviews, review_id, NOT_FOUND, on_found=bind)


@bp.post("/utilization-reviews/<review_id>/decide")
def decide(review_id):
    ctx = Ctx(roles=("UtilizationReviewer",))
    _bind_review(ctx, review_id)
    ctx.freeze_gate()
    ctx.require("decision")
    ctx.enum("decision", DECISION)
    ctx.status_in(lambda: ctx.row("review"), ("OPEN",))

    def referral_pending():
        referral = ctx.row("referral")
        if referral is not None and referral["status"] != "PENDING_UR":
            raise ApiError("ERR_INVALID_STATE", "the parent referral is not PENDING_UR")
    ctx.cross_state(referral_pending)

    def defer_cap():
        if ctx.body.get("decision") == "DEFER" and ctx.row("review")["defer_count"] >= UR_MAX_DEFERRALS:
            raise ApiError("ERR_MAX_DEFERRALS_EXCEEDED", "deferral limit reached")
    ctx.caps(defer_cap)
    ctx.run()

    review = ctx.row("review")
    referral = ctx.row("referral")
    decision = ctx.body["decision"]
    review["decision"] = decision
    review["decided_at"] = store.now()
    review["decided_by_user_id"] = ctx.user_id

    if decision == "APPROVE":
        review["status"] = "APPROVED"
        referral["status"] = "AUTHORIZED"
        referral["authorized_at"] = store.now()
        store.touch(referral)
    elif decision == "DENY":
        review["status"] = "DENIED"          # the referral STAYS PENDING_UR
    else:
        review["status"] = "DEFERRED"
        review["defer_count"] += 1
        review["turnaround_deadline_at"] = add_hours(review["turnaround_deadline_at"],
                                                     UR_DEFER_EXTENSION_HOURS)
    store.touch(review)
    return ok(serializers.utilization_review(review))


@bp.post("/utilization-reviews/<review_id>/supply-information")
def supply_information(review_id):
    ctx = Ctx(roles=("Provider",))
    _bind_review(ctx, review_id)
    ctx.freeze_gate()
    ctx.require("information_text")
    ctx.check_type("information_text", "string")
    ctx.status_in(lambda: ctx.row("review"), ("DEFERRED",))
    ctx.run()

    review = ctx.row("review")
    review["status"] = "OPEN"
    review["decision"] = None
    review["decided_at"] = None
    # decided_by_user_id is deliberately RETAINED for the later segregation check.
    store.touch(review)
    return ok(serializers.utilization_review(review))


@bp.post("/utilization-reviews/<review_id>/escalate-peer-review")
def escalate_peer_review(review_id):
    ctx = Ctx(roles=("Provider",))
    _bind_review(ctx, review_id)
    ctx.freeze_gate()
    ctx.status_in(lambda: ctx.row("review"), ("DENIED",))

    def window():
        review = ctx.row("review")
        decided = review.get("decided_at")
        if decided is None:
            return
        limit = decided.dt + timedelta(hours=UR_PEER_REVIEW_WINDOW_HOURS)
        if store.clock_dt() > limit:
            raise ApiError("ERR_PEER_REVIEW_WINDOW_EXPIRED", "the peer-review window has closed")
    ctx.temporal(window)
    ctx.run()

    review = ctx.row("review")
    review["status"] = "PEER_REVIEW"
    store.touch(review)
    return ok(serializers.utilization_review(review))


@bp.post("/utilization-reviews/<review_id>/peer-decide")
def peer_decide(review_id):
    ctx = Ctx(roles=("PeerReviewer",))
    _bind_review(ctx, review_id)
    ctx.freeze_gate()
    ctx.require("peer_decision")
    ctx.enum("peer_decision", PEER_DECISION)
    ctx.status_in(lambda: ctx.row("review"), ("PEER_REVIEW",))

    def not_own_denial():
        review = ctx.row("review")
        if ctx.user_id == review.get("decided_by_user_id"):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "a reviewer may not resolve their own denial")
    ctx.segregation(not_own_denial)
    ctx.run()

    review = ctx.row("review")
    referral = ctx.row("referral")
    review["peer_reviewer_user_id"] = ctx.user_id
    if ctx.body["peer_decision"] == "OVERTURN":
        review["status"] = "OVERTURNED"
        referral["status"] = "AUTHORIZED"
        referral["authorized_at"] = store.now()
    else:
        review["status"] = "UPHELD"
        referral["status"] = "DENIED"
    store.touch(referral)
    store.touch(review)
    return ok(serializers.utilization_review(review))
