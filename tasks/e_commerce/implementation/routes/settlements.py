"""Settlement routes: Flask Blueprint for /shops/<shop_id>/settlements endpoints."""

from flask import Blueprint, request, g

from middleware import require_auth, require_role, require_shop_owner
from response import success, success_list, parse_pagination
from services.shop import get_shop
from services import settlement as settlement_svc

settlements_bp = Blueprint("settlements", __name__)


@settlements_bp.before_request
def _auth():
    require_auth()


def _load_shop(shop_id):
    """Load shop and enforce ownership for Sellers."""
    shop = get_shop(shop_id)
    if g.role == "Seller":
        require_shop_owner(shop)
    return shop


# ---------------------------------------------------------------------------
# POST /shops/<shop_id>/settlements — Create settlement (Seller/Admin)
# ---------------------------------------------------------------------------
@settlements_bp.route("/shops/<shop_id>/settlements", methods=["POST"])
def create_settlement(shop_id):
    require_role("Seller", "PlatformAdmin")
    _load_shop(shop_id)
    data = request.get_json(force=True)
    result = settlement_svc.create_settlement(shop_id, data)
    return success(result, 201)


# ---------------------------------------------------------------------------
# GET /shops/<shop_id>/settlements — List settlements
# ---------------------------------------------------------------------------
@settlements_bp.route("/shops/<shop_id>/settlements", methods=["GET"])
def list_settlements(shop_id):
    require_role("Seller", "PlatformAdmin")
    _load_shop(shop_id)
    limit, offset = parse_pagination(request.args)
    items, total = settlement_svc.list_settlements(shop_id, limit, offset)
    return success_list(items, total, limit, offset)


# ---------------------------------------------------------------------------
# GET /shops/<shop_id>/settlements/<settlement_id> — Get settlement
# ---------------------------------------------------------------------------
@settlements_bp.route("/shops/<shop_id>/settlements/<settlement_id>", methods=["GET"])
def get_settlement(shop_id, settlement_id):
    require_role("Seller", "PlatformAdmin")
    _load_shop(shop_id)
    result = settlement_svc.get_settlement(shop_id, settlement_id)
    return success(result)


# ---------------------------------------------------------------------------
# POST /shops/<shop_id>/settlements/<sid>/submit — Submit (Seller)
# ---------------------------------------------------------------------------
@settlements_bp.route(
    "/shops/<shop_id>/settlements/<settlement_id>/submit", methods=["POST"]
)
def submit_settlement(shop_id, settlement_id):
    require_role("Seller", "PlatformAdmin")
    _load_shop(shop_id)
    result = settlement_svc.submit_settlement(shop_id, settlement_id)
    return success(result)


# ---------------------------------------------------------------------------
# POST /shops/<shop_id>/settlements/<sid>/approve — Approve (Admin)
# ---------------------------------------------------------------------------
@settlements_bp.route(
    "/shops/<shop_id>/settlements/<settlement_id>/approve", methods=["POST"]
)
def approve_settlement(shop_id, settlement_id):
    require_role("PlatformAdmin")
    result = settlement_svc.approve_settlement(shop_id, settlement_id)
    return success(result)


# ---------------------------------------------------------------------------
# POST /shops/<shop_id>/settlements/<sid>/mark-paid — Mark paid (Admin)
# ---------------------------------------------------------------------------
@settlements_bp.route(
    "/shops/<shop_id>/settlements/<settlement_id>/mark-paid", methods=["POST"]
)
def mark_paid(shop_id, settlement_id):
    require_role("PlatformAdmin")
    result = settlement_svc.mark_paid(shop_id, settlement_id)
    return success(result)


# ---------------------------------------------------------------------------
# POST /shops/<shop_id>/settlements/<sid>/dispute — Dispute (Seller)
# ---------------------------------------------------------------------------
@settlements_bp.route(
    "/shops/<shop_id>/settlements/<settlement_id>/dispute", methods=["POST"]
)
def dispute_settlement(shop_id, settlement_id):
    require_role("Seller")
    _load_shop(shop_id)
    result = settlement_svc.dispute_settlement(shop_id, settlement_id)
    return success(result)


# ---------------------------------------------------------------------------
# POST /shops/<shop_id>/settlements/<sid>/resolve — Resolve dispute (Admin)
# ---------------------------------------------------------------------------
@settlements_bp.route(
    "/shops/<shop_id>/settlements/<settlement_id>/resolve-dispute", methods=["POST"]
)
def resolve_dispute(shop_id, settlement_id):
    require_role("PlatformAdmin")
    result = settlement_svc.resolve_dispute(shop_id, settlement_id)
    return success(result)
