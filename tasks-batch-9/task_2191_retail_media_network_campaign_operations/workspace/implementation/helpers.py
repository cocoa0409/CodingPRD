"""Listing / filtering helpers, the billing dimension, and the cascades that
more than one route module needs.
"""
import re

from flask import request

from core import db, fail, now, ok_list, paginate, sort_rows, touch
import derive as D
from guard import advertiser_id_of

FISCAL_RE = re.compile(r"^\d{4}-Q[1-4]$")
BILLING_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
BRAND_CODE_RE = re.compile(r"^[A-Z0-9]{3,12}$")


# ---------------------------------------------------------------------------
# Collection reads
# ---------------------------------------------------------------------------
def _match(row, field, raw, kind):
    value = row.get(field)
    if kind == "bool":
        low = raw.strip().lower()
        if low in ("true", "1"):
            return bool(value) is True
        if low in ("false", "0"):
            return bool(value) is False
        return False
    return value == raw


def respond_list(ctx, kind, all_rows, specs, owner_kind=None):
    """Applies the ownership scope, the declared filters, the mandatory
    created_at ordering and the offset/limit window."""
    rows_ = list(all_rows)
    if ctx.role == "AdvertiserUser" and owner_kind is not None:
        rows_ = [r for r in rows_
                 if advertiser_id_of(owner_kind, r) == ctx.user_id]
    for name, field, ftype in specs:
        raw = request.args.get(name)
        if raw is None:
            continue
        rows_ = [r for r in rows_ if _match(r, field, raw, ftype)]
    rows_ = sort_rows(rows_)
    window, total = paginate(rows_, ctx.limit, ctx.offset)
    return ok_list(D.ser_many(kind, window), total, ctx.limit, ctx.offset)


# ---------------------------------------------------------------------------
# The billing dimension (PRD 2.10 -- delivery never writes billing directly)
# ---------------------------------------------------------------------------
BILLING_TRANSITIONS = {
    "UNBILLED": ("ACCRUING",),
    "ACCRUING": ("PENDING_INVOICE",),
    "PENDING_INVOICE": ("INVOICED",),
    "INVOICED": ("DISPUTED", "RECONCILED"),
    "DISPUTED": ("INVOICED", "RECONCILED"),
    "RECONCILED": (),
}


def fire_billing(camp, target):
    """Fires a billing transition.  Silently no-ops when the precondition of
    the billing machine itself does not hold."""
    if target in BILLING_TRANSITIONS.get(camp["billing_status"], ()):
        camp["billing_status"] = target
        touch(camp)
        return True
    return False


# ---------------------------------------------------------------------------
# Line item / campaign pause + end cascades
# ---------------------------------------------------------------------------
def pause_line_item(li, reason):
    li["line_item_status"] = "MANUAL_PAUSED"
    li["pause_reason"] = reason
    li["last_pause_at"] = now()
    touch(li)


def end_line_item(li):
    """Entering ENDED surrenders the slot occupancy and the reservation."""
    li["line_item_status"] = "ENDED"
    li["reserved_cents"] = 0
    touch(li)
    slot = D.slot_of_line_item(li)
    if slot is not None:
        touch(slot)


def campaign_rollup_pause(camp):
    """A campaign with nothing still SERVING rolls up from DELIVERING."""
    if camp["delivery_status"] != "DELIVERING":
        return False
    serving = [l for l in D.line_items_of_campaign(camp["id"])
               if l["line_item_status"] == "SERVING"]
    if serving:
        return False
    camp["delivery_status"] = "PAUSED"
    touch(camp)
    return True


# ---------------------------------------------------------------------------
# Advertiser suspension: the depth-three cascade of PRD 3.1
# ---------------------------------------------------------------------------
def suspend_advertiser(adv, reason):
    adv["onboarding_status"] = "SUSPENDED"
    adv["suspension_reason"] = reason
    touch(adv)
    for camp in D.campaigns_of_advertiser(adv["id"]):
        if camp["delivery_status"] not in ("SCHEDULED", "DELIVERING"):
            continue
        camp["delivery_status"] = "PAUSED"
        touch(camp)
        for li in D.line_items_of_campaign(camp["id"]):
            if li["line_item_status"] in ("ELIGIBLE", "SERVING"):
                pause_line_item(li, "MANUAL")
                # level three: the slot's occupancy_count is recomputed and
                # comes back unchanged, so the slot row itself is untouched.


# ---------------------------------------------------------------------------
# Budget plan exhaustion: the depth-three cascade of PRD 3.2 / 3.6
# ---------------------------------------------------------------------------
def exhaust_plan_if_drained(plan):
    if plan["plan_status"] != "ACTIVE":
        return False
    if D.plan_available(plan) > 0:
        return False
    plan["plan_status"] = "EXHAUSTED"
    plan["exhausted_at"] = now()
    touch(plan)
    for camp in D.campaigns_of_plan(plan["id"]):
        if camp["delivery_status"] != "DELIVERING":
            continue
        camp["delivery_status"] = "PAUSED"
        touch(camp)
        for li in D.line_items_of_campaign(camp["id"]):
            if li["line_item_status"] == "SERVING":
                pause_line_item(li, "BUDGET_EXHAUSTED")
    return True


def promote_plan_active(plan):
    """An APPROVED plan whose window has opened becomes ACTIVE."""
    if plan["plan_status"] == "APPROVED":
        plan["plan_status"] = "ACTIVE"
        touch(plan)
        return True
    return False


# ---------------------------------------------------------------------------
# Exposure driven suspension (invoice issuance / write-off)
# ---------------------------------------------------------------------------
def enforce_credit_limit(adv):
    if adv["onboarding_status"] != "ACTIVE":
        return False
    if D.advertiser_exposure(adv) > D.effective_credit_limit(adv):
        suspend_advertiser(adv, "CREDIT_BREACH")
        return True
    return False


# ---------------------------------------------------------------------------
# Pool freeze / unfreeze consequences
# ---------------------------------------------------------------------------
def unfreeze_overdrawn_pool(pool):
    """A pool frozen OVERDRAWN whose drawable amount is restored reopens, and
    that reopening returns drained plans of the same period to ACTIVE."""
    if pool is None:
        return False
    if pool["account_status"] != "FROZEN" or pool["frozen_reason"] != "OVERDRAWN":
        return False
    if D.pool_available(pool) < 0:
        return False
    pool["account_status"] = "OPEN"
    pool["frozen_reason"] = "NONE"
    touch(pool)
    revive_plans_for_pool(pool)
    return True


def revive_plans_for_pool(pool):
    for plan in db.budget_plans.values():
        if plan["advertiser_id"] != pool["advertiser_id"]:
            continue
        if plan["fiscal_period_code"] != pool["fiscal_period_code"]:
            continue
        if plan["plan_status"] != "EXHAUSTED":
            continue
        if D.plan_available(plan) > 0:
            plan["plan_status"] = "ACTIVE"
            plan["exhausted_at"] = None
            touch(plan)


# ---------------------------------------------------------------------------
# Invoice <-> dispute coupling (PRD 3.8)
# ---------------------------------------------------------------------------
OPEN_DISPUTE_STATES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED",
                       "ESCALATED", "UPHELD")
ACTIVE_DISPUTE_STATES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED",
                         "ESCALATED")


def restore_invoice_if_clear(invoice):
    """As soon as no dispute on the invoice is still open the invoice returns
    from DISPUTED to ISSUED and its campaigns from DISPUTED to INVOICED."""
    if invoice["invoice_status"] != "DISPUTED":
        return False
    if any(d["dispute_status"] in OPEN_DISPUTE_STATES
           for d in D.disputes_of_invoice(invoice["id"])):
        return False
    invoice["invoice_status"] = "ISSUED"
    touch(invoice)
    for camp in D.campaigns_of_plan(invoice["budget_plan_id"]):
        if camp["billing_status"] == "DISPUTED":
            fire_billing(camp, "INVOICED")
    return True


# ---------------------------------------------------------------------------
# Validation shorthands used by several modules
# ---------------------------------------------------------------------------
def require_fiscal_period(code):
    if not FISCAL_RE.match(code or ""):
        fail("ERR_VALIDATION",
             "fiscal_period_code must match YYYY-Qn with n between 1 and 4.")


def require_billing_period(code):
    if not BILLING_PERIOD_RE.match(code or ""):
        fail("ERR_VALIDATION",
             "billing_period_code must match YYYY-MM with a month of 01..12.")


def require_brand_code(code):
    if not BRAND_CODE_RE.match(code or ""):
        fail("ERR_VALIDATION",
             "brand_code must be 3 to 12 characters of A-Z and 0-9.")


def require_transition(current, table, error_id, label="state"):
    if current not in table:
        fail(error_id, "No transition is declared from %s '%s'." % (label, current))
    return table[current]


def quarter_of_billing_period(code):
    year, month = code.split("-")
    quarter = (int(month) - 1) // 3 + 1
    return "%s-Q%d" % (year, quarter)
