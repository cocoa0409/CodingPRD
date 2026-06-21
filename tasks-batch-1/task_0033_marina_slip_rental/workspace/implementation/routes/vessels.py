"""Vessel routes (scaffold §1.5 — Vessels block; PRD §3.2)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from middleware import get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services.validation import (
    lookup_or_404,
    require_date,
    require_fields,
    require_int,
    require_number,
    require_string,
)


bp = Blueprint("vessels", __name__)


@bp.post("/vessels")
def create_vessel():
    require_auth(["Tenant", "MarinaStaff", "HarborMaster"])()
    body = get_json_body()
    require_fields(
        body,
        [
            "tenant_id",
            "name",
            "loa_ft",
            "beam_ft",
            "insurance_policy_number",
            "insurance_expires_on",
            "insurance_coverage_cents",
        ],
    )
    tenant = lookup_or_404(db.tenants, body["tenant_id"], "Tenant")
    name = require_string(body["name"], "name", max_len=200)
    loa_ft = require_number(body["loa_ft"], "loa_ft", strict_min=0.0)
    beam_ft = require_number(body["beam_ft"], "beam_ft", strict_min=0.0)
    insurance_policy_number = require_string(
        body["insurance_policy_number"], "insurance_policy_number", max_len=120
    )
    insurance_expires_on = require_date(
        body["insurance_expires_on"], "insurance_expires_on"
    )
    insurance_coverage_cents = require_int(
        body["insurance_coverage_cents"], "insurance_coverage_cents", min_value=0
    )

    with db.mutation_lock:
        vessel = {
            "tenant_id": tenant["id"],
            "name": name,
            "loa_ft": loa_ft,
            "beam_ft": beam_ft,
            "insurance_policy_number": insurance_policy_number,
            "insurance_expires_on": insurance_expires_on.isoformat(),
            "insurance_coverage_cents": insurance_coverage_cents,
        }
        db.stamp_common(vessel)
        db.vessels[vessel["id"]] = vessel
        return ok_object(vessel, 201)


@bp.get("/vessels")
def list_vessels():
    require_auth(["HarborMaster", "MarinaStaff", "Tenant"])()
    limit, offset = paginate_params(request.args)
    items = list(db.vessels.values())
    if "tenant_id" in request.args:
        items = [v for v in items if v.get("tenant_id") == request.args["tenant_id"]]
    items.sort(key=db.created_then_id)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.get("/vessels/<vid>")
def get_vessel(vid: str):
    require_auth(["HarborMaster", "MarinaStaff", "Tenant"])()
    vessel = lookup_or_404(db.vessels, vid, "Vessel")
    return ok_object(vessel, 200)
