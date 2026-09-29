"""Transitions, terminal states, preconditions and cascade side effects."""

from test_helpers import (
    ADMIN,
    CLUB_ADMIN_PRIMARY_ID,
    assert_entitlement_counters,
    assert_membership_axes,
    assert_reservation_state,
    book_member_stay,
    check_in,
    completed_stay,
    create_member,
    create_open_park,
    create_park,
    create_president_tier,
    find_by_id,
    make_transfer_decision_payload,
    make_park_manager_headers,
    parse_instant,
    read_membership,
    read_park,
    read_reservation,
    reset_clock,
    schedule_window,
    sell_membership,
    sell_membership_to_new_member,
    set_clock,
    submit_transfer,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_transfer_approval_terminates_the_source_and_mints_a_successor(api):
    """One approval fires every declared side effect at once.

    PRD §3.8: "**Approval** moves the request to `APPROVED` and the source
    membership from `TRANSFER_PENDING` to the terminal `TERMINATED`, then mints a
    successor membership for `to_member_id`."

    Design: Corner/state_machines/transfer_request_approval_terminates_the_source_and_mints_a_successor_membership
    """
    reset_clock(api)
    tier = create_president_tier(api)
    gia = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Gia Halvorsen", "email": "gia@example.com"},
        upfront_paid_cents=1850000,
    )
    hal = create_member(api, full_name="Hal Ozturk", email="hal@example.com")
    source_before = read_membership(api, gia["membership_id"])

    request = submit_transfer(
        api, gia["headers"], gia["membership_id"], hal["id"], transfer_type="GIFT"
    )
    assert request["status"] == "SUBMITTED"
    assert request["from_member_id"] == gia["member_id"]
    # round_half_up(95000 * 0.50) with no resale surcharge on a gift.
    assert request["transfer_fee_cents"] == 47500
    assert_membership_axes(
        read_membership(api, gia["membership_id"]), "TRANSFER_PENDING", "CURRENT"
    )

    decided = validate_success(
        api.decide_transfer_request(request["id"], make_transfer_decision_payload("APPROVE"), ADMIN),
        200,
    )
    assert decided["status"] == "APPROVED"
    assert decided["decided_by_user_id"] == CLUB_ADMIN_PRIMARY_ID
    assert decided["decided_at"] is not None
    assert decided["successor_membership_id"] is not None

    source_after = read_membership(api, gia["membership_id"])
    assert source_after["membership_status"] == "TERMINATED"

    successor = read_membership(api, decided["successor_membership_id"])
    assert successor["member_id"] == hal["id"]
    assert successor["tier_id"] == tier["id"]
    assert successor["transferred_from_membership_id"] == gia["membership_id"]
    assert successor["transfer_count"] == 1
    assert_membership_axes(successor, "ACTIVE", "CURRENT")
    assert_entitlement_counters(successor, class_a=0, class_b=0, class_c=0, annual=0)
    assert parse_instant(successor["tenure_origin_at"]) == parse_instant(
        source_before["tenure_origin_at"]
    ), "a gift does not reset tenure"


def test_activating_a_completed_maintenance_window_is_rejected(api):
    """COMPLETED is terminal, so a re-activation cannot drag the park back offline.

    PRD §2.8: "Maintenance window state — `ERR_INVALID_MAINTENANCE_STATE` (HTTP
    409): a window must be `SCHEDULED` to be activated and `ACTIVE` to be
    completed."

    Design: Corner/state_machines/maintenance_window_activation_from_completed_is_rejected
    """
    reset_clock(api)
    park = create_open_park(
        api,
        name="Pinnacle Bay RV Resort",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )
    manager = make_park_manager_headers(park["id"])
    window = schedule_window(api, park["id"], "2026-09-11", "2026-09-15", work_type="ROUTINE")
    validate_success(api.activate_maintenance_window(window["id"], manager), 200)
    completed = validate_success(api.complete_maintenance_window(window["id"], manager), 200)
    assert completed["status"] == "COMPLETED"
    assert read_park(api, park["id"])["park_status"] == "OPEN"

    validate_error(
        api.activate_maintenance_window(window["id"], manager),
        "ERR_INVALID_MAINTENANCE_STATE",
        409,
    )

    rows, _meta = validate_paginated(api.list_park_maintenance_windows(park["id"], manager))
    still = find_by_id(rows, window["id"])
    assert still["status"] == "COMPLETED"
    assert still["cancelled_reservation_count"] == 0

    park_after = read_park(api, park["id"])
    assert park_after["park_status"] == "OPEN", "the refused activation took no park offline"
    assert park_after["forced_cancellation_count"] == 0


def test_checking_in_twice_is_rejected_and_keeps_the_first_stamp(api):
    """A replayed check-in is a 409, not a no-op that re-stamps the arrival instant.

    PRD §3.5: "Check-in stamps `checked_in_at` with the current logical instant
    and changes nothing else; no entitlement moves, because the provisional debit
    was taken at confirmation."

    Design: Corner/state_machines/reservation_check_in_twice_is_rejected_on_the_second_attempt
    """
    reset_clock(api)
    tier = create_president_tier(api)
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Imani Fowler", "email": "imani@example.com"},
        upfront_paid_cents=1850000,
    )
    park = create_open_park(
        api,
        name="Copper Springs RV Resort",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )
    reservation = book_member_stay(
        api, holder["headers"], park["id"], holder["membership_id"], "2026-08-20", "2026-08-23"
    )

    arrived = check_in(api, reservation["id"], holder["headers"], "2026-08-20T14:00:00Z")
    assert arrived["status"] == "CHECKED_IN"
    assert parse_instant(arrived["checked_in_at"]) == parse_instant("2026-08-20T14:00:00Z")

    set_clock(api, "2026-08-20T18:00:00Z")
    validate_error(
        api.check_in_reservation(reservation["id"], holder["headers"]),
        "ERR_INVALID_RESERVATION_STATE",
        409,
    )

    unchanged = read_reservation(api, reservation["id"])
    assert parse_instant(unchanged["checked_in_at"]) == parse_instant("2026-08-20T14:00:00Z"), (
        "the original arrival stamp survives the rejected replay"
    )
    assert_entitlement_counters(
        read_membership(api, holder["membership_id"]), class_b=3, annual=3
    )


def test_a_new_membership_opens_on_both_axes_with_a_zeroed_ledger(api):
    """Both state axes and every counter take their declared initial values.

    PRD §3.1: "Upon creation the contract opens on both of its state axes at once
    — `membership_status` is `ACTIVE` and `dues_status` is `CURRENT` — with
    `suspension_reason` null and `transferred_from_membership_id` null, marking it
    an original purchase rather than a successor."

    Design: Corner/state_machines/membership_initial_state_is_active_and_current_with_a_zeroed_ledger
    """
    reset_clock(api)
    tier = create_president_tier(api)
    member = create_member(api, full_name="Juno Kaster", email="juno@example.com")

    membership = sell_membership(api, member["id"], tier["id"], upfront_paid_cents=1850000)

    assert_membership_axes(membership, "ACTIVE", "CURRENT", suspension_reason=None)
    assert membership["transferred_from_membership_id"] is None
    assert membership["transfer_count"] == 0
    assert membership["tenure_years"] == 0
    assert_entitlement_counters(membership, class_a=0, class_b=0, class_c=0, annual=0)
    assert parse_instant(membership["purchased_at"]) == parse_instant("2026-08-01T00:00:00Z")
    assert parse_instant(membership["tenure_origin_at"]) == parse_instant(
        membership["purchased_at"]
    )
    assert membership["entitlement_year_start"] == "2026-08-01"
    # 2026-08-01 advanced by the 730-day resale hold lands on 2028-07-31.
    assert parse_instant(membership["resale_eligible_at"]) == parse_instant(
        "2028-07-31T00:00:00Z"
    )
    assert membership["dues_balance_cents"] == 59508
    assert membership["version"] == 1


def test_a_terminated_membership_accepts_no_further_transfer(api):
    """A terminal contract axis refuses a well-formed, version-fresh submission.

    PRD §2.8: "Membership contract state — `ERR_MEMBERSHIP_NOT_ACTIVE` (HTTP
    409), on member booking, extension and transfer submission: the acting
    membership's `membership_status` must be `ACTIVE`, so `SUSPENDED`,
    `TRANSFER_PENDING` and `TERMINATED` memberships can neither book, extend nor
    transfer."

    Design: Corner/state_machines/terminated_membership_cannot_open_another_transfer_request
    """
    reset_clock(api)
    tier = create_president_tier(api)
    kelo = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Kelo Adeniyi", "email": "kelo@example.com"},
        upfront_paid_cents=1850000,
    )
    lior = create_member(api, full_name="Lior Bassett", email="lior@example.com")
    mira = create_member(api, full_name="Mira Solano", email="mira@example.com")

    request = submit_transfer(api, kelo["headers"], kelo["membership_id"], lior["id"])
    validate_success(
        api.decide_transfer_request(request["id"], make_transfer_decision_payload("APPROVE"), ADMIN),
        200,
    )
    terminated = read_membership(api, kelo["membership_id"])
    assert terminated["membership_status"] == "TERMINATED"

    response = api.create_transfer_request(
        {
            "membership_id": kelo["membership_id"],
            "to_member_id": mira["id"],
            "transfer_type": "GIFT",
            "expected_membership_version": terminated["version"],
        },
        kelo["headers"],
    )
    validate_error(response, "ERR_MEMBERSHIP_NOT_ACTIVE", 409)

    _rows, meta = validate_paginated(
        api.list_transfer_requests(ADMIN, {"membership_id": kelo["membership_id"]})
    )
    assert meta["total_count"] == 1, "the refused submission created no second request"

    after = read_membership(api, kelo["membership_id"])
    assert after["membership_status"] == "TERMINATED"
    assert after["transfer_count"] == terminated["transfer_count"]


def test_a_season_opening_before_the_lead_window_is_rejected(api):
    """The transition carries a date precondition whose first day is inclusive.

    PRD §3.2: "A `ParkManager` (or a `ClubAdmin`) may do this only within the
    season-opening lead allowance of 30 days: the current logical date must be on
    or after `season_open_date` minus 30 days, and on or before
    `season_close_date`."

    Design: Corner/state_machines/season_opening_before_the_lead_window_is_rejected
    """
    reset_clock(api)
    park = create_park(
        api,
        name="Late Season Landing",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
        season_open_date="2026-10-01",
        season_close_date="2026-12-20",
    )
    manager = make_park_manager_headers(park["id"])

    validate_error(api.open_park_season(park["id"], manager), "ERR_INVALID_PARK_STATE", 409)
    refused = read_park(api, park["id"])
    assert refused["park_status"] == "SEASONAL_CLOSED"
    assert refused["version"] == park["version"], "a refused transition bumps no version"

    set_clock(api, "2026-09-01")
    opened = validate_success(api.open_park_season(park["id"], manager), 200)
    assert opened["park_status"] == "OPEN", "2026-09-01 is the inclusive first day of the window"


def test_season_closure_cancels_only_the_non_terminal_stay(api):
    """The closure evicts the future stay and never re-touches the completed one.

    PRD §3.2: "Otherwise, every reservation at that park in status `CONFIRMED`
    whose `arrival_date` is on or after the current logical date moves to
    `CANCELLED` with `cancellation_reason` set to `SEASON_CLOSURE`, and every
    reservation at that park in status `WAITLISTED` moves to `EXPIRED`."

    Design: Corner/state_machines/season_closure_cancels_only_non_terminal_reservations
    """
    reset_clock(api)
    tier = create_president_tier(api)
    holder = sell_membership_to_new_member(
        api,
        tier["id"],
        member_overrides={"full_name": "Otto Vance", "email": "otto@example.com"},
        upfront_paid_cents=1850000,
    )
    park = create_open_park(
        api,
        name="Harvest Moon RV Resort",
        park_class="CLASS_B",
        total_sites=40,
        member_allocation_pct=60,
    )
    past = completed_stay(
        api,
        holder["headers"],
        park["id"],
        holder["membership_id"],
        "2026-08-05",
        "2026-08-08",
    )
    future = book_member_stay(
        api, holder["headers"], park["id"], holder["membership_id"], "2026-11-10", "2026-11-13"
    )
    set_clock(api, "2026-08-20")
    assert_entitlement_counters(
        read_membership(api, holder["membership_id"]), class_b=6, annual=6
    )

    closed = validate_success(api.close_park_season(park["id"], ADMIN), 200)
    assert closed["park_status"] == "SEASONAL_CLOSED"

    evicted = read_reservation(api, future["id"])
    assert_reservation_state(
        evicted, "CANCELLED", pool_charged="NONE", entitlement_nights_charged=0
    )
    assert evicted["cancellation_reason"] == "SEASON_CLOSURE"

    untouched = read_reservation(api, past["id"])
    assert_reservation_state(untouched, "COMPLETED", entitlement_nights_charged=3)
    assert untouched["cancellation_reason"] is None, "terminal rows are never re-touched"

    assert_entitlement_counters(
        read_membership(api, holder["membership_id"]), class_b=3, annual=3
    )
    assert closed["forced_cancellation_count"] == 1
    assert closed["amenity_compliance_status"] == "COMPLIANT", (
        "one forced cancellation is below the probation threshold of two"
    )
