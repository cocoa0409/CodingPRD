"""Dispute endpoints: offers, accept-offer, ratify, arbitrate."""
from flask import Blueprint

import common
import db
import errors
import middleware
import response

bp = Blueprint("disputes", __name__)

READERS = ("LicensingAnalyst", "LegalCounsel", "Licensee")


def _pending_offer(dispute):
    pends = [o for o in dispute["offers"] if o["status"] == "PENDING"]
    return pends[0] if pends else None


def _resolve_finding_and_post(dispute, amount):
    """Shared side effects of ratify/arbitrate: finding RESOLVED, ledger postings."""
    f = db.findings[dispute["finding_id"]]
    f["status"] = "RESOLVED"
    common.touch(f)
    agr = db.agreements[dispute["agreement_id"]]
    licensee = db.licensees[dispute["licensee_id"]]
    licensee["outstanding_balance_cents"] += amount
    common.touch(licensee)
    agr["cumulative_recognized_revenue_cents"] += amount
    agr["undistributed_pool_cents"] += amount
    common.touch(agr)


@bp.get("/licensing/disputes")
def list_disputes():
    user_id, role = middleware.require_role(*READERS)
    args = common.request.args
    items = list(db.disputes.values())
    if role == "Licensee":
        items = [d for d in items if d["licensee_id"] == user_id]
    for param in ("finding_id", "agreement_id", "licensee_id", "status"):
        v = args.get(param)
        if v is not None:
            items = [d for d in items if d[param] == v]
    limit, offset = common.get_pagination()
    page, total = common.paginate(items, limit, offset)
    return response.success_list(page, limit, offset, total)


@bp.get("/licensing/disputes/<did>")
def get_dispute(did):
    user_id, role = middleware.require_role(*READERS)
    d = db.disputes.get(did)
    if d is None:
        raise errors.err_dispute_not_found()
    if role == "Licensee" and d["licensee_id"] != user_id:
        raise errors.err_not_resource_owner()
    return response.success_object(d)


@bp.post("/licensing/disputes/<did>/offers")
def make_offer(did):
    user_id, role = middleware.require_role("LegalCounsel", "Licensee")
    d = db.disputes.get(did)
    if d is None:
        raise errors.err_dispute_not_found()
    # Tier 4: ownership for licensee
    if role == "Licensee" and d["licensee_id"] != user_id:
        raise errors.err_not_resource_owner()
    body = common.get_body()
    common.validate_body(body, [
        ("amount_cents", "int", True),
        ("expected_dispute_version", "int", True),
    ])
    if body["amount_cents"] < 0:
        raise errors.err_validation("amount_cents must be >= 0")
    # Tier 8: state conformance
    if d["status"] not in ("OPEN", "NEGOTIATION", "COUNTERED"):
        raise errors.err_dispute_invalid_state(
            "Offers are only permitted from OPEN, NEGOTIATION, or COUNTERED")
    # OCC check
    if body["expected_dispute_version"] != d["version"]:
        raise errors.err_stale_version()

    # Supersede any pending offer
    pend = _pending_offer(d)
    if pend is not None:
        pend["status"] = "SUPERSEDED"

    offer = {
        "amount_cents": body["amount_cents"],
        "offered_by_role": role,
        "offered_by_user_id": user_id,
        "status": "PENDING",
        "created_at": common.wall_now_str(),
    }
    d["offers"].append(offer)
    # State transition: counsel offer -> NEGOTIATION; licensee offer -> COUNTERED
    d["status"] = "NEGOTIATION" if role == "LegalCounsel" else "COUNTERED"
    common.touch(d)
    return response.success_object(d, 201)


@bp.post("/licensing/disputes/<did>/accept-offer")
def accept_offer(did):
    user_id, role = middleware.require_role("LegalCounsel", "Licensee")
    d = db.disputes.get(did)
    if d is None:
        raise errors.err_dispute_not_found()
    body = common.get_body()
    if body:
        raise errors.err_validation("Undeclared fields in request body")
    # Tier 8: state + exactly one PENDING offer
    if d["status"] not in ("NEGOTIATION", "COUNTERED"):
        raise errors.err_dispute_invalid_state(
            "Offer acceptance requires NEGOTIATION or COUNTERED status")
    pends = [o for o in d["offers"] if o["status"] == "PENDING"]
    if len(pends) != 1:
        raise errors.err_dispute_invalid_state(
            "Exactly one PENDING offer is required")
    pend = pends[0]
    # Tier 10: counterparty acceptance only
    if pend["offered_by_role"] == role:
        raise errors.err_cannot_accept_own_offer()
    # Tier 4: ownership -- only the owning licensee may accept counsel's offer
    if role == "Licensee" and d["licensee_id"] != user_id:
        raise errors.err_not_resource_owner()

    pend["status"] = "ACCEPTED"
    d["settlement_amount_cents"] = pend["amount_cents"]
    d["status"] = "RATIFICATION_PENDING"
    common.touch(d)
    return response.success_object(d)


@bp.post("/licensing/disputes/<did>/ratify")
def ratify_dispute(did):
    user_id, _ = middleware.require_role("LegalCounsel")
    d = db.disputes.get(did)
    if d is None:
        raise errors.err_dispute_not_found()
    body = common.get_body()
    if body:
        raise errors.err_validation("Undeclared fields in request body")
    # Tier 8
    if d["status"] != "RATIFICATION_PENDING":
        raise errors.err_dispute_invalid_state(
            "Ratification requires RATIFICATION_PENDING status")
    # Tier 9: SoD vs audit opener
    f = db.findings[d["finding_id"]]
    audit = db.audits[f["audit_id"]]
    if user_id == audit["opened_by_user_id"]:
        raise errors.err_sod_conflict(
            "Ratifying counsel must differ from the audit opener")

    d["ratified_by_user_id"] = user_id
    d["status"] = "SETTLED"
    common.touch(d)
    _resolve_finding_and_post(d, d["settlement_amount_cents"])
    return response.success_object(d)


@bp.post("/licensing/disputes/<did>/arbitrate")
def arbitrate_dispute(did):
    user_id, _ = middleware.require_role("LegalCounsel")
    d = db.disputes.get(did)
    if d is None:
        raise errors.err_dispute_not_found()
    body = common.get_body()
    common.validate_body(body, [("awarded_amount_cents", "int", True)])
    if body["awarded_amount_cents"] < 0:
        raise errors.err_validation("awarded_amount_cents must be >= 0")
    # Tier 8
    if d["status"] not in ("NEGOTIATION", "COUNTERED"):
        raise errors.err_dispute_invalid_state(
            "Arbitration requires NEGOTIATION or COUNTERED status")

    pend = _pending_offer(d)
    if pend is not None:
        pend["status"] = "SUPERSEDED"
    d["awarded_amount_cents"] = body["awarded_amount_cents"]
    d["status"] = "ARBITRATED"
    common.touch(d)
    _resolve_finding_and_post(d, body["awarded_amount_cents"])
    return response.success_object(d)
