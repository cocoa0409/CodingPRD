"""Entity CRUD, defaults, parent relationships, FK integrity, derived-field
reconciliation, and inventory/rain-check state transitions (PRD §3.1, §3.6, §3.8)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    make_guest_headers, TEST_USERS, NON_EXISTENT_UUID,
    assert_park, assert_order, assert_locker_rental,
    create_park, create_policy, create_window, create_cabana, create_guest, create_order,
    setup_held_cabana_rental, setup_rained_out_admission, get_window,
)

PM = TEST_USERS["park_manager_headers"]
FC = TEST_USERS["finance_clerk_headers"]
GH_SHARED = TEST_USERS["guest_headers"]


# ───────────────── Queue B: entities ─────────────────

def test_create_park_returns_201_with_defaults(api):
    """PRD §3.1: "A freshly created park starts with weather_status of CLEAR and
    open_window_count of 0."
    PRD §2.4: "The version field is an integer that begins at creation"

    Design: Corner/entities/create_park_returns_201_with_defaults
    """
    res = api_client.create_park({"name": "New Park", "total_gate_capacity": 500}, PM)
    park = validate_success(res, 201)
    assert_park(park)
    assert park["weather_status"] == "CLEAR"
    assert park["open_window_count"] == 0
    assert park["version"] == 1


def test_get_park_returns_stored_data(api):
    """PRD §3.1: "a total_gate_capacity of at least 1 that bounds park-wide admittance"
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."

    Design: Corner/entities/get_park_returns_stored_data
    """
    park = create_park(total_gate_capacity=777)
    fetched = validate_success(api_client.get_park(park["id"], GH_SHARED), 200)
    assert fetched["total_gate_capacity"] == 777


def test_list_parks_paginated_envelope(api):
    """PRD §2.3: "Each list response carries limit, offset, total_count, and has_more
    inside the meta object of the envelope, where total_count is the count of all
    matching rows before pagination and has_more indicates whether rows remain beyond
    the current page."

    Design: Corner/entities/list_parks_paginated_envelope
    """
    create_park(name="P1", total_gate_capacity=100)
    create_park(name="P2", total_gate_capacity=100)
    data, meta = validate_paginated(api_client.list_parks(PM, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] >= 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_get_park_not_found_returns_404(api):
    """PRD §2.5: "the first identifier that does not resolve to a live resource causes
    the request to be rejected with ERR_NOT_FOUND"

    Design: Corner/entities/get_park_not_found_returns_404
    """
    res = api_client.get_park(NON_EXISTENT_UUID, PM)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_park_missing_required_field_rejected(api):
    """PRD §2.9: "Request-schema validation is fifth — missing required fields, invalid
    enum values, out-of-range numbers, or an interval whose starts_at is not
    strictly before its ends_at fail with ERR_INVALID_REQUEST."
    PRD §3.1: "a total_gate_capacity of at least 1 that bounds park-wide admittance"

    Design: Corner/entities/create_park_missing_required_field_returns_invalid_request
    """
    res = api_client.create_park({"name": "No Cap"}, PM)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_order_food_combo_defaults_false(api):
    """PRD §3.3: "an optional food_beverage_combo flag defaulting to false."

    Design: Corner/entities/order_food_combo_default_false
    """
    park = create_park()
    guest = create_guest()
    order = get_success_data(api_client.create_order(
        {"park_id": park["id"], "guest_id": guest["id"], "product_type": "DAY_TICKET",
         "party_size": 1}, make_guest_headers(guest["id"])))
    assert order["food_beverage_combo"] is False


def test_order_system_fields_generated(api):
    """PRD §2.4: "The id is a server-minted UUID with no type prefix."
    PRD §2.4: "The version field is an integer that begins at creation and increments
    by one on every mutation"

    Design: Corner/entities/order_system_fields_generated_input_ignored
    """
    park = create_park()
    guest = create_guest()
    order = get_success_data(api_client.create_order(
        {"park_id": park["id"], "guest_id": guest["id"], "product_type": "DAY_TICKET",
         "party_size": 3}, make_guest_headers(guest["id"])))
    assert_order(order)
    assert order["version"] == 1


def test_order_invalid_product_type_enum_rejected(api):
    """PRD §2.9: "Request-schema validation is fifth — missing required fields, invalid
    enum values, out-of-range numbers, or an interval whose starts_at is not strictly
    before its ends_at fail with ERR_INVALID_REQUEST."

    Design: Corner/entities/order_invalid_product_type_enum_rejected
    """
    park = create_park()
    guest = create_guest()
    res = api_client.create_order(
        {"park_id": park["id"], "guest_id": guest["id"], "product_type": "GOLD_PASS",
         "party_size": 1}, make_guest_headers(guest["id"]))
    validate_error(res, "ERR_INVALID_REQUEST")


def test_locker_rental_lean_no_version_field(api):
    """PRD §2.4: "A LockerRental and the singleton ClockState carry only id and
    created_at; they have no updated_at and no version."
    PRD §3.7: "hours_billed is that duration rounded up to the next whole hour"

    Design: Corner/entities/locker_rental_immutable_no_version_field
    """
    park = create_park()
    create_policy(park["id"], product_type="DAY_TICKET", base_price_cents=5000)
    locker = get_success_data(api_client.create_locker(park["id"],
                                                       {"bank_code": "B", "hourly_rate_cents": 300}, PM))
    guest = create_guest()
    gh = make_guest_headers(guest["id"])
    order = create_order(park["id"], guest["id"], product_type="DAY_TICKET", party_size=1)
    get_success_data(api_client.pay_order(order["id"], gh))
    lr = get_success_data(api_client.create_locker_rental(
        {"locker_id": locker["id"], "order_id": order["id"],
         "starts_at": "2026-07-01T10:00:00Z", "ends_at": "2026-07-01T12:30:00Z"}, gh))
    assert_locker_rental(lr)
    assert lr["hours_billed"] == 3, f"ceil(2.5h) = 3, got {lr['hours_billed']}"
    assert "version" not in lr


def test_entry_window_requires_existing_parent_park(api):
    """PRD §2.5: "A request for a window under a non-existent park therefore fails on
    the park, not the window."

    Design: Corner/entities/entry_window_requires_existing_parent_park
    """
    res = api_client.create_entry_window(
        NON_EXISTENT_UUID,
        {"starts_at": "2026-07-01T09:00:00Z", "ends_at": "2026-07-01T17:00:00Z",
         "window_capacity": 10}, PM)
    validate_error(res, "ERR_NOT_FOUND")


def test_order_unknown_guest_rejected(api):
    """PRD §2.5: "The server validates every identifier appearing in a path or body
    from left to right, and the first identifier that does not resolve to a live
    resource causes the request to be rejected with ERR_NOT_FOUND before any later
    identifier or business rule is consulted."

    Design: Corner/entities/fk_integrity_order_unknown_guest_rejected
    """
    park = create_park()
    res = api_client.create_order(
        {"park_id": park["id"], "guest_id": NON_EXISTENT_UUID, "product_type": "DAY_TICKET",
         "party_size": 1}, make_guest_headers(NON_EXISTENT_UUID))
    validate_error(res, "ERR_NOT_FOUND")


# ───────────────── Queue B: state_machines (windows, cabana, rain-check) ─────────────────

def test_window_restrict_sets_restricted_status(api):
    """PRD §3.1: "Restricting a window moves it from OPEN to RESTRICTED, which keeps
    existing reservations valid but blocks new assignment"

    Design: Corner/state_machines/window_restrict_blocks_new_assignment_keeps_reservation
    """
    park = create_park()
    window = create_window(park["id"], starts_at="2026-07-01T09:00:00Z",
                           ends_at="2026-07-01T17:00:00Z", window_capacity=50)
    restricted = get_success_data(api_client.restrict_entry_window(window["id"], PM))
    assert restricted["status"] == "RESTRICTED"


def test_close_window_with_force_flag(api):
    """PRD §3.1: "Closing a window moves it from either OPEN or RESTRICTED to the
    terminal CLOSED status; closing is permitted only when the window's admitted_count
    and reserved_count are both zero, unless the caller sets the optional force flag"

    Design: Corner/state_machines/close_window_with_force_flag
    """
    park = create_park()
    window = create_window(park["id"], starts_at="2026-07-01T09:00:00Z",
                           ends_at="2026-07-01T17:00:00Z", window_capacity=50)
    closed = get_success_data(api_client.close_entry_window(window["id"], {"force": True}, PM))
    assert closed["status"] == "CLOSED"


def test_open_window_count_reconciled_on_restrict(api):
    """PRD §2.7: "open_window_count is the number of that park's EntryWindow children
    whose status is OPEN, and it is recomputed on every window status change that adds
    or removes an OPEN window."
    PRD §3.1: "Restricting a window moves it from OPEN to RESTRICTED, which keeps existing
    reservations valid but blocks new assignment, and recomputes the park's
    open_window_count downward."

    Design: Corner/state_machines/open_window_count_reconciled_on_restrict
    """
    park = create_park()
    window = create_window(park["id"], starts_at="2026-07-01T09:00:00Z",
                           ends_at="2026-07-01T17:00:00Z", window_capacity=50)
    get_success_data(api_client.restrict_entry_window(window["id"], PM))
    park_after = get_success_data(api_client.get_park(park["id"], PM))
    assert park_after["open_window_count"] == 0


def test_derived_open_window_count_after_close(api):
    """PRD §2.7: "open_window_count is the number of that park's EntryWindow children
    whose status is OPEN, and it is recomputed on every window status change that adds
    or removes an OPEN window."
    PRD §3.1: "Closing a window moves it from either OPEN or RESTRICTED to the terminal
    CLOSED status; closing is permitted only when the window's admitted_count and
    reserved_count are both zero, unless the caller sets the optional force flag, and it
    recomputes open_window_count when the window had been OPEN."

    Design: Corner/cross_cutting_complexity_layers/derived_open_window_count_after_close
    """
    park = create_park()
    create_window(park["id"], starts_at="2026-07-01T09:00:00Z",
                  ends_at="2026-07-01T13:00:00Z", window_capacity=50)
    w2 = create_window(park["id"], starts_at="2026-07-01T13:00:00Z",
                       ends_at="2026-07-01T17:00:00Z", window_capacity=50)
    get_success_data(api_client.close_entry_window(w2["id"], {"force": True}, PM))
    park_after = get_success_data(api_client.get_park(park["id"], PM))
    assert park_after["open_window_count"] == 1, \
        f"closing one of two OPEN windows → 1, got {park_after['open_window_count']}"


def test_cabana_rental_confirmed_on_order_fulfill(api):
    """PRD §3.6: "When its parent order is fulfilled, the rental is promoted from HELD
    to CONFIRMED as a side effect of fulfillment, provided the order's payment_status
    is PAID"

    Design: Corner/state_machines/cabana_rental_confirmed_on_order_fulfill
    """
    ctx = setup_held_cabana_rental()
    gh = make_guest_headers(ctx["guest"]["id"])
    get_success_data(api_client.fulfill_order(ctx["order"]["id"], gh))
    rental_after = get_success_data(api_client.get_cabana_rental(ctx["rental"]["id"], gh))
    assert rental_after["status"] == "CONFIRMED"


def test_cancel_cabana_rental_releases_reserved_count(api):
    """PRD §3.6: "A guest or manager may cancel a rental that is HELD or CONFIRMED,
    moving it to the terminal CANCELLED and decrementing the window's reserved_count by
    one."

    Design: Corner/state_machines/cancel_cabana_rental_releases_reserved_count
    """
    ctx = setup_held_cabana_rental()
    gh = make_guest_headers(ctx["guest"]["id"])
    before = get_window(ctx["window"]["id"])
    assert before["reserved_count"] == 1, f"HELD rental holds 1, got {before['reserved_count']}"
    get_success_data(api_client.cancel_cabana_rental(ctx["rental"]["id"], gh))
    after = get_window(ctx["window"]["id"])
    assert after["reserved_count"] == 0


def test_raincheck_expire_no_wallet_credit(api):
    """PRD §3.8: "a ParkManager expires an ISSUED voucher, moving it to the terminal
    EXPIRED with no wallet credit."

    Design: Corner/state_machines/raincheck_expire_no_wallet_credit
    """
    ctx = setup_rained_out_admission(rain_check_value_cents=4000, clock="2026-07-01T10:00:00Z")
    rc = [r for r in ctx["rain_checks"] if r["guest_id"] == ctx["guest"]["id"]][0]
    expired = get_success_data(api_client.expire_rain_check(rc["id"], PM))
    assert expired["status"] == "EXPIRED"
    guest_after = get_success_data(api_client.get_guest(ctx["guest"]["id"], PM))
    assert guest_after["wallet_credit_cents"] == 0


def test_settle_already_settled_raincheck_rejected(api):
    """PRD §3.8: "A settle or expire attempted on a voucher that is not in ISSUED status
    is rejected with ERR_RAINCHECK_NOT_ISSUED."

    Design: Corner/state_machines/settle_already_settled_raincheck_rejected
    """
    ctx = setup_rained_out_admission(rain_check_value_cents=4000, clock="2026-07-01T10:00:00Z")
    rc = [r for r in ctx["rain_checks"] if r["guest_id"] == ctx["guest"]["id"]][0]
    get_success_data(api_client.settle_rain_check(rc["id"], FC))
    res = api_client.settle_rain_check(rc["id"], FC)
    validate_error(res, "ERR_RAINCHECK_NOT_ISSUED")


# ───────────────── Queue B: endpoints ─────────────────

def test_pricing_policy_supersede_deactivates_prior(api):
    """PRD §3.2: "Creating a new policy for a given park-and-product-type pairing
    supersedes any prior policy for that same pairing by setting the prior row's active
    to false, leaving exactly one active policy live per pairing."

    Design: Corner/endpoints/pricing_policy_supersede_deactivates_prior
    """
    park = create_park()
    pol1 = create_policy(park["id"], product_type="DAY_TICKET", base_price_cents=5000)
    create_policy(park["id"], product_type="DAY_TICKET", base_price_cents=5500)
    actives = get_success_data(api_client.list_pricing_policies(
        PM, params={"park_id": park["id"], "product_type": "DAY_TICKET", "active": True}))
    assert len(actives) == 1, f"exactly one active policy expected, got {len(actives)}"
    assert actives[0]["base_price_cents"] == 5500
    prior = get_success_data(api_client.get_pricing_policy(pol1["id"], PM))
    assert prior["active"] is False


def test_bind_guest_sets_guest_id(api):
    """PRD §3.4: "Binding a named guest sets the admission's guest_id and may be
    performed by the owning guest or by a GateAgent before check-in"

    Design: Corner/endpoints/bind_guest_action_endpoint_sets_guest_id
    """
    from test_helpers import setup_issued_admission
    ctx = setup_issued_admission(make_window=False)
    adm = ctx["admissions"][0]
    bound = get_success_data(api_client.bind_guest(adm["id"], {"guest_id": ctx["guest"]["id"]}, TEST_USERS["gate_agent_headers"]))
    assert bound["guest_id"] == ctx["guest"]["id"]
