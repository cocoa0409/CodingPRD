"""GarmentOrder / AlterationTicket lifecycle transitions, cross-entity state
dependencies, and the exact-deposit fitting boundary.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_confirmed_order, create_confirmed_order_with_deposit,
    create_order_at_scheduled_final, create_ready_order, create_picked_up_order,
    create_fabric, create_journeyman_tailor, create_open_room,
    setup_group_with_confirmed_members, lock_group,
    add_confirmed_member,
    create_group, create_customer, create_profile,
    create_order_payload, create_option_line_payload, create_fitting_payload,
    create_alteration_payload, create_payment_payload,
    TEST_USERS,
)

SA = TEST_USERS["sales_associate_headers"]
FS = TEST_USERS["fitting_specialist_headers"]
SM = TEST_USERS["shop_manager_headers"]


# ─── Queue B: state_machines corners ────────────────────────────────────

def test_confirm_already_confirmed_order_rejected(api):
    """PRD §3.3: "When these hold, the order advances from `DRAFT` to `CONFIRMED`".
    PRD §2.7: "Only then does the server evaluate whether the target resource is in a state
    that permits the requested transition (the state family, HTTP 409)".

    Confirming an order that is already CONFIRMED is not a valid from-state ->
    ERR_ORDER_INVALID_STATE.

    Design: Corner/state_machines/confirm_already_confirmed_order_rejected
    """
    bundle = create_confirmed_order(option_codes=("MONOGRAM",))
    res = api.confirm_order(bundle["order"]["id"], SA)
    validate_error(res, "ERR_ORDER_INVALID_STATE")


def test_cancel_picked_up_order_rejected(api):
    """PRD §3.8: "The single precondition is that the order has no pickup record; an order that already has a pickup is rejected with `ERR_ALREADY_PICKED_UP` (HTTP 409)."

    A fully completed PICKED_UP order is terminal; cancelling it -> ERR_ALREADY_PICKED_UP.

    Design: Corner/state_machines/cancel_picked_up_order_rejected_terminal_lockdown
    """
    bundle = create_picked_up_order()
    order_id = bundle["order"]["id"]
    assert bundle["order"]["status"] == "PICKED_UP"
    res = api.cancel_order(order_id, SM)
    validate_error(res, "ERR_ALREADY_PICKED_UP")
    after = get_success_data(api.get_order(order_id, SA))
    assert after["status"] == "PICKED_UP"


def test_complete_voided_alteration_rejected(api):
    """PRD §3.7: "Completing or voiding a ticket that is not `OPEN` is rejected with `ERR_ALTERATION_INVALID_STATE` (HTTP 409)."

    A ticket that was VOIDED can no longer be completed.

    Design: Corner/state_machines/alteration_complete_on_voided_ticket_rejected
    """
    bundle = create_ready_order()
    order_id = bundle["order"]["id"]
    ticket = get_success_data(api.create_alteration(
        order_id, create_alteration_payload("take in waist", billable_cents=0), FS))
    get_success_data(api.void_alteration(order_id, ticket["id"], SM))
    res = api.complete_alteration(order_id, ticket["id"], FS)
    validate_error(res, "ERR_ALTERATION_INVALID_STATE")


# ─── Queue A: cross_entity_state_dependency ─────────────────────────────

def test_grouped_order_cannot_confirm_after_group_locked(api):
    """PRD §3.3: "and if the order belongs to a group, that group must be in `FORMING` status (otherwise `ERR_GROUP_NOT_FORMING`, HTTP 409)."

    A group with 3 confirmed members is locked; a still-DRAFT member added to that group
    before the lock cannot confirm once the group is LOCKED.

    Design: Difficulty/cross_entity_state_dependency/cross_entity_order_confirm_requires_group_forming
    """
    group, members = setup_group_with_confirmed_members(num_members=3)
    fabric = members[0]["fabric"]
    # A 4th DRAFT member still attached to the group.
    customer = create_customer()
    profile = create_profile(customer["id"])
    draft = get_success_data(api.create_order(
        create_order_payload(customer["id"], profile["id"],
                             garment_type="SUIT", base_labor_cents=20000,
                             fabric_meters_required=3.0, group_order_id=group["id"]), SA))
    get_success_data(api.create_option_line(
        draft["id"], create_option_line_payload(fabric["id"], "MONOGRAM"), SA))

    lock_group(group["id"])

    res = api.confirm_order(draft["id"], SA)
    validate_error(res, "ERR_GROUP_NOT_FORMING")
    after = get_success_data(api.get_order(draft["id"], SA))
    assert after["status"] == "DRAFT"


def test_grouped_order_confirms_while_group_forming(api):
    """PRD §3.3: "and if the order belongs to a group, that group must be in `FORMING` status (otherwise `ERR_GROUP_NOT_FORMING`, HTTP 409)."

    Second cross-entity instance, the positive side of the same dependency: while the group
    is still FORMING a grouped member order confirms successfully (advances to CONFIRMED),
    proving the dependency is on the FORMING state specifically.

    Design: Difficulty/cross_entity_state_dependency/cross_entity_order_confirm_requires_group_forming
    """
    fabric = create_fabric(price_per_meter_cents=6000, bolt_meters_initial=200)
    group = create_group()
    customer = create_customer()
    profile = create_profile(customer["id"])
    draft = get_success_data(api.create_order(
        create_order_payload(customer["id"], profile["id"],
                             garment_type="SUIT", base_labor_cents=20000,
                             fabric_meters_required=3.0, group_order_id=group["id"]), SA))
    get_success_data(api.create_option_line(
        draft["id"], create_option_line_payload(fabric["id"], "MONOGRAM"), SA))

    confirmed = validate_success(api.confirm_order(draft["id"], SA), 200)
    assert confirmed["status"] == "CONFIRMED"


def test_record_outcome_requires_order_in_fitting(api):
    """PRD §3.5: "An outcome may be recorded only while the parent order is `IN_FITTING`; otherwise the attempt is rejected with `ERR_ORDER_NOT_IN_FITTING` (HTTP 409)."

    An order reached IN_FITTING via a scheduled BASTED fitting, then was cancelled (the
    cascade FAILs the fitting). Recording PASS on that fitting is rejected because the
    parent order is no longer IN_FITTING.

    Design: Difficulty/cross_entity_state_dependency/cross_entity_fitting_outcome_requires_order_in_fitting
    """
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=50)
    tailor = create_journeyman_tailor()
    room = create_open_room()
    bundle = create_confirmed_order_with_deposit(fabric=fabric, bolt_meters_initial=50)
    order = get_success_data(api.get_order(bundle["order"]["id"], SA))
    basted = get_success_data(api.create_fitting(
        order["id"],
        create_fitting_payload(tailor["id"], room["id"], "BASTED",
                               "2026-07-08T09:00:00.000Z", "2026-07-08T10:00:00.000Z",
                               order["version"]),
        FS))
    in_fitting = get_success_data(api.get_order(order["id"], SA))
    assert in_fitting["status"] == "IN_FITTING"

    validate_success(api.cancel_order(order["id"], SM), 200)
    res = api.record_fitting_outcome(order["id"], basted["id"], {"result": "PASS"}, FS)
    validate_error(res, "ERR_ORDER_NOT_IN_FITTING")
    after = get_success_data(api.get_order(order["id"], SA))
    assert after["status"] == "CANCELLED"


def test_record_outcome_rejected_after_order_reaches_ready(api):
    """PRD §3.5: "An outcome may be recorded only while the parent order is `IN_FITTING`; otherwise the attempt is rejected with `ERR_ORDER_NOT_IN_FITTING` (HTTP 409)."

    Second cross-entity instance reaching the same rule from a different parent state: once
    a FINAL pass bubbles the order to READY, the order is no longer IN_FITTING, so recording
    another outcome on the (now PASSED) FINAL fitting is rejected on order state.

    Design: Difficulty/cross_entity_state_dependency/cross_entity_fitting_outcome_requires_order_in_fitting
    """
    bundle = create_ready_order()
    order_id = bundle["order"]["id"]
    assert bundle["order"]["status"] == "READY"
    res = api.record_fitting_outcome(order_id, bundle["fittings"]["final"]["id"], {"result": "PASS"}, FS)
    validate_error(res, "ERR_ORDER_NOT_IN_FITTING")


# ─── Queue A: boundary_precision_check (exact deposit) ──────────────────

def test_exact_deposit_allows_first_fitting(api):
    """PRD §3.3: "The very first fitting of round zero may be scheduled only once a `DEPOSIT` payment has been captured summing to at least `deposit_due_cents`; absent that, the transition to fitting is rejected with `ERR_DEPOSIT_NOT_PAID` (HTTP 402)."

    Paying exactly deposit_due_cents (48750) — not a cent more — meets the "at least"
    gate, so the first BASTED fitting schedules and the order advances to IN_FITTING.

    Design: Difficulty/boundary_precision_check/boundary_deposit_exactly_meets_threshold_allows_first_fitting
    """
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=50)
    tailor = create_journeyman_tailor()
    room = create_open_room()
    bundle = create_confirmed_order(fabric=fabric, bolt_meters_initial=50,
                                    base_labor_cents=40000, fabric_meters_required=7.0)
    order = bundle["order"]
    assert order["deposit_due_cents"] == 48750
    get_success_data(api.create_payment(order["id"], create_payment_payload("DEPOSIT", 48750), SA))

    order = get_success_data(api.get_order(order["id"], SA))
    fitting = validate_success(api.create_fitting(
        order["id"],
        create_fitting_payload(tailor["id"], room["id"], "BASTED",
                               "2026-07-06T09:00:00.000Z", "2026-07-06T10:00:00.000Z",
                               order["version"]),
        FS), 201)
    assert fitting["outcome"] == "SCHEDULED"
    after = get_success_data(api.get_order(order["id"], SA))
    assert after["status"] == "IN_FITTING"


def test_unpaid_deposit_blocks_first_fitting(api):
    """PRD §3.3: "The very first fitting of round zero may be scheduled only once a `DEPOSIT` payment has been captured summing to at least `deposit_due_cents`; absent that, the transition to fitting is rejected with `ERR_DEPOSIT_NOT_PAID` (HTTP 402)."

    Boundary below-threshold companion: with NO deposit captured, scheduling the first
    fitting is rejected and the order stays CONFIRMED.

    Design: Difficulty/boundary_precision_check/boundary_deposit_exactly_meets_threshold_allows_first_fitting
    """
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=50)
    tailor = create_journeyman_tailor()
    room = create_open_room()
    bundle = create_confirmed_order(fabric=fabric, bolt_meters_initial=50,
                                    base_labor_cents=40000, fabric_meters_required=7.0)
    order = bundle["order"]
    res = api.create_fitting(
        order["id"],
        create_fitting_payload(tailor["id"], room["id"], "BASTED",
                               "2026-07-06T09:00:00.000Z", "2026-07-06T10:00:00.000Z",
                               order["version"]),
        FS)
    validate_error(res, "ERR_DEPOSIT_NOT_PAID")
    after = get_success_data(api.get_order(order["id"], SA))
    assert after["status"] == "CONFIRMED"
