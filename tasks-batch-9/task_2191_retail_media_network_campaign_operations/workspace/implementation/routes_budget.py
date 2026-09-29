"""Budget plans: the fiscal-period cash container (PRD 3.2)."""
from flask import Blueprint

from core import F, fail, insert, new_row, now, ok, rows, touch
import derive as D
import helpers as H
from guard import guard

bp = Blueprint("budget_plans", __name__)

CREATE_ROLES = ("NetworkAdmin", "AccountManager", "AdvertiserUser")
READ_ROLES = ("NetworkAdmin", "AccountManager", "CreditAnalyst", "BillingOps",
              "AdvertiserUser")

PLAN_TRANSITIONS = {
    "submit": {"DRAFT": "PENDING_APPROVAL"},
    "approve": {"PENDING_APPROVAL": "APPROVED"},
    "return": {"PENDING_APPROVAL": "DRAFT"},
    "top_up": {"ACTIVE": "ACTIVE", "EXHAUSTED": "ACTIVE"},
    "close": {"ACTIVE": "CLOSED", "EXHAUSTED": "CLOSED"},
}

LIST_FILTERS = (
    ("advertiser_id", "advertiser_id", "string"),
    ("fiscal_period_code", "fiscal_period_code", "string"),
    ("plan_status", "plan_status", "string"),
)


@bp.post("/rmn/budget-plans")
def create_plan():
    specs = (
        F("advertiser_id", "string", required=True),
        F("fiscal_period_code", "string", required=True),
        F("committed_total_cents", "integer", required=True, minimum=100000),
        F("trade_fund_share_cents", "integer", minimum=0, default=0,
          has_default=True),
        F("window_start_at", "datetime", required=True),
        F("window_end_at", "datetime", required=True),
        F("expected_advertiser_version", "integer", required=True),
    )
    ctx = guard(CREATE_ROLES, body_specs=specs,
                body_refs=(("advertiser", "advertiser_id"),),
                occ=("expected_advertiser_version", "advertiser",
                     "ERR_STALE_ADVERTISER_VERSION"),
                mutating=True)
    data = ctx.data
    H.require_fiscal_period(data["fiscal_period_code"])
    if data["window_start_at"] >= data["window_end_at"]:
        fail("ERR_VALIDATION", "window_start_at must precede window_end_at.")
    if data["trade_fund_share_cents"] > data["committed_total_cents"]:
        fail("ERR_CAP_EXCEEDS_PARENT_LIMIT",
             "trade_fund_share_cents may not exceed committed_total_cents.")

    row = new_row()
    row.update({
        "advertiser_id": data["advertiser_id"],
        "fiscal_period_code": data["fiscal_period_code"],
        "plan_status": "DRAFT",
        "committed_total_cents": data["committed_total_cents"],
        "trade_fund_share_cents": data["trade_fund_share_cents"],
        "top_up_total_cents": 0,
        "window_start_at": data["window_start_at"],
        "window_end_at": data["window_end_at"],
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "revision_round": 0,
        "exhausted_at": None,
    })
    insert("budget_plan", row)
    return ok(D.ser_budget_plan(row), 201)


@bp.get("/rmn/budget-plans")
def list_plans():
    ctx = guard(READ_ROLES, paginated=True)
    return H.respond_list(ctx, "budget_plan", rows("budget_plan"),
                          LIST_FILTERS, owner_kind="budget_plan")


@bp.get("/rmn/budget-plans/<pid>")
def read_plan(pid):
    ctx = guard(READ_ROLES, path_refs=(("budget_plan", pid),))
    return ok(D.ser_budget_plan(ctx.get("budget_plan")))


@bp.post("/rmn/budget-plans/<pid>/submit")
def submit_plan(pid):
    specs = (F("submission_note", "string"),)
    ctx = guard(CREATE_ROLES, path_refs=(("budget_plan", pid),),
                body_specs=specs, mutating=True)
    plan = ctx.get("budget_plan")
    target = H.require_transition(plan["plan_status"],
                                  PLAN_TRANSITIONS["submit"],
                                  "ERR_PLAN_INVALID_STATE", "plan_status")
    share = plan["trade_fund_share_cents"]
    if share > 0:
        pool = D.pool_for(plan["advertiser_id"], plan["fiscal_period_code"])
        if pool is None:
            fail("ERR_TRADE_FUND_INSUFFICIENT",
                 "No trade fund pool exists for this advertiser and period.")
        if pool["account_status"] != "OPEN":
            fail("ERR_TRADE_FUND_FROZEN",
                 "The trade fund pool is %s." % pool["account_status"])
        if D.pool_available(pool) < share:
            fail("ERR_TRADE_FUND_INSUFFICIENT",
                 "The pool cannot cover trade_fund_share_cents.")
    if plan["committed_total_cents"] < 100000:
        fail("ERR_AMOUNT_BELOW_MINIMUM",
             "committed_total_cents must be at least 100000.")
    plan["submitted_by_user_id"] = ctx.user_id
    plan["plan_status"] = target
    touch(plan)
    return ok(D.ser_budget_plan(plan))


@bp.post("/rmn/budget-plans/<pid>/approve")
def approve_plan(pid):
    specs = (F("approval_note", "string"),)
    ctx = guard(("NetworkAdmin", "CreditAnalyst"),
                path_refs=(("budget_plan", pid),), body_specs=specs,
                mutating=True)
    plan = ctx.get("budget_plan")
    adv = ctx.get("advertiser")
    if adv["onboarding_status"] != "ACTIVE":
        fail("ERR_ADVERTISER_NOT_ACTIVE",
             "The advertiser is %s." % adv["onboarding_status"])
    target = H.require_transition(plan["plan_status"],
                                  PLAN_TRANSITIONS["approve"],
                                  "ERR_PLAN_INVALID_STATE", "plan_status")
    if ctx.user_id == plan["submitted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The operator that submitted the plan may not approve it.")
    for other in D.plans_of_advertiser(plan["advertiser_id"]):
        if other["id"] == plan["id"]:
            continue
        if other["plan_status"] not in ("APPROVED", "ACTIVE"):
            continue
        if plan["window_start_at"] < other["window_end_at"] and \
                other["window_start_at"] < plan["window_end_at"]:
            fail("ERR_PLAN_WINDOW_OVERLAP",
                 "Another approved or active plan overlaps this window.")
    if D.advertiser_exposure(adv) + D.plan_cash_share(plan) > \
            D.effective_credit_limit(adv):
        fail("ERR_CREDIT_LIMIT_EXCEEDED",
             "The plan's cash share exceeds the remaining credit headroom.")

    plan["approved_by_user_id"] = ctx.user_id
    plan["plan_status"] = target
    touch(plan)
    if now() >= plan["window_start_at"] and adv["onboarding_status"] == "ACTIVE":
        plan["plan_status"] = "ACTIVE"
    return ok(D.ser_budget_plan(plan))


@bp.post("/rmn/budget-plans/<pid>/return-for-revision")
def return_plan(pid):
    specs = (F("revision_reason", "string", required=True),)
    ctx = guard(("NetworkAdmin", "CreditAnalyst"),
                path_refs=(("budget_plan", pid),), body_specs=specs,
                mutating=True)
    plan = ctx.get("budget_plan")
    H.require_transition(plan["plan_status"], PLAN_TRANSITIONS["return"],
                         "ERR_PLAN_INVALID_STATE", "plan_status")
    if plan["revision_round"] > D.MAX_REVISION_ROUNDS:
        fail("ERR_MAX_ROUNDS_EXCEEDED",
             "revision_round has passed the maximum of %d."
             % D.MAX_REVISION_ROUNDS)
    if plan["revision_round"] >= D.MAX_REVISION_ROUNDS:
        # the revision budget is spent: the plan terminates instead, releasing
        # its trade fund reservation.
        plan["plan_status"] = "REJECTED"
    else:
        plan["plan_status"] = "DRAFT"
        plan["revision_round"] = plan["revision_round"] + 1
        plan["submitted_by_user_id"] = None
    touch(plan)
    return ok(D.ser_budget_plan(plan))


@bp.post("/rmn/budget-plans/<pid>/top-up")
def top_up_plan(pid):
    specs = (
        F("top_up_amount_cents", "integer", required=True, minimum=0),
        F("top_up_reason", "string"),
    )
    ctx = guard(("NetworkAdmin", "AccountManager", "CreditAnalyst"),
                path_refs=(("budget_plan", pid),), body_specs=specs,
                mutating=True)
    plan = ctx.get("budget_plan")
    adv = ctx.get("advertiser")
    if adv["onboarding_status"] != "ACTIVE":
        fail("ERR_ADVERTISER_NOT_ACTIVE",
             "The advertiser is %s." % adv["onboarding_status"])
    target = H.require_transition(plan["plan_status"],
                                  PLAN_TRANSITIONS["top_up"],
                                  "ERR_PLAN_INVALID_STATE", "plan_status")
    if now() >= plan["window_end_at"]:
        fail("ERR_PLAN_INVALID_STATE", "The plan window has already elapsed.")
    if ctx.data["top_up_amount_cents"] < D.MIN_TOP_UP_CENTS:
        fail("ERR_AMOUNT_BELOW_MINIMUM",
             "top_up_amount_cents must be at least %d." % D.MIN_TOP_UP_CENTS)
    plan["top_up_total_cents"] += ctx.data["top_up_amount_cents"]
    plan["plan_status"] = target
    plan["exhausted_at"] = None
    touch(plan)
    return ok(D.ser_budget_plan(plan))


@bp.post("/rmn/budget-plans/<pid>/close")
def close_plan(pid):
    specs = (F("closure_note", "string"),)
    ctx = guard(("NetworkAdmin", "BillingOps"),
                path_refs=(("budget_plan", pid),), body_specs=specs,
                mutating=True)
    plan = ctx.get("budget_plan")
    target = H.require_transition(plan["plan_status"],
                                  PLAN_TRANSITIONS["close"],
                                  "ERR_PLAN_INVALID_STATE", "plan_status")
    if now() < plan["window_end_at"]:
        fail("ERR_PLAN_INVALID_STATE", "The plan window has not yet elapsed.")
    for camp in D.campaigns_of_plan(plan["id"]):
        if camp["delivery_status"] in ("SCHEDULED", "DELIVERING", "PAUSED"):
            fail("ERR_INVALID_CAMPAIGN_TRANSITION",
                 "A campaign on this plan is still %s."
                 % camp["delivery_status"])
    for inv in D.invoices_of_plan(plan["id"]):
        if inv["invoice_status"] not in ("SETTLED", "WRITTEN_OFF"):
            fail("ERR_INVOICE_INVALID_STATE",
                 "An invoice on this plan is still %s." % inv["invoice_status"])
    plan["plan_status"] = target
    touch(plan)
    return ok(D.ser_budget_plan(plan))
