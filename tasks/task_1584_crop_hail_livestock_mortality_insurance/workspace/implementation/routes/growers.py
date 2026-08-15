"""Grower registry endpoints (PRD 3.1, 3.9): registration, reads, debarment."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import require_roles
from response import success_object, success_list
from routes.common import resolve_carrier, resolve_grower
from serializers import grower_view
from util import (
    get_json_body, reject_unknown_fields, require_string,
    parse_pagination, paginate, sort_created, query_arg,
)

bp = Blueprint("growers", __name__)

ALL_ROLES = ("PlatformAdmin", "Underwriter", "Policyholder", "Adjuster", "ClaimsApprover")
LIST_ROLES = ("PlatformAdmin", "Underwriter", "ClaimsApprover")

CREATE_FIELDS = {"full_name", "tax_id_last4", "email", "county_code", "state_code"}


@bp.route("/carriers/<carrierId>/growers", methods=["POST"])
@require_roles("Underwriter")
def create_grower(carrierId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    full_name = require_string(body, "full_name")
    tax_id_last4 = require_string(body, "tax_id_last4")
    if len(tax_id_last4) != 4:
        raise_err(ERR_INVALID_REQUEST, "tax_id_last4 must be the last four digits")
    email = require_string(body, "email")
    county_code = require_string(body, "county_code")
    if len(county_code) != 5:
        raise_err(ERR_INVALID_REQUEST, "county_code must be a five-character FIPS code")
    state_code = require_string(body, "state_code")
    if len(state_code) != 2:
        raise_err(ERR_INVALID_REQUEST, "state_code must be a two-letter code")

    grower = db.stamp_new({
        "carrier_id": carrier["id"],
        "full_name": full_name,
        "tax_id_last4": tax_id_last4,
        "email": email,
        "county_code": county_code,
        "state_code": state_code,
        "continuous_coverage_since": None,
        "prior_claims_count": 0,
        "status": "ACTIVE",
    }, carrier["current_utc"])
    db.growers[grower["id"]] = grower
    return success_object(grower_view(grower), 201)


@bp.route("/carriers/<carrierId>/growers", methods=["GET"])
@require_roles(*LIST_ROLES)
def list_growers(carrierId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    items = [g for g in db.growers.values() if g["carrier_id"] == carrier["id"]]
    status = query_arg("status")
    if status is not None:
        items = [g for g in items if g["status"] == status]
    items = sort_created(items)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([grower_view(g) for g in page], limit, offset, total)


@bp.route("/carriers/<carrierId>/growers/<growerId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_grower(carrierId: str, growerId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    grower = resolve_grower(carrier["id"], growerId)
    return success_object(grower_view(grower))


@bp.route("/carriers/<carrierId>/growers/<growerId>/debar", methods=["POST"])
@require_roles("Underwriter")
def debar_grower(carrierId: str, growerId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    grower = resolve_grower(carrier["id"], growerId)
    body = get_json_body()
    reject_unknown_fields(body, set())

    if grower["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err(ERR_INVALID_STATE,
                  "Only an ACTIVE or SUSPENDED grower can be debarred")

    now = carrier["current_utc"]
    grower["status"] = "DEBARRED"
    db.touch(grower, now)

    # Cascade: every BOUND/ACTIVE policy of the grower is cancelled.
    grower_policy_ids = {
        p["id"] for p in db.policies.values() if p["grower_id"] == grower["id"]
    }
    for policy in sorted(db.policies.values(), key=lambda p: p["_seq"]):
        if policy["grower_id"] != grower["id"]:
            continue
        if policy["lifecycle_state"] in ("BOUND", "ACTIVE"):
            policy["lifecycle_state"] = "CANCELLED"
            policy["premium_reserve_cents"] = 0
            db.touch(policy, now)

    # Cascade: every REPORTED/INSPECTION_SCHEDULED claim of the grower is
    # withdrawn and its coverage unit released.
    for claim in sorted(db.claims.values(), key=lambda c: c["_seq"]):
        if claim["policy_id"] not in grower_policy_ids:
            continue
        if claim["claim_state"] in ("REPORTED", "INSPECTION_SCHEDULED"):
            claim["claim_state"] = "WITHDRAWN"
            db.touch(claim, now)
            unit = db.coverage_units.get(claim["coverage_unit_id"])
            if unit is not None and unit["status"] == "UNDER_CLAIM":
                unit["status"] = "REPORTED"
                db.touch(unit, now)

    return success_object(grower_view(grower))
