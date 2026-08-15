"""Provider and ProviderAbrasionProfile endpoints."""

from flask import Blueprint, request

import db
from errors import raise_err
from middleware import (
    get_body,
    pagination_params,
    require_auth,
    require_role,
    validate_body,
)
from response import success_list, success_object
from serializers import serialize

bp = Blueprint("providers", __name__)

PREFIX = "/payment-integrity"


@bp.route(PREFIX + "/providers", methods=["POST"])
def create_provider():
    user_id, role = require_auth()
    require_role(role, ["PlanAdmin"])
    body = get_body()
    vals = validate_body(
        body,
        {
            "npi": (True, "string", None),
            "name": (True, "string", None),
            "status": (False, "string", {"ACTIVE", "TERMINATED"}),
        },
    )
    provider = db.create_resource(
        "providers",
        {
            "npi": vals["npi"],
            "name": vals["name"],
            "status": vals.get("status", "ACTIVE"),
        },
    )
    # Side effect: auto-create the abrasion profile, one-to-one, zeroed
    db.create_resource(
        "abrasion_profiles",
        {
            "provider_id": provider["id"],
            "confirmed_count": 0,
            "overridden_count": 0,
            "fp_count": 0,
            "superseded_count": 0,
            "denied_cents_lifetime": 0,
            "released_cents_lifetime": 0,
            "open_ibr_count": 0,
            "standard_index": 0,
            "regulatory_index": 0,
            "tier": "LOW",
            "monitor_only": False,
        },
    )
    return success_object(serialize(provider), status=201)


@bp.route(PREFIX + "/providers", methods=["GET"])
def list_providers():
    require_auth()
    limit, offset = pagination_params()
    status_filter = request.args.get("status")
    rows = db.all_records("providers")
    if status_filter is not None:
        if status_filter not in ("ACTIVE", "TERMINATED"):
            raise_err("ERR_INVALID_ENUM", "status filter carries undeclared member")
        rows = [r for r in rows if r["status"] == status_filter]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    page = rows[offset : offset + limit]
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.route(PREFIX + "/providers/<pid>", methods=["GET"])
def get_provider(pid):
    require_auth()
    provider = db.get("providers", pid)
    if provider is None:
        raise_err("ERR_PROVIDER_NOT_FOUND", "Provider not found")
    return success_object(serialize(provider))


@bp.route(PREFIX + "/providers/<pid>", methods=["PATCH"])
def patch_provider(pid):
    user_id, role = require_auth()
    require_role(role, ["PlanAdmin"])
    body = get_body()
    vals = validate_body(body, {"status": (True, "string", {"ACTIVE", "TERMINATED"})})
    provider = db.get("providers", pid)
    if provider is None:
        raise_err("ERR_PROVIDER_NOT_FOUND", "Provider not found")
    provider["status"] = vals["status"]
    db.touch(provider)
    return success_object(serialize(provider))


@bp.route(PREFIX + "/abrasion-profiles", methods=["GET"])
def list_abrasion_profiles():
    require_auth()
    limit, offset = pagination_params()
    provider_filter = request.args.get("provider_id")
    rows = db.all_records("abrasion_profiles")
    if provider_filter is not None:
        rows = [r for r in rows if r["provider_id"] == provider_filter]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    page = rows[offset : offset + limit]
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.route(PREFIX + "/abrasion-profiles/<pid>", methods=["GET"])
def get_abrasion_profile(pid):
    require_auth()
    profile = db.get("abrasion_profiles", pid)
    if profile is None:
        raise_err("ERR_PROVIDER_NOT_FOUND", "Abrasion profile not found")
    return success_object(serialize(profile))
