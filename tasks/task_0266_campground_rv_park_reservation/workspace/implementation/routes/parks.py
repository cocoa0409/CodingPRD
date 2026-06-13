"""Park, RatePlan, Season, CancellationPolicy endpoints."""
from flask import Blueprint

from db import store, new_id
import errors
from middleware import get_principal, require_role, ROLE_OPERATOR, ROLE_GUEST
from response import success, success_list
from services.common import stamp_common, touch, parse_date
from services import validate as V
from services.listing import pagination, paginate
from services.serializers import (
    serialize_park,
    serialize_rate_plan,
    serialize_season,
    serialize_cancellation_policy,
)

bp = Blueprint("parks", __name__)

SITE_TYPES = {"TENT", "RV", "CABIN"}


def _check_park_config(deposit_pct, tax_rate):
    """deposit_pct and tax_rate must each lie within [0, 1] (PRD §3.1)."""
    if deposit_pct is not None and not (0 <= deposit_pct <= 1):
        raise errors.err(errors.ERR_VALIDATION_FAILED, "deposit_pct must be within [0,1]")
    if tax_rate is not None and not (0 <= tax_rate <= 1):
        raise errors.err(errors.ERR_VALIDATION_FAILED, "tax_rate must be within [0,1]")


# ---------------------------------------------------------------------------
# Park
# ---------------------------------------------------------------------------
@bp.route("/parks", methods=["POST"])
def create_park():
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR})
    body = V.get_json_body()
    V.require_fields(body, ["name"])
    name = V.require_str(body, "name")

    deposit_pct = body.get("deposit_pct", 0.30)
    tax_rate = body.get("tax_rate", 0.08)
    if "deposit_pct" in body and body["deposit_pct"] is not None:
        deposit_pct = V.require_number(body, "deposit_pct")
    if "tax_rate" in body and body["tax_rate"] is not None:
        tax_rate = V.require_number(body, "tax_rate")
    long_stay = body.get("long_stay_nights_threshold", 28)
    if "long_stay_nights_threshold" in body and body["long_stay_nights_threshold"] is not None:
        long_stay = V.require_int(body, "long_stay_nights_threshold")

    _check_park_config(deposit_pct, tax_rate)

    pid = new_id()
    park = {
        "id": pid,
        "name": name,
        "timezone": body.get("timezone") or "America/Denver",
        "check_in_time": body.get("check_in_time") or "15:00",
        "check_out_time": body.get("check_out_time") or "11:00",
        "quiet_hours_start": body.get("quiet_hours_start") or "22:00",
        "quiet_hours_end": body.get("quiet_hours_end") or "07:00",
        "deposit_pct": deposit_pct,
        "tax_rate": tax_rate,
        "long_stay_nights_threshold": long_stay,
    }
    stamp_common(park)
    store.parks[pid] = park
    return success(serialize_park(park), 201)


@bp.route("/parks/<pid>", methods=["GET"])
def get_park(pid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR, ROLE_GUEST})
    park = store.parks.get(pid)
    if park is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Park not found")
    return success(serialize_park(park), 200)


@bp.route("/parks/<pid>", methods=["PATCH"])
def update_park(pid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR})
    park = store.parks.get(pid)
    if park is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Park not found")
    body = V.get_json_body()

    # OCC on park.version via expected_park_version.
    expected = body.get("expected_park_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise errors.err(errors.ERR_INVALID_REQUEST, "expected_park_version must be an integer")
        if expected != park["version"]:
            raise errors.err(errors.ERR_STALE_SITE_VERSION, "Stale park version")

    new_deposit = park["deposit_pct"]
    new_tax = park["tax_rate"]
    if "deposit_pct" in body and body["deposit_pct"] is not None:
        new_deposit = V.require_number(body, "deposit_pct")
    if "tax_rate" in body and body["tax_rate"] is not None:
        new_tax = V.require_number(body, "tax_rate")
    _check_park_config(new_deposit, new_tax)

    for f in ("check_in_time", "check_out_time", "quiet_hours_start", "quiet_hours_end"):
        if f in body and body[f] is not None:
            park[f] = V.require_str(body, f)
    park["deposit_pct"] = new_deposit
    park["tax_rate"] = new_tax
    if "long_stay_nights_threshold" in body and body["long_stay_nights_threshold"] is not None:
        park["long_stay_nights_threshold"] = V.require_int(body, "long_stay_nights_threshold")

    touch(park)
    return success(serialize_park(park), 200)


# ---------------------------------------------------------------------------
# RatePlan
# ---------------------------------------------------------------------------
@bp.route("/parks/<pid>/rate-plans", methods=["POST"])
def create_rate_plan(pid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR})
    park = store.parks.get(pid)
    if park is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Park not found")
    body = V.get_json_body()
    V.require_fields(body, ["site_type", "nightly_rate_cents", "weekly_rate_cents", "monthly_rate_cents"])
    site_type = V.require_enum(body, "site_type", SITE_TYPES)
    nightly = V.require_int(body, "nightly_rate_cents", non_negative=True)
    weekly = V.require_int(body, "weekly_rate_cents", non_negative=True)
    monthly = V.require_int(body, "monthly_rate_cents", non_negative=True)

    rid = new_id()
    rp = {
        "id": rid,
        "park_id": pid,
        "site_type": site_type,
        "nightly_rate_cents": nightly,
        "weekly_rate_cents": weekly,
        "monthly_rate_cents": monthly,
    }
    stamp_common(rp)
    store.rate_plans[rid] = rp
    return success(serialize_rate_plan(rp), 201)


@bp.route("/parks/<pid>/rate-plans", methods=["GET"])
def list_rate_plans(pid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR, ROLE_GUEST})
    park = store.parks.get(pid)
    if park is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Park not found")
    from flask import request

    site_type = request.args.get("site_type")
    items = [r for r in store.rate_plans.values() if r["park_id"] == pid]
    if site_type is not None:
        items = [r for r in items if r["site_type"] == site_type]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_rate_plan(r) for r in page], limit, offset, total)


@bp.route("/rate-plans/<rid>", methods=["GET"])
def get_rate_plan(rid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR, ROLE_GUEST})
    rp = store.rate_plans.get(rid)
    if rp is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Rate plan not found")
    return success(serialize_rate_plan(rp), 200)


# ---------------------------------------------------------------------------
# Season
# ---------------------------------------------------------------------------
@bp.route("/parks/<pid>/seasons", methods=["POST"])
def create_season(pid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR})
    park = store.parks.get(pid)
    if park is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Park not found")
    body = V.get_json_body()
    V.require_fields(body, ["name", "start_date", "end_date", "surcharge_pct"])
    name = V.require_str(body, "name")
    start_s = V.require_str(body, "start_date")
    end_s = V.require_str(body, "end_date")
    start_d = parse_date(start_s)
    end_d = parse_date(end_s)
    surcharge_pct = V.require_number(body, "surcharge_pct")
    if surcharge_pct < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "surcharge_pct must be non-negative")
    if end_d < start_d:
        raise errors.err(errors.ERR_INVALID_REQUEST, "end_date must be >= start_date")

    # Non-overlap with existing seasons on this park (closed intervals) -> 409.
    for s in store.seasons.values():
        if s["park_id"] != pid:
            continue
        s_start = parse_date(s["start_date"])
        s_end = parse_date(s["end_date"])
        if start_d <= s_end and s_start <= end_d:  # closed-interval overlap
            raise errors.err(errors.ERR_SEASON_OVERLAP, "Season window overlaps an existing season")

    sid = new_id()
    season = {
        "id": sid,
        "park_id": pid,
        "name": name,
        "start_date": start_s,
        "end_date": end_s,
        "surcharge_pct": surcharge_pct,
    }
    stamp_common(season)
    store.seasons[sid] = season
    return success(serialize_season(season), 201)


@bp.route("/parks/<pid>/seasons", methods=["GET"])
def list_seasons(pid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR, ROLE_GUEST})
    park = store.parks.get(pid)
    if park is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Park not found")
    items = [s for s in store.seasons.values() if s["park_id"] == pid]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_season(s) for s in page], limit, offset, total)


# ---------------------------------------------------------------------------
# CancellationPolicy
# ---------------------------------------------------------------------------
@bp.route("/parks/<pid>/cancellation-policies", methods=["POST"])
def create_cancellation_policy(pid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR})
    park = store.parks.get(pid)
    if park is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Park not found")
    body = V.get_json_body()
    V.require_fields(body, ["full_refund_min_days", "half_refund_min_days"])
    full = V.require_int(body, "full_refund_min_days")
    half = V.require_int(body, "half_refund_min_days")
    # Range guard: full >= half >= 0 (PRD §3.1/§3.2) -> ERR_VALIDATION_FAILED.
    if half < 0 or full < half:
        raise errors.err(
            errors.ERR_VALIDATION_FAILED,
            "full_refund_min_days must be >= half_refund_min_days >= 0",
        )

    cid = new_id()
    policy = {
        "id": cid,
        "park_id": pid,
        "full_refund_min_days": full,
        "half_refund_min_days": half,
    }
    stamp_common(policy)
    store.cancellation_policies[cid] = policy
    return success(serialize_cancellation_policy(policy), 201)


@bp.route("/parks/<pid>/cancellation-policies", methods=["GET"])
def list_cancellation_policies(pid):
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR, ROLE_GUEST})
    park = store.parks.get(pid)
    if park is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Park not found")
    items = [c for c in store.cancellation_policies.values() if c["park_id"] == pid]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list(
        [serialize_cancellation_policy(c) for c in page], limit, offset, total
    )
