"""Sealed bids, the responsiveness determination and the responsibility
review (PRD §3.4 and §3.5)."""

from flask import Blueprint, g

import calc
import serializers
import services
import store
import validation as v
from errors import ApiError

bp = Blueprint("bids", __name__)

BID_STATES = ("ISSUED", "QUESTION_PERIOD_CLOSED")
DETERMINATION_STATES = ("BIDS_OPENED", "EVALUATION")
NONRESPONSIVE_REASON_CODES = (
    "MATERIAL_REQUIREMENT_UNMET", "ADDENDUM_NOT_ACKNOWLEDGED", "LATE_SUBMISSION",
    "VENDOR_DEBARRED", "VENDOR_SUSPENDED", "OFFICER_DETERMINATION",
)


@bp.post("/procurement/bids")
@v.endpoint(["Vendor"])
def submit_bid():
    data = v.body()
    solicitation_id = v.req_str(data, "solicitation_id")
    vendor_id = v.req_str(data, "vendor_id")
    total_price_cents = v.req_int(data, "total_price_cents", minimum=1)
    acknowledged = v.int_array(data, "acknowledged_addendum_sequences", default=[])
    expected_version = v.req_int(data, "expected_solicitation_version")

    solicitation = services.must("solicitations", solicitation_id)
    vendor = services.must("vendors", vendor_id)

    if g.user_id != vendor["id"]:
        raise ApiError("ERR_VENDOR_IDENTITY_MISMATCH")

    if expected_version != solicitation["version"]:
        raise ApiError("ERR_STALE_SOLICITATION_VERSION")

    if solicitation["status"] not in BID_STATES:
        raise ApiError("ERR_INVALID_SOLICITATION_STATE")

    if store.now() > solicitation["effective_bid_due_utc"]:
        raise ApiError("ERR_BID_DEADLINE_PASSED")

    if vendor["eligibility_status"] != "ELIGIBLE":
        raise ApiError("ERR_VENDOR_NOT_ELIGIBLE")

    bid = store.insert("bids", store.row("bids", {
        "solicitation_id": solicitation["id"],
        "vendor_id": vendor["id"],
        "total_price_cents": total_price_cents,
        "acknowledged_addendum_sequences": list(acknowledged),
        "submitted_at_utc": store.now(),
        "responsiveness_status": "UNREVIEWED",
        "responsibility_status": "NOT_REVIEWED",
        "evaluated_price_cents": None,
        "corrected_total_price_cents": None,
        "informality_loading_cents": 0,
        "nonresponsive_reason_codes": [],
        "responsiveness_decided_at_utc": None,
        "responsiveness_decided_by_user_id": None,
        "superseded_by_bid_id": None,
    }))

    for earlier in services.bids_of(solicitation):
        if earlier["id"] == bid["id"] or earlier["vendor_id"] != vendor["id"]:
            continue
        if earlier["responsiveness_status"] in ("UNREVIEWED", "RESPONSIVE"):
            v.set_field(earlier, "responsiveness_status", "WITHDRAWN")
            v.set_field(earlier, "superseded_by_bid_id", bid["id"])

    v.touch(solicitation)
    return ("obj", bid, serializers.bid, 201)


@bp.get("/procurement/bids/<bid_id>")
@v.endpoint(v.ALL_ROLES)
def read_bid(bid_id):
    return ("obj", services.must("bids", bid_id), serializers.bid, 200)


@bp.get("/procurement/bids")
@v.endpoint(v.ALL_ROLES)
def list_bids():
    limit, offset = v.pagination()
    filters = {
        "solicitation_id": v.query("solicitation_id"),
        "vendor_id": v.query("vendor_id"),
        "responsiveness_status": v.query("responsiveness_status"),
        "responsibility_status": v.query("responsibility_status"),
        "superseded_by_bid_id": v.query("superseded_by_bid_id"),
    }
    rows = [r for r in store.ordered(store.values("bids")) if v.match_filters(r, filters)]
    page, total = v.paginate(rows, limit, offset)
    return ("list", page, serializers.bid, limit, offset, total)


@bp.post("/procurement/bids/<bid_id>/responsiveness")
@v.endpoint(["ProcurementOfficer"])
def record_responsiveness(bid_id):
    data = v.body()
    determination = v.req_enum(data, "determination", ("RESPONSIVE", "NONRESPONSIVE"))
    reason_codes = v.code_array(data, "reason_codes", NONRESPONSIVE_REASON_CODES)
    corrected = v.opt_int(data, "corrected_total_price_cents", minimum=1)

    bid = services.must("bids", bid_id)
    solicitation = services.must("solicitations", bid["solicitation_id"])

    if solicitation["status"] not in DETERMINATION_STATES:
        raise ApiError("ERR_INVALID_SOLICITATION_STATE")
    if bid["responsiveness_status"] != "UNREVIEWED":
        raise ApiError("ERR_INVALID_BID_STATE")

    acknowledged = bid["acknowledged_addendum_sequences"]

    if determination == "RESPONSIVE":
        for requirement in services.requirements_of(solicitation):
            if requirement["materiality"] != "MATERIAL":
                continue
            sequence = requirement["introduced_by_addendum_sequence"]
            if sequence > 0 and sequence not in acknowledged:
                raise ApiError("ERR_MATERIAL_REQUIREMENT_UNMET")

        base = corrected if corrected is not None else bid["total_price_cents"]
        unacked = 0
        for addendum in services.addenda_of(solicitation):
            if (addendum["acknowledgment_required"]
                    and not addendum["adds_material_requirement"]
                    and addendum["sequence_number"] not in acknowledged):
                unacked += 1
        loading = calc.informality_loading(base, unacked)
        if corrected is not None:
            v.set_field(bid, "corrected_total_price_cents", corrected)
        v.set_field(bid, "informality_loading_cents", loading)
        v.set_field(bid, "evaluated_price_cents", base + loading)
        v.set_field(bid, "responsiveness_status", "RESPONSIVE")
    else:
        if corrected is not None:
            v.set_field(bid, "corrected_total_price_cents", corrected)
        applied = list(reason_codes) if reason_codes else ["OFFICER_DETERMINATION"]
        bid["nonresponsive_reason_codes"] = bid["nonresponsive_reason_codes"] + applied
        v.set_field(bid, "responsiveness_status", "NONRESPONSIVE")

    v.set_field(bid, "responsiveness_decided_at_utc", store.now())
    v.set_field(bid, "responsiveness_decided_by_user_id", g.user_id)
    v.touch(bid)

    if solicitation["status"] == "BIDS_OPENED":
        v.set_field(solicitation, "status", "EVALUATION")
    services.recompute_apparent_low_bid(solicitation)
    return ("obj", bid, serializers.bid, 200)


@bp.post("/procurement/bids/<bid_id>/responsibility-reviews")
@v.endpoint(["ResponsibilityReviewer"])
def record_responsibility_review(bid_id):
    data = v.body()
    financial = v.req_int(data, "financial_capacity_score", minimum=0, maximum=100)
    performance = v.req_int(data, "past_performance_score", minimum=0, maximum=100)
    integrity = v.req_int(data, "integrity_score", minimum=0, maximum=100)
    determination = v.req_enum(data, "determination", ("RESPONSIBLE", "NONRESPONSIBLE"))
    notes = v.opt_str(data, "notes")

    bid = services.must("bids", bid_id)
    solicitation = services.must("solicitations", bid["solicitation_id"])
    vendor = services.must("vendors", bid["vendor_id"])

    if bid["responsibility_status"] != "NOT_REVIEWED":
        raise ApiError("ERR_INVALID_BID_STATE")
    if bid["responsiveness_status"] != "RESPONSIVE":
        raise ApiError("ERR_INVALID_BID_STATE")

    if determination == "RESPONSIBLE" and vendor["eligibility_status"] != "ELIGIBLE":
        raise ApiError("ERR_VENDOR_NOT_ELIGIBLE")

    if g.user_id == bid["responsiveness_decided_by_user_id"]:
        raise ApiError("ERR_REVIEWER_CONFLICT")

    profile, penalty, score = calc.composite_score(
        financial, performance, integrity,
        solicitation["estimated_value_cents"], vendor["debarment_strike_count"],
    )

    if determination == "RESPONSIBLE" and score < calc.RESPONSIBLE_THRESHOLD:
        raise ApiError("ERR_RESPONSIBILITY_SCORE_BELOW_THRESHOLD")

    if solicitation["apparent_low_bid_id"] != bid["id"]:
        raise ApiError("ERR_NOT_APPARENT_LOW_BIDDER")

    review = store.insert("reviews", store.row("reviews", {
        "bid_id": bid["id"],
        "reviewer_user_id": g.user_id,
        "financial_capacity_score": financial,
        "past_performance_score": performance,
        "integrity_score": integrity,
        "weight_profile": profile,
        "strike_penalty_points": penalty,
        "composite_score": score,
        "determination": determination,
        "decided_at_utc": store.now(),
        "notes": notes,
        "superseded_at_utc": None,
    }))

    v.set_field(bid, "responsibility_status", determination)
    v.touch(bid)

    if determination == "RESPONSIBLE":
        if solicitation["status"] == "EVALUATION":
            v.set_field(solicitation, "status", "AWARD_PENDING")
    else:
        services.recompute_apparent_low_bid(solicitation)

    return ("obj", review, serializers.review, 201)


@bp.get("/procurement/bids/<bid_id>/responsibility-reviews")
@v.endpoint(v.ALL_ROLES)
def list_responsibility_reviews(bid_id):
    limit, offset = v.pagination()
    bid = services.must("bids", bid_id)
    rows = services.reviews_of(bid)
    page, total = v.paginate(rows, limit, offset)
    return ("list", page, serializers.review, limit, offset, total)
