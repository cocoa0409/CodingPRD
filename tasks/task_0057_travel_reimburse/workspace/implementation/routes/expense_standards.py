"""ExpenseStandard endpoints."""

from __future__ import annotations

from flask import Blueprint, request

from db import STORE
from errors import APIError
from middleware import require_auth
from response import success, parse_pagination, paginate
from serializers import expense_standard as ser_es
from services.validate import (
    require_body, get_int, get_enum, get_money, get_datetime,
)
from utils import CLOCK, new_uuid, parse_ts, format_ts


bp = Blueprint("expense_standards", __name__)


TIERS = {"TIER_1", "TIER_2", "TIER_3", "OVERSEAS"}
LEVELS = {"STAFF", "MANAGER", "DIRECTOR", "EXECUTIVE"}


@bp.route("/expense-standards", methods=["POST"])
@require_auth(["Admin"])
def create_standard():
    body = require_body(request.get_json(silent=True))
    version = get_int(body, "version", min_value=1)
    effective_from = get_datetime(body, "effective_from")
    effective_to_raw = body.get("effective_to")
    effective_to = None
    if effective_to_raw is not None:
        effective_to = get_datetime(body, "effective_to")
        if effective_to <= effective_from:
            raise APIError("ERR_VALIDATION", "effective_to must be > effective_from", 422)
    city_tier = get_enum(body, "city_tier", TIERS)
    employee_level = get_enum(body, "employee_level", LEVELS)
    lodging = get_money(body, "lodging_daily_cap")
    per_diem = get_money(body, "per_diem_amount")
    transp = get_money(body, "transportation_daily_cap")
    holiday_mult = get_money(body, "holiday_multiplier", required=False,
                              non_negative=True,
                              default=__import__("decimal").Decimal("1.00"))

    # Auto-close prior open row in same (city_tier, employee_level) bucket;
    # also enforce effective_from is strictly later than any prior version's effective_from
    # for the same bucket.
    same_bucket = [
        r for r in STORE.expense_standards.values()
        if r["city_tier"] == city_tier and r["employee_level"] == employee_level
    ]
    for r in same_bucket:
        prev_from = parse_ts(r["effective_from"])
        if effective_from <= prev_from:
            raise APIError(
                "ERR_VALIDATION",
                "effective_from must be strictly later than any prior version in the same bucket",
                422,
            )
        # Auto-close any open prior row
        if not r.get("effective_to"):
            r["effective_to"] = format_ts(effective_from)

    sid = new_uuid()
    row = {
        "id": sid,
        "version": version,
        "effective_from": format_ts(effective_from),
        "effective_to": format_ts(effective_to) if effective_to else None,
        "city_tier": city_tier,
        "employee_level": employee_level,
        "lodging_daily_cap": lodging,
        "per_diem_amount": per_diem,
        "transportation_daily_cap": transp,
        "holiday_multiplier": holiday_mult,
        "created_at": CLOCK.now_iso(),
    }
    STORE.expense_standards[sid] = row
    return success(ser_es(row), status=201)


@bp.route("/expense-standards", methods=["GET"])
@require_auth(["Admin", "Finance", "Applicant"])
def list_standards():
    limit, offset = parse_pagination()
    version_f = request.args.get("version")
    city_tier_f = request.args.get("city_tier")
    level_f = request.args.get("employee_level")

    rows = list(STORE.expense_standards.values())
    if version_f is not None:
        try:
            v = int(version_f)
        except (TypeError, ValueError):
            raise APIError("ERR_VALIDATION", "version filter must be an integer", 422)
        rows = [r for r in rows if r["version"] == v]
    if city_tier_f is not None:
        if city_tier_f not in TIERS:
            raise APIError("ERR_VALIDATION", "city_tier filter invalid", 422)
        rows = [r for r in rows if r["city_tier"] == city_tier_f]
    if level_f is not None:
        if level_f not in LEVELS:
            raise APIError("ERR_VALIDATION", "employee_level filter invalid", 422)
        rows = [r for r in rows if r["employee_level"] == level_f]

    rows.sort(key=lambda r: r["created_at"])
    page, pag = paginate(rows, limit, offset)
    return success([ser_es(r) for r in page], pagination=pag)
