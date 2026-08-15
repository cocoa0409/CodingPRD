"""Temperature-abuse claims (PRD §3.9): replay engine, dual payout variants,
appeal loop."""

from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_APPEAL_WINDOW_CLOSED,
    ERR_CLAIM_NOT_ALLOWED,
    ERR_DUPLICATE_CLAIM,
    ERR_INSUFFICIENT_READINGS,
    ERR_INVALID_STATE,
)
from middleware import authenticate, check_ownership, ALL_ROLES
from response import success_obj, success_list
from services import (
    APPEAL_WINDOW_DAYS,
    claim_payouts,
    serialize,
    temperature_replay,
)
from util import (
    apply_filters,
    body_json,
    check_shape,
    exist_body_fks,
    paginate,
    pagination_params,
    parse_dt,
    path_entity,
)

bp = Blueprint("claims", __name__)

CLAIM_SPEC = {
    "claim_code": {"type": "string", "required": True},
    "shipment_id": {"type": "string", "required": True},
    "declared_value_cents": {"type": "integer", "min": 1, "required": True},
}

OPEN_CLAIM_STATUSES = {"SUBMITTED", "EVIDENCE_REVIEW", "APPEALED", "APPROVED"}


@bp.route("/temp-abuse-claims", methods=["POST"])
def create_claim():
    user_id, _role = authenticate({"CustomerRep"})
    body = body_json()
    exist_body_fks(body, {"shipment_id": ("shipments", "shipment")})
    check_shape(body, CLAIM_SPEC)
    shipment = db.get("shipments", body["shipment_id"])
    # Priority 7: the filer must be the shipment's customer.
    check_ownership(user_id, shipment["customer_id"], "shipment")
    # Priority 26: shipment must be DELIVERED or REJECTED.
    if shipment["status"] not in ("DELIVERED", "REJECTED"):
        raise ApiError(
            ERR_CLAIM_NOT_ALLOWED, 422, "shipment is not DELIVERED or REJECTED"
        )
    # Priority 27: at most one non-terminal claim per shipment.
    for other in db.all_of("claims"):
        if (
            other["shipment_id"] == shipment["id"]
            and other["status"] in OPEN_CLAIM_STATUSES
        ):
            raise ApiError(
                ERR_DUPLICATE_CLAIM, 409, "a non-terminal claim exists for the shipment"
            )
    claim = db.new_entity("claims", {
        "claim_code": body["claim_code"],
        "shipment_id": shipment["id"],
        "filed_by_customer_id": user_id,
        "declared_value_cents": body["declared_value_cents"],
        "status": "SUBMITTED",
        "abuse_minutes": None,
        "peak_temp_c": None,
        "heat_shock_events": None,
        "payout_standard_cents": None,
        "payout_carrier_cents": None,
        "payout_variant": None,
        "payout_cents": None,
        "decided_at": None,
        "paid_at": None,
    })
    return success_obj(serialize("claims", claim), 201)


@bp.route("/temp-abuse-claims", methods=["GET"])
def list_claims():
    authenticate(ALL_ROLES)
    items = apply_filters(
        db.all_of("claims"), ["shipment_id", "filed_by_customer_id", "status"]
    )
    limit, offset = pagination_params()
    page, total, has_more = paginate(items, limit, offset)
    return success_list([serialize("claims", e) for e in page],
                        limit, offset, total, has_more)


@bp.route("/temp-abuse-claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    authenticate(ALL_ROLES)
    claim = path_entity("claims", claim_id, "claim")
    return success_obj(serialize("claims", claim))


@bp.route("/temp-abuse-claims/<claim_id>/open-review", methods=["POST"])
def open_claim_review(claim_id):
    authenticate({"ClaimsAdjuster"})
    claim = path_entity("claims", claim_id, "claim")
    if claim["status"] not in ("SUBMITTED", "APPEALED"):
        raise ApiError(ERR_INVALID_STATE, 409, "claim is not SUBMITTED or APPEALED")
    shipment = db.get("shipments", claim["shipment_id"])
    # Priority 28: at least 2 temperature readings on the shipment.
    reading_count = sum(
        1 for r in db.all_of("readings") if r["shipment_id"] == shipment["id"]
    )
    if reading_count < 2:
        raise ApiError(
            ERR_INSUFFICIENT_READINGS, 422, "shipment has fewer than 2 readings"
        )
    abuse_minutes, peak_temp_c, heat_shock_events = temperature_replay(shipment)
    standard, carrier = claim_payouts(abuse_minutes, claim["declared_value_cents"])
    claim["abuse_minutes"] = abuse_minutes
    claim["peak_temp_c"] = peak_temp_c
    claim["heat_shock_events"] = heat_shock_events
    claim["payout_standard_cents"] = standard
    claim["payout_carrier_cents"] = carrier
    claim["status"] = "EVIDENCE_REVIEW"
    db.touch(claim)
    return success_obj(serialize("claims", claim))


@bp.route("/temp-abuse-claims/<claim_id>/approve", methods=["POST"])
def approve_claim(claim_id):
    authenticate({"ClaimsAdjuster"})
    claim = path_entity("claims", claim_id, "claim")
    if claim["status"] != "EVIDENCE_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "claim is not EVIDENCE_REVIEW")
    shipment = db.get("shipments", claim["shipment_id"])
    # Variant selection: carrier_liability picks the CARRIER payout.
    if shipment is not None and shipment.get("carrier_liability"):
        claim["payout_variant"] = "CARRIER"
        claim["payout_cents"] = claim["payout_carrier_cents"]
    else:
        claim["payout_variant"] = "STANDARD"
        claim["payout_cents"] = claim["payout_standard_cents"]
    claim["decided_at"] = db.fmt_ts(db.now())
    claim["status"] = "APPROVED"
    db.touch(claim)
    return success_obj(serialize("claims", claim))


@bp.route("/temp-abuse-claims/<claim_id>/deny", methods=["POST"])
def deny_claim(claim_id):
    authenticate({"ClaimsAdjuster"})
    claim = path_entity("claims", claim_id, "claim")
    if claim["status"] != "EVIDENCE_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "claim is not EVIDENCE_REVIEW")
    claim["decided_at"] = db.fmt_ts(db.now())
    claim["status"] = "DENIED"
    db.touch(claim)
    return success_obj(serialize("claims", claim))


@bp.route("/temp-abuse-claims/<claim_id>/pay", methods=["POST"])
def pay_claim(claim_id):
    authenticate({"ClaimsAdjuster"})
    claim = path_entity("claims", claim_id, "claim")
    if claim["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409, "claim is not APPROVED")
    claim["paid_at"] = db.fmt_ts(db.now())
    claim["status"] = "PAID"
    db.touch(claim)
    return success_obj(serialize("claims", claim))


@bp.route("/temp-abuse-claims/<claim_id>/appeal", methods=["POST"])
def appeal_claim(claim_id):
    user_id, _role = authenticate({"CustomerRep"})
    claim = path_entity("claims", claim_id, "claim")
    if claim["status"] != "DENIED":
        raise ApiError(ERR_INVALID_STATE, 409, "claim is not DENIED")
    check_ownership(user_id, claim["filed_by_customer_id"], "claim")
    # Priority 21: appeal window closes after decided_at + 14 days (inclusive).
    if db.now() > parse_dt(claim["decided_at"]) + timedelta(days=APPEAL_WINDOW_DAYS):
        raise ApiError(ERR_APPEAL_WINDOW_CLOSED, 422, "appeal window has closed")
    claim["status"] = "APPEALED"
    db.touch(claim)
    return success_obj(serialize("claims", claim))


@bp.route("/temp-abuse-claims/<claim_id>/withdraw", methods=["POST"])
def withdraw_claim(claim_id):
    user_id, _role = authenticate({"CustomerRep"})
    claim = path_entity("claims", claim_id, "claim")
    if claim["status"] not in ("SUBMITTED", "EVIDENCE_REVIEW"):
        raise ApiError(ERR_INVALID_STATE, 409, "claim is not SUBMITTED or EVIDENCE_REVIEW")
    check_ownership(user_id, claim["filed_by_customer_id"], "claim")
    claim["status"] = "WITHDRAWN"
    db.touch(claim)
    return success_obj(serialize("claims", claim))
