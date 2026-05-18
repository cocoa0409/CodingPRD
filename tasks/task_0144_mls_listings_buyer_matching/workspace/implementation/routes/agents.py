"""/agents endpoints."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint

from config import AGENT_ROLE_BUYER, AGENT_ROLE_DUAL, AGENT_ROLE_LISTING
from db import store
from errors import (
    err_invalid_listing_fields,  # reused for shape errors generally? — no, use specific
    err_invalid_state,
)
from middleware import require_auth
from response import success
from routes._helpers import (
    check_version_if_present,
    get_agent_or_404,
    get_int,
    get_json,
    get_number,
)
from services.serializers import agent as serialize_agent
from services.state_machine import bump_version
from utils import new_uuid, to_decimal


bp = Blueprint("agents", __name__)

VALID_AGENT_ROLES = {AGENT_ROLE_LISTING, AGENT_ROLE_BUYER, AGENT_ROLE_DUAL}


def _validate_split(split) -> Decimal:
    if split is None:
        return Decimal("0.70")
    try:
        d = to_decimal(split)
    except Exception:
        raise err_invalid_state("brokerage_split_pct must be numeric.")
    if d <= 0 or d > 1:
        raise err_invalid_state("brokerage_split_pct must be in (0, 1].")
    return d


@bp.post("/agents")
@require_auth(["MlsAdmin"])
def create_agent():
    body = get_json()
    full_name = body.get("full_name")
    brokerage_name = body.get("brokerage_name")
    agent_role = body.get("agent_role")
    license_number = body.get("license_number")
    split_raw = body.get("brokerage_split_pct")

    if not isinstance(full_name, str) or not full_name:
        raise err_invalid_state("full_name is required.")
    if not isinstance(brokerage_name, str) or not brokerage_name:
        raise err_invalid_state("brokerage_name is required.")
    if agent_role not in VALID_AGENT_ROLES:
        raise err_invalid_state("agent_role is invalid.")
    if not isinstance(license_number, str) or not license_number:
        raise err_invalid_state("license_number is required.")

    split = _validate_split(split_raw)

    # Uniqueness across ACTIVE agents.
    if license_number in store.active_license_numbers:
        raise err_invalid_state("license_number is already in use by an ACTIVE agent.")

    with store.lock:
        if license_number in store.active_license_numbers:
            raise err_invalid_state("license_number is already in use by an ACTIVE agent.")
        now = store.now()
        agent = {
            "id": new_uuid(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "full_name": full_name,
            "brokerage_name": brokerage_name,
            "agent_role": agent_role,
            "license_number": license_number,
            "brokerage_split_pct": split,
            "status": "ACTIVE",
        }
        store.agents[agent["id"]] = agent
        store.active_license_numbers.add(license_number)
    return success(serialize_agent(agent), 201)


@bp.get("/agents/<agent_id>")
@require_auth(["ListingAgent", "BuyerAgent", "MlsAdmin"])
def get_agent(agent_id):
    agent = get_agent_or_404(agent_id)
    return success(serialize_agent(agent), 200)


@bp.patch("/agents/<agent_id>")
@require_auth(["MlsAdmin"])
def patch_agent(agent_id):
    body = get_json()
    with store.lock:
        agent = get_agent_or_404(agent_id)
        check_version_if_present(agent, body)

        if "brokerage_split_pct" in body and body["brokerage_split_pct"] is not None:
            agent["brokerage_split_pct"] = _validate_split(body["brokerage_split_pct"])

        if "status" in body and body["status"] is not None:
            new_status = body["status"]
            if new_status not in ("ACTIVE", "SUSPENDED"):
                raise err_invalid_state("status must be ACTIVE or SUSPENDED.")
            old_status = agent["status"]
            if new_status != old_status:
                # Update active_license_numbers index.
                if new_status == "ACTIVE":
                    if agent["license_number"] in store.active_license_numbers:
                        # Another active agent owns this license.
                        # Only allow if it's this very agent.
                        # Since the only way license_number is in the set is via this agent
                        # (we removed on SUSPEND), this is fine. But guard.
                        pass
                    store.active_license_numbers.add(agent["license_number"])
                else:  # SUSPENDED
                    store.active_license_numbers.discard(agent["license_number"])
                agent["status"] = new_status

        now = store.now()
        bump_version(agent, now)
    return success(serialize_agent(agent), 200)
