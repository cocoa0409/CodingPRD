"""BagKit lifecycle endpoints."""
from flask import Blueprint

from db import store, touch
from errors import fail
from middleware import endpoint
from response import success
from services import domain
from util import get_body

bp = Blueprint("kits", __name__)


@bp.route("/bag-kits/<kid>/dispatch", methods=["POST"])
@endpoint(["ZoneOperator"])
def dispatch_kit(user_id, role, kid):
    get_body()
    kit = domain.get_or_404(store.kits, kid, "BagKit")
    if kit["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", "Kit must be REQUESTED to dispatch")
    kit["status"] = "DISPATCHED"
    touch(kit)
    return success(domain.kit_view(kit))


@bp.route("/bag-kits/<kid>/deliver", methods=["POST"])
@endpoint(["Driver"])
def deliver_kit(user_id, role, kid):
    get_body()
    kit = domain.get_or_404(store.kits, kid, "BagKit")
    if kit["status"] != "DISPATCHED":
        fail("ERR_INVALID_STATE", "Kit must be DISPATCHED to deliver")
    kit["status"] = "DELIVERED"
    touch(kit)
    return success(domain.kit_view(kit))


@bp.route("/bag-kits/<kid>/retire", methods=["POST"])
@endpoint(["Resident", "ZoneOperator"])
def retire_kit(user_id, role, kid):
    kit = store.kits.get(kid)
    # p2: Resident may retire only their own kit (decidable only when kit exists)
    if role == "Resident" and kit is not None and kit["resident_id"] != user_id:
        fail("ERR_UNAUTHORIZED", "Residents may only retire their own kits")
    get_body()
    if kit is None:
        fail("ERR_NOT_FOUND", "BagKit not found: %s" % kid)
    if kit["status"] != "DELIVERED":
        fail("ERR_INVALID_STATE", "Kit must be DELIVERED to retire")
    kit["status"] = "RETIRED"
    touch(kit)
    return success(domain.kit_view(kit))
