"""Scheduling occupations: the changeover buffer, capacity and the unwind path."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_asset_booking,
    assert_reserved_units_total,
    assert_staff_assignment,
    assign_staff,
    asset_version,
    book_asset,
    cancel_booking,
    create_staff_member,
    read_assignment,
    read_booking,
    read_contract,
    read_entitlement,
    read_inventory_asset,
    setup_contract_scenario,
    setup_countersigned_contract_in_season,
    setup_delivered_booking,
    setup_two_contract_property,
    validate_error,
    validate_paginated,
    validate_success,
)

ACTIVATION = TEST_USERS["activation_headers"]


def _booking_payload(entitlement_id, asset_id, version, **overrides):
    payload = {
        "entitlement_id": entitlement_id,
        "inventory_asset_id": asset_id,
        "window_start": "2026-09-10T18:00:00Z",
        "window_end": "2026-09-10T21:00:00Z",
        "units_booked": 2,
        "expected_inventory_asset_version": version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# The changeover buffer between two sponsors on one asset
# ---------------------------------------------------------------------------
def test_changeover_buffer_rejects_a_gap_shorter_than_the_buffer(api):
    """PRD §3.6: "Consider every other booking already on this asset whose
    `status` is `SCHEDULED` or `DELIVERED`, that does **not** intersect the new
    half-open window, and whose entitlement belongs to a **different** contract
    than the new booking's."
    PRD §3.6: "For each such neighbour the idle gap must be at least the asset's
    `changeover_buffer_minutes`: when the new window follows the neighbour, the
    gap is measured from the neighbour's `window_end` to the new `window_start`;
    when the new window precedes it, the gap is measured from the new
    `window_end` to the neighbour's `window_start`. A gap shorter than the buffer
    is rejected with `ERR_BOOKING_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/asset_half_open_window_with_changeover_buffer_boundary
    """
    estate = setup_two_contract_property(activate_second=True)
    book_asset(
        estate["entitlement_one"]["id"], estate["asset"]["id"],
        window_start="2026-09-10T18:00:00Z",
        window_end="2026-09-10T21:00:00Z",
        units_booked=4,
    )

    response = api.create_asset_booking(
        _booking_payload(
            estate["entitlement_two"]["id"], estate["asset"]["id"],
            asset_version(estate["asset"]["id"]),
            window_start="2026-09-10T21:15:00Z",
            window_end="2026-09-10T23:00:00Z",
        ),
        ACTIVATION,
    )
    validate_error(response, ApiErrorId.ERR_BOOKING_WINDOW_CONFLICT.value)
    assert response.status_code == 409, (
        "a 15-minute gap is shorter than the asset's 30-minute changeover buffer"
    )


def test_changeover_buffer_admits_a_gap_equal_to_the_buffer(api):
    """PRD §3.6: "The occupation window is treated as half-open: `window_start`
    is inside the window and `window_end` is not, so a booking that ends exactly
    when another begins does not intersect it."
    PRD §3.6: "For each such neighbour the idle gap must be at least the asset's
    `changeover_buffer_minutes`: when the new window follows the neighbour, the
    gap is measured from the neighbour's `window_end` to the new `window_start`;
    when the new window precedes it, the gap is measured from the new
    `window_end` to the neighbour's `window_start`. A gap shorter than the buffer
    is rejected with `ERR_BOOKING_WINDOW_CONFLICT`."
    PRD §3.6: "An accepted booking opens in `SCHEDULED` with `proof_state` at
    `NONE`, `verified_impressions` at 0 and `delivered_at` null. It raises the
    asset's `reserved_units_total` by `units_booked` and increments the asset's
    `version` by 1 — which is precisely what makes the next writer's stale
    `expected_inventory_asset_version` fail."

    Design: Difficulty/resource_temporal_overlap/asset_half_open_window_with_changeover_buffer_boundary
    """
    estate = setup_two_contract_property(activate_second=True)
    book_asset(
        estate["entitlement_one"]["id"], estate["asset"]["id"],
        window_start="2026-09-10T18:00:00Z",
        window_end="2026-09-10T21:00:00Z",
        units_booked=4,
    )

    response = api.create_asset_booking(
        _booking_payload(
            estate["entitlement_two"]["id"], estate["asset"]["id"],
            asset_version(estate["asset"]["id"]),
            window_start="2026-09-10T21:30:00Z",
            window_end="2026-09-10T23:00:00Z",
        ),
        ACTIVATION,
    )
    booking = validate_success(response, 201)
    assert_asset_booking(booking)
    assert booking["status"] == "SCHEDULED", (
        "a gap of exactly the 30-minute buffer is admitted"
    )
    assert booking["proof_state"] == "NONE"
    assert booking["verified_impressions"] == 0
    assert booking["delivered_at"] is None

    assert_reserved_units_total(read_inventory_asset(estate["asset"]["id"]), 6)


# ---------------------------------------------------------------------------
# Capacity on the intersecting window
# ---------------------------------------------------------------------------
def test_capacity_admits_a_request_landing_exactly_on_the_ceiling(api):
    """PRD §3.6: "The second constraint is capacity. Sum `units_booked` over
    every booking on the asset whose `status` is `SCHEDULED` or `DELIVERED` and
    whose half-open window intersects the new one, add the new `units_booked`, and
    the result must be no greater than the asset's `capacity_units`; exceeding it
    is `ERR_ASSET_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/asset_capacity_admits_exact_equality_and_rejects_one_more_unit
    """
    scenario = setup_contract_scenario(
        stage="ACTIVE", contract_overrides={"exclusivity_scope": "CATEGORY"}
    )
    book_asset(
        scenario["entitlement"]["id"], scenario["asset"]["id"], units_booked=4
    )

    response = api.create_asset_booking(
        _booking_payload(
            scenario["entitlement"]["id"], scenario["asset"]["id"],
            asset_version(scenario["asset"]["id"]),
            units_booked=2,
        ),
        ACTIVATION,
    )
    booking = validate_success(response, 201)
    assert booking["status"] == "SCHEDULED", (
        "4 units already held plus 2 more lands exactly on capacity 6"
    )
    assert_reserved_units_total(read_inventory_asset(scenario["asset"]["id"]), 6)


def test_capacity_rejects_one_unit_over_the_ceiling(api):
    """PRD §3.6: "The second constraint is capacity. Sum `units_booked` over
    every booking on the asset whose `status` is `SCHEDULED` or `DELIVERED` and
    whose half-open window intersects the new one, add the new `units_booked`, and
    the result must be no greater than the asset's `capacity_units`; exceeding it
    is `ERR_ASSET_CAPACITY_EXCEEDED`."
    PRD §2.9: "First, `reserved_units_total` on an inventory asset is at all
    times the sum of `units_booked` over that asset's bookings whose `status` is
    `SCHEDULED`: creating a booking raises it, and cancellation, delivery and
    preemption each lower it by exactly the units the booking held, in every case
    incrementing the asset's `version` by 1."

    Design: Difficulty/boundary_precision_check/asset_capacity_admits_exact_equality_and_rejects_one_more_unit
    """
    scenario = setup_contract_scenario(
        stage="ACTIVE", contract_overrides={"exclusivity_scope": "CATEGORY"}
    )
    book_asset(
        scenario["entitlement"]["id"], scenario["asset"]["id"], units_booked=4
    )
    book_asset(
        scenario["entitlement"]["id"], scenario["asset"]["id"], units_booked=2
    )

    response = api.create_asset_booking(
        _booking_payload(
            scenario["entitlement"]["id"], scenario["asset"]["id"],
            asset_version(scenario["asset"]["id"]),
            units_booked=1,
        ),
        ACTIVATION,
    )
    validate_error(response, ApiErrorId.ERR_ASSET_CAPACITY_EXCEEDED.value)
    assert response.status_code == 409

    assert_reserved_units_total(read_inventory_asset(scenario["asset"]["id"]), 6)


# ---------------------------------------------------------------------------
# Order of rejection between the state guard, the buffer and capacity
# ---------------------------------------------------------------------------
def test_contract_state_guard_precedes_the_changeover_buffer(api):
    """PRD §3.6: "The contract that owns the entitlement must be `ACTIVE`, or the
    request fails with `ERR_CONTRACT_NOT_ACTIVE`, and the asset must be
    `AVAILABLE`, or it fails with `ERR_ASSET_UNAVAILABLE` — an asset in
    `MAINTENANCE` or `RETIRED` takes no new occupations."
    PRD §2.8: "8. Cross-entity state guards — `ERR_PROPERTY_NOT_SELLING`,
    `ERR_NO_PUBLISHED_RATE_CARD`, `ERR_CONTRACT_NOT_ACTIVE`,
    `ERR_ASSET_UNAVAILABLE`, `ERR_STAFF_INACTIVE` and `ERR_OPEN_CONTRACTS`."
    PRD §2.8: "15. Neighbourhood separation — `ERR_BOOKING_WINDOW_CONFLICT` for
    the asset changeover buffer and `ERR_STAFF_SHIFT_CONFLICT` for staff overlap
    and rest."

    Design: Difficulty/priority_pair_validation_conflict/contract_state_error_wins_over_booking_buffer_conflict
    """
    estate = setup_two_contract_property(activate_second=False)
    book_asset(
        estate["entitlement_one"]["id"], estate["asset"]["id"],
        window_start="2026-09-10T18:00:00Z",
        window_end="2026-09-10T21:00:00Z",
        units_booked=4,
    )

    response = api.create_asset_booking(
        _booking_payload(
            estate["entitlement_two"]["id"], estate["asset"]["id"],
            asset_version(estate["asset"]["id"]),
            window_start="2026-09-10T21:15:00Z",
            window_end="2026-09-10T23:00:00Z",
            units_booked=1,
        ),
        ACTIVATION,
    )
    validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value)
    assert response.status_code == 409, (
        "the second contract is only COUNTERSIGNED, so the state guard fires "
        "before the 15-minute buffer breach is ever considered"
    )


def test_rejected_booking_reserves_no_units_and_bumps_no_version(api):
    """PRD §3.6: "An accepted booking opens in `SCHEDULED` with `proof_state` at
    `NONE`, `verified_impressions` at 0 and `delivered_at` null. It raises the
    asset's `reserved_units_total` by `units_booked` and increments the asset's
    `version` by 1 — which is precisely what makes the next writer's stale
    `expected_inventory_asset_version` fail."
    PRD §3.6: "The contract that owns the entitlement must be `ACTIVE`, or the
    request fails with `ERR_CONTRACT_NOT_ACTIVE`, and the asset must be
    `AVAILABLE`, or it fails with `ERR_ASSET_UNAVAILABLE` — an asset in
    `MAINTENANCE` or `RETIRED` takes no new occupations."

    Design: Difficulty/priority_pair_validation_conflict/contract_state_error_wins_over_booking_buffer_conflict
    """
    estate = setup_two_contract_property(activate_second=False)
    book_asset(
        estate["entitlement_one"]["id"], estate["asset"]["id"],
        window_start="2026-09-10T18:00:00Z",
        window_end="2026-09-10T21:00:00Z",
        units_booked=4,
    )
    before = read_inventory_asset(estate["asset"]["id"])

    refused = api.create_asset_booking(
        _booking_payload(
            estate["entitlement_two"]["id"], estate["asset"]["id"],
            before["version"],
            window_start="2026-09-10T21:15:00Z",
            window_end="2026-09-10T23:00:00Z",
            units_booked=1,
        ),
        ACTIVATION,
    )
    validate_error(refused, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value)

    after = read_inventory_asset(estate["asset"]["id"])
    assert_reserved_units_total(after, 4)
    assert after["version"] == before["version"], (
        "a rejected booking reserves nothing and leaves the asset's version "
        f"untouched, got {after['version']} vs {before['version']}"
    )


def test_changeover_buffer_precedes_the_capacity_ceiling(api):
    """PRD §2.8: "15. Neighbourhood separation — `ERR_BOOKING_WINDOW_CONFLICT`
    for the asset changeover buffer and `ERR_STAFF_SHIFT_CONFLICT` for staff
    overlap and rest."
    PRD §2.8: "16. Capacity and completeness — `ERR_ASSET_CAPACITY_EXCEEDED`,
    `ERR_STAFFING_INCOMPLETE`, `ERR_DUPLICATE_CLAUSE_REF`,
    `ERR_DUPLICATE_RATE_LINE`, `ERR_NO_ENTITLEMENTS`, `ERR_REVISION_LIMIT_REACHED`
    and `ERR_OPEN_BOOKINGS`."
    PRD §3.6: "Two geometric constraints then guard the asset. The first is the
    changeover buffer."

    Design: Difficulty/priority_pair_validation_conflict/buffer_temporal_error_wins_over_capacity_constraint
    """
    estate = setup_two_contract_property(activate_second=True)
    book_asset(
        estate["entitlement_one"]["id"], estate["asset"]["id"],
        window_start="2026-09-10T18:00:00Z",
        window_end="2026-09-10T21:00:00Z",
        units_booked=4,
    )
    book_asset(
        estate["entitlement_one"]["id"], estate["asset"]["id"],
        window_start="2026-09-10T22:00:00Z",
        window_end="2026-09-10T23:30:00Z",
        units_booked=4,
    )

    response = api.create_asset_booking(
        _booking_payload(
            estate["entitlement_two"]["id"], estate["asset"]["id"],
            asset_version(estate["asset"]["id"]),
            window_start="2026-09-10T21:15:00Z",
            window_end="2026-09-10T23:00:00Z",
            units_booked=3,
        ),
        ACTIVATION,
    )
    validate_error(response, ApiErrorId.ERR_BOOKING_WINDOW_CONFLICT.value)
    assert response.status_code == 409, (
        "the request breaches the buffer against the 18:00-21:00 neighbour and "
        "would also push the intersecting occupancy to 7 against capacity 6"
    )


def test_buffer_rejection_creates_no_booking_for_the_second_contract(api):
    """PRD §2.9: "First, `reserved_units_total` on an inventory asset is at all
    times the sum of `units_booked` over that asset's bookings whose `status` is
    `SCHEDULED`: creating a booking raises it, and cancellation, delivery and
    preemption each lower it by exactly the units the booking held, in every case
    incrementing the asset's `version` by 1."
    PRD §3.6: "A gap shorter than the buffer is rejected with
    `ERR_BOOKING_WINDOW_CONFLICT`."
    PRD §3.6: "Bookings can be enumerated and narrowed by `entitlement_id`, by
    `inventory_asset_id` or by `status`."

    Design: Difficulty/priority_pair_validation_conflict/buffer_temporal_error_wins_over_capacity_constraint
    """
    estate = setup_two_contract_property(activate_second=True)
    book_asset(
        estate["entitlement_one"]["id"], estate["asset"]["id"],
        window_start="2026-09-10T18:00:00Z",
        window_end="2026-09-10T21:00:00Z",
        units_booked=4,
    )
    book_asset(
        estate["entitlement_one"]["id"], estate["asset"]["id"],
        window_start="2026-09-10T22:00:00Z",
        window_end="2026-09-10T23:30:00Z",
        units_booked=4,
    )

    refused = api.create_asset_booking(
        _booking_payload(
            estate["entitlement_two"]["id"], estate["asset"]["id"],
            asset_version(estate["asset"]["id"]),
            window_start="2026-09-10T21:15:00Z",
            window_end="2026-09-10T23:00:00Z",
            units_booked=3,
        ),
        ACTIVATION,
    )
    validate_error(refused, ApiErrorId.ERR_BOOKING_WINDOW_CONFLICT.value)

    assert_reserved_units_total(read_inventory_asset(estate["asset"]["id"]), 8)

    rows, meta = validate_paginated(
        api.list_asset_bookings(
            ACTIVATION, {"entitlement_id": estate["entitlement_two"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"the refused request created no booking, got {meta['total_count']}"
    )
    assert rows == []


# ---------------------------------------------------------------------------
# The booking endpoint depends on the owning contract's lifecycle
# ---------------------------------------------------------------------------
def test_booking_is_refused_while_the_owning_contract_is_only_countersigned(api):
    """PRD §3.6: "The contract that owns the entitlement must be `ACTIVE`, or the
    request fails with `ERR_CONTRACT_NOT_ACTIVE`, and the asset must be
    `AVAILABLE`, or it fails with `ERR_ASSET_UNAVAILABLE` — an asset in
    `MAINTENANCE` or `RETIRED` takes no new occupations."

    Design: Difficulty/cross_entity_state_dependency/booking_create_blocked_until_owning_contract_is_active
    """
    scenario = setup_countersigned_contract_in_season(
        contract_overrides={"exclusivity_scope": "CATEGORY"}
    )
    version_before = asset_version(scenario["asset"]["id"])

    response = api.create_asset_booking(
        _booking_payload(
            scenario["entitlement"]["id"], scenario["asset"]["id"],
            version_before, units_booked=4,
        ),
        ACTIVATION,
    )
    validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value)

    asset = read_inventory_asset(scenario["asset"]["id"])
    assert_reserved_units_total(asset, 0)
    assert asset["version"] == version_before


def test_same_booking_payload_succeeds_once_the_contract_is_active(api):
    """PRD §3.5: "Activation follows once the season and the term have both
    begun. A `ContractApprover` drives the contract `COUNTERSIGNED → ACTIVE` with
    no request body."
    PRD §3.6: "The contract that owns the entitlement must be `ACTIVE`, or the
    request fails with `ERR_CONTRACT_NOT_ACTIVE`, and the asset must be
    `AVAILABLE`, or it fails with `ERR_ASSET_UNAVAILABLE` — an asset in
    `MAINTENANCE` or `RETIRED` takes no new occupations."
    PRD §3.6: "An accepted booking opens in `SCHEDULED` with `proof_state` at
    `NONE`, `verified_impressions` at 0 and `delivered_at` null. It raises the
    asset's `reserved_units_total` by `units_booked` and increments the asset's
    `version` by 1 — which is precisely what makes the next writer's stale
    `expected_inventory_asset_version` fail."

    Design: Difficulty/cross_entity_state_dependency/booking_create_blocked_until_owning_contract_is_active
    """
    scenario = setup_countersigned_contract_in_season(
        contract_overrides={"exclusivity_scope": "CATEGORY"}
    )
    captured_version = asset_version(scenario["asset"]["id"])
    payload = _booking_payload(
        scenario["entitlement"]["id"], scenario["asset"]["id"],
        captured_version, units_booked=4,
    )

    refused = api.create_asset_booking(payload, ACTIVATION)
    validate_error(refused, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value)

    activated = validate_success(
        api.activate_contract(
            scenario["contract"]["id"], TEST_USERS["approver_headers"]
        )
    )
    assert activated["status"] == "ACTIVE"

    accepted = validate_success(api.create_asset_booking(payload, ACTIVATION), 201)
    assert accepted["status"] == "SCHEDULED", (
        "the identical payload, including the version the rejected attempt left "
        "untouched, is admitted once the contract is ACTIVE"
    )
    assert_reserved_units_total(
        read_inventory_asset(scenario["asset"]["id"]), 4
    )


# ---------------------------------------------------------------------------
# Booking then cancelling conserves the unit ledger
# ---------------------------------------------------------------------------
def test_booking_then_cancel_returns_reserved_units_to_zero(api):
    """PRD §2.9: "First, `reserved_units_total` on an inventory asset is at all
    times the sum of `units_booked` over that asset's bookings whose `status` is
    `SCHEDULED`: creating a booking raises it, and cancellation, delivery and
    preemption each lower it by exactly the units the booking held, in every case
    incrementing the asset's `version` by 1."
    PRD §3.6: "It drives the booking `SCHEDULED → CANCELLED`, drops the asset's
    `reserved_units_total` by exactly the `units_booked` the booking held —
    restoring the value the asset carried before the booking was created — and
    increments the asset's `version` by 1."

    Design: Difficulty/compensating_invariant/booking_then_cancel_conserves_asset_reserved_units
    """
    scenario = setup_contract_scenario(
        stage="ACTIVE", contract_overrides={"exclusivity_scope": "CATEGORY"}
    )
    before = read_inventory_asset(scenario["asset"]["id"])
    assert_reserved_units_total(before, 0)

    booking = book_asset(
        scenario["entitlement"]["id"], scenario["asset"]["id"], units_booked=4
    )
    mid = read_inventory_asset(scenario["asset"]["id"])
    assert_reserved_units_total(mid, 4)

    cancelled = cancel_booking(
        booking["id"], reason="Sponsor pulled the creative"
    )
    assert cancelled["status"] == "CANCELLED"

    after = read_inventory_asset(scenario["asset"]["id"])
    assert_reserved_units_total(after, 0)
    assert after["reserved_units_total"] == before["reserved_units_total"]
    assert after["version"] > mid["version"], (
        "the cancellation is itself a mutation of the asset"
    )


def test_cancelled_booking_never_contributed_delivered_value(api):
    """PRD §3.6: "No entitlement or contract money changes, because a
    `SCHEDULED` booking never contributed to `delivered_units` in the first
    place."
    PRD §3.8: "For one entitlement, `delivered_units` is the sum of
    `units_booked` over that entitlement's bookings whose `status` is `DELIVERED`
    and whose `proof_state` is anything other than `DEFICIENT`; bookings that are
    `SCHEDULED`, `CANCELLED` or `PREEMPTED` never count, and neither do deficient
    ones."

    Design: Difficulty/compensating_invariant/booking_then_cancel_conserves_asset_reserved_units
    """
    scenario = setup_contract_scenario(
        stage="ACTIVE", contract_overrides={"exclusivity_scope": "CATEGORY"}
    )
    booking = book_asset(
        scenario["entitlement"]["id"], scenario["asset"]["id"], units_booked=4
    )
    cancel_booking(booking["id"], reason="Sponsor pulled the creative")

    entitlement = read_entitlement(scenario["entitlement"]["id"])
    assert entitlement["delivered_units"] == 0
    assert entitlement["delivery_pct"] == 0.00
    assert entitlement["status"] == "PENDING"

    contract = read_contract(scenario["contract"]["id"])
    assert contract["delivered_media_value_cents"] == 0


# ---------------------------------------------------------------------------
# Interval, reference and availability guards
# ---------------------------------------------------------------------------
def test_booking_interval_and_reference_violations_return_declared_errors(api):
    """PRD §3.6: "Next the supplied `inventory_asset_id` must equal the
    entitlement's own `inventory_asset_id`, since a clause can only be delivered
    on the asset it names; a divergence is `ERR_ASSET_MISMATCH`. Then the window
    itself is checked: `window_end` must be strictly after `window_start`, or the
    request fails with `ERR_INVALID_WINDOW` (422), and the whole window must lie
    inside the owning contract's term, between `term_start` and `term_end`
    inclusive, or it fails with `ERR_WINDOW_OUTSIDE_TERM` (409)."

    Design: Corner/validations/booking_interval_and_reference_violations_return_declared_errors
    """
    scenario = setup_contract_scenario(
        stage="ACTIVE",
        asset_specs=[
            {
                "name": "North LED Ribbon",
                "asset_class": "DIGITAL_BOARD",
                "capacity_units": 6,
                "changeover_buffer_minutes": 30,
            },
            {
                "name": "South Fascia Board",
                "asset_class": "SIGNAGE",
                "capacity_units": 3,
            },
        ],
        contract_overrides={"exclusivity_scope": "CATEGORY"},
    )
    entitlement_id = scenario["entitlement"]["id"]
    board = scenario["assets"][0]
    signage = scenario["assets"][1]
    board_version = asset_version(board["id"])

    zero_length = api.create_asset_booking(
        _booking_payload(
            entitlement_id, board["id"], board_version,
            window_start="2026-09-10T18:00:00Z",
            window_end="2026-09-10T18:00:00Z",
        ),
        ACTIVATION,
    )
    validate_error(zero_length, ApiErrorId.ERR_INVALID_WINDOW.value)
    assert zero_length.status_code == 422

    outside_term = api.create_asset_booking(
        _booking_payload(
            entitlement_id, board["id"], board_version,
            window_start="2027-01-05T18:00:00Z",
            window_end="2027-01-05T21:00:00Z",
        ),
        ACTIVATION,
    )
    validate_error(outside_term, ApiErrorId.ERR_WINDOW_OUTSIDE_TERM.value)
    assert outside_term.status_code == 409

    wrong_asset = api.create_asset_booking(
        _booking_payload(
            entitlement_id, signage["id"], asset_version(signage["id"])
        ),
        ACTIVATION,
    )
    validate_error(wrong_asset, ApiErrorId.ERR_ASSET_MISMATCH.value)
    assert wrong_asset.status_code == 409

    assert_reserved_units_total(read_inventory_asset(board["id"]), 0)


def test_unavailable_asset_and_inactive_staff_are_rejected(api):
    """PRD §3.6: "The contract that owns the entitlement must be `ACTIVE`, or the
    request fails with `ERR_CONTRACT_NOT_ACTIVE`, and the asset must be
    `AVAILABLE`, or it fails with `ERR_ASSET_UNAVAILABLE` — an asset in
    `MAINTENANCE` or `RETIRED` takes no new occupations."
    PRD §3.7: "Only an `ACTIVE` staffer may be rostered; an `INACTIVE` one yields
    `ERR_STAFF_INACTIVE`."

    Design: Corner/validations/unavailable_asset_and_inactive_staff_are_rejected
    """
    scenario = setup_contract_scenario(
        stage="ACTIVE",
        asset_specs=[
            {
                "name": "West Ribbon Under Repair",
                "asset_class": "DIGITAL_BOARD",
                "capacity_units": 4,
                "status": "MAINTENANCE",
            },
            {
                "name": "North LED Ribbon",
                "asset_class": "DIGITAL_BOARD",
                "capacity_units": 6,
                "changeover_buffer_minutes": 30,
            },
        ],
        entitlement_specs=[
            {"asset_index": 0, "clause_ref": "5.1", "promised_units": 4},
            {"asset_index": 1, "clause_ref": "5.2", "promised_units": 10},
        ],
        contract_overrides={"exclusivity_scope": "CATEGORY"},
    )
    maintenance_asset = scenario["assets"][0]
    available_asset = scenario["assets"][1]
    inactive_staffer = create_staff_member(
        full_name="Ivo Marek", hourly_rate_cents=3_200, status="INACTIVE"
    )

    blocked = api.create_asset_booking(
        _booking_payload(
            scenario["entitlements"][0]["id"], maintenance_asset["id"],
            asset_version(maintenance_asset["id"]),
        ),
        ACTIVATION,
    )
    validate_error(blocked, ApiErrorId.ERR_ASSET_UNAVAILABLE.value)

    booking = book_asset(
        scenario["entitlements"][1]["id"], available_asset["id"], units_booked=2
    )

    rostered = api.create_staff_assignment(
        booking["id"],
        {
            "staff_member_id": inactive_staffer["id"],
            "shift_start": "2026-09-10T18:00:00Z",
            "shift_end": "2026-09-10T21:00:00Z",
            "role_label": "Brand Ambassador",
        },
        ACTIVATION,
    )
    validate_error(rostered, ApiErrorId.ERR_STAFF_INACTIVE.value)

    assert_reserved_units_total(read_inventory_asset(maintenance_asset["id"]), 0)
    assert_reserved_units_total(read_inventory_asset(available_asset["id"]), 2)


# ---------------------------------------------------------------------------
# Terminal bookings and the cancellation cascade
# ---------------------------------------------------------------------------
def test_cancelling_a_delivered_booking_is_rejected(api):
    """PRD §3.6: "Requesting delivery or cancellation of a booking that has
    already reached `DELIVERED`, `CANCELLED` or `PREEMPTED` is rejected
    unconditionally with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/booking_cancel_after_delivery_returns_invalid_state
    """
    scenario = setup_delivered_booking(
        units_booked=4, contract_overrides={"exclusivity_scope": "CATEGORY"}
    )

    response = api.cancel_asset_booking(
        scenario["booking"]["id"], {"reason": "too late"}, ACTIVATION
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    assert response.status_code == 409

    booking = read_booking(scenario["booking"]["id"])
    assert booking["status"] == "DELIVERED"

    entitlement = read_entitlement(scenario["entitlement"]["id"])
    assert entitlement["delivered_units"] == 4

    assert_reserved_units_total(read_inventory_asset(scenario["asset"]["id"]), 0)


def test_cancelling_releases_the_shift_and_the_reserved_units(api):
    """PRD §3.6: "Every one of the booking's staff assignments still sitting at
    `ASSIGNED` or `CHECKED_IN` is moved to `RELEASED`, lowering each staffer's
    `scheduled_minutes` accordingly."
    PRD §3.6: "It drives the booking `SCHEDULED → CANCELLED`, drops the asset's
    `reserved_units_total` by exactly the `units_booked` the booking held —
    restoring the value the asset carried before the booking was created — and
    increments the asset's `version` by 1."

    Design: Corner/state_machines/cancel_booking_releases_assignment_and_reserved_units
    """
    scenario = setup_contract_scenario(
        stage="ACTIVE", contract_overrides={"exclusivity_scope": "CATEGORY"}
    )
    booking = book_asset(
        scenario["entitlement"]["id"], scenario["asset"]["id"], units_booked=4
    )
    staffer = create_staff_member()
    assignment = assign_staff(
        booking["id"], staffer["id"],
        shift_start="2026-09-10T18:00:00Z",
        shift_end="2026-09-10T21:00:00Z",
    )
    assert_staff_assignment(assignment)
    assert assignment["status"] == "ASSIGNED"

    cancelled = cancel_booking(booking["id"], reason="Creative not approved")
    assert cancelled["status"] == "CANCELLED"

    assert read_assignment(assignment["id"])["status"] == "RELEASED"

    entitlement = read_entitlement(scenario["entitlement"]["id"])
    assert entitlement["status"] == "PENDING"
    assert entitlement["delivered_units"] == 0

    assert_reserved_units_total(read_inventory_asset(scenario["asset"]["id"]), 0)
