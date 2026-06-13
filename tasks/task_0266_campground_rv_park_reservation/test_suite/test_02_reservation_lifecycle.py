"""Reservation lifecycle: the two independent status dimensions, valid and
invalid transitions, terminal lockdown, and immediate-consistency reads.

Covers difficulty queue non_linear_state_machine (reservation parallel dims)
and corner state_machines / consistency_model claims.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    make_guest_headers,
    make_operator_headers,
    create_payment_payload,
    ApiErrorId,
    setup_base_scenario,
    create_reservation,
    create_deposit_paid_reservation,
    create_confirmed_reservation,
    create_cancelled_reservation,
    get_reservation,
)

OP = make_operator_headers()


# ===========================================================================
# Difficulty: non_linear_state_machine /
#   reservation_parallel_payment_and_reservation_dimensions
# ===========================================================================
def test_deposit_advances_payment_status_while_still_requested(api):
    """PRD §3.7: "A guest records a deposit, moving an `UNPAID` reservation to
    `DEPOSIT_PAID`; this is permitted only while `payment_status` is `UNPAID`,
    and the deposit's `amount_cents` must equal the reservation's
    `deposit_due_cents`."
    PRD §3.7: "The `payment_status` dimension advances independently of the
    booking lifecycle."

    Design: Difficulty/non_linear_state_machine/reservation_parallel_payment_and_reservation_dimensions
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30})
    res = create_reservation(site, guest, "2026-08-01", "2026-08-11")
    resp = api.create_payment(
        res["id"], create_payment_payload("DEPOSIT", res["deposit_due_cents"]),
        make_guest_headers(guest["id"]))
    validate_success(resp, expected_status=201)
    updated = get_reservation(res["id"])
    # payment dimension advanced, booking dimension untouched.
    assert updated["payment_status"] == "DEPOSIT_PAID"
    assert updated["reservation_status"] == "REQUESTED"


def test_new_reservation_starts_requested_and_unpaid(api):
    """PRD §3.5: "at creation begins life with `reservation_status` `REQUESTED`
    and `payment_status` `UNPAID`."

    Design: Difficulty/non_linear_state_machine/reservation_parallel_payment_and_reservation_dimensions
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30})
    res = create_reservation(site, guest, "2026-08-01", "2026-08-11")
    assert res["reservation_status"] == "REQUESTED"
    assert res["payment_status"] == "UNPAID"


# ===========================================================================
# Corner: entities / reservation_system_fields_generated_input_ignored
# ===========================================================================
def test_reservation_system_fields_set_by_server(api):
    """PRD §3.5: "at creation begins life with `reservation_status` `REQUESTED`
    and `payment_status` `UNPAID`."
    PRD §2.4: "a `version`, an integer that starts at 1 on creation"

    Design: Corner/entities/reservation_system_fields_generated_input_ignored
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30})
    res = create_reservation(site, guest, "2026-08-01", "2026-08-11")
    assert res["reservation_status"] == "REQUESTED"
    assert res["payment_status"] == "UNPAID"
    assert res["version"] == 1


# ===========================================================================
# Corner: state_machines / confirm_from_already_confirmed_returns_invalid_state
# ===========================================================================
def test_confirm_already_confirmed_reservation_rejected(api):
    """PRD §3.5: "Any of these transitions attempted from a state where it is not
    defined is rejected with `ERR_INVALID_STATE`."
    PRD §3.5: "A guest confirms a `REQUESTED` reservation, moving it to
    `CONFIRMED`. Confirmation is permitted only when the reservation is
    `REQUESTED`"

    Design: Corner/state_machines/confirm_from_already_confirmed_returns_invalid_state
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30})
    confirmed = create_confirmed_reservation(site, guest, "2026-08-01", "2026-08-11")
    resp = api.confirm_reservation(confirmed["id"], make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner: state_machines / check_in_from_requested_without_confirm_returns_invalid_state
# ===========================================================================
def test_check_in_from_requested_rejected(api):
    """PRD §3.5: "An operator checks a guest in, moving a `CONFIRMED` reservation
    to `CHECKED_IN`; this requires the reservation to be `CONFIRMED`"
    PRD §3.5: "Any of these transitions attempted from a state where it is not
    defined is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/check_in_from_requested_without_confirm_returns_invalid_state
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-08-02T12:00:00Z", with_policy=False,
        site_overrides={"max_length_of_stay_nights": 30})
    res = create_reservation(site, guest, "2026-08-01", "2026-08-11")
    resp = api.check_in_reservation(res["id"], OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner: state_machines / terminal_cancelled_reservation_cannot_confirm
# ===========================================================================
def test_confirm_on_cancelled_reservation_rejected(api):
    """PRD §3.5: "A guest (or the system, during a site retirement) may cancel a
    reservation that is `REQUESTED` or `CONFIRMED`, moving it to the terminal
    `CANCELLED` state"
    PRD §3.5: "Any of these transitions attempted from a state where it is not
    defined is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminal_cancelled_reservation_cannot_confirm
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30})
    cancelled = create_cancelled_reservation(site, guest, "2026-08-01", "2026-08-11")
    assert cancelled["reservation_status"] == "CANCELLED"
    resp = api.confirm_reservation(cancelled["id"], make_guest_headers(guest["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner: consistency_model / confirm_recompute_visible_same_response
# ===========================================================================
def test_confirm_returns_recomputed_reservation_in_same_response(api):
    """PRD §3.5: "Confirmation freezes the loyalty discount from the acting
    guest's spend tier onto `discount_cents`, recomputes `total_due_cents` and
    `deposit_due_cents`, and bumps both the site's `version` and the
    reservation's `version`."
    PRD §3.6: "Finally `deposit_due_cents` is `total_due_cents` multiplied by the
    park's `deposit_pct`, rounded half up to whole cents, and frozen at
    confirmation time."

    Design: Corner/consistency_model/confirm_recompute_visible_same_response
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30})
    res = create_deposit_paid_reservation(site, guest, "2026-08-01", "2026-08-11")
    resp = api.confirm_reservation(res["id"], make_guest_headers(guest["id"]))
    data = validate_success(resp, expected_status=200)
    assert data["reservation_status"] == "CONFIRMED"
    # total 48600, deposit_pct 0.30 -> round_half_up(14580)=14580 in the response.
    assert data["deposit_due_cents"] == 14580
