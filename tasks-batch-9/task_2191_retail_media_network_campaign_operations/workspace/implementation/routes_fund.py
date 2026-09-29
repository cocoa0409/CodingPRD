"""The co-op trade fund pool (PRD 3.2)."""
from flask import Blueprint

from core import F, db, fail, insert, new_row, now, ok, rows, touch
import derive as D
import helpers as H
from guard import guard

bp = Blueprint("trade_funds", __name__)

READ_ROLES = ("NetworkAdmin", "BillingOps", "CreditAnalyst", "AccountManager",
              "AdvertiserUser")
WRITE_ROLES = ("NetworkAdmin", "BillingOps")
FROZEN_REASONS = ("AUDIT", "OVERDRAWN", "MANUAL")

LIST_FILTERS = (
    ("advertiser_id", "advertiser_id", "string"),
    ("fiscal_period_code", "fiscal_period_code", "string"),
    ("account_status", "account_status", "string"),
)


@bp.post("/rmn/trade-fund-accounts")
def create_pool():
    specs = (
        F("advertiser_id", "string", required=True),
        F("fiscal_period_code", "string", required=True),
        F("accrual_basis", "enum", enum=("PURCHASE_VOLUME", "FIXED"),
          default="PURCHASE_VOLUME", has_default=True),
        F("deduction_cap_pct", "number", minimum=0.0, maximum=1.0,
          default=0.6, has_default=True),
    )
    ctx = guard(WRITE_ROLES, body_specs=specs,
                body_refs=(("advertiser", "advertiser_id"),), mutating=True)
    data = ctx.data
    H.require_fiscal_period(data["fiscal_period_code"])
    if D.pool_for(data["advertiser_id"], data["fiscal_period_code"]) is not None:
        fail("ERR_DUPLICATE_TRADE_FUND_PERIOD",
             "A fund account already exists for this advertiser and period.")
    row = new_row()
    row.update({
        "advertiser_id": data["advertiser_id"],
        "fiscal_period_code": data["fiscal_period_code"],
        "account_status": "OPEN",
        "accrual_basis": data["accrual_basis"],
        "deduction_cap_pct": data["deduction_cap_pct"],
        "accrued_cents": 0,
        "frozen_reason": "NONE",
        "last_reconciled_at": None,
        "_manual_deducted_cents": 0,
    })
    insert("trade_fund_account", row)
    return ok(D.ser_trade_fund_account(row), 201)


@bp.get("/rmn/trade-fund-accounts")
def list_pools():
    ctx = guard(READ_ROLES, paginated=True)
    return H.respond_list(ctx, "trade_fund_account", rows("trade_fund_account"),
                          LIST_FILTERS, owner_kind="trade_fund_account")


@bp.get("/rmn/trade-fund-accounts/<fid>")
def read_pool(fid):
    ctx = guard(READ_ROLES, path_refs=(("trade_fund_account", fid),))
    return ok(D.ser_trade_fund_account(ctx.get("trade_fund_account")))


@bp.post("/rmn/trade-fund-accounts/<fid>/accruals")
def post_accrual(fid):
    specs = (
        F("accrual_amount_cents", "integer", required=True, minimum=0),
        F("accrual_reference", "string", required=True),
    )
    ctx = guard(WRITE_ROLES, path_refs=(("trade_fund_account", fid),),
                body_specs=specs, mutating=True)
    pool = ctx.get("trade_fund_account")
    if pool["account_status"] != "OPEN":
        fail("ERR_TRADE_FUND_FROZEN",
             "The fund account is %s." % pool["account_status"])
    if ctx.data["accrual_amount_cents"] < D.MIN_ACCRUAL_CENTS:
        fail("ERR_AMOUNT_BELOW_MINIMUM",
             "accrual_amount_cents must be at least %d." % D.MIN_ACCRUAL_CENTS)
    pool["accrued_cents"] += ctx.data["accrual_amount_cents"]
    touch(pool)
    return ok(D.ser_trade_fund_account(pool))


@bp.post("/rmn/trade-fund-accounts/<fid>/deductions")
def post_deduction(fid):
    specs = (
        F("deduction_amount_cents", "integer", required=True, minimum=0),
        F("deduction_reference", "string", required=True),
        F("expected_trade_fund_account_version", "integer", required=True),
    )
    ctx = guard(WRITE_ROLES, path_refs=(("trade_fund_account", fid),),
                body_specs=specs,
                occ=("expected_trade_fund_account_version",
                     "trade_fund_account", "ERR_STALE_TRADE_FUND_VERSION"),
                mutating=True)
    pool = ctx.get("trade_fund_account")
    if pool["account_status"] != "OPEN":
        fail("ERR_TRADE_FUND_FROZEN",
             "The fund account is %s." % pool["account_status"])
    amount = ctx.data["deduction_amount_cents"]
    if D.pool_available(pool) < amount:
        fail("ERR_TRADE_FUND_INSUFFICIENT",
             "The drawable amount does not cover the deduction.")
    pool["_manual_deducted_cents"] += amount
    touch(pool)
    return ok(D.ser_trade_fund_account(pool))


@bp.post("/rmn/trade-fund-accounts/<fid>/freeze")
def freeze_pool(fid):
    specs = (F("frozen_reason", "enum", required=True, enum=FROZEN_REASONS),)
    ctx = guard(WRITE_ROLES, path_refs=(("trade_fund_account", fid),),
                body_specs=specs, mutating=True)
    pool = ctx.get("trade_fund_account")
    if pool["account_status"] != "OPEN":
        fail("ERR_TRADE_FUND_FROZEN",
             "Only an OPEN fund account may be frozen; this one is %s."
             % pool["account_status"])
    pool["account_status"] = "FROZEN"
    pool["frozen_reason"] = ctx.data["frozen_reason"]
    touch(pool)
    return ok(D.ser_trade_fund_account(pool))


@bp.post("/rmn/trade-fund-accounts/<fid>/unfreeze")
def unfreeze_pool(fid):
    specs = (F("run_reconciliation", "boolean", default=False, has_default=True),)
    ctx = guard(WRITE_ROLES, path_refs=(("trade_fund_account", fid),),
                body_specs=specs, mutating=True)
    pool = ctx.get("trade_fund_account")
    if pool["account_status"] != "FROZEN":
        fail("ERR_TRADE_FUND_FROZEN",
             "Only a FROZEN fund account may be unfrozen; this one is %s."
             % pool["account_status"])
    if D.pool_available(pool) < 0:
        fail("ERR_TRADE_FUND_INSUFFICIENT",
             "The drawable amount is still negative.")
    if ctx.data["run_reconciliation"]:
        pool["account_status"] = "RECONCILING"
        pool["last_reconciled_at"] = now()
    pool["account_status"] = "OPEN"
    pool["frozen_reason"] = "NONE"
    touch(pool)
    H.revive_plans_for_pool(pool)
    return ok(D.ser_trade_fund_account(pool))
