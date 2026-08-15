"""Grower, grade schedule, warehouse, ledger routes."""

from flask import Blueprint, request

from db import db, new_id, parse_dt, is_valid_datetime, fmt_date_z
from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_INVALID_WINDOW,
    ERR_GROWER_NOT_FOUND,
    ERR_GRADE_SCHEDULE_NOT_FOUND,
    ERR_WAREHOUSE_NOT_FOUND,
    ERR_LEDGER_ENTRY_NOT_FOUND,
    ERR_GRADE_WINDOW_OVERLAP,
    ERR_STALE_VERSION,
    ERR_SETTLEMENT_ALREADY_PAID,
    ERR_OVERPAYMENT,
)
from middleware import (
    get_context,
    require_role,
    grower_owns,
    parse_pagination,
    get_json_body,
    require_fields,
)
from response import success_object
from services.core import stamp_new, touch, post_ledger, sorted_entities, paginate
from services.calc import compute_settlement_lines, recompute_draft_settlements

bp = Blueprint("growers", __name__)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def register_clock(app):
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        user_id, role = get_context()
        require_role(role, {"CoopAdmin"})
        body = get_json_body()
        require_fields(body, ["to_iso8601"])
        to = body["to_iso8601"]
        if not isinstance(to, str) or not is_valid_datetime(to):
            err_id, status = ERR_INVALID_REQUEST
            raise ApiError(err_id, "to_iso8601 must be a valid ISO-8601 datetime", status)
        db.clock_iso = parse_dt(to).strftime("%Y-%m-%dT%H:%M:%SZ")
        return success_object({"current_utc": db.clock_iso})


# ---------------------------------------------------------------------------
# Growers
# ---------------------------------------------------------------------------

@bp.route("/gin-ops/growers", methods=["POST"])
def create_grower():
    user_id, role = get_context()
    require_role(role, {"CoopAdmin"})
    body = get_json_body()
    require_fields(body, ["membership_number", "legal_name"])
    membership = body["membership_number"]
    if not isinstance(membership, str) or not membership:
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "membership_number must be a non-empty string", status)
    legal_name = body["legal_name"]
    if not isinstance(legal_name, str) or not legal_name:
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "legal_name must be a non-empty string", status)
    patronage_rate = body.get("patronage_rate", 0.20)
    if isinstance(patronage_rate, bool) or not isinstance(patronage_rate, (int, float)):
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "patronage_rate must be a number", status)
    # Uniqueness of membership_number
    for g in db.growers.values():
        if g["membership_number"] == membership:
            err_id, status = ERR_INVALID_REQUEST
            raise ApiError(err_id, "membership_number must be unique", status)
    grower = stamp_new({
        "membership_number": membership,
        "legal_name": legal_name,
        "credit_balance_cents": 0,
        "patronage_rate": patronage_rate,
    })
    db.growers[grower["id"]] = grower
    return success_object(_grower_out(grower), 201)


def _grower_out(g):
    return {
        "id": g["id"],
        "membership_number": g["membership_number"],
        "legal_name": g["legal_name"],
        "credit_balance_cents": g["credit_balance_cents"],
        "patronage_rate": g["patronage_rate"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


@bp.route("/gin-ops/growers/<gid>", methods=["GET"])
def get_grower(gid):
    user_id, role = get_context()
    grower = db.growers.get(gid)
    if grower is None:
        err_id, status = ERR_GROWER_NOT_FOUND
        raise ApiError(err_id, "Grower not found", status)
    grower_owns(user_id, role, gid)
    return success_object(_grower_out(grower))


@bp.route("/gin-ops/growers/<gid>/settlements", methods=["GET"])
def list_grower_settlements(gid):
    user_id, role = get_context()
    grower = db.growers.get(gid)
    if grower is None:
        err_id, status = ERR_GROWER_NOT_FOUND
        raise ApiError(err_id, "Grower not found", status)
    grower_owns(user_id, role, gid)
    limit, offset = parse_pagination()
    items = [s for s in db.settlements.values() if s["grower_id"] == gid]
    items = sorted_entities(items)
    return paginate([_settlement_out(s) for s in items], limit, offset)


@bp.route("/gin-ops/growers/<gid>/settlements", methods=["POST"])
def create_settlement(gid):
    user_id, role = get_context()
    require_role(role, {"CoopAccountant"})
    grower = db.growers.get(gid)
    if grower is None:
        err_id, status = ERR_GROWER_NOT_FOUND
        raise ApiError(err_id, "Grower not found", status)
    body = get_json_body()
    require_fields(body, ["season", "expected_grower_version"])
    season = body["season"]
    if not isinstance(season, str) or not season:
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "season must be a non-empty string", status)
    expected = body["expected_grower_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "expected_grower_version must be an integer", status)
    # OCC
    if expected != grower["version"]:
        err_id, status = ERR_STALE_VERSION
        raise ApiError(err_id, "expected_grower_version does not match current version", status)
    # PAID guard
    for s in db.settlements.values():
        if s["grower_id"] == gid and s["season"] == season and s["status"] == "PAID":
            err_id, status = ERR_SETTLEMENT_ALREADY_PAID
            raise ApiError(err_id, "A PAID settlement exists for this grower and season", status)
    # Supersede existing DRAFT/FINAL
    for s in db.settlements.values():
        if s["grower_id"] == gid and s["season"] == season and s["status"] in ("DRAFT", "FINAL"):
            s["status"] = "SUPERSEDED"
            touch(s)
    lines = compute_settlement_lines(grower, season, "PROVISIONAL")
    settlement = stamp_new({
        "grower_id": gid,
        "season": season,
        "computation_variant": "PROVISIONAL",
        "status": "DRAFT",
        "paid_amount_cents": None,
        **lines,
    })
    db.settlements[settlement["id"]] = settlement
    touch(grower)
    return success_object(_settlement_out(settlement), 201)


def _settlement_out(s):
    return {
        "id": s["id"],
        "grower_id": s["grower_id"],
        "season": s["season"],
        "computation_variant": s["computation_variant"],
        "status": s["status"],
        "lint_value_cents": s["lint_value_cents"],
        "quality_adjustment_cents": s["quality_adjustment_cents"],
        "seed_credit_cents": s["seed_credit_cents"],
        "ginning_charge_cents": s["ginning_charge_cents"],
        "storage_charge_cents": s["storage_charge_cents"],
        "loan_net_cents": s["loan_net_cents"],
        "adjustment_net_cents": s["adjustment_net_cents"],
        "patronage_cents": s["patronage_cents"],
        "net_payable_cents": s["net_payable_cents"],
        "paid_amount_cents": s["paid_amount_cents"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


@bp.route("/gin-ops/growers/<gid>/ledger-adjustments", methods=["POST"])
def create_ledger_adjustment(gid):
    user_id, role = get_context()
    require_role(role, {"CoopAccountant"})
    grower = db.growers.get(gid)
    if grower is None:
        err_id, status = ERR_GROWER_NOT_FOUND
        raise ApiError(err_id, "Grower not found", status)
    body = get_json_body()
    require_fields(body, ["season", "amount_cents", "memo"])
    season = body["season"]
    amount = body["amount_cents"]
    memo = body["memo"]
    if not isinstance(season, str) or not season:
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "season must be a non-empty string", status)
    if isinstance(amount, bool) or not isinstance(amount, int):
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "amount_cents must be an integer", status)
    if not isinstance(memo, str):
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "memo must be a string", status)
    entry = post_ledger(gid, season, "ADJUSTMENT", amount, memo)
    # Adjustment flows into next settlement recompute
    recompute_draft_settlements(gid, season)
    return success_object(_ledger_out(entry), 201)


# ---------------------------------------------------------------------------
# Ledger entries
# ---------------------------------------------------------------------------

def _ledger_out(e):
    return {
        "id": e["id"],
        "grower_id": e["grower_id"],
        "settlement_id": e["settlement_id"],
        "season": e["season"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "memo": e["memo"],
        "created_at": e["created_at"],
    }


@bp.route("/gin-ops/ledger-entries", methods=["GET"])
def list_ledger_entries():
    user_id, role = get_context()
    limit, offset = parse_pagination()
    args = request.args
    grower_id = args.get("grower_id")
    settlement_id = args.get("settlement_id")
    season = args.get("season")
    items = list(db.ledger_entries.values())
    if role == "Grower":
        # own entries only
        items = [e for e in items if e["grower_id"] == user_id]
        if grower_id is not None and grower_id != user_id:
            err_id, status = ERR_FORBIDDEN
            raise ApiError(err_id, "Grower may only access own ledger entries", status)
    if grower_id is not None:
        items = [e for e in items if e["grower_id"] == grower_id]
    if settlement_id is not None:
        items = [e for e in items if e["settlement_id"] == settlement_id]
    if season is not None:
        items = [e for e in items if e["season"] == season]
    items = sorted_entities(items)
    return paginate([_ledger_out(e) for e in items], limit, offset)


@bp.route("/gin-ops/ledger-entries/<eid>", methods=["GET"])
def get_ledger_entry(eid):
    user_id, role = get_context()
    entry = db.ledger_entries.get(eid)
    if entry is None:
        err_id, status = ERR_LEDGER_ENTRY_NOT_FOUND
        raise ApiError(err_id, "Ledger entry not found", status)
    if role == "Grower" and entry["grower_id"] != user_id:
        err_id, status = ERR_FORBIDDEN
        raise ApiError(err_id, "Grower may only access own ledger entries", status)
    return success_object(_ledger_out(entry))


# ---------------------------------------------------------------------------
# Grade schedules
# ---------------------------------------------------------------------------

@bp.route("/gin-ops/grade-schedules", methods=["POST"])
def create_grade_schedule():
    user_id, role = get_context()
    require_role(role, {"CoopAdmin"})
    body = get_json_body()
    require_fields(body, ["grade_code", "premium_discount_points", "loan_rate_points", "effective_from", "effective_to"])
    grade_code = body["grade_code"]
    pd = body["premium_discount_points"]
    lr = body["loan_rate_points"]
    if not isinstance(grade_code, str) or not grade_code:
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "grade_code must be a non-empty string", status)
    for v, name in ((pd, "premium_discount_points"), (lr, "loan_rate_points")):
        if isinstance(v, bool) or not isinstance(v, int):
            err_id, status = ERR_INVALID_REQUEST
            raise ApiError(err_id, f"{name} must be an integer", status)
    ef_raw, et_raw = body["effective_from"], body["effective_to"]
    if not is_valid_datetime(ef_raw) or not is_valid_datetime(et_raw):
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "effective_from/effective_to must be valid datetimes", status)
    ef = parse_dt(ef_raw)
    et = parse_dt(et_raw)
    if et <= ef:
        err_id, status = ERR_INVALID_WINDOW
        raise ApiError(err_id, "effective_to must be strictly later than effective_from", status)
    # overlap check for same grade_code: half-open windows; adjacency allowed
    for s in db.grade_schedules.values():
        if s["grade_code"] != grade_code:
            continue
        if ef < s["_effective_to_dt"] and s["_effective_from_dt"] < et:
            err_id, status = ERR_GRADE_WINDOW_OVERLAP
            raise ApiError(err_id, "Grade schedule window overlaps an existing window", status)
    schedule = stamp_new({
        "grade_code": grade_code,
        "premium_discount_points": pd,
        "loan_rate_points": lr,
        "effective_from": fmt_date_z(ef),
        "effective_to": fmt_date_z(et),
        "_effective_from_dt": ef,
        "_effective_to_dt": et,
    })
    db.grade_schedules[schedule["id"]] = schedule
    return success_object(_schedule_out(schedule), 201)


def _schedule_out(s):
    return {
        "id": s["id"],
        "grade_code": s["grade_code"],
        "premium_discount_points": s["premium_discount_points"],
        "loan_rate_points": s["loan_rate_points"],
        "effective_from": s["effective_from"],
        "effective_to": s["effective_to"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


@bp.route("/gin-ops/grade-schedules/<sid>", methods=["GET"])
def get_grade_schedule(sid):
    user_id, role = get_context()
    s = db.grade_schedules.get(sid)
    if s is None:
        err_id, status = ERR_GRADE_SCHEDULE_NOT_FOUND
        raise ApiError(err_id, "Grade schedule not found", status)
    return success_object(_schedule_out(s))


# ---------------------------------------------------------------------------
# Warehouses
# ---------------------------------------------------------------------------

@bp.route("/gin-ops/warehouses", methods=["POST"])
def create_warehouse():
    user_id, role = get_context()
    require_role(role, {"CoopAdmin"})
    body = get_json_body()
    require_fields(body, ["name", "capacity_bales", "dock_count"])
    name = body["name"]
    cap = body["capacity_bales"]
    docks = body["dock_count"]
    if not isinstance(name, str) or not name:
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "name must be a non-empty string", status)
    for v, fname in ((cap, "capacity_bales"), (docks, "dock_count")):
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            err_id, status = ERR_INVALID_REQUEST
            raise ApiError(err_id, f"{fname} must be a non-negative integer", status)
    wh = stamp_new({
        "name": name,
        "capacity_bales": cap,
        "stored_bale_count": 0,
        "dock_count": docks,
    })
    db.warehouses[wh["id"]] = wh
    return success_object(_warehouse_out(wh), 201)


def _warehouse_out(w):
    return {
        "id": w["id"],
        "name": w["name"],
        "capacity_bales": w["capacity_bales"],
        "stored_bale_count": w["stored_bale_count"],
        "dock_count": w["dock_count"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


@bp.route("/gin-ops/warehouses/<wid>", methods=["GET"])
def get_warehouse(wid):
    user_id, role = get_context()
    w = db.warehouses.get(wid)
    if w is None:
        err_id, status = ERR_WAREHOUSE_NOT_FOUND
        raise ApiError(err_id, "Warehouse not found", status)
    return success_object(_warehouse_out(w))
