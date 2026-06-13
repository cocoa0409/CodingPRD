"""Inventory configuration, basic CRUD, listing, and request-shape validation.

Translates Corner-design instances from the `entities`, `endpoints`, and `errors`
sections plus the request-shape RBAC checks. Each test cites a verbatim PRD
sentence and is tagged with its source design instance.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    assert_venue,
    assert_space,
    assert_payment,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    create_venue_payload,
    create_space_payload,
    create_package_payload,
    create_booking_payload,
    create_payment_payload,
    create_inventory,
    create_inquiry_booking,
    add_both_holds,
    place_soft_hold,
    pay_deposit,
    confirm,
    set_clock,
)

VA = TEST_USERS["venue_admin_headers"]


def test_create_venue_returns_201_with_defaults(api):
    """PRD §3.1: "an optional `cancellation_tier` drawn from `STANDARD`, `STRICT`,
    or `FLEXIBLE` (defaulting to `STANDARD`), and an optional `force_majeure_fee_pct`
    between 0.0 and 0.25 inclusive (defaulting to 0.0). A venue's `status` is
    system-managed, beginning `ACTIVE`".
    PRD §2.4: "an integer `version` that begins at its initial value and increments
    by one on every mutation of the resource."

    Design: Corner/entities/create_venue_returns_201_with_defaults
    """
    res = api.create_venue({"name": "Solo Venue"}, VA)
    data = validate_success(res, expected_status=201)
    assert_venue(data)
    assert data["status"] == "ACTIVE"
    assert data["cancellation_tier"] == "STANDARD"
    assert data["force_majeure_fee_pct"] == 0.0
    assert data["version"] == 1


def test_get_booking_returns_stored_entity(api):
    """PRD §3.2: "On creation the booking lands at `booking_status` `INQUIRY` and
    `payment_status` `UNPAID`; its `coordinator_id` is null until assigned."
    PRD §3.5: "The booking's `amount_paid_cents` is always derived from this stream".

    Design: Corner/entities/get_booking_returns_stored_entity
    """
    inv = create_inventory(with_space=False, with_coordinator=False)
    booking = create_inquiry_booking(inv, assign_coordinator=False)
    res = api.get_booking(booking["id"], inv["client_headers"])
    data = validate_success(res)
    assert data["booking_status"] == "INQUIRY"
    assert data["payment_status"] == "UNPAID"
    assert data["amount_paid_cents"] == 0


def test_list_spaces_paginated_total_count_has_more(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned".
    PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
    `total_count`, `has_more`) are included for list endpoints."

    Design: Corner/entities/list_spaces_paginated_total_count_has_more
    """
    set_clock()
    venue = get_success_data(api.create_venue(create_venue_payload(), VA))
    get_success_data(api.create_space(
        venue["id"], create_space_payload(name="S1", space_kind="CEREMONY",
                                          max_capacity=100, base_rental_cents=100_000), VA))
    get_success_data(api.create_space(
        venue["id"], create_space_payload(name="S2", space_kind="RECEPTION",
                                          max_capacity=200, base_rental_cents=200_000), VA))
    res = api.list_spaces(venue["id"], VA, params={"limit": 1, "offset": 0})
    rows, meta = validate_paginated(res)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(rows) == 1


def test_get_booking_not_found_returns_404(api):
    """PRD §2.5: "The first identifier in the path that does not resolve to an
    existing resource yields `ERR_NOT_FOUND` (HTTP 404) before any deeper resource
    is consulted".

    Design: Corner/entities/get_booking_not_found_returns_404
    """
    res = api.get_booking(NON_EXISTENT_UUID, VA)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_booking_missing_required_field_rejected(api):
    """PRD §2.9: "does the system validate the request body's shape — required
    fields present and well-typed, enums in range, numeric bounds satisfied —
    yielding `ERR_INVALID_REQUEST`."
    PRD §3.2: "an `expected_guest_count` of at least 1 representing the early
    estimate used for the provisional charge."

    Design: Corner/entities/create_booking_missing_required_field_rejected
    """
    inv = create_inventory(with_space=False, with_coordinator=False)
    payload = create_booking_payload(inv["client_id"], inv["venue_id"], inv["package_id"])
    del payload["expected_guest_count"]
    res = api.create_booking(payload, inv["client_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_space_default_turnover_buffer_zero(api):
    """PRD §3.1: "an optional `turnover_buffer_minutes` (at least 0, defaulting to 0)
    that fixes the minimum gap required after one occupation ends before the next
    may begin on the same space."

    Design: Corner/entities/space_default_turnover_buffer_zero
    """
    set_clock()
    venue = get_success_data(api.create_venue(create_venue_payload(), VA))
    res = api.create_space(
        venue["id"],
        {"name": "S", "space_kind": "DUAL", "max_capacity": 100, "base_rental_cents": 100_000},
        VA)
    data = validate_success(res, expected_status=201)
    assert data["turnover_buffer_minutes"] == 0


def test_payment_immutable_no_version_field(api):
    """PRD §2.4: "a `Payment` carries only `id` and `created_at` — it has neither
    `updated_at` nor `version`. Implementers must not invent those two fields for
    payments."

    Design: Corner/entities/payment_immutable_no_version_field
    """
    inv = create_inventory()
    booking = create_inquiry_booking(inv)
    booking, _, _ = add_both_holds(inv, booking)
    place_soft_hold(inv, booking["id"])
    res = api.post_payment(
        booking["id"], create_payment_payload("INBOUND", 500_000, "CHECK"),
        TEST_USERS["finance_officer_headers"])
    data = validate_success(res, expected_status=201)
    assert_payment(data)
    assert data["status"] == "POSTED"
    assert "version" not in data
    assert "updated_at" not in data


def test_delete_held_hold_releases_it(api):
    """PRD §3.3: "A `Coordinator` may also explicitly release a single `HELD` hold;
    releasing transitions that hold's `hold_status` from `HELD` to `RELEASED` and
    frees its space-date interval for others."

    Design: Corner/endpoints/delete_held_hold_releases_it
    """
    inv = create_inventory()
    booking = create_inquiry_booking(inv, assign_coordinator=False)
    coord = inv["coord_headers"]
    hold = get_success_data(api.create_hold(
        booking["id"],
        {"space_id": inv["space_id"], "block_role": "CEREMONY",
         "expected_booking_version": booking["version"]},
        coord))
    res = api.delete_hold(booking["id"], hold["id"], coord)
    data = validate_success(res)
    assert data["hold_status"] == "RELEASED"


def test_list_holds_by_space_filter(api):
    """PRD §3.3: "the hold's `hold_status` starts at `HELD`."
    PRD §3.3: "On creation the hold's `occupy_start` and `occupy_end` are copied by
    the system from the booking's matching block — the ceremony block instants for a
    `CEREMONY` hold, the reception block instants for a `RECEPTION` hold".

    Design: Corner/endpoints/list_holds_by_space_filter
    """
    inv = create_inventory()
    booking = create_inquiry_booking(inv, assign_coordinator=False)
    coord = inv["coord_headers"]
    get_success_data(api.create_hold(
        booking["id"],
        {"space_id": inv["space_id"], "block_role": "CEREMONY",
         "expected_booking_version": booking["version"]},
        coord))
    res = api.list_holds(coord, params={"space_id": inv["space_id"]})
    rows, meta = validate_paginated(res)
    assert meta["total_count"] == 1
    assert rows[0]["space_id"] == inv["space_id"]
    assert rows[0]["hold_status"] == "HELD"


def test_pagination_limit_over_max_rejected(api):
    """PRD §2.3: "A `limit` or `offset` outside its permitted range is rejected
    with `ERR_VALIDATION_LIMIT` (HTTP 422)."

    Design: Corner/errors/pagination_limit_over_max_rejected
    """
    res = api.list_bookings(VA, params={"limit": 101})
    validate_error(res, ApiErrorId.ERR_VALIDATION_LIMIT.value)


def test_reference_not_found_archived_venue_on_booking(api):
    """PRD §3.1: "When a write body references a parent that does not exist or is
    `ARCHIVED` — a venue, package, space, or client — the request is rejected with
    `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/errors/reference_not_found_archived_venue_on_booking
    """
    inv = create_inventory(with_space=False, with_coordinator=False)
    get_success_data(api.archive_venue(inv["venue_id"], VA))
    payload = create_booking_payload(inv["client_id"], inv["venue_id"], inv["package_id"])
    res = api.create_booking(payload, inv["client_headers"])
    validate_error(res, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)
