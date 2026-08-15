"""FarmMembership endpoints (PRD §3.1)."""

from decimal import Decimal

from flask import Blueprint, request

import db
from errors import ApiError, ERR_SHARE_SUM_INVALID
from middleware import require_roles, ALL_ROLES
from response import success_object, paginate
from services.helpers import (
    get_farm_or_404, get_producer_or_404, get_membership_or_404,
)
from validation import body, require_string, require_decimal, optional_bool

bp = Blueprint("memberships", __name__)


@bp.post("/fsa/farms/<farm_id>/memberships")
def create_membership(farm_id):
    require_roles(["CountySpecialist"])
    farm = get_farm_or_404(farm_id)
    data = body()
    producer_id = require_string(data, "producer_id")
    producer = get_producer_or_404(producer_id)
    share = require_decimal(data, "share_percent")
    is_spouse_pair = optional_bool(data, "is_spouse_pair", False)

    if share <= 0 or share > 100:
        raise ApiError(ERR_SHARE_SUM_INVALID,
                       "share_percent must be > 0 and <= 100", 422)

    # Share-percent sum across the farm's ACTIVE memberships must equal
    # exactly 100.00 after the add (PRD §3.1; validation priority 14).
    existing = [
        m for m in db.memberships.values()
        if m["farm_id"] == farm_id and m["membership_status"] == "ACTIVE"
    ]
    total = sum(Decimal(str(m["share_percent"])) for m in existing) + share
    if total != Decimal("100"):
        raise ApiError(
            ERR_SHARE_SUM_INVALID,
            "Membership share_percent sum on a farm must equal exactly 100.00",
            422,
        )

    membership = db.common_fields()
    membership.update({
        "farm_id": farm_id,
        "producer_id": producer_id,
        "share_percent": float(share),
        "is_spouse_pair": is_spouse_pair,
        "membership_status": "ACTIVE",
    })
    db.memberships[membership["id"]] = membership

    # Spouse rule: two memberships flagged is_spouse_pair raise the members'
    # payment limitation cap to 25000000 cents (PRD §3.8).
    flagged = [
        m for m in db.memberships.values()
        if m["farm_id"] == farm_id
        and m["membership_status"] == "ACTIVE"
        and m.get("is_spouse_pair")
    ]
    if len(flagged) >= 2:
        for m in flagged:
            p = db.producers.get(m["producer_id"])
            if p is not None and p["payment_limitation_cap_cents"] < 25000000:
                p["payment_limitation_cap_cents"] = 25000000
                db.touch(p)

    return success_object(membership, 201)


@bp.get("/fsa/farms/<farm_id>/memberships")
def list_farm_memberships(farm_id):
    require_roles(ALL_ROLES)
    get_farm_or_404(farm_id)
    items = [m for m in db.memberships.values() if m["farm_id"] == farm_id]
    items.sort(key=lambda m: m["created_at"])
    return paginate(items, request.args)


@bp.get("/fsa/memberships")
def list_memberships():
    require_roles(ALL_ROLES)
    producer_id = request.args.get("producer_id")
    farm_id = request.args.get("farm_id")
    items = list(db.memberships.values())
    if producer_id is not None:
        items = [m for m in items if m["producer_id"] == producer_id]
    if farm_id is not None:
        items = [m for m in items if m["farm_id"] == farm_id]
    items.sort(key=lambda m: m["created_at"])
    return paginate(items, request.args)


@bp.get("/fsa/memberships/<membership_id>")
def get_membership(membership_id):
    require_roles(ALL_ROLES)
    return success_object(get_membership_or_404(membership_id))


@bp.delete("/fsa/memberships/<membership_id>")
def delete_membership(membership_id):
    require_roles(["CountySpecialist"])
    m = get_membership_or_404(membership_id)
    m["membership_status"] = "REMOVED"
    db.touch(m)
    return "", 204
