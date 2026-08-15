from flask import Blueprint, request

from db import store
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_POLICY_NOT_FOUND, ERR_DUPLICATE_JURISDICTION,
)
from middleware import require_roles
from response import success_object
from services.calc import compute_effective_cap_bps
from services.common import new_entity, touch

bp = Blueprint("policies", __name__)

REQUIRED_INT_FIELDS = [
    "base_cap_bps", "cpi_adjustment_bps", "hard_ceiling_bps",
    "high_increase_threshold_bps", "notice_days_low", "notice_days_high",
    "non_renewal_notice_days",
]
PATCH_FIELDS = REQUIRED_INT_FIELDS


def _serialize(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "jurisdiction_code": p["jurisdiction_code"],
        "base_cap_bps": p["base_cap_bps"],
        "cpi_adjustment_bps": p["cpi_adjustment_bps"],
        "hard_ceiling_bps": p["hard_ceiling_bps"],
        "high_increase_threshold_bps": p["high_increase_threshold_bps"],
        "notice_days_low": p["notice_days_low"],
        "notice_days_high": p["notice_days_high"],
        "non_renewal_notice_days": p["non_renewal_notice_days"],
        "effective_cap_bps": p["effective_cap_bps"],
    }


@bp.route("/rent-cap-policies", methods=["POST"])
def create_policy():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    jurisdiction_code = body.get("jurisdiction_code")
    if not jurisdiction_code or not isinstance(jurisdiction_code, str):
        raise_err(ERR_INVALID_REQUEST, "jurisdiction_code required")
    values = {}
    for f in REQUIRED_INT_FIELDS:
        v = body.get(f)
        if v is None or not isinstance(v, int) or isinstance(v, bool):
            raise_err(ERR_INVALID_REQUEST, f"{f} required int")
        values[f] = v
    # Non-negativity
    if values["base_cap_bps"] < 0 or values["cpi_adjustment_bps"] < 0:
        raise_err(ERR_INVALID_REQUEST, "cap components must be >= 0")
    # Uniqueness
    for p in store.rent_cap_policies.values():
        if p["jurisdiction_code"] == jurisdiction_code:
            raise_err(ERR_DUPLICATE_JURISDICTION, "jurisdiction_code already exists")
    rec = new_entity()
    rec.update(values)
    rec["jurisdiction_code"] = jurisdiction_code
    rec["effective_cap_bps"] = compute_effective_cap_bps(rec)
    store.rent_cap_policies[rec["id"]] = rec
    return success_object(_serialize(rec), status_code=201)


@bp.route("/rent-cap-policies/<pid>", methods=["GET"])
def get_policy(pid):
    require_roles("PlatformAdmin", "RegionalDirector", "PropertyManager", "LeasingAgent")
    p = store.rent_cap_policies.get(pid)
    if p is None:
        raise_err(ERR_POLICY_NOT_FOUND, "policy not found")
    return success_object(_serialize(p))


@bp.route("/rent-cap-policies/<pid>", methods=["PATCH"])
def patch_policy(pid):
    require_roles("PlatformAdmin")
    p = store.rent_cap_policies.get(pid)
    if p is None:
        raise_err(ERR_POLICY_NOT_FOUND, "policy not found")
    body = request.get_json(silent=True) or {}
    for f in PATCH_FIELDS:
        if f in body:
            v = body[f]
            if not isinstance(v, int) or isinstance(v, bool):
                raise_err(ERR_INVALID_REQUEST, f"{f} must be int")
            p[f] = v
    p["effective_cap_bps"] = compute_effective_cap_bps(p)
    touch(p)
    return success_object(_serialize(p))
