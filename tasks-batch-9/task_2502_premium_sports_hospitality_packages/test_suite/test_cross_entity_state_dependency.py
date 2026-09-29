"""Requests rejected because of the state of a row they never name.

Committing inventory depends on the rights deal reached two hops away through
the block, and rostering a host depends on the build's state, whose accepted set
has two members rather than one.
"""

from typing import Any, Dict

from test_helpers import (
    CLIENT_SERVICE_AGENT,
    ERR_ALLOCATION_UNITS_UNAVAILABLE,
    ERR_ASSIGNMENT_SCOPE_MISMATCH,
    ERR_CHANNEL_OR_DEAL_MISMATCH,
    ERR_INVALID_BUILD_STATE,
    OPERATIONS_MANAGER,
    RIGHTS_MANAGER,
    ApiClient,
    allocate_booking,
    allocate_payload,
    approve_build,
    assert_block_position,
    assert_total_count,
    confirm_tranche,
    get_success_data,
    host_assignment_payload,
    make_block,
    make_booking,
    make_build,
    make_client,
    make_committed_deal,
    make_event,
    make_host,
    make_published_gold_package,
    make_tranche,
    read_block,
    read_booking,
    read_host,
    reset_clock,
    validate_error,
)


def _reserved_booking_on_a_block_whose_deal_has_released_nothing(
    api: ApiClient,
) -> Dict[str, Any]:
    """A correct-looking allocation target whose rights deal is still COMMITTED.

    The block is created while the deal is merely COMMITTED, which is legal, so
    it holds 0 allocated units. The promise exists but has not been confirmed,
    so the deal has released nothing.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"])
    block = make_block(api, deal["id"], channel="CORPORATE", target_units=40,
                       priority_rank=1)
    package = make_published_gold_package(api, event["id"])
    client = make_client(api)
    booking = make_booking(api, client["id"], package["id"], channel="CORPORATE",
                           units=10)
    tranche = make_tranche(api, deal["id"], promised_units=60)
    return {
        "event": event,
        "deal": deal,
        "block": block,
        "package": package,
        "client": client,
        "booking": booking,
        "tranche": tranche,
    }


def _allocated_booking_with_a_planned_build_and_an_idle_host(
    api: ApiClient,
) -> Dict[str, Any]:
    """An ALLOCATED booking, a PLANNED build on its fixture, and a free host."""
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"])
    block = make_block(api, deal["id"], channel="CORPORATE", target_units=40,
                       priority_rank=1)
    tranche = make_tranche(api, deal["id"], promised_units=60)
    confirm_tranche(api, tranche["id"], deal["id"], 60)
    package = make_published_gold_package(api, event["id"])
    client = make_client(api)
    booking = make_booking(api, client["id"], package["id"], channel="CORPORATE",
                           units=10)
    allocated = allocate_booking(api, booking["id"], block["id"])
    build = make_build(api, event["id"])
    host = make_host(api, max_concurrent_bookings=2)
    return {
        "event": event,
        "deal": deal,
        "block": block,
        "package": package,
        "client": client,
        "booking": allocated,
        "build": build,
        "host": host,
        "payload": host_assignment_payload(host["id"], booking["id"], build["id"]),
    }


def _attempt_allocation(api: ApiClient, booking_id: str, block_id: str):
    """Fire the allocate call with the block's current version, without asserting."""
    version = read_block(api, block_id)["version"]
    return api.allocate_booking(booking_id, allocate_payload(block_id, version),
                                CLIENT_SERVICE_AGENT)


# --------------------------------------------------------------------------
# A booking's allocation depends on the deal two hops away
# --------------------------------------------------------------------------


def test_allocation_is_refused_while_the_blocks_deal_has_released_nothing(
    api: ApiClient,
) -> None:
    """Nothing in the request is wrong, and the request is still rejected.

    The booking is RESERVED, the block is OPEN, both are CORPORATE and the
    version pin is current — yet the deal that owns the block is only COMMITTED,
    and that is what the rejection is about. The unit-availability rule is
    broken at the same moment, since the block has 0 allocated units against a
    requirement of 20, and it is not the code returned.

    PRD §3.5: "The block's `channel` must equal the booking's `channel`, and the
    block's rights deal must have `deal_status` of `PARTIALLY_RELEASED` or
    `FULLY_RELEASED`; either failing gives `ERR_CHANNEL_OR_DEAL_MISMATCH`."

    Design: Difficulty/cross_entity_state_dependency/allocate_requires_rights_deal_partially_or_fully_released
    """
    scenario = _reserved_booking_on_a_block_whose_deal_has_released_nothing(api)
    assert scenario["deal"]["deal_status"] == "COMMITTED"
    assert scenario["deal"]["released_units"] == 0
    assert scenario["block"]["block_state"] == "OPEN"
    assert scenario["block"]["allocated_units"] == 0
    assert scenario["booking"]["channel"] == "CORPORATE"
    assert scenario["booking"]["net_price_cents"] == 1637605

    response = _attempt_allocation(api, scenario["booking"]["id"],
                                   scenario["block"]["id"])

    body = validate_error(response, ERR_CHANNEL_OR_DEAL_MISMATCH, 422)
    assert body["error_id"] != ERR_ALLOCATION_UNITS_UNAVAILABLE

    booking = read_booking(api, scenario["booking"]["id"])
    assert booking["fulfillment_status"] == "RESERVED"
    assert booking["allocation_block_id"] is None
    assert read_block(api, scenario["block"]["id"])["committed_units"] == 0


def test_releasing_the_deal_alone_makes_the_identical_allocation_succeed(
    api: ApiClient,
) -> None:
    """Only the remote deal changes, and the same call flips from 422 to 200.

    Confirming the outstanding promise for all 60 units takes the deal to
    FULLY_RELEASED and lets the waterfall fill the block to its target of 40.
    Nothing about the booking or the block was touched by hand, and the repeated
    allocate — identical apart from the refreshed version pin — now commits the
    20 ticket units the sale consumes.

    PRD §3.5: "On success the booking moves `RESERVED → ALLOCATED`, its
    `allocation_block_id` is set, the block's `committed_units` increases by the
    booking's `units` multiplied by `tickets_per_package`, the block's `version`
    increases by one, and the fixture's `fulfillment_risk_score` and
    `risk_posture` are recomputed."

    Design: Difficulty/cross_entity_state_dependency/allocate_requires_rights_deal_partially_or_fully_released
    """
    scenario = _reserved_booking_on_a_block_whose_deal_has_released_nothing(api)
    block_id = scenario["block"]["id"]
    booking_id = scenario["booking"]["id"]
    validate_error(_attempt_allocation(api, booking_id, block_id),
                   ERR_CHANNEL_OR_DEAL_MISMATCH, 422)

    confirmed = confirm_tranche(api, scenario["tranche"]["id"],
                                scenario["deal"]["id"], 60)
    assert confirmed["tranche_state"] == "CONFIRMED"
    deal = get_success_data(api.get_rights_deal(scenario["deal"]["id"], RIGHTS_MANAGER))
    assert deal["deal_status"] == "FULLY_RELEASED"
    assert deal["released_units"] == 60
    assert read_block(api, block_id)["allocated_units"] == 40

    allocated = get_success_data(_attempt_allocation(api, booking_id, block_id))

    assert allocated["fulfillment_status"] == "ALLOCATED"
    assert allocated["allocation_block_id"] == block_id
    assert_block_position(read_block(api, block_id), allocated=40, committed=20,
                          released_back=0, state="EXHAUSTED")


# --------------------------------------------------------------------------
# A roster depends on a build state whose accepted set has two members
# --------------------------------------------------------------------------


def test_rostering_a_host_onto_a_planned_build_is_refused(api: ApiClient) -> None:
    """The booking, the host and the shift are all fine; the build is not.

    The booking already holds inventory, the build belongs to the booking's own
    fixture and the 10:00-18:00 shift lies inside the 09:00-20:00 service
    window, so neither the booking-state rule nor the scope rule can be the
    cause. A PLANNED build has no confirmed footprint to staff, and that is the
    rejection. Nothing is written: the host's counter stays at 0 and the booking
    has no rosters.

    PRD §3.7: "The build must be `APPROVED` or `READY`, since a `PLANNED` build
    has no confirmed hospitality footprint to staff and a `CLOSED` or `CANCELLED`
    build can no longer be staffed; anything else is `ERR_INVALID_BUILD_STATE`."

    Design: Difficulty/cross_entity_state_dependency/host_assignment_requires_build_approved_or_ready
    """
    scenario = _allocated_booking_with_a_planned_build_and_an_idle_host(api)
    assert scenario["booking"]["fulfillment_status"] == "ALLOCATED"
    assert scenario["build"]["build_state"] == "PLANNED"
    assert scenario["host"]["active_assignment_count"] == 0

    response = api.create_host_assignment(scenario["payload"], CLIENT_SERVICE_AGENT)

    body = validate_error(response, ERR_INVALID_BUILD_STATE, 409)
    assert body["error_id"] != ERR_ASSIGNMENT_SCOPE_MISMATCH

    assert read_host(api, scenario["host"]["id"])["active_assignment_count"] == 0
    assert_total_count(
        api.list_host_assignments(OPERATIONS_MANAGER,
                                  {"booking_id": scenario["booking"]["id"]}), 0
    )


def test_an_approved_build_is_staffable_without_ever_being_declared_ready(
    api: ApiClient,
) -> None:
    """The accepted set really has two members, and APPROVED is one of them.

    Finance approval is the only thing that changes between the two attempts,
    and the build is deliberately never readied. The identical payload is
    accepted, the assignment opens ASSIGNED against that same build and booking,
    and the host's counter — which is defined as the number of its ASSIGNED
    rosters — rises to 1.

    PRD §3.7: "A new assignment opens `ASSIGNED` with `released_at` unset, and it
    immediately triggers a recompute of the host's `active_assignment_count` and
    of the host list on the booking's itinerary."

    Design: Difficulty/cross_entity_state_dependency/host_assignment_requires_build_approved_or_ready
    """
    scenario = _allocated_booking_with_a_planned_build_and_an_idle_host(api)
    build_id = scenario["build"]["id"]
    validate_error(api.create_host_assignment(scenario["payload"], CLIENT_SERVICE_AGENT),
                   ERR_INVALID_BUILD_STATE, 409)

    approved = approve_build(api, build_id)
    assert approved["build_state"] == "APPROVED"

    assignment = get_success_data(
        api.create_host_assignment(scenario["payload"], CLIENT_SERVICE_AGENT), 201
    )

    assert assignment["assignment_state"] == "ASSIGNED"
    assert assignment["released_at"] is None
    assert assignment["hospitality_build_id"] == build_id
    assert assignment["booking_id"] == scenario["booking"]["id"]
    assert read_host(api, scenario["host"]["id"])["active_assignment_count"] == 1

    still_approved = get_success_data(
        api.get_hospitality_build(build_id, OPERATIONS_MANAGER)
    )
    assert still_approved["build_state"] == "APPROVED"
