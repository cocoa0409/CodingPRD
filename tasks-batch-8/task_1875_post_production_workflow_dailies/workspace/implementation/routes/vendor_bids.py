"""VendorBid routes (PRD §3.5)."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_VENDOR_INELIGIBLE,
)
from helpers import (
    new_entity,
    touch,
    get_json_body,
    require_fields,
    check_int,
    get_pagination,
    get_filter,
    paginate,
)
from middleware import require_roles
from response import success_object, success_list
from routes.projects import get_project_or_404
from routes.vendors import get_vendor_or_404
from services.transitions import guard_transition

bp = Blueprint("vendor_bids", __name__)

BID_TERMINAL = ("AWARDED", "REJECTED", "EXPIRED", "WITHDRAWN")
# Terminal states of the parent TurnoverPackage lifecycle (PRD §3.5); kept
# locally to avoid a circular import with routes.turnovers.
TURNOVER_TERMINAL = ("CLOSED", "VOID")
LIST_ROLES = ("PostSupervisor", "VendorRep", "FacilityAdmin")


def serialize(bid):
    return dict(bid)


def get_bid_or_404(project, bid_id):
    bid = db.vendor_bids.get(bid_id)
    if bid is None or bid["project_id"] != project["id"]:
        raise ApiError(ERR_NOT_FOUND, f"VendorBid {bid_id} does not exist", 404)
    return bid


@bp.route("/post-production/projects/<project_id>/vendor-bids", methods=["POST"])
def create_bid(project_id):
    user_id, role = require_roles(("VendorRep",))
    project = get_project_or_404(project_id)
    body = get_json_body()
    require_fields(body, ("turnover_id", "vendor_id", "bid_amount_cents", "eta_days"))
    turnover_id = body["turnover_id"]
    vendor_id = body["vendor_id"]
    if not isinstance(turnover_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'turnover_id' must be a string", 400)
    if not isinstance(vendor_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'vendor_id' must be a string", 400)
    # FK resolution (priority 3)
    turnover = db.turnovers.get(turnover_id)
    if turnover is None or turnover["project_id"] != project_id:
        raise ApiError(
            ERR_NOT_FOUND, f"TurnoverPackage {turnover_id} does not exist", 404
        )
    vendor = get_vendor_or_404(vendor_id)
    bid_amount_cents = check_int(body, "bid_amount_cents", min_v=1)
    eta_days = check_int(body, "eta_days", min_v=1, max_v=60)
    # VendorRep acts only for their own vendor: vendor_id must equal X-User-ID.
    if vendor_id != user_id:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "A VendorRep may submit bids only for their own vendor "
            "(vendor_id must equal X-User-ID)",
            400,
        )
    # Endpoint contract: submit a bid against a STAGED turnover.
    if turnover["status"] == "DRAFT" or turnover["status"] in (
        "CLOSED",
        "VOID",
    ):
        if turnover["status"] in TURNOVER_TERMINAL:
            raise ApiError(
                "ERR_ALREADY_TERMINAL",
                "Attempted transition on a turnover package already in "
                f"terminal state {turnover['status']}",
                409,
            )
        raise ApiError(
            ERR_INVALID_STATE,
            "Bids may be submitted only against a STAGED turnover",
            409,
        )
    if turnover["status"] != "STAGED":
        raise ApiError(
            ERR_INVALID_STATE,
            "Bids may be submitted only against a STAGED turnover",
            409,
        )
    bid = new_entity(
        {
            "project_id": project_id,
            "turnover_id": turnover_id,
            "vendor_id": vendor_id,
            "bid_amount_cents": bid_amount_cents,
            "eta_days": eta_days,
            "status": "SUBMITTED",
        }
    )
    db.vendor_bids[bid["id"]] = bid
    return success_object(serialize(bid), 201)


@bp.route("/post-production/projects/<project_id>/vendor-bids", methods=["GET"])
def list_bids(project_id):
    require_roles(LIST_ROLES)
    get_project_or_404(project_id)
    limit, offset = get_pagination()
    items = [b for b in db.vendor_bids.values() if b["project_id"] == project_id]
    turnover_id = get_filter("turnover_id")
    if turnover_id is not None:
        items = [b for b in items if b.get("turnover_id") == turnover_id]
    vendor_id = get_filter("vendor_id")
    if vendor_id is not None:
        items = [b for b in items if b.get("vendor_id") == vendor_id]
    status = get_filter("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    window, total = paginate(items, limit, offset)
    return success_list([serialize(b) for b in window], limit, offset, total)


@bp.route(
    "/post-production/projects/<project_id>/vendor-bids/<bid_id>/award",
    methods=["POST"],
)
def award_bid(project_id, bid_id):
    require_roles(("PostSupervisor",))
    project = get_project_or_404(project_id)
    bid = get_bid_or_404(project, bid_id)
    guard_transition(bid, "SUBMITTED", BID_TERMINAL, "vendor bid")
    turnover = db.turnovers.get(bid["turnover_id"])
    if turnover is None:
        raise ApiError(
            ERR_NOT_FOUND, f"TurnoverPackage {bid['turnover_id']} does not exist", 404
        )
    # Parent TurnoverPackage.status must be STAGED.
    if turnover["status"] != "STAGED":
        if turnover["status"] in ("CLOSED", "VOID"):
            raise ApiError(
                "ERR_ALREADY_TERMINAL",
                "Attempted transition on a turnover package already in "
                f"terminal state {turnover['status']}",
                409,
            )
        raise ApiError(
            ERR_INVALID_STATE,
            "Parent TurnoverPackage must be STAGED to award a bid",
            409,
        )
    # No other bid for this turnover may already be AWARDED.
    for other in db.vendor_bids.values():
        if (
            other.get("turnover_id") == bid["turnover_id"]
            and other["id"] != bid_id
            and other["status"] == "AWARDED"
        ):
            raise ApiError(
                ERR_INVALID_STATE,
                "Another bid for this turnover is already AWARDED",
                409,
            )
    # Vendor eligibility (priority 12): vendor ONBOARDED and capability covers
    # turnover_kind.
    vendor = db.vendors.get(bid["vendor_id"])
    if vendor is None:
        raise ApiError(
            ERR_NOT_FOUND, f"Vendor {bid['vendor_id']} does not exist", 404
        )
    if vendor["status"] != "ONBOARDED" or (
        turnover["turnover_kind"] not in vendor["capabilities"]
    ):
        raise ApiError(
            ERR_VENDOR_INELIGIBLE,
            "Vendor lacks required capability for turnover_kind, or vendor "
            "not ONBOARDED",
            422,
        )
    bid["status"] = "AWARDED"
    touch(bid)
    # All other SUBMITTED bids for the same turnover -> REJECTED.
    for other in db.vendor_bids.values():
        if (
            other.get("turnover_id") == bid["turnover_id"]
            and other["id"] != bid_id
            and other["status"] == "SUBMITTED"
        ):
            other["status"] = "REJECTED"
            touch(other)
    # TurnoverPackage.vendor_id := bid.vendor_id (a mutation of the turnover).
    if turnover.get("vendor_id") != bid["vendor_id"]:
        turnover["vendor_id"] = bid["vendor_id"]
        touch(turnover)
    return success_object(serialize(bid))


@bp.route(
    "/post-production/projects/<project_id>/vendor-bids/<bid_id>/withdraw",
    methods=["POST"],
)
def withdraw_bid(project_id, bid_id):
    user_id, role = require_roles(("VendorRep",))
    project = get_project_or_404(project_id)
    bid = get_bid_or_404(project, bid_id)
    guard_transition(bid, "SUBMITTED", BID_TERMINAL, "vendor bid")
    # VendorRep may withdraw only their own bids (their vendor's bids).
    if bid["vendor_id"] != user_id:
        raise ApiError(
            ERR_INVALID_STATE,
            "A VendorRep may withdraw only bids belonging to their own vendor",
            409,
        )
    bid["status"] = "WITHDRAWN"
    touch(bid)
    return success_object(serialize(bid))


# ---------------------------------------------------------------------------
# Flat alias
# ---------------------------------------------------------------------------


@bp.route("/post-production/vendor-bids/<bid_id>", methods=["GET"])
def get_bid_flat(bid_id):
    require_roles(LIST_ROLES)
    bid = db.vendor_bids.get(bid_id)
    if bid is None:
        raise ApiError(ERR_NOT_FOUND, f"VendorBid {bid_id} does not exist", 404)
    return success_object(serialize(bid))
