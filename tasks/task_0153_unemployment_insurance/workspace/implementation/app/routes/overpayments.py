"""Overpayment routes."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import (
    ROLE_ADJUDICATOR,
    ROLE_APPEAL_OFFICER,
    ROLE_CLAIMANT,
    ROLE_SYSTEM_ADMIN,
    current_user_id,
    require_auth,
)
from ..envelope import paginate, parse_pagination, success_array, success_object
from ..serializers import serialize_overpayment
from ..services.entities import (
    repay_overpayment,
    waive_overpayment,
    write_off_overpayment,
)
from ..store import get_store
from ..validators import get_json_body, optional_int, require_int, require_string
from ._helpers import (
    lookup_claim,
    lookup_overpayment,
    require_claim_owner,
    sort_by_created_at,
)

bp = Blueprint("overpayments", __name__)


@bp.get("/overpayments/<overpayment_id>")
@require_auth([ROLE_CLAIMANT, ROLE_ADJUDICATOR, ROLE_APPEAL_OFFICER, ROLE_SYSTEM_ADMIN])
def overpayment_read(overpayment_id: str):
    o = lookup_overpayment(overpayment_id)
    claim = get_store().claims.get(o["claim_id"])
    if claim is not None:
        require_claim_owner(claim)
    return jsonify(success_object(serialize_overpayment(o))), 200


@bp.get("/claims/<claim_id>/overpayments")
@require_auth([ROLE_CLAIMANT, ROLE_ADJUDICATOR, ROLE_APPEAL_OFFICER, ROLE_SYSTEM_ADMIN])
def overpayment_list_for_claim(claim_id: str):
    cl = lookup_claim(claim_id)
    require_claim_owner(cl)
    status_filter = request.args.get("status")
    limit, offset = parse_pagination()
    items = [o for o in get_store().overpayments.values() if o["claim_id"] == claim_id]
    if status_filter:
        items = [o for o in items if o["status"] == status_filter]
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return jsonify(success_array(
        [serialize_overpayment(o) for o in page],
        limit=limit, offset=offset, total_count=total,
    )), 200


@bp.post("/overpayments/<overpayment_id>/repay")
@require_auth([ROLE_CLAIMANT])
def overpayment_repay(overpayment_id: str):
    lookup_overpayment(overpayment_id)
    body = get_json_body()
    amount = require_int(body, "amount_cents")  # don't pre-validate min — service decides
    version = optional_int(body, "version", min_val=0)
    o = repay_overpayment(overpayment_id, amount, current_user_id(), version)
    return jsonify(success_object(serialize_overpayment(o))), 200


@bp.post("/overpayments/<overpayment_id>/waive")
@require_auth([ROLE_ADJUDICATOR])
def overpayment_waive(overpayment_id: str):
    lookup_overpayment(overpayment_id)
    body = get_json_body()
    # `reason` field exists in input spec but is not stored on Overpayment.
    require_string(body, "reason") if "reason" in body else None
    version = optional_int(body, "version", min_val=0)
    o = waive_overpayment(overpayment_id, version)
    return jsonify(success_object(serialize_overpayment(o))), 200


@bp.post("/overpayments/<overpayment_id>/write-off")
@require_auth([ROLE_ADJUDICATOR])
def overpayment_write_off(overpayment_id: str):
    lookup_overpayment(overpayment_id)
    body = get_json_body()
    version = optional_int(body, "version", min_val=0)
    o = write_off_overpayment(overpayment_id, version)
    return jsonify(success_object(serialize_overpayment(o))), 200
