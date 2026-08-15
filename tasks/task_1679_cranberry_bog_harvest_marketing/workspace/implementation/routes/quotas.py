"""MemberQuota endpoints: get, list, OCC-guarded manual override PATCH."""
from flask import Blueprint

from db import store, touch
from errors import ApiError
from middleware import authenticate, require_roles, ANY_ROLE
from response import ok, paginate
from services import quota as quota_service
from validation import (get_body, has_field, is_number, to_decimal, req_int,
                        round2)

bp = Blueprint("quotas", __name__)


def get_quota_or_404(quota_id):
    quota = store.quotas.get(quota_id)
    if quota is None:
        raise ApiError("ERR_NOT_FOUND", 404, "MemberQuota not found")
    return quota


@bp.get("/coop/quotas/<quota_id>")
def get_quota(quota_id):
    _, role = authenticate()
    require_roles(role, ANY_ROLE)
    return ok(get_quota_or_404(quota_id))


@bp.get("/coop/quotas")
def list_quotas():
    _, role = authenticate()
    require_roles(role, ANY_ROLE)
    rows = list(store.quotas.values())
    rows = paginate.filter(rows, "member_id")
    rows = paginate.filter(rows, "season_id")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.patch("/coop/quotas/<quota_id>")
def patch_quota(quota_id):
    body = get_body()
    # Shape: base_quota_barrels present (number >= 0, or null to clear the
    # override); expected_quota_version required integer.
    if not has_field(body, "base_quota_barrels"):
        raise ApiError("ERR_VALIDATION", 400, "Field 'base_quota_barrels' is required")
    raw_value = body["base_quota_barrels"]
    if raw_value is not None:
        if not is_number(raw_value):
            raise ApiError("ERR_VALIDATION", 400, "Field 'base_quota_barrels' must be a number")
        value = to_decimal(raw_value)
        if value < 0:
            raise ApiError("ERR_VALIDATION", 400, "Field 'base_quota_barrels' must be non-negative")
    else:
        value = None
    expected_version = req_int(body, "expected_quota_version")

    _, role = authenticate()
    require_roles(role, {"CoopAdmin"})

    quota = get_quota_or_404(quota_id)

    # Optimistic concurrency (band 5) is checked before the quota lock (band 9).
    if expected_version != quota["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_quota_version does not match the quota's current version")
    if quota["quota_locked"]:
        raise ApiError("ERR_QUOTA_LOCKED", 409,
                       "Quota is locked because the season has reached HARVEST_CLOSED")

    if value is None:
        quota["base_quota_override"] = None
        season = store.seasons.get(quota["season_id"])
        if season is not None:
            _, approved_total = quota_service.compute_quota_values(quota["member_id"], season)
            quota["base_quota_barrels"] = approved_total
    else:
        quota["base_quota_override"] = value
        quota["base_quota_barrels"] = round2(value)
    quota["posture"] = quota_service.posture_of(quota)
    touch(quota)
    return ok(quota)
