"""Boundary precision: cancellation-notice fee tiers at 1440/240/239 minutes,
and the wait-grace boundary at included_wait_minutes."""
from test_helpers import (
    TEST_USERS,
    create_booked_ride,
    create_client,
    create_completed_ride,
    create_invoice_payload,
    get_success_data,
    make_client_headers,
    set_clock,
    setup_standard_dispatch_env,
    validate_paginated,
    validate_success,
    api_client,
)

BILLING = TEST_USERS["billing_admin_headers"]


def test_cancel_at_exactly_1440_minutes_notice_is_free(api):
    """PRD §3.7: "Notice of at least a full day — 1,440 minutes — is free;
    exactly 1,440 is free."

    Design: Difficulty/boundary_precision_check/cancellation_notice_exact_boundaries
    """
    client, _ = setup_standard_dispatch_env(with_driver=False, clock="2026-06-08T09:00:00Z")
    ride = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-10T12:00:00Z")
    set_clock("2026-06-09T12:00:00Z")
    cancelled = validate_success(api_client.cancel_ride(
        ride["id"], {"cancel_note": "plans changed"}, make_client_headers(client["id"])))
    assert cancelled["cancellation_fee_cents"] == 0, (
        f"1440 minutes of notice is the free boundary; got "
        f"{cancelled['cancellation_fee_cents']}")
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "CUSTOMER"


def test_cancel_at_exactly_240_minutes_notice_is_half_fee(api):
    """PRD §3.7: "Notice of at least four hours — 240 minutes — but less than a
    full day bills half of `minimum_charge_cents`, rounded half-up to whole
    cents; exactly 240 lands in this half-fee tier."

    Design: Difficulty/boundary_precision_check/cancellation_notice_exact_boundaries
    """
    client, _ = setup_standard_dispatch_env(with_driver=False, clock="2026-06-08T09:00:00Z")
    ride = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-10T16:00:00Z")
    set_clock("2026-06-10T12:00:00Z")
    cancelled = validate_success(api_client.cancel_ride(
        ride["id"], {"cancel_note": "plans changed"}, make_client_headers(client["id"])))
    # round_half_up(2501 * 0.5) = 1251
    assert cancelled["cancellation_fee_cents"] == 1251, (
        f"exactly 240 minutes lands in the 50% tier: 1251; got "
        f"{cancelled['cancellation_fee_cents']}")


def test_cancel_at_239_minutes_notice_is_full_fee(api):
    """PRD §3.7: "Anything shorter bills the full `minimum_charge_cents`; 239
    minutes of notice is already a full-fee cancel."

    Design: Difficulty/boundary_precision_check/cancellation_notice_exact_boundaries
    """
    client, _ = setup_standard_dispatch_env(with_driver=False, clock="2026-06-08T09:00:00Z")
    ride = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-10T15:59:00Z")
    set_clock("2026-06-10T12:00:00Z")
    cancelled = validate_success(api_client.cancel_ride(
        ride["id"], {"cancel_note": "plans changed"}, make_client_headers(client["id"])))
    assert cancelled["cancellation_fee_cents"] == 2501, (
        f"239 minutes is the 100% tier: full 2501; got "
        f"{cancelled['cancellation_fee_cents']}")


def _setup_wait_grace_pair():
    """Two completed rides on 2026-06-01: ride A with total wait exactly 10
    (== included_wait_minutes), ride B with total wait 11. Returns invoice."""
    client, driver = setup_standard_dispatch_env(clock="2026-05-31T09:00:00Z")
    create_completed_ride(
        client["id"], driver["id"], "2026-06-01T10:00:00Z",
        estimated_duration_minutes=60, estimated_distance_miles=10,
        actual_distance_miles=10, service_minutes=60, wait_segments=((0, 10),))
    create_completed_ride(
        client["id"], driver["id"], "2026-06-01T14:00:00Z",
        estimated_duration_minutes=60, estimated_distance_miles=10,
        actual_distance_miles=10, service_minutes=60, wait_segments=((0, 11),))
    invoice = get_success_data(api_client.generate_invoice(
        create_invoice_payload(client["id"], period_start="2026-06-01", period_end="2026-06-08"),
        BILLING))
    return invoice


def test_wait_equal_to_grace_bills_zero_minutes(api):
    """PRD §3.6: "Billing applies the rate card's grace exactly — wait equal to
    `included_wait_minutes` bills zero minutes, and wait one minute above the
    grace bills exactly one minute."
    PRD §3.8: "a `WAIT` line only when the billable wait exceeds zero"

    Design: Difficulty/boundary_precision_check/wait_grace_exact_boundaries
    """
    invoice = _setup_wait_grace_pair()
    # Ride A: 3000 hourly + 1500 mileage + 0 wait = 4500.
    # Ride B: 3000 + 1500 + 50 = 4550. Total 9050.
    assert invoice["charges_cents"] == 9050, (
        f"4500 (wait == grace bills nothing) + 4550 = 9050; got "
        f"{invoice['charges_cents']}")
    resp = api_client.list_invoice_lines(invoice["id"], BILLING)
    lines, _ = validate_paginated(resp)
    kinds = [line["line_kind"] for line in lines]
    assert kinds == ["HOURLY", "MILEAGE", "HOURLY", "MILEAGE", "WAIT"], (
        f"no WAIT line for the at-grace ride; pinned emission order; got {kinds}")


def test_wait_one_minute_above_grace_bills_exactly_one(api):
    """PRD §3.6: "Billing applies the rate card's grace exactly — wait equal to
    `included_wait_minutes` bills zero minutes, and wait one minute above the
    grace bills exactly one minute."
    PRD §3.3: "Third, the wait charge is the billable wait — total wait minutes
    minus `included_wait_minutes`, floored at zero — multiplied by
    `wait_per_minute_cents`."

    Design: Difficulty/boundary_precision_check/wait_grace_exact_boundaries
    """
    invoice = _setup_wait_grace_pair()
    resp = api_client.list_invoice_lines(invoice["id"], BILLING)
    lines, _ = validate_paginated(resp)
    wait_lines = [line for line in lines if line["line_kind"] == "WAIT"]
    assert len(wait_lines) == 1
    assert wait_lines[0]["quantity"] == 1, "exactly 1 billable minute at wait 11 - 10"
    assert wait_lines[0]["amount_cents"] == 50
