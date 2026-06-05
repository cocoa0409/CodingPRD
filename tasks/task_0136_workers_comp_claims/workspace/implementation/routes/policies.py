"""Policy endpoints (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_DUPLICATE_RESOURCE
from middleware import require_auth, get_json_body
from response import ok_object
from services.validation import require_str, require_int, require_datetime
from services import calculations as calc
from routes._common import get_employer, get_policy, assert_employer_owns_employer

bp = Blueprint("policies", __name__)


@bp.post("/policies")
def create_policy():
    require_auth(["PlatformAdmin"])()
    body = get_json_body()

    employer_id = require_str(body, "employer_id")
    # Existence (priority 4) before uniqueness / field-shape business checks.
    emp = get_employer(employer_id)

    policy_number = require_str(body, "policy_number")
    manual_premium_cents = require_int(body, "manual_premium_cents", minimum=0)
    require_datetime(body, "effective_date")
    require_datetime(body, "expiration_date")

    # Uniqueness (priority 12) of policy_number across all policies.
    for p in db.policies.values():
        if p["policy_number"] == policy_number:
            raise APIError(ERR_DUPLICATE_RESOURCE, 409,
                           f"policy_number already exists: {policy_number}")

    modified = calc.modified_premium(manual_premium_cents, emp["current_emr"])
    pol = {
        "employer_id": employer_id,
        "policy_number": policy_number,
        "manual_premium_cents": manual_premium_cents,
        "effective_date": body["effective_date"],
        "expiration_date": body["expiration_date"],
        "modified_premium_cents": modified,
    }
    db.stamp_common(pol)
    db.policies[pol["id"]] = pol
    return ok_object(pol, 201)


@bp.get("/policies/<rid>")
def get_policy_route(rid):
    require_auth(["PlatformAdmin", "ClaimsAdjuster", "Employer"])()
    pol = get_policy(rid)
    assert_employer_owns_employer(pol["employer_id"])
    return ok_object(pol, 200)
