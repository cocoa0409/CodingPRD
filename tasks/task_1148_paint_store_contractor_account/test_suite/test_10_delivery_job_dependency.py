"""Cross-entity state dependency: delivery dispatch gated by job state
(PRD §3.8, §3.2), and job completion gated by open work (PRD §3.2)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    dispatch_delivery,
    place_order,
    schedule_delivery,
    setup_account_job_product,
    setup_paid_order_with_delivery,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]
MANAGER = TEST_USERS["manager_headers"]


def _setup_held_job_with_delivery(api):
    """Paid order with a SCHEDULED delivery for 2026-06-12; job ON_HOLD."""
    account, job, product, order, delivery = setup_paid_order_with_delivery(
        window_start="2026-06-12T09:00:00Z", window_end="2026-06-12T10:00:00Z",
        jurisdiction_code="NM-OPEN")
    validate_success(api.place_job_on_hold(job["id"], MANAGER))
    return account, job, order, delivery


def test_dispatch_blocked_while_job_on_hold(api):
    """PRD §3.8: "Dispatch moves the delivery `SCHEDULED` to `EN_ROUTE` and is
    where operations harden. The guards evaluate in order: the job must be
    `OPEN` (`ERR_JOB_NOT_OPEN`); the delivery must still be `SCHEDULED`
    (`ERR_DELIVERY_NOT_DISPATCHABLE`, HTTP 409); the order must be `PAID` (a
    generic state failure, `ERR_INVALID_STATE`); and finally VOC compliance is
    re-checked at the dispatch instant ...".

    Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_by_job_hold
    """
    account, job, order, delivery = _setup_held_job_with_delivery(api)
    resp = api.dispatch_delivery(delivery["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_JOB_NOT_OPEN)
    after = validate_success(api.get_delivery(delivery["id"], MANAGER))
    assert after["status"] == "SCHEDULED", (
        f"the blocked dispatch must not move the delivery, got {after['status']}")


def test_resume_restores_dispatchability(api):
    """PRD §3.2: "Placing a job on hold moves `OPEN` to `ON_HOLD`; resuming
    moves `ON_HOLD` back to `OPEN`." PRD §3.8: "A successful dispatch stamps
    `dispatched_at` from the logical clock and fires the cross-entity hop that
    moves the order's `fulfillment_status` from `PENDING` to
    `OUT_FOR_DELIVERY` on this first dispatch, incrementing both the
    delivery's and the order's `version`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_by_job_hold
    """
    account, job, order, delivery = _setup_held_job_with_delivery(api)
    validate_error(api.dispatch_delivery(delivery["id"], MANAGER),
                   ApiErrorId.ERR_JOB_NOT_OPEN)
    validate_success(api.resume_job(job["id"], MANAGER))
    dispatched = validate_success(api.dispatch_delivery(delivery["id"], MANAGER))
    assert dispatched["status"] == "EN_ROUTE", (
        f"after resume the delivery dispatches, got {dispatched['status']}")
    order_after = validate_success(api.get_order(order["id"], ASSOCIATE))
    assert order_after["fulfillment_status"] == "OUT_FOR_DELIVERY", (
        f"first dispatch moves the order OUT_FOR_DELIVERY, "
        f"got {order_after['fulfillment_status']}")


def _setup_job_with_pending_order(api):
    """Job holding one UNPAID PENDING order."""
    account, _, job, product = setup_account_job_product(
        company_name="Gate Co", credit_limit_cents=1_000_000,
        jurisdiction_code="ME-OPEN", jurisdiction_name="Maine",
        sku="P-GATE", list_price_cents=5000)
    order = place_order(account["id"], job["id"],
                        [{"product_id": product["id"], "quantity": 1}])
    return account, job, order


def test_complete_blocked_by_pending_order(api):
    """PRD §3.2: "Completing a job moves either `OPEN` or `ON_HOLD` to the
    terminal `COMPLETE`, but only when no order of the job still has
    `fulfillment_status` `PENDING` or `OUT_FOR_DELIVERY` and no delivery of
    the job is still `SCHEDULED` or `EN_ROUTE` — a job with open work cannot
    be closed out. Each transition bumps the job's `version`; a transition
    attempted from the wrong source state, or a completion with open orders or
    deliveries outstanding, is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/job_complete_blocked_then_allowed
    """
    account, job, order = _setup_job_with_pending_order(api)
    resp = api.complete_job(job["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_job_account(job["id"], MANAGER))
    assert after["status"] == "OPEN", (
        f"the blocked completion must not move the job, got {after['status']}")


def test_complete_allowed_after_order_cancelled(api):
    """PRD §3.2: "Completing a job moves either `OPEN` or `ON_HOLD` to the
    terminal `COMPLETE`, but only when no order of the job still has
    `fulfillment_status` `PENDING` or `OUT_FOR_DELIVERY` and no delivery of
    the job is still `SCHEDULED` or `EN_ROUTE` — a job with open work cannot
    be closed out." PRD §3.6: "Cancellation is the inverse for untouched
    orders: from `PENDING` *and* `UNPAID` — both conditions required,
    otherwise `ERR_ORDER_NOT_CANCELLABLE` (HTTP 409) — the fulfillment
    dimension moves to `CANCELLED`, the account's outstanding balance is
    recomputed, and both versions increment."

    Cancelling the pending order clears the completion gate.

    Design: Corner/state_machines/job_complete_blocked_then_allowed
    """
    account, job, order = _setup_job_with_pending_order(api)
    validate_error(api.complete_job(job["id"], MANAGER),
                   ApiErrorId.ERR_INVALID_STATE)
    validate_success(api.cancel_order(order["id"], ASSOCIATE))
    completed = validate_success(api.complete_job(job["id"], MANAGER))
    assert completed["status"] == "COMPLETE", (
        f"with no open work remaining the job completes, got {completed['status']}")
