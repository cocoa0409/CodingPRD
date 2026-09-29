"""Stale parent versions, the cumulative footprint threshold and cascade visibility."""

from test_helpers import (
    AUDITOR,
    CLOCK_AT_LOAD_IN,
    CLOCK_AT_OPEN,
    CLOCK_START,
    EVENT_PERMIT_VALID_FROM,
    EVENT_PERMIT_VALID_UNTIL,
    GENERAL_MANAGER,
    GIANT_WHEEL,
    KIDDIE_WHIP,
    LOT_BOSS,
    TEA_CUPS,
    TRANSPORT_PERMIT_VALID_FROM,
    TRANSPORT_PERMIT_VALID_UNTIL,
    ApiErrorId,
    add_route_stop,
    approved_permit,
    assert_lot_ledgers,
    assert_readiness,
    assert_ride_allocation,
    assert_settlement,
    assert_settlement_amounts,
    begin_setup,
    book_crew,
    commit_route,
    create_ride_allocation_payload,
    create_settlement_payload,
    current_stop_version,
    draft_contract,
    execute_contract,
    open_gates,
    open_route,
    read_allocation,
    read_contract,
    read_readiness,
    read_ride,
    read_route_stop,
    record_sale,
    register_jurisdiction,
    register_ride,
    register_venue,
    register_worker,
    release_allocation,
    reserve_allocation,
    send_contract,
    sequence_route,
    set_logical_clock,
    setup_committed_route_with_sent_contract,
    validate_error,
    validate_paginated,
    validate_success,
)

CARNIVAL_DEAL = {
    "counterparty_name": "Franklin County Ag Society",
    "revenue_split_pct_operator": 65,
    "guarantee_cents": 900000,
    "ride_minimum_count": 1,
    "settlement_basis": "SPLIT_ONLY",
}
OPERATOR_SPEC = {
    "full_name": "Op One",
    "employment_type": "PERMANENT",
    "hourly_rate_cents": 1600,
    "certified_ride_classes": ["MAJOR"],
}
TIGHT_LOT = {
    "name": "Tight Lot",
    "city": "Newark",
    "lot_area_sqft": 9200,
    "power_amps_available": 1200,
    "expected_attendance": 42,
    "lot_surface": "PAVED",
}
INSPECTABLE_WHEEL = dict(GIANT_WHEEL, requires_state_inspection=False)
PLAIN_WHIP = dict(KIDDIE_WHIP, requires_state_inspection=False)
PLAIN_CUPS = dict(TEA_CUPS, requires_state_inspection=False)


def test_a_reservation_replaying_a_spent_lot_version_is_refused(api):
    """PRD §2.5: "Reserving a ride onto a lot requires the field
    `expected_route_stop_version` in the request body. This field is not optional:
    the caller must supply the `version` of the route stop as they last observed
    it. If that value does not equal the route stop's current `version`, the
    reservation is rejected with `ERR_STALE_ROUTE_STOP_VERSION` (HTTP 412)."

    PRD §2.4: "Recomputing a derived aggregate — a lot's footprint total, a
    route's guarantee total — is a mutation and therefore bumps `version` and
    refreshes `updated_at` on the row that owns the aggregate."

    PRD §3.3: "A ride's **charged footprint**, `footprint_charged_sqft`, is its
    bare `footprint_sqft` multiplied by a spacing multiplier that depends on class
    — 1.35 for `MAJOR`, 1.20 for `FLAT` and 1.10 for `KIDDIE` — and rounded **up**
    to a whole square foot."

    Design: Corner/cross_cutting_complexity_layers/allocation_create_refuses_a_route_stop_version_read_before_the_first_reservation
    """
    set_logical_clock(CLOCK_START)
    jurisdiction = register_jurisdiction()
    venue = register_venue(jurisdiction["id"])
    wheel = register_ride(INSPECTABLE_WHEEL)
    whip = register_ride(PLAIN_WHIP)
    route = open_route()
    stop = add_route_stop(route["id"], venue["id"])
    stale_version = stop["version"]

    first = validate_success(
        api.create_ride_allocation(
            create_ride_allocation_payload(wheel["id"], stop["id"], stale_version),
            LOT_BOSS,
        ),
        expected_status=201,
    )
    assert first["footprint_charged_sqft"] == 5414

    validate_error(
        api.create_ride_allocation(
            create_ride_allocation_payload(whip["id"], stop["id"], stale_version),
            LOT_BOSS,
        ),
        ApiErrorId.ERR_STALE_ROUTE_STOP_VERSION.value,
        expected_status=412,
    )
    charged = read_route_stop(stop["id"])
    assert charged["version"] == 2, "the refused write consumed no version"
    assert_lot_ledgers(charged, 5414, 375.0)

    second = validate_success(
        api.create_ride_allocation(
            create_ride_allocation_payload(
                whip["id"], stop["id"], charged["version"]
            ),
            LOT_BOSS,
        ),
        expected_status=201,
    )
    assert_ride_allocation(second)
    assert second["footprint_charged_sqft"] == 1925
    assert second["power_charged_amps"] == 100.0

    settled = read_route_stop(stop["id"])
    assert_lot_ledgers(settled, 7339, 475.0)
    assert settled["version"] == 3

    _rows, meta = validate_paginated(
        api.list_ride_allocations(LOT_BOSS, params={"route_stop_id": stop["id"]})
    )
    assert meta["total_count"] == 2


def test_a_settlement_built_on_pre_signature_deal_terms_is_refused(api):
    """PRD §2.5: "Creating a provisional settlement for a contract requires the
    field `expected_contract_version` in the request body, again non-optional,
    carrying the `version` of the contract as the caller last observed it. A
    mismatch with the contract's current `version` is rejected with
    `ERR_STALE_CONTRACT_VERSION` (HTTP 412)."

    PRD §3.8: "**Tax, rounded per channel then summed.** For each of the same three
    channels, multiply that channel's gross by the jurisdiction's
    `amusement_tax_pct` divided by 100 and round half-up to whole cents. The
    settlement's `tax_cents` is the sum of the three rounded channel taxes."

    Design: Corner/cross_cutting_complexity_layers/settlement_create_refuses_a_contract_version_read_before_the_deal_was_signed
    """
    set_logical_clock(CLOCK_START)
    jurisdiction = register_jurisdiction()
    venue = register_venue(jurisdiction["id"])
    wheel = register_ride(INSPECTABLE_WHEEL)
    operator = register_worker(**OPERATOR_SPEC)
    route = open_route()
    stop = add_route_stop(route["id"], venue["id"])
    contract = draft_contract(stop["id"], **CARNIVAL_DEAL)
    draft_version = contract["version"]

    sequence_route(route["id"])
    send_contract(contract["id"])
    commit_route(route["id"])
    reserve_allocation(wheel["id"], stop["id"])
    execute_contract(contract["id"])

    approved_permit(
        stop["id"],
        "TRANSPORT",
        TRANSPORT_PERMIT_VALID_FROM,
        TRANSPORT_PERMIT_VALID_UNTIL,
        axles_declared=4,
    )
    approved_permit(
        stop["id"], "EVENT", EVENT_PERMIT_VALID_FROM, EVENT_PERMIT_VALID_UNTIL
    )
    book_crew(
        stop["id"],
        operator["id"],
        "RIDE_OPERATOR",
        "2026-09-04T12:00:00Z",
        "2026-09-04T20:00:00Z",
    )
    set_logical_clock(CLOCK_AT_LOAD_IN)
    begin_setup(stop["id"])
    set_logical_clock(CLOCK_AT_OPEN)
    open_gates(stop["id"])
    set_logical_clock("2026-09-05T18:00:00Z")
    record_sale(stop["id"], "WRISTBAND", 100, 1000, "2026-09-05T18:00:00Z")

    signed_version = read_contract(contract["id"])["version"]
    assert signed_version != draft_version, (
        "send and execute both mutated the deal after it was drafted"
    )

    validate_error(
        api.create_settlement(
            create_settlement_payload(contract["id"], draft_version), AUDITOR
        ),
        ApiErrorId.ERR_STALE_CONTRACT_VERSION.value,
        expected_status=412,
    )
    _empty, empty_meta = validate_paginated(
        api.list_contract_settlements(contract["id"], AUDITOR)
    )
    assert empty_meta["total_count"] == 0
    assert read_contract(contract["id"])["version"] == signed_version, (
        "the refused settlement did not bump the deal"
    )

    settlement = validate_success(
        api.create_settlement(
            create_settlement_payload(contract["id"], signed_version), AUDITOR
        ),
        expected_status=201,
    )
    assert_settlement(settlement)
    assert settlement["status"] == "PROVISIONAL"
    assert settlement["variant"] == "PROVISIONAL"
    assert_settlement_amounts(
        settlement,
        gross_cents=100000,
        tax_cents=6500,
        taxable_net_cents=93500,
        split_share_cents=60775,
        settlement_due_cents=60775,
    )


def test_the_lot_footprint_admits_an_exact_fit_and_frees_it_on_release(api):
    """PRD §3.3: "If the lot's existing `allocated_sqft_used` plus the candidate's
    charged footprint exceeds that usable area, the reservation is refused with
    `ERR_LOT_CAPACITY_EXCEEDED`; a total exactly equal to the usable area is
    admitted."

    PRD §3.3: "Not all of a fairground can hold rides: the usable area is 80
    percent of `lot_area_sqft`, rounded **down** to a whole square foot, less a
    circulation reserve of half a square foot per projected attendee — that is,
    `expected_attendance` multiplied by 0.5 and rounded **up** to a whole square
    foot."

    PRD §2.10: "The **footprint ledger** of a lot, `allocated_sqft_used`, is the
    sum of `footprint_charged_sqft` over the lot's allocations whose status is
    `RESERVED`, `COMMITTED`, `INSPECTION_HELD` or `OPERATING`. The **power
    ledger**, `power_amps_used`, is the sum of `power_charged_amps` over that same
    status set, rounded to one decimal place."

    Design: Corner/cross_cutting_complexity_layers/the_cumulative_lot_footprint_threshold_admits_the_exact_fit_and_frees_it_on_release
    """
    set_logical_clock(CLOCK_START)
    jurisdiction = register_jurisdiction()
    tight = register_venue(jurisdiction["id"], **TIGHT_LOT)
    wheel = register_ride(INSPECTABLE_WHEEL)
    whip = register_ride(PLAIN_WHIP)
    cups = register_ride(PLAIN_CUPS)
    route = open_route(name="2026 Tight Circuit")
    stop = add_route_stop(route["id"], tight["id"])

    major = reserve_allocation(wheel["id"], stop["id"])
    assert major["footprint_charged_sqft"] == 5414
    assert major["power_charged_amps"] == 375.0

    kiddie = reserve_allocation(whip["id"], stop["id"])
    assert kiddie["footprint_charged_sqft"] == 1925
    assert_lot_ledgers(read_route_stop(stop["id"]), 7339, 475.0)

    validate_error(
        api.create_ride_allocation(
            create_ride_allocation_payload(
                cups["id"], stop["id"], current_stop_version(stop["id"])
            ),
            LOT_BOSS,
        ),
        ApiErrorId.ERR_LOT_CAPACITY_EXCEEDED.value,
        expected_status=422,
    )

    freed = release_allocation(kiddie["id"])
    assert freed["status"] == "RELEASED"
    assert_lot_ledgers(read_route_stop(stop["id"]), 5414, 375.0)

    retried = reserve_allocation(cups["id"], stop["id"])
    assert retried["footprint_charged_sqft"] == 11
    assert retried["power_charged_amps"] == 5.0
    assert_lot_ledgers(read_route_stop(stop["id"]), 5425, 380.0)

    _rows, meta = validate_paginated(
        api.list_ride_allocations(
            LOT_BOSS, params={"route_stop_id": stop["id"], "status": "RELEASED"}
        )
    )
    assert meta["total_count"] == 1


def test_the_execute_cascade_is_readable_on_the_very_next_request(api):
    """PRD §2.8: "The specification calls each of those steps a **cascade hop**,
    and every hop is part of the same request: there is no deferred or eventual
    reconciliation, and a caller who reads any touched row immediately afterwards
    sees its post-cascade state."

    PRD §3.2: "The first hop advances the lot `PLANNED → CONFIRMED`. The second hop
    commits every one of that lot's allocations sitting in `RESERVED`, processed
    oldest-first by `created_at`, because each commit may consume a scarce inspection
    slot. The third hop, caused by the second, sets each newly committed allocation's
    ride to `ASSIGNED` and — where the ride requires a state inspection and the lot's
    jurisdiction demands one — creates a single inspection order with `authority` of
    `STATE`, `status` of `SCHEDULED` and `attempt_number` of 1, on a date chosen by
    the slot ladder described in §3.5; where that ladder finds no day with free
    capacity, the allocation is instead moved `COMMITTED → INSPECTION_HELD` and no
    inspection row is written."

    PRD §3.7: "Unless the lot holds a permit whose `permit_type` is `EVENT`, whose
    `status` is `APPROVED`, whose `valid_from` is at or before the lot's
    `open_date` and whose `valid_until` is at or after its `close_date`, the
    posture is `PERMIT_HOLD`. The blocking error that posture would raise is
    `ERR_PERMIT_NOT_APPROVED`, except where such a permit exists but has gone
    `EXPIRED`, in which case it is `ERR_PERMIT_EXPIRED`."

    Design: Corner/consistency_model/every_cascaded_field_is_visible_in_the_same_response_cycle
    """
    ctx = setup_committed_route_with_sent_contract(
        contract_overrides=CARNIVAL_DEAL,
        ride_specs=[INSPECTABLE_WHEEL],
        jurisdiction_overrides={"requires_state_ride_inspection": False},
    )
    stop_id = ctx["stop"]["id"]
    ride_id = ctx["rides"][0]["id"]
    allocation_id = ctx["allocations"][0]["id"]

    executed = validate_success(
        api.execute_contract(ctx["contract"]["id"], GENERAL_MANAGER)
    )
    assert executed["status"] == "EXECUTED"

    first_stop_read = read_route_stop(stop_id)
    assert first_stop_read["status"] == "CONFIRMED"
    first_allocation_read = read_allocation(allocation_id)
    assert first_allocation_read["status"] == "COMMITTED"
    first_ride_read = read_ride(ride_id)
    assert first_ride_read["status"] == "ASSIGNED"

    first_readiness = read_readiness(stop_id, LOT_BOSS)
    assert_readiness(first_readiness)
    assert first_readiness["compliance_posture"] == "PERMIT_HOLD"
    assert (
        first_readiness["blocking_error_id"]
        == ApiErrorId.ERR_PERMIT_NOT_APPROVED.value
    )
    assert first_readiness["committed_ride_count"] == 1
    assert first_readiness["ride_minimum_required"] == 1

    assert read_route_stop(stop_id) == first_stop_read
    assert read_allocation(allocation_id) == first_allocation_read
    assert read_ride(ride_id) == first_ride_read
    assert read_readiness(stop_id, LOT_BOSS) == first_readiness
