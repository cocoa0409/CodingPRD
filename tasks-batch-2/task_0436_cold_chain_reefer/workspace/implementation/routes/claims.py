"""SpoilageClaim endpoints (PRD §3.8).

Lifecycle: FILED -> UNDER_REVIEW -> {APPROVED|DENIED}; FILED -> WITHDRAWN.
Filing snapshots claimed_value_cents (ELIGIBLE / pre-cap); approval applies the
carrier liability cap and sets per-lot spoilage_status.
"""

from flask import Blueprint, request

from constants import CLAIM_STATUSES
from db import store
from errors import err
from helpers import (
    get_claim_or_404,
    get_shipment_or_404,
    pagination_params,
    paginate,
)
from middleware import authenticate, require_role
from models import serialize, stamp_create, touch
from response import array_response, object_response
from services import eligible_claim_value_cents, set_lot_spoilage_statuses
from validators import as_string, get_body, require

bp = Blueprint("claims", __name__)

# Statuses that count as an open claim already occupying a shipment.
_OPEN_STATUSES = {"FILED", "UNDER_REVIEW", "APPROVED"}


@bp.route("/spoilage-claims", methods=["POST"])
def file_claim(sid=None):
    uid, role = authenticate()
    require_role(role, {"Shipper"})

    body = get_body(request)
    shipment_id = as_string(require(body, "shipment_id"), "shipment_id")

    # FK existence (priority 4)
    shipment = store.shipments.get(shipment_id)
    if shipment is None:
        raise err("ERR_FK_NOT_FOUND", "shipment_id does not resolve to a shipment")

    # eligibility (priority 16, ERR_CLAIM_NOT_ELIGIBLE)
    if shipment["status"] != "DELIVERED":
        raise err("ERR_CLAIM_NOT_ELIGIBLE", "Shipment is not DELIVERED")
    if shipment["load_integrity_posture"] not in ("AT_RISK", "COMPROMISED"):
        raise err("ERR_CLAIM_NOT_ELIGIBLE", "Shipment posture is not AT_RISK/COMPROMISED")
    for c in store.spoilage_claims.values():
        if c["shipment_id"] == shipment_id and c["status"] in _OPEN_STATUSES:
            raise err("ERR_CLAIM_NOT_ELIGIBLE", "An open claim already exists for this shipment")

    claimed = eligible_claim_value_cents(shipment)
    rec = {
        "shipment_id": shipment_id,
        "filed_by_user_id": uid,
        "status": "FILED",
        "claimed_value_cents": claimed,
        "approved_payout_cents": 0,
    }
    stamp_create(rec)
    store.spoilage_claims[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/spoilage-claims/<cid>", methods=["GET"])
def get_claim(cid):
    _uid, role = authenticate()
    require_role(role, {"Shipper", "Carrier", "ComplianceOfficer", "PlatformAdmin"})
    rec = get_claim_or_404(cid)
    return object_response(serialize(rec), 200)


@bp.route("/spoilage-claims", methods=["GET"])
def list_claims():
    _uid, role = authenticate()
    require_role(role, {"Shipper", "Carrier", "ComplianceOfficer", "PlatformAdmin"})
    limit, offset = pagination_params()

    shipment_id = request.args.get("shipment_id")
    status = request.args.get("status")
    if status is not None and status not in CLAIM_STATUSES:
        raise err("ERR_INVALID_REQUEST", "Invalid status filter")

    records = list(store.spoilage_claims.values())
    if shipment_id is not None:
        records = [r for r in records if r["shipment_id"] == shipment_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]

    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


@bp.route("/spoilage-claims/<cid>/review", methods=["POST"])
def review_claim(cid):
    _uid, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    rec = get_claim_or_404(cid)
    if rec["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Claim is not FILED")
    rec["status"] = "UNDER_REVIEW"
    touch(rec)
    return object_response(serialize(rec), 200)


@bp.route("/spoilage-claims/<cid>/approve", methods=["POST"])
def approve_claim(cid):
    _uid, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    rec = get_claim_or_404(cid)
    if rec["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Claim is not UNDER_REVIEW")

    shipment = store.shipments.get(rec["shipment_id"])
    if shipment is None or shipment["load_integrity_posture"] not in ("AT_RISK", "COMPROMISED"):
        raise err("ERR_INVALID_STATE", "Related shipment posture is not AT_RISK/COMPROMISED")

    carrier = store.carriers.get(shipment["carrier_id"])
    cap = carrier["liability_cap_cents"] if carrier else rec["claimed_value_cents"]
    rec["approved_payout_cents"] = min(rec["claimed_value_cents"], cap)

    # set per-lot spoilage_status per its compartment impairment
    set_lot_spoilage_statuses(shipment)

    rec["status"] = "APPROVED"
    touch(rec)
    return object_response(serialize(rec), 200)


@bp.route("/spoilage-claims/<cid>/deny", methods=["POST"])
def deny_claim(cid):
    _uid, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    rec = get_claim_or_404(cid)
    if rec["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Claim is not UNDER_REVIEW")
    rec["approved_payout_cents"] = 0
    rec["status"] = "DENIED"
    touch(rec)
    return object_response(serialize(rec), 200)


@bp.route("/spoilage-claims/<cid>/withdraw", methods=["POST"])
def withdraw_claim(cid):
    uid, role = authenticate()
    require_role(role, {"Shipper"})
    rec = get_claim_or_404(cid)
    if rec["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Claim is not FILED")
    # ownership: caller's X-User-ID must match filed_by_user_id
    if uid != rec["filed_by_user_id"]:
        raise err("ERR_FORBIDDEN_ROLE", "Caller did not file this claim")
    rec["status"] = "WITHDRAWN"
    touch(rec)
    return object_response(serialize(rec), 200)
