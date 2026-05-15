"""Region endpoints + manual recompute-risk."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..errors import ApiError
from ..services.calculations import compute_case_density_score
from ..store import common_fields_create, get_store, bump_version
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:
    app.add_url_rule(
        "/epi/regions",
        view_func=require_auth("CDCSupervisor")(with_lock(create_region)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/regions/<region_id>",
        view_func=require_auth(
            "CDCSupervisor", "CDCDispatcher", "CDCTracer", "RiskExpert", "PressOfficer"
        )(with_lock(get_region)),
        methods=["GET"],
    )
    app.add_url_rule(
        "/epi/regions/<region_id>/recompute-risk",
        view_func=require_auth("CDCSupervisor")(with_lock(recompute_risk)),
        methods=["POST"],
    )


def create_region():
    body = get_json_body()
    store = get_store()
    district = body.get("district_code")
    pop = body.get("population")
    if not district:
        raise ApiError("ERR_INVALID_INPUT", "Missing district_code.")
    if pop is None:
        raise ApiError("ERR_INVALID_INPUT", "Missing population.")
    try:
        pop_int = int(pop)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_INPUT", "population must be an integer.")
    if pop_int <= 0:
        raise ApiError("ERR_INVALID_INPUT", "population must be > 0.")
    for r in store.regions.values():
        if r.get("district_code") == district:
            raise ApiError("ERR_INVALID_INPUT", f"district_code {district!r} already exists.")
    row = {
        **common_fields_create(),
        "district_code": district,
        "population": pop_int,
        "current_risk_tier": "LOW",
        "provisional_risk_tier": "LOW",
        "last_tier_decision_id": None,
    }
    store.regions[row["id"]] = row
    return ok(row, status=201)


def get_region(region_id: str):
    store = get_store()
    r = store.regions.get(region_id)
    if not r:
        raise ApiError("ERR_NOT_FOUND", f"Region {region_id} not found.")
    return ok(r)


def recompute_risk(region_id: str):
    store = get_store()
    region = store.regions.get(region_id)
    if not region:
        raise ApiError("ERR_NOT_FOUND", f"Region {region_id} not found.")
    score, tier = compute_case_density_score(region)
    region["provisional_risk_tier"] = tier
    bump_version(region)
    return ok({"region": region, "score": score, "provisional_tier": tier})
