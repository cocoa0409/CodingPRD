"""Beneficiary endpoints."""

from flask import Blueprint, g, request
from core.auth import require_roles
from core.envelope import success_object
from core.errors import raise_error
from core.store import STORE, lock
from core.validation import (
    require_body, require_full_name, require_ssn_last_four, require_enum, require_field,
)
from core.models import beneficiary_create, beneficiary_view


bp = Blueprint("beneficiaries", __name__)

RELATIONSHIP_CODES = {
    "SELF", "CHILD", "SIBLING", "NIECE_NEPHEW", "PARENT",
    "COUSIN", "SPOUSE", "IN_LAW", "FIRST_COUSIN_ONCE_REMOVED",
}


@bp.post("/beneficiaries")
@require_roles("PlanAdministrator", "Donor")
def create_beneficiary():
    body = require_body(request)
    full_name = require_full_name(body, "full_name")
    date_of_birth = require_field(body, "date_of_birth", kind="string")
    ssn_last_four = require_ssn_last_four(body, "ssn_last_four")
    rel_code = require_enum(body, "relationship_family_code", RELATIONSHIP_CODES)

    with lock():
        b = beneficiary_create(full_name, date_of_birth, ssn_last_four, rel_code)
    return success_object(beneficiary_view(b), 201)


@bp.get("/beneficiaries/<bid>")
@require_roles("PlanAdministrator", "Donor", "Beneficiary")
def get_beneficiary(bid):
    b = STORE.beneficiaries.get(bid)
    if not b:
        raise_error("ERR_NOT_FOUND", f"Beneficiary {bid} not found")
    if g.user_role == "Beneficiary" and g.user_id != bid:
        raise_error("ERR_FORBIDDEN", "Beneficiary may only read their own record")
    return success_object(beneficiary_view(b))
