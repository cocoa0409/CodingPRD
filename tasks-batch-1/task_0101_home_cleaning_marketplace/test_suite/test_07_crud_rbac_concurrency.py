"""CRUD, RBAC, OCC, soft-delete, consistency, and field-validation corner cases.
All instances here come from Queue B (the corner-design index).
"""
from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    make_customer_headers,
    setup_booking_world, create_one_time_booking,
    create_customer, create_address, create_active_plan, create_active_cleaner,
    create_check_failed_cleaner, create_check_passed_cleaner,
    setup_series_with_one_occurrence,
    NON_EXISTENT_UUID,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ===========================================================================
# Queue B — Corner: entities
# ===========================================================================
def test_create_customer_returns_201_with_zeroed_ledger_fields(api):
    """PRD §3.2: "On creation the platform initializes their `wallet_credit_cents`
    to 0 and their `lifetime_booking_count` to 0."
    PRD §2.4: "a `version` integer that begins at its initial value and increments
    by one on every mutation"

    Design: Corner/entities/create_customer_returns_201_with_zeroed_ledger_fields
    """
    data = validate_success(api.create_customer({"email": "new1@x.com", "full_name": "New Cust"}, ANON),
                            expected_status=201)
    assert data["wallet_credit_cents"] == 0, f"Expected wallet 0, got {data['wallet_credit_cents']}"
    assert data["lifetime_booking_count"] == 0, \
        f"Expected lifetime_booking_count 0, got {data['lifetime_booking_count']}"
    assert data["version"] == 1, f"Expected version 1, got {data['version']}"


def test_get_customer_not_found_returns_404(api):
    """PRD §2.5: "The first identifier that does not resolve to an existing
    resource causes the request to fail immediately with `ERR_NOT_FOUND`"

    Design: Corner/entities/get_customer_not_found_returns_404
    """
    validate_error(api.get_customer(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_NOT_FOUND.value)


def test_create_address_missing_home_size_returns_invalid_request(api):
    """PRD §3.2: "a `home_size` band drawn from `STUDIO`, `ONE_BR`, `TWO_BR`,
    `THREE_BR`, or `FOUR_PLUS_BR`."
    PRD §5 / §2.6: a malformed or missing body field yields `ERR_INVALID_REQUEST`.

    Omitting the required home_size on POST /addresses -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_address_missing_home_size_returns_invalid_request
    """
    cust = create_customer()
    cust_hdr = make_customer_headers(cust["id"])
    validate_error(
        api.create_address(
            {"customer_id": cust["id"], "line1": "1 A St", "postal_code": "94110"}, cust_hdr
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )


def test_create_address_invalid_home_size_enum_returns_invalid_request(api):
    """PRD §3.2: "a `home_size` band drawn from `STUDIO`, `ONE_BR`, `TWO_BR`,
    `THREE_BR`, or `FOUR_PLUS_BR`."

    A home_size outside the enum set -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_address_invalid_home_size_enum_returns_invalid_request
    """
    cust = create_customer()
    cust_hdr = make_customer_headers(cust["id"])
    validate_error(
        api.create_address(
            {"customer_id": cust["id"], "line1": "1 A St", "postal_code": "94110", "home_size": "MANSION"},
            cust_hdr,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )


def test_booking_home_size_snapshot_from_address(api):
    """PRD §3.3: "At creation the booking snapshots its `home_size` from the
    address so that later edits to the address never retro-change this visit's
    price"

    A booking against a TWO_BR address snapshots home_size TWO_BR and prices the
    TWO_BR base 11000 (no add-ons, customer supplies, count 0).

    Design: Corner/entities/booking_home_size_snapshot_ignores_later_address_input
    """
    world = setup_booking_world(home_size="TWO_BR", loyalty_count=0)
    booking = create_one_time_booking(world, scheduled_start="2026-06-10T09:00:00Z")
    assert booking["home_size"] == "TWO_BR", f"Expected snapshot TWO_BR, got {booking['home_size']}"
    assert booking["quoted_price_cents"] == 11000, \
        f"Expected 11000 (TWO_BR base), got {booking['quoted_price_cents']}"


# ===========================================================================
# Queue B — Corner: validations (addon not allowed on series)
# ===========================================================================
def test_move_out_on_series_returns_addon_not_allowed(api):
    """PRD §3.4: "The move-out add-on may not appear on a recurring series —
    supplying `MOVE_OUT` in a series' `add_ons` is rejected with
    `ERR_ADDON_NOT_ALLOWED`"

    Design: Corner/validations/move_out_on_series_returns_addon_not_allowed
    """
    world = setup_booking_world(home_size="TWO_BR", loyalty_count=0)
    cust = world["customer"]
    cust_hdr = make_customer_headers(cust["id"])
    validate_error(
        api.create_booking_series({
            "customer_id": cust["id"], "address_id": world["address"]["id"],
            "pricing_plan_id": world["plan"]["id"], "cadence": "BIWEEKLY",
            "first_occurrence_date": "2026-06-20T09:00:00Z", "add_ons": ["MOVE_OUT"],
        }, cust_hdr),
        ApiErrorId.ERR_ADDON_NOT_ALLOWED.value,
    )


# ===========================================================================
# Queue B — Corner: errors (terminal CHECK_FAILED cannot be activated)
# ===========================================================================
def test_activate_terminal_check_failed_cleaner_returns_invalid_state(api):
    """PRD §3.1: "`CHECK_FAILED` is terminal: a cleaner who has failed vetting can
    never be activated and is permanently barred from work."
    PRD §3.1: "Any of these transitions attempted from the wrong state yields
    `ERR_INVALID_STATE`."

    Activating a terminal CHECK_FAILED cleaner -> ERR_INVALID_STATE.

    Design: Corner/errors/activate_terminal_check_failed_cleaner_returns_invalid_state
    """
    bad = create_check_failed_cleaner()
    assert bad["status"] == "CHECK_FAILED"
    validate_error(api.activate_cleaner(bad["id"], ADMIN), ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Queue B — Corner: endpoints (paginated list envelope)
# ===========================================================================
def test_list_bookings_paginated_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object of the envelope, where `total_count`
    reflects the full size of the filtered collection and `has_more` indicates
    whether additional items remain beyond the current page."

    GET /bookings?customer_id for a customer with one booking returns an array
    envelope with total_count 1 and has_more false.

    Design: Corner/endpoints/list_bookings_paginated_envelope
    """
    world = setup_booking_world(home_size="STUDIO", loyalty_count=0)
    cust = world["customer"]
    cust_hdr = make_customer_headers(cust["id"])
    create_one_time_booking(world, scheduled_start="2026-06-10T09:00:00Z")
    data, meta = validate_paginated(api.list_bookings(cust_hdr, params={"customer_id": cust["id"]}))
    assert meta["total_count"] == 1, f"Expected total_count 1, got {meta['total_count']}"
    assert meta["has_more"] is False, f"Expected has_more False, got {meta['has_more']}"


# ===========================================================================
# Queue B — Corner: rbac
# ===========================================================================
def test_customer_cannot_activate_cleaner(api):
    """PRD §2.1: "When the headers are well formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."
    PRD §4: "POST `/cleaning/cleaners/{id}/activate` ... PlatformAdmin"

    A Customer calling the PlatformAdmin-exclusive activate endpoint ->
    ERR_UNAUTHORIZED.

    Design: Corner/rbac/customer_cannot_activate_cleaner
    """
    cleaner = create_check_passed_cleaner()
    cust = create_customer()
    validate_error(
        api.activate_cleaner(cleaner["id"], make_customer_headers(cust["id"])),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )


def test_customer_cannot_cancel_other_customers_booking(api):
    """PRD §2.1: "Ownership checks on any resource that references a customer
    compare that resource's `customer_id` foreign key to `X-User-ID`; a customer
    acting on a booking, address, series, preferred-pro association, tip, or
    ledger entry that they do not own is rejected with `ERR_FORBIDDEN_OWNERSHIP`."

    Customer B cancelling Customer A's booking -> ERR_FORBIDDEN_OWNERSHIP.

    Design: Corner/rbac/customer_cannot_cancel_other_customers_booking
    """
    world = setup_booking_world(home_size="STUDIO", loyalty_count=0)
    cust_a = world["customer"]
    booking = create_one_time_booking(world, scheduled_start="2026-06-20T09:00:00Z")
    cust_b = create_customer()
    validate_error(
        api.cancel_booking(booking["id"], make_customer_headers(cust_b["id"])),
        ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value,
    )


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Requests that omit either header, or that supply a malformed
    value, are rejected with `ERR_UNAUTHENTICATED`."

    A protected POST /addresses with no auth headers -> ERR_UNAUTHENTICATED.

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    cust = create_customer()
    validate_error(
        api.create_address(
            {"customer_id": cust["id"], "line1": "1 A St", "postal_code": "94110", "home_size": "STUDIO"},
            {},  # no X-User-ID / X-User-Role headers
        ),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )


# ===========================================================================
# Queue B — Corner: cross_cutting_complexity_layers (OCC, soft-delete)
# ===========================================================================
def test_stale_series_version_on_generate_rejected(api):
    """PRD §2.7: "Generating the next occurrence of a recurring series requires
    the request to carry `expected_series_version`, which must equal the target
    series' current `version`. ... if a client's `expected_series_version` no
    longer matches because the series has since advanced, the generation is
    rejected with `ERR_STALE_VERSION` and HTTP status 412"

    A second generate carrying the pre-generate version (already bumped by the
    first) is rejected with ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_series_version_on_generate
    """
    from test_helpers import setup_series, set_clock
    world = setup_series(cadence="WEEKLY", first_occurrence_date="2026-06-20T09:00:00Z")
    series = world["series"]
    stale_version = series["version"]
    # PRD §3.4: generation is permitted only when next_occurrence_date is at or
    # before the current clock. Advance to the first occurrence instant so the
    # first generate is due.
    set_clock("2026-06-20T09:00:00Z")
    get_success_data(api.generate_occurrence(series["id"], {"expected_series_version": stale_version}, ADMIN))
    # PRD §2.7: the first generate advanced next_occurrence_date by the WEEKLY
    # cadence (7 days, to 2026-06-27T09:00:00Z) AND bumped the series version.
    # Advance the clock to that new occurrence instant so the second generate's
    # due-date precondition is satisfied and the ONLY failing precondition is the
    # stale expected_series_version, isolating ERR_STALE_VERSION deterministically.
    set_clock("2026-06-27T09:00:00Z")
    validate_error(
        api.generate_occurrence(series["id"], {"expected_series_version": stale_version}, ADMIN),
        ApiErrorId.ERR_STALE_VERSION.value,
    )


def test_stale_plan_version_on_activate_rejected(api):
    """PRD §2.7: "Activating a pricing plan requires the request to carry
    `expected_plan_version`, which must equal that plan's current `version`.
    Because activation deactivates the previously active plan and bumps the
    activating plan's `version`, a second activation that still carries the
    previously observed version is acting on a stale view and is rejected with
    `ERR_STALE_VERSION` and HTTP status 412"

    Re-activating a plan with its pre-activation version -> ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/activate_second_plan_with_stale_version_rejected
    """
    plan = get_success_data(api.create_pricing_plan({
        "name": "P", "base_price_cents": {"STUDIO": 6000, "ONE_BR": 8000, "TWO_BR": 11000,
                                           "THREE_BR": 14000, "FOUR_PLUS_BR": 18000},
        "deep_clean_surcharge_pct": 0.50, "move_out_surcharge_pct": 0.75, "supplies_fee_cents": 1500,
    }, ADMIN))
    stale_version = plan["version"]
    get_success_data(api.activate_pricing_plan(plan["id"], {"expected_plan_version": stale_version}, ADMIN))
    validate_error(
        api.activate_pricing_plan(plan["id"], {"expected_plan_version": stale_version}, ADMIN),
        ApiErrorId.ERR_STALE_VERSION.value,
    )


def test_archived_address_excluded_from_default_list(api):
    """PRD §3.2: "archived addresses are hidden from default address listings
    (unless a list request opts in with `include_archived`)"

    After archiving, GET /addresses?customer_id omits the archived address by
    default (total_count 0) but includes it with include_archived=true
    (total_count 1).

    Design: Corner/cross_cutting_complexity_layers/archived_address_excluded_from_default_list
    """
    cust = create_customer()
    cust_hdr = make_customer_headers(cust["id"])
    addr = create_address(cust["id"], postal_code="94110", home_size="STUDIO")
    get_success_data(api.archive_address(addr["id"], cust_hdr))
    _, meta_default = validate_paginated(api.list_addresses(cust_hdr, params={"customer_id": cust["id"]}))
    assert meta_default["total_count"] == 0, \
        f"Expected archived address excluded by default (total 0), got {meta_default['total_count']}"
    _, meta_incl = validate_paginated(
        api.list_addresses(cust_hdr, params={"customer_id": cust["id"], "include_archived": "true"})
    )
    assert meta_incl["total_count"] == 1, \
        f"Expected archived address included with include_archived (total 1), got {meta_incl['total_count']}"


# ===========================================================================
# Queue B — Corner: consistency_model
# ===========================================================================
def test_charge_ledger_visible_in_same_request_flow(api):
    """PRD §1 (Introduction): "every balance-moving operation settles atomically
    inside the request that triggers it — there are no deferred or background
    reconciliations."
    PRD §3.3: "a `LedgerEntry` of kind `CHARGE` is written for the booking"

    A CHARGE LedgerEntry for the booking is queryable immediately after creating
    the booking (exactly one, total_count 1).

    Design: Corner/consistency_model/charge_ledger_visible_in_same_create_response
    """
    world = setup_booking_world(home_size="STUDIO", loyalty_count=0)
    cust = world["customer"]
    cust_hdr = make_customer_headers(cust["id"])
    booking = create_one_time_booking(world, scheduled_start="2026-06-10T09:00:00Z")
    _, meta = validate_paginated(
        api.list_ledger_entries(cust_hdr, params={"booking_id": booking["id"], "kind": "CHARGE"})
    )
    assert meta["total_count"] == 1, \
        f"Expected exactly one CHARGE ledger entry visible immediately, got {meta['total_count']}"
