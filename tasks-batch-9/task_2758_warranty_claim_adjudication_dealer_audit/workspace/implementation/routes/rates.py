"""Labor rate and parts markup petitions (PRD 3.2)."""

from flask import Blueprint

import db
import response
import util
from errors import ApiError
from middleware import (
    ADJUDICATION_MANAGER,
    AUDIT_MANAGER,
    DEALER_WARRANTY_ADMIN,
    WARRANTY_ADMIN,
    auth,
    fetch,
)
from routes.common import apply_filters, resolve_fk, str_filter, two_decimals
from services import calc

bp = Blueprint("rates", __name__)


def _profile_of(record):
    return db.state_law_profiles[record["state_law_profile_id"]]


@bp.post("/warranty/labor-rate-requests")
def create_labor_rate_request():
    actor = auth(DEALER_WARRANTY_ADMIN)
    data = util.body()
    dealer = resolve_fk(data, "dealer_id", db.dealers, "ERR_DEALER_NOT_FOUND")
    # ---- body shape ----
    dealer_id = util.get_str(data, "dealer_id")
    requested_labor_rate_cents = util.get_int(data, "requested_labor_rate_cents", minimum=1)
    requested_parts_markup_pct = two_decimals(
        util.get_dec(data, "requested_parts_markup_pct", minimum=0, maximum=1), "requested_parts_markup_pct"
    )
    sample_repair_order_count = util.get_int(data, "sample_repair_order_count", required=False, minimum=0)
    sample_median_rate_cents = util.get_int(data, "sample_median_rate_cents", required=False, minimum=0)
    effective_date = util.get_date(data, "effective_date")
    expected_dealer_version = util.get_int(data, "expected_dealer_version")
    if dealer is None:
        dealer = db.dealers.get(dealer_id)
        if dealer is None:
            raise ApiError("ERR_DEALER_NOT_FOUND")
    # ---- version pinning ----
    if expected_dealer_version != dealer["version"]:
        raise ApiError("ERR_STALE_DEALER_VERSION", "The dealer has been modified since it was read.")
    # ---- dealer posture ----
    if dealer["status"] == "SUSPENDED":
        raise ApiError("ERR_DEALER_SUSPENDED", "A suspended dealer may not petition for new terms.")
    profile = _profile_of(dealer)
    # ---- retail-sample sufficiency, before the ceiling that consumes the median ----
    if profile["labor_rate_method"] == "RETAIL_SAMPLE":
        cited = sample_repair_order_count or 0
        if cited < profile["min_sample_repair_orders"] or sample_median_rate_cents is None:
            raise ApiError(
                "ERR_INSUFFICIENT_RATE_SAMPLE",
                "The retail sample must cite at least %d repair orders and a median rate."
                % profile["min_sample_repair_orders"],
            )
    ceiling = calc.labor_rate_statutory_ceiling(profile, dealer, sample_median_rate_cents or 0)
    if requested_labor_rate_cents > ceiling:
        raise ApiError(
            "ERR_LABOR_RATE_ABOVE_STATUTORY_CEILING",
            "Requested rate %d exceeds the statutory ceiling of %d cents." % (requested_labor_rate_cents, ceiling),
        )
    if requested_parts_markup_pct > profile["markup_cap_pct"]:
        raise ApiError(
            "ERR_MARKUP_ABOVE_STATE_CAP",
            "Requested markup exceeds the statutory cap of %s." % profile["markup_cap_pct"],
        )
    # ---- supersede any earlier SUBMITTED petition of this dealer ----
    for other in db.ordered(db.labor_rate_requests):
        if other["dealer_id"] == dealer["id"] and other["status"] == "SUBMITTED":
            other["status"] = "WITHDRAWN"
            db.touch(other)
    record = db.new_record(
        db.labor_rate_requests,
        dealer_id=dealer["id"],
        state_law_profile_id=dealer["state_law_profile_id"],
        requested_labor_rate_cents=requested_labor_rate_cents,
        requested_parts_markup_pct=requested_parts_markup_pct,
        sample_repair_order_count=sample_repair_order_count,
        sample_median_rate_cents=sample_median_rate_cents,
        effective_date=effective_date.isoformat(),
        statutory_ceiling_cents=ceiling,
        submitted_by_user_id=actor.user_id,
        status="SUBMITTED",
        approved_labor_rate_cents=None,
        approved_parts_markup_pct=None,
        deemed_approved=False,
        denial_reason=None,
    )
    db.touch(dealer)
    return response.created(record)


@bp.get("/warranty/labor-rate-requests/<request_id>")
def read_labor_rate_request(request_id):
    auth(WARRANTY_ADMIN, ADJUDICATION_MANAGER, AUDIT_MANAGER, DEALER_WARRANTY_ADMIN)
    record = fetch(db.labor_rate_requests, request_id, "ERR_LABOR_RATE_REQUEST_NOT_FOUND")
    return response.ok(record)


@bp.get("/warranty/labor-rate-requests")
def list_labor_rate_requests():
    auth(WARRANTY_ADMIN, ADJUDICATION_MANAGER, AUDIT_MANAGER)
    limit, offset = util.pagination()
    rows = db.ordered(db.labor_rate_requests)
    rows = apply_filters(
        rows,
        [
            (str_filter("dealer_id"), "dealer_id"),
            (str_filter("state_law_profile_id"), "state_law_profile_id"),
            (str_filter("status"), "status"),
            (util.bool_filter("deemed_approved"), "deemed_approved"),
        ],
    )
    page, total = util.paginate(rows, limit, offset)
    return response.listing(page, limit, offset, total)


@bp.post("/warranty/labor-rate-requests/<request_id>/review")
def review_labor_rate_request(request_id):
    auth(WARRANTY_ADMIN)
    record = fetch(db.labor_rate_requests, request_id, "ERR_LABOR_RATE_REQUEST_NOT_FOUND")
    data = util.body()
    action = util.get_enum(data, "action", ("START_REVIEW", "RETURN_FOR_INFO"))
    util.get_str(data, "note", required=False)
    if action == "START_REVIEW":
        if record["status"] != "SUBMITTED":
            raise ApiError("ERR_LABOR_RATE_REQUEST_INVALID_STATE", "Only a SUBMITTED request can enter review.")
        record["status"] = "UNDER_REVIEW"
    else:
        if record["status"] != "UNDER_REVIEW":
            raise ApiError("ERR_LABOR_RATE_REQUEST_INVALID_STATE", "Only an UNDER_REVIEW request can be returned.")
        record["status"] = "SUBMITTED"
    db.touch(record)
    return response.ok(record)


def _approve_dealer_terms(dealer, rate_cents, markup_pct, effective_date):
    dealer["approved_labor_rate_cents"] = rate_cents
    dealer["approved_parts_markup_pct"] = markup_pct
    dealer["labor_rate_effective_date"] = effective_date
    db.touch(dealer)


@bp.post("/warranty/labor-rate-requests/<request_id>/decision")
def decide_labor_rate_request(request_id):
    actor = auth(ADJUDICATION_MANAGER)
    record = fetch(db.labor_rate_requests, request_id, "ERR_LABOR_RATE_REQUEST_NOT_FOUND")
    if actor.user_id == record["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "The submitter of a petition may not decide it.")
    data = util.body()
    action = util.get_enum(data, "action", ("APPROVE", "DENY"))
    profile = _profile_of(record)
    if action == "APPROVE":
        approved_rate = util.get_int(data, "approved_labor_rate_cents", minimum=1)
        approved_markup = two_decimals(
            util.get_dec(data, "approved_parts_markup_pct", minimum=0, maximum=1), "approved_parts_markup_pct"
        )
    else:
        denial_reason = util.get_str(data, "denial_reason")
    if record["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        raise ApiError("ERR_LABOR_RATE_REQUEST_INVALID_STATE", "This petition is no longer open for a decision.")
    if action == "APPROVE":
        if approved_rate > record["statutory_ceiling_cents"]:
            raise ApiError(
                "ERR_LABOR_RATE_ABOVE_STATUTORY_CEILING",
                "Granted rate exceeds the pinned statutory ceiling of %d cents." % record["statutory_ceiling_cents"],
            )
        if approved_markup > profile["markup_cap_pct"]:
            raise ApiError("ERR_MARKUP_ABOVE_STATE_CAP", "Granted markup exceeds the statutory cap.")
        record["status"] = "APPROVED"
        record["approved_labor_rate_cents"] = approved_rate
        record["approved_parts_markup_pct"] = approved_markup
        db.touch(record)
        _approve_dealer_terms(db.dealers[record["dealer_id"]], approved_rate, approved_markup, record["effective_date"])
    else:
        record["status"] = "DENIED"
        record["denial_reason"] = denial_reason
        db.touch(record)
    return response.ok(record)


@bp.post("/warranty/labor-rate-requests/deemed-approval-run")
def deemed_approval_run():
    auth(WARRANTY_ADMIN)
    clock = db.now()
    promoted = []
    for record in db.ordered(db.labor_rate_requests):
        if record["status"] != "SUBMITTED":
            continue
        profile = _profile_of(record)
        if clock < db.add_days(record["_created_dt"], profile["deemed_approved_days"]):
            continue
        record["status"] = "APPROVED"
        record["deemed_approved"] = True
        record["approved_labor_rate_cents"] = record["requested_labor_rate_cents"]
        record["approved_parts_markup_pct"] = record["requested_parts_markup_pct"]
        db.touch(record)
        _approve_dealer_terms(
            db.dealers[record["dealer_id"]],
            record["approved_labor_rate_cents"],
            record["approved_parts_markup_pct"],
            record["effective_date"],
        )
        promoted.append(record["id"])
    return response.raw({"promoted_count": len(promoted), "promoted_request_ids": promoted})
