"""Traders, desks."""
from __future__ import annotations

from flask import Blueprint

from app.auth import require_auth
from app.clock import clock
from app.errors import make_error
from app.responses import success_array, success_object
from app.services import positions as positions_service
from app.services.serializers import position_dto, trader_dto
from app.store import store
from app.validation import parse_pagination, paginate, get_json_body, require_str


VALID_DESK_CODES = {"G10_SPOT", "EM_FX", "OPTIONS"}

bp = Blueprint("traders", __name__, url_prefix="/fx-risk")


@bp.route("/traders", methods=["POST"])
@require_auth(["RiskOfficer"])
def create_trader():
    with store.lock:
        body = get_json_body()
        name = require_str(body, "name", min_len=1, max_len=200)
        desk_code = require_str(body, "desk_code")
        if desk_code not in VALID_DESK_CODES:
            raise make_error("ERR_VALIDATION", "desk_code must be one of G10_SPOT, EM_FX, OPTIONS.")
        meta = store.stamp_common(create=True)
        row = {
            **meta,
            "name": name,
            "desk_code": desk_code,
            "status": "ACTIVE",
        }
        store.traders[row["id"]] = row
        return success_object(trader_dto(row), status=201)


@bp.route("/traders/<trader_id>", methods=["GET"])
@require_auth(["RiskOfficer", "Trader", "ComplianceOfficer"])
def get_trader(trader_id: str):
    with store.lock:
        row = store.traders.get(trader_id)
        if row is None:
            raise make_error("ERR_NOT_FOUND")
        return success_object(trader_dto(row))


@bp.route("/desks/<desk_code>/positions", methods=["GET"])
@require_auth(["RiskOfficer", "ComplianceOfficer"])
def desk_positions(desk_code: str):
    with store.lock:
        limit, offset = parse_pagination()
        # Recompute warning_status for every trader on this desk to ensure freshness.
        trader_ids = {t["id"] for t in store.traders.values() if t["desk_code"] == desk_code}
        if not trader_ids and desk_code not in VALID_DESK_CODES:
            # Treat unknown desk as empty result (not a 404) since the path is
            # parameter-driven and the PRD doesn't promise a 404 here.
            pass
        trading_day = clock.today_iso_date()
        for tid in trader_ids:
            positions_service.recompute_warning_status_for_trader(store, tid, trading_day)
        rows = [p for p in store.positions.values() if p["trader_id"] in trader_ids]
        page, total = paginate(rows, limit, offset)
        return success_array(
            [position_dto(r) for r in page],
            limit=limit, offset=offset, total_count=total,
        )


@bp.route("/traders/<trader_id>/positions", methods=["GET"])
@require_auth(["RiskOfficer", "Trader", "ComplianceOfficer"])
def list_trader_positions(trader_id: str):
    from flask import g
    with store.lock:
        limit, offset = parse_pagination()
        trader = store.traders.get(trader_id)
        if trader is None:
            raise make_error("ERR_NOT_FOUND")
        # Ownership check for Trader role
        if g.role == "Trader" and g.user_id != trader_id:
            raise make_error("ERR_FORBIDDEN")
        trading_day = clock.today_iso_date()
        positions_service.recompute_warning_status_for_trader(store, trader_id, trading_day)
        rows = [p for p in store.positions.values() if p["trader_id"] == trader_id]
        page, total = paginate(rows, limit, offset)
        return success_array(
            [position_dto(r) for r in page],
            limit=limit, offset=offset, total_count=total,
        )


@bp.route("/traders/<trader_id>/exposure", methods=["GET"])
@require_auth(["RiskOfficer", "Trader", "ComplianceOfficer"])
def trader_exposure(trader_id: str):
    from flask import g
    with store.lock:
        trader = store.traders.get(trader_id)
        if trader is None:
            raise make_error("ERR_NOT_FOUND")
        if g.role == "Trader" and g.user_id != trader_id:
            raise make_error("ERR_FORBIDDEN")
        # Make sure positions are fresh
        for pair_code in {k[1] for k in store.position_index.keys() if k[0] == trader_id}:
            positions_service.recompute_position(store, trader_id, pair_code, clock.today_iso_date())
        gross, net = positions_service.gross_and_net_exposure(store, trader_id)
        return success_object({
            "trader_id": trader_id,
            "gross_usd": float(gross),
            "net_usd": float(net),
        })


@bp.route("/traders/<trader_id>/var", methods=["GET"])
@require_auth(["RiskOfficer", "Trader", "ComplianceOfficer"])
def trader_var(trader_id: str):
    from flask import g
    with store.lock:
        trader = store.traders.get(trader_id)
        if trader is None:
            raise make_error("ERR_NOT_FOUND")
        if g.role == "Trader" and g.user_id != trader_id:
            raise make_error("ERR_FORBIDDEN")
        for pair_code in {k[1] for k in store.position_index.keys() if k[0] == trader_id}:
            positions_service.recompute_position(store, trader_id, pair_code, clock.today_iso_date())
        var = positions_service.value_at_risk(store, trader_id)
        return success_object({
            "trader_id": trader_id,
            "var_99_1d_usd": float(var),
        })
