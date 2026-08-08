"""Booking creation gates, the parallel screening/stay dimensions, and confirm gating."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId, fixtures,
)

PM = TEST_USERS["property_manager_headers"]


def test_screening_advances_while_stay_stays_hold(api):
    """PRD §3.4: "Bookings use two independent status dimensions that evolve in parallel:
    `stay_status`, which begins at `HOLD`, and `screening_status`, which begins at `PENDING`."
    PRD §3.4: "A decision of `APPROVED` moves `screening_status` from `PENDING` to `APPROVED`,
    provided the guest is not `BANNED`".

    Design: Difficulty/non_linear_state_machine/booking_parallel_screening_and_stay_dimensions
    """
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    listed = fixtures.create_listed_property(api)
    guest = fixtures.create_guest(api)
    b = fixtures.create_booking(api, listed["property"]["id"], guest["id"],
                                "2026-07-01T00:00:00Z", "2026-07-04T00:00:00Z")
    data = get_success_data(api.screen_booking(b["id"], {"decision": "APPROVED"}, PM))
    assert data["screening_status"] == "APPROVED", f"got {data['screening_status']}"
    assert data["stay_status"] == "HOLD", f"stay dimension must stay HOLD, got {data['stay_status']}"


def test_confirm_advances_stay_after_screening_clears(api):
    """PRD §3.5: "Confirming a booking advances `stay_status` from `HOLD` to `CONFIRMED`, but
    only when `screening_status` is `APPROVED`".

    Design: Difficulty/non_linear_state_machine/booking_parallel_screening_and_stay_dimensions
    """
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    listed = fixtures.create_listed_property(api)
    guest = fixtures.create_guest(api)
    b = fixtures.create_booking(api, listed["property"]["id"], guest["id"],
                                "2026-07-01T00:00:00Z", "2026-07-04T00:00:00Z")
    fixtures.screen_booking(api, b["id"], "APPROVED")
    data = get_success_data(api.confirm_booking(b["id"], PM))
    assert data["stay_status"] == "CONFIRMED", f"got {data['stay_status']}"
    assert data["screening_status"] == "APPROVED", f"got {data['screening_status']}"


def test_confirm_from_cancelled_returns_invalid_state(api):
    """PRD §3.5: "Confirming a booking advances `stay_status` from `HOLD` to `CONFIRMED`".
    PRD §2.6: "falling back to the generic `ERR_INVALID_STATE` (409) for any transition
    attempted from a state that does not permit it."

    Design: Corner/state_machines/confirm_from_cancelled_returns_invalid_state
    """
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    listed = fixtures.create_listed_property(api)
    guest = fixtures.create_guest(api)
    b = fixtures.create_booking(api, listed["property"]["id"], guest["id"],
                                "2026-07-01T00:00:00Z", "2026-07-04T00:00:00Z")
    get_success_data(api.cancel_booking(b["id"], PM))  # stay_status -> CANCELLED
    resp = api.confirm_booking(b["id"], PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_booking_on_unlisted_property_not_bookable(api):
    """PRD §3.4: "At creation the property must be `LISTED` (else `ERR_PROPERTY_NOT_BOOKABLE`)".

    Design: Corner/validations/booking_on_unlisted_property_not_bookable
    """
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    owner = fixtures.create_owner(api)
    prop = fixtures.create_property(api, owner["id"])  # ONBOARDING, never listed
    guest = fixtures.create_guest(api)
    resp = api.create_booking(
        {"property_id": prop["id"], "guest_id": guest["id"],
         "check_in": "2026-07-01T00:00:00Z", "check_out": "2026-07-04T00:00:00Z"}, PM)
    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_BOOKABLE.value)


def test_confirm_without_screening_approved_rejected(api):
    """PRD §3.5: "Confirming a booking advances `stay_status` from `HOLD` to `CONFIRMED`, but
    only when `screening_status` is `APPROVED`; a confirm attempted otherwise is rejected with
    `ERR_SCREENING_NOT_APPROVED`."

    Design: Corner/validations/confirm_without_screening_approved_rejected
    """
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    listed = fixtures.create_listed_property(api)
    guest = fixtures.create_guest(api)
    b = fixtures.create_booking(api, listed["property"]["id"], guest["id"],
                                "2026-07-01T00:00:00Z", "2026-07-04T00:00:00Z")
    resp = api.confirm_booking(b["id"], PM)  # screening still PENDING
    validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_APPROVED.value)


def test_booking_for_banned_guest_rejected(api):
    """PRD §3.1: "a banned guest may neither create a booking nor be approved during
    screening, and either attempt is rejected with `ERR_GUEST_BANNED`."

    Design: Corner/validations/booking_for_banned_guest_rejected
    """
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    listed = fixtures.create_listed_property(api)
    guest = fixtures.create_guest(api, banned=True)
    resp = api.create_booking(
        {"property_id": listed["property"]["id"], "guest_id": guest["id"],
         "check_in": "2026-07-01T00:00:00Z", "check_out": "2026-07-04T00:00:00Z"}, PM)
    validate_error(resp, ApiErrorId.ERR_GUEST_BANNED.value)
