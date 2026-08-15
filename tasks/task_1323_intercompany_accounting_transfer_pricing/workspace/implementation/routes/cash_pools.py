"""CashPool lifecycle (PRD 3.8): OPEN -> NETTING -> SETTLED.

Sweeps are OCC-guarded (expected_cash_pool_version) and zero-sum validated.
Netting computes balance-day accrual (AVERAGE_BALANCE) or point-in-time base
(CLOSING_BALANCE), per-position interest at 85 bp p.a., and the pinned
round-per-position-then-residual admin fee allocation, then folds pending
amounts and UNSETTLED MATCHED/ELIMINATED transactions into positions.
"""
from flask import Blueprint, request

import errors
from db import store, new_resource, touch, public, clock_iso
from errors import ApiError
from middleware import (
    require_auth, get_body, get_path, require_fk, is_int,
    shape_str, shape_enum, shape_int, list_page, whole_days, ALL_ROLES,
)
from response import ok_object, ok_list
from services import calc

bp = Blueprint("cash_pools", __name__)

INTEREST_METHODS = ["AVERAGE_BALANCE", "CLOSING_BALANCE"]
_TREASURY = ["TreasuryManager"]


def upsert_position(pool, entity_id):
    for p in pool["positions"]:
        if p["entity_id"] == entity_id:
            return p
    p = {
        "entity_id": entity_id,
        "balance_cents": 0,
        "accrued_balance_day_cents": 0,
        "pending_cents": 0,
        "interest_cents": 0,
        "fee_cents": 0,
        "status": "OPEN",
        "_last_event_dt": pool["_opened_dt"],
    }
    pool["positions"].append(p)
    return p


def _entity_seq(entity_id):
    ent = store.legal_entities.get(entity_id)
    return ent["_seq"] if ent is not None else 0


@bp.post("/tp/cash_pools")
def create_cash_pool():
    require_auth(_TREASURY)
    body = get_body()
    fyid = body.get("fiscal_year_id")
    require_fk(store.fiscal_years, fyid, "fiscal_year_id")
    # (8) at most one pool per fiscal year.
    if isinstance(fyid, str):
        for p in store.cash_pools.values():
            if p["fiscal_year_id"] == fyid:
                raise ApiError(errors.DUPLICATE_CASH_POOL, 409,
                               "A cash pool already exists for this fiscal year")
    # (10) shape.
    shape_str(body, "fiscal_year_id")
    method = shape_enum(body, "interest_method", INTEREST_METHODS)
    fee = shape_int(body, "admin_fee_cents", min_v=0)
    p = new_resource()
    p.update({
        "fiscal_year_id": fyid,
        "interest_method": method,
        "admin_fee_cents": fee,
        "status": "OPEN",
        "positions": [],
        "opened_at_utc": clock_iso(),
        "netting_at_utc": None,
        "_opened_dt": store.clock,
    })
    store.cash_pools[p["id"]] = p
    return ok_object(public(p), 201)


@bp.get("/tp/cash_pools/<cashPoolId>")
def get_cash_pool(cashPoolId):
    require_auth(ALL_ROLES)
    p = get_path(store.cash_pools, cashPoolId)
    return ok_object(public(p), 200)


@bp.get("/tp/cash_pools")
def list_cash_pools():
    require_auth(ALL_ROLES)
    filters = [("fiscal_year_id", request.args.get("fiscal_year_id"))]
    page, limit, offset, total = list_page(list(store.cash_pools.values()), filters)
    return ok_list([public(r) for r in page], limit, offset, total)


@bp.post("/tp/cash_pools/<cashPoolId>/sweeps")
def post_sweeps(cashPoolId):
    require_auth(_TREASURY)
    pool = get_path(store.cash_pools, cashPoolId)
    body = get_body()
    movements = body.get("movements")
    # (3) existence of each movement's entity id, in declared order.
    if isinstance(movements, list):
        for mv in movements:
            if isinstance(mv, dict):
                require_fk(store.legal_entities, mv.get("entity_id"), "entity_id")
    if pool["status"] != "OPEN":
        raise ApiError(errors.INVALID_STATE, 409,
                       "sweeps require the cash pool to be OPEN")
    # OCC guard (PRD 2.7).
    expected = body.get("expected_cash_pool_version")
    if is_int(expected) and expected != pool["version"]:
        raise ApiError(errors.STALE_VERSION, 412,
                       "expected_cash_pool_version does not match the pool's current version")
    # (8) zero-sum validation, before any movement is applied (atomicity).
    def _amount(mv):
        if not isinstance(mv, dict):
            return None
        v = mv.get("amount_cents", mv.get("amount"))
        return v if is_int(v) else None
    if isinstance(movements, list) and all(_amount(mv) is not None for mv in movements):
        if sum(_amount(mv) for mv in movements) != 0:
            raise ApiError(errors.POOL_NOT_ZERO_SUM, 409,
                           "Sweep movements must sum to zero")
    # (10) shape.
    if not isinstance(movements, list):
        raise ApiError(errors.INVALID_REQUEST, 400, "movements must be a list")
    for mv in movements:
        if not isinstance(mv, dict):
            raise ApiError(errors.INVALID_REQUEST, 400,
                           "each movement must be an object")
        if not isinstance(mv.get("entity_id"), str) or not mv.get("entity_id"):
            raise ApiError(errors.INVALID_REQUEST, 400,
                           "each movement requires an entity_id")
        if _amount(mv) is None:
            raise ApiError(errors.INVALID_REQUEST, 400,
                           "each movement requires a signed integer amount_cents")
    if not is_int(expected):
        raise ApiError(errors.INVALID_REQUEST, 400,
                       "expected_cash_pool_version is required and must be an integer")
    # Apply: upsert positions, accrue balance-days (AVERAGE_BALANCE), add amounts.
    now = store.clock
    for mv in movements:
        pos = upsert_position(pool, mv["entity_id"])
        if pool["interest_method"] == "AVERAGE_BALANCE":
            days = whole_days(pos["_last_event_dt"], now)
            pos["accrued_balance_day_cents"] += pos["balance_cents"] * days
            pos["_last_event_dt"] = now
        pos["balance_cents"] += _amount(mv)
    touch(pool)
    return ok_object(public(pool), 200)


@bp.post("/tp/cash_pools/<cashPoolId>/begin_netting")
def begin_netting(cashPoolId):
    require_auth(_TREASURY)
    pool = get_path(store.cash_pools, cashPoolId)
    if pool["status"] != "OPEN":
        raise ApiError(errors.INVALID_STATE, 409,
                       "begin_netting requires the cash pool to be OPEN")
    now = store.clock
    pool["netting_at_utc"] = clock_iso()
    positions = pool["positions"]
    # 1) Final balance-day epoch accrual (AVERAGE_BALANCE only).
    if pool["interest_method"] == "AVERAGE_BALANCE":
        for pos in positions:
            days = whole_days(pos["_last_event_dt"], now)
            pos["accrued_balance_day_cents"] += pos["balance_cents"] * days
            pos["_last_event_dt"] = now
    # 2) Interest per position (pre-fold balances), signed with the balance.
    total_days = whole_days(pool["_opened_dt"], now)
    for pos in positions:
        if pool["interest_method"] == "AVERAGE_BALANCE":
            base = pos["accrued_balance_day_cents"]
        else:  # CLOSING_BALANCE
            base = pos["balance_cents"] * total_days
        pos["interest_cents"] = calc.interest_cents(base)
    # 3) Fold pending into balances, then net the year's UNSETTLED
    #    MATCHED/ELIMINATED transactions (chronological), each -> NETTED.
    for pos in positions:
        pos["balance_cents"] += pos["pending_cents"]
        pos["pending_cents"] = 0
    foldable = [t for t in store.transactions.values()
                if t["fiscal_year_id"] == pool["fiscal_year_id"]
                and t["settlement_status"] == "UNSETTLED"
                and t["elimination_status"] in ("MATCHED", "ELIMINATED")]
    foldable.sort(key=lambda t: t["_seq"])
    for t in foldable:
        agreement = store.agreements.get(t["agreement_id"])
        if agreement is None:
            continue
        prov_pos = upsert_position(pool, agreement["provider_entity_id"])
        prov_pos["balance_cents"] += t["provider_revenue_cents"]
        rec_pos = upsert_position(pool, agreement["recipient_entity_id"])
        rec_pos["balance_cents"] -= t["recipient_cost_cents"]
        t["settlement_status"] = "NETTED"
        touch(t)
    # 4) Admin fee: round PER POSITION first (entity created_at ASC walk),
    #    then residual to the largest |balance| (tie-break entity created_at ASC).
    positions = pool["positions"]
    fee_base = sum(abs(pos["balance_cents"]) for pos in positions)
    ordered = sorted(positions, key=lambda pos: _entity_seq(pos["entity_id"]))
    if ordered:
        if fee_base == 0:
            for pos in ordered:
                pos["fee_cents"] = 0
            residual = pool["admin_fee_cents"]
            ordered[0]["fee_cents"] += residual
        else:
            for pos in ordered:
                pos["fee_cents"] = calc.fee_share_cents(
                    pool["admin_fee_cents"], abs(pos["balance_cents"]), fee_base)
            residual = pool["admin_fee_cents"] - sum(pos["fee_cents"] for pos in positions)
            target = max(ordered, key=lambda pos: abs(pos["balance_cents"]))
            target["fee_cents"] += residual
    for pos in positions:
        pos["status"] = "NETTING"
    pool["status"] = "NETTING"
    touch(pool)
    return ok_object(public(pool), 200)


@bp.post("/tp/cash_pools/<cashPoolId>/settle")
def settle_cash_pool(cashPoolId):
    require_auth(_TREASURY)
    pool = get_path(store.cash_pools, cashPoolId)
    if pool["status"] != "NETTING":
        raise ApiError(errors.INVALID_STATE, 409,
                       "settle requires the cash pool to be NETTING")
    if sum(pos["balance_cents"] for pos in pool["positions"]) != 0:
        raise ApiError(errors.POOL_NOT_ZERO_SUM, 409,
                       "Pool positions do not sum to zero after folding")
    for pos in pool["positions"]:
        pos["status"] = "SETTLED"
    for t in store.transactions.values():
        if (t["fiscal_year_id"] == pool["fiscal_year_id"]
                and t["settlement_status"] == "NETTED"):
            t["settlement_status"] = "SETTLED"
            touch(t)
    pool["status"] = "SETTLED"
    touch(pool)
    return ok_object(public(pool), 200)
