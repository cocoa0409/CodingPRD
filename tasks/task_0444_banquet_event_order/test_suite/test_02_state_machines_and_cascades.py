"""Event / booking / link / payment lifecycles, the revision loop, and the
cascade + compensating-invariant behaviours that ripple state changes down to
bookings, blocks, menu lines, and payment allocations.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_event, add_menu_line, add_schedule_item, record_payment,
    get_event, get_event_version, create_hotel_room_block, get_block,
    create_room_block_link,
    setup_tentative_event_with_hold_booking, setup_tentative_event_with_definite_booking,
    setup_definite_event, setup_confirmed_event, setup_completed_event,
    make_definite,
    TEST_USERS,
)
from test_helpers.api_client import api_client

_SALES = TEST_USERS["sales_manager_headers"]
_CAPTAIN = TEST_USERS["banquet_captain_headers"]
_CLERK = TEST_USERS["accounting_clerk_headers"]
_ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# Difficulty: non_linear_state_machine
# ===========================================================================

def test_event_revision_loop_definite_back_to_tentative(api):
    """PRD §3.5: "A `SalesManager` reopens the event, dropping it from `DEFINITE` back to
    `TENTATIVE`, but only while the event is in `DEFINITE` status and the `guarantee_count`
    is still null"
    PRD §3.5: "Reopening reverts every `DEFINITE` booking on the event back to `HOLD`
    occupancy as a cascade and recomputes `estimated_total_cents` using the estimate
    variant."

    Design: Difficulty/non_linear_state_machine/event_revision_loop_definite_to_tentative
    """
    event_definite, _room, booking = setup_definite_event(
        event_overrides={"account_name": "Epsilon Mtg", "event_date": "2026-12-01",
                         "setup_style": "THEATER", "expected_attendance": 80},
        room_overrides={"name": "Salon D", "max_capacity": 200,
                        "turnover_buffer_minutes": 60, "hourly_rental_cents": 40000},
        start_utc="2026-12-01T09:00:00Z", end_utc="2026-12-01T12:00:00Z",
    )
    reopened = validate_success(api.reopen_event(event_definite["id"], _SALES))
    assert reopened["status"] == "TENTATIVE", f"got {reopened['status']}"
    booking_after = get_success_data(api.get_booking(event_definite["id"], booking["id"], _SALES))
    assert booking_after["hold_status"] == "HOLD", (
        f"reopen must revert the DEFINITE booking to HOLD, got {booking_after['hold_status']}"
    )


def test_booking_hold_definite_cycle_via_soften(api):
    """PRD §3.3: "The reverse move, softening a booking, returns its occupancy from
    `DEFINITE` to `HOLD`, again only while the owning event is `TENTATIVE` or `DEFINITE`;
    this frees the buffered window so other rooms or bookings may claim it."
    PRD §3.3: "A `SalesManager` makes a booking definite, advancing its occupancy from
    `HOLD` to `DEFINITE`, only while the owning event is in `TENTATIVE` or `DEFINITE` status."

    Design: Difficulty/non_linear_state_machine/booking_hold_definite_cycle
    """
    held, _room, booking = setup_tentative_event_with_hold_booking(
        event_overrides={"account_name": "Zeta Lunch", "event_date": "2027-01-15",
                         "setup_style": "ROUNDS", "expected_attendance": 60},
        room_overrides={"name": "Salon E", "max_capacity": 200,
                        "turnover_buffer_minutes": 30, "hourly_rental_cents": 30000},
        start_utc="2027-01-15T11:00:00Z", end_utc="2027-01-15T14:00:00Z",
    )
    make_definite(held["id"], booking["id"])
    validate_success(api.soften_booking(held["id"], booking["id"], _SALES))
    re_definite = validate_success(api.make_definite(held["id"], booking["id"], _SALES))
    assert re_definite["hold_status"] == "DEFINITE", (
        f"HOLD->DEFINITE->HOLD->DEFINITE cycle should end DEFINITE, got {re_definite['hold_status']}"
    )


# ===========================================================================
# Difficulty: transitive_cascade
# ===========================================================================

def test_cancel_event_releases_links_returns_block_rooms(api):
    """PRD §3.9: "Cancellation unwinds the event fully: every non-released booking is
    released, every non-released room-block link is released (each returning its committed
    rooms to its block's available pool as a second hop), and both `estimated_total_cents`
    and `actualized_total_cents` are frozen at their last computed values."

    Design: Difficulty/transitive_cascade/cancel_event_releases_links_returns_block_rooms_depth3
    """
    block = create_hotel_room_block(block_name="Conf Block", total_rooms=10, nightly_rate_cents=15000)
    held, _room, booking = setup_tentative_event_with_definite_booking(
        event_overrides={"account_name": "Eta Summit", "event_date": "2027-02-02",
                         "setup_style": "THEATER", "expected_attendance": 80},
        room_overrides={"name": "Salon F", "max_capacity": 200,
                        "turnover_buffer_minutes": 0, "hourly_rental_cents": 0},
        start_utc="2027-02-02T18:00:00Z", end_utc="2027-02-02T22:00:00Z",
    )
    link = create_room_block_link(held["id"], block["id"], 6, "2027-02-01", "2027-02-03")
    avail_before = get_block(block["id"])["rooms_available"]
    assert avail_before == 4, f"6 reserved of 10 -> available 4, got {avail_before}"

    cancelled = validate_success(api.cancel_event(held["id"], _SALES))
    assert cancelled["status"] == "CANCELLED", f"got {cancelled['status']}"

    links = get_success_data(api.list_event_room_block_links(held["id"], _CLERK))
    this_link = next(l for l in links if l["id"] == link["id"])
    assert this_link["link_status"] == "RELEASED", f"got {this_link['link_status']}"

    block_after = get_block(block["id"])
    assert block_after["rooms_available"] == 10, (
        f"released link should return rooms; available back to 10, got {block_after['rooms_available']}"
    )
    assert block_after["rooms_committed"] == 0, f"got {block_after['rooms_committed']}"


def test_actualize_recomputes_billable_menu_and_total(api):
    """PRD §3.5: "On success the system sets `actual_attendance` to the supplied value,
    recomputes `billable_count` (now the larger of guarantee and actual), recomputes the
    `extended_cents` of every `PER_PERSON` menu line as a cascade from that headcount
    change, computes `actualized_total_cents` using the actual variant of the charge
    rollup, and recomputes `balance_due_cents`."

    Design: Difficulty/transitive_cascade/actualize_recomputes_billable_menu_and_total_depth3
    """
    confirmed, _room, _booking, menu_ids = setup_confirmed_event(
        event_overrides={"account_name": "Theta Gala", "event_date": "2027-03-10",
                         "setup_style": "THEATER", "expected_attendance": 100,
                         "overset_pct": 0.05, "service_charge_pct": 0.20,
                         "gratuity_pct": 0.0, "sales_tax_pct": 0.10},
        room_overrides={"name": "Salon G", "max_capacity": 200,
                        "turnover_buffer_minutes": 60, "hourly_rental_cents": 50000},
        start_utc="2027-03-10T18:00:00Z", end_utc="2027-03-10T22:00:00Z",
        menu_lines=[{"name": "Plated Filet", "pricing_mode": "PER_PERSON", "unit_price_cents": 10000}],
        guarantee_count=120, deposit_amount_cents=500000,
    )
    menu_line_id = menu_ids[0]
    completed = validate_success(
        api.actualize_event(confirmed["id"], {"actual_attendance": 140}, _CAPTAIN))
    assert completed["billable_count"] == 140, f"got {completed['billable_count']}"

    lines = get_success_data(api.list_menu_lines(confirmed["id"], _SALES))
    ml = next(l for l in lines if l["id"] == menu_line_id)
    assert ml["extended_cents"] == 1400000, (
        f"PER_PERSON line should recompute to 10000*140=1400000, got {ml['extended_cents']}"
    )
    assert completed["actualized_total_cents"] == 2068000, (
        f"got {completed['actualized_total_cents']}"
    )


# ===========================================================================
# Difficulty: compensating_invariant
# ===========================================================================

def test_link_reserve_then_release_conserves_block_inventory(api):
    """PRD §3.6: "The block's `rooms_available` is `total_rooms` minus `rooms_committed`,
    never negative."
    PRD §3.6: "a released link stops counting toward the block's committed rooms, returning
    its rooms to the available pool, so the block is recomputed."

    Design: Difficulty/compensating_invariant/link_reserve_then_release_conserves_block_total_rooms
    """
    block = create_hotel_room_block(block_name="Invariant Block", total_rooms=10, nightly_rate_cents=10000)
    event = create_event(account_name="Rho Event", event_date="2027-12-02",
                         setup_style="ROUNDS", expected_attendance=40)
    link = create_room_block_link(event["id"], block["id"], 6, "2027-12-01", "2027-12-03")
    block_reserved = get_block(block["id"])
    assert block_reserved["rooms_committed"] == 6 and block_reserved["rooms_available"] == 4

    validate_success(api.release_link(event["id"], link["id"], _CLERK))
    block_after = get_block(block["id"])
    assert block_after["rooms_available"] == 10, f"got {block_after['rooms_available']}"
    assert block_after["rooms_committed"] == 0, f"got {block_after['rooms_committed']}"


def test_payment_apply_then_void_conserves_paid_and_allocations(api):
    """PRD §3.9: "When a void succeeds, the voided payment is excluded from
    `paid_to_date_cents`, the allocation waterfall is re-run so every schedule item's
    `allocated_cents` and `settled` are recomputed, and the event's `balance_due_cents` is
    recomputed."
    PRD §3.8: "Walking the items from `sequence_no` 1 upward, each item is allocated the
    smaller of the remaining unallocated pool and that item's `amount_due_cents`"

    Design: Difficulty/compensating_invariant/payment_apply_then_void_conserves_paid_and_allocations
    """
    event = create_event(account_name="Sigma Event", event_date="2028-01-15",
                         setup_style="THEATER", expected_attendance=50,
                         service_charge_pct=0.0, gratuity_pct=0.0, sales_tax_pct=0.0)
    add_schedule_item(event["id"], 500000, label="Deposit", due_date="2027-12-01")
    item2 = add_schedule_item(event["id"], 300000, label="Second", due_date="2028-01-01")
    v1 = get_event_version(event["id"])
    record_payment(event["id"], 500000, v1, method="WIRE")
    v2 = get_event_version(event["id"])
    pay2 = record_payment(event["id"], 400000, v2, method="ACH")

    validate_success(api.void_payment(event["id"], pay2["id"], _CLERK))

    ev = get_event(event["id"])
    assert ev["paid_to_date_cents"] == 500000, (
        f"void should restore paid_to_date to 500000, got {ev['paid_to_date_cents']}"
    )
    items = get_success_data(api.list_payment_schedule_items(event["id"], _CLERK))
    item2_after = next(i for i in items if i["id"] == item2["id"])
    assert item2_after["allocated_cents"] == 0, (
        f"item2 allocation should return to 0, got {item2_after['allocated_cents']}"
    )
    assert item2_after["settled"] is False, f"got {item2_after['settled']}"


# ===========================================================================
# Corner: state_machines
# ===========================================================================

def test_hold_from_already_definite_event_invalid_state(api):
    """PRD §3.2: "The first lifecycle move is placing a soft space hold, taking the event
    from `INQUIRY` to `TENTATIVE`."
    PRD §2.8: "State is checked next: a transition endpoint whose target resource is not in
    a valid state for the requested transition — for example, locking the guarantee on an
    event that is not `DEFINITE`, or voiding a payment that is not `APPLIED` — is rejected
    with the generic `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/hold_from_already_definite_event_returns_invalid_state
    """
    event_definite, _room, _booking = setup_definite_event(
        event_overrides={"account_name": "Tau Co", "event_date": "2028-02-01",
                         "setup_style": "THEATER", "expected_attendance": 40},
        room_overrides={"name": "Salon M", "max_capacity": 300,
                        "turnover_buffer_minutes": 0, "hourly_rental_cents": 0},
        start_utc="2028-02-01T18:00:00Z", end_utc="2028-02-01T22:00:00Z",
    )
    resp = api.hold_event(event_definite["id"], _SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_event(event_definite["id"])["status"] == "DEFINITE"


def test_confirm_space_with_hold_booking_not_all_definite(api):
    """PRD §3.2: "every booking on the event has been flipped to `DEFINITE` occupancy with
    none left in `HOLD`; if any booking is still soft-held the move is rejected with
    `ERR_BOOKING_NOT_ALL_DEFINITE`."

    Design: Corner/state_machines/confirm_space_with_hold_booking_returns_not_all_definite
    """
    room = get_success_data(api.create_function_room(
        {"name": "Salon N", "max_capacity": 300, "turnover_buffer_minutes": 0,
         "hourly_rental_cents": 0}, _ADMIN))
    event = create_event(account_name="Ups Co", event_date="2028-03-01",
                         setup_style="THEATER", expected_attendance=40)
    b1 = get_success_data(api.create_booking(
        event["id"], {"function_room_id": room["id"], "start_utc": "2028-03-01T09:00:00Z",
                      "end_utc": "2028-03-01T11:00:00Z",
                      "expected_event_version": event["version"]}, _SALES))
    get_success_data(api.hold_event(event["id"], _SALES))
    make_definite(event["id"], b1["id"])
    v1 = get_event_version(event["id"])
    get_success_data(api.create_booking(
        event["id"], {"function_room_id": room["id"], "start_utc": "2028-03-01T13:00:00Z",
                      "end_utc": "2028-03-01T15:00:00Z", "expected_event_version": v1}, _SALES))
    resp = api.confirm_space(event["id"], _SALES)
    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_ALL_DEFINITE.value)
    assert get_event(event["id"])["status"] == "TENTATIVE"


def test_cancel_from_completed_terminal_invalid_state(api):
    """PRD §3.2: "An event's lifecycle status is one of `INQUIRY`, `TENTATIVE`, `DEFINITE`,
    `CONFIRMED`, `COMPLETED`, or `CANCELLED`; the last two are terminal."
    PRD §3.9: "The terminal cancellation of an event is driven by a `SalesManager`, who may
    cancel an event from any non-terminal status — `INQUIRY`, `TENTATIVE`, `DEFINITE`, or
    `CONFIRMED` — moving it to the terminal `CANCELLED`."

    Design: Corner/state_machines/cancel_from_completed_terminal_returns_invalid_state
    """
    completed, _room, _booking, _ = setup_completed_event(
        event_overrides={"account_name": "Term Co", "event_date": "2028-04-01",
                         "setup_style": "THEATER", "expected_attendance": 40,
                         "service_charge_pct": 0.0, "gratuity_pct": 0.0, "sales_tax_pct": 0.0},
        room_overrides={"name": "Salon O", "max_capacity": 300,
                        "turnover_buffer_minutes": 0, "hourly_rental_cents": 0},
        start_utc="2028-04-01T18:00:00Z", end_utc="2028-04-01T22:00:00Z",
        guarantee_count=40, actual_attendance=38, deposit_amount_cents=50000,
    )
    resp = api.cancel_event(completed["id"], _SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_event(completed["id"])["status"] == "COMPLETED"


def test_release_booking_zeroes_rental_and_frees_window(api):
    """PRD §3.3: "Releasing a booking moves it from either `HOLD` or `DEFINITE` to the
    terminal `RELEASED` occupancy: its `rental_charge_cents` is set to zero and its window
    is freed entirely."

    Design: Corner/state_machines/release_booking_zeroes_rental_and_frees_window
    """
    held, _room, booking = setup_tentative_event_with_definite_booking(
        event_overrides={"account_name": "Rel Co", "event_date": "2028-05-01",
                         "setup_style": "THEATER", "expected_attendance": 40},
        room_overrides={"name": "Salon P", "max_capacity": 300,
                        "turnover_buffer_minutes": 0, "hourly_rental_cents": 50000},
        start_utc="2028-05-01T18:00:00Z", end_utc="2028-05-01T22:00:00Z",
    )
    released = validate_success(api.release_booking(held["id"], booking["id"], _SALES))
    assert released["hold_status"] == "RELEASED", f"got {released['hold_status']}"
    assert released["rental_charge_cents"] == 0, f"got {released['rental_charge_cents']}"


def test_void_already_voided_payment_invalid_state(api):
    """PRD §3.9: "An `AccountingClerk` may void a payment, flipping it from `APPLIED` to the
    terminal `VOIDED` status, but only while that payment is currently `APPLIED`"
    PRD §2.8: "voiding a payment that is not `APPLIED` — is rejected with the generic
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/void_already_voided_payment_returns_invalid_state
    """
    event = create_event(account_name="Idem Co", event_date="2028-06-01",
                         setup_style="THEATER", expected_attendance=20,
                         service_charge_pct=0.0, gratuity_pct=0.0, sales_tax_pct=0.0)
    v0 = event["version"]
    pay = record_payment(event["id"], 30000, v0, method="CHECK")
    validate_success(api.void_payment(event["id"], pay["id"], _CLERK))
    resp = api.void_payment(event["id"], pay["id"], _CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    payments = get_success_data(api.list_payments(event["id"], _CLERK))
    this_pay = next(p for p in payments if p["id"] == pay["id"])
    assert this_pay["status"] == "VOIDED", f"got {this_pay['status']}"


def test_reopen_after_guarantee_locked_invalid_state(api):
    """PRD §3.5: "A `SalesManager` reopens the event, dropping it from `DEFINITE` back to
    `TENTATIVE`, but only while the event is in `DEFINITE` status and the `guarantee_count`
    is still null — once a guarantee is locked the event has moved past `DEFINITE` and
    reopening is no longer available."

    Design: Corner/state_machines/reopen_after_guarantee_locked_returns_invalid_state
    """
    confirmed, _room, _booking, _ = setup_confirmed_event(
        event_overrides={"account_name": "Reopen Co", "event_date": "2028-07-01",
                         "setup_style": "THEATER", "expected_attendance": 40,
                         "service_charge_pct": 0.0, "gratuity_pct": 0.0, "sales_tax_pct": 0.0},
        room_overrides={"name": "Salon Q", "max_capacity": 300,
                        "turnover_buffer_minutes": 0, "hourly_rental_cents": 0},
        start_utc="2028-07-01T18:00:00Z", end_utc="2028-07-01T22:00:00Z",
        guarantee_count=40, deposit_amount_cents=50000,
    )
    resp = api.reopen_event(confirmed["id"], _SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_event(confirmed["id"])["status"] == "CONFIRMED"


# ===========================================================================
# Corner: errors (terminal-event line-edit lockdown)
# ===========================================================================

def test_terminal_event_rejects_menu_line_add(api):
    """PRD §3.7: "Any attempt to edit lines on a `COMPLETED` or `CANCELLED` event is
    rejected with `ERR_EVENT_TERMINAL`."

    Design: Corner/errors/terminal_event_rejects_menu_line_add
    """
    event = create_event(account_name="Cancel Co", event_date="2029-07-01",
                         setup_style="THEATER", expected_attendance=30)
    validate_success(api.cancel_event(event["id"], _SALES))
    resp = api.create_menu_line(
        event["id"], {"name": "Late Add", "pricing_mode": "CONSUMPTION",
                      "unit_price_cents": 500, "consumption_qty": 2}, _SALES)
    validate_error(resp, ApiErrorId.ERR_EVENT_TERMINAL.value)


# ===========================================================================
# Corner: cross_cutting_complexity_layers (derived-field reconciliation)
# ===========================================================================

def test_void_payment_recomputes_balance_derived_field(api):
    """PRD §3.9: "When a void succeeds, the voided payment is excluded from
    `paid_to_date_cents`, the allocation waterfall is re-run so every schedule item's
    `allocated_cents` and `settled` are recomputed, and the event's `balance_due_cents` is
    recomputed."

    Design: Corner/cross_cutting_complexity_layers/void_payment_recomputes_balance_derived_field
    """
    event = create_event(account_name="Recon Co", event_date="2030-03-01",
                         setup_style="THEATER", expected_attendance=20,
                         service_charge_pct=0.0, gratuity_pct=0.0, sales_tax_pct=0.0)
    v0 = event["version"]
    pay = record_payment(event["id"], 20000, v0, method="CHECK")
    ev_before = get_event(event["id"])
    assert ev_before["paid_to_date_cents"] == 20000 and ev_before["balance_due_cents"] == -20000

    validate_success(api.void_payment(event["id"], pay["id"], _CLERK))
    ev = get_event(event["id"])
    assert ev["paid_to_date_cents"] == 0, f"got {ev['paid_to_date_cents']}"
    assert ev["balance_due_cents"] == 0, f"got {ev['balance_due_cents']}"
    payments = get_success_data(api.list_payments(event["id"], _CLERK))
    this_pay = next(p for p in payments if p["id"] == pay["id"])
    assert this_pay["status"] == "VOIDED", f"got {this_pay['status']}"
