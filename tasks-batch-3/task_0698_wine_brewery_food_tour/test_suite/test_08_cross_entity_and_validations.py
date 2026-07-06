"""Cross-entity state preconditions, reserve-time validation precedence, and
standalone business-rule validations.

Queue A: cross_entity_state_dependency, priority_pair_validation_conflict.
Queue B: validations section.
"""
from test_helpers import (
    validate_error, validate_error_is_one_of, ApiErrorId,
    make_operator_headers, make_guest_headers, make_partner_venue_headers,
    get_success_data,
    create_tour_product_payload, create_vehicle_payload, create_partner_venue_payload,
    create_departure_payload, create_stop_payload, create_guest_payload,
    create_booking_payload,
    setup_scheduled_departure, setup_scheduled_departure_with_confirmed_stop,
    setup_venue_confirmation_at_revision,
)
from test_helpers import api_client

OP = make_operator_headers()


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency
# ---------------------------------------------------------------------------
def test_booking_pay_requires_guest_cleared(api):
    """PRD §3.6: "it requires that the lead guest be fully cleared — both
    `age_verified` and `waiver_signed` must be true — failing which the payment
    is rejected with `ERR_GUEST_NOT_CLEARED`."

    Design: Difficulty/cross_entity_state_dependency/booking_pay_requires_guest_cleared
    """
    # RESERVED booking; lead guest age_verified but waiver NOT signed.
    s = setup_scheduled_departure(seat_capacity=12)
    guest = get_success_data(api.create_guest(create_guest_payload(), OP))
    get_success_data(api.verify_age(guest["id"], OP))  # age verified, waiver still unsigned
    booking = get_success_data(api.create_booking(
        create_booking_payload(s["departure"]["id"], guest["id"], s["pickup"]["id"], 4),
        make_guest_headers(guest["id"])))
    get_success_data(api.reserve_booking(
        booking["id"], s["departure"]["version"], make_guest_headers(guest["id"])))
    resp = api.pay_booking(booking["id"], make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_GUEST_NOT_CLEARED.value, expected_status=409)


def test_departure_confirm_requires_vehicle_available(api):
    """PRD §3.8: "The assigned vehicle must be `AVAILABLE`, failing which the
    confirm is rejected with `ERR_VEHICLE_UNAVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/departure_confirm_requires_vehicle_available
    """
    # SCHEDULED departure, CONFIRMED stop, RESERVED booking; van set OUT_OF_SERVICE.
    s = setup_scheduled_departure_with_confirmed_stop(seat_capacity=12, requested_headcount=4)
    guest = get_success_data(api.create_guest(create_guest_payload(), OP))
    booking = get_success_data(api.create_booking(
        create_booking_payload(s["departure"]["id"], guest["id"], s["pickup"]["id"], 4),
        make_guest_headers(guest["id"])))
    get_success_data(api.reserve_booking(
        booking["id"], s["departure"]["version"], make_guest_headers(guest["id"])))
    get_success_data(api.set_vehicle_status(s["vehicle"]["id"], "OUT_OF_SERVICE", OP))
    resp = api.confirm_departure(s["departure"]["id"], OP)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_UNAVAILABLE.value, expected_status=409)


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict
# ---------------------------------------------------------------------------
def test_state_beats_fiscal_on_reserve_terminal_departure(api):
    """PRD §3.6: "The platform first confirms the departure is in `SCHEDULED`
    (`ERR_DEPARTURE_NOT_BOOKABLE`); then verifies the lead guest meets the
    minimum age (`ERR_UNDERAGE_GUEST`); then, for a private charter, that the
    whole-van rule holds (`ERR_CHARTER_WHOLE_VAN_REQUIRED`); then that the seat
    pool has room (`ERR_SEAT_CAPACITY_EXCEEDED`); and finally that the supplied
    departure version is current (`ERR_STALE_VERSION`)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reserve_terminal_departure
    """
    # seat_capacity 4; DRAFT booking party 8 (> capacity); departure then CANCELLED_OPS.
    s = setup_scheduled_departure(seat_capacity=4)
    guest = get_success_data(api.create_guest(create_guest_payload(), OP))
    booking = get_success_data(api.create_booking(
        create_booking_payload(s["departure"]["id"], guest["id"], s["pickup"]["id"], 8),
        make_guest_headers(guest["id"])))
    cancelled = get_success_data(api.cancel_departure_ops(s["departure"]["id"], "scrub", OP))
    # Reserve against a non-SCHEDULED departure with an oversized party: a
    # state precondition wins over the fiscal capacity check. PRD §3.8's cancel-ops
    # cascade also moves "every non-terminal booking" (incl. this DRAFT one) to
    # CANCELLED, so a PRD-faithful impl that checks the booking's own state first
    # reports ERR_INVALID_STATE, while one that checks the departure state first
    # reports ERR_DEPARTURE_NOT_BOOKABLE. The PRD names both as possible and does
    # not order booking-state vs departure-state, so either is acceptable; both
    # are HTTP 409.
    resp = api.reserve_booking(booking["id"], cancelled["version"],
                               make_guest_headers(guest["id"]))
    assert resp.status_code == 409, f"expected 409, got {resp.status_code}"
    validate_error_is_one_of(resp, [
        ApiErrorId.ERR_DEPARTURE_NOT_BOOKABLE.value,
        ApiErrorId.ERR_INVALID_STATE.value,
    ])


def test_safety_beats_fiscal_on_reserve_underage_overcapacity(api):
    """PRD §3.6: "then verifies the lead guest meets the minimum age
    (`ERR_UNDERAGE_GUEST`); ... then that the seat pool has room
    (`ERR_SEAT_CAPACITY_EXCEEDED`)"
    PRD §3.6: "an underage lead guest is rejected with `ERR_UNDERAGE_GUEST`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_reserve_underage_overcapacity
    """
    # SCHEDULED departure seat_capacity 4, min_guest_age 21; party 8 (over capacity),
    # lead guest born 2010 (underage at default clock 2026-03-01). Underage wins.
    s = setup_scheduled_departure(seat_capacity=4,
                                  product_overrides={"min_guest_age": 21})
    guest = get_success_data(api.create_guest(
        create_guest_payload(full_name="Kid", birth_date="2010-06-15T00:00:00Z"), OP))
    booking = get_success_data(api.create_booking(
        create_booking_payload(s["departure"]["id"], guest["id"], s["pickup"]["id"], 8),
        make_guest_headers(guest["id"])))
    resp = api.reserve_booking(booking["id"], s["departure"]["version"],
                               make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_UNDERAGE_GUEST.value, expected_status=422)


# ---------------------------------------------------------------------------
# Queue B: validations
# ---------------------------------------------------------------------------
def test_duplicate_stop_sequence_rejected(api):
    """PRD §3.3: "The `sequence` must be unique within its departure; an attempt
    to reuse a sequence number already present on that departure is rejected with
    `ERR_DUPLICATE_STOP_SEQUENCE`."

    Design: Corner/validations/duplicate_stop_sequence_rejected
    """
    product = get_success_data(api.create_tour_product(create_tour_product_payload(), OP))
    vehicle = get_success_data(api.create_vehicle(create_vehicle_payload(), OP))
    venue = get_success_data(api.create_partner_venue(
        create_partner_venue_payload(commission_pct=0.10,
                                     tasting_cost_per_guest_cents=1200), OP))
    departure = get_success_data(api.create_departure(
        create_departure_payload(product["id"], vehicle["id"]), OP))
    get_success_data(api.create_stop(
        create_stop_payload(departure["id"], venue["id"], sequence=1, dwell_minutes=60), OP))
    resp = api.create_stop(
        create_stop_payload(departure["id"], venue["id"], sequence=1, dwell_minutes=30), OP)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_STOP_SEQUENCE.value, expected_status=409)


def test_gratuity_pct_out_of_range_rejected(api):
    """PRD §3.1: "The `gratuity_pct` is the default gratuity rate applied to
    seats and add-ons; it defaults to 0.18 and must lie between 0.0 and 0.30
    inclusive."

    Design: Corner/validations/gratuity_pct_out_of_range_rejected
    """
    resp = api.create_tour_product(
        create_tour_product_payload(name="P", theme="WINE",
                                    base_price_per_person_cents=9000, gratuity_pct=0.40), OP)
    validate_error(resp, ApiErrorId.ERR_VALUE_OUT_OF_RANGE.value, expected_status=422)


def test_revision_limit_reached_on_fourth_resubmit(api):
    """PRD §3.4: "A resubmit is permitted only while the confirmation's
    `revision_count` is less than 3; once three revisions have been spent, a
    further resubmit is rejected with `ERR_REVISION_LIMIT_REACHED`."

    Design: Corner/validations/revision_limit_reached_on_fourth_resubmit
    """
    # Cycle to revision_count 3, currently CHANGES_REQUESTED; a 4th resubmit is rejected.
    s = setup_venue_confirmation_at_revision(target_revisions=3)
    assert s["confirmation"]["revision_count"] == 3, \
        f"setup expected revision_count 3, got {s['confirmation']['revision_count']}"
    resp = api.resubmit_venue_confirmation(s["confirmation"]["id"], 8, OP)
    validate_error(resp, ApiErrorId.ERR_REVISION_LIMIT_REACHED.value, expected_status=409)


def test_retire_product_with_active_departure_rejected(api):
    """PRD §3.1: "Retiring a `PUBLISHED` product advances it to `RETIRED`, but
    only if no departure of this product is currently in `SCHEDULED`,
    `CONFIRMED`, or `DEPARTED` status; if any such live departure exists, the
    retire is rejected with `ERR_PRODUCT_HAS_ACTIVE_DEPARTURES`."

    Design: Corner/validations/retire_product_with_active_departure_rejected
    """
    s = setup_scheduled_departure(seat_capacity=12)  # PUBLISHED product + SCHEDULED departure
    resp = api.retire_tour_product(s["product"]["id"], OP)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_HAS_ACTIVE_DEPARTURES.value, expected_status=409)


def test_pagination_limit_too_large_rejected(api):
    """PRD §2.3: "A `limit` outside the range of 1 through 100 inclusive, or an
    `offset` below 0, is rejected with `ERR_INVALID_PAGINATION`."

    Design: Corner/validations/pagination_limit_too_large_rejected
    """
    resp = api.list_tour_products(OP, params={"limit": 500})
    validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value, expected_status=400)
