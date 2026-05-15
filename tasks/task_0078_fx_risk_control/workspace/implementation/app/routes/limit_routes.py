"""Limits: create, list, patch."""
from __future__ import annotations

from flask import Blueprint, g, request

from app.auth import require_auth
from app.clock import clock
from app.errors import make_error
from app.numeric import ZERO
from app.responses import success_array, success_object
from app.services import positions as positions_service
from app.services.serializers import limit_dto
from app.store import store
from app.validation import (
    check_version,
    get_json_body,
    optional_decimal,
    parse_pagination,
    paginate,
    require_decimal,
    require_enum,
)


bp = Blueprint("limits", __name__, url_prefix="/fx-risk")

VALID_BUCKETS = {"INTRADAY", "OVERNIGHT"}


@bp.route("/traders/<trader_id>/limits", methods=["POST"])
@require_auth(["RiskOfficer"])
def create_limit(trader_id: str):
    with store.lock:
        if trader_id not in store.traders:
            raise make_error("ERR_NOT_FOUND")
        body = get_json_body()
        bucket = require_enum(body, "bucket", VALID_BUCKETS)
        notional_cap = require_decimal(body, "notional_cap_usd", gt=ZERO)
        stop_loss_cap = require_decimal(body, "stop_loss_cap_usd", gte=ZERO)
        pair_code = body.get("pair_code")
        if pair_code is not None and not isinstance(pair_code, str):
            raise make_error("ERR_VALIDATION", "pair_code must be string or null.")
        if pair_code and pair_code not in store.pair_index_by_code:
            raise make_error("ERR_NOT_FOUND")
        meta = store.stamp_common(create=True)
        row = {
            **meta,
            "trader_id": trader_id,
            "pair_code": pair_code,
            "bucket": bucket,
            "notional_cap_usd": notional_cap,
            "stop_loss_cap_usd": stop_loss_cap,
            "temporary_override_usd": ZERO,
            "utilization_usd": ZERO,
            "utilization_pct": ZERO,
        }
        store.limits[row["id"]] = row
        positions_service.recompute_limit_utilization(store, row, clock.today_iso_date())
        positions_service.recompute_warning_status_for_trader(store, trader_id, clock.today_iso_date())
        return success_object(limit_dto(row), status=201)


@bp.route("/traders/<trader_id>/limits", methods=["GET"])
@require_auth(["RiskOfficer", "Trader", "ComplianceOfficer"])
def list_limits(trader_id: str):
    with store.lock:
        limit_param, offset_param = parse_pagination()
        if trader_id not in store.traders:
            raise make_error("ERR_NOT_FOUND")
        if g.role == "Trader" and g.user_id != trader_id:
            raise make_error("ERR_FORBIDDEN")
        bucket_filter = request.args.get("bucket")
        trading_day = clock.today_iso_date()
        rows = [l for l in store.limits.values() if l["trader_id"] == trader_id]
        if bucket_filter:
            rows = [l for l in rows if l["bucket"] == bucket_filter]
        for limit in rows:
            positions_service.recompute_limit_utilization(store, limit, trading_day)
        page, total = paginate(rows, limit_param, offset_param)
        return success_array(
            [limit_dto(r) for r in page],
            limit=limit_param, offset=offset_param, total_count=total,
        )


@bp.route("/limits/<limit_id>", methods=["PATCH"])
@require_auth(["RiskOfficer"])
def patch_limit(limit_id: str):
    with store.lock:
        limit = store.limits.get(limit_id)
        if limit is None:
            raise make_error("ERR_NOT_FOUND")
        body = get_json_body()
        check_version(body, limit["version"])
        new_notional = optional_decimal(body, "notional_cap_usd", gt=ZERO)
        new_stop_loss = optional_decimal(body, "stop_loss_cap_usd", gte=ZERO)
        before = {
            "notional_cap_usd": float(limit["notional_cap_usd"]),
            "stop_loss_cap_usd": float(limit["stop_loss_cap_usd"]),
        }
        if new_notional is not None:
            limit["notional_cap_usd"] = new_notional
        if new_stop_loss is not None:
            limit["stop_loss_cap_usd"] = new_stop_loss
        limit["updated_at"] = clock.now_iso()
        limit["version"] = limit["version"] + 1
        trading_day = clock.today_iso_date()
        positions_service.recompute_limit_utilization(store, limit, trading_day)
        positions_service.recompute_warning_status_for_trader(store, limit["trader_id"], trading_day)
        store.audit(
            event_type="LIMIT_CHANGE",
            actor_user_id=g.user_id,
            actor_role=g.role,
            subject_entity="Limit",
            subject_id=limit["id"],
            before_snapshot=before,
            after_snapshot={
                "notional_cap_usd": float(limit["notional_cap_usd"]),
                "stop_loss_cap_usd": float(limit["stop_loss_cap_usd"]),
            },
        )
        return success_object(limit_dto(limit))
