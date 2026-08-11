"""Non-linear state machines: the ride ASSIGNED -> DISPATCHING rematch cycle
and the invoice's two independent state dimensions."""
from test_helpers import (
    TEST_USERS,
    assert_invoice_money_invariants,
    create_booked_ride,
    create_client_with_billing_payer,
    create_completed_ride,
    create_compliant_driver,
    create_invoice_payload,
    create_payment_payload,
    dispatch_and_accept,
    get_success_data,
    make_billing_admin_headers,
    make_client_headers,
    make_coordinator_headers,
    make_driver_headers,
    make_family_member_headers,
    set_clock,
    setup_standard_dispatch_env,
    setup_two_driver_env,
    validate_success,
    api_client,
)

COORD = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


def _setup_rematch_cycle():
    """Two ACTIVE drivers (D1 zone north, D2 zone south); ride origin north
    dispatched once and accepted by D1. Returns (ride, d1, d2, asg1)."""
    client, d1, d2 = setup_two_driver_env()
    ride = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-05T10:00:00Z")
    offer = get_success_data(api_client.dispatch_ride(ride["id"], COORD))
    get_success_data(api_client.respond_assignment(
        offer["id"], {"decision": "ACCEPT"}, make_driver_headers(d1["id"])))
    return ride, d1, d2, offer


def test_release_returns_ride_to_dispatching_with_releaser_excluded(api):
    """PRD §3.5: "releasing an `ACCEPTED` assignment (any other status is
    `ERR_ASSIGNMENT_RELEASE_INVALID`, with an optional `reason` recorded)
    stamps `release_reason` of `DRIVER_RELEASE` and pushes the ride through the
    rematch cycle — back to `DISPATCHING` with `assigned_driver_id` cleared,
    `dispatch_round` incremented, the releasing driver added to
    `excluded_driver_ids`, and a `RELEASED` event logged."

    Design: Difficulty/non_linear_state_machine/ride_release_rematch_cycle_excludes_releaser
    """
    ride, d1, _, asg1 = _setup_rematch_cycle()
    released = get_success_data(api_client.release_assignment(
        asg1["id"], {"reason": "vehicle trouble"}, make_driver_headers(d1["id"])))
    assert released["status"] == "RELEASED"
    assert released["release_reason"] == "DRIVER_RELEASE"
    mid = validate_success(api_client.get_ride(ride["id"], COORD))
    assert mid["status"] == "DISPATCHING"
    assert mid["dispatch_round"] == 2
    assert mid["assigned_driver_id"] is None
    assert d1["id"] in mid["excluded_driver_ids"]


def test_rematch_offer_lands_on_other_driver_and_completes_cycle(api):
    """PRD §3.5: "Declining appends the driver to `excluded_driver_ids` and
    logs `DECLINED`, so re-offers after a decline or a timeout run the selector
    with the exclusion set applied."
    PRD §3.5: "headroom under the daily cap such that `current_load_minutes`
    plus the ride's `estimated_duration_minutes` stays at or below
    `max_daily_service_minutes`; and absence from the ride's
    `excluded_driver_ids`."
    PRD §3.5: "A clean acceptance moves the ride to `ASSIGNED`, sets
    `assigned_driver_id`, stamps `responded_at`, and appends an `ACCEPTED`
    event."

    Design: Difficulty/non_linear_state_machine/ride_release_rematch_cycle_excludes_releaser
    """
    ride, d1, d2, asg1 = _setup_rematch_cycle()
    get_success_data(api_client.release_assignment(
        asg1["id"], {"reason": "vehicle trouble"}, make_driver_headers(d1["id"])))
    offer2 = get_success_data(api_client.dispatch_ride(ride["id"], COORD))
    assert offer2["driver_id"] == d2["id"], (
        f"re-offer must exclude the releasing driver and land on D2; got "
        f"{offer2['driver_id']}")
    get_success_data(api_client.respond_assignment(
        offer2["id"], {"decision": "ACCEPT"}, make_driver_headers(d2["id"])))
    end = validate_success(api_client.get_ride(ride["id"], COORD))
    assert end["status"] == "ASSIGNED"
    assert end["assigned_driver_id"] == d2["id"]
    assert end["dispatch_round"] == 3


def _setup_issued_invoice_with_payer():
    """Completed 60-min / 10-mi ride (fare 4500) invoiced and issued for a
    client with a BILLING_PAYER family member. Returns (client, member, invoice)."""
    client, member = create_client_with_billing_payer()
    from test_helpers import create_active_rate_card
    create_active_rate_card()
    driver, _ = create_compliant_driver()
    set_clock("2026-05-20T09:00:00Z")
    create_completed_ride(
        client["id"], driver["id"], "2026-06-01T10:00:00Z",
        estimated_duration_minutes=60, estimated_distance_miles=10,
        actual_distance_miles=10, service_minutes=60)
    invoice = get_success_data(api_client.generate_invoice(
        create_invoice_payload(client["id"], period_start="2026-06-01", period_end="2026-06-08"),
        BILLING))
    invoice = get_success_data(api_client.issue_invoice(invoice["id"], BILLING))
    return client, member, invoice


def test_payment_and_dispute_advance_independent_dimensions(api):
    """PRD §3.8: "The invoice carries **two independent state dimensions**. The
    issuance dimension (`issuance_status`: `DRAFT`, `ISSUED`, `PARTIALLY_PAID`,
    `PAID`, `VOIDED`) tracks the money; the dispute dimension (`dispute_status`:
    `NONE`, `DISPUTED`, `RESOLVED_ACCEPTED`, `RESOLVED_REJECTED`) tracks the
    disagreement, and the two evolve independently — a dispute can be raised
    and resolved while payments keep arriving against the issuance side."
    PRD §3.9: "`ISSUED` becomes `PARTIALLY_PAID` under a partial cover and
    `PAID` under a full one, with `PARTIALLY_PAID` reaching `PAID` when
    cumulative applications meet the total."

    Design: Difficulty/non_linear_state_machine/invoice_issuance_and_dispute_dimensions_independent
    """
    client, member, invoice = _setup_issued_invoice_with_payer()
    get_success_data(api_client.create_payment(
        create_payment_payload(client["id"], amount_cents=2000),
        make_family_member_headers(member["id"])))
    get_success_data(api_client.invoice_dispute_event(
        invoice["id"], {"action": "RAISE"}, make_family_member_headers(member["id"])))
    mid = validate_success(api_client.get_invoice(invoice["id"], BILLING))
    assert mid["issuance_status"] == "PARTIALLY_PAID", (
        f"2000 of 4500 paid -> PARTIALLY_PAID; got {mid['issuance_status']}")
    assert mid["dispute_status"] == "DISPUTED"


def test_invoice_reaches_paid_and_resolved_accepted_combination(api):
    """PRD §3.9: "Resolution belongs to a `BillingAdmin`: `RESOLVE_ACCEPT`
    takes a `credit_cents` goodwill amount that may not exceed the invoice's
    `total_due_cents` (an excess is rejected with `ERR_INVALID_REQUEST`), posts
    that amount into the client's `credit_balance_cents`, and records
    `resolution_credit_cents` (zero until then) and the resolver's
    `resolved_by_user_id`"
    PRD §3.8: "the two evolve independently — a dispute can be raised and
    resolved while payments keep arriving against the issuance side."

    Design: Difficulty/non_linear_state_machine/invoice_issuance_and_dispute_dimensions_independent
    """
    client, member, invoice = _setup_issued_invoice_with_payer()
    get_success_data(api_client.create_payment(
        create_payment_payload(client["id"], amount_cents=2000),
        make_family_member_headers(member["id"])))
    get_success_data(api_client.invoice_dispute_event(
        invoice["id"], {"action": "RAISE"}, make_family_member_headers(member["id"])))
    get_success_data(api_client.invoice_dispute_event(
        invoice["id"], {"action": "RESOLVE_ACCEPT", "credit_cents": 500},
        make_billing_admin_headers("bill-9")))
    get_success_data(api_client.create_payment(
        create_payment_payload(client["id"], amount_cents=2500, method="ACH"),
        make_family_member_headers(member["id"])))
    end = validate_success(api_client.get_invoice(invoice["id"], BILLING))
    assert end["issuance_status"] == "PAID"
    assert end["paid_cents"] == 4500
    assert end["dispute_status"] == "RESOLVED_ACCEPTED"
    assert_invoice_money_invariants(end)
    client_after = validate_success(api_client.get_client(client["id"], BILLING))
    assert client_after["credit_balance_cents"] == 500, (
        "resolution credit posted; the second payment fully covered the open "
        f"invoice so nothing else reached credit; got "
        f"{client_after['credit_balance_cents']}")
