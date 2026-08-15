"""Routes: settlement offers — tender (OCC-guarded), accept, withdraw
(PRD §3.7, §2.9)."""

from flask import Blueprint, request

import db
import services as svc
from errors import (
    raise_err,
    ERR_INSUFFICIENT_PERMISSIONS, ERR_AUDIT_CASE_NOT_FOUND,
    ERR_OFFER_NOT_FOUND, ERR_STALE_VERSION, ERR_AUDIT_CASE_INVALID_STATE,
    ERR_OFFER_INVALID_STATE, ERR_SEGREGATION_OF_DUTIES_VIOLATION,
    ERR_OFFER_EXCEEDS_WORST_CASE_CAP,
)
from middleware import require_role, ALL_ROLES
from response import success_object, success_list, paginate
from validation import (
    body, req_string, req_int, req_positive_int, req_number, req_enum,
)

bp = Blueprint("offers", __name__)

OFFER_PARTIES = ("CUSTOMER", "VENDOR")


def _get_offer(oid):
    rec = db.offers.get(oid)
    if rec is None:
        raise_err(ERR_OFFER_NOT_FOUND, "SettlementOffer not found")
    return rec


def _tendered_offer_for_case(case_id):
    """The single TENDERED offer of a case (invariant: at most one)."""
    for o in db.offers.values():
        if o["audit_case_id"] == case_id and o["status"] == "TENDERED":
            return o
    return None


@bp.post("/sam/settlement-offers")
def create_offer():
    user_id, role = require_role(["ProcurementLead", "VendorAuditor"])
    data = body()
    # Priority-2 party match: when offered_by names a valid party, the role
    # must match it before any further request-shape checks.
    raw_party = data.get("offered_by")
    if raw_party in OFFER_PARTIES:
        if (raw_party == "CUSTOMER" and role != "ProcurementLead") or \
                (raw_party == "VENDOR" and role != "VendorAuditor"):
            raise_err(ERR_INSUFFICIENT_PERMISSIONS,
                      "offered_by party does not match the actor role")
    audit_case_id = req_string(data, "audit_case_id")
    offered_by = req_enum(data, "offered_by", OFFER_PARTIES)
    amount = req_positive_int(data, "amount_cents")
    expected_version = req_int(data, "expected_audit_case_version")
    discount = req_number(data, "future_license_discount_pct", required=False,
                          minimum=0, maximum=0.5, default=0)
    case = db.audit_cases.get(audit_case_id)
    if case is None:
        raise_err(ERR_AUDIT_CASE_NOT_FOUND, "audit_case_id does not exist")
    if expected_version != case["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_audit_case_version does not match the current "
                  "AuditCase version")
    if case["status"] != "SETTLEMENT_NEGOTIATION":
        raise_err(ERR_AUDIT_CASE_INVALID_STATE,
                  "Offers may only be tendered while the case is in "
                  "SETTLEMENT_NEGOTIATION")
    if offered_by == "CUSTOMER" and amount > case["worst_case_exposure_cents"]:
        raise_err(ERR_OFFER_EXCEEDS_WORST_CASE_CAP,
                  "CUSTOMER offer exceeds the case worst_case_exposure_cents "
                  "cap")
    prior = _tendered_offer_for_case(audit_case_id)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        svc.touch(prior)
    rec = svc.stamp_new({
        "audit_case_id": audit_case_id,
        "offered_by": offered_by,
        "tendered_by_user_id": user_id,
        "amount_cents": amount,
        "future_license_discount_pct": discount,
        "status": "TENDERED",
        "supersedes_offer_id": prior["id"] if prior is not None else None,
    })
    db.offers[rec["id"]] = rec
    case["last_tendered_offer_id"] = rec["id"]
    svc.touch(case)
    return success_object(rec, 201)


@bp.get("/sam/settlement-offers")
def list_offers():
    require_role(ALL_ROLES)
    records = list(db.offers.values())
    for param in ("audit_case_id", "supersedes_offer_id", "status"):
        v = request.args.get(param)
        if v is not None:
            records = [o for o in records if o[param] == v]
    page, total, limit, offset = paginate(records)
    return success_list(page, total, limit, offset)


@bp.get("/sam/settlement-offers/<oid>")
def get_offer(oid):
    require_role(ALL_ROLES)
    return success_object(_get_offer(oid))


@bp.post("/sam/settlement-offers/<oid>/accept")
def accept_offer(oid):
    user_id, role = require_role(["LegalCounsel", "VendorAuditor"])
    offer = _get_offer(oid)
    # Counterparty rule: VENDOR offers are accepted by LegalCounsel,
    # CUSTOMER offers by the VendorAuditor.
    if (offer["offered_by"] == "VENDOR" and role != "LegalCounsel") or \
            (offer["offered_by"] == "CUSTOMER" and role != "VendorAuditor"):
        raise_err(ERR_INSUFFICIENT_PERMISSIONS,
                  "Only the counterparty role may accept this offer")
    if offer["status"] != "TENDERED":
        raise_err(ERR_OFFER_INVALID_STATE,
                  "Only a TENDERED offer can be accepted")
    if user_id == offer["tendered_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES_VIOLATION,
                  "The acceptor must differ from the tenderer")
    offer["status"] = "ACCEPTED"
    svc.touch(offer)
    case = db.audit_cases[offer["audit_case_id"]]
    case["status"] = "CLOSED_SETTLED"
    case["settled_amount_cents"] = offer["amount_cents"]
    case["accepted_future_discount_pct"] = offer["future_license_discount_pct"]
    case["last_tendered_offer_id"] = None
    svc.touch(case)
    for it in db.scope_items.values():
        if it["audit_case_id"] == case["id"] and it["scope_status"] == "CONFIRMED":
            pos = svc.position_for_product(it["product_id"])
            if pos is not None and pos["position_basis"] != "AGREED":
                pos["position_basis"] = "AGREED"
                svc.touch(pos)
    return success_object(offer)


@bp.post("/sam/settlement-offers/<oid>/withdraw")
def withdraw_offer(oid):
    _user_id, role = require_role(["ProcurementLead", "VendorAuditor"])
    offer = _get_offer(oid)
    # Party match: the tendering party withdraws its own offer.
    if (offer["offered_by"] == "CUSTOMER" and role != "ProcurementLead") or \
            (offer["offered_by"] == "VENDOR" and role != "VendorAuditor"):
        raise_err(ERR_INSUFFICIENT_PERMISSIONS,
                  "Only the tendering party may withdraw this offer")
    if offer["status"] != "TENDERED":
        raise_err(ERR_OFFER_INVALID_STATE,
                  "Only a TENDERED offer can be withdrawn")
    offer["status"] = "WITHDRAWN"
    svc.touch(offer)
    case = db.audit_cases[offer["audit_case_id"]]
    if case["last_tendered_offer_id"] == offer["id"]:
        case["last_tendered_offer_id"] = None
    return success_object(offer)
