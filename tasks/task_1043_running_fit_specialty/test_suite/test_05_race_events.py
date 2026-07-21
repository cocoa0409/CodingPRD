"""Race events and registrations: parallel payment/packet dimensions, packet-pool
capacity boundary, refund money conservation, event-state guards, and the
uniqueness-before-capacity precedence."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_member_headers, make_staff_headers,
    TEST_USERS,
    fixtures as fx,
)
import test_helpers.factories as f

SM = TEST_USERS["store_manager_headers"]


def test_registration_payment_dimension_advances_independently(api):
    """PRD §3.5: "The owning member pays the entry fee, which moves `payment_status`
    from `UNPAID` to `PAID` and sets `amount_paid_cents` equal to the snapshotted
    `entry_fee_cents`; payment is permitted only while the registration is `UNPAID`
    and its packet is still `RESERVED`."

    Design: Difficulty/non_linear_state_machine/race_registration_parallel_payment_and_packet_dimensions
    """
    member = fx.new_member(api)
    event = fx.new_event(api, packet_capacity=2, entry_fee_cents=5000)
    reg = fx.register_for_event(api, event["id"], member["id"])
    paid = get_success_data(api.pay_registration(reg["id"], make_member_headers(member["id"])))
    assert paid["payment_status"] == "PAID"
    assert paid["packet_status"] == "RESERVED"


def test_registration_packet_allocated_while_paid(api):
    """PRD §3.5: "A staff member then allocates the reserved packet, moving
    `packet_status` from `RESERVED` to `ALLOCATED` and incrementing the event's
    `packets_allocated`; allocation requires the registration's `payment_status` to
    be `PAID` — otherwise `ERR_REGISTRATION_NOT_PAID` (409) — and the parent event to
    still be `OPEN`, otherwise `ERR_EVENT_CLOSED` (409)."

    Design: Difficulty/non_linear_state_machine/race_registration_parallel_payment_and_packet_dimensions
    """
    store = fx.new_store(api)
    staff = fx.new_staff(api, store["id"], role_type="BOTH")
    member = fx.new_member(api)
    event = fx.new_event(api, packet_capacity=2, entry_fee_cents=5000)
    reg = fx.register_for_event(api, event["id"], member["id"])
    fx.pay_registration(api, reg["id"], member["id"])
    allocated = get_success_data(api.allocate_registration(reg["id"], make_staff_headers(staff["id"])))
    assert allocated["payment_status"] == "PAID"
    assert allocated["packet_status"] == "ALLOCATED"


def test_registration_admitted_while_pool_available(api):
    """PRD §3.5: "the packet pool must not be exhausted — a registration is admitted
    only while `active_registrations` is strictly less than `packet_capacity`, and an
    attempt made when they are already equal is rejected with `ERR_EVENT_FULL`
    (409)."

    Design: Difficulty/boundary_precision_check/race_packet_pool_exhausted_rejects_registration
    """
    member = fx.new_member(api)
    event = fx.new_event(api, name="Marathon", packet_capacity=1, entry_fee_cents=5000)
    # active_registrations (0) < packet_capacity (1): admitted.
    data = validate_success(
        api.create_registration(event["id"], f.create_registration_payload(member["id"]), make_member_headers(member["id"])),
        201,
    )
    assert data["packet_status"] == "RESERVED"
    assert fx.get_event(api, event["id"])["active_registrations"] == 1


def test_registration_rejected_when_pool_exhausted(api):
    """PRD §3.5: "the packet pool must not be exhausted — a registration is admitted
    only while `active_registrations` is strictly less than `packet_capacity`, and an
    attempt made when they are already equal is rejected with `ERR_EVENT_FULL`
    (409)."

    Design: Difficulty/boundary_precision_check/race_packet_pool_exhausted_rejects_registration
    """
    m1 = fx.new_member(api)
    m2 = fx.new_member(api)
    event = fx.new_event(api, name="Marathon", packet_capacity=1, entry_fee_cents=5000)
    fx.register_for_event(api, event["id"], m1["id"])
    resp = api.create_registration(event["id"], f.create_registration_payload(m2["id"]), make_member_headers(m2["id"]))
    validate_error(resp, ApiErrorId.ERR_EVENT_FULL, 409)
    assert fx.get_event(api, event["id"])["active_registrations"] == 1


def test_paid_registration_cancel_refunds_net_of_fee(api):
    """PRD §3.5: "When the cancelled registration had been paid, the cancellation
    additionally refunds the member: `payment_status` becomes `REFUNDED`,
    `refund_cents` is set to `amount_paid_cents` minus a cancellation fee of 500
    cents but never below zero (floored at 0), and that refund amount is credited to
    the member's `wallet_credit_cents`."

    Design: Difficulty/compensating_invariant/race_money_conserved_across_pay_then_cancel
    """
    member = fx.new_member(api)
    event = fx.new_event(api, name="Half", packet_capacity=2, entry_fee_cents=5000)
    reg = fx.register_for_event(api, event["id"], member["id"])
    fx.pay_registration(api, reg["id"], member["id"])
    cancelled = get_success_data(api.cancel_registration(reg["id"], make_member_headers(member["id"])))
    assert cancelled["refund_cents"] == 4500
    assert fx.get_member(api, member["id"])["wallet_credit_cents"] == 4500


def test_paid_registration_cancel_releases_and_refunds(api):
    """PRD §3.5: "The owning member may cancel a registration from either `RESERVED`
    or `ALLOCATED`, which sets `packet_status` to `RELEASED` and decrements the
    event's `active_registrations`, freeing a slot; if the packet had been
    `ALLOCATED`, the event's `packets_allocated` is also decremented."

    Design: Difficulty/compensating_invariant/race_money_conserved_across_pay_then_cancel
    """
    member = fx.new_member(api)
    event = fx.new_event(api, name="Half", packet_capacity=2, entry_fee_cents=5000)
    reg = fx.register_for_event(api, event["id"], member["id"])
    paid = fx.pay_registration(api, reg["id"], member["id"])
    assert paid["amount_paid_cents"] == 5000
    cancelled = get_success_data(api.cancel_registration(reg["id"], make_member_headers(member["id"])))
    assert cancelled["payment_status"] == "REFUNDED"
    assert cancelled["packet_status"] == "RELEASED"


def test_allocate_on_closed_event_rejected(api):
    """PRD §3.5: "allocation requires the registration's `payment_status` to be
    `PAID` — otherwise `ERR_REGISTRATION_NOT_PAID` (409) — and the parent event to
    still be `OPEN`, otherwise `ERR_EVENT_CLOSED` (409)."

    Design: Difficulty/cross_entity_state_dependency/allocate_requires_parent_event_open
    """
    store = fx.new_store(api)
    staff = fx.new_staff(api, store["id"], role_type="BOTH")
    member = fx.new_member(api)
    event = fx.new_event(api, name="Trail", packet_capacity=2, entry_fee_cents=5000)
    reg = fx.register_for_event(api, event["id"], member["id"])
    fx.pay_registration(api, reg["id"], member["id"])
    get_success_data(api.close_event(event["id"], SM))
    resp = api.allocate_registration(reg["id"], make_staff_headers(staff["id"]))
    validate_error(resp, ApiErrorId.ERR_EVENT_CLOSED, 409)


def test_allocate_on_open_event_succeeds(api):
    """PRD §3.5: "allocation requires the registration's `payment_status` to be
    `PAID` — otherwise `ERR_REGISTRATION_NOT_PAID` (409) — and the parent event to
    still be `OPEN`, otherwise `ERR_EVENT_CLOSED` (409)."

    Design: Difficulty/cross_entity_state_dependency/allocate_requires_parent_event_open
    """
    store = fx.new_store(api)
    staff = fx.new_staff(api, store["id"], role_type="BOTH")
    member = fx.new_member(api)
    event = fx.new_event(api, name="Trail", packet_capacity=2, entry_fee_cents=5000)
    reg = fx.register_for_event(api, event["id"], member["id"])
    fx.pay_registration(api, reg["id"], member["id"])
    allocated = get_success_data(api.allocate_registration(reg["id"], make_staff_headers(staff["id"])))
    assert allocated["packet_status"] == "ALLOCATED"


def test_reregister_reports_already_registered_over_full(api):
    """PRD §3.5: "Three conditions guard registration, checked in this order: the
    parent event must be `OPEN`, else `ERR_EVENT_CLOSED` (409); the member must not
    already hold a non-`RELEASED` registration for this event, else
    `ERR_ALREADY_REGISTERED` (409); and the packet pool must not be exhausted — a
    registration is admitted only while `active_registrations` is strictly less than
    `packet_capacity`, and an attempt made when they are already equal is rejected
    with `ERR_EVENT_FULL` (409)."

    Design: Difficulty/priority_pair_validation_conflict/register_uniqueness_beats_event_full_fiscal
    """
    m1 = fx.new_member(api)
    event = fx.new_event(api, name="5K", packet_capacity=1, entry_fee_cents=5000)
    fx.register_for_event(api, event["id"], m1["id"])
    resp = api.create_registration(event["id"], f.create_registration_payload(m1["id"]), make_member_headers(m1["id"]))
    validate_error(resp, ApiErrorId.ERR_ALREADY_REGISTERED, 409)


def test_reregister_rejection_leaves_active_registrations_unchanged(api):
    """PRD §3.5: "the member must not already hold a non-`RELEASED` registration for
    this event, else `ERR_ALREADY_REGISTERED` (409)"

    Design: Difficulty/priority_pair_validation_conflict/register_uniqueness_beats_event_full_fiscal
    """
    m1 = fx.new_member(api)
    event = fx.new_event(api, name="5K", packet_capacity=1, entry_fee_cents=5000)
    fx.register_for_event(api, event["id"], m1["id"])
    api.create_registration(event["id"], f.create_registration_payload(m1["id"]), make_member_headers(m1["id"]))
    assert fx.get_event(api, event["id"])["active_registrations"] == 1


def test_allocate_unpaid_registration_rejected(api):
    """PRD §3.5: "allocation requires the registration's `payment_status` to be
    `PAID` — otherwise `ERR_REGISTRATION_NOT_PAID` (409) — and the parent event to
    still be `OPEN`, otherwise `ERR_EVENT_CLOSED` (409)."

    Design: Corner/validations/allocate_unpaid_registration_returns_not_paid
    """
    store = fx.new_store(api)
    staff = fx.new_staff(api, store["id"], role_type="BOTH")
    member = fx.new_member(api)
    event = fx.new_event(api, name="Dash", packet_capacity=3, entry_fee_cents=4000)
    reg = fx.register_for_event(api, event["id"], member["id"])
    resp = api.allocate_registration(reg["id"], make_staff_headers(staff["id"]))
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_NOT_PAID, 409)
