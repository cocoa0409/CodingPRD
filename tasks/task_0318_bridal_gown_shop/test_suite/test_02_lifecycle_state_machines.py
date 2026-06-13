"""Gown-order, alteration-job, and appointment lifecycle state machines:
parallel axes, the cyclic refit loop, cross-entity preconditions, valid and
invalid transitions, and terminal lockdown.

Covers difficulty rules non_linear_state_machine and cross_entity_state_dependency,
plus the corner state_machines section.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId,
    create_draft_order, create_received_order, create_received_order_with_queued_job,
    create_fitting_job, create_ordered_order, create_ready_order,
    create_deposit_paid_ready_order, create_picked_up_order,
    create_checked_in_appointment, create_stylist,
)
from test_helpers.fixtures import CONSULTANT, MANAGER, CLERK, SEAMSTRESS, get_plan


# ─── non_linear_state_machine / alteration_cyclic_refit_loop ─────────────────

def test_refit_loop_increments_refitting_count(api):
    """PRD §3.5: "From `FITTING`, the seamstress can request an adjustment, advancing
    `FITTING -> ADJUSTING`, which requires the `FITTING` state ... and increments
    `refitting_count` by one to record the revision round." Two adjustment rounds give 2.

    Design: Difficulty/non_linear_state_machine/alteration_cyclic_refit_loop
    """
    order, job = create_fitting_job(order_overrides={
        "gown_style_code": "ATELIER", "ordered_size": 12, "base_price_cents": 160000,
        "standard_lead_days": 60}, job_overrides={"estimated_labor_minutes": 40})
    validate_success(api.request_adjustment_alteration_job(job["id"], SEAMSTRESS), 200)
    validate_success(api.log_labor_alteration_job(job["id"], {"minutes": 30}, SEAMSTRESS), 200)

    after_second = validate_success(api.request_adjustment_alteration_job(job["id"], SEAMSTRESS), 200)
    assert after_second["status"] == "ADJUSTING"
    assert after_second["refitting_count"] == 2, (
        f"refitting_count should be 2 after two adjustment rounds, got {after_second['refitting_count']}"
    )


def test_log_labor_cycles_adjusting_back_to_fitting(api):
    """PRD §3.5: "To resume after an adjustment, the seamstress logs labor, advancing
    `ADJUSTING -> FITTING`; this requires the `ADJUSTING` state ... and adds those
    `minutes` to the running `actual_labor_minutes` accumulator before cycling the job
    back to `FITTING`."

    Design: Difficulty/non_linear_state_machine/alteration_cyclic_refit_loop
    """
    order, job = create_fitting_job(job_overrides={"estimated_labor_minutes": 40})
    validate_success(api.request_adjustment_alteration_job(job["id"], SEAMSTRESS), 200)
    resumed = validate_success(
        api.log_labor_alteration_job(job["id"], {"minutes": 30}, SEAMSTRESS), 200)
    assert resumed["status"] == "FITTING"
    assert resumed["actual_labor_minutes"] == 30
    assert resumed["refitting_count"] == 1


# ─ non_linear_state_machine / gown_order_parallel_payment_and_fulfillment_axes ─

def test_fulfillment_advances_while_payment_axis_independent(api):
    """PRD §3.7: "the plan advances `DEPOSIT_DUE -> ACTIVE` and the linked order's
    `payment_status` advances `UNPAID -> DEPOSIT_PAID`." After the deposit, receiving the
    order drives fulfillment to RECEIVED while payment_status independently stays DEPOSIT_PAID.

    Design: Difficulty/non_linear_state_machine/gown_order_parallel_payment_and_fulfillment_axes
    """
    order = create_draft_order(gown_style_code="ELEGANCE", ordered_size=22,
                               base_price_cents=200000, standard_lead_days=90, is_rush=True)
    plan = validate_success(api.create_payment_plan(
        {"gown_order_id": order["id"], "term_installments": 5, "deposit_cents": 145000}, CLERK), 201)
    validate_success(api.post_payment(
        plan["id"], {"amount_cents": 145000, "expected_plan_version": plan["version"]}, CLERK), 201)
    validate_success(api.submit_gown_order(order["id"], CONSULTANT), 200)

    received = validate_success(api.receive_gown_order(order["id"], MANAGER), 200)
    assert received["fulfillment_status"] == "RECEIVED"
    assert received["payment_status"] == "DEPOSIT_PAID", (
        f"payment_status should independently sit at DEPOSIT_PAID, got {received['payment_status']}"
    )


def test_deposit_paid_persists_through_ready(api):
    """PRD §3.4 / §3.7: marking ready advances `RECEIVED -> READY` (a fulfillment-axis move)
    while the payment axis is untouched. PRD §3.7: a deposit drives the order's
    `payment_status` to `DEPOSIT_PAID`; that axis stays DEPOSIT_PAID as fulfillment moves to READY.

    Design: Difficulty/non_linear_state_machine/gown_order_parallel_payment_and_fulfillment_axes
    """
    order, plan = create_deposit_paid_ready_order(order_overrides={
        "gown_style_code": "ATELIER", "ordered_size": 10, "base_price_cents": 180000,
        "standard_lead_days": 60})
    assert order["fulfillment_status"] == "READY"
    assert order["payment_status"] == "DEPOSIT_PAID"


# ─── cross_entity_state_dependency / start_fitting_requires_order_received ───

def test_start_fitting_blocked_when_order_not_received(api):
    """PRD §3.5: "A `Seamstress` starts the first fitting, advancing `QUEUED -> FITTING`;
    this requires the job to be `QUEUED` ... and requires the linked gown order to be
    `RECEIVED` (else `ERR_ORDER_NOT_RECEIVED`), since alterations cannot begin before the
    gown is physically in the shop."

    Design: Difficulty/cross_entity_state_dependency/start_fitting_requires_order_received
    """
    order, _ = create_ordered_order(order_overrides={
        "gown_style_code": "ATELIER", "ordered_size": 10, "base_price_cents": 180000,
        "standard_lead_days": 60})
    job = validate_success(api.create_alteration_job(
        {"gown_order_id": order["id"], "estimated_labor_minutes": 40}, SEAMSTRESS), 201)

    res = api.start_fitting_alteration_job(job["id"], SEAMSTRESS)
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_RECEIVED.value)
    job_after = validate_success(api.get_alteration_job(job["id"], SEAMSTRESS), 200)
    assert job_after["status"] == "QUEUED"


def test_start_fitting_succeeds_once_order_received(api):
    """PRD §3.5: "A `Seamstress` starts the first fitting, advancing `QUEUED -> FITTING`;
    this requires the job to be `QUEUED` ... and requires the linked gown order to be
    `RECEIVED`". With the order RECEIVED the same call now moves the job to FITTING.

    Design: Difficulty/cross_entity_state_dependency/start_fitting_requires_order_received
    """
    order, job = create_received_order_with_queued_job(order_overrides={
        "gown_style_code": "ATELIER", "ordered_size": 10, "base_price_cents": 180000,
        "standard_lead_days": 60}, job_overrides={"estimated_labor_minutes": 40})
    started = validate_success(api.start_fitting_alteration_job(job["id"], SEAMSTRESS), 200)
    assert started["status"] == "FITTING"


# ─── cross_entity_state_dependency / pickup_requires_payment_paid_in_full ────

def test_pickup_blocked_when_balance_outstanding(api):
    """PRD §3.4: "the order's `payment_status` must be `PAID_IN_FULL`, meaning the plan's
    balance has reached zero (else `ERR_BALANCE_OUTSTANDING`)". A READY order whose plan
    only has the deposit paid (balance > 0) is rejected on pickup with steam done.

    Design: Difficulty/cross_entity_state_dependency/pickup_requires_payment_paid_in_full
    """
    order, plan = create_deposit_paid_ready_order(order_overrides={
        "gown_style_code": "ATELIER", "ordered_size": 10, "base_price_cents": 180000,
        "standard_lead_days": 60}, plan_overrides={"term_installments": 2, "deposit_cents": 90000})
    res = api.pickup_gown_order(order["id"], {"final_steam_done": True}, CONSULTANT)
    validate_error(res, ApiErrorId.ERR_BALANCE_OUTSTANDING.value)
    order_after = validate_success(api.get_gown_order(order["id"], MANAGER), 200)
    assert order_after["fulfillment_status"] == "READY"


def test_pickup_succeeds_when_paid_in_full_and_steam_done(api):
    """PRD §3.4: "A `BridalConsultant` or `ShopManager` performs the final steam and
    pickup, advancing `READY -> PICKED_UP`." A fully-paid READY order with
    final_steam_done true reaches PICKED_UP.

    Design: Difficulty/cross_entity_state_dependency/pickup_requires_payment_paid_in_full
    """
    order, plan = create_picked_up_order(order_overrides={
        "gown_style_code": "ATELIER", "ordered_size": 10, "base_price_cents": 180000,
        "standard_lead_days": 60})
    assert order["fulfillment_status"] == "PICKED_UP"
    assert order["payment_status"] == "PAID_IN_FULL"


# ─── Corner: state_machines ──────────────────────────────────────────────────

def test_check_in_twice_rejected(api):
    """PRD §3.2: "A `BridalConsultant` checks a client in, advancing `BOOKED -> CHECKED_IN`;
    this requires the appointment to be `BOOKED` (else `ERR_APPOINTMENT_NOT_BOOKED`)".
    A second check-in sees CHECKED_IN and is rejected.

    Design: Corner/state_machines/check_in_already_checked_in_returns_not_booked
    """
    appt, _ = create_checked_in_appointment(
        start_at="2026-07-08T10:00:00.000Z", end_at="2026-07-08T11:00:00.000Z")
    res = api.check_in_appointment(appt["id"], CONSULTANT)
    validate_error(res, ApiErrorId.ERR_APPOINTMENT_NOT_BOOKED.value)


def test_cancel_picked_up_order_rejected(api):
    """PRD §3.4: "A `ShopManager` may cancel an order from any non-terminal fulfillment
    state — that is, any state that is not already `PICKED_UP` or `CANCELLED` (else
    `ERR_ORDER_NOT_CANCELLABLE`)". A PICKED_UP order rejects cancel.

    Design: Corner/state_machines/cancel_terminal_picked_up_order_returns_not_cancellable
    """
    order, _ = create_picked_up_order(order_overrides={
        "gown_style_code": "ATELIER", "ordered_size": 10, "base_price_cents": 180000,
        "standard_lead_days": 60})
    res = api.cancel_gown_order(order["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE.value)
    order_after = validate_success(api.get_gown_order(order["id"], MANAGER), 200)
    assert order_after["fulfillment_status"] == "PICKED_UP"


def test_revert_check_in_returns_to_booked(api):
    """PRD §3.2: "An accidental check-in can be undone by the same consultant, reverting
    `CHECKED_IN -> BOOKED`, which requires the appointment to be `CHECKED_IN` (else
    `ERR_APPOINTMENT_NOT_CHECKED_IN`)".

    Design: Corner/state_machines/appointment_revert_check_in_returns_to_booked
    """
    appt, _ = create_checked_in_appointment(
        start_at="2026-07-09T10:00:00.000Z", end_at="2026-07-09T11:00:00.000Z")
    reverted = validate_success(api.revert_check_in_appointment(appt["id"], CONSULTANT), 200)
    assert reverted["status"] == "BOOKED"


def test_mark_ready_with_outstanding_alteration_blocked(api):
    """PRD §3.4: "requires that every alteration job belonging to the order has reached
    `COMPLETED` or `CANCELLED`; if any job is still outstanding the request is rejected
    with `ERR_ALTERATIONS_OUTSTANDING`."

    Design: Corner/state_machines/mark_ready_with_outstanding_alteration_blocked
    """
    order, job = create_received_order_with_queued_job(order_overrides={
        "gown_style_code": "ATELIER", "ordered_size": 10, "base_price_cents": 180000,
        "standard_lead_days": 60}, job_overrides={"estimated_labor_minutes": 30})
    res = api.mark_ready_gown_order(order["id"], SEAMSTRESS)
    validate_error(res, ApiErrorId.ERR_ALTERATIONS_OUTSTANDING.value)
    order_after = validate_success(api.get_gown_order(order["id"], MANAGER), 200)
    assert order_after["fulfillment_status"] == "RECEIVED"


def test_submit_without_payment_plan_blocked(api):
    """PRD §3.4: "Submission requires the order to be `DRAFT` (else `ERR_ORDER_NOT_DRAFT`)
    and requires that a payment plan already exists for the order with a status other than
    `CANCELLED` (else `ERR_PAYMENT_PLAN_REQUIRED`)."

    Design: Corner/state_machines/submit_without_payment_plan_blocked
    """
    order = create_draft_order(gown_style_code="ATELIER", ordered_size=10,
                               base_price_cents=180000, standard_lead_days=60)
    res = api.submit_gown_order(order["id"], CONSULTANT)
    validate_error(res, ApiErrorId.ERR_PAYMENT_PLAN_REQUIRED.value)
    order_after = validate_success(api.get_gown_order(order["id"], MANAGER), 200)
    assert order_after["fulfillment_status"] == "DRAFT"


def test_refund_on_non_cancelled_order_rejected(api):
    """PRD §3.7: "A refund is permitted solely when the linked gown order's
    `fulfillment_status` is `CANCELLED`; a refund attempted on a non-cancelled order is
    rejected with `ERR_REFUND_NOT_ALLOWED`."

    Design: Corner/state_machines/refund_on_non_cancelled_order_rejected
    """
    order = create_draft_order(gown_style_code="ATELIER", ordered_size=10,
                               base_price_cents=180000, standard_lead_days=60)
    plan = validate_success(api.create_payment_plan(
        {"gown_order_id": order["id"], "term_installments": 2, "deposit_cents": 90000}, CLERK), 201)
    validate_success(api.post_payment(
        plan["id"], {"amount_cents": 90000, "expected_plan_version": plan["version"]}, CLERK), 201)
    fresh = get_plan(plan["id"])

    res = api.refund_payment_plan(plan["id"], {"expected_plan_version": fresh["version"]}, CLERK)
    validate_error(res, ApiErrorId.ERR_REFUND_NOT_ALLOWED.value)
    plan_after = get_plan(plan["id"])
    assert plan_after["amount_paid_cents"] == 90000


def test_log_labor_from_fitting_not_adjusting_rejected(api):
    """PRD §3.5: "To resume after an adjustment, the seamstress logs labor, advancing
    `ADJUSTING -> FITTING`; this requires the `ADJUSTING` state (else
    `ERR_JOB_NOT_ADJUSTING`)". Calling it from FITTING is rejected.

    Design: Corner/state_machines/log_labor_from_fitting_not_adjusting_rejected
    """
    order, job = create_fitting_job(order_overrides={
        "gown_style_code": "ATELIER", "ordered_size": 10, "base_price_cents": 180000,
        "standard_lead_days": 60}, job_overrides={"estimated_labor_minutes": 30})
    res = api.log_labor_alteration_job(job["id"], {"minutes": 20}, SEAMSTRESS)
    validate_error(res, ApiErrorId.ERR_JOB_NOT_ADJUSTING.value)


def test_pickup_without_final_steam_blocked(api):
    """PRD §3.4: "and `final_steam_done` must be `true` in the request body (else
    `ERR_FINAL_STEAM_REQUIRED`)". A fully-paid READY order with final_steam_done false
    is rejected.

    Design: Corner/state_machines/pickup_without_final_steam_blocked
    """
    order, plan = create_ready_order(order_overrides={
        "gown_style_code": "ATELIER", "ordered_size": 10, "base_price_cents": 180000,
        "standard_lead_days": 60}, plan_overrides={"term_installments": 2, "deposit_cents": 90000},
        fully_paid=True)
    res = api.pickup_gown_order(order["id"], {"final_steam_done": False}, CONSULTANT)
    validate_error(res, ApiErrorId.ERR_FINAL_STEAM_REQUIRED.value)
    order_after = validate_success(api.get_gown_order(order["id"], MANAGER), 200)
    assert order_after["fulfillment_status"] == "READY"


def test_full_happy_path_pickup_succeeds(api):
    """PRD §3.4: "A `BridalConsultant` or `ShopManager` performs the final steam and
    pickup, advancing `READY -> PICKED_UP`." PRD §3.7: a payment driving balance to zero
    moves payment_status to PAID_IN_FULL.

    Design: Corner/state_machines/full_happy_path_pickup_succeeds
    """
    order, _ = create_picked_up_order(order_overrides={
        "gown_style_code": "ATELIER", "ordered_size": 10, "base_price_cents": 180000,
        "standard_lead_days": 60})
    assert order["fulfillment_status"] == "PICKED_UP"
    assert order["payment_status"] == "PAID_IN_FULL"
