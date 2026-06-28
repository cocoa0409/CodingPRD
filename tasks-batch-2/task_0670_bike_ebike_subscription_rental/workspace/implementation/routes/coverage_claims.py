from flask import Blueprint, request

from db import db
from clock import parse_clock_field
from middleware import require_role
from response import object_response, array_response
from errors import (
    err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_PAYOUT_EXCEEDS_CAP,
)
from services.common import (
    stamp_create, touch, get_json_body, require_fields, require_enum,
    parse_pagination, paginate,
)
from services.lookups import get_rental, get_claim, check_rental_ownership
from services.reconcile import recompute_model_counts, recompute_active_rental_count
from services.serialize import coverage_claim_view
from services import calculations as calc

coverage_claims_bp = Blueprint("coverage_claims", __name__)

CLAIM_TYPES = {"THEFT", "DAMAGE"}
VIEW_ROLES = {"OpsAdmin", "Subscriber", "FleetManager"}


@coverage_claims_bp.route("/coverage-claims", methods=["POST"])
def file_claim():
    user_id, role = require_role({"Subscriber", "FleetManager"})
    body = get_json_body()
    require_fields(body, ["rental_id", "claim_type", "incident_clock", "claimed_amount_cents"])
    with db.lock:
        rental = get_rental(body["rental_id"])
        check_rental_ownership(rental, user_id, role)
        require_enum(body["claim_type"], CLAIM_TYPES, "claim_type")
        try:
            parse_clock_field(body["incident_clock"])
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "incident_clock must be an ISO-8601 instant.")
        amount = body["claimed_amount_cents"]
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
            raise err(ERR_INVALID_REQUEST, "claimed_amount_cents must be a non-negative integer.")

        claim = {
            "rental_id": rental["id"],
            "claim_type": body["claim_type"],
            "incident_clock": body["incident_clock"],
            "claimed_amount_cents": amount,
            "status": "FILED",
            "approved_payout_cents": 0,
        }
        stamp_create(claim)
        db.coverage_claims[claim["id"]] = claim
    return object_response(coverage_claim_view(claim), 201)


@coverage_claims_bp.route("/coverage-claims/<claim_id>", methods=["GET"])
def fetch_claim(claim_id):
    require_role(VIEW_ROLES)
    claim = get_claim(claim_id)
    return object_response(coverage_claim_view(claim), 200)


@coverage_claims_bp.route("/coverage-claims", methods=["GET"])
def list_claims():
    require_role(VIEW_ROLES)
    limit, offset = parse_pagination()
    records = list(db.coverage_claims.values())
    for field in ("rental_id", "status"):
        val = request.args.get(field)
        if val:
            records = [r for r in records if r.get(field) == val]
    page, total = paginate(records, limit, offset)
    return array_response([coverage_claim_view(r) for r in page], limit, offset, total)


@coverage_claims_bp.route("/coverage-claims/<claim_id>/review", methods=["POST"])
def review_claim(claim_id):
    require_role({"OpsAdmin"})
    with db.lock:
        claim = get_claim(claim_id)
        if claim["status"] != "FILED":
            raise err(ERR_INVALID_STATE, "Claim must be FILED to review.")
        claim["status"] = "UNDER_REVIEW"
        touch(claim)
    return object_response(coverage_claim_view(claim), 200)


@coverage_claims_bp.route("/coverage-claims/<claim_id>/approve", methods=["POST"])
def approve_claim(claim_id):
    require_role({"OpsAdmin"})
    body = get_json_body()
    with db.lock:
        claim = get_claim(claim_id)
        if claim["status"] != "UNDER_REVIEW":
            raise err(ERR_INVALID_STATE, "Claim must be UNDER_REVIEW to approve.")
        require_fields(body, ["approved_payout_cents"])
        payout = body["approved_payout_cents"]
        if not isinstance(payout, int) or isinstance(payout, bool) or payout < 0:
            raise err(ERR_INVALID_REQUEST, "approved_payout_cents must be a non-negative integer.")

        rental = db.rentals[claim["rental_id"]]
        model = db.bike_models[rental["model_id"]]
        max_payout = calc.coverage_max_payout(model, claim)
        # Reject if payout > claimed_amount or > coverage cap.
        if payout > claim["claimed_amount_cents"] or payout > max_payout:
            raise err(ERR_PAYOUT_EXCEEDS_CAP, "approved_payout_cents exceeds claim or cap.")

        claim["approved_payout_cents"] = payout
        claim["status"] = "APPROVED"
        touch(claim)

        account = db.accounts[rental["account_id"]]

        if claim["claim_type"] == "THEFT" and rental["billing_status"] == "BILLING_ACTIVE":
            # Theft write-off cascade.
            rental["billing_status"] = "WRITTEN_OFF"
            rental["lifecycle_status"] = "CANCELLED"
            touch(rental)
            bike = db.bikes.get(rental["bike_id"])
            if bike is not None:
                bike["bike_status"] = "RETIRED"
                bike["current_rental_id"] = None
                touch(bike)
                recompute_model_counts(bike["model_id"])
            account["wallet_credit_cents"] += payout
            touch(account)
            recompute_active_rental_count(rental["account_id"])
        else:
            # DAMAGE (or THEFT not BILLING_ACTIVE): credit payout to wallet only.
            account["wallet_credit_cents"] += payout
            touch(account)

    return object_response(coverage_claim_view(claim), 200)


@coverage_claims_bp.route("/coverage-claims/<claim_id>/deny", methods=["POST"])
def deny_claim(claim_id):
    require_role({"OpsAdmin"})
    with db.lock:
        claim = get_claim(claim_id)
        if claim["status"] != "UNDER_REVIEW":
            raise err(ERR_INVALID_STATE, "Claim must be UNDER_REVIEW to deny.")
        claim["approved_payout_cents"] = 0
        claim["status"] = "DENIED"
        touch(claim)
    return object_response(coverage_claim_view(claim), 200)


@coverage_claims_bp.route("/coverage-claims/<claim_id>/close", methods=["POST"])
def close_claim(claim_id):
    require_role({"OpsAdmin"})
    with db.lock:
        claim = get_claim(claim_id)
        if claim["status"] not in ("APPROVED", "DENIED"):
            raise err(ERR_INVALID_STATE, "Claim must be APPROVED or DENIED to close.")
        claim["status"] = "CLOSED"
        touch(claim)
    return object_response(coverage_claim_view(claim), 200)
