"""Error-condition coverage: OCC stale-version, FK-not-found, plan-not-covering,
party-size patch infeasibility — Queue B (Corner)."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    set_clock,
    setup_guest_restaurant_plan_session,
    setup_confirmed_reservation,
    create_guest,
    create_restaurant,
    create_dining_plan,
    create_park_session,
    create_pending_reservation,
    confirm_reservation,
    cancel_reservation_payload,
    patch_party_size_payload,
    create_reservation_payload,
    create_dining_plan_payload,
    make_guest_headers,
    TEST_USERS,
    ApiErrorId,
)


def test_stale_version_on_cancel_after_party_size_patch_returns_412(api):
    """PRD §2.7: "Both endpoints take a non-optional input field
    expected_reservation_version of integer type, which must equal the parent
    Reservation's current version. If it does not, the request is rejected with
    ERR_STALE_VERSION (HTTP 412) and no state changes."

    Design: Corner/errors/error_err_stale_version_on_cancel_negative_test
    """
    guest, restaurant, dp, ps, reservation = setup_confirmed_reservation(party_size=2)
    stale_version = reservation["version"]
    # Apply a party-size patch (advances version).
    patch_res = api.patch_party_size(
        reservation["id"],
        patch_party_size_payload(party_size=3),
        make_guest_headers(guest["id"]),
    )
    validate_success(patch_res, expected_status=200)
    # Cancel using the stale version — should be rejected with 412.
    res = api.cancel_reservation(
        reservation["id"],
        cancel_reservation_payload(stale_version),
        make_guest_headers(guest["id"]),
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    # Reservation must still be CONFIRMED.
    fetched = validate_success(
        api.get_reservation(reservation["id"], make_guest_headers(guest["id"])),
        expected_status=200,
    )
    assert fetched["status"] == "CONFIRMED"


def test_fk_not_found_unknown_dining_plan_on_reservation_create(api):
    """PRD §2.8: "then resolution of body-referenced foreign keys such as guest_id,
    restaurant_id, park_session_id, dining_plan_id, and reservation_id
    (ERR_FK_NOT_FOUND)"

    Design: Corner/errors/error_err_fk_not_found_unknown_dining_plan_on_reservation_create
    """
    set_clock("2026-01-15T12:00:00Z")
    guest = create_guest(email="fk_corner@x.com")
    restaurant = create_restaurant(name="FK Rest", park_code="EPCOT")
    ps = create_park_session(guest["id"], park_code="EPCOT", visit_date="2026-02-15")
    payload = create_reservation_payload(
        guest_id=guest["id"],
        restaurant_id=restaurant["id"],
        park_session_id=ps["id"],
        dining_plan_id="00000000-0000-4000-8000-000000000000",
        slot_start_utc="2026-02-15T18:00:00Z",
        party_size=1,
    )
    res = api.create_reservation(payload, make_guest_headers(guest["id"]))
    validate_error(res, ApiErrorId.ERR_FK_NOT_FOUND, expected_status=404)


def test_plan_not_covering_when_plan_expired_before_slot(api):
    """PRD §3.4: "The DiningPlan must additionally be in ACTIVE status and must
    cover the slot — its valid_from must be at or before slot_start_utc and
    slot_start_utc must be strictly before valid_until; coverage failure raises
    ERR_PLAN_NOT_COVERING."

    Design: Corner/errors/error_err_plan_not_covering_when_plan_expired_at_slot
    """
    set_clock("2026-01-15T12:00:00Z")
    guest = create_guest(email="pnc_corner@x.com")
    restaurant = create_restaurant(name="PNC Rest", park_code="EPCOT")
    # Plan valid_until 2026-02-10 — does NOT cover slot at 2026-02-15.
    dp = create_dining_plan(
        guest["id"],
        valid_from="2026-01-01T00:00:00Z",
        valid_until="2026-02-10T00:00:00Z",
    )
    ps = create_park_session(guest["id"], park_code="EPCOT", visit_date="2026-02-15")
    pending = create_pending_reservation(
        guest, restaurant, ps, dp,
        slot_start_utc="2026-02-15T18:00:00Z", party_size=1,
    )
    res = api.confirm_reservation(pending["id"], make_guest_headers(guest["id"]))
    validate_error(res, ApiErrorId.ERR_PLAN_NOT_COVERING, expected_status=409)


def test_party_size_patch_infeasible_when_capacity_exceeded(api):
    """PRD §3.4: "The patch re-validates two things: the new party_size must not
    cause the slot to exceed capacity_per_slot after accounting for the seats
    already counted by this reservation, and on a CONFIRMED reservation the
    implied credit-hold delta must not deplete the plan's
    (table_service_credits_remaining - table_service_credits_held) budget. Either
    failure produces ERR_PARTY_SIZE_PATCH_INFEASIBLE."

    Design: Corner/errors/error_err_party_size_patch_infeasible_when_capacity_exceeded
    """
    set_clock("2026-01-15T12:00:00Z")
    # capacity_per_slot=4; guest A confirms party_size=2; guest B confirms
    # party_size=1 at same slot. Slot total = 3 confirmed seats. Guest B patch
    # to 4 → would need 2 (A) + 4 (B) = 6 > 4.
    restaurant = create_restaurant(name="Rcap", park_code="EPCOT", capacity_per_slot=4)
    guest_a = create_guest(email="cap_a@x.com")
    dp_a = create_dining_plan(guest_a["id"], table_service_credits_initial=5)
    ps_a = create_park_session(guest_a["id"], park_code="EPCOT", visit_date="2026-02-15")
    pending_a = create_pending_reservation(
        guest_a, restaurant, ps_a, dp_a,
        slot_start_utc="2026-02-15T18:00:00Z", party_size=2,
    )
    confirm_reservation(pending_a, guest_a["id"])

    guest_b = create_guest(email="cap_b@x.com")
    dp_b = create_dining_plan(guest_b["id"], tier="DELUXE", table_service_credits_initial=20)
    ps_b = create_park_session(guest_b["id"], park_code="EPCOT", visit_date="2026-02-15")
    pending_b = create_pending_reservation(
        guest_b, restaurant, ps_b, dp_b,
        slot_start_utc="2026-02-15T18:00:00Z", party_size=1,
    )
    confirm_reservation(pending_b, guest_b["id"])

    res = api.patch_party_size(
        pending_b["id"],
        patch_party_size_payload(party_size=4),
        make_guest_headers(guest_b["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PARTY_SIZE_PATCH_INFEASIBLE, expected_status=422)
