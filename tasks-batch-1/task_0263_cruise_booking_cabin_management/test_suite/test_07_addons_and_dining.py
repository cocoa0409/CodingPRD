"""Add-ons and dining: excursion overlap, add-on shape, dining party-size, cancel.

The half-open excursion-overlap rule (PRD 3.6) is exercised in both its
conflicting and its touching-adjacent forms.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_add_on_payload, create_dining_reservation_payload,
    make_guest_user_headers,
    create_quote_booking,
)

RM = TEST_USERS["revenue_manager_headers"]


def _single_guest_booking(api, owner, num_cabins=1):
    sailing, category, booking = create_quote_booking(
        owner, num_guests=1, num_cabins=num_cabins, guests=[("N One", 40)],
    )
    guests = get_success_data(api.list_guests(RM, params={"booking_id": booking["id"]}))
    if isinstance(guests, dict):
        guests = guests.get("data", guests)
    return booking, guests[0]


# ===========================================================================
# Difficulty: excursion half-open overlap on a guest
# ===========================================================================
def test_excursion_true_overlap_on_guest_conflicts(api):
    """PRD 3.6: "Two excursions assigned to the same guest may not overlap in time:
    overlap is judged on half-open intervals running from `window_start` up to but
    not including `window_end` ... while any true overlap with another `RESERVED`
    excursion on that guest is rejected with `ERR_TIME_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/excursion_halfopen_overlap_on_guest_touching_allowed
    """
    booking, guest = _single_guest_booking(api, "guest-13")
    headers = make_guest_user_headers("guest-13")
    get_success_data(api.create_add_on(
        create_add_on_payload(booking["id"], "EXCURSION", "Snorkel", 12000,
                              guest_id=guest["id"],
                              window_start="2026-09-02T10:00:00Z",
                              window_end="2026-09-02T12:00:00Z"),
        headers,
    ))
    # 11:00-13:00 truly overlaps 10:00-12:00.
    resp = api.create_add_on(
        create_add_on_payload(booking["id"], "EXCURSION", "Reef Tour", 9000,
                              guest_id=guest["id"],
                              window_start="2026-09-02T11:00:00Z",
                              window_end="2026-09-02T13:00:00Z"),
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_TIME_WINDOW_CONFLICT.value)


def test_excursion_touching_endpoint_on_guest_allowed(api):
    """PRD 3.6: "overlap is judged on half-open intervals running from `window_start`
    up to but not including `window_end`, so an excursion that ends exactly when
    another begins does not conflict".

    Design: Difficulty/resource_temporal_overlap/excursion_halfopen_overlap_on_guest_touching_allowed
    """
    booking, guest = _single_guest_booking(api, "guest-13b")
    headers = make_guest_user_headers("guest-13b")
    get_success_data(api.create_add_on(
        create_add_on_payload(booking["id"], "EXCURSION", "Snorkel", 12000,
                              guest_id=guest["id"],
                              window_start="2026-09-02T10:00:00Z",
                              window_end="2026-09-02T12:00:00Z"),
        headers,
    ))
    # 12:00-14:00 starts exactly when the first ends -> no conflict.
    resp = api.create_add_on(
        create_add_on_payload(booking["id"], "EXCURSION", "Beach Walk", 8000,
                              guest_id=guest["id"],
                              window_start="2026-09-02T12:00:00Z",
                              window_end="2026-09-02T14:00:00Z"),
        headers,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "RESERVED"


# ===========================================================================
# Corner: add-on shape, dining
# ===========================================================================
def test_dining_addon_create_succeeds_with_dining_kind(api):
    """PRD 3.6: "An `AddOn` is attached to a booking via its `booking_id` with a
    `kind` of `DINING` or `EXCURSION`, a `title`, and a `price_cents` of 0 or more,
    and starts in `RESERVED` status." PRD 3.6: "A `DINING` add-on takes none of
    those three".

    Design: Corner/endpoints/dining_addon_create_succeeds_with_dining_kind
    """
    sailing, category, booking = create_quote_booking(
        "guest-c12", num_guests=1, num_cabins=1, guests=[("C One", 40)],
    )
    resp = api.create_add_on(
        create_add_on_payload(booking["id"], "DINING", "Specialty Dining Package", 15000),
        make_guest_user_headers("guest-c12"),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "RESERVED"
    assert data["kind"] == "DINING"


def test_excursion_addon_missing_window_rejected(api):
    """PRD 3.6: "An `EXCURSION` is assigned to a specific guest and scheduled: it
    requires a `guest_id`, a `window_start`, and a `window_end` ... omitting any of
    them on an `EXCURSION`, is a shape violation rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/validations/excursion_addon_missing_window_rejected
    """
    booking, guest = _single_guest_booking(api, "guest-c11")
    resp = api.create_add_on(
        create_add_on_payload(booking["id"], "EXCURSION", "Snorkel", 12000,
                              guest_id=guest["id"]),  # no window_start/window_end
        make_guest_user_headers("guest-c11"),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_dining_party_size_exceeds_guest_count_rejected(api):
    """PRD 3.6: "The `party_size` must be at least 1 and must not exceed the
    booking's `guest_count`; a party larger than the roster is rejected with
    `ERR_OCCUPANCY_EXCEEDED`."

    Design: Corner/validations/dining_party_size_exceeds_guest_count_rejected
    """
    sailing, category, booking = create_quote_booking(
        "guest-c10", num_guests=2, num_cabins=1, guests=[("C One", 40), ("C Two", 38)],
    )
    resp = api.create_dining_reservation(
        create_dining_reservation_payload(booking["id"], "MAIN",
                                          "2026-09-02T18:00:00Z", 3),
        make_guest_user_headers("guest-c10"),
    )
    validate_error(resp, ApiErrorId.ERR_OCCUPANCY_EXCEEDED.value)


def test_dining_reservation_second_cancel_invalid(api):
    """PRD 3.6: "It starts `BOOKED` and may later be cancelled (`BOOKED →
    CANCELLED`, with a repeat cancellation rejected as `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/dining_reservation_cancel_idempotency_second_cancel_invalid
    """
    sailing, category, booking = create_quote_booking(
        "guest-c7", num_guests=2, num_cabins=1, guests=[("C One", 40), ("C Two", 38)],
    )
    headers = make_guest_user_headers("guest-c7")
    dr = get_success_data(api.create_dining_reservation(
        create_dining_reservation_payload(booking["id"], "MAIN",
                                          "2026-09-02T18:00:00Z", 2),
        headers,
    ))
    get_success_data(api.cancel_dining_reservation(dr["id"], headers))
    resp = api.cancel_dining_reservation(dr["id"], headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
