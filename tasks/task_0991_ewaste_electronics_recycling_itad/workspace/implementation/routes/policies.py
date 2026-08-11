"""CompliancePolicy endpoints (PRD §2.11, §3.2)."""

from decimal import Decimal

from flask import Blueprint

import db
import serialize
import utils
from errors import ApiError, ERR_VALIDATION
from middleware import require_roles
from response import ok_object, paginate, sort_created
from services import calculations as calc

bp = Blueprint("policies", __name__)

STANDARDS = {"R2", "E_STEWARDS"}


def _weight(data, name):
    d = utils.req_number(data, name)
    if d < 0 or d > 1:
        raise ApiError(ERR_VALIDATION, 400, f"{name} must be between 0 and 1")
    return float(d)


@bp.post("/itad/compliance-policies")
def create_policy():
    uid, role = require_roles("PlatformAdmin")
    data = utils.body_json()
    standard = utils.req_enum(data, "standard", STANDARDS)
    methods = utils.req_enum_list(data, "sanitization_methods_allowed", calc.SANITIZATION_METHODS)
    export_allowed = utils.req_bool(data, "export_allowed")
    resale_requires = utils.req_bool(data, "resale_requires_verified_sanitization")
    is_active = utils.opt_bool(data, "is_active", default=False)
    w_cert = _weight(data, "weight_cert_freshness")
    w_volume = _weight(data, "weight_volume")
    w_viol = _weight(data, "weight_violations")
    policy = {
        "id": utils.new_id(),
        "standard": standard,
        "sanitization_methods_allowed": methods,
        "export_allowed": export_allowed,
        "resale_requires_verified_sanitization": resale_requires,
        "is_active": bool(is_active),
        "weight_cert_freshness": w_cert,
        "weight_volume": w_volume,
        "weight_violations": w_viol,
    }
    utils.stamp_new(policy)
    db.policies[policy["id"]] = policy
    if policy["is_active"]:
        # Exactly one active policy platform-wide (PRD §2.11).
        for other in db.policies.values():
            if other["id"] != policy["id"] and other["is_active"]:
                other["is_active"] = False
                utils.touch(other)
    return ok_object(serialize.policy(policy), code=201)


@bp.get("/itad/compliance-policies")
def list_policies():
    uid, role = require_roles("PlatformAdmin", "ComplianceOfficer")
    records = sort_created(list(db.policies.values()))
    return paginate([serialize.policy(p) for p in records])
