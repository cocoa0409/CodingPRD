"""Booking validation rule violations — Queue B (Corner) and validation-error mapping."""
import pytest

from test_helpers import (
    validate_error,
    validate_success,
    set_clock,
    setup_guest_restaurant_plan_session,
    setup_pending_reservation,
    setup_confirmed_reservation,
    create_pending_reservation,
    confirm_reservation,
    create_park_session,
    create_dining_plan,
    create_guest,
    create_restaurant,
    create_reservation_payload,
    create_allergy_meal_payload,
    patch_party_size_payload,
    make_guest_headers,
    ApiErrorId,
)


def test_slot_misaligned_off_30min_grid_returns_error(api):
    """PRD §3.3: "The slot start must additionally land on a 30-minute grid measured
    from opening_local_time — if opening is 11:00 a 13:30 start is on grid and a
    13:15 start is not, the latter producing ERR_SLOT_MISALIGNED."

    Design: Corner/validations/slot_misaligned_off_30min_grid_returns_invalid_request_error
    """
    set_clock("2026-01-15T12:00:00Z")
    guest, restaurant, dp, ps = setup_guest_restaurant_plan_session(
        park_code="EPCOT",
        opening_local_time="11:00",
        closing_local_time="22:00",
    )
    payload = create_reservation_payload(
        guest_id=guest["id"],
        restaurant_id=restaurant["id"],
        park_session_id=ps["id"],
        dining_plan_id=dp["id"],
        # 11:10 EST = 16:10 UTC (Standard Time, no DST in Feb)
        slot_start_utc="2026-02-15T16:10:00Z",
        party_size=1,
    )
    res = api.create_reservation(payload, make_guest_headers(guest["id"]))
    validate_error(res, ApiErrorId.ERR_SLOT_MISALIGNED, expected_status=422)


def test_slot_outside_hours_after_closing_returns_error(api):
    """PRD §3.3: "The slot start, projected back to resort wall-clock, must fall in
    the half-open interval from the restaurant's opening_local_time (inclusive) up
    to its closing_local_time (exclusive); outside that range the request is
    rejected with ERR_SLOT_OUTSIDE_HOURS."

    Design: Corner/validations/slot_outside_hours_after_closing_returns_error
    """
    set_clock("2026-01-15T12:00:00Z")
    guest, restaurant, dp, ps = setup_guest_restaurant_plan_session(
        park_code="EPCOT",
        opening_local_time="11:00",
        closing_local_time="22:00",
    )
    payload = create_reservation_payload(
        guest_id=guest["id"],
        restaurant_id=restaurant["id"],
        park_session_id=ps["id"],
        dining_plan_id=dp["id"],
        # 2026-02-16T03:30Z = 22:30 EST on 2026-02-15 (after closing 22:00)
        slot_start_utc="2026-02-16T03:30:00Z",
        party_size=1,
    )
    res = api.create_reservation(payload, make_guest_headers(guest["id"]))
    validate_error(res, ApiErrorId.ERR_SLOT_OUTSIDE_HOURS, expected_status=422)


def test_insufficient_credits_on_confirm_returns_error(api):
    """PRD §3.4: "The plan must also have enough free credits: the difference between
    its table_service_credits_remaining and its current table_service_credits_held
    must be at least the restaurant's dining_plan_credit_cost multiplied by the
    reservation's party_size. If the plan is short, confirmation fails with
    ERR_INSUFFICIENT_CREDITS."

    Design: Corner/validations/insufficient_credits_on_confirm_returns_error
    """
    set_clock("2026-01-15T12:00:00Z")
    # Restaurant dining_plan_credit_cost=2, party_size=2 → requires 4 credits;
    # plan has only 1 credit.
    guest, restaurant, dp, ps = setup_guest_restaurant_plan_session(
        park_code="EPCOT",
        dining_plan_credit_cost=2,
        table_service_credits_initial=1,
    )
    pending = create_pending_reservation(
        guest, restaurant, ps, dp,
        slot_start_utc="2026-02-15T18:00:00Z",
        party_size=2,
    )
    res = api.confirm_reservation(pending["id"], make_guest_headers(guest["id"]))
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_CREDITS, expected_status=422)


def test_invalid_allergen_code_returns_error(api):
    """PRD §3.6: "An empty array or any unrecognised allergen value yields
    ERR_INVALID_ALLERGEN."

    Design: Corner/validations/invalid_allergen_code_returns_error
    """
    _, _, _, _, reservation = setup_confirmed_reservation(party_size=1)
    payload = create_allergy_meal_payload(
        reservation_id=reservation["id"],
        allergen_codes=["KIWI"],   # not in PRD's allowed set
    )
    res = api.create_allergy_meal(payload, make_guest_headers(reservation["guest_id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_ALLERGEN, expected_status=422)


def test_addon_already_exists_second_allergy_meal_rejected(api):
    """PRD §3.6: "Only one allergy meal may exist per reservation; attempting to
    create a second one returns ERR_ADDON_ALREADY_EXISTS"

    Design: Corner/validations/addon_already_exists_second_allergy_meal_rejected
    """
    _, _, _, _, reservation = setup_confirmed_reservation(party_size=1)
    # First allergy meal — succeeds
    first = create_allergy_meal_payload(
        reservation_id=reservation["id"], allergen_codes=["PEANUT"],
    )
    api.create_allergy_meal(first, make_guest_headers(reservation["guest_id"]))
    # Second attempt — rejected
    second = create_allergy_meal_payload(
        reservation_id=reservation["id"], allergen_codes=["DAIRY"],
    )
    res = api.create_allergy_meal(second, make_guest_headers(reservation["guest_id"]))
    validate_error(res, ApiErrorId.ERR_ADDON_ALREADY_EXISTS, expected_status=409)


def test_park_session_mismatch_wrong_park_returns_error(api):
    """PRD §3.3: "The supplied park_session_id must be in NOT_STARTED or ACTIVE
    status, must share the same park_code as the chosen restaurant, and its
    visit_date must equal the resort-projected calendar date of slot_start_utc;
    any mismatch yields ERR_PARK_SESSION_MISMATCH."

    Design: Corner/validations/park_session_mismatch_wrong_park_returns_error
    """
    set_clock("2026-01-15T12:00:00Z")
    # ParkSession in EPCOT but restaurant in MAGIC_KINGDOM.
    guest = create_guest(email="psm_corner@x.com")
    restaurant = create_restaurant(name="MK Restaurant", park_code="MAGIC_KINGDOM")
    dp = create_dining_plan(guest["id"], table_service_credits_initial=5)
    ps = create_park_session(guest["id"], park_code="EPCOT", visit_date="2026-02-15")
    payload = create_reservation_payload(
        guest_id=guest["id"],
        restaurant_id=restaurant["id"],
        park_session_id=ps["id"],
        dining_plan_id=dp["id"],
        slot_start_utc="2026-02-15T18:00:00Z",
        party_size=1,
    )
    res = api.create_reservation(payload, make_guest_headers(guest["id"]))
    validate_error(res, ApiErrorId.ERR_PARK_SESSION_MISMATCH, expected_status=409)


def test_past_dining_date_returns_error(api):
    """PRD §3.3: "a booking whose visit_date (or whose slot) is already in the past
    relative to the current resort-time date is rejected with ERR_PAST_DINING_DATE."

    Design: Corner/validations/past_dining_date_returns_error
    """
    set_clock("2026-02-15T19:00:00Z")  # clock past the would-be slot at 18:00
    guest, restaurant, dp, ps = setup_guest_restaurant_plan_session(
        park_code="EPCOT", visit_date="2026-02-15",
    )
    payload = create_reservation_payload(
        guest_id=guest["id"],
        restaurant_id=restaurant["id"],
        park_session_id=ps["id"],
        dining_plan_id=dp["id"],
        slot_start_utc="2026-02-15T18:00:00Z",  # past
        party_size=1,
    )
    res = api.create_reservation(payload, make_guest_headers(guest["id"]))
    validate_error(res, ApiErrorId.ERR_PAST_DINING_DATE, expected_status=422)
