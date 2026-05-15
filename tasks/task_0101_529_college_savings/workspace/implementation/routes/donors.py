"""Donor endpoints: POST /donors, GET /donors/{id}."""

from flask import Blueprint, g, request
from core.auth import require_roles
from core.envelope import success_object
from core.errors import raise_error
from core.store import STORE, lock
from core.validation import (
    require_body, require_full_name, require_ssn_last_four, require_state_code,
)
from core.models import donor_create, donor_view


bp = Blueprint("donors", __name__)


@bp.post("/donors")
@require_roles("PlanAdministrator")
def create_donor():
    body = require_body(request)
    full_name = require_full_name(body, "full_name")
    state_of_residence = require_state_code(body, "state_of_residence")
    ssn_last_four = require_ssn_last_four(body, "ssn_last_four")

    with lock():
        if state_of_residence not in STORE.state_rules:
            # The PRD constrains state_of_residence to match a StateRule.state_code.
            raise_error("ERR_NOT_FOUND",
                        f"No StateRule for state_of_residence '{state_of_residence}'")
        d = donor_create(full_name, state_of_residence, ssn_last_four)
    return success_object(donor_view(d), 201)


@bp.get("/donors/<donor_id>")
@require_roles("PlanAdministrator", "Donor")
def get_donor(donor_id):
    d = STORE.donors.get(donor_id)
    if not d:
        raise_error("ERR_NOT_FOUND", f"Donor {donor_id} not found")
    # PRD §2.1: Donor identity = X-User-ID; donors should be able to read themselves.
    if g.user_role == "Donor" and g.user_id != donor_id:
        raise_error("ERR_FORBIDDEN", "Donor may only read their own donor record")
    return success_object(donor_view(d))
