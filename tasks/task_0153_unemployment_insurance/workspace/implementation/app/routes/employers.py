"""Employer routes."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import (
    ROLE_ADJUDICATOR,
    ROLE_EMPLOYER_AGENT,
    ROLE_SYSTEM_ADMIN,
    current_role,
    current_user_id,
    require_auth,
)
from ..envelope import paginate, parse_pagination, success_array, success_object
from ..errors import APIError
from ..serializers import serialize_employer, serialize_employer_charge
from ..services.entities import create_employer, relieve_charge
from ..store import get_store
from ..validators import (
    get_json_body,
    require_int,
    require_string,
    validate_ein,
)
from ._helpers import lookup_employer, sort_by_created_at, require_employer_owner

bp = Blueprint("employers", __name__)


@bp.post("/employers")
@require_auth([ROLE_SYSTEM_ADMIN])
def employers_create():
    body = get_json_body()
    ein = validate_ein(require_string(body, "ein"))
    legal_name = require_string(body, "legal_name")
    reserve = require_int(body, "reserve_ratio_basis_cents", min_val=1)
    taxable = require_int(body, "taxable_payroll_cents", min_val=0)
    entity = create_employer({
        "ein": ein,
        "legal_name": legal_name,
        "reserve_ratio_basis_cents": reserve,
        "taxable_payroll_cents": taxable,
    })
    return jsonify(success_object(serialize_employer(entity))), 201


@bp.get("/employers/<employer_id>")
@require_auth([ROLE_EMPLOYER_AGENT, ROLE_SYSTEM_ADMIN])
def employers_read(employer_id: str):
    e = lookup_employer(employer_id)
    require_employer_owner(employer_id)
    return jsonify(success_object(serialize_employer(e))), 200


@bp.get("/employers/<employer_id>/charges")
@require_auth([ROLE_EMPLOYER_AGENT, ROLE_SYSTEM_ADMIN])
def employer_charges_list(employer_id: str):
    lookup_employer(employer_id)
    require_employer_owner(employer_id)
    status_filter = request.args.get("status")
    limit, offset = parse_pagination()
    store = get_store()
    items = [ch for ch in store.employer_charges.values() if ch["employer_id"] == employer_id]
    if status_filter:
        items = [ch for ch in items if ch["status"] == status_filter]
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return jsonify(success_array(
        [serialize_employer_charge(c) for c in page],
        limit=limit, offset=offset, total_count=total,
    )), 200


@bp.post("/employers/<employer_id>/charges/<charge_id>/relieve")
@require_auth([ROLE_EMPLOYER_AGENT, ROLE_ADJUDICATOR])
def employer_charge_relieve(employer_id: str, charge_id: str):
    lookup_employer(employer_id)
    require_employer_owner(employer_id)
    body = get_json_body()
    reason = require_string(body, "reason")
    ch = relieve_charge(employer_id, charge_id, reason, current_role(), current_user_id())
    return jsonify(success_object(serialize_employer_charge(ch))), 200
