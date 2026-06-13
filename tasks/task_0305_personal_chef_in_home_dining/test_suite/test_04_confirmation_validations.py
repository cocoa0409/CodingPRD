"""The confirmation cascade: validation ordering, cross-entity state gates,
buffer-widened temporal overlap, daily capacity, party-size boundary, equipment,
and grocery-run finalize preconditions.

Queue A / Difficulty: priority_pair_validation_conflict, cross_entity_state_dependency,
resource_temporal_overlap, boundary_precision_check (party-size).
Queue B / Corner: validations.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, get_success_data,
    make_chef_headers, make_client_headers, admin_headers,
    create_menu_payload, create_travel_zone_payload, create_booking_payload,
    pin_clock, create_chef, create_client, create_active_chef, create_blackout,
    setup_requested_booking, setup_confirmed_booking, confirm_booking,
    open_grocery_run,
)


# ─── Difficulty / priority_pair: state (409) beats allergen (422) ────────────

def test_confirm_declined_booking_returns_invalid_state_not_allergen(api):
    """PRD §3.3: "Confirmation is the chef's decision to take a `REQUESTED` booking ...".
    PRD §2.9: "(6) the target resource is in a legal source state for the requested
    transition ... (`ERR_INVALID_STATE` ...). Beyond that point, the confirm operation
    layers further business checks whose relative order is given in §3.3 ...".
    PRD §3.3: "then allergen safety — the client's `allergen_restrictions` and the menu's
    `allergen_tags` must share no common token (`ERR_ALLERGEN_CONFLICT`) ...".

    Design: Difficulty/priority_pair_validation_conflict/terminal_state_beats_allergen_safety_on_confirm
    """
    pin_clock()
    chef, menu, zone = create_active_chef(
        chef_overrides={"display_name": "Chef PP1"},
        menu_overrides={"title": "Nutty", "allergen_tags": ["PEANUT"]},
    )
    client = create_client(client_overrides={"allergen_restrictions": ["PEANUT"]})
    booking = get_success_data(api.create_booking(
        create_booking_payload(chef["id"], client["id"], menu["id"], service_zip="94140",
                               event_start_utc="2026-09-01T18:00:00Z",
                               event_end_utc="2026-09-01T22:00:00Z"),
        make_client_headers(client["id"])))
    # Decline first so the booking is terminal (DECLINED) AND has an allergen conflict.
    # Declining recomputes the chef's reliability scores (PRD §3.7), and recomputing a
    # derived field is a mutation that bumps the chef's version (PRD §2.4). Re-read the
    # chef so the version guard (PRD §2.5, evaluated first) passes and the state check
    # is what trips — isolating the "state beats allergen" ordering under test.
    validate_success(api.decline_booking(booking["id"], make_chef_headers(chef["id"])), 200)
    fresh = get_success_data(api.get_chef(chef["id"], make_chef_headers(chef["id"])))
    res = api.confirm_booking(booking["id"], {"expected_chef_version": fresh["version"]},
                              make_chef_headers(chef["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_confirm_declined_booking_state_check_precedes_business(api):
    """PRD §2.9: "(6) the target resource is in a legal source state for the requested
    transition ... with the version check evaluated before any later business check
    (`ERR_INVALID_STATE` ...)." PRD §3.3: "A chef may instead decline a `REQUESTED`
    booking ... Declining moves `lifecycle_status` to `DECLINED`, a terminal state."

    Design: Difficulty/priority_pair_validation_conflict/terminal_state_beats_allergen_safety_on_confirm
    """
    pin_clock()
    chef, menu, zone = create_active_chef(
        chef_overrides={"display_name": "Chef PP1b"},
        menu_overrides={"title": "Nutty2", "allergen_tags": ["SHELLFISH"]},
    )
    client = create_client(client_overrides={"allergen_restrictions": ["SHELLFISH"]})
    booking = get_success_data(api.create_booking(
        create_booking_payload(chef["id"], client["id"], menu["id"], service_zip="94141",
                               event_start_utc="2026-09-01T18:00:00Z",
                               event_end_utc="2026-09-01T22:00:00Z"),
        make_client_headers(client["id"])))
    # Decline bumps the chef's version via reliability recompute (PRD §3.7 + §2.4);
    # re-read the chef so the §2.5 version guard passes and the §2.9 state check trips.
    validate_success(api.decline_booking(booking["id"], make_chef_headers(chef["id"])), 200)
    fresh = get_success_data(api.get_chef(chef["id"], make_chef_headers(chef["id"])))
    res = api.confirm_booking(booking["id"], {"expected_chef_version": fresh["version"]},
                              make_chef_headers(chef["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Difficulty / priority_pair: temporal conflict on confirm ────────────────

def test_confirm_overlapping_blackout_returns_time_conflict(api):
    """PRD §3.3: "then time conflict — the booking's occupied window, running from
    `event_start_utc` minus the chef's `prep_buffer_minutes` up to `event_end_utc`, must
    not overlap any `HELD` availability block of the chef under the half-open semantics of
    §2.7 (`ERR_CHEF_TIME_CONFLICT`) ...".

    Design: Difficulty/priority_pair_validation_conflict/time_conflict_beats_deposit_mismatch_ordering
    """
    pin_clock()
    chef = create_chef(chef_overrides={"display_name": "Chef PP2", "prep_buffer_minutes": 90})
    ch = make_chef_headers(chef["id"])
    menu = get_success_data(api.create_menu(create_menu_payload(chef["id"]), ch))
    get_success_data(api.publish_menu(menu["id"], ch))
    get_success_data(api.create_travel_zone(create_travel_zone_payload(chef["id"]), ch))
    create_blackout(chef["id"], "2026-09-05T17:00:00Z", "2026-09-05T23:00:00Z")
    chef = get_success_data(api.activate_chef(chef["id"], ch))
    client = create_client()
    booking = get_success_data(api.create_booking(
        create_booking_payload(chef["id"], client["id"], menu["id"], service_zip="94145",
                               event_start_utc="2026-09-05T19:00:00Z",
                               event_end_utc="2026-09-05T22:00:00Z"),
        make_client_headers(client["id"])))
    res = api.confirm_booking(booking["id"], {"expected_chef_version": chef["version"]}, ch)
    validate_error(res, "ERR_CHEF_TIME_CONFLICT", expected_status=409)


def test_confirm_window_inside_blackout_returns_time_conflict(api):
    """PRD §2.7: "Two intervals overlap when one starts strictly before the other ends and
    ends strictly after the other starts ...". PRD §3.3: "then time conflict — the
    booking's occupied window, running from `event_start_utc` minus the chef's
    `prep_buffer_minutes` up to `event_end_utc`, must not overlap any `HELD` availability
    block of the chef under the half-open semantics of §2.7 (`ERR_CHEF_TIME_CONFLICT`) ...".

    Design: Difficulty/priority_pair_validation_conflict/time_conflict_beats_deposit_mismatch_ordering
    """
    pin_clock()
    chef = create_chef(chef_overrides={"display_name": "Chef PP2b", "prep_buffer_minutes": 30})
    ch = make_chef_headers(chef["id"])
    menu = get_success_data(api.create_menu(create_menu_payload(chef["id"]), ch))
    get_success_data(api.publish_menu(menu["id"], ch))
    get_success_data(api.create_travel_zone(create_travel_zone_payload(chef["id"]), ch))
    create_blackout(chef["id"], "2026-09-06T17:00:00Z", "2026-09-06T23:00:00Z")
    chef = get_success_data(api.activate_chef(chef["id"], ch))
    client = create_client()
    booking = get_success_data(api.create_booking(
        create_booking_payload(chef["id"], client["id"], menu["id"], service_zip="94146",
                               event_start_utc="2026-09-06T18:00:00Z",
                               event_end_utc="2026-09-06T21:00:00Z"),
        make_client_headers(client["id"])))
    res = api.confirm_booking(booking["id"], {"expected_chef_version": chef["version"]}, ch)
    validate_error(res, "ERR_CHEF_TIME_CONFLICT", expected_status=409)


# ─── Difficulty / cross_entity_state_dependency ──────────────────────────────

def test_confirm_requires_chef_active(api):
    """PRD §3.3: "then the cross-entity state gate that the chef must be `ACTIVE`
    (`ERR_CHEF_NOT_ACTIVE`) ...". PRD §3.1: "Suspension is a forward-looking gate: it
    blocks new booking confirmations against the chef but does not disturb bookings already
    `CONFIRMED` or in progress."

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_chef_active
    """
    chef, menu, zone, client, booking = setup_requested_booking(
        chef_overrides={"display_name": "Chef CE1"},
        booking_overrides={"service_zip": "94160", "event_start_utc": "2026-09-12T18:00:00Z",
                           "event_end_utc": "2026-09-12T22:00:00Z"},
    )
    validate_success(api.suspend_chef(chef["id"], admin_headers()), 200)
    fresh = get_success_data(api.get_chef(chef["id"], make_chef_headers(chef["id"])))
    res = api.confirm_booking(booking["id"], {"expected_chef_version": fresh["version"]},
                              make_chef_headers(chef["id"]))
    validate_error(res, "ERR_CHEF_NOT_ACTIVE", expected_status=409)


def test_grocery_run_open_requires_booking_confirmed(api):
    """PRD §3.5: "Once a booking is `CONFIRMED`, the chef opens a grocery run for it."
    PRD §4 endpoint table: "Open a grocery run for a CONFIRMED booking".

    Design: Difficulty/cross_entity_state_dependency/grocery_run_open_requires_booking_confirmed
    """
    chef, menu, zone, client, booking = setup_requested_booking(
        chef_overrides={"display_name": "Chef CE2"},
        booking_overrides={"service_zip": "94165", "event_start_utc": "2026-09-14T18:00:00Z",
                           "event_end_utc": "2026-09-14T22:00:00Z"},
    )
    res = api.create_grocery_run(
        {"booking_id": booking["id"], "line_items": [{"label": "x", "actual_cost_cents": 5000}]},
        make_chef_headers(chef["id"]),
    )
    validate_error(res, "ERR_BOOKING_NOT_CONFIRMED", expected_status=409)


def test_confirm_suspended_chef_then_reactivate_allows_confirm(api):
    """PRD §3.3: "then the cross-entity state gate that the chef must be `ACTIVE`
    (`ERR_CHEF_NOT_ACTIVE`) ...". PRD §3.1: "A `SUSPENDED` chef may be returned to `ACTIVE`
    by a `PlatformAdmin`; that re-activation requires that the chef still has at least one
    listed menu (`ERR_NO_LISTED_MENU`) and likewise bumps `version`."

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_chef_active
    """
    chef, menu, zone, client, booking = setup_requested_booking(
        chef_overrides={"display_name": "Chef CE1b"},
        booking_overrides={"service_zip": "94161", "event_start_utc": "2026-09-13T18:00:00Z",
                           "event_end_utc": "2026-09-13T22:00:00Z"},
    )
    validate_success(api.suspend_chef(chef["id"], admin_headers()), 200)
    reactivated = validate_success(api.activate_chef(chef["id"], admin_headers()), 200)
    booking2 = confirm_booking(chef["id"], booking["id"], reactivated["version"])
    assert booking2["lifecycle_status"] == "CONFIRMED"


def test_grocery_finalize_requires_booking_confirmed_state(api):
    """PRD §3.5: "Finalizing the run is the chef's action that locks the receipts and
    re-pins the quote to real costs. It is allowed only when the acting chef owns the
    parent booking (`ERR_NOT_RESOURCE_OWNER`), the parent booking is `CONFIRMED`
    (`ERR_BOOKING_NOT_CONFIRMED`), and the run has at least one line item
    (`ERR_GROCERY_RUN_EMPTY`)."

    Design: Difficulty/cross_entity_state_dependency/grocery_run_open_requires_booking_confirmed
    """
    # Confirm, open a run, cancel the booking (run -> VOIDED), then attempt finalize.
    chef, menu, zone, client, booking = setup_confirmed_booking(
        booking_overrides={"service_zip": "94166", "event_start_utc": "2026-09-15T18:00:00Z",
                           "event_end_utc": "2026-09-15T22:00:00Z"}
    )
    run = open_grocery_run(chef["id"], booking["id"], [{"label": "x", "actual_cost_cents": 5000}])
    validate_success(api.cancel_booking(booking["id"], make_client_headers(client["id"])), 200)
    res = api.finalize_grocery_run(run["id"], make_chef_headers(chef["id"]))
    validate_error(res, "ERR_BOOKING_NOT_CONFIRMED", expected_status=409)


# ─── Difficulty / resource_temporal_overlap ──────────────────────────────────

def test_confirm_buffer_widened_overlap_with_held_blackout(api):
    """PRD §2.7: "The occupied window of a booking is widened by the chef's prep time: a
    `BOOKING_HOLD` runs from the booking's `event_start_utc` minus the chef's
    `prep_buffer_minutes` up to the booking's `event_end_utc`." PRD §3.3: "then time
    conflict — the booking's occupied window, running from `event_start_utc` minus the
    chef's `prep_buffer_minutes` up to `event_end_utc`, must not overlap any `HELD`
    availability block of the chef under the half-open semantics of §2.7
    (`ERR_CHEF_TIME_CONFLICT`) ...".

    Design: Difficulty/resource_temporal_overlap/confirm_buffer_widened_overlap_with_held_blackout
    """
    pin_clock()
    chef = create_chef(chef_overrides={"display_name": "Chef TO1", "prep_buffer_minutes": 90})
    ch = make_chef_headers(chef["id"])
    menu = get_success_data(api.create_menu(create_menu_payload(chef["id"]), ch))
    get_success_data(api.publish_menu(menu["id"], ch))
    get_success_data(api.create_travel_zone(create_travel_zone_payload(chef["id"]), ch))
    # BLACKOUT 15:45-16:30; event 17:00 with 90-min buffer -> occupied start 15:30 overlaps.
    create_blackout(chef["id"], "2026-09-18T15:45:00Z", "2026-09-18T16:30:00Z")
    chef = get_success_data(api.activate_chef(chef["id"], ch))
    client = create_client()
    booking = get_success_data(api.create_booking(
        create_booking_payload(chef["id"], client["id"], menu["id"], service_zip="94170",
                               event_start_utc="2026-09-18T17:00:00Z",
                               event_end_utc="2026-09-18T20:00:00Z"),
        make_client_headers(client["id"])))
    res = api.confirm_booking(booking["id"], {"expected_chef_version": chef["version"]}, ch)
    validate_error(res, "ERR_CHEF_TIME_CONFLICT", expected_status=409)


def test_confirm_back_to_back_window_does_not_conflict(api):
    """PRD §2.7: "because the intervals are half-open, a block that ends exactly when
    another begins does **not** overlap it — back-to-back events are permitted." PRD §3.3:
    "then time conflict — the booking's occupied window, running from `event_start_utc`
    minus the chef's `prep_buffer_minutes` up to `event_end_utc`, must not overlap any
    `HELD` availability block of the chef under the half-open semantics of §2.7
    (`ERR_CHEF_TIME_CONFLICT`) ...".

    Design: Difficulty/resource_temporal_overlap/confirm_buffer_widened_overlap_with_held_blackout
    """
    pin_clock()
    chef = create_chef(chef_overrides={"display_name": "Chef TO1b", "prep_buffer_minutes": 90})
    ch = make_chef_headers(chef["id"])
    menu = get_success_data(api.create_menu(create_menu_payload(chef["id"]), ch))
    get_success_data(api.publish_menu(menu["id"], ch))
    get_success_data(api.create_travel_zone(create_travel_zone_payload(chef["id"]), ch))
    # BLACKOUT ends 15:30; event 17:00 with 90-min buffer -> occupied start exactly 15:30.
    # Half-open: block [.., 15:30) and occupied [15:30, ..) are back-to-back, no overlap.
    create_blackout(chef["id"], "2026-09-19T14:00:00Z", "2026-09-19T15:30:00Z")
    chef = get_success_data(api.activate_chef(chef["id"], ch))
    client = create_client()
    booking = get_success_data(api.create_booking(
        create_booking_payload(chef["id"], client["id"], menu["id"], service_zip="94171",
                               event_start_utc="2026-09-19T17:00:00Z",
                               event_end_utc="2026-09-19T20:00:00Z"),
        make_client_headers(client["id"])))
    confirmed = validate_success(
        api.confirm_booking(booking["id"], {"expected_chef_version": chef["version"]}, ch), 200)
    assert confirmed["lifecycle_status"] == "CONFIRMED"


def test_daily_capacity_aggregate_overlap_same_event_date(api):
    """PRD §3.3: "and finally daily capacity — the count of the chef's bookings in
    `CONFIRMED` or `IN_PREP` sharing the same `event_date` must be strictly less than the
    chef's `max_bookings_per_day` (`ERR_DAILY_CAPACITY_EXCEEDED`)."

    Design: Difficulty/resource_temporal_overlap/daily_capacity_aggregate_overlap_same_event_date
    """
    pin_clock()
    chef, menu, zone = create_active_chef(
        chef_overrides={"display_name": "Chef TO2", "prep_buffer_minutes": 30,
                        "max_bookings_per_day": 1},
    )
    ch = make_chef_headers(chef["id"])
    client = create_client()
    # First booking same date morning -> confirm (active_booking_count 1).
    b_a = get_success_data(api.create_booking(
        create_booking_payload(chef["id"], client["id"], menu["id"], service_zip="94175",
                               event_start_utc="2026-09-20T09:00:00Z",
                               event_end_utc="2026-09-20T12:00:00Z"),
        make_client_headers(client["id"])))
    confirmed_a = confirm_booking(chef["id"], b_a["id"], chef["version"])
    chef_after = get_success_data(api.get_chef(chef["id"], ch))
    # Second booking same date evening (no geometric overlap), still over the daily cap.
    b_b = get_success_data(api.create_booking(
        create_booking_payload(chef["id"], client["id"], menu["id"], service_zip="94175",
                               event_start_utc="2026-09-20T19:00:00Z",
                               event_end_utc="2026-09-20T22:00:00Z"),
        make_client_headers(client["id"])))
    res = api.confirm_booking(b_b["id"], {"expected_chef_version": chef_after["version"]}, ch)
    validate_error(res, "ERR_DAILY_CAPACITY_EXCEEDED", expected_status=409)


def test_daily_capacity_allows_different_event_date(api):
    """PRD §3.3: "and finally daily capacity — the count of the chef's bookings in
    `CONFIRMED` or `IN_PREP` sharing the same `event_date` must be strictly less than the
    chef's `max_bookings_per_day` (`ERR_DAILY_CAPACITY_EXCEEDED`)." PRD §3.3: "The system
    also derives `event_date`, the calendar date (formatted `YYYY-MM-DD` in UTC) taken from
    `event_start_utc`, which is the key used later for daily capacity."

    Design: Difficulty/resource_temporal_overlap/daily_capacity_aggregate_overlap_same_event_date
    """
    pin_clock()
    chef, menu, zone = create_active_chef(
        chef_overrides={"display_name": "Chef TO2b", "prep_buffer_minutes": 30,
                        "max_bookings_per_day": 1},
    )
    ch = make_chef_headers(chef["id"])
    client = create_client()
    b_a = get_success_data(api.create_booking(
        create_booking_payload(chef["id"], client["id"], menu["id"], service_zip="94176",
                               event_start_utc="2026-09-21T09:00:00Z",
                               event_end_utc="2026-09-21T12:00:00Z"),
        make_client_headers(client["id"])))
    confirm_booking(chef["id"], b_a["id"], chef["version"])
    chef_after = get_success_data(api.get_chef(chef["id"], ch))
    # Different event_date -> capacity count for that day is 0, confirm succeeds.
    b_b = get_success_data(api.create_booking(
        create_booking_payload(chef["id"], client["id"], menu["id"], service_zip="94176",
                               event_start_utc="2026-09-22T09:00:00Z",
                               event_end_utc="2026-09-22T12:00:00Z"),
        make_client_headers(client["id"])))
    confirmed_b = validate_success(
        api.confirm_booking(b_b["id"], {"expected_chef_version": chef_after["version"]}, ch), 200)
    assert confirmed_b["lifecycle_status"] == "CONFIRMED"


# ─── Difficulty / boundary_precision_check: party-size min boundary ──────────

def test_party_size_below_min_rejected(api):
    """PRD §3.3: "then party-size range — `party_size` must fall within the menu's
    `min_party_size` and `max_party_size`, inclusive on both ends
    (`ERR_PARTY_SIZE_OUT_OF_RANGE`) ...".

    Design: Difficulty/boundary_precision_check/party_size_below_min_rejected_at_min_boundary
    """
    # PRD §3.3 places the party-size range check at confirmation, not at booking
    # creation (creation only requires party_size >= 1). So a party-3 booking against a
    # min_party_size-4 menu is created REQUESTED, and the below-min rejection surfaces
    # when the chef confirms it.
    pin_clock()
    chef, menu, zone = create_active_chef(
        chef_overrides={"display_name": "Chef BP2"},
        menu_overrides={"title": "Min4", "min_party_size": 4},
    )
    client = create_client()
    booking = get_success_data(api.create_booking(
        create_booking_payload(chef["id"], client["id"], menu["id"], party_size=3,
                               service_zip="94155", event_start_utc="2026-09-10T18:00:00Z",
                               event_end_utc="2026-09-10T22:00:00Z"),
        make_client_headers(client["id"])))
    res = api.confirm_booking(booking["id"], {"expected_chef_version": chef["version"]},
                              make_chef_headers(chef["id"]))
    validate_error(res, "ERR_PARTY_SIZE_OUT_OF_RANGE", expected_status=422)


def test_party_size_at_min_boundary_accepted(api):
    """PRD §3.3: "then party-size range — `party_size` must fall within the menu's
    `min_party_size` and `max_party_size`, inclusive on both ends
    (`ERR_PARTY_SIZE_OUT_OF_RANGE`) ...".

    Design: Difficulty/boundary_precision_check/party_size_below_min_rejected_at_min_boundary
    """
    # party 4 == min_party_size 4 is inclusive, so confirm succeeds.
    chef, menu, zone, client, booking = setup_confirmed_booking(
        menu_overrides={"title": "Min4", "min_party_size": 4},
        booking_overrides={"party_size": 4, "service_zip": "94156",
                           "event_start_utc": "2026-09-11T18:00:00Z",
                           "event_end_utc": "2026-09-11T22:00:00Z"},
    )
    assert booking["lifecycle_status"] == "CONFIRMED"
    assert booking["party_size"] == 4


# ─── Corner / validations ────────────────────────────────────────────────────

def test_confirm_equipment_unavailable_rejected(api):
    """PRD §3.3: "then equipment — every token in the menu's `required_equipment` must also
    appear in the chef's `equipment_inventory`, i.e. the required set is a subset of what
    the chef carries (`ERR_EQUIPMENT_UNAVAILABLE`) ...".

    Design: Corner/validations/confirm_equipment_unavailable_rejected
    """
    chef, menu, zone, client, booking = setup_requested_booking(
        chef_overrides={"display_name": "Chef EQ", "equipment_inventory": []},
        menu_overrides={"title": "Frozen", "required_equipment": ["BLAST_CHILLER"]},
        booking_overrides={"service_zip": "94110", "event_start_utc": "2026-08-27T18:00:00Z",
                           "event_end_utc": "2026-08-27T22:00:00Z"},
    )
    res = api.confirm_booking(booking["id"], {"expected_chef_version": chef["version"]},
                              make_chef_headers(chef["id"]))
    validate_error(res, "ERR_EQUIPMENT_UNAVAILABLE", expected_status=422)


def test_finalize_empty_grocery_run_rejected(api):
    """PRD §3.5: "It is allowed only when the acting chef owns the parent booking
    (`ERR_NOT_RESOURCE_OWNER`), the parent booking is `CONFIRMED`
    (`ERR_BOOKING_NOT_CONFIRMED`), and the run has at least one line item
    (`ERR_GROCERY_RUN_EMPTY`)."

    Design: Corner/validations/finalize_empty_grocery_run_rejected
    """
    chef, menu, zone, client, booking = setup_confirmed_booking(
        booking_overrides={"service_zip": "94110", "event_start_utc": "2026-08-28T18:00:00Z",
                           "event_end_utc": "2026-08-28T22:00:00Z"}
    )
    run = get_success_data(api.create_grocery_run(
        {"booking_id": booking["id"], "line_items": []}, make_chef_headers(chef["id"])))
    res = api.finalize_grocery_run(run["id"], make_chef_headers(chef["id"]))
    validate_error(res, "ERR_GROCERY_RUN_EMPTY", expected_status=422)
