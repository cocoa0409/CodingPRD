"""Onboarding, entity creation, computed fields, and existence/validation basics.

Covers queue-B corner instances under the `entities` section plus the location
version-increment reconciliation instance.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    assert_host, assert_booking, assert_bag,
    TEST_USERS, ANON_HEADERS,
    setup_open_location, set_clock, create_host, create_traveler,
    create_insurance_plan, create_location, open_location, create_booking, get_bags,
    make_host_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_create_host_returns_full_active_host(api):
    """PRD §3.1: "A freshly onboarded host is `ACTIVE`, and all of its money counters —
    `pending_payout_cents`, `payout_balance_cents`, `lifetime_earnings_cents` — and its
    rating counters `rating_sum`, `rating_count`, and `avg_rating` are initialized to zero."
    PRD §2.4: "The `version` begins at 1 when the resource is created and increments by 1
    on every mutation that changes the resource."

    Design: Corner/entities/host_create_returns_full_host
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    resp = api.create_host(
        {"display_name": "Acme Storage", "email": "a@x.com",
         "platform_fee_bps": 1500, "max_concurrent_bookings": 3}, ADMIN)
    data = validate_success(resp, 201)
    assert_host(data)
    assert data["status"] == "ACTIVE"
    assert data["payout_balance_cents"] == 0
    assert data["pending_payout_cents"] == 0
    assert data["lifetime_earnings_cents"] == 0
    assert data["version"] == 1


def test_get_host_nonexistent_returns_not_found(api):
    """PRD §2.9: "the first segment that names a nonexistent resource causes `ERR_NOT_FOUND`
    before any deeper segment or foreign key is examined."

    Design: Corner/entities/get_host_nonexistent_returns_not_found
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    resp = api.get_host(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_traveler_missing_required_field_returns_validation(api):
    """PRD §2.8: "A malformed body or a missing required field that is caught before any
    domain check surfaces as `ERR_VALIDATION`."
    PRD §3.1: "Travelers self-register without authentication, providing an `email` and a
    `full_name`."

    Design: Corner/entities/traveler_missing_required_field_returns_validation
    """
    resp = api.create_traveler({"email": "nobody@x.com"}, ANON_HEADERS)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_booking_bag_count_and_oversize_computed(api):
    """PRD §3.3: "A bag's `is_oversize` flag is computed, never taken from input: a bag is
    oversize exactly when its `dimension_sum_cm` is at least 150 centimeters. The booking's
    `bag_count` is the number of bags minted, and its `oversize_count` is how many of them
    are oversize."

    Design: Corner/entities/booking_bag_count_and_oversize_computed
    """
    ctx = setup_open_location(api, tier="NONE", per_bag_coverage_cents=0, premium_cents_per_bag_day=0)
    booking = create_booking(
        api, ctx, check_in_date="2026-06-10", check_out_date="2026-06-12",
        bags=[{"declared_value_cents": 1000, "dimension_sum_cm": 100},
              {"declared_value_cents": 1000, "dimension_sum_cm": 160}])
    assert_booking(booking)
    assert booking["bag_count"] == 2
    assert booking["oversize_count"] == 1
    bags = get_bags(api, ctx, booking["id"])
    oversize_flags = sorted(b["is_oversize"] for b in bags)
    assert oversize_flags == [False, True]


def test_booking_unknown_location_returns_not_found(api):
    """PRD §2.9: "Foreign keys supplied in a request body are resolved the same way and are
    equally subject to `ERR_NOT_FOUND`."
    PRD §2.9: "Only once all referenced resources are confirmed to exist do ownership, state,
    and domain checks proceed in the order of §2.8."

    Design: Corner/entities/booking_unknown_location_returns_not_found
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    traveler = create_traveler(api, email="t@x.com")
    plan = create_insurance_plan(api, tier="NONE", per_bag_coverage_cents=0, premium_cents_per_bag_day=0)
    from test_helpers import make_traveler_headers
    # A well-formed request whose only fault is the nonexistent location_id: existence
    # (§2.8 priority 3) is checked before the OCC version compare (priority 5).
    resp = api.create_booking(
        {"location_id": NON_EXISTENT_UUID, "traveler_id": traveler["id"],
         "insurance_plan_id": plan["id"], "check_in_date": "2026-06-10",
         "check_out_date": "2026-06-12",
         "bags": [{"declared_value_cents": 1000, "dimension_sum_cm": 100}],
         "expected_location_version": 1},
        make_traveler_headers(traveler["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_location_version_increments_on_status_change(api):
    """PRD §2.4: "The `version` begins at 1 when the resource is created and increments by 1
    on every mutation that changes the resource."

    Design: Corner/cross_cutting_complexity_layers/location_version_increments_on_status_change
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    host = create_host(api, email="h@x.com")
    location = create_location(api, host["id"])
    assert location["version"] == 1
    opened = open_location(api, host["id"], location["id"])
    assert opened["version"] == 2
    assert opened["status"] == "OPEN"
