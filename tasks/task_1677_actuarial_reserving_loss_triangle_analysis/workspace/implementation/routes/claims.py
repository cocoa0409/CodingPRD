"""Claim and ClaimTransaction endpoints."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_CLAIM_NOT_CLOSEABLE,
    ERR_CLAIM_OUTSIDE_CAT_WINDOW,
    ERR_CASE_OUTSTANDING_NEGATIVE,
    ERR_PAYMENT_REVERSAL_EXCEEDS_PAID,
    ERR_QUARTER_CLOSED,
)
from middleware import authorized
from response import success_object, success_list
from routes.helpers import new_common_record, new_event_record, touch, sorted_by_creation
from services.cascade import transaction_posted_staleness, catastrophe_assignment_staleness
from services.serializers import claim_view, claim_transaction_view
from util import parse_date, quarter_of_datetime_str
from validate import (
    get_body,
    parse_pagination,
    reject_server_managed,
    req_str,
    req_enum,
    req_date,
    req_datetime,
    req_int,
    opt_nullable_str,
    require_path_resource,
    require_body_fk,
)

bp = Blueprint("claims", __name__)

CLAIM_COMPUTED = [
    "status", "paid_to_date_cents", "case_outstanding_cents",
    "reported_incurred_cents", "is_large_loss", "is_segregated",
    "adequacy_ratio_development", "adequacy_ratio_benchmark",
]

TXN_COMPUTED = ["claim_id", "effective_quarter"]


def _refresh_claim_derived(claim, segment):
    claim["reported_incurred_cents"] = claim["paid_to_date_cents"] + claim["case_outstanding_cents"]
    claim["is_large_loss"] = claim["reported_incurred_cents"] >= segment["large_loss_threshold_cents"]
    claim["is_segregated"] = claim["is_large_loss"] or (claim.get("catastrophe_event_id") is not None)


@bp.post("/actuarial/claims")
def create_claim():
    authorized(["ClaimsExaminer"])
    body = get_body()
    reject_server_managed(body, CLAIM_COMPUTED)
    segment_id = req_str(body, "segment_id")
    claim_number = req_str(body, "claim_number")
    accident_date = req_date(body, "accident_date")
    report_date = req_date(body, "report_date")
    if parse_date(report_date) < parse_date(accident_date):
        raise_error(ERR_INVALID_REQUEST, "report_date must be >= accident_date")

    segment = require_body_fk("segments", segment_id, "segment_id")

    rec = new_common_record({
        "segment_id": segment_id,
        "claim_number": claim_number,
        "accident_date": accident_date,
        "report_date": report_date,
        "catastrophe_event_id": None,
        "status": "OPEN",
        "paid_to_date_cents": 0,
        "case_outstanding_cents": 0,
        "reported_incurred_cents": 0,
        "is_large_loss": False,
        "is_segregated": False,
    })
    db["claims"][rec["id"]] = rec
    return success_object(claim_view(rec), status=201)


@bp.get("/actuarial/claims/<cid>")
def get_claim(cid):
    authorized(["ClaimsExaminer", "ActuarialAnalyst", "PeerReviewer", "AppointedActuary"])
    rec = require_path_resource("claims", cid)
    return success_object(claim_view(rec))


@bp.get("/actuarial/claims")
def list_claims():
    authorized(["ClaimsExaminer", "ActuarialAnalyst", "PeerReviewer", "AppointedActuary"])
    limit, offset = parse_pagination()
    segment_id = request.args.get("segment_id")
    cat_id = request.args.get("catastrophe_event_id")
    status = request.args.get("status")
    if status is not None and status not in ("OPEN", "CLOSED", "REOPENED"):
        raise_error(ERR_INVALID_REQUEST, "invalid status filter")
    items = list(db["claims"].values())
    if segment_id is not None:
        items = [c for c in items if c["segment_id"] == segment_id]
    if cat_id is not None:
        items = [c for c in items if c.get("catastrophe_event_id") == cat_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sorted_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([claim_view(c) for c in page], total, limit, offset)


@bp.patch("/actuarial/claims/<cid>")
def patch_claim(cid):
    caller = authorized(["ClaimsExaminer"])
    body = get_body()
    reject_server_managed(body, CLAIM_COMPUTED)
    claim = require_path_resource("claims", cid)

    # Only field supported is catastrophe_event_id (nullable).
    # Reject any other unexpected field.
    allowed = {"catastrophe_event_id"}
    for k in body.keys():
        if k not in allowed:
            raise_error(ERR_INVALID_REQUEST, f"unsupported field for claim PATCH: {k}")

    if "catastrophe_event_id" not in body:
        # no-op; still bumps version per spec? PRD says PATCH triggers cascade because
        # layer membership changes. If the field is absent we treat as no-change but
        # still return the claim. To keep the cascade honest we only fire when the
        # field is present.
        return success_object(claim_view(claim))

    new_cat = opt_nullable_str(body, "catastrophe_event_id")
    if new_cat is not None:
        ev = db["catastrophe_events"].get(new_cat)
        # Cross-segment event reference is NOT_FOUND for this claim (PRD §2.8/§3.2).
        if ev is None or ev["segment_id"] != claim["segment_id"]:
            raise_error(ERR_NOT_FOUND, "catastrophe_event_id not found for this claim")
        acc = parse_date(claim["accident_date"])
        if not (parse_date(ev["start_date"]) <= acc <= parse_date(ev["end_date"])):
            raise_error(ERR_CLAIM_OUTSIDE_CAT_WINDOW,
                        "claim accident_date outside the catastrophe event's closed window")

    claim["catastrophe_event_id"] = new_cat
    segment = db["segments"][claim["segment_id"]]
    _refresh_claim_derived(claim, segment)
    touch(claim)
    # Cascade: assigning or clearing an event changes layer membership on every
    # triangle of the segment.
    catastrophe_assignment_staleness(claim["segment_id"])
    return success_object(claim_view(claim))


@bp.post("/actuarial/claims/<cid>/status")
def claim_status(cid):
    authorized(["ClaimsExaminer"])
    body = get_body()
    reject_server_managed(body, CLAIM_COMPUTED)
    claim = require_path_resource("claims", cid)
    target = req_enum(body, "target_status", ["CLOSED", "REOPENED"])

    if target == "CLOSED":
        if claim["status"] not in ("OPEN", "REOPENED"):
            raise_error(ERR_INVALID_STATE, "claim cannot be closed from its current status")
        if claim["case_outstanding_cents"] != 0:
            raise_error(ERR_CLAIM_NOT_CLOSEABLE,
                        "claim cannot close with non-zero case outstanding")
        claim["status"] = "CLOSED"
    elif target == "REOPENED":
        if claim["status"] != "CLOSED":
            raise_error(ERR_INVALID_STATE, "claim cannot be reopened from its current status")
        claim["status"] = "REOPENED"

    touch(claim)
    return success_object(claim_view(claim))


@bp.post("/actuarial/claims/<cid>/transactions")
def post_transaction(cid):
    authorized(["ClaimsExaminer"])
    body = get_body()
    reject_server_managed(body, TXN_COMPUTED)
    claim = require_path_resource("claims", cid)
    segment = db["segments"][claim["segment_id"]]

    txn_type = req_enum(body, "type", ["PAYMENT", "PAYMENT_REVERSAL", "CASE_RESERVE_SET"])
    transaction_date = req_datetime(body, "transaction_date")

    amount_cents = None
    case_value_cents = None
    if txn_type in ("PAYMENT", "PAYMENT_REVERSAL"):
        amount_cents = req_int(body, "amount_cents", positive=True)
    elif txn_type == "CASE_RESERVE_SET":
        # present + int-typed required; negativity is a tier-11 fiscal guard
        if "case_value_cents" not in body or body.get("case_value_cents") is None:
            raise_error(ERR_INVALID_REQUEST, "case_value_cents required for CASE_RESERVE_SET")
        v = body.get("case_value_cents")
        if isinstance(v, bool) or not isinstance(v, int):
            raise_error(ERR_INVALID_REQUEST, "case_value_cents must be an integer")
        case_value_cents = v

    effective_quarter = quarter_of_datetime_str(transaction_date)

    # Tier 10 temporal: effective_quarter > last_closed_quarter required
    lcq = segment.get("last_closed_quarter")
    if lcq is not None and effective_quarter <= lcq:
        raise_error(ERR_QUARTER_CLOSED,
                    "transaction effective_quarter is on or before the segment's last closed quarter")

    # Tier 11 fiscal guards
    if txn_type == "CASE_RESERVE_SET" and case_value_cents < 0:
        raise_error(ERR_CASE_OUTSTANDING_NEGATIVE, "case_value_cents must be >= 0")
    if txn_type == "PAYMENT_REVERSAL" and amount_cents > claim["paid_to_date_cents"]:
        raise_error(ERR_PAYMENT_REVERSAL_EXCEEDS_PAID,
                    "reversal amount exceeds paid_to_date_cents")

    # Apply
    if txn_type == "PAYMENT":
        claim["paid_to_date_cents"] += amount_cents
    elif txn_type == "PAYMENT_REVERSAL":
        claim["paid_to_date_cents"] -= amount_cents
    elif txn_type == "CASE_RESERVE_SET":
        claim["case_outstanding_cents"] = case_value_cents
    _refresh_claim_derived(claim, segment)
    touch(claim)

    rec = new_event_record({
        "claim_id": claim["id"],
        "type": txn_type,
        "transaction_date": transaction_date,
        "effective_quarter": effective_quarter,
        "amount_cents": amount_cents,
        "case_value_cents": case_value_cents,
    })
    db["claim_transactions"][rec["id"]] = rec

    # Cascade: transactions mark triangles with valuation_quarter >= effective_quarter stale.
    transaction_posted_staleness(claim["segment_id"], effective_quarter)

    return success_object(claim_transaction_view(rec), status=201)


@bp.get("/actuarial/claims/<cid>/transactions")
def list_transactions(cid):
    authorized(["ClaimsExaminer", "ActuarialAnalyst", "PeerReviewer", "AppointedActuary"])
    claim = require_path_resource("claims", cid)
    limit, offset = parse_pagination()
    items = sorted_by_creation([
        t for t in db["claim_transactions"].values() if t["claim_id"] == claim["id"]
    ])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([claim_transaction_view(t) for t in page], total, limit, offset)
