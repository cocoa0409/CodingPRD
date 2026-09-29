"""Liquidated damages claims and their disposition (PRD 3.7)."""
from decimal import Decimal

from flask import Blueprint, request

from db import db, new_record, touch
from errors import ApiError
from middleware import ALL_ROLES, require
from response import ok, ok_list, read_pagination, window
from services import calc, domain
import validate as v

bp = Blueprint("claims", __name__)

CLAIM_TYPES = ("LATE_ARRIVAL", "NON_ARRIVAL", "SEAL_VIOLATION",
               "UNAUTHORIZED_DIVERSION", "NO_PROOF_OF_EXPORT")
ACTIONS = ("PAY", "CANCEL")


def _witness(movement, claim_type):
    """Does the movement actually exhibit the violation claimed?"""
    if claim_type == "LATE_ARRIVAL":
        arrived = movement["arrival_reported_at"]
        return arrived is not None and arrived > movement["transit_deadline_utc"]
    if claim_type == "NON_ARRIVAL":
        return (movement["transit_status"] == "OVERDUE"
                and movement["arrival_reported_at"] is None)
    if claim_type == "NO_PROOF_OF_EXPORT":
        pending = any(r["report_type"] == "EXPORT" and r["status"] == "PENDING_PROOF"
                      for r in domain.reports_of(movement["id"]))
        return pending and db.now > movement["transit_deadline_utc"]
    if claim_type == "SEAL_VIOLATION":
        return any(e["event_type"] == "BROKEN_UNAUTHORIZED"
                   for e in domain.seal_events_of(movement["id"]))
    if claim_type == "UNAUTHORIZED_DIVERSION":
        if not movement["diversion_flag"]:
            return False
        for amendment in domain.amendments_of(movement["id"]):
            if amendment["amendment_type"] == "DIVERSION" and amendment["status"] == "APPROVED":
                return False
        return True
    return False


@bp.route("/in-bond/ld-claims", methods=["POST"])
def issue_claim():
    user_id, _role = require("CBPOfficer")
    body = v.get_body()
    movement_id = v.req_str(body, "movement_id")
    claim_type = v.req_enum(body, "claim_type", CLAIM_TYPES)
    v.opt_str(body, "reason_code")

    movement = db.movements.get(movement_id)
    if movement is None:
        raise ApiError("ERR_MOVEMENT_NOT_FOUND")

    for existing in domain.rows(db.claims):
        if (existing["movement_id"] == movement["id"]
                and existing["claim_type"] == claim_type
                and existing["status"] in calc.LIVE_CLAIM_STATUSES):
            raise ApiError("ERR_DUPLICATE_CLAIM")
    if not _witness(movement, claim_type):
        raise ApiError("ERR_NO_VIOLATION_TO_CLAIM")

    bond = db.bonds.get(movement["bond_id"])
    reference = movement["arrival_reported_at"] if claim_type == "LATE_ARRIVAL" else db.now
    overdue, assessed = calc.ld_assessment(
        claim_type, movement["transit_deadline_utc"], reference,
        movement["cargo_value"], bond["limit_amount"] if bond else Decimal("0.00"))

    rec = new_record()
    rec.update({
        "movement_id": movement["id"],
        "bond_id": movement["bond_id"],
        "claim_type": claim_type,
        "overdue_days_at_issue": overdue,
        "assessed_amount": assessed,
        "mitigated_amount": None,
        "paid_amount": None,
        "status": "ISSUED",
        "issued_by_officer_id": user_id,
        "issued_at": db.now,
        "sanction_points_applied": calc.round1(calc.POINTS[claim_type]),
        "cancellation_reason": None,
    })
    db.claims[rec["id"]] = rec

    domain.append_ledger(bond, movement["id"], "INCREASE_LD", assessed,
                         "CLAIM_ISSUED", claim_id=rec["id"])
    domain.recompute_sanctions(db.carriers.get(movement["carrier_id"]))
    return ok(domain.claim_json(rec), 201)


@bp.route("/in-bond/ld-claims/<claim_id>", methods=["GET"])
def read_claim(claim_id):
    require(*ALL_ROLES)
    rec = db.claims.get(claim_id)
    if rec is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND")
    return ok(domain.claim_json(rec))


@bp.route("/in-bond/ld-claims", methods=["GET"])
def list_claims():
    require(*ALL_ROLES)
    limit, offset = read_pagination(request.args)
    items = domain.rows(db.claims)
    for key in ("movement_id", "bond_id", "claim_type", "status"):
        value = request.args.get(key)
        if value is not None and value != "":
            items = [c for c in items if c[key] == value]
    total = len(items)
    page = window(items, limit, offset)
    return ok_list([domain.claim_json(c) for c in page], limit, offset, total)


@bp.route("/in-bond/ld-claims/<claim_id>/disposition", methods=["POST"])
def dispose_claim(claim_id):
    user_id, role = require("BondedCarrier", "FPFOfficer")

    rec = db.claims.get(claim_id)
    action = v.peek_body().get("action")
    if action == "PAY" and role != "BondedCarrier":
        raise ApiError("ERR_UNAUTHORIZED")
    if action == "CANCEL" and role != "FPFOfficer":
        raise ApiError("ERR_UNAUTHORIZED")

    # Band 3 then band 4.
    if rec is not None and role == "BondedCarrier":
        carrier = domain.claim_carrier(rec)
        if carrier is None or carrier["id"] != user_id:
            raise ApiError("ERR_NOT_MOVEMENT_CARRIER")
    if rec is not None and user_id == rec["issued_by_officer_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    body = v.get_body()
    action = v.req_enum(body, "action", ACTIONS)
    paid_amount = v.opt_money(body, "paid_amount")
    reason_code = v.opt_str(body, "reason_code")
    if action == "PAY" and paid_amount is None:
        raise ApiError("ERR_INVALID_REQUEST")

    if rec is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND")

    if action == "PAY":
        if rec["status"] not in ("ISSUED", "MITIGATED"):
            raise ApiError("ERR_CLAIM_INVALID_STATE")
    else:
        if rec["status"] not in ("ISSUED", "PETITIONED", "MITIGATED"):
            raise ApiError("ERR_CLAIM_INVALID_STATE")

    outstanding = (rec["mitigated_amount"] if rec["mitigated_amount"] is not None
                   else rec["assessed_amount"])
    bond = db.bonds.get(rec["bond_id"])

    if action == "PAY":
        owed = (rec["mitigated_amount"] if rec["status"] == "MITIGATED"
                else rec["assessed_amount"])
        if calc.round2(paid_amount) != calc.round2(owed):
            raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH")
        rec["paid_amount"] = calc.round2(owed)
        rec["status"] = "PAID"
        touch(rec)
        domain.append_ledger(bond, rec["movement_id"], "RELEASE_LD", -outstanding,
                             "CLAIM_PAID", claim_id=rec["id"])
        return ok(domain.claim_json(rec))

    rec["status"] = "CANCELLED"
    rec["cancellation_reason"] = reason_code
    touch(rec)
    domain.append_ledger(bond, rec["movement_id"], "RELEASE_LD", -outstanding,
                         "CLAIM_CANCELLED", claim_id=rec["id"])
    domain.recompute_sanctions(domain.claim_carrier(rec))
    for petition in domain.petitions_of(rec["id"]):
        if petition["status"] in ("SUBMITTED", "SUPPLEMENT_REQUESTED"):
            petition["status"] = "SUPERSEDED"
            petition["decision_reason_code"] = "CLAIM_CANCELLED"
            touch(petition)
    return ok(domain.claim_json(rec))
