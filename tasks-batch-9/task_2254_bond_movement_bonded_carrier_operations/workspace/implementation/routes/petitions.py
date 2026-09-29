"""Mitigation petitions (PRD 3.7)."""
from flask import Blueprint, request

from db import db, new_record, touch
from errors import ApiError
from middleware import ALL_ROLES, require
from response import ok, ok_list, read_pagination, window
from services import calc, domain
import validate as v

bp = Blueprint("petitions", __name__)

FACTOR_CODES = ("FIRST_VIOLATION", "CARGO_SECURED_INTACT", "PROMPT_ARRIVAL_REPORT",
                "CBP_ADMIN_DELAY", "EXTRAORDINARY_CIRCUMSTANCE")
DECISIONS = ("GRANT", "PARTIAL_GRANT", "DENY", "REQUEST_SUPPLEMENT")
LIVE_PETITIONS = ("SUBMITTED", "SUPPLEMENT_REQUESTED")


def _check_factors(raw):
    if not isinstance(raw, list) or not raw or len(raw) > 5:
        raise ApiError("ERR_MITIGATION_FACTOR_INVALID")
    seen = []
    for code in raw:
        if not isinstance(code, str) or code not in FACTOR_CODES or code in seen:
            raise ApiError("ERR_MITIGATION_FACTOR_INVALID")
        seen.append(code)
    return seen


def _prior_violation_count(claim):
    """Live-or-settled claims on OTHER movements of the carrier, last 365 days."""
    carrier = domain.claim_carrier(claim)
    if carrier is None:
        return 0
    floor = db.now - calc.days(365)
    count = 0
    for other in domain.claims_of_carrier(carrier["id"]):
        if other["movement_id"] == claim["movement_id"]:
            continue
        if other["status"] == "CANCELLED":
            continue
        if other["issued_at"] < floor or other["issued_at"] > db.now:
            continue
        count += 1
    return count


def _price(petition, claim):
    pct, net, fee, offer = calc.mitigation_offer(
        petition["mitigation_factors"], petition["round"],
        claim["assessed_amount"], petition["prior_violation_count"])
    petition["mitigation_pct"] = pct
    petition["net_before_fee"] = net
    petition["processing_fee"] = fee
    petition["offer_amount"] = offer


@bp.route("/in-bond/petitions", methods=["POST"])
def file_petition():
    user_id, _role = require("BondedCarrier")

    peeked = v.peek_body().get("claim_id")
    if isinstance(peeked, str):
        target = db.claims.get(peeked)
        if target is not None:
            carrier = domain.claim_carrier(target)
            if carrier is None or carrier["id"] != user_id:
                raise ApiError("ERR_NOT_MOVEMENT_CARRIER")

    body = v.get_body()
    claim_id = v.req_str(body, "claim_id")
    raw_factors = v.req_list(body, "mitigation_factors")
    narrative_reference = v.req_str(body, "narrative_reference")
    expected_version = v.req_int(body, "expected_claim_version", minimum=0)

    claim = db.claims.get(claim_id)
    if claim is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND")
    carrier = domain.claim_carrier(claim)
    if carrier is None or carrier["id"] != user_id:
        raise ApiError("ERR_NOT_MOVEMENT_CARRIER")

    if expected_version != claim["version"]:
        raise ApiError("ERR_STALE_CLAIM_VERSION")
    if claim["status"] != "ISSUED":
        raise ApiError("ERR_CLAIM_INVALID_STATE")
    factors = _check_factors(raw_factors)

    rec = new_record()
    rec.update({
        "claim_id": claim["id"],
        "mitigation_factors": factors,
        "narrative_reference": narrative_reference,
        "round": 1,
        "status": "SUBMITTED",
        "mitigation_pct": None,
        "net_before_fee": None,
        "processing_fee": None,
        "offer_amount": None,
        "prior_violation_count": _prior_violation_count(claim),
        "decided_by_user_id": None,
        "decision_reason_code": None,
        "filed_by_user_id": user_id,
    })
    _price(rec, claim)
    db.petitions[rec["id"]] = rec

    for other in domain.petitions_of(claim["id"]):
        if other["id"] == rec["id"] or other["status"] not in LIVE_PETITIONS:
            continue
        other["status"] = "SUPERSEDED"
        other["decision_reason_code"] = "SUPERSEDED_BY_NEWER_PETITION"
        touch(other)

    claim["status"] = "PETITIONED"
    touch(claim)
    return ok(domain.petition_json(rec), 201)


@bp.route("/in-bond/petitions/<petition_id>/supplement", methods=["POST"])
def supplement_petition(petition_id):
    user_id, _role = require("BondedCarrier")

    rec = db.petitions.get(petition_id)
    if rec is not None:
        claim = db.claims.get(rec["claim_id"])
        carrier = domain.claim_carrier(claim) if claim else None
        if carrier is None or carrier["id"] != user_id:
            raise ApiError("ERR_NOT_MOVEMENT_CARRIER")

    body = v.get_body()
    raw_factors = v.req_list(body, "mitigation_factors")
    narrative_reference = v.req_str(body, "narrative_reference")

    if rec is None:
        raise ApiError("ERR_PETITION_NOT_FOUND")
    if rec["status"] != "SUPPLEMENT_REQUESTED":
        raise ApiError("ERR_PETITION_INVALID_STATE")
    if rec["round"] >= calc.MAX_PETITION_ROUNDS:
        raise ApiError("ERR_PETITION_ROUND_LIMIT")
    factors = _check_factors(raw_factors)

    claim = db.claims.get(rec["claim_id"])
    rec["round"] += 1
    rec["mitigation_factors"] = factors
    rec["narrative_reference"] = narrative_reference
    rec["status"] = "SUBMITTED"
    _price(rec, claim)
    touch(rec)
    return ok(domain.petition_json(rec))


@bp.route("/in-bond/petitions/<petition_id>/decision", methods=["POST"])
def decide_petition(petition_id):
    user_id, _role = require("FPFOfficer")

    rec = db.petitions.get(petition_id)
    claim = db.claims.get(rec["claim_id"]) if rec is not None else None
    if claim is not None and user_id == claim["issued_by_officer_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    body = v.get_body()
    decision = v.req_enum(body, "decision", DECISIONS)
    decision_reason_code = v.req_str(body, "decision_reason_code")

    if rec is None:
        raise ApiError("ERR_PETITION_NOT_FOUND")
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_PETITION_INVALID_STATE")
    if claim is None or claim["status"] != "PETITIONED":
        raise ApiError("ERR_CLAIM_INVALID_STATE")
    if decision == "REQUEST_SUPPLEMENT" and rec["round"] >= calc.MAX_PETITION_ROUNDS:
        raise ApiError("ERR_PETITION_ROUND_LIMIT")

    rec["decided_by_user_id"] = user_id
    rec["decision_reason_code"] = decision_reason_code
    bond = db.bonds.get(claim["bond_id"])

    if decision == "REQUEST_SUPPLEMENT":
        rec["status"] = "SUPPLEMENT_REQUESTED"
        touch(rec)
        return ok(domain.petition_json(rec))

    if decision == "DENY":
        rec["status"] = "DENIED"
        touch(rec)
        claim["status"] = "ISSUED"
        touch(claim)
        return ok(domain.petition_json(rec))

    if decision == "GRANT":
        rec["status"] = "GRANTED"
        mitigated = calc.round2(rec["offer_amount"])
    else:
        rec["status"] = "PARTIALLY_GRANTED"
        mitigated = calc.partial_grant_amount(claim["assessed_amount"], rec["offer_amount"])
    touch(rec)

    claim["mitigated_amount"] = mitigated
    claim["status"] = "MITIGATED"
    touch(claim)
    domain.append_ledger(bond, claim["movement_id"], "MITIGATE",
                         -(calc.round2(claim["assessed_amount"] - mitigated)),
                         "PETITION_GRANTED", claim_id=claim["id"])
    return ok(domain.petition_json(rec))


@bp.route("/in-bond/ld-claims/<claim_id>/petitions", methods=["GET"])
def list_petitions(claim_id):
    require(*ALL_ROLES)
    limit, offset = read_pagination(request.args)
    if db.claims.get(claim_id) is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND")
    items = domain.petitions_of(claim_id)
    items.sort(key=lambda p: (p["round"], p["created_at"], p["_seq"]))
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    total = len(items)
    page = window(items, limit, offset)
    return ok_list([domain.petition_json(p) for p in page], limit, offset, total)
