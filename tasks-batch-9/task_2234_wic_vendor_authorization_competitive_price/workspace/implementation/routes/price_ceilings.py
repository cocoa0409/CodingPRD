"""Maximum allowable reimbursement read endpoints (PRD §3.4)."""

from flask import Blueprint

import config as C
import envelope
from auth import authenticate
from routes.common import listing, need
from store import db, ordered

bp = Blueprint("price_ceilings", __name__)

READ_ROLES = (
    C.ROLE_ANALYST,
    C.ROLE_SUPERVISOR,
    C.ROLE_INVESTIGATOR,
    C.ROLE_VENDOR_OPERATOR,
)


@bp.get("/price-ceilings/<entity_id>")
def read_ceiling(entity_id):
    authenticate(*READ_ROLES)
    return envelope.success(
        need(db.price_ceilings, entity_id, "ERR_PRICE_CEILING_NOT_FOUND")
    )


@bp.get("/price-ceilings")
def list_ceilings():
    authenticate(*READ_ROLES)
    return listing(
        ordered(db.price_ceilings),
        {
            "peer_group_id": "peer_group_id",
            "food_item_id": "food_item_id",
            "price_cycle_id": "price_cycle_id",
            "status": "status",
        },
    )
