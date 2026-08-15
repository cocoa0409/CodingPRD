"""Season endpoints: create, get, open (creates MemberQuota rows per ACTIVE member)."""
from flask import Blueprint

from db import store, new_common, touch
from errors import ApiError
from middleware import authenticate, require_roles, ANY_ROLE
from response import ok, created
from services import quota as quota_service
from validation import get_body, req_int, req_date, req_number

bp = Blueprint("seasons", __name__)


def get_season_or_404(season_id):
    season = store.seasons.get(season_id)
    if season is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Season not found")
    return season


@bp.post("/coop/seasons")
def create_season():
    body = get_body()
    year = req_int(body, "year")
    window_start = req_date(body, "harvest_window_start")
    window_end = req_date(body, "harvest_window_end")
    baseline = req_number(body, "baseline_barrels_per_acre")
    if window_end < window_start:
        raise ApiError("ERR_VALIDATION", 400,
                       "harvest_window_end must be >= harvest_window_start")

    _, role = authenticate()
    require_roles(role, {"CoopAdmin"})

    if any(s["year"] == year for s in store.seasons.values()):
        raise ApiError("ERR_DUPLICATE_SEASON_YEAR", 409,
                       "A season with the same year already exists")

    season = new_common({
        "year": year,
        "harvest_window_start": window_start.isoformat(),
        "harvest_window_end": window_end.isoformat(),
        "baseline_barrels_per_acre": baseline,
        "status": "SETUP",
        "_window_start_date": window_start,
        "_window_end_date": window_end,
    })
    store.seasons[season["id"]] = season
    return created(season)


@bp.get("/coop/seasons/<season_id>")
def get_season(season_id):
    _, role = authenticate()
    require_roles(role, ANY_ROLE)
    return ok(get_season_or_404(season_id))


@bp.post("/coop/seasons/<season_id>/open")
def open_season(season_id):
    _, role = authenticate()
    require_roles(role, {"CoopAdmin"})
    season = get_season_or_404(season_id)

    if season["status"] != "SETUP":
        raise ApiError("ERR_INVALID_STATE", 409, "Season is not in SETUP")
    active_members = sorted(
        (m for m in store.members.values() if m["status"] == "ACTIVE"),
        key=lambda m: (m["created_at"], m.get("_seq", 0)),
    )
    if not active_members:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "At least one ACTIVE member is required to open a season")

    season["status"] = "OPEN"
    touch(season)

    for member in active_members:
        baseline, approved_total = quota_service.compute_quota_values(member["id"], season)
        quota = new_common({
            "member_id": member["id"],
            "season_id": season["id"],
            "base_quota_barrels": approved_total,
            "baseline_quota_barrels": baseline,
            "base_quota_override": None,
            "delivered_barrels": 0,
            "over_quota_barrels": 0,
            "posture": "WITHIN_QUOTA",
            "quota_locked": False,
        })
        store.quotas[quota["id"]] = quota

    return ok(season)
