"""
The three authorisation layers: headers, role, and ownership.

PRD 2.10 evaluates them as tiers 1, 2, 3 and 7, so every test here pairs a refusal
with a positive control on a neighbouring endpoint - that is the only way to show
which check answered rather than merely that something did.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ERR_MISSING_AUTH_HEADERS,
    ERR_NOT_BOOKING_OWNER,
    ERR_ROLE_NOT_PERMITTED,
    ERR_UNKNOWN_ROLE,
    GROUP_SALES_AGENT,
    NO_AUTH_HEADERS,
    PORT_OPS_COORDINATOR,
    RESERVATION_AGENT,
    REVENUE_MANAGER,
    assert_capacity_identity,
    assert_version_is,
    factories as f,
    fixtures as fx,
    headers_with_role,
    make_guest_headers,
)

FLAT_FARE_50K = {
    "window_open_days_to_sail": 730,
    "window_close_days_to_sail": 0,
    "base_lower_berth_fare_cents": 50000,
    "third_berth_fare_cents": 20000,
    "fourth_berth_fare_cents": 15000,
}


def test_no_role_is_a_superset_of_another_one(api):
    """Seven exclusive operations, seven 403s, and two shared reads that still work.

    PRD 2.1: "A `RevenueManager` owns pricing, allotments, promotions, oversell
    strategy, upgrade-bid adjudication, cancellation settlement, and the per-sailing
    operations sweep. A `ReservationAgent` sells and services individual bookings: guest
    profiles, booking creation, confirmation, payments, guarantee assignment. A
    `GroupSalesAgent` owns travel-agency group blocks: tentative holds, the four-eyes
    definite signature, review-date releases, and review extensions. A
    `PortOpsCoordinator` owns itinerary disruption: drafting and publishing port
    cancellations, substitutions, and shortened itineraries together with their
    compensation policy. A `Guest` is the traveller acting on their own booking. When the
    acting role is not listed for the endpoint being called (see the table in §4), the
    request is rejected with `ERR_ROLE_NOT_PERMITTED` and HTTP 403." PRD 2.10 puts that
    check at tier 3, above every body and state check.

    Design: Corner/rbac/other_roles_cannot_call_a_roles_exclusive_operations
    """
    world = fx.simple_world(
        api,
        voyage_code="RBC-2701",
        fare_overrides=dict(FLAT_FARE_50K, base_lower_berth_fare_cents=189995),
    )
    guest = fx.make_guest(api, full_name="Ada Ames", email="ada@example.com")
    opened_version = world.sailing["version"]

    # Selling agents do not create voyages, even with a flawless body.
    validate_error(
        api.create_sailing(
            f.sailing_payload(
                voyage_code="RBC-2799",
                embark_date="2027-04-01T17:00:00Z",
                nights=5,
                total_lower_berths=100,
            ),
            RESERVATION_AGENT,
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    _, phantom_meta = validate_paginated(
        api.list_sailings(REVENUE_MANAGER, params={"voyage_code": "RBC-2799"})
    )
    assert phantom_meta["total_count"] == 0

    # Group agents do not sell individual cabins.
    validate_error(
        api.create_booking(
            f.booking_payload(
                world.sailing["id"],
                world.category["id"],
                guest["id"],
                occupancy_adults=2,
            ),
            GROUP_SALES_AGENT,
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    assert fx.read_guest(api, guest["id"])["bookings_count"] == 0

    # And reservation agents do not open group holds.
    validate_error(
        api.create_group_block(
            f.group_block_payload(world.sailing["id"], world.category["id"], cabins_held=2),
            RESERVATION_AGENT,
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    _, block_meta = validate_paginated(
        api.list_group_blocks(
            REVENUE_MANAGER, params={"sailing_id": world.sailing["id"]}
        )
    )
    assert block_meta["total_count"] == 0

    # The sweep belongs to revenue management, not to port operations.
    validate_error(
        api.ops_run(world.sailing["id"], PORT_OPS_COORDINATOR),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    # A 403 performs no write, so the sweep's version bump never happened.
    assert_version_is(fx.read_sailing(api, world.sailing["id"]), opened_version)

    # Itinerary disruption belongs to port operations, not to the selling desk.
    validate_error(
        api.create_itinerary_change(
            f.itinerary_change_payload(world.sailing["id"]), RESERVATION_AGENT
        ),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    _, change_meta = validate_paginated(
        api.list_itinerary_changes(
            REVENUE_MANAGER, params={"sailing_id": world.sailing["id"]}
        )
    )
    assert change_meta["total_count"] == 0

    guest_headers = make_guest_headers(guest["id"])
    # The sailing list is not a guest-facing endpoint.
    validate_error(
        api.list_sailings(guest_headers, params={"ship_code": "AURORA"}),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    # The single-sailing read is, so the same credentials succeed one endpoint over.
    seen = validate_success(api.get_sailing(world.sailing["id"], guest_headers))
    assert seen["id"] == world.sailing["id"]
    assert seen["voyage_code"] == "RBC-2701"

    # The same asymmetry on the guest resource.
    validate_error(
        api.list_guests(GROUP_SALES_AGENT, params={"email": "ada@example.com"}),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )
    one_guest = validate_success(api.get_guest(guest["id"], GROUP_SALES_AGENT))
    assert one_guest["id"] == guest["id"]
    assert one_guest["email"] == "ada@example.com"


def test_one_guest_cannot_reach_into_another_guests_booking(api):
    """Peers share a role, so only the id comparison can separate them.

    PRD 2.1: "`Guest` is the one entity-backed role: when `X-User-Role` is `Guest`,
    `X-User-ID` is the `id` of the acting `Guest` row, and ownership checks on any
    resource that references a `Guest` compare the resource's foreign-key field to
    `X-User-ID` ... Any mismatch is rejected with `ERR_NOT_BOOKING_OWNER` (HTTP 403)."
    PRD 2.10 tier 7 lists the guarded calls: "reading one booking, cancelling a booking,
    submitting an upgrade bid on a booking, re-bidding after a counter, reading one
    upgrade bid, and reading a booking's payment ledger." Tier 3 still runs first, so an
    endpoint that excludes the `Guest` role answers `ERR_ROLE_NOT_PERMITTED` before
    ownership is ever considered.

    Design: Corner/rbac/a_guest_cannot_touch_another_guests_booking
    """
    fx.set_clock(api)
    ocean_view = fx.make_category(api, f.ocean_view_category_payload())
    inside = fx.make_guarantee_category(api, upgrade_to_category_id=ocean_view["id"])
    world = fx.simple_world(
        api,
        voyage_code="OWN-2701",
        nights=4,
        total_lower_berths=40,
        category=inside,
        physical_cabins=10,
        oversell_allowance=0,
        fare_overrides=FLAT_FARE_50K,
        open_now=False,
    )
    fx.add_allotment_and_fare(
        api,
        world,
        ocean_view,
        physical_cabins=10,
        oversell_allowance=0,
        fare_overrides=dict(
            FLAT_FARE_50K,
            base_lower_berth_fare_cents=90000,
            third_berth_fare_cents=30000,
            fourth_berth_fare_cents=25000,
        ),
    )
    fx.open_sailing(api, world.sailing["id"])

    ada = fx.make_guest(api, full_name="Ada Ames", email="ada@example.com")
    bo = fx.make_guest(api, full_name="Bo Chen", email="bo@example.com")
    ada_booking = fx.make_booking(
        api, world.sailing["id"], inside["id"], ada["id"], occupancy_adults=2
    )
    bo_booking = fx.make_booking(
        api, world.sailing["id"], inside["id"], bo["id"], occupancy_adults=2
    )
    fx.pay(api, ada_booking["id"], "DEPOSIT", 50000)
    ada_headers = make_guest_headers(ada["id"])

    validate_error(
        api.get_booking(bo_booking["id"], ada_headers),
        ERR_NOT_BOOKING_OWNER,
        403,
    )
    validate_error(
        api.list_payment_events(bo_booking["id"], ada_headers),
        ERR_NOT_BOOKING_OWNER,
        403,
    )
    validate_error(
        api.cancel_booking(
            bo_booking["id"], {"reason": "NOT_MY_BOOKING"}, ada_headers
        ),
        ERR_NOT_BOOKING_OWNER,
        403,
    )
    # Ownership is checked long before the bid window or the floor.
    validate_error(
        api.submit_upgrade_bid(
            bo_booking["id"],
            f.upgrade_bid_payload(ocean_view["id"], 40000),
            ada_headers,
        ),
        ERR_NOT_BOOKING_OWNER,
        403,
    )
    # The booking list excludes Guest entirely, so tier 3 answers instead of tier 7.
    validate_error(
        api.list_bookings(ada_headers, params={"sailing_id": world.sailing["id"]}),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    untouched = fx.read_booking(api, bo_booking["id"])
    assert untouched["booking_status"] == "OPTION"
    assert untouched["cancelled_at"] is None
    assert untouched["cancel_reason"] is None
    assert_version_is(untouched, bo_booking["version"])
    _, bid_meta = validate_paginated(
        api.list_upgrade_bids(REVENUE_MANAGER, params={"booking_id": bo_booking["id"]})
    )
    # The refused bid was never stored.
    assert bid_meta["total_count"] == 0

    own = validate_success(api.get_booking(ada_booking["id"], ada_headers))
    assert own["guest_id"] == ada["id"]
    assert own["net_ticket_cents"] == 100000
    assert own["amount_paid_cents"] == 50000

    ledger, ledger_meta = validate_paginated(
        api.list_payment_events(ada_booking["id"], ada_headers)
    )
    assert ledger_meta["total_count"] == 1
    assert ledger[0]["kind"] == "DEPOSIT"
    assert ledger[0]["amount_cents"] == 50000

    inventory = fx.read_inventory(api, world.inventory["id"])
    # No peer-crossing attempt moved a cabin.
    assert inventory["booked_cabins"] == 2
    assert inventory["available_cabins"] == 8
    assert_capacity_identity(inventory)


def test_authentication_outranks_the_path_the_body_and_the_role_list(api):
    """Two 401s that beat a 404 and a 400, and an unknown role that never reaches §4.

    PRD 2.1: "Every request to the API - including the test-driving clock endpoint - must
    carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`,
    declaring the capacity in which that principal acts. If either header is absent or
    empty, the request is rejected with `ERR_MISSING_AUTH_HEADERS`. If `X-User-Role`
    carries a value outside the five recognized roles, the request is rejected with
    `ERR_UNKNOWN_ROLE`. Both of those failures are authentication failures and carry HTTP
    401." PRD 2.10 orders them first and second, above request shape (tier 4), path
    existence (tier 5), and role authorization (tier 3).

    Design: Corner/rbac/missing_or_unknown_auth_headers_are_rejected_before_anything_else
    """
    fx.set_clock(api)
    fx.make_guarantee_category(api)
    sailing = fx.make_sailing(api, voyage_code="AUT-2701")

    validate_error(
        api.get_sailing(sailing["id"], NO_AUTH_HEADERS),
        ERR_MISSING_AUTH_HEADERS,
        401,
    )
    # An unknown path id cannot turn the 401 into a 404.
    validate_error(
        api.get_sailing("00000000-0000-4000-8000-0000000000aa", NO_AUTH_HEADERS),
        ERR_MISSING_AUTH_HEADERS,
        401,
    )
    # An empty body cannot turn it into a 400 either.
    validate_error(
        api.create_sailing({}, NO_AUTH_HEADERS),
        ERR_MISSING_AUTH_HEADERS,
        401,
    )

    impostor = headers_with_role("FleetAdmiral")
    # A role outside the five is an authentication failure, not an authorisation one.
    validate_error(
        api.create_sailing(
            f.sailing_payload(
                voyage_code="AUT-2799",
                embark_date="2027-05-01T17:00:00Z",
                nights=5,
                total_lower_berths=100,
            ),
            impostor,
        ),
        ERR_UNKNOWN_ROLE,
        401,
    )
    validate_error(
        api.open_for_sale(sailing["id"], impostor),
        ERR_UNKNOWN_ROLE,
        401,
    )
    unmoved = fx.read_sailing(api, sailing["id"])
    assert unmoved["status"] == "PLANNED"
    assert_version_is(unmoved, sailing["version"])

    all_sailings, meta = validate_paginated(api.list_sailings(REVENUE_MANAGER))
    # None of the five refusals wrote anything.
    assert meta["total_count"] == 1
    assert all_sailings[0]["voyage_code"] == "AUT-2701"

    # The endpoint itself was reachable all along, given well-formed credentials.
    read = validate_success(api.get_sailing(sailing["id"], PORT_OPS_COORDINATOR))
    assert read["id"] == sailing["id"]
    assert read["status"] == "PLANNED"
