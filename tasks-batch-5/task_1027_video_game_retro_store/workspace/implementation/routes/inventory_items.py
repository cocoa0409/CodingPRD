from flask import Blueprint

import store
from common import authorize, require_found
from envelope import object_response

bp = Blueprint("inventory_items", __name__)


@bp.get("/inventory-items/<iid>")
def get_inventory_item(iid):
    authorize(["Member", "Clerk", "Manager"])
    i = require_found(store.inventory_items, iid)
    return object_response(store.serialize(i), 200)
