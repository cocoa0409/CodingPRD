"""RentalReimbursement routes (PRD §3.7)."""
from flask import Blueprint, request

import db
import serializers as S
from auth import authenticate, authorize
from errors import err
from helpers import (get_json_body, require_resource, require_fields,
                     require_int, parse_pagination, paginate)
from response import success, list_success
from util import parse_iso
from services import calc
from services.lookups import rental_coverage, has_verified_coverage

bp = Blueprint("rental_reimbursements", __name__)

READ_ROLES = {"ClaimsSupervisor", "ClaimsAdjuster"}


def _intervals_overlap(start_a, end_a, start_b, end_b):
    """Half-open overlap, adjacency ALLOWED:
    overlap iff start_A < end_B AND start_B < end_A."""
    return start_a < end_b and start_b < end_a


@bp.route("/rental-reimbursements", methods=["POST"])
def create_rental_reimbursement():
    principal = authenticate()
    authorize(principal, {"ClaimsAdjuster"})
    body = get_json_body()
    require_fields(body, ["claim_id", "rental_start_date", "rental_end_date",
                          "daily_rate_cents"])
    claim = require_resource(db.claims, body["claim_id"], "claim")
    start_dt = parse_iso(body["rental_start_date"])
    end_dt = parse_iso(body["rental_end_date"])
    daily_rate_cents = require_int(body, "daily_rate_cents")

    # Positive interval (priority 14).
    if not (end_dt > start_dt):
        raise err("ERR_INVALID_RENTAL_INTERVAL",
                  "rental_end_date must be strictly after rental_start_date")

    # Period overlap with existing PENDING/APPROVED rentals on the same claim
    # (priority 17, half-open, adjacency allowed).
    for r in db.rental_reimbursements.values():
        if r["claim_id"] != claim["id"]:
            continue
        if r["status"] not in ("PENDING", "APPROVED"):
            continue
        if _intervals_overlap(start_dt, end_dt,
                              r["rental_start_date"], r["rental_end_date"]):
            raise err("ERR_RENTAL_PERIOD_OVERLAP",
                      "rental period overlaps an existing rental on this claim")

    cov = rental_coverage(claim["policy_id"])
    rmax = cov["rental_max_days"] if cov else 0
    daily_cap = cov["rental_daily_cap_cents"] if cov else 0
    requested = calc.rental_requested_days(start_dt, end_dt)
    days, cents = calc.rental_reimbursement(
        requested, rmax, daily_cap, daily_rate_cents, claim["disposition"])

    rec = {
        "claim_id": claim["id"],
        "rental_start_date": start_dt,
        "rental_end_date": end_dt,
        "daily_rate_cents": daily_rate_cents,
        "reimbursable_days": days,
        "reimbursement_cents": cents,
        "status": "PENDING",
    }
    db.insert(db.rental_reimbursements, rec)
    return success(S.rental_reimbursement(rec), status=201)


@bp.route("/rental-reimbursements/<rid>", methods=["GET"])
def get_rental_reimbursement(rid):
    principal = authenticate()
    authorize(principal, READ_ROLES)
    rec = require_resource(db.rental_reimbursements, rid, "rental reimbursement")
    return success(S.rental_reimbursement(rec), status=200)


@bp.route("/rental-reimbursements", methods=["GET"])
def list_rental_reimbursements():
    principal = authenticate()
    authorize(principal, READ_ROLES)
    limit, offset = parse_pagination()
    claim_id = request.args.get("claim_id")
    status = request.args.get("status")
    rows = list(db.rental_reimbursements.values())
    if claim_id is not None:
        rows = [r for r in rows if r["claim_id"] == claim_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return list_success([S.rental_reimbursement(r) for r in page], limit, offset, total)


@bp.route("/rental-reimbursements/<rid>/approve", methods=["POST"])
def approve_rental_reimbursement(rid):
    principal = authenticate()
    authorize(principal, {"ClaimsAdjuster"})
    rental = require_resource(db.rental_reimbursements, rid, "rental reimbursement")
    if rental["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "rental is not PENDING")

    claim = db.claims.get(rental["claim_id"])
    cov = rental_coverage(claim["policy_id"]) if claim else None
    if claim is None or not has_verified_coverage(claim["id"]) or cov is None:
        raise err("ERR_INVALID_STATE",
                  "claim lacks verified coverage or a RENTAL coverage")
    if rental["reimbursement_cents"] <= 0:
        raise err("ERR_INVALID_STATE", "reimbursement_cents is not positive")

    rental["status"] = "APPROVED"
    db.touch(rental)

    disb = {
        "claim_id": claim["id"],
        "disbursement_type": "RENTAL",
        "amount_cents": rental["reimbursement_cents"],
        "source_entity_id": claim["id"],
        "status": "APPROVED",
    }
    db.insert(db.disbursements, disb)
    calc.refresh_claim_ledger(claim)  # touch_no_version on the claim
    return success(S.rental_reimbursement(rental), status=200)


@bp.route("/rental-reimbursements/<rid>/reject", methods=["POST"])
def reject_rental_reimbursement(rid):
    principal = authenticate()
    authorize(principal, {"ClaimsAdjuster"})
    rental = require_resource(db.rental_reimbursements, rid, "rental reimbursement")
    if rental["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "rental is not PENDING")

    claim = db.claims.get(rental["claim_id"])
    cov = rental_coverage(claim["policy_id"]) if claim else None
    # Reject precondition: reimbursement_cents == 0 OR no RENTAL coverage.
    if not (rental["reimbursement_cents"] == 0 or cov is None):
        raise err("ERR_INVALID_STATE",
                  "reject requires zero reimbursement or no RENTAL coverage")

    rental["status"] = "REJECTED"
    db.touch(rental)
    return success(S.rental_reimbursement(rental), status=200)
