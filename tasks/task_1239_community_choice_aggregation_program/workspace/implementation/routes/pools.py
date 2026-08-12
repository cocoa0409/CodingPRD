"""BadDebtPool endpoints: open, close (sharing split), true-up (reserve draw)."""

from flask import Blueprint, g, request

from auth import require_roles
from envelope import ok_object, paginate
from errors import (ApiError, ERR_ALREADY_TERMINAL, ERR_INVALID_STATE,
                    ERR_SEGREGATION_OF_DUTIES, ERR_STATUTE_WINDOW_VIOLATION,
                    ERR_UNIQUENESS_CONFLICT)
from serializers import ser_pool
from services import account_open_balance, get_or_404, reserve_debit
from store import STORE
from util import (as_str, dec, get_body, quarter_end_exclusive,
                  quarter_of_month, round_half_up_int)

bp = Blueprint("pools", __name__)

POOL_READERS = ("FinanceController", "UtilityLiaison", "BoardDirector")


@bp.post("/cca/bad-debt-pools")
@require_roles("FinanceController")
def create_pool():
    body = get_body(request)
    period = body.get("pool_period")
    if isinstance(period, str):
        for p in STORE.pools.values():
            if p["pool_period"] == period:
                raise ApiError(ERR_UNIQUENESS_CONFLICT, 409,
                               f"pool_period '{period}' already exists")
    period = as_str(period, "pool_period")
    from util import POOL_RE
    if not POOL_RE.match(period):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "pool_period must be a quarter label like '2026-Q3'")
    rec = STORE.new_record()
    rec.update({
        "pool_period": period,
        "status": "ACCRUING",
        "written_off_cents": 0,
        "billed_generation_cents": 0,
        "cca_share_cents": 0,
        "utility_share_cents": 0,
        "reserve_draw_cents": 0,
        "expensed_cents": 0,
        "_closed_by": None,
    })
    STORE.pools[rec["id"]] = rec
    return ok_object(ser_pool(rec), status=201)


@bp.get("/cca/bad-debt-pools")
@require_roles(*POOL_READERS)
def list_pools():
    items = list(STORE.pools.values())
    st = request.args.get("status")
    if st is not None:
        items = [p for p in items if p["status"] == st]
    items.sort(key=lambda p: (p["_created_dt"], p["_seq"]))
    return paginate(items, ser_pool)


@bp.get("/cca/bad-debt-pools/<pid>")
@require_roles(*POOL_READERS)
def get_pool(pid):
    return ok_object(ser_pool(get_or_404(STORE.pools, pid, "BadDebtPool")))


@bp.post("/cca/bad-debt-pools/<pid>/close")
@require_roles("FinanceController")
def close_pool(pid):
    pool = get_or_404(STORE.pools, pid, "BadDebtPool")
    if pool["status"] == "TRUED_UP":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "BadDebtPool is TRUED_UP (terminal)")
    if pool["status"] != "ACCRUING":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"BadDebtPool in status {pool['status']} cannot be closed")
    if STORE.now() < quarter_end_exclusive(pool["pool_period"]):
        raise ApiError(ERR_STATUTE_WINDOW_VIOLATION, 422,
                       "Pool cannot be closed before the last day of its period has passed")
    # Sweep written-off accounts attributed to this pool period.
    written = 0
    for acct in STORE.accounts.values():
        if (acct["uncollectible_flag"]
                and acct.get("_write_off_period") == pool["pool_period"]):
            written += account_open_balance(acct)
    pool["written_off_cents"] = written
    # Denominator: SETTLED extracts whose billing month falls inside the period.
    billed = 0
    for e in STORE.extracts.values():
        if e["status"] == "SETTLED" and quarter_of_month(e["billing_month"]) == pool["pool_period"]:
            billed += e["total_billed_cents"]
    pool["billed_generation_cents"] = billed
    auth = STORE.authority()
    cap_pct = dec(auth["bad_debt_trueup_cap_pct"]) if auth else dec(0)
    cap_cents = round_half_up_int(dec(billed) * cap_pct)
    pool["cca_share_cents"] = min(written, cap_cents)
    pool["utility_share_cents"] = written - pool["cca_share_cents"]
    pool["status"] = "CLOSED"
    pool["_closed_by"] = g.user_id
    STORE.touch(pool)
    return ok_object(ser_pool(pool))


@bp.post("/cca/bad-debt-pools/<pid>/true-up")
@require_roles("FinanceController")
def true_up_pool(pid):
    pool = get_or_404(STORE.pools, pid, "BadDebtPool")
    if pool["status"] == "TRUED_UP":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "BadDebtPool is TRUED_UP (terminal)")
    if pool["status"] != "CLOSED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"BadDebtPool in status {pool['status']} cannot be trued up")
    if g.user_id == pool["_closed_by"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 422,
                       "The true-up operator must differ from the operator who closed the pool")
    # Cascade: reserve draw (clamped), expensed remainder, Authority version bump.
    draw = reserve_debit(pool["cca_share_cents"])
    pool["reserve_draw_cents"] = draw
    pool["expensed_cents"] = pool["cca_share_cents"] - draw
    pool["status"] = "TRUED_UP"
    STORE.touch(pool)
    return ok_object(ser_pool(pool))
