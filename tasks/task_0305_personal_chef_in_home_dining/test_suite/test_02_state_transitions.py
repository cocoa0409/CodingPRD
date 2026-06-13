"""Booking, GroceryRun, Chef, RescheduleRequest, and RecurringPlan state transitions:
invalid transitions, terminal lockdown, precondition enforcement, and a side effect.

Queue B / Corner / state_machines.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_menu_payload, create_recurring_plan_payload,
    admin_headers, make_chef_headers, make_client_headers,
    pin_clock, create_chef, create_client,
    setup_confirmed_booking, setup_completed_booking, setup_recurring_plan,
    propose_reschedule,
)


def test_confirm_already_confirmed_booking_returns_invalid_state(api):
    """PRD §3.3: "Confirmation is the chef's decision to take a `REQUESTED` booking,
    advancing its `lifecycle_status` from `REQUESTED` to `CONFIRMED`."
    PRD §2.9: "(6) the target resource is in a legal source state for the requested
    transition ... (`ERR_INVALID_STATE` ...)".

    Design: Corner/state_machines/confirm_already_confirmed_booking_returns_invalid_state
    """
    chef, menu, zone, client, booking = setup_confirmed_booking()
    fresh_chef = validate_success(api.get_chef(chef["id"], make_chef_headers(chef["id"])), 200)
    res = api.confirm_booking(
        booking["id"], {"expected_chef_version": fresh_chef["version"]}, make_chef_headers(chef["id"])
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_complete_before_paid_in_full_returns_balance_outstanding(api):
    """PRD §3.6: "A chef completes an `IN_PREP` booking it owns only when its
    `payment_status` is `PAID_IN_FULL` (`ERR_BALANCE_OUTSTANDING`); completion moves
    `lifecycle_status` to `COMPLETED`, a terminal state."

    Design: Corner/state_machines/complete_before_paid_in_full_returns_balance_outstanding
    """
    # IN_PREP with deposit paid + grocery finalized, balance NOT paid.
    chef, menu, zone, client, booking = setup_confirmed_booking()
    from test_helpers import pay_deposit, open_grocery_run, finalize_grocery_run
    pay_deposit(client["id"], booking["id"], 26196)
    run = open_grocery_run(chef["id"], booking["id"], [
        {"label": "a", "actual_cost_cents": 8001},
        {"label": "b", "actual_cost_cents": 8001},
        {"label": "c", "actual_cost_cents": 7998},
    ])
    finalize_grocery_run(chef["id"], run["id"])
    validate_success(api.start_prep_booking(booking["id"], make_chef_headers(chef["id"])), 200)
    res = api.complete_booking(booking["id"], make_chef_headers(chef["id"]))
    validate_error(res, "ERR_BALANCE_OUTSTANDING", expected_status=402)


def test_start_prep_without_finalized_grocery_run_rejected(api):
    """PRD §3.6: "A chef starts prep on a `CONFIRMED` booking it owns, provided a
    finalized grocery run exists (`ERR_GROCERY_RUN_NOT_FINALIZED`); this moves
    `lifecycle_status` from `CONFIRMED` to `IN_PREP`."

    Design: Corner/state_machines/start_prep_without_finalized_grocery_run_rejected
    """
    chef, menu, zone, client, booking = setup_confirmed_booking(
        booking_overrides={"event_start_utc": "2026-08-16T18:00:00Z",
                           "event_end_utc": "2026-08-16T22:00:00Z"}
    )
    res = api.start_prep_booking(booking["id"], make_chef_headers(chef["id"]))
    validate_error(res, "ERR_GROCERY_RUN_NOT_FINALIZED", expected_status=409)


def test_cancel_terminal_completed_booking_returns_invalid_state(api):
    """PRD §3.6: "completion moves `lifecycle_status` to `COMPLETED`, a terminal state."
    PRD §3.8: "A client may cancel a booking it owns while that booking is `REQUESTED`,
    `CONFIRMED`, or `IN_PREP` ...".
    PRD §2.9: "(6) the target resource is in a legal source state for the requested
    transition ... (`ERR_INVALID_STATE` ...)".

    Design: Corner/state_machines/cancel_terminal_completed_booking_returns_invalid_state
    """
    chef, menu, zone, client, booking = setup_completed_booking(
        booking_overrides={"event_start_utc": "2026-08-17T18:00:00Z",
                           "event_end_utc": "2026-08-17T22:00:00Z"}
    )
    assert booking["lifecycle_status"] == "COMPLETED"
    res = api.cancel_booking(booking["id"], make_client_headers(client["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_chef_activate_without_listed_menu_returns_no_listed_menu(api):
    """PRD §3.1: "Activation is allowed only when the chef has published at least one menu
    — that is, at least one `MenuPackage` belonging to the chef whose `is_listed` is true
    (otherwise `ERR_NO_LISTED_MENU`) — and has declared at least one travel zone
    (otherwise `ERR_NO_TRAVEL_ZONE`)."

    Design: Corner/state_machines/chef_activate_without_listed_menu_returns_no_listed_menu
    """
    pin_clock()
    chef = create_chef(chef_overrides={"display_name": "Chef NL"})
    ch = make_chef_headers(chef["id"])
    # Unlisted menu (no publish) + a travel zone present, so only ERR_NO_LISTED_MENU applies.
    validate_success(api.create_menu(create_menu_payload(chef["id"], title="Unlisted"), ch), 201)
    validate_success(api.create_travel_zone({
        "chef_id": chef["id"], "zone_code": "ZONE_A", "zip_prefixes": ["941"], "travel_fee_cents": 5000,
    }, ch), 201)
    res = api.activate_chef(chef["id"], ch)
    validate_error(res, "ERR_NO_LISTED_MENU", expected_status=409)


def test_reschedule_accept_withdraws_sibling_proposals(api):
    """PRD §3.9: "Acceptance updates the booking's `event_start_utc`, `event_end_utc`, and
    `event_date` to the proposed window ...". PRD §3.9: "The request moves to `ACCEPTED`
    (terminal), and any sibling `PROPOSED` requests on the same booking are moved to
    `WITHDRAWN`."

    Design: Corner/state_machines/reschedule_accept_withdraws_sibling_proposals
    """
    chef, menu, zone, client, booking = setup_confirmed_booking(
        chef_overrides={"prep_buffer_minutes": 30},
        booking_overrides={"event_start_utc": "2026-08-18T18:00:00Z",
                           "event_end_utc": "2026-08-18T22:00:00Z"},
    )
    rr1 = propose_reschedule(client["id"], "CLIENT", booking["id"],
                             "2026-08-19T18:00:00Z", "2026-08-19T22:00:00Z")
    rr2 = propose_reschedule(client["id"], "CLIENT", booking["id"],
                             "2026-08-20T18:00:00Z", "2026-08-20T22:00:00Z")
    accepted = validate_success(api.accept_reschedule_request(rr1["id"], make_chef_headers(chef["id"])), 200)
    assert accepted["status"] == "ACCEPTED"
    sibling = validate_success(api.get_reschedule_request(rr2["id"], make_chef_headers(chef["id"])), 200)
    assert sibling["status"] == "WITHDRAWN"
    moved = validate_success(api.get_booking(booking["id"], make_chef_headers(chef["id"])), 200)
    assert moved["event_start_utc"] == "2026-08-19T18:00:00Z"


def test_existence_check_before_state_on_confirm_nonexistent_booking(api):
    """PRD §2.8: "When an endpoint addresses a resource by a path identifier, that
    identifier is validated first; an unknown id yields the appropriate not-found error
    (`ERR_CHEF_NOT_FOUND`, `ERR_MENU_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`,
    `ERR_CLIENT_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
    `ERR_RESCHEDULE_NOT_FOUND`, or `ERR_GROCERY_RUN_NOT_FOUND`, all HTTP 404) before any
    state or business rule is evaluated."

    Design: Corner/state_machines/existence_check_before_state_on_confirm_nonexistent_booking
    """
    from test_helpers import NONEXISTENT_BOOKING_ID
    pin_clock()
    chef = create_chef(chef_overrides={"display_name": "Chef EX"})
    res = api.confirm_booking(
        NONEXISTENT_BOOKING_ID, {"expected_chef_version": chef["version"]},
        make_chef_headers(chef["id"]),
    )
    validate_error(res, "ERR_BOOKING_NOT_FOUND", expected_status=404)


def test_generate_occurrence_on_cancelled_plan_rejected(api):
    """PRD §3.10: "A plan may be cancelled by its owner from either `ACTIVE` or `PAUSED`,
    moving its `status` to `CANCELLED` (terminal); no further occurrences may ever be
    generated from a cancelled plan."

    Design: Corner/state_machines/generate_occurrence_on_cancelled_plan_rejected
    """
    chef, menu, client, plan = setup_recurring_plan(publish_menu=False, with_zone=False)
    validate_success(api.cancel_recurring_plan(plan["id"], make_client_headers(client["id"])), 200)
    res = api.generate_occurrence(plan["id"], {"occurrence_date": "2026-08-04"},
                                  make_client_headers(client["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
