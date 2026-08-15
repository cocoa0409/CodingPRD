"""Routes: quota transfers (lease negotiation between vessels)."""

from flask import Blueprint, request

from errors import ApiError
import store
from common import (
    auth,
    body,
    f_enum,
    f_int,
    f_str,
    find_holding,
    get_transfer,
    get_vessel,
    list_response,
    make_entity,
    not_owner,
    ok_object,
    pub,
    require_roles,
    touch,
    vessel_has_issued_permit,
)
import domain

bp = Blueprint("transfers", __name__)

OWNER = ["VesselOwner"]
CLERK = ["SettlementClerk"]
OPEN_STATUSES = ("PROPOSED", "COUNTERED")


def _caller_side(transfer, uid):
    """Return 'FROM_VESSEL' / 'TO_VESSEL' / None for the caller."""
    if uid == transfer["from_vessel_id"]:
        return "FROM_VESSEL"
    if uid == transfer["to_vessel_id"]:
        return "TO_VESSEL"
    return None


def _require_party(transfer, uid):
    side = _caller_side(transfer, uid)
    if side is None:
        not_owner("X-User-ID must be one of the two vessels on the transfer")
    return side


@bp.route("/quota-transfers", methods=["POST"])
def create_transfer():
    uid, role = auth()
    require_roles(role, OWNER)
    payload = body()
    from_vessel_id = f_str(payload, "from_vessel_id")
    to_vessel_id = f_str(payload, "to_vessel_id")
    if uid != from_vessel_id:
        not_owner("from_vessel_id must equal the caller's X-User-ID")
    from_vessel = get_vessel(from_vessel_id)
    to_vessel = get_vessel(to_vessel_id)
    fishery = f_enum(payload, "fishery_code", domain.FISHERY_CODES)
    season_year = f_int(payload, "season_year")
    # Tier 8 cross-entity link state.
    if from_vessel["status"] != "ACTIVE" or to_vessel["status"] != "ACTIVE":
        raise ApiError(409, "ERR_VESSEL_NOT_ACTIVE", "both vessels must be ACTIVE")
    if not vessel_has_issued_permit(from_vessel_id, fishery) or not vessel_has_issued_permit(
        to_vessel_id, fishery
    ):
        raise ApiError(
            409, "ERR_PERMIT_NOT_ACTIVE", "both vessels must hold an ISSUED permit"
        )
    from_holding = find_holding(from_vessel_id, fishery, season_year)
    to_holding = find_holding(to_vessel_id, fishery, season_year)
    if from_holding is None or to_holding is None:
        raise ApiError(
            404,
            "ERR_QUOTA_HOLDING_NOT_FOUND",
            "both vessels must hold quota for the fishery and season year",
        )
    # Tier 9 shape.
    pounds = f_int(payload, "pounds")
    price = f_int(payload, "price_per_lb_cents")
    if from_vessel_id == to_vessel_id:
        raise ApiError(422, "ERR_SELF_TRANSFER", "from_vessel_id == to_vessel_id")
    if pounds <= 0:
        raise ApiError(400, "ERR_INVALID_REQUEST", "pounds must be > 0")
    if price < 0:
        raise ApiError(400, "ERR_INVALID_REQUEST", "price_per_lb_cents must be >= 0")
    # Tier 10 fiscal gate.
    if domain.availability(from_holding)["available_conservative_pounds"] < pounds:
        raise ApiError(
            402, "ERR_QUOTA_EXCEEDED", "pounds exceed available_conservative_pounds"
        )
    transfer = make_entity(
        {
            "from_vessel_id": from_vessel_id,
            "to_vessel_id": to_vessel_id,
            "fishery_code": fishery,
            "season_year": season_year,
            "pounds": pounds,
            "price_per_lb_cents": price,
            "round_number": 1,
            "last_offered_by": "FROM_VESSEL",
            "transfer_fee_cents": None,
            "status": "PROPOSED",
        }
    )
    store.db.transfers[transfer["id"]] = transfer
    return ok_object(pub(transfer), 201)


@bp.route("/quota-transfers", methods=["GET"])
def list_transfers():
    auth()
    return list_response(
        store.db.transfers.values(),
        [
            ("from_vessel_id", request.args.get("from_vessel_id")),
            ("to_vessel_id", request.args.get("to_vessel_id")),
            ("status", request.args.get("status")),
        ],
    )


@bp.route("/quota-transfers/<rid>", methods=["GET"])
def get_one_transfer(rid):
    auth()
    return ok_object(pub(get_transfer(rid)))


@bp.route("/quota-transfers/<rid>/counter", methods=["POST"])
def counter_transfer(rid):
    uid, role = auth()
    require_roles(role, OWNER)
    transfer = get_transfer(rid)
    side = _require_party(transfer, uid)
    payload = body()
    expected = f_int(payload, "expected_transfer_version")
    if expected != transfer["version"]:
        raise ApiError(412, "ERR_STALE_VERSION", "expected_transfer_version is stale")
    if transfer["status"] not in OPEN_STATUSES:
        raise ApiError(
            409, "ERR_TRANSFER_NOT_OPEN", "counter requires PROPOSED or COUNTERED"
        )
    if side == transfer["last_offered_by"]:
        raise ApiError(
            409,
            "ERR_TRANSFER_OWN_OFFER",
            "the side that tabled the current offer cannot counter it",
        )
    pounds = f_int(payload, "pounds")
    price = f_int(payload, "price_per_lb_cents")
    if pounds <= 0:
        raise ApiError(400, "ERR_INVALID_REQUEST", "pounds must be > 0")
    if price < 0:
        raise ApiError(400, "ERR_INVALID_REQUEST", "price_per_lb_cents must be >= 0")
    transfer["pounds"] = pounds
    transfer["price_per_lb_cents"] = price
    transfer["round_number"] += 1
    transfer["last_offered_by"] = side
    transfer["status"] = "COUNTERED" if transfer["status"] == "PROPOSED" else "PROPOSED"
    touch(transfer)
    return ok_object(pub(transfer))


@bp.route("/quota-transfers/<rid>/accept", methods=["POST"])
def accept_transfer(rid):
    uid, role = auth()
    require_roles(role, OWNER)
    transfer = get_transfer(rid)
    side = _require_party(transfer, uid)
    if transfer["status"] not in OPEN_STATUSES:
        raise ApiError(
            409, "ERR_TRANSFER_NOT_OPEN", "accept requires PROPOSED or COUNTERED"
        )
    if side == transfer["last_offered_by"]:
        raise ApiError(
            409,
            "ERR_TRANSFER_OWN_OFFER",
            "accept must come from the side that did not table the current offer",
        )
    # Re-check link state and quota at acceptance.
    if not vessel_has_issued_permit(
        transfer["from_vessel_id"], transfer["fishery_code"]
    ) or not vessel_has_issued_permit(transfer["to_vessel_id"], transfer["fishery_code"]):
        raise ApiError(
            409, "ERR_PERMIT_NOT_ACTIVE", "both vessels must hold an ISSUED permit"
        )
    from_holding = find_holding(
        transfer["from_vessel_id"], transfer["fishery_code"], transfer["season_year"]
    )
    to_holding = find_holding(
        transfer["to_vessel_id"], transfer["fishery_code"], transfer["season_year"]
    )
    if from_holding is None or to_holding is None:
        raise ApiError(404, "ERR_QUOTA_HOLDING_NOT_FOUND", "quota holding missing")
    if (
        domain.availability(from_holding)["available_conservative_pounds"]
        < transfer["pounds"]
    ):
        raise ApiError(
            402, "ERR_QUOTA_EXCEEDED", "pounds exceed available_conservative_pounds"
        )
    transfer["status"] = "ACCEPTED"
    touch(transfer)
    # The reservation is derived from the ACCEPTED status; record the mutation
    # on both holdings.
    touch(from_holding)
    touch(to_holding)
    return ok_object(pub(transfer))


@bp.route("/quota-transfers/<rid>/decline", methods=["POST"])
def decline_transfer(rid):
    uid, role = auth()
    require_roles(role, OWNER)
    transfer = get_transfer(rid)
    side = _require_party(transfer, uid)
    if transfer["status"] not in OPEN_STATUSES:
        raise ApiError(
            409, "ERR_TRANSFER_NOT_OPEN", "decline requires PROPOSED or COUNTERED"
        )
    if side == transfer["last_offered_by"]:
        raise ApiError(
            409,
            "ERR_TRANSFER_OWN_OFFER",
            "decline must come from the side that did not table the current offer",
        )
    transfer["status"] = "DECLINED"
    touch(transfer)
    return ok_object(pub(transfer))


@bp.route("/quota-transfers/<rid>/withdraw", methods=["POST"])
def withdraw_transfer(rid):
    uid, role = auth()
    require_roles(role, OWNER)
    transfer = get_transfer(rid)
    side = _require_party(transfer, uid)
    if transfer["status"] not in OPEN_STATUSES:
        raise ApiError(
            409, "ERR_TRANSFER_NOT_OPEN", "withdraw requires PROPOSED or COUNTERED"
        )
    if side != transfer["last_offered_by"]:
        raise ApiError(
            409,
            "ERR_TRANSFER_OWN_OFFER",
            "withdraw must come from the side that tabled the current offer",
        )
    transfer["status"] = "WITHDRAWN"
    touch(transfer)
    return ok_object(pub(transfer))


@bp.route("/quota-transfers/<rid>/settle", methods=["POST"])
def settle_transfer(rid):
    _, role = auth()
    require_roles(role, CLERK)
    transfer = get_transfer(rid)
    if transfer["status"] != "ACCEPTED":
        raise ApiError(409, "ERR_TRANSFER_NOT_ACCEPTED", "settle requires ACCEPTED")
    transfer["transfer_fee_cents"] = domain.transfer_fee(
        transfer["pounds"], transfer["price_per_lb_cents"]
    )
    transfer["status"] = "SETTLED"
    touch(transfer)
    return ok_object(pub(transfer))
