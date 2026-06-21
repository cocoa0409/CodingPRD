"""Marina routes (scaffold §1.5 — Marinas block; PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services.validation import (
    lookup_or_404,
    require_fields,
    require_harbor_code,
    require_int,
    require_mmdd,
    require_number,
    require_string,
)


bp = Blueprint("marinas", __name__)


@bp.post("/marinas")
def create_marina():
    require_auth(["HarborMaster"])()
    body = get_json_body()
    require_fields(body, ["name", "harbor_code", "liveaboard_cap"])
    name = require_string(body["name"], "name", max_len=200)
    harbor_code = require_harbor_code(body["harbor_code"], "harbor_code")
    liveaboard_cap = require_int(body["liveaboard_cap"], "liveaboard_cap", min_value=0)

    # Optional MM-DD season window — defaults per PRD §3.1.
    summer_start_str = body.get("season_summer_start") or "05-01"
    summer_end_str = body.get("season_summer_end") or "09-30"
    summer_start = require_mmdd(summer_start_str, "season_summer_start")
    summer_end = require_mmdd(summer_end_str, "season_summer_end")
    if not (summer_end > summer_start):
        raise APIError(
            ERR_INVALID_REQUEST,
            400,
            "season_summer_end must be after season_summer_start",
        )

    tow_radius_raw = body.get("tow_assist_radius_nm")
    if tow_radius_raw is None:
        tow_assist_radius_nm = 25.0
    else:
        tow_assist_radius_nm = require_number(
            tow_radius_raw, "tow_assist_radius_nm", min_value=0.0
        )

    with db.mutation_lock:
        # harbor_code must be globally unique.
        for m in db.marinas.values():
            if m.get("harbor_code") == harbor_code:
                raise APIError(
                    ERR_INVALID_REQUEST, 400, "harbor_code already in use"
                )
        marina = {
            "name": name,
            "harbor_code": harbor_code,
            "liveaboard_cap": liveaboard_cap,
            "liveaboard_current_count": 0,
            "season_summer_start": summer_start_str,
            "season_summer_end": summer_end_str,
            "tow_assist_radius_nm": tow_assist_radius_nm,
        }
        db.stamp_common(marina)
        db.marinas[marina["id"]] = marina
        return ok_object(marina, 201)


@bp.get("/marinas")
def list_marinas():
    require_auth(["HarborMaster", "MarinaStaff", "Tenant"])()
    limit, offset = paginate_params(request.args)
    items = list(db.marinas.values())
    items.sort(key=db.created_then_id)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.get("/marinas/<mid>")
def get_marina(mid: str):
    require_auth(["HarborMaster", "MarinaStaff", "Tenant"])()
    marina = lookup_or_404(db.marinas, mid, "Marina")
    return ok_object(marina, 200)
