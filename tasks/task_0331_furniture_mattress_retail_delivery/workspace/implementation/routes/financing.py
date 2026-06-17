"""FinancingPlan endpoints incl. the cyclic plan lifecycle (PRD §3.5, §3.6)."""
from flask import Blueprint

import clock
import db
import helpers
import response
from errors import err
from middleware import get_auth, require_role
from services import calculations as calc
from services import domain, serializers

bp = Blueprint("financing", __name__)

PLAN_TYPES = {"INSTALLMENT", "LEASE_TO_OWN"}
TERM_BY_TYPE = {"INSTALLMENT": {6, 12, 24, 36}, "LEASE_TO_OWN": {12, 18}}


# ---------------------------------------------------------------------------
# Apply (OCC on Order.version)
# ---------------------------------------------------------------------------
@bp.post("/financing-plans")
def apply_financing():
    _, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager"})
    body = helpers.get_body()

    # Existence (4).
    order_id = helpers.require_str(body, "order_id")
    order = helpers.fetch(db.orders, order_id)

    # Shape (5).
    plan_type = helpers.require_enum(body, "plan_type", PLAN_TYPES)
    term_months = helpers.require_int(body, "term_months")
    if term_months not in TERM_BY_TYPE[plan_type]:
        raise err("ERR_INVALID_REQUEST",
                  "term_months %s invalid for plan_type %s." % (term_months, plan_type))
    expected_order_version = helpers.require_int(body, "expected_order_version")

    # Business referential (10): order must be UNPAID with no open plan.
    if order["payment_status"] != "UNPAID":
        raise err("ERR_ALREADY_SETTLED", "Order is already settled.")
    if domain.open_financing_plans_for_order(order_id):
        raise err("ERR_FINANCING_EXISTS", "An open financing plan already exists for this order.")

    # OCC (21): expected_order_version must match the live order version.
    if expected_order_version != order["version"]:
        raise err("ERR_STALE_VERSION", "Order version has advanced; re-read required.")

    plan = {
        "order_id": order_id,
        "customer_id": order["customer_id"],
        "plan_type": plan_type,
        "term_months": term_months,
        "financed_principal_cents": None,
        "monthly_payment_cents": None,
        "total_of_payments_cents": None,
        "paid_to_date_cents": 0,
        "payoff_balance_cents": None,
        "payments_made_count": 0,
        "status": "PENDING_APPROVAL",
        "_activation_date": None,
    }
    helpers.stamp_create(plan)
    db.financing_plans[plan["id"]] = plan
    return response.object_response(serializers.financing_plan(plan), status=201)


@bp.get("/financing-plans/<pid>")
def get_financing(pid):
    user_id, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    plan = helpers.fetch(db.financing_plans, pid)
    if role == "Customer" and user_id != plan["customer_id"]:
        raise err("ERR_FORBIDDEN_NOT_OWNER", "Not the owning customer.")
    return response.object_response(serializers.financing_plan(plan))


# ---------------------------------------------------------------------------
# Approve (heavily gated, pinned evaluation order)
# ---------------------------------------------------------------------------
@bp.post("/financing-plans/<pid>/approve")
def approve_financing(pid):
    _, role = get_auth()
    require_role(role, {"StoreManager"})
    plan = helpers.fetch(db.financing_plans, pid)

    # State (7).
    if plan["status"] != "PENDING_APPROVAL":
        raise err("ERR_INVALID_STATE", "Plan is not PENDING_APPROVAL.")

    order = db.orders.get(plan["order_id"])
    customer = db.customers.get(plan["customer_id"])

    # Order must still be UNPAID with no other competing open plan (ERR_ALREADY_SETTLED).
    if order is None or order["payment_status"] != "UNPAID":
        raise err("ERR_ALREADY_SETTLED", "Order is already settled.")
    other_open = [p for p in domain.open_financing_plans_for_order(plan["order_id"])
                  if p["id"] != plan["id"]]
    if other_open:
        raise err("ERR_ALREADY_SETTLED", "Another open plan exists for this order.")

    # Pinned eval order: (1) snapshot principal, (2) compute schedule, then gates.
    principal = order["order_total_cents"]
    total, monthly = calc.financing_schedule(plan["plan_type"], principal, plan["term_months"])

    # Gate priority: credit (11) -> DTI (12) -> open-plan (13).
    if customer["credit_score"] < calc.credit_floor(plan["plan_type"]):
        raise err("ERR_CREDIT_TOO_LOW", "Credit score below the plan-type minimum.")
    if not calc.dti_within_limit(customer["existing_monthly_obligations_cents"],
                                 monthly, customer["monthly_income_cents"]):
        raise err("ERR_DTI_EXCEEDED", "Debt-to-income ratio exceeds the limit.")
    if customer["open_financing_count"] >= calc.MAX_OPEN_PLANS:
        raise err("ERR_TOO_MANY_OPEN_PLANS", "Customer already has the maximum open plans.")

    # Commit: lock the snapshot and schedule.
    plan["financed_principal_cents"] = principal
    plan["total_of_payments_cents"] = total
    plan["monthly_payment_cents"] = monthly
    plan["paid_to_date_cents"] = 0
    plan["payments_made_count"] = 0
    plan["status"] = "CURRENT"
    plan["_activation_date"] = clock.iso_now()
    plan["payoff_balance_cents"] = calc.financing_payoff_balance(plan)
    helpers.touch(plan)

    # Cross-entity: order -> FINANCED; customer open count +1.
    order["payment_status"] = "FINANCED"
    helpers.touch(order)
    domain.recompute_open_financing_count(plan["customer_id"])

    return response.object_response(serializers.financing_plan(plan))


@bp.post("/financing-plans/<pid>/decline")
def decline_financing(pid):
    _, role = get_auth()
    require_role(role, {"StoreManager"})
    plan = helpers.fetch(db.financing_plans, pid)
    if plan["status"] != "PENDING_APPROVAL":
        raise err("ERR_INVALID_STATE", "Plan is not PENDING_APPROVAL.")
    plan["status"] = "DECLINED"
    helpers.touch(plan)
    return response.object_response(serializers.financing_plan(plan))


@bp.post("/financing-plans/<pid>/mark-past-due")
def mark_past_due(pid):
    _, role = get_auth()
    require_role(role, {"StoreManager"})
    plan = helpers.fetch(db.financing_plans, pid)
    if plan["status"] != "CURRENT":
        raise err("ERR_INVALID_STATE", "Plan is not CURRENT.")
    elapsed = domain.periods_elapsed(plan)
    if not (plan["payments_made_count"] < elapsed):
        raise err("ERR_NO_PERIOD_DUE", "No monthly period is currently owed.")
    plan["status"] = "PAST_DUE"
    helpers.touch(plan)
    return response.object_response(serializers.financing_plan(plan))


@bp.post("/financing-plans/<pid>/default")
def default_financing(pid):
    _, role = get_auth()
    require_role(role, {"StoreManager"})
    plan = helpers.fetch(db.financing_plans, pid)
    if plan["status"] != "PAST_DUE":
        raise err("ERR_INVALID_STATE", "Plan is not PAST_DUE.")
    plan["status"] = "DEFAULTED"
    helpers.touch(plan)
    domain.recompute_open_financing_count(plan["customer_id"])
    return response.object_response(serializers.financing_plan(plan))


# ---------------------------------------------------------------------------
# Payments (cyclic lifecycle)
# ---------------------------------------------------------------------------
@bp.post("/financing-plans/<pid>/payments")
def post_payment(pid):
    _, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager"})
    plan = helpers.fetch(db.financing_plans, pid)
    body = helpers.get_body()
    amount = helpers.require_int(body, "amount_cents", minimum=1)

    status = plan["status"]
    if status not in ("CURRENT", "PAST_DUE"):
        raise err("ERR_INVALID_STATE", "Plan does not accept payments in its current state.")

    payoff_before = plan["payoff_balance_cents"]

    is_payoff = amount >= payoff_before
    if is_payoff:
        # CURRENT/PAST_DUE -> PAID_OFF
        _append_payment(plan, amount)
        domain.recompute_plan_payment_aggregates(plan)
        plan["payoff_balance_cents"] = 0
        plan["status"] = "PAID_OFF"
        helpers.touch(plan)
        order = db.orders.get(plan["order_id"])
        if order is not None:
            order["payment_status"] = "PAID_IN_FULL"
            helpers.touch(order)
        domain.recompute_open_financing_count(plan["customer_id"])
        payment_rec = _last_payment(plan)
        return response.object_response(serializers.payment(payment_rec), status=201)

    # Non-payoff path (amount < payoff_before).
    if status == "CURRENT":
        # Self-loop: routine in-schedule payment keeps it CURRENT.
        _append_payment(plan, amount)
        domain.recompute_plan_payment_aggregates(plan)
        helpers.touch(plan)
        payment_rec = _last_payment(plan)
        return response.object_response(serializers.payment(payment_rec), status=201)

    # status == PAST_DUE catch-up: must bring paid_to_date up to monthly * periods_elapsed.
    elapsed = domain.periods_elapsed(plan)
    prospective_paid = plan["paid_to_date_cents"] + amount
    if prospective_paid < plan["monthly_payment_cents"] * elapsed:
        raise err("ERR_INSUFFICIENT_CATCH_UP", "Payment does not restore the schedule.")
    _append_payment(plan, amount)
    domain.recompute_plan_payment_aggregates(plan)
    plan["status"] = "CURRENT"
    helpers.touch(plan)
    payment_rec = _last_payment(plan)
    return response.object_response(serializers.payment(payment_rec), status=201)


def _append_payment(plan, amount):
    """Append a Payment row; applied_period_index = next 1-based period (by created_at ASC)."""
    next_index = len(domain.payments_for_plan(plan["id"])) + 1
    rec = {
        "financing_plan_id": plan["id"],
        "amount_cents": amount,
        "applied_period_index": next_index,
    }
    helpers.stamp_create(rec, with_version=False)
    db.payments[rec["id"]] = rec
    return rec


def _last_payment(plan):
    pays = sorted(domain.payments_for_plan(plan["id"]), key=lambda p: p["_seq"])
    return pays[-1]


@bp.get("/financing-plans/<pid>/payments")
def list_payments(pid):
    user_id, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    plan = helpers.fetch(db.financing_plans, pid)
    if role == "Customer" and user_id != plan["customer_id"]:
        raise err("ERR_FORBIDDEN_NOT_OWNER", "Not the owning customer.")
    limit, offset = helpers.get_pagination()
    page, total = helpers.paginate(domain.payments_for_plan(pid), limit, offset)
    return response.array_response(
        [serializers.payment(p) for p in page], limit, offset, total)
