"""WarrantyClaim endpoints."""
from flask import Blueprint, request

import clock
import db
import errors
import middleware
import response
from routes.helpers import as_enum, as_number, as_string, body, require
from services import calc, cascade

bp = Blueprint("warranty", __name__)

CLAIM_TYPES = {"SAG_DEFECT", "WORKMANSHIP"}
SAG_THRESHOLD_INCHES = 1.5


def claim_view(c):
    return {
        "id": c["id"],
        "unit_id": c["unit_id"],
        "retailer_id": c["retailer_id"],
        "claim_type": c["claim_type"],
        "measured_sag_inches": c["measured_sag_inches"],
        "age_months": c["age_months"],
        "credit_variant": c["credit_variant"],
        "credit_cents": c["credit_cents"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def get_claim(claim_id):
    c = db.claims.get(claim_id)
    if c is None:
        errors.raise_err(errors.ERR_CLAIM_NOT_FOUND, "claim not found")
    return c


@bp.route("/warranty-claims", methods=["POST"])
def create_claim():
    user_id, role = middleware.require_roles(["Retailer"])
    data = body()
    unit_id = as_string(require(data, "unit_id"), "unit_id")
    retailer_id = as_string(require(data, "retailer_id"), "retailer_id")
    claim_type = as_enum(require(data, "claim_type"), "claim_type", CLAIM_TYPES)
    sag = as_number(require(data, "measured_sag_inches"), "measured_sag_inches")
    # body-FK existence (PRD section 2.8 tier 3: unit before retailer)
    unit = db.units.get(unit_id)
    if unit is None:
        errors.raise_err(errors.ERR_UNIT_NOT_FOUND, "unit not found")
    # NOTE: no body-supplied retailer existence check here. PRD section 2.8
    # tier 3 only extends to path ids and body-supplied unit references; a
    # retailer_id that does not name an existing retailer falls through to
    # the tier-10 mismatch/identity checks (422).
    # tier 5: unit must be DELIVERED
    if unit["status"] != "DELIVERED":
        errors.raise_err(errors.ERR_UNIT_NOT_DELIVERED, "unit must be DELIVERED")
    # tier 10: referential integrity
    if retailer_id != unit["retailer_id"]:
        errors.raise_err(
            errors.ERR_RETAILER_UNIT_MISMATCH,
            "retailer_id must equal the unit's retailer",
        )
    if role == "Retailer" and retailer_id != user_id:
        errors.raise_err(
            errors.ERR_RETAILER_IDENTITY_MISMATCH,
            "Retailer callers may only reference their own retailer_id",
        )
    if claim_type == "SAG_DEFECT" and calc.dec(sag) < calc.dec(SAG_THRESHOLD_INCHES):
        errors.raise_err(errors.ERR_SAG_BELOW_THRESHOLD, "sag below 1.5 inches")
    claim = {
        "id": db.new_id(),
        "unit_id": unit_id,
        "retailer_id": retailer_id,
        "claim_type": claim_type,
        "measured_sag_inches": sag,
        "age_months": None,
        "credit_variant": None,
        "credit_cents": None,
        "status": "FILED",
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
        "version": 1,
    }
    db.put(db.claims, claim)
    return response.success_object(claim_view(claim), 201)


@bp.route("/warranty-claims", methods=["GET"])
def list_claims():
    middleware.require_roles(middleware.ALL_ROLES)
    items = list(db.claims.values())
    for param in ("unit_id", "retailer_id", "status"):
        q = request.args.get(param)
        if q is not None:
            items = [c for c in items if c[param] == q]
    items.sort(key=lambda c: c["_seq"])
    return response.success_list([claim_view(c) for c in items])


@bp.route("/warranty-claims/<claimId>", methods=["GET"])
def get_one_claim(claimId):
    middleware.require_roles(middleware.ALL_ROLES)
    c = get_claim(claimId)
    return response.success_object(claim_view(c))


@bp.route("/warranty-claims/<claimId>/approve", methods=["POST"])
def approve_claim(claimId):
    middleware.require_roles(["PlantManager"])
    claim = get_claim(claimId)
    if claim["status"] != "FILED":
        errors.raise_err(errors.ERR_CLAIM_NOT_FILED, "claim must be FILED")
    unit = db.units[claim["unit_id"]]
    age_months, variant, credit = calc.warranty_credit(
        clock.iso_parse(unit["delivered_at"]),
        unit["purchase_price_cents"],
        clock.now(),
    )
    claim["age_months"] = age_months
    claim["credit_variant"] = variant
    claim["credit_cents"] = credit
    claim["status"] = "APPROVED"
    cascade.bump(claim)
    return response.success_object(claim_view(claim))


@bp.route("/warranty-claims/<claimId>/deny", methods=["POST"])
def deny_claim(claimId):
    middleware.require_roles(["PlantManager"])
    claim = get_claim(claimId)
    if claim["status"] != "FILED":
        errors.raise_err(errors.ERR_CLAIM_NOT_FILED, "claim must be FILED")
    claim["status"] = "DENIED"
    cascade.bump(claim)
    return response.success_object(claim_view(claim))


@bp.route("/warranty-claims/<claimId>/pay", methods=["POST"])
def pay_claim(claimId):
    middleware.require_roles(["PlantManager"])
    claim = get_claim(claimId)
    if claim["status"] != "APPROVED":
        errors.raise_err(errors.ERR_CLAIM_NOT_APPROVED, "claim must be APPROVED")
    retailer = db.retailers[claim["retailer_id"]]
    # tier 11: fiscal cap
    if retailer["credit_balance_cents"] + claim["credit_cents"] > retailer["credit_limit_cents"]:
        errors.raise_err(errors.ERR_CREDIT_LIMIT_EXCEEDED, "credit limit exceeded")
    cascade.post_credit_adjustment(
        retailer,
        claim["credit_cents"],
        "Warranty claim payout",
        "WARRANTY_PAYOUT",
        claim["id"],
    )
    claim["status"] = "PAID"
    cascade.bump(claim)
    return response.success_object(claim_view(claim))
