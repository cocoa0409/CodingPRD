"""Calculation corner cases: the payment waterfall over two invoices, invoice
input-set filtering, standing-ride horizon generation, and the overdue-AR
boundary at the due date."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_rate_card,
    create_booked_ride,
    create_client,
    create_client_with_billing_payer,
    create_invoice_payload,
    create_late_cancel_invoice,
    create_payment_payload,
    create_standing_ride_payload,
    get_success_data,
    make_client_headers,
    make_family_member_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


def test_payment_waterfall_two_invoices_oldest_first(api):
    """PRD §3.9: "The tendered amount waterfall-applies to the client's open
    invoices — those `ISSUED` or `PARTIALLY_PAID` with `total_due_cents` still
    above `paid_cents` — in `due_date` ascending order with `created_at`
    ascending breaking ties. Each candidate absorbs the smaller of the
    remaining tender and its outstanding balance; the application is recorded
    in the payment's `applications` array as an `invoice_id` / `applied_cents`
    pair in allocation order, the invoice's `paid_cents` (initially zero) grows
    by the applied amount, and its issuance status recomputes"
    PRD §3.9: "Any remainder beyond all open invoices is credited to the
    client's `credit_balance_cents`."

    Design: Corner/calculations/payment_waterfall_two_invoices_oldest_first
    """
    client, member = create_client_with_billing_payer()
    create_active_rate_card()
    inv1, _ = create_late_cancel_invoice(
        client["id"], "2026-05-04T12:00:00Z", "2026-05-04T16:00:00Z",
        "2026-05-01", "2026-05-08", issue=True)
    inv2, _ = create_late_cancel_invoice(
        client["id"], "2026-06-03T12:00:00Z", "2026-06-03T16:00:00Z",
        "2026-06-01", "2026-06-08", issue=True)
    # due_dates: inv1 2026-05-22, inv2 2026-06-22 -> inv1 fills first.
    payment = get_success_data(api_client.create_payment(
        create_payment_payload(client["id"], amount_cents=2000, method="ACH"),
        make_family_member_headers(member["id"])))
    assert payment["applications"] == [
        {"invoice_id": inv1["id"], "applied_cents": 1251},
        {"invoice_id": inv2["id"], "applied_cents": 749},
    ], f"due_date ASC allocation 1251 then 749; got {payment['applications']}"
    first = validate_success(api_client.get_invoice(inv1["id"], BILLING))
    assert first["issuance_status"] == "PAID"
    assert first["paid_cents"] == 1251
    second = validate_success(api_client.get_invoice(inv2["id"], BILLING))
    assert second["issuance_status"] == "PARTIALLY_PAID"
    assert second["paid_cents"] == 749
    credit = validate_success(api_client.get_client(client["id"], BILLING))
    assert credit["credit_balance_cents"] == 0, "no remainder: 1251 + 749 == 2000"


def test_invoice_input_set_excludes_free_cancels_and_unfinished(api):
    """PRD §3.8: "Billable work in the period is precisely: `COMPLETED` rides;
    `CANCELLED` rides whose `cancellation_fee_cents` is positive; and
    `NO_SHOW` rides — all keyed by the pickup date falling inside the half-open
    window. Rides still open, and fee-free cancellations, bill nothing."
    PRD §3.8: "Fee-bearing cancellations contribute a single
    `CANCELLATION_FEE` line of quantity one"

    Design: Corner/calculations/invoice_input_set_excludes_free_cancels_and_unfinished
    """
    client = create_client()
    create_active_rate_card()
    set_clock("2026-05-20T09:00:00Z")
    r_free = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-02T10:00:00Z")
    r_late = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-03T16:00:00Z")
    create_booked_ride(client["id"], scheduled_pickup_at="2026-06-04T10:00:00Z")
    # Free cancel: notice 1440+ (created 05-20 for 06-02 pickup).
    get_success_data(api_client.cancel_ride(
        r_free["id"], {"cancel_note": "early cancel"}, make_client_headers(client["id"])))
    # Late cancel: exactly 240 minutes of notice.
    set_clock("2026-06-03T12:00:00Z")
    get_success_data(api_client.cancel_ride(
        r_late["id"], {"cancel_note": "late cancel"}, make_client_headers(client["id"])))
    invoice = get_success_data(api_client.generate_invoice(
        create_invoice_payload(client["id"], period_start="2026-06-01", period_end="2026-06-08"),
        BILLING))
    assert invoice["charges_cents"] == 1251, (
        f"only the late-cancel fee bills; got {invoice['charges_cents']}")
    resp = api_client.list_invoice_lines(invoice["id"], BILLING)
    lines, _ = validate_paginated(resp)
    assert len(lines) == 1
    assert lines[0]["line_kind"] == "CANCELLATION_FEE"
    assert lines[0]["amount_cents"] == 1251


def test_standing_generation_respects_horizon(api):
    """PRD §3.4: "Creation immediately generates occurrences: for every
    calendar date matching the series weekday that falls from the logical today
    through the earlier of `ends_on` and fourteen days out — today included — a
    `SCHEDULED` ride is created with `scheduled_pickup_at` at the cadence time,
    the estimated fields and `kind` copied, and `standing_ride_id` set."
    PRD §3.4: "The series' computed `next_occurrence_date` is the earliest
    cadence date from today forward within the inclusive range, or null when
    none remains."
    PRD §3.10: "Second, horizon generation: standing series regenerate their
    occurrences within the fourteen-day window, keeping the pipeline of future
    `SCHEDULED` rides topped up."

    Design: Corner/calculations/standing_generation_respects_horizon
    """
    client = create_client()
    create_active_rate_card()
    set_clock("2026-05-20T09:00:00Z")
    series = get_success_data(api_client.create_standing_ride(
        create_standing_ride_payload(client["id"]), COORD))
    assert series["next_occurrence_date"] == "2026-06-01", (
        f"only Monday 2026-06-01 falls within today+14 from 2026-05-20; got "
        f"{series['next_occurrence_date']}")
    resp = api_client.list_rides(COORD, params={"standing_ride_id": series["id"]})
    rides, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"exactly one occurrence inside the horizon; got {meta['total_count']}"
    # PRD fixes the cadence date/time but not the timestamp serialization
    # format, so compare parsed instants.
    from datetime import datetime, timezone
    def _parse(ts):
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    assert _parse(rides[0]["scheduled_pickup_at"]) == datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    assert rides[0]["status"] == "SCHEDULED"
    set_clock("2026-05-30T09:00:00Z")
    cycle = get_success_data(api_client.run_cycle(ADMIN))
    assert len(cycle["generated_ride_ids"]) == 1, (
        f"exactly one new occurrence (2026-06-08, horizon 2026-06-13); got "
        f"{cycle['generated_ride_ids']}")
    resp = api_client.list_rides(COORD, params={"standing_ride_id": series["id"]})
    rides, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, "no duplicates, nothing beyond the horizon"
    pickups = sorted(_parse(r["scheduled_pickup_at"]) for r in rides)
    assert pickups == [
        datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
        datetime(2026, 6, 8, 9, 0, tzinfo=timezone.utc),
    ]
    refreshed = validate_success(api_client.get_standing_ride(series["id"], COORD))
    assert refreshed["next_occurrence_date"] == "2026-06-01"


def test_overdue_ar_boundary_at_due_date(api):
    """PRD §3.4: "The **billing hold** sums, over the client's invoices in
    `ISSUED` or `PARTIALLY_PAID` whose `due_date` is strictly before the
    logical today — an invoice due today is not yet overdue — the unpaid
    remainder of each, and when that sum is greater than or equal to
    `billing_hold_limit_cents` (exactly equal triggers the hold) the booking is
    rejected with `ERR_BILLING_HOLD`."

    Design: Corner/calculations/overdue_ar_boundary_at_due_date
    """
    create_active_rate_card()
    client = create_client(billing_hold_limit_cents=1000)
    create_late_cancel_invoice(
        client["id"], "2026-05-04T12:00:00Z", "2026-05-04T16:00:00Z",
        "2026-05-01", "2026-05-08", issue=True)
    # due_date 2026-05-22; on the due date itself the invoice is NOT overdue.
    set_clock("2026-05-22T09:00:00Z")
    ride = get_success_data(api_client.create_ride(
        {"client_id": client["id"], "kind": "GROCERY",
         "scheduled_pickup_at": "2026-06-01T10:00:00Z",
         "estimated_duration_minutes": 60, "estimated_distance_miles": 10,
         "origin_zone": "north"},
        make_client_headers(client["id"])))
    assert ride["status"] == "SCHEDULED", "due today is not yet overdue"
    set_clock("2026-05-23T09:00:00Z")
    resp = api_client.create_ride(
        {"client_id": client["id"], "kind": "GROCERY",
         "scheduled_pickup_at": "2026-06-02T10:00:00Z",
         "estimated_duration_minutes": 60, "estimated_distance_miles": 10,
         "origin_zone": "north"},
        make_client_headers(client["id"]))
    # One day past due: overdue AR 1251 >= limit 1000 (inclusive boundary).
    validate_error(resp, ApiErrorId.ERR_BILLING_HOLD)


def test_rides_list_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    to return. If not provided, it defaults to 10, with a minimum of 1 and
    maximum of 100. The `offset` parameter specifies the number of items to
    skip and defaults to 0."
    PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/rides_list_pagination_envelope
    """
    client = create_client()
    create_active_rate_card()
    set_clock("2026-05-20T09:00:00Z")
    r1 = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-01T10:00:00Z")
    r2 = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-02T10:00:00Z")
    page1, meta1 = validate_paginated(
        api_client.list_rides(COORD, params={"client_id": client["id"], "limit": 1, "offset": 0}))
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True
    assert len(page1) == 1
    page2, meta2 = validate_paginated(
        api_client.list_rides(COORD, params={"client_id": client["id"], "limit": 1, "offset": 1}))
    assert meta2["has_more"] is False
    assert len(page2) == 1
    assert page1[0]["id"] != page2[0]["id"], "the two pages partition the set"
    assert {page1[0]["id"], page2[0]["id"]} == {r1["id"], r2["id"]}
