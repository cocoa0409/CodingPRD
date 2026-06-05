"""Slip routes (scaffold §1.5 — Slips block; PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services.validation import (
    lookup_or_404,
    require_bool,
    require_enum,
    require_fields,
    require_int,
    require_number,
    require_string,
)


bp = Blueprint("slips", __name__)

POWER_AMP_VALUES = {"NONE", "A30", "A50", "A100"}
SLIP_STATUSES = {"AVAILABLE", "RESERVED", "OCCUPIED", "OUT_OF_SERVICE"}


@bp.post("/marinas/<mid>/slips")
def create_slip(mid: str):
    require_auth(["HarborMaster"])()
    marina = lookup_or_404(db.marinas, mid, "Marina")
    body = get_json_body()
    require_fields(
        body,
        ["slip_number", "length_ft", "beam_ft", "power_amp", "base_daily_rate_cents"],
    )
    slip_number = require_string(body["slip_number"], "slip_number", max_len=60)
    length_ft = require_number(body["length_ft"], "length_ft", strict_min=0.0)
    beam_ft = require_number(body["beam_ft"], "beam_ft", strict_min=0.0)
    power_amp = require_enum(body["power_amp"], POWER_AMP_VALUES, "power_amp")
    base_daily_rate_cents = require_int(
        body["base_daily_rate_cents"], "base_daily_rate_cents", min_value=0
    )

    pumpout_available_raw = body.get("pumpout_available", False)
    if pumpout_available_raw is None:
        pumpout_available_raw = False
    pumpout_available = require_bool(pumpout_available_raw, "pumpout_available")

    liveaboard_allowed_raw = body.get("liveaboard_allowed", False)
    if liveaboard_allowed_raw is None:
        liveaboard_allowed_raw = False
    liveaboard_allowed = require_bool(liveaboard_allowed_raw, "liveaboard_allowed")

    with db.mutation_lock:
        # slip_number unique within (marina_id).
        for s in db.slips.values():
            if (
                s.get("marina_id") == marina["id"]
                and s.get("slip_number") == slip_number
            ):
                raise APIError(
                    ERR_INVALID_REQUEST,
                    400,
                    "slip_number already in use within marina",
                )
        slip = {
            "marina_id": marina["id"],
            "slip_number": slip_number,
            "length_ft": length_ft,
            "beam_ft": beam_ft,
            "power_amp": power_amp,
            "pumpout_available": pumpout_available,
            "liveaboard_allowed": liveaboard_allowed,
            "base_daily_rate_cents": base_daily_rate_cents,
            "status": "AVAILABLE",
        }
        db.stamp_common(slip)
        db.slips[slip["id"]] = slip
        return ok_object(slip, 201)


@bp.get("/slips")
def list_slips():
    require_auth(["HarborMaster", "MarinaStaff", "Tenant"])()
    limit, offset = paginate_params(request.args)
    items = list(db.slips.values())
    if "marina_id" in request.args:
        items = [s for s in items if s.get("marina_id") == request.args["marina_id"]]
    if "status" in request.args:
        items = [s for s in items if s.get("status") == request.args["status"]]
    items.sort(key=db.created_then_id)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.get("/slips/<sid>")
def get_slip(sid: str):
    require_auth(["HarborMaster", "MarinaStaff", "Tenant"])()
    slip = lookup_or_404(db.slips, sid, "Slip")
    return ok_object(slip, 200)


@bp.post("/slips/<sid>/decommission")
def decommission_slip(sid: str):
    require_auth(["HarborMaster"])()
    slip = lookup_or_404(db.slips, sid, "Slip")
    with db.mutation_lock:
        if slip.get("status") != "AVAILABLE":
            raise APIError(
                ERR_INVALID_STATE,
                409,
                "Slip must be AVAILABLE to decommission",
            )
        # No RESERVED or ACTIVE lease on this slip.
        for lease in db.leases.values():
            if lease.get("slip_id") == slip["id"] and lease.get("status") in (
                "RESERVED",
                "ACTIVE",
            ):
                raise APIError(
                    ERR_INVALID_STATE,
                    409,
                    "Slip has an open lease; cannot decommission",
                )
        slip["status"] = "OUT_OF_SERVICE"
        db.bump(slip)
        return ok_object(slip, 200)
