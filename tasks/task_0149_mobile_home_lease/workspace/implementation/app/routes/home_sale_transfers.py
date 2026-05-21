"""HomeSaleTransfer routes: open, approve, reject, close, get."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..errors import ApiError
from ..responses import success_response
from ..services.calculations import (
    buyer_has_disqualifying_eviction,
    recompute_violation_count_12mo,
)
from ..services.cascades import void_pending_notices_for_lease
from ..services.entities import (
    get_home_body_or_404,
    get_resident_body_or_404,
    get_transfer_or_404,
    init_common_fields,
    touch,
)
from ..services.serialization import serialize_transfer
from ..store import store
from ..validation import get_json_body, require_int, require_string


bp = Blueprint("home_sale_transfers", __name__)


@bp.route("/home-sale-transfers", methods=["POST"])
@require_auth("ParkManager", "Resident")
def open_transfer():
    body = get_json_body()
    home_id = require_string(body, "home_id")
    seller = require_string(body, "seller_resident_id")
    buyer = require_string(body, "buyer_resident_id")
    sale_price = require_int(body, "sale_price_cents", strict_positive=True)

    # Body-resource existence: home and both residents
    home = get_home_body_or_404(home_id)
    get_resident_body_or_404(seller)
    get_resident_body_or_404(buyer)

    with store.lock:
        t = init_common_fields({
            "home_id": home_id,
            "seller_resident_id": seller,
            "buyer_resident_id": buyer,
            "sale_price_cents": int(sale_price),
            "status": "PENDING_PARK_APPROVAL",
            "new_lease_id": None,
        })
        store.home_sale_transfers[t["id"]] = t

    return success_response(serialize_transfer(t), status=201)


@bp.route("/home-sale-transfers/<transfer_id>/approve", methods=["POST"])
@require_auth("ParkManager")
def approve_transfer(transfer_id: str):
    t = get_transfer_or_404(transfer_id)

    with store.lock:
        # State precondition
        if t["status"] != "PENDING_PARK_APPROVAL":
            raise ApiError("ERR_INVALID_STATE", "Transfer is not in PENDING_PARK_APPROVAL state.")
        home = store.homes.get(t["home_id"])
        if home is None:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", "Home missing.")
        lot = store.lots.get(home.get("lot_id") or "")
        if lot is None:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", "Lot missing for home.")
        # Priority 12: Lot must be RESIDENT_OWNED
        if lot["ownership_mode"] != "RESIDENT_OWNED":
            raise ApiError("ERR_HOME_NOT_RESIDENT_OWNED", "Home is not resident-owned.")
        # Seller must currently own the home
        if home.get("owner_resident_id") != t["seller_resident_id"]:
            raise ApiError("ERR_INVALID_STATE", "Seller is not the current owner of the home.")
        # Priority 9: buyer eligibility
        buyer = store.residents.get(t["buyer_resident_id"])
        if buyer is None:
            raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", "Buyer resident missing.")
        # Always recompute the buyer's rolling count before checking
        recompute_violation_count_12mo(buyer)
        if buyer_has_disqualifying_eviction(buyer):
            raise ApiError("ERR_BUYER_INELIGIBLE", "Buyer has a disqualifying eviction history.")
        touch(buyer)

        t["status"] = "APPROVED"
        touch(t)

    return success_response(serialize_transfer(t), status=200)


@bp.route("/home-sale-transfers/<transfer_id>/reject", methods=["POST"])
@require_auth("ParkManager")
def reject_transfer(transfer_id: str):
    t = get_transfer_or_404(transfer_id)
    with store.lock:
        if t["status"] != "PENDING_PARK_APPROVAL":
            raise ApiError("ERR_INVALID_STATE", "Transfer is not in PENDING_PARK_APPROVAL state.")
        t["status"] = "REJECTED"
        touch(t)
    return success_response(serialize_transfer(t), status=200)


@bp.route("/home-sale-transfers/<transfer_id>/close", methods=["POST"])
@require_auth("ParkManager")
def close_transfer(transfer_id: str):
    t = get_transfer_or_404(transfer_id)

    with store.lock:
        if t["status"] != "APPROVED":
            raise ApiError("ERR_INVALID_STATE", "Transfer is not in APPROVED state.")
        home = store.homes.get(t["home_id"])
        if home is None:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", "Home missing.")
        lot = store.lots.get(home.get("lot_id") or "")
        if lot is None:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", "Lot missing.")
        predecessor_id = lot.get("current_lease_id")
        if predecessor_id is None:
            raise ApiError("ERR_INVALID_STATE", "No active lease on the lot to assume.")
        predecessor = store.leases.get(predecessor_id)
        if predecessor is None:
            raise ApiError("ERR_INVALID_STATE", "Predecessor lease missing.")
        if predecessor["status"] not in ("CURRENT", "DELINQUENT"):
            raise ApiError("ERR_INVALID_STATE", "Predecessor lease must be CURRENT or DELINQUENT.")

        # Mint successor lease in CURRENT
        from ..services.entities import init_common_fields as _init
        successor = _init({
            "lot_id": lot["id"],
            "resident_id": t["buyer_resident_id"],
            "monthly_rent_cents": int(predecessor.get("monthly_rent_cents") or lot["base_rent_cents"]),
            "start_date": _now_iso(),
            "status": "CURRENT",
            "outstanding_balance_cents": 0,
            "predecessor_lease_id": predecessor["id"],
        })
        store.leases[successor["id"]] = successor

        # Predecessor lease: CURRENT/DELINQUENT -> ASSUMED
        predecessor["status"] = "ASSUMED"
        touch(predecessor)
        # Void any pending notices on the predecessor
        void_pending_notices_for_lease(predecessor["id"])

        # Lot.current_lease_id := successor.id
        lot["current_lease_id"] = successor["id"]
        touch(lot)
        # Home.owner_resident_id := buyer
        home["owner_resident_id"] = t["buyer_resident_id"]
        touch(home)
        # Transfer.new_lease_id := successor.id
        t["new_lease_id"] = successor["id"]
        t["status"] = "CLOSED"
        touch(t)

    return success_response(serialize_transfer(t), status=200)


@bp.route("/home-sale-transfers/<transfer_id>", methods=["GET"])
@require_auth("ParkManager", "PlatformAdmin", "Resident")
def get_transfer(transfer_id: str):
    t = get_transfer_or_404(transfer_id)
    return success_response(serialize_transfer(t), status=200)


def _now_iso() -> str:
    from ..clock import clock
    return clock.iso_now()


__all__ = ["bp"]
