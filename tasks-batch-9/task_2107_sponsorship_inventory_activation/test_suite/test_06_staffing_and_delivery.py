"""Rostering shifts, working them, and the delivery cascade they gate."""

from test_helpers import (
    ApiErrorId,
    SEASON_START,
    TEST_USERS,
    assert_instant_equals,
    assert_reserved_units_total,
    assert_staff_assignment,
    assign_staff,
    book_asset,
    cancel_booking,
    create_staff_member,
    deliver_booking,
    read_assignment,
    read_booking,
    read_contract,
    read_entitlement,
    read_inventory_asset,
    read_property,
    set_clock,
    setup_active_contract_with_booking,
    setup_back_to_back_shift_bookings,
    setup_contract_scenario,
    setup_staffed_booking,
    transition_property,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["property_admin_headers"]
APPROVER = TEST_USERS["approver_headers"]
ACTIVATION = TEST_USERS["activation_headers"]


def _shift_payload(staff_member_id, shift_start, shift_end):
    return {
        "staff_member_id": staff_member_id,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "role_label": "Brand Ambassador",
    }


# ---------------------------------------------------------------------------
# Shift geometry: closed intervals plus a fixed rest gap
# ---------------------------------------------------------------------------
def test_shift_touching_an_existing_shift_end_collides(api):
    """PRD §3.7: "Where occupation windows are half-open, shifts are treated as
    **closed** intervals, so two shifts that merely touch at an endpoint do
    collide: a new shift conflicts with an existing one when the new `shift_start`
    is at or before the existing `shift_end` and the existing `shift_start` is at
    or before the new `shift_end`."
    PRD §3.7: "A violation of either test is reported as
    `ERR_STAFF_SHIFT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/staff_closed_interval_shift_with_forty_five_minute_rest_gap
    """
    scenario = setup_back_to_back_shift_bookings()

    response = api.create_staff_assignment(
        scenario["booking_two"]["id"],
        _shift_payload(
            scenario["staff_member"]["id"],
            "2026-09-15T18:00:00Z",
            "2026-09-15T19:00:00Z",
        ),
        ACTIVATION,
    )
    validate_error(response, ApiErrorId.ERR_STAFF_SHIFT_CONFLICT.value)
    assert response.status_code == 409, (
        "the new shift starts exactly when the existing one ends, and closed "
        "intervals make touching endpoints collide"
    )


def test_rest_gap_below_forty_five_minutes_is_rejected_and_exactly_forty_five_is_admitted(api):
    """PRD §3.7: "Beyond outright collision, two non-touching shifts of the same
    staffer must be separated by at least 45 minutes of rest."
    PRD §3.7: "A violation of either test is reported as
    `ERR_STAFF_SHIFT_CONFLICT`."
    PRD §3.7: "An accepted assignment opens at `ASSIGNED` and raises that
    staffer's `scheduled_minutes` by the shift's length in whole minutes."

    Design: Difficulty/resource_temporal_overlap/staff_closed_interval_shift_with_forty_five_minute_rest_gap
    """
    scenario = setup_back_to_back_shift_bookings()

    too_soon = api.create_staff_assignment(
        scenario["booking_two"]["id"],
        _shift_payload(
            scenario["staff_member"]["id"],
            "2026-09-15T18:30:00Z",
            "2026-09-15T19:00:00Z",
        ),
        ACTIVATION,
    )
    validate_error(too_soon, ApiErrorId.ERR_STAFF_SHIFT_CONFLICT.value)

    response = api.create_staff_assignment(
        scenario["booking_two"]["id"],
        _shift_payload(
            scenario["staff_member"]["id"],
            "2026-09-15T18:45:00Z",
            "2026-09-15T19:30:00Z",
        ),
        ACTIVATION,
    )
    assignment = validate_success(response, 201)
    assert_staff_assignment(assignment)
    assert assignment["status"] == "ASSIGNED", (
        "45 minutes of rest is exactly the declared minimum and is admitted"
    )


# ---------------------------------------------------------------------------
# Delivery is gated on the staffing of the occupied asset
# ---------------------------------------------------------------------------
def test_delivery_is_refused_while_the_only_shift_is_still_assigned(api):
    """PRD §3.8: "An `ActivationManager` drives a booking `SCHEDULED →
    DELIVERED` once three conditions hold, evaluated in this order: the owning
    entitlement's contract must be `ACTIVE`, or the request fails with
    `ERR_CONTRACT_NOT_ACTIVE`; the logical clock must have reached the booking's
    `window_end` or passed it, or it fails with `ERR_DELIVERY_WINDOW_OPEN`; and
    when the occupied asset has `requires_staffing` set to true, the number of
    this booking's assignments whose `status` is `CHECKED_IN` must be at least the
    asset's `min_staff_count`, or it fails with `ERR_STAFFING_INCOMPLETE`."

    Design: Difficulty/cross_entity_state_dependency/deliver_blocked_until_staff_assignment_is_checked_in
    """
    scenario = setup_staffed_booking()
    assert scenario["contract"]["cash_value_cents"] == 360_000, (
        "two ACTIVATION_SPACE units at 150000 scaled by seasonality 1.20 carry "
        f"no volume discount; got {scenario['contract']['cash_value_cents']}"
    )
    assert scenario["assignment"]["status"] == "ASSIGNED"

    response = api.deliver_asset_booking(scenario["booking"]["id"], ACTIVATION)
    validate_error(response, ApiErrorId.ERR_STAFFING_INCOMPLETE.value)
    assert response.status_code == 409

    assert read_booking(scenario["booking"]["id"])["status"] == "SCHEDULED"


def test_delivery_succeeds_after_check_in_and_releases_the_shift(api):
    """PRD §3.7: "On the day, the `ActivationManager` checks the staffer in,
    driving the assignment `ASSIGNED → CHECKED_IN`."
    PRD §3.8: "An accepted delivery stamps `delivered_at` with the current
    logical-clock instant and then unwinds the roster: every one of the booking's
    assignments still sitting at `ASSIGNED` becomes `NO_SHOW`, because the shift
    ended without anyone reporting, while every assignment at `CHECKED_IN` becomes
    `RELEASED`."

    Design: Difficulty/cross_entity_state_dependency/deliver_blocked_until_staff_assignment_is_checked_in
    """
    scenario = setup_staffed_booking()

    refused = api.deliver_asset_booking(scenario["booking"]["id"], ACTIVATION)
    validate_error(refused, ApiErrorId.ERR_STAFFING_INCOMPLETE.value)

    checked_in = validate_success(
        api.check_in_staff_assignment(scenario["assignment"]["id"], ACTIVATION)
    )
    assert checked_in["status"] == "CHECKED_IN"

    delivered = validate_success(
        api.deliver_asset_booking(scenario["booking"]["id"], ACTIVATION)
    )
    assert delivered["status"] == "DELIVERED"

    assert read_assignment(scenario["assignment"]["id"])["status"] == "RELEASED"
    assert read_entitlement(scenario["entitlement"]["id"])["delivered_units"] == 1


# ---------------------------------------------------------------------------
# The delivery cascade runs upward through four rows
# ---------------------------------------------------------------------------
def test_delivery_cascades_from_booking_to_entitlement_to_contract(api):
    """PRD §3.8: "An accepted delivery stamps `delivered_at` with the current
    logical-clock instant and then unwinds the roster: every one of the booking's
    assignments still sitting at `ASSIGNED` becomes `NO_SHOW`, because the shift
    ended without anyone reporting, while every assignment at `CHECKED_IN` becomes
    `RELEASED`."
    PRD §3.8: "`delivery_pct` is 100 multiplied by `delivered_units`, divided by
    `promised_units`, rounded half up to 2 decimal places. The entitlement's
    `status` follows directly from those numbers: a `WAIVED` entitlement stays
    `WAIVED`; otherwise zero delivered units means `PENDING`, delivered units
    below `promised_units` means `PARTIAL`, and delivered units at or above
    `promised_units` means `FULFILLED`."
    PRD §3.8: "In the same rollup the contract's `delivered_media_value_cents` is
    set to the sum, over that contract's bookings whose `status` is `DELIVERED`
    and whose `proof_state` is not `DEFICIENT`, of `units_booked` multiplied by
    the owning entitlement's `unit_value_cents`."

    Design: Difficulty/transitive_cascade/deliver_booking_cascades_booking_entitlement_contract_property
    """
    scenario = setup_active_contract_with_booking(
        units_booked=4, contract_overrides={"exclusivity_scope": "CATEGORY"}
    )
    set_clock("2026-09-10T21:00:00Z")

    delivered = deliver_booking(scenario["booking"]["id"])
    assert delivered["status"] == "DELIVERED"
    assert_instant_equals(
        delivered["delivered_at"], "2026-09-10T21:00:00Z", "delivered_at"
    )

    entitlement = read_entitlement(scenario["entitlement"]["id"])
    assert entitlement["delivered_units"] == 4
    assert entitlement["status"] == "PARTIAL"

    contract = read_contract(scenario["contract"]["id"])
    assert contract["fulfillment_status"] == "IN_PROGRESS"
    assert contract["delivered_media_value_cents"] == 1_350_000, (
        "4 units at the 337500 pinned unit value; got "
        f"{contract['delivered_media_value_cents']}"
    )


def test_delivery_cascade_reaches_the_property_and_releases_the_units(api):
    """PRD §3.8: "The occupation itself is over, so the asset's
    `reserved_units_total` drops by `units_booked` and the asset's `version`
    increments by 1. From there the value cascade runs upward: the owning
    entitlement recomputes its delivery figures, the owning contract recomputes
    its fulfilment dimension and its delivered media value, and the property
    recomputes its own `delivered_media_value_cents`, incrementing the property's
    `version` by 1."
    PRD §3.1: "`delivered_media_value_cents` is the sum of the contracts' own
    `delivered_media_value_cents` across those contracts whose `status` is
    `ACTIVE` or `CLOSED`."

    Design: Difficulty/transitive_cascade/deliver_booking_cascades_booking_entitlement_contract_property
    """
    scenario = setup_active_contract_with_booking(
        units_booked=4, contract_overrides={"exclusivity_scope": "CATEGORY"}
    )
    set_clock("2026-09-10T21:00:00Z")
    deliver_booking(scenario["booking"]["id"])

    prop = read_property(scenario["property"]["id"])
    assert prop["delivered_media_value_cents"] == 1_350_000
    assert prop["committed_gross_value_cents"] == 3_105_000, (
        "an ACTIVE contract still contributes to the committed position"
    )

    assert_reserved_units_total(
        read_inventory_asset(scenario["asset"]["id"]), 0
    )


# ---------------------------------------------------------------------------
# The fulfilment dimension moves without touching the lifecycle
# ---------------------------------------------------------------------------
def _two_booking_scenario():
    scenario = setup_contract_scenario(
        stage="ACTIVE", contract_overrides={"exclusivity_scope": "CATEGORY"}
    )
    scenario["booking_one"] = book_asset(
        scenario["entitlement"]["id"], scenario["asset"]["id"],
        window_start="2026-09-10T18:00:00Z",
        window_end="2026-09-10T21:00:00Z",
        units_booked=4,
    )
    scenario["booking_two"] = book_asset(
        scenario["entitlement"]["id"], scenario["asset"]["id"],
        window_start="2026-09-20T18:00:00Z",
        window_end="2026-09-20T21:00:00Z",
        units_booked=6,
    )
    return scenario


def test_first_partial_delivery_moves_fulfillment_to_in_progress(api):
    """PRD §3.8: "This dimension moves `NOT_STARTED → IN_PROGRESS` as the first
    clause starts landing, `IN_PROGRESS → FULFILLED` when the last one lands, and
    `IN_PROGRESS → NOT_STARTED` again if every clause falls back to `PENDING` —
    for instance when the only delivered booking is made deficient by a rejected
    proof."
    PRD §3.8: "Otherwise, if every entitlement is `FULFILLED` or `WAIVED` the
    `fulfillment_status` is `FULFILLED`; if every entitlement is `PENDING` or
    `WAIVED` it is `NOT_STARTED`; in every other mix it is `IN_PROGRESS`."

    Design: Difficulty/non_linear_state_machine/fulfillment_dimension_advances_while_lifecycle_stays_active
    """
    scenario = _two_booking_scenario()
    before = read_contract(scenario["contract"]["id"])
    assert before["fulfillment_status"] == "NOT_STARTED"
    assert before["status"] == "ACTIVE"

    set_clock("2026-09-10T21:00:00Z")
    deliver_booking(scenario["booking_one"]["id"])

    mid = read_contract(scenario["contract"]["id"])
    assert mid["status"] == "ACTIVE", (
        "no lifecycle endpoint was called, so status must not move"
    )
    assert mid["fulfillment_status"] == "IN_PROGRESS"
    assert mid["delivered_media_value_cents"] == 1_350_000


def test_final_delivery_moves_fulfillment_to_fulfilled_while_status_stays_active(api):
    """PRD §3.8: "Otherwise, if every entitlement is `FULFILLED` or `WAIVED` the
    `fulfillment_status` is `FULFILLED`; if every entitlement is `PENDING` or
    `WAIVED` it is `NOT_STARTED`; in every other mix it is `IN_PROGRESS`."
    PRD §3.8: "It never touches the lifecycle `status`, and the lifecycle
    `status` never touches it, except at close."

    Design: Difficulty/non_linear_state_machine/fulfillment_dimension_advances_while_lifecycle_stays_active
    """
    scenario = _two_booking_scenario()

    set_clock("2026-09-10T21:00:00Z")
    deliver_booking(scenario["booking_one"]["id"])
    set_clock("2026-09-20T21:00:00Z")
    deliver_booking(scenario["booking_two"]["id"])

    contract = read_contract(scenario["contract"]["id"])
    assert contract["status"] == "ACTIVE"
    assert contract["fulfillment_status"] == "FULFILLED"
    assert contract["delivered_media_value_cents"] == 3_375_000

    entitlement = read_entitlement(scenario["entitlement"]["id"])
    assert entitlement["status"] == "FULFILLED"
    assert entitlement["delivery_pct"] == 100.00


# ---------------------------------------------------------------------------
# The rollup's input set
# ---------------------------------------------------------------------------
def test_delivery_rollup_counts_only_delivered_bookings(api):
    """PRD §3.8: "For one entitlement, `delivered_units` is the sum of
    `units_booked` over that entitlement's bookings whose `status` is `DELIVERED`
    and whose `proof_state` is anything other than `DEFICIENT`; bookings that are
    `SCHEDULED`, `CANCELLED` or `PREEMPTED` never count, and neither do deficient
    ones."
    PRD §3.8: "`delivery_pct` is 100 multiplied by `delivered_units`, divided by
    `promised_units`, rounded half up to 2 decimal places."

    Design: Corner/calculations/delivery_rollup_excludes_cancelled_and_scheduled_bookings
    """
    scenario = setup_contract_scenario(
        stage="ACTIVE", contract_overrides={"exclusivity_scope": "CATEGORY"}
    )
    to_deliver = book_asset(
        scenario["entitlement"]["id"], scenario["asset"]["id"],
        window_start="2026-09-10T18:00:00Z",
        window_end="2026-09-10T21:00:00Z", units_booked=4,
    )
    to_cancel = book_asset(
        scenario["entitlement"]["id"], scenario["asset"]["id"],
        window_start="2026-09-11T18:00:00Z",
        window_end="2026-09-11T21:00:00Z", units_booked=2,
    )
    to_leave_scheduled = book_asset(
        scenario["entitlement"]["id"], scenario["asset"]["id"],
        window_start="2026-09-12T18:00:00Z",
        window_end="2026-09-12T21:00:00Z", units_booked=3,
    )

    set_clock("2026-09-10T21:00:00Z")
    deliver_booking(to_deliver["id"])
    cancel_booking(to_cancel["id"], reason="Sponsor skipped the fixture")

    entitlement = read_entitlement(scenario["entitlement"]["id"])
    assert entitlement["delivered_units"] == 4
    assert entitlement["delivery_pct"] == 40.00
    assert entitlement["status"] == "PARTIAL"

    assert_reserved_units_total(read_inventory_asset(scenario["asset"]["id"]), 3)

    rows, meta = validate_paginated(
        api.list_asset_bookings(
            ACTIVATION,
            {
                "entitlement_id": scenario["entitlement"]["id"],
                "status": "SCHEDULED",
            },
        )
    )
    assert meta["total_count"] == 1, (
        f"exactly one booking is still SCHEDULED, got {meta['total_count']}"
    )
    assert rows[0]["id"] == to_leave_scheduled["id"]

    contract = read_contract(scenario["contract"]["id"])
    assert contract["delivered_media_value_cents"] == 1_350_000


# ---------------------------------------------------------------------------
# Every clock gate raises its own error
# ---------------------------------------------------------------------------
def test_each_clock_gate_raises_its_own_error(api):
    """PRD §3.1: "Moving to `IN_SEASON` requires that the season has actually
    opened — the logical clock must have reached `season_start` or passed it — and
    otherwise fails with `ERR_SEASON_NOT_STARTED`."
    PRD §3.5: "The owning property must be `IN_SEASON`, or the request fails with
    `ERR_PROPERTY_NOT_SELLING`, and the logical clock must have reached
    `term_start` or passed it, or it fails with `ERR_TERM_NOT_STARTED`."
    PRD §3.8: "An `ActivationManager` drives a booking `SCHEDULED → DELIVERED`
    once three conditions hold, evaluated in this order: the owning entitlement's
    contract must be `ACTIVE`, or the request fails with `ERR_CONTRACT_NOT_ACTIVE`;
    the logical clock must have reached the booking's `window_end` or passed it,
    or it fails with `ERR_DELIVERY_WINDOW_OPEN`; and when the occupied asset has
    `requires_staffing` set to true, the number of this booking's assignments
    whose `status` is `CHECKED_IN` must be at least the asset's `min_staff_count`,
    or it fails with `ERR_STAFFING_INCOMPLETE`."
    PRD §3.7: "Two conditions gate it: the owning booking must still be
    `SCHEDULED`, or the request fails with `ERR_INVALID_STATE`, and the logical
    clock must have reached the assignment's `shift_start` or passed it, or it
    fails with `ERR_SHIFT_NOT_STARTED`."
    PRD §3.9: "Two conditions gate it, in this order: the logical clock must have
    reached `term_end` or passed it, or the request fails with
    `ERR_TERM_NOT_ENDED`; and no booking belonging to any of the contract's
    entitlements may still be `SCHEDULED`, or it fails with `ERR_OPEN_BOOKINGS` —
    every occupation must have been delivered, cancelled or preempted before the
    books can be shut."

    Design: Corner/validations/clock_gate_violations_return_domain_specific_errors
    """
    scenario = setup_contract_scenario(
        stage="COUNTERSIGNED",
        contract_overrides={
            "exclusivity_scope": "CATEGORY",
            "term_start": "2026-09-15T00:00:00Z",
        },
    )
    property_id = scenario["property"]["id"]
    contract_id = scenario["contract"]["id"]

    early_season = api.transition_property(
        property_id, {"to_status": "IN_SEASON"}, ADMIN
    )
    validate_error(early_season, ApiErrorId.ERR_SEASON_NOT_STARTED.value)

    set_clock(SEASON_START)
    transition_property(property_id, "IN_SEASON")

    early_activate = api.activate_contract(contract_id, APPROVER)
    validate_error(early_activate, ApiErrorId.ERR_TERM_NOT_STARTED.value)

    set_clock("2026-09-15T00:00:00Z")
    validate_success(api.activate_contract(contract_id, APPROVER))

    booking = book_asset(
        scenario["entitlement"]["id"], scenario["asset"]["id"],
        window_start="2026-09-20T18:00:00Z",
        window_end="2026-09-20T21:00:00Z", units_booked=4,
    )

    early_deliver = api.deliver_asset_booking(booking["id"], ACTIVATION)
    validate_error(early_deliver, ApiErrorId.ERR_DELIVERY_WINDOW_OPEN.value)

    staffer = create_staff_member()
    assignment = assign_staff(
        booking["id"], staffer["id"],
        shift_start="2026-09-20T18:00:00Z",
        shift_end="2026-09-20T21:00:00Z",
    )
    early_check_in = api.check_in_staff_assignment(assignment["id"], ACTIVATION)
    validate_error(early_check_in, ApiErrorId.ERR_SHIFT_NOT_STARTED.value)

    early_close = api.close_contract(contract_id, APPROVER)
    validate_error(early_close, ApiErrorId.ERR_TERM_NOT_ENDED.value)

    assert read_contract(contract_id)["status"] == "ACTIVE"
