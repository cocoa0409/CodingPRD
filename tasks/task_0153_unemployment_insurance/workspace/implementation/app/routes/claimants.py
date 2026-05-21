"""Claimant routes."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import (
    ROLE_ADJUDICATOR,
    ROLE_APPEAL_OFFICER,
    ROLE_CLAIMANT,
    ROLE_SYSTEM_ADMIN,
    current_role,
    current_user_id,
    require_auth,
)
from ..envelope import success_array, success_object, parse_pagination, paginate
from ..errors import APIError
from ..serializers import (
    serialize_claim,
    serialize_claimant,
    serialize_overpayment,
    serialize_wage_record,
    serialize_certification,
)
from ..services.entities import create_claimant, create_wage_record, open_claim
from ..store import get_store
from ..validators import (
    get_json_body,
    require_int,
    require_string,
    validate_ein,
    validate_iso_date,
    validate_ssn_last4,
    validate_state_code,
)
from ._helpers import (
    lookup_claim,
    lookup_claimant,
    require_claim_owner,
    require_claimant_ownership,
    sort_by_created_at,
)

bp = Blueprint("claimants", __name__)


@bp.post("/claimants")
@require_auth([ROLE_SYSTEM_ADMIN, ROLE_CLAIMANT])
def claimants_create():
    body = get_json_body()
    ssn = validate_ssn_last4(require_string(body, "ssn_last4"))
    full_name = require_string(body, "full_name")
    state = validate_state_code(require_string(body, "state_residence"))
    dob = validate_iso_date(require_string(body, "date_of_birth"), "date_of_birth")
    entity = create_claimant({
        "ssn_last4": ssn,
        "full_name": full_name,
        "state_residence": state,
        "date_of_birth": dob,
    })
    return jsonify(success_object(serialize_claimant(entity))), 201


@bp.get("/claimants/<claimant_id>")
@require_auth([ROLE_CLAIMANT, ROLE_ADJUDICATOR, ROLE_APPEAL_OFFICER, ROLE_SYSTEM_ADMIN])
def claimants_read(claimant_id: str):
    c = lookup_claimant(claimant_id)
    if current_role() == ROLE_CLAIMANT and current_user_id() != claimant_id:
        raise APIError("ERR_NOT_OWNER", "Claimant may only read own record", 403)
    return jsonify(success_object(serialize_claimant(c))), 200


# ----- Wage records under a claimant -----

@bp.post("/claimants/<claimant_id>/wage-records")
@require_auth([ROLE_SYSTEM_ADMIN])
def wage_records_create(claimant_id: str):
    lookup_claimant(claimant_id)
    body = get_json_body()
    employer_id = require_string(body, "employer_id")
    quarter_year = require_int(body, "quarter_year", min_val=2000)
    quarter_index = require_int(body, "quarter_index", min_val=1, max_val=4)
    wages_cents = require_int(body, "wages_cents", min_val=0)
    wr = create_wage_record(claimant_id, {
        "employer_id": employer_id,
        "quarter_year": quarter_year,
        "quarter_index": quarter_index,
        "wages_cents": wages_cents,
    })
    return jsonify(success_object(serialize_wage_record(wr))), 201


@bp.get("/claimants/<claimant_id>/wage-records")
@require_auth([ROLE_CLAIMANT, ROLE_ADJUDICATOR, ROLE_SYSTEM_ADMIN])
def wage_records_list(claimant_id: str):
    lookup_claimant(claimant_id)
    if current_role() == ROLE_CLAIMANT and current_user_id() != claimant_id:
        raise APIError("ERR_NOT_OWNER", "Claimant may only list own wage records", 403)
    limit, offset = parse_pagination()
    items = [wr for wr in get_store().wage_records.values() if wr["claimant_id"] == claimant_id]
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return jsonify(success_array(
        [serialize_wage_record(w) for w in page],
        limit=limit, offset=offset, total_count=total,
    )), 200


# ----- Claims under a claimant -----

@bp.post("/claimants/<claimant_id>/claims")
@require_auth([ROLE_CLAIMANT])
def claims_create(claimant_id: str):
    lookup_claimant(claimant_id)
    require_claimant_ownership(claimant_id)
    cl = open_claim(claimant_id)
    return jsonify(success_object(serialize_claim(cl))), 201
