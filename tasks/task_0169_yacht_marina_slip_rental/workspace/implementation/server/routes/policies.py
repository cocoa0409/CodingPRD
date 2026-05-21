"""Insurance policy routes."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..clock import iso_format
from ..common import bump, get_json_body, positive_int, require_fields, stamp_new
from ..errors import ApiError
from ..marina_helpers import (
    enforce_boater_owns,
    get_boater,
    get_marina,
    get_policy,
    parse_required_iso,
)
from ..response import respond
from ..serializers import policy_view
from ..store import store


bp = Blueprint("policies", __name__, url_prefix="/marinas")


@bp.post("/<marina_id>/boaters/<boater_id>/policies")
@require_auth("Boater", "DockMaster")
def create_policy(marina_id: str, boater_id: str):
    body = get_json_body()
    require_fields(body, "carrier", "liability_limit_cents", "effective_date", "expiration_date")
    liability = positive_int(body["liability_limit_cents"], "liability_limit_cents", allow_zero=True)
    eff = parse_required_iso(body, "effective_date")
    exp = parse_required_iso(body, "expiration_date")
    if not (exp > eff):
        raise ApiError("ERR_BAD_REQUEST", "expiration_date must be after effective_date")
    with store.lock:
        get_marina(marina_id)
        boater = get_boater(marina_id, boater_id)
        enforce_boater_owns(boater_id)
        policy = {
            "marina_id": marina_id,
            "boater_id": boater["id"],
            "carrier": body["carrier"],
            "liability_limit_cents": liability,
            "effective_date": iso_format(eff),
            "expiration_date": iso_format(exp),
            "status": "ACTIVE",
        }
        stamp_new(policy)
        store.policies[policy["id"]] = policy
    return respond(policy_view(policy), 201)


@bp.get("/<marina_id>/policies/<policy_id>")
@require_auth("Boater", "DockMaster", "BillingClerk")
def fetch_policy(marina_id: str, policy_id: str):
    with store.lock:
        get_marina(marina_id)
        policy = get_policy(marina_id, policy_id)
        if g.user_role == "Boater":
            enforce_boater_owns(policy["boater_id"])
        return respond(policy_view(policy), 200)


@bp.post("/<marina_id>/policies/<policy_id>/cancel")
@require_auth("Boater", "DockMaster")
def cancel_policy(marina_id: str, policy_id: str):
    with store.lock:
        get_marina(marina_id)
        policy = get_policy(marina_id, policy_id)
        if g.user_role == "Boater":
            enforce_boater_owns(policy["boater_id"])
        if policy.get("status") != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Policy is not ACTIVE")
        # Block if any referencing reservation is APPROVED or CHECKED_IN
        for r in store.reservations.values():
            if r.get("insurance_policy_id") == policy["id"] and r.get("status") in (
                "APPROVED",
                "CHECKED_IN",
            ):
                raise ApiError(
                    "ERR_HAS_DEPENDENCIES",
                    "Policy is referenced by an active reservation",
                )
        policy["status"] = "CANCELLED"
        bump(policy)
        return respond(policy_view(policy), 200)
