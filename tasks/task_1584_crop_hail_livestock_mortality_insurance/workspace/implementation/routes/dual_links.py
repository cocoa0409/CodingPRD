"""Dual coverage link endpoints (PRD 3.3)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_NOT_FOUND, ERR_DUAL_COVERAGE_MISMATCH
from middleware import require_roles
from response import success_object, success_list
from routes.common import resolve_carrier, resolve_policy
from serializers import dual_link_view
from services import core
from util import (
    get_json_body, reject_unknown_fields, require_string,
    parse_pagination, paginate, sort_created,
)

bp = Blueprint("dual_links", __name__)

LIST_ROLES = ("PlatformAdmin", "Underwriter", "ClaimsApprover")

CREATE_FIELDS = {"federal_crop_policy_id"}


@bp.route("/carriers/<carrierId>/policies/<policyId>/dual-coverage-links",
          methods=["POST"])
@require_roles("Underwriter")
def create_dual_link(carrierId: str, policyId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    federal_crop_policy_id = require_string(body, "federal_crop_policy_id")

    fed = db.federal_policies.get(federal_crop_policy_id)
    if fed is None or fed["carrier_id"] != carrier["id"]:
        raise_err(ERR_NOT_FOUND, f"FederalCropPolicy not found: {federal_crop_policy_id}")

    # The federal policy must be ACTIVE, and its crop/county must match the
    # private policy's coverage units (PRD 3.3).
    matches = any(
        u["unit_kind"] == "CROP_HAIL"
        and u["crop_code"] == fed["crop_code"]
        and u["county_code"] == fed["county_code"]
        for u in core.units_of_policy(policy["id"])
    )
    if fed["status"] != "ACTIVE" or not matches:
        raise_err(ERR_DUAL_COVERAGE_MISMATCH,
                  "Federal policy not ACTIVE or crop/county mismatch at link time")

    now = carrier["current_utc"]
    link = db.stamp_new({
        "policy_id": policy["id"],
        "federal_crop_policy_id": fed["id"],
        "offset_pct_of_federal_liability": 20,
        "established_at": now,
    }, now)
    db.dual_links[link["id"]] = link

    policy["dual_coverage_link_id"] = link["id"]
    db.touch(policy, now)
    return success_object(dual_link_view(link), 201)


@bp.route("/carriers/<carrierId>/policies/<policyId>/dual-coverage-links",
          methods=["GET"])
@require_roles(*LIST_ROLES)
def list_dual_links(carrierId: str, policyId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    items = [l for l in db.dual_links.values() if l["policy_id"] == policy["id"]]
    items = sort_created(items)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([dual_link_view(l) for l in page], limit, offset, total)
