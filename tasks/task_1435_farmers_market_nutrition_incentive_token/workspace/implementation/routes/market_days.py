"""MarketDay endpoints: schedule, read, list, open, close, reconcile."""

from flask import Blueprint, request

from db import STORE, stamp_new, touch, idem_marker
from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_MARKET_DAY_NOT_OPEN,
    ERR_MARKET_DAY_OVERLAP,
    ERR_RECONCILIATION_VARIANCE,
    ERR_SEASON_INACTIVE,
)
from logical_clock import CLOCK, _parse_iso
from middleware import (
    IdempotencyReplay,
    authenticate,
    ensure_valid_json,
    fail_shape,
    get_body,
    idempotency_guard,
    opt_bool,
    paginate,
    req_date,
    req_datetime,
    req_str,
)
from response import success_list, success_object
from routes.common import get_path_entity, ref_exists, replay_response
from services.domain import (
    RECONCILE_TOLERANCE_CENTS,
    date_to_utc_start,
    iso,
    market_day_totals,
    serialize_market_day,
)

bp = Blueprint("market_days", __name__)

DAY_READ_ROLES = ["ProgramAdmin", "MarketManager", "BoothOperator", "Auditor", "Vendor"]


@bp.route("/market-days", methods=["POST"])
def create_market_day():
    role, _uid = authenticate(["MarketManager"])
    body = get_body()
    try:
        key, fp = idempotency_guard(body)
    except IdempotencyReplay as replay:
        return replay_response(replay)
    ref_exists("markets", body.get("market_id"))
    ensure_valid_json(body)
    market_id = req_str(body, "market_id")
    date_str = req_date(body, "date")
    opens_at = req_datetime(body, "opens_at")
    closes_at = req_datetime(body, "closes_at")
    if not closes_at > opens_at:
        fail_shape("closes_at must be strictly after opens_at")

    market = STORE["markets"][market_id]
    program = STORE["programs"].get(market["program_id"])

    # Priority 21: date within [season_start, season_end)
    day_start = date_to_utc_start(date_str)
    season_start = _parse_iso(program["season_start"])
    season_end = _parse_iso(program["season_end"])
    if not (season_start <= day_start < season_end):
        raise ApiError(ERR_SEASON_INACTIVE, 409,
                       "MarketDay.date is outside the program season window")

    # Priority 23: half-open window overlap within the same market (any status)
    for other in STORE["market_days"].values():
        if other["market_id"] != market_id:
            continue
        o_start = _parse_iso(other["opens_at"])
        o_end = _parse_iso(other["closes_at"])
        if opens_at < o_end and o_start < closes_at:
            raise ApiError(ERR_MARKET_DAY_OVERLAP, 409,
                           "Operating window overlaps an existing market day")

    day = stamp_new({
        "market_id": market_id,
        "date": date_str,
        "opens_at": iso(opens_at),
        "closes_at": iso(closes_at),
        "status": "SCHEDULED",
    })
    STORE["market_days"][day["id"]] = day
    env, status = success_object(serialize_market_day(day), 201)
    idem_marker(key, fp, status, env.get_json())
    return env, status


@bp.route("/market-days/<did>", methods=["GET"])
def get_market_day(did):
    authenticate(DAY_READ_ROLES)
    day = get_path_entity("market_days", did)
    return success_object(serialize_market_day(day))


@bp.route("/market-days", methods=["GET"])
def list_market_days():
    authenticate(DAY_READ_ROLES)
    market_id = request.args.get("market_id")
    status_filter = request.args.get("status")
    items = list(STORE["market_days"].values())
    if market_id is not None:
        items = [d for d in items if d["market_id"] == market_id]
    if status_filter is not None:
        items = [d for d in items if d["status"] == status_filter]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_market_day(d) for d in page], limit, offset, total)


@bp.route("/market-days/<did>/open", methods=["POST"])
def open_market_day(did):
    role, _uid = authenticate(["MarketManager"])
    body = get_body()
    try:
        key, fp = idempotency_guard(body)
    except IdempotencyReplay as replay:
        return replay_response(replay)
    day = get_path_entity("market_days", did)
    if day["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"MarketDay in status {day['status']} cannot be opened")
    if CLOCK.current_date_str() != day["date"]:
        raise ApiError(ERR_MARKET_DAY_NOT_OPEN, 409,
                       "Logical clock date does not equal the market day date")
    day["status"] = "OPEN"
    touch(day)
    env, status = success_object(serialize_market_day(day), 200)
    idem_marker(key, fp, status, env.get_json())
    return env, status


@bp.route("/market-days/<did>/close", methods=["POST"])
def close_market_day(did):
    role, _uid = authenticate(["MarketManager"])
    body = get_body()
    try:
        key, fp = idempotency_guard(body)
    except IdempotencyReplay as replay:
        return replay_response(replay)
    day = get_path_entity("market_days", did)
    if day["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"MarketDay in status {day['status']} cannot be closed")
    day["status"] = "CLOSED"
    touch(day)
    env, status = success_object(serialize_market_day(day), 200)
    idem_marker(key, fp, status, env.get_json())
    return env, status


@bp.route("/market-days/<did>/reconcile", methods=["POST"])
def reconcile_market_day(did):
    # Priority 2 includes the payload-scoped rule: override_variance: true is
    # ProgramAdmin-only; a MarketManager sending it gets ERR_FORBIDDEN — this
    # evaluates before idempotency and path-existence checks.
    role, _uid = authenticate(["MarketManager", "ProgramAdmin"])
    body = get_body()
    override = body.get("override_variance")
    if role == "MarketManager" and override is True:
        raise ApiError(ERR_FORBIDDEN, 403,
                       "override_variance: true is ProgramAdmin-only")
    try:
        key, fp = idempotency_guard(body)
    except IdempotencyReplay as replay:
        return replay_response(replay)
    day = get_path_entity("market_days", did)
    ensure_valid_json(body)
    override_flag = opt_bool(body, "override_variance") or False

    if day["status"] not in ("CLOSED", "VARIANCE_FLAGGED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"MarketDay in status {day['status']} cannot be reconciled")

    _, _, _, variance = market_day_totals(day)
    if day["status"] == "CLOSED":
        if override_flag:
            day["status"] = "RECONCILED"
        elif abs(variance) <= RECONCILE_TOLERANCE_CENTS:
            day["status"] = "RECONCILED"
        else:
            # Soft failure (PRD §3.2): 200 OK, routed to VARIANCE_FLAGGED.
            day["status"] = "VARIANCE_FLAGGED"
    else:  # VARIANCE_FLAGGED
        if not override_flag:
            raise ApiError(ERR_RECONCILIATION_VARIANCE, 409,
                           "A variance-flagged day reconciles only with "
                           "override_variance: true")
        day["status"] = "RECONCILED"
    touch(day)
    env, status = success_object(serialize_market_day(day), 200)
    idem_marker(key, fp, status, env.get_json())
    return env, status
