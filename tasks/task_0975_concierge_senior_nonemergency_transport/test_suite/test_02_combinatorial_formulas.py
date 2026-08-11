"""Combinatorial money formulas: floor+multiplier composition, per-line
rounding order, and the pinned credit-application evaluation order."""
from test_helpers import (
    TEST_USERS,
    assert_invoice_money_invariants,
    create_active_wav_rate_card,
    create_booked_ride,
    create_client,
    create_client_with_billing_payer,
    create_completed_ride,
    create_compliant_driver,
    create_invoice_payload,
    dispatch_and_accept,
    execute_ride_happy_path,
    get_success_data,
    make_client_headers,
    seed_credit_via_payment,
    set_clock,
    setup_standard_dispatch_env,
    validate_paginated,
    validate_success,
    api_client,
)

COORD = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


def _setup_after_hours_floor_ride():
    """Ride picked up 2026-06-02T19:00:00Z (after the 18:00 after-hours
    start), completed with 12 wait min, 30 service min, 4 mi."""
    client, driver = setup_standard_dispatch_env(clock="2026-05-20T09:00:00Z")
    ride = create_booked_ride(
        client["id"], kind="COMPANION_OUTING",
        scheduled_pickup_at="2026-06-02T19:00:00Z",
        estimated_duration_minutes=30, estimated_distance_miles=4)
    return client, driver, ride


def _complete_after_hours_ride(ride_id, driver_id):
    dispatch_and_accept(ride_id, driver_id)
    return execute_ride_happy_path(
        ride_id, driver_id, "2026-06-02T19:00:00Z",
        actual_distance_miles=4, service_minutes=30, wait_segments=((0, 12),))


def test_after_hours_multiplier_composes_before_floor_binds(api):
    """PRD §3.3: "Fifth, when the pickup time-of-day (minutes after midnight
    UTC) is at or after `after_hours_start_minute`, the subtotal is multiplied
    by `after_hours_multiplier_bp` and divided by ten thousand, rounded half-up
    to whole cents; pickups earlier in the day skip this step. Sixth, the fare
    is floored at `minimum_charge_cents`; the difference between the floor and
    the subtotal is the minimum adjustment, zero when the floor does not bind."

    Design: Difficulty/combinatorial_formula/fare_floor_binds_after_hours_multiplier
    """
    _, driver, ride = _setup_after_hours_floor_ride()
    completed = _complete_after_hours_ride(ride["id"], driver["id"])
    # hourly 1500 + mileage 600 + wait (12-10)*50 = 100 -> subtotal 2200;
    # after-hours x1.1 -> 2420; max(2420, 2501) floor binds -> 2501.
    assert completed["final_fare_cents"] == 2501, (
        f"floor must bind last at 2501, got {completed['final_fare_cents']}")


def test_after_hours_floor_ride_wait_and_service_totals(api):
    """PRD §3.6: "the ride's `wait_minutes` starts at zero and is the sum, over
    closed `WAIT_STARTED`/`WAIT_ENDED` event pairs in occurrence order, of each
    pair's elapsed whole minutes."
    PRD §3.6: "it computes `service_minutes` as the whole minutes from service
    start to completion, finalizes `wait_minutes`, evaluates the
    final-settlement fare variant of §3.3 into `final_fare_cents`, and logs
    `COMPLETED`."

    Design: Difficulty/combinatorial_formula/fare_floor_binds_after_hours_multiplier
    """
    _, driver, ride = _setup_after_hours_floor_ride()
    completed = _complete_after_hours_ride(ride["id"], driver["id"])
    assert completed["wait_minutes"] == 12, (
        f"replayed wait must be 12 (2 billable after the 10-minute grace); got "
        f"{completed['wait_minutes']}")
    assert completed["service_minutes"] == 30
    assert completed["status"] == "COMPLETED"


def _setup_two_late_cancel_invoice():
    """Client with two rides cancelled at exactly 240 minutes of notice
    (50% tier of a 2501-cent minimum), invoiced over [2026-06-08, 2026-06-15)."""
    setup_standard_dispatch_env(with_driver=False, clock="2026-06-08T09:00:00Z")
    client = create_client()
    client_id = client["id"]
    ride_a = create_booked_ride(client_id, scheduled_pickup_at="2026-06-10T16:00:00Z")
    ride_b = create_booked_ride(client_id, scheduled_pickup_at="2026-06-11T16:00:00Z")
    set_clock("2026-06-10T12:00:00Z")
    get_success_data(api_client.cancel_ride(
        ride_a["id"], {"cancel_note": "feeling unwell"}, make_client_headers(client_id)))
    set_clock("2026-06-11T12:00:00Z")
    get_success_data(api_client.cancel_ride(
        ride_b["id"], {"cancel_note": "feeling unwell"}, make_client_headers(client_id)))
    invoice = get_success_data(api_client.generate_invoice(
        create_invoice_payload(client_id, period_start="2026-06-08", period_end="2026-06-15"),
        BILLING))
    return client, invoice


def test_invoice_sums_per_line_rounded_amounts(api):
    """PRD §3.8: "Each line's `amount_cents` is rounded half-up to whole cents
    at line level **first**, and the invoice's `charges_cents` is the plain sum
    of those rounded amounts — never a sum of unrounded amounts rounded once."
    PRD §3.8: "two late-cancel fees each computed as half of a 2,501-cent
    minimum round to 1,251 cents apiece at line level, so the invoice charges
    2,502 cents, not 2,501."

    Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum
    """
    _, invoice = _setup_two_late_cancel_invoice()
    assert invoice["charges_cents"] == 2502, (
        f"charges must be 1251 + 1251 = 2502, not 2501; got {invoice['charges_cents']}")
    assert invoice["total_due_cents"] == 2502
    assert_invoice_money_invariants(invoice)


def test_invoice_lines_each_round_half_up(api):
    """PRD §3.8: "Fee-bearing cancellations contribute a single
    `CANCELLATION_FEE` line of quantity one; no-shows a single `NO_SHOW_FEE`
    line of quantity one."
    PRD §3.8: "Each line's `amount_cents` is rounded half-up to whole cents at
    line level **first**, and the invoice's `charges_cents` is the plain sum of
    those rounded amounts — never a sum of unrounded amounts rounded once."

    Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum
    """
    _, invoice = _setup_two_late_cancel_invoice()
    resp = api_client.list_invoice_lines(invoice["id"], BILLING)
    lines, _ = validate_paginated(resp)
    assert len(lines) == 2
    for line in lines:
        assert line["line_kind"] == "CANCELLATION_FEE"
        assert line["amount_cents"] == 1251, (
            f"each 50%-of-2501 fee line rounds half-up to 1251; got "
            f"{line['amount_cents']}")
        assert line["quantity"] == 1


def _setup_credit_cap_invoice():
    """POWER_WHEELCHAIR client with 3000 credit; completed WAV ride
    (service 120 min, 16 mi, zero wait) -> charges 11200."""
    create_active_wav_rate_card()
    client, member = create_client_with_billing_payer(
        full_name="Walt W", mobility_aid="POWER_WHEELCHAIR",
        assist_level_default="DOOR_THROUGH_DOOR", home_zone="north",
        address="9 Oak Ave")
    seed_credit_via_payment(client["id"], 3000, payer_member_id=member["id"])
    driver, _ = create_compliant_driver(
        full_name="Vic V", vehicle_class="WAV",
        assist_certification="DOOR_THROUGH_DOOR", home_zone="north")
    set_clock("2026-05-20T09:00:00Z")
    create_completed_ride(
        client["id"], driver["id"], "2026-06-03T10:00:00Z",
        kind="APPOINTMENT", estimated_duration_minutes=120,
        estimated_distance_miles=16, actual_distance_miles=16,
        service_minutes=120)
    return client


def test_credit_applied_capped_at_half_of_pre_credit_charges(api):
    """PRD §3.8: "`credit_applied_cents` is then the smaller of the client's
    current `credit_balance_cents` and half of `charges_cents` — the cap is
    5,000 basis points of the pre-credit charges, taken by floor division."
    PRD §3.8: "`total_due_cents` is the charges minus the applied credit."

    Design: Difficulty/combinatorial_formula/credit_share_capped_before_deduction
    """
    client = _setup_credit_cap_invoice()
    invoice = get_success_data(api_client.generate_invoice(
        create_invoice_payload(client["id"], period_start="2026-06-01", period_end="2026-06-08"),
        BILLING))
    assert invoice["charges_cents"] == 11200, (
        f"7200 hourly + 2800 mileage + 1200 WAV surcharge = 11200; got "
        f"{invoice['charges_cents']}")
    assert invoice["credit_applied_cents"] == 3000, (
        f"min(balance 3000, floor(11200 * 5000 / 10000) = 5600) = 3000; got "
        f"{invoice['credit_applied_cents']}")
    assert invoice["total_due_cents"] == 8200
    assert_invoice_money_invariants(invoice)


def test_generation_debits_client_credit_pool(api):
    """PRD §3.8: "Generation debits the client's pool by exactly
    `credit_applied_cents` (skipped when zero, leaving the client row
    untouched), and the invoice's `due_date` is set fourteen days after
    `period_end`."

    Design: Difficulty/combinatorial_formula/credit_share_capped_before_deduction
    """
    client = _setup_credit_cap_invoice()
    invoice = get_success_data(api_client.generate_invoice(
        create_invoice_payload(client["id"], period_start="2026-06-01", period_end="2026-06-08"),
        BILLING))
    after = validate_success(api_client.get_client(client["id"], BILLING))
    assert after["credit_balance_cents"] == 0, (
        f"pool must drop 3000 -> 0 at generation; got {after['credit_balance_cents']}")
    assert invoice["due_date"] == "2026-06-22", (
        f"due_date = period_end + 14 days = 2026-06-22; got {invoice['due_date']}")
