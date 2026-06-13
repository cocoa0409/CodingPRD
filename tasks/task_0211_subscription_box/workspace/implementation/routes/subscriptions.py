"""Subscription lifecycle + billing endpoints (PRD §3.2-§3.6, §3.12)."""
from flask import Blueprint, request, g

from db import db
from common import (new_record, touch, serialize, get_body, require_str,
                    require_int, require_enum, require_field, must_exist,
                    parse_datetime, paginate)
from middleware import authenticate, require_roles, require_owner_subscriber
from response import success, list_success
from errors import (err, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_STALE_SUBSCRIPTION_VERSION, ERR_PREPAID_TERM_NOT_OFFERED,
                    ERR_PLAN_RETIRED, ERR_GIFT_NOT_REACTIVATABLE,
                    ERR_PAUSE_LIMIT_REACHED, ERR_INVALID_RESUME_DATE,
                    ERR_BOX_ALREADY_FINALIZED, ERR_WINBACK_WINDOW_CLOSED,
                    ERR_BOX_ITEM_COUNT_MISMATCH)
from services.ledger import (cadence_delta, create_invoice, create_wallet_entry,
                             create_billing_cycle)
from services import calculations
from services.renewal import revert_all_upcoming_finalized
from datetime import timedelta

bp = Blueprint("subscriptions", __name__)


# ---- create -------------------------------------------------------------
@bp.post("/subscriptions")
def create_subscription():
    authenticate()
    require_roles("Subscriber")
    body = get_body()
    subscriber_id = require_str(body, "subscriber_id")
    plan_id = require_str(body, "plan_id")
    # ownership: subscriber acts on own subscriber_id
    require_owner_subscriber(subscriber_id)
    # existence of FK references
    must_exist(db.subscribers, subscriber_id, "Subscriber")
    plan = must_exist(db.plans, plan_id, "Plan")

    now = db.now()
    sub = new_record({
        "subscriber_id": subscriber_id,
        "plan_id": plan_id,
        "lifecycle_status": "ACTIVE",
        "billing_status": "CURRENT",
        "is_gift": False,
        "prepaid_periods_remaining": 0,
        "prepaid_unit_value_cents": 0,
        "current_period_index": 1,
        "next_renewal_at": now + cadence_delta(plan["cadence"]),
        "paused_until": None,
        "pause_count_in_term": 0,
        "cancelled_at": None,
        "_pause_start": None,
    })
    db.subscriptions[sub["id"]] = sub

    # bill first period immediately
    amount = plan["period_price_cents"]
    create_billing_cycle(sub["id"], 1, amount, "CHARGE", status="PAID", charged_at=now)
    create_invoice(subscriber_id, sub["id"], amount, "PERIOD_CHARGE")
    return success(serialize(sub), status=201)


@bp.get("/subscriptions/<sid>")
def get_subscription(sid):
    authenticate()
    require_roles("Subscriber", "CurationAdmin", "BillingOperator")
    sub = must_exist(db.subscriptions, sid, "Subscription")
    require_owner_subscriber(sub["subscriber_id"])
    return success(serialize(sub))


@bp.get("/subscriptions")
def list_subscriptions():
    authenticate()
    require_roles("Subscriber", "CurationAdmin", "BillingOperator")
    records = list(db.subscriptions.values())
    if g.role == "Subscriber":
        records = [r for r in records if r["subscriber_id"] == g.user_id]
    sub_filter = request.args.get("subscriber_id")
    if sub_filter is not None:
        records = [r for r in records if r["subscriber_id"] == sub_filter]
    plan_filter = request.args.get("plan_id")
    if plan_filter is not None:
        records = [r for r in records if r["plan_id"] == plan_filter]
    lc_filter = request.args.get("lifecycle_status")
    if lc_filter is not None:
        records = [r for r in records if r["lifecycle_status"] == lc_filter]
    page, limit, offset, total = paginate(records)
    return list_success([serialize(r) for r in page], limit, offset, total)


# ---- pause --------------------------------------------------------------
@bp.post("/subscriptions/<sid>/pause")
def pause_subscription(sid):
    authenticate()
    require_roles("Subscriber")
    sub = must_exist(db.subscriptions, sid, "Subscription")
    require_owner_subscriber(sub["subscriber_id"])
    body = get_body()
    paused_until_raw = require_field(body, "paused_until")
    paused_until = parse_datetime(paused_until_raw, "paused_until")

    # state: ACTIVE -> PAUSED defined only from ACTIVE
    if sub["lifecycle_status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Pause requires an ACTIVE subscription.")

    # business: pause limit (priority 8)
    if sub["pause_count_in_term"] >= 3:
        raise err(ERR_PAUSE_LIMIT_REACHED, "Pause limit reached for the current term.")

    # business: upcoming box already finalized into OPEN/LOCKED wave
    if _upcoming_box_finalized(sub):
        raise err(ERR_BOX_ALREADY_FINALIZED,
                  "Upcoming box is already finalized into a wave.")

    # temporal: paused_until strictly after clock (priority 9)
    if paused_until <= db.now():
        raise err(ERR_INVALID_RESUME_DATE, "paused_until must be strictly after now.")

    sub["lifecycle_status"] = "PAUSED"
    sub["paused_until"] = paused_until
    sub["pause_count_in_term"] += 1
    sub["_pause_start"] = db.now()
    # next_renewal_at frozen (unchanged)
    touch(sub)
    return success(serialize(sub))


def _upcoming_box_finalized(sub):
    period = sub["current_period_index"] + 1
    for box in db.box_selections.values():
        if box["subscription_id"] != sub["id"]:
            continue
        if box["period_index"] != period:
            continue
        if box["decision"] == "FINALIZED" and box.get("allocation_id"):
            alloc = db.allocations.get(box["allocation_id"])
            if alloc and alloc["status"] == "RESERVED":
                wave = db.shipping_waves.get(alloc["wave_id"])
                if wave and wave["status"] in ("OPEN", "LOCKED"):
                    return True
    return False


# ---- resume -------------------------------------------------------------
@bp.post("/subscriptions/<sid>/resume")
def resume_subscription(sid):
    authenticate()
    require_roles("Subscriber")
    sub = must_exist(db.subscriptions, sid, "Subscription")
    require_owner_subscriber(sub["subscriber_id"])
    if sub["lifecycle_status"] != "PAUSED":
        raise err(ERR_INVALID_STATE, "Resume requires a PAUSED subscription.")

    plan = db.plans[sub["plan_id"]]
    delta = cadence_delta(plan["cadence"])
    pause_start = sub.get("_pause_start")
    resume_instant = db.now()
    if sub["next_renewal_at"] is not None and pause_start is not None:
        elapsed = resume_instant - pause_start
        periods = 0
        if delta.total_seconds() > 0 and elapsed.total_seconds() > 0:
            import math
            periods = math.ceil(elapsed.total_seconds() / delta.total_seconds())
        sub["next_renewal_at"] = sub["next_renewal_at"] + periods * delta
    sub["lifecycle_status"] = "ACTIVE"
    sub["paused_until"] = None
    sub["_pause_start"] = None
    touch(sub)
    return success(serialize(sub))


# ---- cancel -------------------------------------------------------------
@bp.post("/subscriptions/<sid>/cancel")
def cancel_subscription(sid):
    authenticate()
    require_roles("Subscriber")
    sub = must_exist(db.subscriptions, sid, "Subscription")
    require_owner_subscriber(sub["subscriber_id"])
    body = get_body()
    effective = require_enum(body, "effective", {"PERIOD_END", "IMMEDIATE"})

    if effective == "PERIOD_END":
        if sub["lifecycle_status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE,
                      "Period-end cancel requires an ACTIVE subscription.")
        sub["lifecycle_status"] = "CANCEL_SCHEDULED"
        sub["cancelled_at"] = db.now()
        # next_renewal_at preserved as scheduled cancellation date
        touch(sub)
        return success(serialize(sub))

    # IMMEDIATE: allowed from ACTIVE or PAUSED
    if sub["lifecycle_status"] not in ("ACTIVE", "PAUSED"):
        raise err(ERR_INVALID_STATE,
                  "Immediate cancel requires an ACTIVE or PAUSED subscription.")

    plan = db.plans[sub["plan_id"]]
    refund = calculations.cancellation_refund(sub)

    # within-period paid cycle reversal (compensation, PRD §3.5)
    _reverse_current_period_cycle(sub)

    sub["cancelled_at"] = db.now()
    sub["next_renewal_at"] = None

    if refund > 0:
        create_invoice(sub["subscriber_id"], sub["id"], -refund, "CANCEL_REFUND")
        create_wallet_entry(sub["subscriber_id"], refund, "REFUND_CREDIT")

    sub["lifecycle_status"] = "CANCELLED"
    # cascade: revert upcoming FINALIZED boxes -> SKIPPED, release allocations
    revert_all_upcoming_finalized(sub, revert_to="SKIPPED")
    # billing posture set to CURRENT (prepaid consumed by refund)
    sub["billing_status"] = "CURRENT"
    sub["prepaid_periods_remaining"] = 0
    sub["prepaid_unit_value_cents"] = 0
    touch(sub)
    return success(serialize(sub))


def _reverse_current_period_cycle(sub):
    """Reverse the PAID cycle for the current period; void its invoice (PRD §3.5)."""
    period = sub["current_period_index"]
    for c in db.billing_cycles.values():
        if (c["subscription_id"] == sub["id"] and c["status"] == "PAID"
                and c["period_index"] == period):
            c["status"] = "REVERSED"
            touch(c)
            # void the matching PERIOD_CHARGE invoice for this subscription
            for inv in db.invoices.values():
                if (inv["subscription_id"] == sub["id"]
                        and inv["kind"] == "PERIOD_CHARGE"
                        and inv["status"] == "SETTLED"):
                    inv["status"] = "VOID"
                    touch(inv)
                    break
            break


# ---- winback ------------------------------------------------------------
@bp.post("/subscriptions/<sid>/winback")
def winback_subscription(sid):
    authenticate()
    require_roles("Subscriber")
    sub = must_exist(db.subscriptions, sid, "Subscription")
    require_owner_subscriber(sub["subscriber_id"])

    # state: win-back defined only from CANCELLED
    if sub["lifecycle_status"] != "CANCELLED":
        raise err(ERR_INVALID_STATE, "Win-back requires a CANCELLED subscription.")

    plan = db.plans[sub["plan_id"]]

    # business (priority 8): plan retired, gift not reactivatable
    if plan["status"] == "RETIRED":
        raise err(ERR_PLAN_RETIRED, "Plan is retired.")
    if sub["is_gift"]:
        raise err(ERR_GIFT_NOT_REACTIVATABLE, "Gift subscriptions cannot be won back.")

    # temporal (priority 9): win-back window [cancelled_at, cancelled_at+60d)
    cancelled_at = sub["cancelled_at"]
    if cancelled_at is not None and db.now() >= cancelled_at + timedelta(days=60):
        raise err(ERR_WINBACK_WINDOW_CLOSED, "Win-back window has closed.")

    grant = calculations.winback_credit(sub["subscriber_id"], plan)

    sub["lifecycle_status"] = "ACTIVE"
    sub["billing_status"] = "CURRENT"
    sub["cancelled_at"] = None
    sub["next_renewal_at"] = db.now() + cadence_delta(plan["cadence"])
    touch(sub)

    create_wallet_entry(sub["subscriber_id"], grant, "WINBACK_CREDIT",
                        source_ref_id=sub["id"])
    return success(serialize(sub))


# ---- prepay -------------------------------------------------------------
@bp.post("/subscriptions/<sid>/prepay")
def prepay_subscription(sid):
    authenticate()
    require_roles("Subscriber")
    sub = must_exist(db.subscriptions, sid, "Subscription")
    require_owner_subscriber(sub["subscriber_id"])
    body = get_body()
    term_periods = require_int(body, "term_periods")
    expected_version = require_field(body, "expected_subscription_version")

    # state: CURRENT -> PREPAID requires billing CURRENT and lifecycle ACTIVE
    if not (sub["billing_status"] == "CURRENT" and sub["lifecycle_status"] == "ACTIVE"):
        raise err(ERR_INVALID_STATE,
                  "Prepay requires an ACTIVE, CURRENT subscription.")

    # OCC (priority 6): expected_subscription_version == live version
    if expected_version != sub["version"]:
        raise err(ERR_STALE_SUBSCRIPTION_VERSION, "Subscription version is stale.")

    plan = db.plans[sub["plan_id"]]
    # business (priority 8): term offered
    if term_periods not in plan["prepaid_terms_offered"]:
        raise err(ERR_PREPAID_TERM_NOT_OFFERED,
                  "Requested term is not offered by the plan.")

    total = calculations.prepaid_total_paid(
        plan["period_price_cents"], term_periods, plan["prepaid_discount_pct"])
    create_invoice(sub["subscriber_id"], sub["id"], total, "PREPAID_CHARGE")
    sub["billing_status"] = "PREPAID"
    sub["prepaid_periods_remaining"] = term_periods
    sub["prepaid_unit_value_cents"] = calculations.amortized_unit_value(total, term_periods)
    touch(sub)  # increments version by 1
    return success(serialize(sub))


# ---- retry-charge -------------------------------------------------------
@bp.post("/subscriptions/<sid>/retry-charge")
def retry_charge(sid):
    authenticate()
    require_roles("BillingOperator")
    sub = must_exist(db.subscriptions, sid, "Subscription")
    body = get_body()
    outcome = require_enum(body, "outcome", {"PAID", "FAILED"})

    if sub["billing_status"] != "PAST_DUE":
        raise err(ERR_INVALID_STATE, "Retry requires a PAST_DUE subscription.")

    plan = db.plans[sub["plan_id"]]
    if outcome == "PAID":
        # replacement cycle PAID; find the failed cycle's period
        period = _latest_failed_period(sub)
        amount = plan["period_price_cents"]
        create_billing_cycle(sub["id"], period, amount, "CHARGE",
                             status="PAID", charged_at=db.now())
        create_invoice(sub["subscriber_id"], sub["id"], amount, "PERIOD_CHARGE")
        sub["billing_status"] = "CURRENT"
        touch(sub)
    # outcome == FAILED: stays PAST_DUE (no state change required)
    return success(serialize(sub))


def _latest_failed_period(sub):
    failed = [c for c in db.billing_cycles.values()
              if c["subscription_id"] == sub["id"] and c["status"] == "FAILED"]
    if not failed:
        return sub["current_period_index"]
    return max(c["period_index"] for c in failed)
