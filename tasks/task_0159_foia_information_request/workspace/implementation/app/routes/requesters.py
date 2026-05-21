"""/foia/requesters — register, fetch, update Requester profiles."""

from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..envelope import ok_object
from ..errors import (
    ApiError,
    ERR_INVALID_INPUT,
    ERR_NOT_FOUND,
    ERR_VERSION_CONFLICT,
)
from ..serializers import serialize_requester
from ..store import store
from ..util import (
    is_valid_email,
    optional_str,
    require_enum,
    require_int,
    require_json_body,
    require_str,
)


requesters_bp = Blueprint("requesters", __name__)

TIERS = ("COMMERCIAL", "EDUCATIONAL_NONCOMMERCIAL", "PUBLIC_INTEREST")


def _validate_tier_justification(tier: str, justification):
    """Per §1.1: tier_justification is nullable only when tier == COMMERCIAL."""

    if tier != "COMMERCIAL":
        if justification is None or justification == "":
            raise ApiError(
                ERR_INVALID_INPUT,
                400,
                "tier_justification is required for non-commercial tiers.",
            )


@requesters_bp.post("/foia/requesters")
@require_auth({"Requester", "Officer"})
def create_requester():
    payload = require_json_body()
    full_name = require_str(payload, "full_name", max_len=200)
    contact_email = require_str(payload, "contact_email", max_len=320)
    if not is_valid_email(contact_email):
        raise ApiError(ERR_INVALID_INPUT, 400, "contact_email is not a valid email address.")
    tier = require_enum(payload, "requester_tier", TIERS)
    justification = optional_str(
        payload, "tier_justification", max_len=1000, allow_empty=False, nullable=True
    )
    _validate_tier_justification(tier, justification)

    entity = {
        "full_name": full_name,
        "contact_email": contact_email,
        "requester_tier": tier,
        "tier_justification": justification,
        "status": "ACTIVE",
    }
    with store.lock:
        store.stamp_create(entity)
        store.requesters[entity["id"]] = entity

    return ok_object(serialize_requester(entity), status=201)


@requesters_bp.get("/foia/requesters/<rid>")
@require_auth({"Requester", "Officer", "AppealAuthority"})
def get_requester(rid: str):
    entity = store.requesters.get(rid)
    if entity is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Requester not found.")
    return ok_object(serialize_requester(entity))


@requesters_bp.patch("/foia/requesters/<rid>")
@require_auth({"Requester", "Officer"})
def update_requester(rid: str):
    payload = require_json_body()
    entity = store.requesters.get(rid)
    if entity is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Requester not found.")

    with store.lock:
        # OCC: only check version when provided.
        if "version" in payload:
            ver = payload.get("version")
            if not isinstance(ver, int) or isinstance(ver, bool):
                raise ApiError(ERR_INVALID_INPUT, 400, "version must be an integer.")
            if ver != entity["version"]:
                raise ApiError(ERR_VERSION_CONFLICT, 409, "Version conflict.")

        new_tier = optional_str(
            payload, "requester_tier", max_len=128, allow_empty=False, nullable=False
        )
        if new_tier is not None and new_tier not in TIERS:
            raise ApiError(
                ERR_INVALID_INPUT, 400, f"requester_tier must be one of {list(TIERS)}"
            )
        new_justification = optional_str(
            payload, "tier_justification", max_len=1000, allow_empty=True, nullable=True
        )
        new_email = optional_str(
            payload, "contact_email", max_len=320, allow_empty=False, nullable=False
        )
        if new_email is not None and not is_valid_email(new_email):
            raise ApiError(ERR_INVALID_INPUT, 400, "contact_email is not a valid email address.")

        tier_after = new_tier if new_tier is not None else entity["requester_tier"]
        justification_after = (
            new_justification if "tier_justification" in payload else entity.get("tier_justification")
        )
        _validate_tier_justification(tier_after, justification_after)

        if new_tier is not None:
            entity["requester_tier"] = new_tier
        if "tier_justification" in payload:
            entity["tier_justification"] = new_justification
        if new_email is not None:
            entity["contact_email"] = new_email
        store.bump(entity)

    return ok_object(serialize_requester(entity))
