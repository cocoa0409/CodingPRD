"""TiDraw endpoints (PRD §3.6)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError, ERR_NOT_FOUND, ERR_FK_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_TI_ALLOWANCE_EXCEEDED,
)
from middleware import auth_required, ALL_ROLES, PROPERTY_MANAGER, ACCOUNTANT, TENANT
from response import ok_object, ok_array
from routes._helpers import (
    get_body, require_fields, serialize, serialize_list, is_int,
    parse_pagination, paginate, order_by_created,
)
from services.common import new_common_fields, touch
from services.ledger import post_ledger_entry

bp = Blueprint("ti_draws", __name__)


def _recompute_ti_drawn(lease: dict):
    """Lease.ti_drawn_cents = sum of APPROVED TiDraw amounts for the lease (PRD §2.6)."""
    total = 0
    for d in db.ti_draws.values():
        if d["lease_id"] == lease["id"] and d["status"] == "APPROVED":
            total += d["amount_cents"]
    lease["ti_drawn_cents"] = total


@bp.post("/ti-draws")
def create_ti_draw():
    auth_required({PROPERTY_MANAGER, TENANT})()
    body = get_body()
    require_fields(body, ["lease_id", "amount_cents"])

    lease_id = body["lease_id"]
    if db.leases.get(lease_id) is None:
        raise APIError(ERR_FK_NOT_FOUND, 404, "lease_id references a non-existent lease")

    amount_cents = body["amount_cents"]
    if not is_int(amount_cents) or amount_cents <= 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "amount_cents must be a positive integer")

    draw = {
        **new_common_fields(),
        "lease_id": lease_id,
        "amount_cents": amount_cents,
        "status": "REQUESTED",
    }
    db.ti_draws[draw["id"]] = draw
    return ok_object(serialize(draw), http_status=201)


@bp.get("/ti-draws/<did>")
def get_ti_draw(did):
    auth_required(ALL_ROLES)()
    d = db.ti_draws.get(did)
    if d is None:
        raise APIError(ERR_NOT_FOUND, 404, "TI draw not found")
    return ok_object(serialize(d))


@bp.get("/ti-draws")
def list_ti_draws():
    auth_required(ALL_ROLES)()
    limit, offset = parse_pagination()
    items = list(db.ti_draws.values())
    lease_id = request.args.get("lease_id")
    if lease_id is not None:
        items = [d for d in items if d["lease_id"] == lease_id]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


@bp.post("/ti-draws/<did>/approve")
def approve_ti_draw(did):
    auth_required({ACCOUNTANT})()
    draw = db.ti_draws.get(did)
    if draw is None:
        raise APIError(ERR_NOT_FOUND, 404, "TI draw not found")

    if draw["status"] != "REQUESTED":
        raise APIError(ERR_INVALID_STATE, 409, "TI draw must be REQUESTED to approve")

    lease = db.leases.get(draw["lease_id"])
    if lease is None:
        raise APIError(ERR_FK_NOT_FOUND, 404, "Referenced lease not found")
    if lease["status"] not in ("ACTIVE", "HOLDOVER"):
        raise APIError(ERR_INVALID_STATE, 409, "Referenced lease must be ACTIVE or HOLDOVER")

    # Remaining allowance must cover this draw.
    if lease["ti_drawn_cents"] + draw["amount_cents"] > lease["ti_allowance_cents"]:
        raise APIError(ERR_TI_ALLOWANCE_EXCEEDED, 422,
                       "Approving this draw would exceed the TI allowance")

    draw["status"] = "APPROVED"
    touch(draw)

    # Cascade: recompute ti_drawn_cents (bump lease version), post TI_DRAW -amount.
    _recompute_ti_drawn(lease)
    touch(lease)
    post_ledger_entry(lease, "TI_DRAW", -draw["amount_cents"])

    return ok_object(serialize(draw))


@bp.post("/ti-draws/<did>/reject")
def reject_ti_draw(did):
    auth_required({ACCOUNTANT})()
    draw = db.ti_draws.get(did)
    if draw is None:
        raise APIError(ERR_NOT_FOUND, 404, "TI draw not found")
    if draw["status"] != "REQUESTED":
        raise APIError(ERR_INVALID_STATE, 409, "TI draw must be REQUESTED to reject")
    draw["status"] = "REJECTED"
    touch(draw)
    return ok_object(serialize(draw))
