"""Confirmation-gating tests: cross-entity dependencies (party posture, unit pool)
and temporal-overlap geometry (cleaning buffer, customer window conflict)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    set_clock, create_catalog, create_unit, create_customer, create_reservation,
    confirm, create_measurement_profile, make_customer_headers,
    setup_ready_party_locked, return_reservation,
)
from test_helpers import api_client
from test_helpers import TEST_USERS
from test_helpers.factories import (
    create_reservation_payload, create_fit_check_payload, return_payload,
)

CLERK = TEST_USERS["clerk_headers"]

CAT = {
    "daily_rate_cents": 5000, "deposit_cents": 20000, "replacement_value_cents": 80000,
    "waiver_daily_rate_cents": 1200, "cleaning_buffer_days": 2, "late_fee_daily_rate_cents": 2000,
}


def test_confirm_blocked_when_party_locked(api):
    """PRD §3.4: "If the reservation names a `party_order_id`, the linked party's `posture` must be `FORMING` or `READY` and the party's `event_date_iso` must equal the reservation's `event_date_iso`, failing which the confirm is rejected with `ERR_PARTY_NOT_OPEN".

    Design: Difficulty/cross_entity_state_dependency/confirm_depends_on_party_posture_open
    """
    info = setup_ready_party_locked(event_date_iso="2026-09-06T00:00:00Z")
    catalog = info["catalog"]
    coordinator = info["coordinator"]
    # Add a second unit so unit availability is not the blocker for the second member.
    create_unit(catalog["id"], "M")
    member2 = create_customer()

    # member2 books into the now-LOCKED party (a still-PENDING member).
    resv2 = validate_success(api_client.create_reservation(
        create_reservation_payload(member2["id"], catalog["id"], requested_size_code="M",
                                   event_date_iso="2026-09-06T00:00:00Z",
                                   party_order_id=info["party"]["id"]),
        make_customer_headers(member2["id"])), 201)

    party = validate_success(api_client.get_party_order(
        info["party"]["id"], make_customer_headers(coordinator["id"])), 200)
    assert party["posture"] == "LOCKED"

    res = api_client.confirm_reservation(
        resv2["id"], {"expected_party_order_version": party["version"]}, CLERK)
    validate_error(res, ApiErrorId.ERR_PARTY_NOT_OPEN)
    after = validate_success(api_client.get_reservation(resv2["id"], CLERK), 200)
    assert after["status"] == "PENDING", "rejected; member stays PENDING"


def test_confirm_blocked_when_no_unit_available(api):
    """PRD §3.4: "There must exist an allocatable unit (described below) or the confirm is rejected with `ERR_NO_UNIT_AVAILABLE`."
    PRD §3.4: "An allocatable unit is one of the reservation's `catalog_id` whose `size_code` equals the `requested_size_code`, whose `status` is `AVAILABLE".

    Design: Difficulty/cross_entity_state_dependency/confirm_depends_on_garment_unit_availability
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux M"})
    unit = create_unit(catalog["id"], "M")
    cust1 = create_customer()
    cust2 = create_customer()
    resv1 = create_reservation(cust1["id"], catalog["id"], requested_size_code="M")
    validate_success(confirm(resv1["id"]), 200)  # consumes the only unit -> RESERVED

    resv2 = create_reservation(cust2["id"], catalog["id"], requested_size_code="M")
    res = api_client.confirm_reservation(resv2["id"], {}, CLERK)
    validate_error(res, ApiErrorId.ERR_NO_UNIT_AVAILABLE)

    held = validate_success(api_client.get_garment_unit(unit["id"], CLERK), 200)
    assert held["status"] == "RESERVED", "the only unit is held by resv1"
    after = validate_success(api_client.get_reservation(resv2["id"], CLERK), 200)
    assert after["status"] == "PENDING", "rejected; no transition"


def test_cleaning_buffer_overlap_blocks_confirm(api):
    """PRD §3.7: "The unit transitions from `OUT` to `IN_CLEANING`, and its `available_from_iso` is set to the `returned_at_iso` plus the catalog's `cleaning_buffer_days`."
    PRD §3.4: "An allocatable unit is one of the reservation's `catalog_id` whose `size_code` equals the `requested_size_code`, whose `status` is `AVAILABLE`, whose `condition_grade` is `GRADE_A` or `GRADE_B` (a `GRADE_C` unit is never allocated), and whose `available_from_iso` is either null or on or before the `pickup_window_start_iso`."

    Design: Difficulty/resource_temporal_overlap/garment_unit_cleaning_buffer_overlap_blocks_confirm
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux N"})
    unit = create_unit(catalog["id"], "M")
    cust1 = create_customer()
    cust2 = create_customer()
    mp1 = create_measurement_profile(cust1["id"], chest_cm=100)

    # First reservation: confirm -> fit -> pickup -> return 09-03T12:00 (buffer 2 days),
    # so available_from_iso == 09-05T12:00.
    resv1 = create_reservation(cust1["id"], catalog["id"], requested_size_code="M",
                               event_date_iso="2026-09-04T00:00:00Z",
                               pickup_window_start_iso="2026-09-01T09:00:00Z",
                               return_window_end_iso="2026-09-03T17:00:00Z")
    validate_success(confirm(resv1["id"]), 200)
    validate_success(api_client.create_fit_check(
        create_fit_check_payload(resv1["id"], mp1["id"]), CLERK), 201)
    validate_success(api_client.pickup_reservation(resv1["id"], CLERK), 200)
    return_reservation(resv1["id"], "2026-09-03T12:00:00Z", "CLEAN")

    unit_after = validate_success(api_client.get_garment_unit(unit["id"], CLERK), 200)
    assert unit_after["available_from_iso"] == "2026-09-05T12:00:00.000Z", \
        f"returned 09-03T12:00 + 2 buffer days; got {unit_after['available_from_iso']}"

    # Second reservation wants pickup 09-04T09:00, inside the buffer window.
    resv2 = create_reservation(cust2["id"], catalog["id"], requested_size_code="M",
                               event_date_iso="2026-09-05T00:00:00Z",
                               pickup_window_start_iso="2026-09-04T09:00:00Z",
                               return_window_end_iso="2026-09-04T18:00:00Z")
    res = api_client.confirm_reservation(resv2["id"], {}, CLERK)
    validate_error(res, ApiErrorId.ERR_NO_UNIT_AVAILABLE)
    after = validate_success(api_client.get_reservation(resv2["id"], CLERK), 200)
    assert after["status"] == "PENDING"


def test_customer_window_overlap_half_open_blocks_confirm(api):
    """PRD §3.4: "The same customer must not already hold another reservation, in `CONFIRMED`, `PICKED_UP`, or `OVERDUE` status, whose rental window overlaps this one; the rental window is the half-open interval running from `pickup_window_start_iso` up to but not including `return_window_end_iso`, compared with no added buffer, and any overlap is rejected with `ERR_CUSTOMER_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/customer_rental_window_overlap_half_open_blocks_confirm
    """
    set_clock()
    catalog = create_catalog(**{**CAT, "style_name": "Tux O"})
    create_unit(catalog["id"], "M")
    create_unit(catalog["id"], "M")  # two units so unit availability is not the blocker
    customer = create_customer()

    resv1 = create_reservation(customer["id"], catalog["id"], requested_size_code="M",
                               event_date_iso="2026-09-06T00:00:00Z",
                               pickup_window_start_iso="2026-09-01T09:00:00Z",
                               return_window_end_iso="2026-09-05T09:00:00Z")
    confirmed1 = validate_success(confirm(resv1["id"]), 200)
    assert confirmed1["status"] == "CONFIRMED"

    # Overlapping window [09-03, 09-08) vs the confirmed [09-01, 09-05).
    resv2 = create_reservation(customer["id"], catalog["id"], requested_size_code="M",
                               event_date_iso="2026-09-09T00:00:00Z",
                               pickup_window_start_iso="2026-09-03T09:00:00Z",
                               return_window_end_iso="2026-09-08T09:00:00Z")
    res = api_client.confirm_reservation(resv2["id"], {}, CLERK)
    validate_error(res, ApiErrorId.ERR_CUSTOMER_WINDOW_CONFLICT)
    after = validate_success(api_client.get_reservation(resv2["id"], CLERK), 200)
    assert after["status"] == "PENDING"
