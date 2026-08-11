"""Cross-cutting: optimistic concurrency, the driver selector policy
(ranking, tie-break, exclusion, empty-pool fallback), and ops-cycle sweeps."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_booked_ride,
    create_client,
    create_standing_ride_payload,
    get_success_data,
    make_driver_headers,
    set_clock,
    setup_standard_dispatch_env,
    setup_two_driver_env,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)

COORD = TEST_USERS["coordinator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


def test_occ_standing_put_stale_version_412(api):
    """PRD §2.7: "`PUT /standing-rides/{id}` requires
    `expected_standing_ride_version` as a non-optional input carrying the
    caller's last observed `version` of the series. Because editing a template
    regenerates its future occurrences, an expectation that no longer equals
    the current version means another writer's edit has already advanced the
    template — and rebuilt the occurrence set — since the caller last read it.
    The edit is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.4: "the edit increments the series' `version`, deletes its
    generated rides still `SCHEDULED` with pickup dates after the logical
    today, and regenerates the window from the new parameters"

    Design: Corner/cross_cutting_layers/occ_standing_put_stale_version_412
    """
    client, _ = setup_standard_dispatch_env(with_driver=False, clock="2026-05-20T09:00:00Z")
    series = get_success_data(api_client.create_standing_ride(
        create_standing_ride_payload(client["id"]), COORD))
    stale_version = series["version"]
    updated = get_success_data(api_client.update_standing_ride(
        series["id"],
        {"pickup_time_of_day_minutes": 600,
         "expected_standing_ride_version": stale_version},
        COORD))
    assert updated["version"] == stale_version + 1
    assert updated["pickup_time_of_day_minutes"] == 600
    resp = api_client.update_standing_ride(
        series["id"],
        {"pickup_time_of_day_minutes": 660,
         "expected_standing_ride_version": stale_version},
        COORD)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    after = validate_success(api_client.get_standing_ride(series["id"], COORD))
    assert after["pickup_time_of_day_minutes"] == 600, "loser's edit not applied"
    assert after["version"] == stale_version + 1


def test_occ_client_patch_stale_version_412(api):
    """PRD §2.7: "`PATCH /clients/{id}` requires `expected_client_version` as a
    non-optional input carrying the caller's last observed `version` of the
    client. Any intervening write — including system-driven transitions such as
    the no-show auto-suspension — advances the client, and a stale expectation
    is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.7: "Rejection leaves the target resource unmodified; the client is
    expected to re-read and retry with the fresh version."

    Design: Corner/cross_cutting_layers/occ_client_patch_stale_version_412
    """
    client = create_client()
    stale_version = client["version"]
    updated = get_success_data(api_client.patch_client(
        client["id"], {"home_zone": "south", "expected_client_version": stale_version},
        COORD))
    assert updated["version"] == stale_version + 1
    assert updated["home_zone"] == "south"
    resp = api_client.patch_client(
        client["id"], {"home_zone": "east", "expected_client_version": stale_version},
        COORD)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    after = validate_success(api_client.get_client(client["id"], COORD))
    assert after["home_zone"] == "south"


def test_selector_prefers_zone_match(api):
    """PRD §3.5: "Eligible drivers are ranked deterministically: zone match
    first (driver `home_zone` equal to the ride's `origin_zone` outranks
    non-match), then `current_load_minutes` ascending, then the driver's
    `created_at` ascending as the final tie-break — ids are never used to break
    ties."

    Design: Corner/cross_cutting_layers/selector_prefers_zone_match
    """
    client, d1, d2 = setup_two_driver_env()
    ride = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-05T10:00:00Z")
    offer = get_success_data(api_client.dispatch_ride(ride["id"], COORD))
    assert offer["driver_id"] == d1["id"], (
        f"zone-north D1 outranks zone-south D2 for an origin-north ride; got "
        f"{offer['driver_id']}")


def test_selector_tie_breaks_by_created_at(api):
    """PRD §3.5: "then `current_load_minutes` ascending, then the driver's
    `created_at` ascending as the final tie-break — ids are never used to break
    ties."

    Design: Corner/cross_cutting_layers/selector_tie_breaks_by_created_at
    """
    client, d1, d2 = setup_two_driver_env(d2_zone="north", stagger_created_at=True)
    ride = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-05T10:00:00Z")
    offer = get_success_data(api_client.dispatch_ride(ride["id"], COORD))
    assert offer["driver_id"] == d1["id"], (
        f"equal zone and load: earlier created_at (09:00) beats 09:01; got "
        f"{offer['driver_id']}")


def test_selector_decline_excludes_driver_on_retry(api):
    """PRD §3.5: "Declining appends the driver to `excluded_driver_ids` and
    logs `DECLINED`, so re-offers after a decline or a timeout run the selector
    with the exclusion set applied."

    Design: Corner/cross_cutting_layers/selector_decline_excludes_driver_on_retry
    """
    client, d1, d2 = setup_two_driver_env()
    ride = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-05T10:00:00Z")
    offer1 = get_success_data(api_client.dispatch_ride(ride["id"], COORD))
    assert offer1["driver_id"] == d1["id"]
    get_success_data(api_client.respond_assignment(
        offer1["id"], {"decision": "DECLINE", "decline_reason": "too far"},
        make_driver_headers(d1["id"])))
    mid = validate_success(api_client.get_ride(ride["id"], COORD))
    assert d1["id"] in mid["excluded_driver_ids"]
    offer2 = get_success_data(api_client.dispatch_ride(ride["id"], COORD))
    assert offer2["driver_id"] == d2["id"], (
        f"D1 excluded after decline; the retry lands on D2; got {offer2['driver_id']}")
    after = validate_success(api_client.get_ride(ride["id"], COORD))
    assert after["dispatch_round"] == 2


def test_selector_empty_pool_returns_null_and_stays_dispatching(api):
    """PRD §3.5: "An empty pool is not an error: the dispatch call returns
    success with `data` null, the ride stays `DISPATCHING`, and no assignment
    is created."
    PRD §4: "The dispatch endpoint also returns `200 OK` with `data` null when
    the selector pool is empty"

    Design: Corner/cross_cutting_layers/selector_empty_pool_returns_null_and_stays_dispatching
    """
    client, _ = setup_standard_dispatch_env(with_driver=False)
    ride = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-05T10:00:00Z")
    resp = api_client.dispatch_ride(ride["id"], COORD)
    data = validate_success(resp, expected_status=200)
    assert data is None or data == {}, (
        f"empty pool returns 200 with data null, got {data!r}")
    after = validate_success(api_client.get_ride(ride["id"], COORD))
    assert after["status"] == "DISPATCHING"
    assert after["dispatch_round"] == 1
    resp = api_client.list_assignments(COORD, params={"ride_id": ride["id"]})
    _, meta = validate_paginated(resp)
    assert meta["total_count"] == 0, "no assignment row created on empty pool"


def test_offer_timeout_expired_by_run_cycle(api):
    """PRD §3.5: "Offers also die of old age: when the ops cycle finds
    `offer_expires_at` at or before the logical now, the assignment moves to
    `EXPIRED`, the driver joins the exclusion set, and the timeout is logged."
    PRD §3.10: "Third, offer timeouts: any `OFFERED` assignment whose
    `offer_expires_at` has been reached moves to `EXPIRED`, its driver joining
    the ride's `excluded_driver_ids`."

    Design: Corner/cross_cutting_layers/offer_timeout_expired_by_run_cycle
    """
    client, driver = setup_standard_dispatch_env()
    ride = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-05T10:00:00Z")
    offer = get_success_data(api_client.dispatch_ride(ride["id"], COORD))
    set_clock("2026-06-01T09:31:00Z")  # offer_expires_at 09:30 has passed
    cycle = get_success_data(api_client.run_cycle(ADMIN))
    assert offer["id"] in cycle["expired_assignment_ids"]
    asg = validate_success(api_client.get_assignment(offer["id"], COORD))
    assert asg["status"] == "EXPIRED"
    resp = api_client.dispatch_ride(ride["id"], COORD)
    data = validate_success(resp, expected_status=200)
    assert data is None or data == {}, (
        "the only driver is now excluded for this ride, so the pool is empty")
    after = validate_success(api_client.get_ride(ride["id"], COORD))
    assert after["status"] == "DISPATCHING"
    assert after["dispatch_round"] == 2
    assert driver["id"] in after["excluded_driver_ids"]


def test_invoice_marked_past_due_by_run_cycle(api):
    """PRD §3.8: "the ops cycle marks an invoice's `past_due` flag true once
    the logical date passes `due_date` while the invoice is `ISSUED` or
    `PARTIALLY_PAID`; the flag is a latch and never auto-clears."
    PRD §3.10: "Fourth, receivables aging: invoices past their `due_date` in
    `ISSUED` or `PARTIALLY_PAID` latch their `past_due` flag."

    Design: Corner/cross_cutting_layers/invoice_marked_past_due_by_run_cycle
    """
    from test_helpers import create_active_rate_card, create_late_cancel_invoice
    create_active_rate_card()
    client = create_client()
    invoice, _ = create_late_cancel_invoice(
        client["id"], "2026-05-04T12:00:00Z", "2026-05-04T16:00:00Z",
        "2026-05-01", "2026-05-08", issue=True)
    # due_date is 2026-05-22; the cycle on the due date leaves past_due false.
    set_clock("2026-05-22T09:00:00Z")
    get_success_data(api_client.run_cycle(ADMIN))
    on_due = validate_success(api_client.get_invoice(invoice["id"], BILLING))
    assert on_due["past_due"] is False, "due today is not past due"
    set_clock("2026-05-23T09:00:00Z")
    cycle = get_success_data(api_client.run_cycle(ADMIN))
    assert invoice["id"] in cycle["past_due_invoice_ids"]
    after = validate_success(api_client.get_invoice(invoice["id"], BILLING))
    assert after["past_due"] is True


def test_no_show_strike_three_auto_suspends_client(api):
    """PRD §3.6: "The third strike is automatic and severe: the moment a
    client's `no_show_count` reaches exactly three, the client is suspended by
    the system and the full suspension cascade of §3.1 fires — future
    `SCHEDULED` and `DISPATCHING` rides cancelled fee-free with `cancel_reason`
    of `CLIENT_SUSPENDED`, their live offers expired. Counts below the limit
    carry no status effect."

    Design: Corner/cross_cutting_layers/no_show_strike_three_auto_suspends_client
    """
    from test_helpers import dispatch_and_accept, exec_event
    client, driver = setup_standard_dispatch_env(clock="2026-05-20T09:00:00Z")
    pickups = ["2026-06-01T08:00:00Z", "2026-06-01T12:00:00Z", "2026-06-01T16:00:00Z"]
    ride_ids = [
        create_booked_ride(client["id"], scheduled_pickup_at=p)["id"] for p in pickups
    ]
    r4 = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-02T08:00:00Z")

    def no_show(ride_id, arrived_clock, no_show_clock):
        dispatch_and_accept(ride_id, driver["id"])
        # EN_ROUTE 20 minutes before ARRIVED (clock only moves forward).
        hh, mm = int(arrived_clock[11:13]), int(arrived_clock[14:16])
        en_route_min = hh * 60 + mm - 20
        en_route_clock = f"{arrived_clock[:10]}T{en_route_min // 60:02d}:{en_route_min % 60:02d}:00Z"
        exec_event(ride_id, driver["id"], "EN_ROUTE", at_clock=en_route_clock)
        exec_event(ride_id, driver["id"], "ARRIVED", at_clock=arrived_clock)
        return exec_event(ride_id, driver["id"], "NO_SHOW", at_clock=no_show_clock)

    first = no_show(ride_ids[0], "2026-06-01T07:55:00Z", "2026-06-01T08:11:00Z")
    assert first["no_show_fee_cents"] == 2501
    second = no_show(ride_ids[1], "2026-06-01T11:55:00Z", "2026-06-01T12:11:00Z")
    assert second["no_show_fee_cents"] == 2501
    mid = validate_success(api_client.get_client(client["id"], COORD))
    assert mid["status"] == "ACTIVE", "two strikes carry no status effect"
    assert mid["no_show_count"] == 2
    third = no_show(ride_ids[2], "2026-06-01T15:55:00Z", "2026-06-01T16:11:00Z")
    assert third["no_show_fee_cents"] == 2501
    end = validate_success(api_client.get_client(client["id"], COORD))
    assert end["status"] == "SUSPENDED", "the third strike auto-suspends"
    assert end["no_show_count"] == 3
    r4_after = validate_success(api_client.get_ride(r4["id"], COORD))
    assert r4_after["status"] == "CANCELLED"
    assert r4_after["cancel_reason"] == "CLIENT_SUSPENDED"
    assert r4_after["cancellation_fee_cents"] == 0


def test_immediate_read_after_write_consistency(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.1: "A `Coordinator` registers a senior client with their legal
    `full_name`, their `mobility_aid` (one of `NONE`, `WALKER`,
    `FOLDING_WHEELCHAIR`, or `POWER_WHEELCHAIR`), their `assist_level_default`
    escort tier (`DOOR_TO_DOOR` or `DOOR_THROUGH_DOOR`), a `home_zone` label
    used later in driver ranking, and a free-text `address`."

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    from test_helpers import create_client_payload
    created = get_success_data(api_client.create_client(
        create_client_payload(mobility_aid="WALKER",
                              assist_level_default="DOOR_THROUGH_DOOR",
                              billing_hold_limit_cents=12345),
        COORD))
    fetched = validate_success(api_client.get_client(created["id"], COORD))
    for field in ("full_name", "mobility_aid", "assist_level_default",
                  "home_zone", "address", "billing_hold_limit_cents", "status"):
        assert fetched[field] == created[field], (
            f"read-after-write mismatch on {field}: {fetched[field]!r} != "
            f"{created[field]!r}")
    assert fetched["full_name"] == "Ada L"
    assert fetched["mobility_aid"] == "WALKER"
    assert fetched["billing_hold_limit_cents"] == 12345
    assert fetched["status"] == "ACTIVE"
