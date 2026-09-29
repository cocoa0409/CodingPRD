"""Invoicing, the trade fund waterfall and measurement disputes
(PRD 3.8 and 3.9)."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint

from core import F, db, dec, fail, insert, new_row, now, ok, rhu, rows, touch
import derive as D
import helpers as H
from guard import guard

bp = Blueprint("billing", __name__)

INVOICE_WRITE = ("NetworkAdmin", "BillingOps")
INVOICE_READ = ("NetworkAdmin", "BillingOps", "CreditAnalyst",
                "AccountManager", "AdvertiserUser")
DISPUTE_FILE = ("NetworkAdmin", "AccountManager", "AdvertiserUser")
DISPUTE_READ = ("NetworkAdmin", "MeasurementAnalyst", "BillingOps",
                "AccountManager", "AdvertiserUser")
ANALYST_ROLES = ("NetworkAdmin", "MeasurementAnalyst")

DISPUTE_CATEGORIES = ("IMPRESSION_DISCREPANCY", "ATTRIBUTION_WINDOW",
                      "OFFSITE_SPEND_VARIANCE", "INCREMENTALITY_RESTATEMENT")

INVOICE_TRANSITIONS = {
    "issue": {"DRAFT": "ISSUED"},
    "adjust": {"DISPUTED": "ADJUSTED"},
    "settle": {"ISSUED": "SETTLED", "ADJUSTED": "SETTLED"},
    "write_off": {"ISSUED": "WRITTEN_OFF", "ADJUSTED": "WRITTEN_OFF"},
}

DISPUTE_TRANSITIONS = {
    "start_review": {"SUBMITTED": "UNDER_REVIEW"},
    "request_info": {"UNDER_REVIEW": "INFO_REQUESTED"},
    "provide_info": {"INFO_REQUESTED": "UNDER_REVIEW"},
    "UPHOLD": {"UNDER_REVIEW": "UPHELD", "ESCALATED": "UPHELD"},
    "REJECT": {"UNDER_REVIEW": "REJECTED", "ESCALATED": "REJECTED"},
    "escalate": {"UNDER_REVIEW": "ESCALATED", "INFO_REQUESTED": "ESCALATED"},
    "withdraw": {"SUBMITTED": "WITHDRAWN", "INFO_REQUESTED": "WITHDRAWN"},
}

INVOICE_FILTERS = (
    ("advertiser_id", "advertiser_id", "string"),
    ("budget_plan_id", "budget_plan_id", "string"),
    ("trade_fund_account_id", "trade_fund_account_id", "string"),
    ("billing_period_code", "billing_period_code", "string"),
    ("invoice_status", "invoice_status", "string"),
)
DISPUTE_FILTERS = (
    ("invoice_id", "invoice_id", "string"),
    ("line_item_id", "line_item_id", "string"),
    ("dispute_category", "dispute_category", "string"),
    ("dispute_status", "dispute_status", "string"),
    ("sla_breached", "sla_breached", "bool"),
)

TIER_BREAK_LOW = 1000000
TIER_BREAK_HIGH = 5000000


# ---------------------------------------------------------------------------
# Calculation 9: the ten pinned steps of the settlement waterfall
# ---------------------------------------------------------------------------
def billing_month_window(code):
    year, month = (int(part) for part in code.split("-"))
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = start.replace(year=year + 1, month=1)
    else:
        end = start.replace(month=month + 1)
    return start, end


def _onsite_spend(inv):
    """Step one."""
    start, end = billing_month_window(inv["billing_period_code"])
    ids = set()
    for camp in D.campaigns_of_plan(inv["budget_plan_id"]):
        for li in D.line_items_of_campaign(camp["id"]):
            ids.add(li["id"])
    total = 0
    for auc in D.settled_auctions():
        if auc.get("winning_line_item_id") not in ids:
            continue
        if not (start <= auc["requested_at"] < end):
            continue
        slot = db.placement_slots.get(auc["placement_slot_id"])
        if slot is not None and slot["channel"] == "ONSITE":
            total += auc["settled_spend_cents"]
    return total


def _offsite_spend(inv):
    """Step two, on whichever basis the reconciliation selected."""
    return sum(D.offsite_billable(camp)
               for camp in D.campaigns_of_plan(inv["budget_plan_id"]))


def _variance_pct(inv):
    best = Decimal("0.00")
    for camp in sorted(D.campaigns_of_plan(inv["budget_plan_id"]),
                       key=lambda c: (c["created_at"], c["_seq"])):
        value = D.offsite_variance_dec(camp)
        if abs(value) > abs(best):
            best = value
    return float(best)


def _upheld_credit(inv):
    """Step five."""
    return sum(d["approved_credit_cents"]
               for d in D.disputes_of_invoice(inv["id"])
               if d["dispute_status"] == "UPHELD")


def _tier_rate(billable):
    """Step seven."""
    if billable < TIER_BREAK_LOW:
        return Decimal("0.20")
    if billable < TIER_BREAK_HIGH:
        return Decimal("0.35")
    return Decimal("0.50")


def _pool_available_excluding(pool, inv):
    available = D.pool_available(pool)
    if inv["invoice_status"] in ("ISSUED", "DISPUTED", "ADJUSTED", "SETTLED"):
        available += inv["trade_fund_deduction_cents"]
    return available


def _plan_share_headroom(inv, plan):
    taken = 0
    for other in D.invoices_of_plan(plan["id"]):
        if other["id"] == inv["id"]:
            continue
        if other["invoice_status"] in ("ISSUED", "DISPUTED", "ADJUSTED",
                                       "SETTLED"):
            taken += other["trade_fund_deduction_cents"]
    return plan["trade_fund_share_cents"] - taken


def run_waterfall(inv, from_step_six=False, extra_credit=0):
    """Steps four through ten; steps one to three are refreshed only at
    issuance."""
    adv = db.advertisers[inv["advertiser_id"]]
    plan = db.budget_plans[inv["budget_plan_id"]]
    pool = db.trade_fund_accounts.get(inv["trade_fund_account_id"])
    if not from_step_six:
        inv["onsite_spend_cents"] = _onsite_spend(inv)
        inv["offsite_spend_cents"] = _offsite_spend(inv)
        inv["gross_spend_cents"] = (inv["onsite_spend_cents"]
                                    + inv["offsite_spend_cents"])
        inv["variance_pct"] = _variance_pct(inv)
    # step four
    inv["managed_service_fee_cents"] = rhu(
        dec(inv["gross_spend_cents"]) * dec(adv["managed_service_fee_pct"]))
    # step five
    inv["dispute_credit_cents"] = _upheld_credit(inv) + extra_credit
    # step six
    billable = (inv["gross_spend_cents"] + inv["managed_service_fee_cents"]
                - inv["dispute_credit_cents"])
    if billable < 0:
        billable = 0
    # steps seven, eight and nine
    if pool is None:
        deduction = 0
    else:
        rate = _tier_rate(billable)
        ceiling = min(
            rhu(dec(inv["gross_spend_cents"]) * dec(pool["deduction_cap_pct"])),
            rhu(dec(billable) * rate),
            _pool_available_excluding(pool, inv),
            _plan_share_headroom(inv, plan),
        )
        deduction = max(0, ceiling)
    inv["trade_fund_deduction_cents"] = deduction
    # step ten
    inv["net_cash_due_cents"] = max(0, billable - deduction)
    return billable


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------
@bp.post("/rmn/invoices")
def create_invoice():
    specs = (
        F("advertiser_id", "string", required=True),
        F("budget_plan_id", "string", required=True),
        F("trade_fund_account_id", "string", nullable=True),
        F("billing_period_code", "string", required=True),
    )
    ctx = guard(INVOICE_WRITE, body_specs=specs,
                body_refs=(("advertiser", "advertiser_id"),
                           ("budget_plan", "budget_plan_id"),
                           ("trade_fund_account", "trade_fund_account_id")),
                mutating=True)
    data = ctx.data
    plan = ctx.get("budget_plan")
    pool = ctx.get("trade_fund_account")
    H.require_billing_period(data["billing_period_code"])
    for other in rows("invoice"):
        if other["advertiser_id"] == data["advertiser_id"] and \
                other["billing_period_code"] == data["billing_period_code"]:
            fail("ERR_DUPLICATE_INVOICE_PERIOD",
                 "This advertiser already has an invoice for the period.")
    if plan["advertiser_id"] != data["advertiser_id"] or \
            (pool is not None and pool["advertiser_id"] != data["advertiser_id"]):
        fail("ERR_CROSS_ADVERTISER_REFERENCE",
             "The funding plan and fund account must belong to the invoiced "
             "advertiser.")
    if pool is not None and pool["fiscal_period_code"] != \
            plan["fiscal_period_code"]:
        fail("ERR_FISCAL_PERIOD_MISMATCH",
             "The fund account period differs from the funding plan period.")
    row = new_row()
    row.update({
        "advertiser_id": data["advertiser_id"],
        "budget_plan_id": plan["id"],
        "trade_fund_account_id": (pool["id"] if pool is not None else None),
        "invoice_status": "DRAFT",
        "billing_period_code": data["billing_period_code"],
        "onsite_spend_cents": 0,
        "offsite_spend_cents": 0,
        "gross_spend_cents": 0,
        "managed_service_fee_cents": 0,
        "trade_fund_deduction_cents": 0,
        "dispute_credit_cents": 0,
        "net_cash_due_cents": 0,
        "variance_pct": 0.0,
        "adjustment_round": 0,
        "issued_at": None,
        "due_at": None,
        "settled_at": None,
        "issued_by_user_id": None,
    })
    insert("invoice", row)
    return ok(D.ser_invoice(row), 201)


@bp.get("/rmn/invoices")
def list_invoices():
    ctx = guard(INVOICE_READ, paginated=True)
    return H.respond_list(ctx, "invoice", rows("invoice"), INVOICE_FILTERS,
                          owner_kind="invoice")


@bp.get("/rmn/invoices/<iid>")
def read_invoice(iid):
    ctx = guard(INVOICE_READ, path_refs=(("invoice", iid),))
    return ok(D.ser_invoice(ctx.get("invoice")))


@bp.post("/rmn/invoices/<iid>/issue")
def issue_invoice(iid):
    specs = (F("issue_note", "string"),)
    ctx = guard(INVOICE_WRITE, path_refs=(("invoice", iid),), body_specs=specs,
                mutating=True)
    inv = ctx.get("invoice")
    adv = ctx.get("advertiser")
    plan = db.budget_plans[inv["budget_plan_id"]]
    pool = db.trade_fund_accounts.get(inv["trade_fund_account_id"])
    target = H.require_transition(inv["invoice_status"],
                                  INVOICE_TRANSITIONS["issue"],
                                  "ERR_INVOICE_INVALID_STATE", "invoice_status")
    if pool is not None and pool["account_status"] != "OPEN":
        fail("ERR_TRADE_FUND_FROZEN",
             "The trade fund pool is %s." % pool["account_status"])
    if adv["onboarding_status"] not in ("ACTIVE", "SUSPENDED"):
        fail("ERR_ADVERTISER_NOT_ACTIVE",
             "The advertiser is %s." % adv["onboarding_status"])
    for camp in D.campaigns_of_plan(plan["id"]):
        if camp["billing_status"] not in ("PENDING_INVOICE", "INVOICED",
                                         "RECONCILED"):
            fail("ERR_INVALID_CAMPAIGN_TRANSITION",
                 "A campaign on the plan is %s." % camp["billing_status"])
    available_before = D.pool_available(pool) if pool is not None else 0
    run_waterfall(inv)
    if inv["gross_spend_cents"] < 1:
        inv["onsite_spend_cents"] = 0
        inv["offsite_spend_cents"] = 0
        inv["gross_spend_cents"] = 0
        inv["managed_service_fee_cents"] = 0
        inv["dispute_credit_cents"] = 0
        inv["trade_fund_deduction_cents"] = 0
        inv["net_cash_due_cents"] = 0
        fail("ERR_NOTHING_TO_INVOICE",
             "The computed gross_spend_cents is 0.")

    overdrawn = False
    if pool is not None and inv["trade_fund_deduction_cents"] > available_before:
        inv["trade_fund_deduction_cents"] = max(0, available_before)
        billable = (inv["gross_spend_cents"] + inv["managed_service_fee_cents"]
                    - inv["dispute_credit_cents"])
        inv["net_cash_due_cents"] = max(
            0, max(0, billable) - inv["trade_fund_deduction_cents"])
        overdrawn = True

    inv["issued_at"] = now()
    inv["due_at"] = now() + timedelta(days=D.NET_TERMS_DAYS)
    inv["issued_by_user_id"] = ctx.user_id
    inv["invoice_status"] = target
    touch(inv)
    for camp in D.campaigns_of_plan(plan["id"]):
        if camp["billing_status"] == "PENDING_INVOICE":
            H.fire_billing(camp, "INVOICED")
    if pool is not None:
        if overdrawn or D.pool_available(pool) < 0:
            pool["account_status"] = "FROZEN"
            pool["frozen_reason"] = "OVERDRAWN"
        touch(pool)
    H.enforce_credit_limit(adv)
    touch(adv)
    return ok(D.ser_invoice(inv))


@bp.post("/rmn/invoices/<iid>/adjust")
def adjust_invoice(iid):
    specs = (
        F("adjustment_amount_cents", "integer", required=True, minimum=0),
        F("adjustment_reason", "string", required=True),
    )
    ctx = guard(INVOICE_WRITE, path_refs=(("invoice", iid),), body_specs=specs,
                mutating=True)
    inv = ctx.get("invoice")
    adv = ctx.get("advertiser")
    pool = db.trade_fund_accounts.get(inv["trade_fund_account_id"])
    target = H.require_transition(inv["invoice_status"],
                                  INVOICE_TRANSITIONS["adjust"],
                                  "ERR_INVOICE_INVALID_STATE", "invoice_status")
    if not any(d["dispute_status"] == "UPHELD"
               for d in D.disputes_of_invoice(inv["id"])):
        fail("ERR_DISPUTE_INVALID_STATE",
             "At least one dispute on the invoice must be UPHELD.")
    if inv["adjustment_round"] >= D.MAX_ADJUSTMENT_ROUNDS:
        fail("ERR_MAX_ROUNDS_EXCEEDED",
             "adjustment_round has reached the maximum of %d."
             % D.MAX_ADJUSTMENT_ROUNDS)
    inv["adjustment_round"] += 1
    run_waterfall(inv, from_step_six=True,
                  extra_credit=ctx.data["adjustment_amount_cents"])
    inv["invoice_status"] = target
    touch(inv)
    if pool is not None:
        H.unfreeze_overdrawn_pool(pool)
        touch(pool)
    touch(adv)
    return ok(D.ser_invoice(inv))


@bp.post("/rmn/invoices/<iid>/settle")
def settle_invoice(iid):
    specs = (
        F("paid_amount_cents", "integer", required=True, minimum=0),
        F("payment_reference", "string", required=True),
    )
    ctx = guard(INVOICE_WRITE, path_refs=(("invoice", iid),), body_specs=specs,
                mutating=True)
    inv = ctx.get("invoice")
    adv = ctx.get("advertiser")
    target = H.require_transition(inv["invoice_status"],
                                  INVOICE_TRANSITIONS["settle"],
                                  "ERR_INVOICE_INVALID_STATE", "invoice_status")
    for dispute in D.disputes_of_invoice(inv["id"]):
        if dispute["dispute_status"] in H.ACTIVE_DISPUTE_STATES:
            fail("ERR_DISPUTE_INVALID_STATE",
                 "A dispute on the invoice is still %s."
                 % dispute["dispute_status"])
    if ctx.data["paid_amount_cents"] != inv["net_cash_due_cents"]:
        fail("ERR_SETTLEMENT_AMOUNT_MISMATCH",
             "paid_amount_cents must equal net_cash_due_cents exactly.")
    inv["settled_at"] = now()
    inv["invoice_status"] = target
    touch(inv)
    for camp in D.campaigns_of_plan(inv["budget_plan_id"]):
        if camp["billing_status"] in ("INVOICED", "DISPUTED"):
            H.fire_billing(camp, "RECONCILED")
    touch(adv)
    return ok(D.ser_invoice(inv))


@bp.post("/rmn/invoices/<iid>/write-off")
def write_off_invoice(iid):
    specs = (F("write_off_reason", "string", required=True),)
    ctx = guard(("NetworkAdmin",), path_refs=(("invoice", iid),),
                body_specs=specs, mutating=True)
    inv = ctx.get("invoice")
    adv = ctx.get("advertiser")
    pool = db.trade_fund_accounts.get(inv["trade_fund_account_id"])
    target = H.require_transition(inv["invoice_status"],
                                  INVOICE_TRANSITIONS["write_off"],
                                  "ERR_INVOICE_INVALID_STATE", "invoice_status")
    if ctx.user_id == inv["issued_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The operator that issued the invoice may not write it off.")
    if inv["due_at"] is None or \
            now() < inv["due_at"] + timedelta(days=D.WRITE_OFF_DAYS):
        fail("ERR_DISPUTE_WINDOW_CLOSED",
             "The write-off period has not elapsed yet.")
    inv["invoice_status"] = target
    touch(inv)
    if pool is not None:
        H.unfreeze_overdrawn_pool(pool)
        touch(pool)
    for camp in D.campaigns_of_plan(inv["budget_plan_id"]):
        if camp["billing_status"] in ("INVOICED", "DISPUTED"):
            H.fire_billing(camp, "RECONCILED")
    if adv["onboarding_status"] == "ACTIVE":
        H.suspend_advertiser(adv, "CREDIT_BREACH")
    else:
        touch(adv)
    return ok(D.ser_invoice(inv))


# ---------------------------------------------------------------------------
# Measurement disputes
# ---------------------------------------------------------------------------
def _dispute_campaign(dispute):
    li = db.line_items.get(dispute.get("line_item_id"))
    return D.campaign_of_line_item(li) if li is not None else None


@bp.post("/rmn/measurement-disputes")
def file_dispute():
    specs = (
        F("invoice_id", "string", required=True),
        F("dispute_category", "enum", required=True, enum=DISPUTE_CATEGORIES),
        F("claimed_amount_cents", "integer", required=True, minimum=1),
        F("line_item_id", "string", nullable=True),
        F("evidence_note", "string"),
        F("expected_invoice_version", "integer", required=True),
    )
    ctx = guard(DISPUTE_FILE, body_specs=specs,
                body_refs=(("line_item", "line_item_id"),
                           ("invoice", "invoice_id")),
                occ=("expected_invoice_version", "invoice",
                     "ERR_STALE_INVOICE_VERSION"),
                mutating=True)
    data = ctx.data
    inv = ctx.get("invoice")
    li = ctx.get("line_item")
    if inv["invoice_status"] not in ("ISSUED", "ADJUSTED"):
        fail("ERR_INVOICE_INVALID_STATE",
             "The invoice is %s." % inv["invoice_status"])
    if inv["due_at"] is None or \
            now() >= inv["due_at"] + timedelta(days=D.DISPUTE_GRACE_DAYS):
        fail("ERR_DISPUTE_WINDOW_CLOSED", "The dispute grace window is closed.")
    if li is not None:
        camp = D.campaign_of_line_item(li)
        if camp is None or camp["budget_plan_id"] != inv["budget_plan_id"]:
            fail("ERR_CROSS_ADVERTISER_REFERENCE",
                 "The line item does not belong to the invoice's funding plan.")
    if data["claimed_amount_cents"] > (inv["net_cash_due_cents"]
                                      + inv["trade_fund_deduction_cents"]):
        fail("ERR_CLAIM_EXCEEDS_INVOICE",
             "claimed_amount_cents exceeds what the invoice can give back.")

    row = new_row()
    row.update({
        "invoice_id": inv["id"],
        "line_item_id": (li["id"] if li is not None else None),
        "dispute_status": "SUBMITTED",
        "dispute_category": data["dispute_category"],
        "claimed_amount_cents": data["claimed_amount_cents"],
        "approved_credit_cents": 0,
        "filed_at": now(),
        "sla_response_hours": 0,
        "sla_due_at": None,
        "first_response_at": None,
        "info_request_count": 0,
        "review_rounds": 0,
        "sla_breached": False,
        "escalation_level": 0,
        "assigned_analyst_user_id": None,
        "resolved_by_user_id": None,
    })
    insert("dispute", row)
    D.recompute_sla(row)
    D.refresh_breach(row)
    if inv["invoice_status"] in ("ISSUED", "ADJUSTED"):
        inv["invoice_status"] = "DISPUTED"
    touch(inv)
    for camp in D.campaigns_of_plan(inv["budget_plan_id"]):
        if camp["billing_status"] == "INVOICED":
            H.fire_billing(camp, "DISPUTED")
    return ok(D.ser_dispute(row), 201)


@bp.get("/rmn/measurement-disputes")
def list_disputes():
    ctx = guard(DISPUTE_READ, paginated=True)
    return H.respond_list(ctx, "dispute", rows("dispute"), DISPUTE_FILTERS,
                          owner_kind="dispute")


@bp.get("/rmn/measurement-disputes/<did>")
def read_dispute(did):
    ctx = guard(DISPUTE_READ, path_refs=(("dispute", did),))
    return ok(D.ser_dispute(ctx.get("dispute")))


@bp.post("/rmn/measurement-disputes/<did>/start-review")
def start_review(did):
    specs = (F("assigned_analyst_user_id", "string", required=True),)
    ctx = guard(ANALYST_ROLES, path_refs=(("dispute", did),), body_specs=specs,
                mutating=True)
    dispute = ctx.get("dispute")
    inv = db.invoices[dispute["invoice_id"]]
    target = H.require_transition(dispute["dispute_status"],
                                  DISPUTE_TRANSITIONS["start_review"],
                                  "ERR_DISPUTE_INVALID_STATE", "dispute_status")
    if inv["invoice_status"] != "DISPUTED":
        fail("ERR_INVOICE_INVALID_STATE",
             "The invoice is %s." % inv["invoice_status"])
    if dispute["dispute_category"] == "INCREMENTALITY_RESTATEMENT":
        camp = _dispute_campaign(dispute)
        studies = D.studies_of_campaign(camp["id"]) if camp is not None else []
        if not any(s["study_status"] in ("PUBLISHED", "INVALIDATED")
                   for s in studies):
            fail("ERR_STUDY_INVALID_STATE",
                 "A restatement claim requires a measured study.")
    if dispute["first_response_at"] is None:
        dispute["first_response_at"] = now()
    dispute["assigned_analyst_user_id"] = ctx.user_id
    dispute["review_rounds"] += 1
    dispute["dispute_status"] = target
    D.refresh_breach(dispute)
    touch(dispute)
    return ok(D.ser_dispute(dispute))


@bp.post("/rmn/measurement-disputes/<did>/request-info")
def request_info(did):
    specs = (F("information_request_note", "string", required=True),)
    ctx = guard(ANALYST_ROLES, path_refs=(("dispute", did),), body_specs=specs,
                mutating=True)
    dispute = ctx.get("dispute")
    target = H.require_transition(dispute["dispute_status"],
                                  DISPUTE_TRANSITIONS["request_info"],
                                  "ERR_DISPUTE_INVALID_STATE", "dispute_status")
    if dispute["info_request_count"] >= D.MAX_INFO_REQUESTS:
        fail("ERR_MAX_INFO_REQUESTS_EXCEEDED",
             "info_request_count has reached the maximum of %d."
             % D.MAX_INFO_REQUESTS)
    dispute["info_request_count"] += 1
    dispute["dispute_status"] = target
    D.recompute_sla(dispute)
    D.refresh_breach(dispute)
    touch(dispute)
    return ok(D.ser_dispute(dispute))


@bp.post("/rmn/measurement-disputes/<did>/provide-info")
def provide_info(did):
    specs = (F("evidence_note", "string", required=True),)
    ctx = guard(DISPUTE_FILE, path_refs=(("dispute", did),), body_specs=specs,
                mutating=True)
    dispute = ctx.get("dispute")
    target = H.require_transition(dispute["dispute_status"],
                                  DISPUTE_TRANSITIONS["provide_info"],
                                  "ERR_DISPUTE_INVALID_STATE", "dispute_status")
    if dispute["sla_due_at"] is not None and now() >= dispute["sla_due_at"]:
        fail("ERR_DISPUTE_WINDOW_CLOSED",
             "The service level window has already closed.")
    dispute["review_rounds"] += 1
    dispute["dispute_status"] = target
    D.refresh_breach(dispute)
    touch(dispute)
    return ok(D.ser_dispute(dispute))


@bp.post("/rmn/measurement-disputes/<did>/resolve")
def resolve_dispute(did):
    specs = (
        F("decision", "enum", required=True, enum=("UPHOLD", "REJECT")),
        F("approved_credit_amount_cents", "integer", required=True, minimum=0),
        F("resolution_note", "string"),
    )
    ctx = guard(ANALYST_ROLES, path_refs=(("dispute", did),), body_specs=specs,
                mutating=True)
    dispute = ctx.get("dispute")
    inv = db.invoices[dispute["invoice_id"]]
    adv = ctx.get("advertiser")
    pool = db.trade_fund_accounts.get(inv["trade_fund_account_id"])
    decision = ctx.data["decision"]
    source = dispute["dispute_status"]
    target = H.require_transition(source, DISPUTE_TRANSITIONS[decision],
                                  "ERR_DISPUTE_INVALID_STATE", "dispute_status")
    if source == "ESCALATED" and ctx.role != "NetworkAdmin":
        fail("ERR_ROLE_NOT_PERMITTED",
             "Only a NetworkAdmin resolves an escalated dispute.")
    if decision == "UPHOLD" and source == "UNDER_REVIEW":
        if inv["invoice_status"] != "DISPUTED":
            fail("ERR_INVOICE_INVALID_STATE",
                 "The invoice is %s." % inv["invoice_status"])
    if source == "ESCALATED":
        if decision == "UPHOLD" and dispute["escalation_level"] < 1:
            fail("ERR_DISPUTE_INVALID_STATE",
                 "An escalated dispute needs escalation_level of at least 1.")
        if decision == "REJECT" and dispute["escalation_level"] != 2:
            fail("ERR_SLA_BREACH_REJECTION_FORBIDDEN",
                 "Only a round-exhaustion escalation may be rejected.")
    if decision == "REJECT" and source == "UNDER_REVIEW" and \
            dispute["sla_breached"]:
        fail("ERR_SLA_BREACH_REJECTION_FORBIDDEN",
             "A dispute answered late cannot be rejected.")
    if decision == "UPHOLD" and \
            dispute["dispute_category"] == "INCREMENTALITY_RESTATEMENT":
        camp = _dispute_campaign(dispute)
        study = D.latest_published_study(camp["id"]) if camp is not None else None
        if study is not None and study["published_by_user_id"] == ctx.user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The analyst that published the study may not adjudicate the "
                 "claim against it.")
    requested = ctx.data["approved_credit_amount_cents"]
    if requested > dispute["claimed_amount_cents"]:
        fail("ERR_CREDIT_EXCEEDS_CLAIM",
             "approved_credit_amount_cents exceeds claimed_amount_cents.")

    dispute["resolved_by_user_id"] = ctx.user_id
    dispute["dispute_status"] = target
    if decision == "UPHOLD":
        dispute["approved_credit_cents"] = D.dispute_credit_award(
            dispute, inv, requested)
        touch(dispute)
        # level one -- the invoice re-runs the waterfall and lands in ADJUSTED
        run_waterfall(inv, from_step_six=True)
        inv["invoice_status"] = "ADJUSTED"
        touch(inv)
        # level two and three -- the pool and its drained plans
        if pool is not None:
            H.unfreeze_overdrawn_pool(pool)
            touch(pool)
        touch(adv)
    else:
        dispute["approved_credit_cents"] = 0
        touch(dispute)
        H.restore_invoice_if_clear(inv)
    return ok(D.ser_dispute(dispute))


@bp.post("/rmn/measurement-disputes/<did>/escalate")
def escalate_dispute(did):
    specs = (F("escalation_reason", "string", required=True),)
    ctx = guard(DISPUTE_FILE, path_refs=(("dispute", did),), body_specs=specs,
                mutating=True)
    dispute = ctx.get("dispute")
    target = H.require_transition(dispute["dispute_status"],
                                  DISPUTE_TRANSITIONS["escalate"],
                                  "ERR_DISPUTE_INVALID_STATE", "dispute_status")
    if dispute["info_request_count"] >= D.MAX_INFO_REQUESTS:
        dispute["escalation_level"] = 2
    else:
        dispute["escalation_level"] = dispute["escalation_level"] + 1
    dispute["dispute_status"] = target
    dispute["first_response_at"] = None
    D.recompute_sla(dispute)
    D.refresh_breach(dispute)
    touch(dispute)
    return ok(D.ser_dispute(dispute))


@bp.post("/rmn/measurement-disputes/<did>/withdraw")
def withdraw_dispute(did):
    specs = (F("withdrawal_reason", "string", required=True),)
    ctx = guard(DISPUTE_FILE, path_refs=(("dispute", did),), body_specs=specs,
                mutating=True)
    dispute = ctx.get("dispute")
    inv = db.invoices[dispute["invoice_id"]]
    target = H.require_transition(dispute["dispute_status"],
                                  DISPUTE_TRANSITIONS["withdraw"],
                                  "ERR_DISPUTE_INVALID_STATE", "dispute_status")
    dispute["dispute_status"] = target
    dispute["approved_credit_cents"] = 0
    touch(dispute)
    H.restore_invoice_if_clear(inv)
    return ok(D.ser_dispute(dispute))
