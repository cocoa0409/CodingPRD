"""Boundary probes on the field-level and cross-entity rules of the API.

Each scenario pushes one declared rule to the exact unit, cent or instant where
it flips, so that an implementation using a strict comparison where the rules
say inclusive — or the reverse — is caught. Every precondition is built through
the declared endpoints against an empty database.
"""

from typing import Any, Dict, Optional

import pytest

from test_helpers import (
    CLIENT_SERVICE_AGENT,
    COMMERCIAL_DIRECTOR,
    COMMERCIAL_MANAGER,
    ERR_ALLOCATION_UNITS_UNAVAILABLE,
    ERR_ASSIGNMENT_SCOPE_MISMATCH,
    ERR_CHANNEL_OR_DEAL_MISMATCH,
    ERR_CLIENT_NOT_ACTIVE,
    ERR_CONFIRMED_UNITS_OUT_OF_RANGE,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_DUPLICATE_CHANNEL_BLOCK,
    ERR_EVENT_NOT_FOUND,
    ERR_EVENT_RISK_CRITICAL,
    ERR_INSTALLMENT_AMOUNT_MISMATCH,
    ERR_INSTALLMENT_NOT_PAYABLE,
    ERR_INVALID_REQUEST,
    ERR_MARGIN_BELOW_FLOOR,
    ERR_MINIMUM_EXCEEDS_CONTRACT,
    ERR_REBOOK_WINDOW_CLOSED,
    ERR_TRANCHE_EXCEEDS_CONTRACT,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    ERR_ZONE_NOT_AT_VENUE,
    FINANCE_CONTROLLER,
    NON_EXISTENT_UUID,
    OPERATIONS_MANAGER,
    RIGHTS_MANAGER,
    ROLE_RIGHTS_MANAGER,
    USER_COMMERCIAL_DIRECTOR,
    USER_RIGHTS_MANAGER,
    ApiClient,
    add_component,
    allocate_booking,
    allocate_payload,
    allocation_block_payload,
    approve_build,
    assert_block_position,
    assert_daily_run_report,
    assert_list_page,
    assert_package_pricing,
    assert_risk_band,
    assert_total_count,
    booking_payload,
    confirm_tranche_payload,
    daily_run,
    deal_version,
    get_success_data,
    headers_without_role,
    headers_without_user_id,
    hospitality_build_payload,
    host_assignment_payload,
    installments_of,
    make_block,
    make_booking,
    make_bronze_package,
    make_build,
    make_client,
    make_committed_deal,
    make_event,
    make_host,
    make_published_bronze_package,
    make_tranche,
    pay_payload,
    price_package,
    publish_payload,
    read_block,
    read_booking,
    read_client,
    read_event,
    read_host,
    rebook_payload,
    release_deal,
    release_tranche_payload,
    reset_clock,
    rights_deal_payload,
    set_clock,
    unexposed_bronze_floor,
    validate_error,
)

SECOND_EVENT = {
    "name": "Northern Derby",
    "venue_name": "Harbour Park",
    "hospitality_zone_codes": ["ZONE_C"],
    "event_date": "2027-03-01T15:00:00.000Z",
}

SECOND_EVENT_BUILD = {
    "zone_code": "ZONE_C",
    "service_window_start": "2027-03-01T09:00:00.000Z",
    "service_window_end": "2027-03-01T20:00:00.000Z",
    "space_units": 10,
    "catering_covers": 8,
    "staff_count": 2,
    "build_cost_cents": 50000,
    "catering_cost_cents": 20000,
    "staffing_cost_cents": 10000,
}


def _committed_deal_on_a_fresh_fixture(api: ApiClient, contracted_units: int,
                                      **overrides: Any) -> Dict[str, Any]:
    """A fixture plus one COMMITTED TICKET deal with no guaranteed minimum."""
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"], contracted_units=contracted_units,
                              guaranteed_minimum_units=0, **overrides)
    return {"event": event, "deal": deal}


def _delivery_floor(api: ApiClient) -> Dict[str, Any]:
    """A fixture sold and serviceable: 40 released units in a CORPORATE block,
    a published package, one ALLOCATED 5-unit booking, an APPROVED ZONE_A
    build running 09:00-20:00, and one host with the default capacity."""
    scenario = _committed_deal_on_a_fresh_fixture(api, 40)
    event_id = scenario["event"]["id"]
    block = make_block(api, scenario["deal"]["id"], channel="CORPORATE", target_units=40)
    release_deal(api, scenario["deal"]["id"], 40)
    package = make_published_bronze_package(api, event_id)
    client = make_client(api)
    booking = make_booking(api, client["id"], package["id"], units=5)
    build = make_build(api, event_id, space_units=30, catering_covers=20, staff_count=5)
    approve_build(api, build["id"])
    scenario.update({
        "block": read_block(api, block["id"]),
        "package": package,
        "client": client,
        "booking": allocate_booking(api, booking["id"], block["id"]),
        "build": build,
        "host": make_host(api),
    })
    return scenario


def _thin_margin_package(api: ApiClient) -> Dict[str, Any]:
    """A PRICED one-line BRONZE package whose margin floor is 0.5000.

    The fixture carries a committed TICKET deal so that ticket supply stands
    behind the package and the margin floor is the only thing publication can
    still object to.
    """
    reset_clock(api)
    event = make_event(api)
    make_committed_deal(api, event["id"])
    package = make_bronze_package(api, event["id"], name="Thin Margin Bronze",
                                  min_margin_pct=0.5000)
    add_component(api, package["id"])
    return {"event": event, "priced": price_package(api, package["id"])}


# --------------------------------------------------------------------------
# The guaranteed minimum against the contracted quantity
# --------------------------------------------------------------------------


def test_a_guaranteed_minimum_one_unit_above_the_contract_is_refused(
    api: ApiClient,
) -> None:
    """Promising to pay for 21 of 20 contracted units is incoherent.

    The acquisition overshoots the contract by exactly one unit, which is the
    smallest breach the rule can see, and it is refused before any deal row is
    created — the fixture ends the call with no rights deals against it.

    PRD §3.1: "A guaranteed minimum larger than the contracted quantity is
    commercially incoherent and is rejected with
    `ERR_MINIMUM_EXCEEDS_CONTRACT`."

    PRD §5: "| `ERR_MINIMUM_EXCEEDS_CONTRACT` | 422 |"

    Design: Corner/validations/guaranteed_minimum_may_equal_but_not_exceed_the_contracted_units
    """
    reset_clock(api)
    event = make_event(api)

    response = api.create_rights_deal(
        rights_deal_payload(event["id"], contracted_units=20,
                            guaranteed_minimum_units=21),
        RIGHTS_MANAGER,
    )

    validate_error(response, ERR_MINIMUM_EXCEEDS_CONTRACT, 422)
    assert_total_count(api.list_rights_deals(RIGHTS_MANAGER, {"event_id": event["id"]}), 0)


def test_a_guaranteed_minimum_equal_to_the_contract_is_accepted(
    api: ApiClient,
) -> None:
    """Equality is inside the rule, not outside it.

    The byte-identical acquisition with a 20-unit guarantee against 20
    contracted units is accepted and opens in the working state, so only a
    minimum strictly larger than the contract is refused.

    PRD §3.1: "A guaranteed minimum larger than the contracted quantity is
    commercially incoherent and is rejected with
    `ERR_MINIMUM_EXCEEDS_CONTRACT`."

    PRD §3.1: "A fresh acquisition opens in `DRAFT` with `released_units`,
    `shortfall_units`, `unallocated_units` and `minimum_liability_cents` all at 0
    and with `committed_by_user_id` and `settled_at` unset."

    Design: Corner/validations/guaranteed_minimum_may_equal_but_not_exceed_the_contracted_units
    """
    reset_clock(api)
    event = make_event(api)

    response = api.create_rights_deal(
        rights_deal_payload(event["id"], contracted_units=20,
                            guaranteed_minimum_units=20),
        RIGHTS_MANAGER,
    )

    deal = get_success_data(response, 201)
    assert deal["contracted_units"] == 20
    assert deal["guaranteed_minimum_units"] == 20
    assert deal["deal_status"] == "DRAFT"
    assert deal["released_units"] == 0
    assert deal["minimum_liability_cents"] == 0


# --------------------------------------------------------------------------
# One live block per channel, and what a recall gives back
# --------------------------------------------------------------------------


def test_a_second_corporate_block_is_refused_while_another_channel_stays_free(
    api: ApiClient,
) -> None:
    """The collision is per channel on the deal, not per deal.

    A second CORPORATE block on a deal that already serves CORPORATE is refused,
    while a TRAVEL_PARTNER block with the identical quantity and rank is
    accepted on that same deal — so an implementation that guards the deal as a
    whole rejects a legitimate second channel.

    PRD §3.3: "Blocks may only be created against a deal that is `COMMITTED`,
    `PARTIALLY_RELEASED` or `SHORTFALL_DECLARED`, and a deal may hold at most one
    live block per channel: if another block on the same deal already serves the
    same `channel` with `block_state` of `OPEN` or `EXHAUSTED`, the create is
    rejected with `ERR_DUPLICATE_CHANNEL_BLOCK`."

    PRD §5: "| `ERR_DUPLICATE_CHANNEL_BLOCK` | 409 |"

    Design: Corner/validations/a_recalled_block_frees_its_channel_for_a_replacement_block
    """
    scenario = _committed_deal_on_a_fresh_fixture(api, 40)
    deal_id = scenario["deal"]["id"]

    incumbent = get_success_data(
        api.create_allocation_block(
            allocation_block_payload(deal_id, channel="CORPORATE",
                                     target_units=10, priority_rank=1),
            COMMERCIAL_MANAGER,
        ),
        201,
    )
    assert incumbent["block_state"] == "OPEN"

    duplicate = api.create_allocation_block(
        allocation_block_payload(deal_id, channel="CORPORATE",
                                 target_units=25, priority_rank=2),
        COMMERCIAL_MANAGER,
    )
    validate_error(duplicate, ERR_DUPLICATE_CHANNEL_BLOCK, 409)

    other_channel = get_success_data(
        api.create_allocation_block(
            allocation_block_payload(deal_id, channel="TRAVEL_PARTNER",
                                     target_units=25, priority_rank=2),
            COMMERCIAL_MANAGER,
        ),
        201,
    )
    assert other_channel["channel"] == "TRAVEL_PARTNER"
    assert other_channel["id"] != incumbent["id"]

    assert_total_count(
        api.list_allocation_blocks(COMMERCIAL_MANAGER, {"rights_deal_id": deal_id}), 2
    )


def test_recalling_the_incumbent_block_admits_a_replacement_on_that_channel(
    api: ApiClient,
) -> None:
    """Recall takes the block out of the live set the uniqueness rule reads.

    The third CORPORATE request is the same deal and the same channel as the one
    that was refused a moment earlier; the only thing that changed is that the
    incumbent moved to the terminal recalled state, and that is enough for the
    replacement to open cleanly with all three counters at zero.

    PRD §3.3: "A recalled block does not block a replacement."

    PRD §3.3: "A new block opens `OPEN` with `allocated_units`,
    `committed_units` and `released_back_units` all at 0 and `recalled_at`
    unset."

    PRD §2.4: "Wherever a field below is described as being stamped with the
    current instant — `confirmed_at`, `lapsed_at`, `recalled_at`, `settled_at`,
    `priced_at`, `published_at`, `paid_at`, `released_at`, `run_at` — the value
    written is the logical clock's value at the moment of the write."

    Design: Corner/validations/a_recalled_block_frees_its_channel_for_a_replacement_block
    """
    scenario = _committed_deal_on_a_fresh_fixture(api, 40)
    deal_id = scenario["deal"]["id"]
    incumbent = make_block(api, deal_id, channel="CORPORATE",
                           target_units=10, priority_rank=1)

    validate_error(
        api.create_allocation_block(
            allocation_block_payload(deal_id, channel="CORPORATE",
                                     target_units=25, priority_rank=2),
            COMMERCIAL_MANAGER,
        ),
        ERR_DUPLICATE_CHANNEL_BLOCK,
        409,
    )

    recalled = get_success_data(
        api.recall_allocation_block(incumbent["id"], RIGHTS_MANAGER)
    )
    assert recalled["block_state"] == "RECALLED"
    assert recalled["recalled_at"] == "2026-08-01T00:00:00.000Z"

    replacement = get_success_data(
        api.create_allocation_block(
            allocation_block_payload(deal_id, channel="CORPORATE",
                                     target_units=25, priority_rank=3),
            COMMERCIAL_MANAGER,
        ),
        201,
    )
    assert replacement["id"] != incumbent["id"]
    assert_block_position(replacement, allocated=0, committed=0,
                          released_back=0, state="OPEN")
    assert replacement["recalled_at"] is None


# --------------------------------------------------------------------------
# Promised units are tested as a running total, not one request at a time
# --------------------------------------------------------------------------


def test_a_promise_far_below_the_contract_is_refused_once_siblings_are_counted(
    api: ApiClient,
) -> None:
    """Sixteen units are refused on a forty-unit contract.

    Twenty-five units are already outstanding, so the sixteen-unit promise
    breaches the contract only in aggregate — on its own it is well under the
    forty units bought. Nothing is persisted, so the deal is still carrying a
    single promise afterwards.

    PRD §3.2: "The provider may not promise more than it bought: the total of
    `promised_units` across the deal's tranches whose `tranche_state` is
    `PENDING`, `CONFIRMED` or `SHORT_CONFIRMED`, plus the new promise, must not
    exceed `contracted_units`, and a breach is rejected with
    `ERR_TRANCHE_EXCEEDS_CONTRACT`."

    PRD §5: "| `ERR_TRANCHE_EXCEEDS_CONTRACT` | 422 |"

    Design: Corner/validations/tranche_promises_are_aggregate_tested_against_the_contract
    """
    scenario = _committed_deal_on_a_fresh_fixture(api, 40)
    deal_id = scenario["deal"]["id"]

    first = get_success_data(
        api.create_release_tranche(
            release_tranche_payload(deal_id, promised_units=25,
                                    promised_release_at="2026-09-01T00:00:00.000Z"),
            RIGHTS_MANAGER,
        ),
        201,
    )
    assert first["tranche_state"] == "PENDING"
    assert first["confirmed_units"] == 0

    response = api.create_release_tranche(
        release_tranche_payload(deal_id, promised_units=16,
                                promised_release_at="2026-10-01T00:00:00.000Z"),
        RIGHTS_MANAGER,
    )

    validate_error(response, ERR_TRANCHE_EXCEEDS_CONTRACT, 422)
    rows = assert_total_count(
        api.list_release_tranches(RIGHTS_MANAGER, {"rights_deal_id": deal_id}), 1
    )
    assert [row["promised_units"] for row in rows] == [25]


def test_the_promise_that_lands_exactly_on_the_contract_is_accepted(
    api: ApiClient,
) -> None:
    """Twenty-five plus fifteen is forty, and forty is allowed.

    The running total may reach the contracted quantity exactly; only exceeding
    it is a breach. Both accepted promises stand on the deal afterwards, in the
    order they were recorded.

    PRD §3.2: "The provider may not promise more than it bought: the total of
    `promised_units` across the deal's tranches whose `tranche_state` is
    `PENDING`, `CONFIRMED` or `SHORT_CONFIRMED`, plus the new promise, must not
    exceed `contracted_units`, and a breach is rejected with
    `ERR_TRANCHE_EXCEEDS_CONTRACT`."

    PRD §3.2: "A new tranche opens in `PENDING` with `confirmed_units` at 0 and
    `confirmed_at` and `lapsed_at` unset."

    Design: Corner/validations/tranche_promises_are_aggregate_tested_against_the_contract
    """
    scenario = _committed_deal_on_a_fresh_fixture(api, 40)
    deal_id = scenario["deal"]["id"]
    make_tranche(api, deal_id, promised_units=25,
                 promised_release_at="2026-09-01T00:00:00.000Z")
    validate_error(
        api.create_release_tranche(
            release_tranche_payload(deal_id, promised_units=16,
                                    promised_release_at="2026-10-01T00:00:00.000Z"),
            RIGHTS_MANAGER,
        ),
        ERR_TRANCHE_EXCEEDS_CONTRACT,
        422,
    )

    response = api.create_release_tranche(
        release_tranche_payload(deal_id, promised_units=15,
                                promised_release_at="2026-10-01T00:00:00.000Z"),
        RIGHTS_MANAGER,
    )

    accepted = get_success_data(response, 201)
    assert accepted["promised_units"] == 15
    assert accepted["tranche_state"] == "PENDING"
    assert accepted["confirmed_at"] is None
    assert accepted["lapsed_at"] is None

    rows = assert_list_page(
        api.list_release_tranches(RIGHTS_MANAGER,
                                  {"rights_deal_id": deal_id, "limit": 10, "offset": 0}),
        expected_total=2, expected_rows=2,
    )
    assert [row["promised_units"] for row in rows] == [25, 15]


# --------------------------------------------------------------------------
# Confirmation between one and the promise, both ends inclusive
# --------------------------------------------------------------------------


def _deal_with_two_forty_unit_promises(api: ApiClient) -> Dict[str, Any]:
    """An 80-unit COMMITTED deal carrying two 40-unit PENDING promises."""
    scenario = _committed_deal_on_a_fresh_fixture(api, 80)
    deal_id = scenario["deal"]["id"]
    scenario["first_tranche"] = make_tranche(
        api, deal_id, promised_units=40,
        promised_release_at="2026-09-01T00:00:00.000Z",
    )
    scenario["second_tranche"] = make_tranche(
        api, deal_id, promised_units=40,
        promised_release_at="2026-10-01T00:00:00.000Z",
    )
    return scenario


def test_confirming_one_unit_more_than_promised_is_out_of_range_not_stale(
    api: ApiClient,
) -> None:
    """Forty-one against a forty-unit promise, on a freshly read version.

    The pinned deal version is read immediately beforehand, so nothing about
    this call is stale; the only fault is that the confirmed quantity sits one
    unit above the promise. The deal's version is untouched by the rejection and
    the tranche is still waiting to be confirmed, which the following successful
    confirmation proves.

    PRD §3.2: "The tranche must still be `PENDING`, or the call fails with
    `ERR_TRANCHE_NOT_PENDING`; its deal must be `COMMITTED`,
    `PARTIALLY_RELEASED` or `SHORTFALL_DECLARED`; and `confirmed_units` must lie
    between 1 and the tranche's `promised_units` inclusive, with anything outside
    that range rejected as `ERR_CONFIRMED_UNITS_OUT_OF_RANGE`."

    PRD §5: "| `ERR_CONFIRMED_UNITS_OUT_OF_RANGE` | 422 |"

    Design: Corner/validations/confirmed_units_must_land_between_one_and_the_promise
    """
    scenario = _deal_with_two_forty_unit_promises(api)
    deal_id = scenario["deal"]["id"]
    tranche_id = scenario["first_tranche"]["id"]
    version_before = deal_version(api, deal_id)

    response = api.confirm_release_tranche(
        tranche_id,
        confirm_tranche_payload(version_before, 41),
        RIGHTS_MANAGER,
    )

    validate_error(response, ERR_CONFIRMED_UNITS_OUT_OF_RANGE, 422)
    assert deal_version(api, deal_id) == version_before

    tranche = get_success_data(api.get_release_tranche(tranche_id, RIGHTS_MANAGER))
    assert tranche["tranche_state"] == "PENDING"
    assert tranche["confirmed_units"] == 0


def test_a_single_unit_short_confirms_while_the_whole_promise_confirms(
    api: ApiClient,
) -> None:
    """Both inclusive ends of the confirmation window behave differently.

    Confirming the whole forty units takes the tranche to the full branch;
    confirming one unit of a sibling forty-unit promise is equally accepted but
    lands on the short branch. The deal then carries exactly the 41 units the two
    accepted confirmations delivered, and its version advanced once per accepted
    confirmation.

    PRD §3.2: "When `confirmed_units` equals `promised_units` the tranche becomes
    `CONFIRMED`; when `confirmed_units` is at least 1 and strictly below
    `promised_units` it becomes `SHORT_CONFIRMED`."

    Design: Corner/validations/confirmed_units_must_land_between_one_and_the_promise
    """
    scenario = _deal_with_two_forty_unit_promises(api)
    deal_id = scenario["deal"]["id"]

    version_before_full = deal_version(api, deal_id)
    full = get_success_data(
        api.confirm_release_tranche(
            scenario["first_tranche"]["id"],
            confirm_tranche_payload(version_before_full, 40),
            RIGHTS_MANAGER,
        )
    )
    assert full["confirmed_units"] == 40
    assert full["tranche_state"] == "CONFIRMED"

    version_after_full = deal_version(api, deal_id)
    assert version_after_full == version_before_full + 1

    short = get_success_data(
        api.confirm_release_tranche(
            scenario["second_tranche"]["id"],
            confirm_tranche_payload(version_after_full, 1),
            RIGHTS_MANAGER,
        )
    )
    assert short["confirmed_units"] == 1
    assert short["tranche_state"] == "SHORT_CONFIRMED"

    deal = get_success_data(api.get_rights_deal(deal_id, RIGHTS_MANAGER))
    assert deal["released_units"] == 41
    assert deal["deal_status"] == "PARTIALLY_RELEASED"


# --------------------------------------------------------------------------
# A build's zone must be declared by its own fixture
# --------------------------------------------------------------------------


def test_a_zone_the_venue_never_declared_is_refused_and_lands_on_the_venue_that_did(
    api: ApiClient,
) -> None:
    """ZONE_C is illegal at one venue and legal at the next.

    The membership test reads the parent fixture's own list of hospitality
    zones rather than a global vocabulary, so the byte-identical build request
    is refused on the two-zone fixture and accepted on the fixture that declares
    ZONE_C. The refused fixture holds no builds at all afterwards, and the
    accepted build's cost is the three cost lines added up.

    PRD §3.7: "That code must be one of the fixture's own
    `hospitality_zone_codes`; a zone that is not at the venue is refused with
    `ERR_ZONE_NOT_AT_VENUE` (HTTP 422)."

    PRD §3.7: "The build's `total_cost_cents` is simply the sum of those three
    cost lines and is computed at once."

    PRD §3.7: "A new build opens in `PLANNED` with `approved_by_user_id` unset,
    and — importantly — a `PLANNED` build does not yet enter the fixture's margin
    cost base."

    Design: Corner/validations/build_zone_code_must_be_one_of_the_events_declared_zones
    """
    reset_clock(api)
    two_zone_fixture = make_event(api)
    assert two_zone_fixture["hospitality_zone_codes"] == ["ZONE_A", "ZONE_B"]
    zone_c_fixture = make_event(api, **SECOND_EVENT)

    refused = api.create_hospitality_build(
        hospitality_build_payload(
            two_zone_fixture["id"],
            **dict(SECOND_EVENT_BUILD,
                   service_window_start="2027-02-01T09:00:00.000Z",
                   service_window_end="2027-02-01T20:00:00.000Z"),
        ),
        OPERATIONS_MANAGER,
    )
    validate_error(refused, ERR_ZONE_NOT_AT_VENUE, 422)

    accepted = get_success_data(
        api.create_hospitality_build(
            hospitality_build_payload(zone_c_fixture["id"], **SECOND_EVENT_BUILD),
            OPERATIONS_MANAGER,
        ),
        201,
    )
    assert accepted["zone_code"] == "ZONE_C"
    assert accepted["build_state"] == "PLANNED"
    assert accepted["total_cost_cents"] == 80000
    assert accepted["approved_by_user_id"] is None

    assert_list_page(
        api.list_hospitality_builds(
            OPERATIONS_MANAGER,
            {"event_id": two_zone_fixture["id"], "limit": 10, "offset": 0},
        ),
        expected_total=0, expected_rows=0,
    )


# --------------------------------------------------------------------------
# A roster must stay inside one fixture and inside one service window
# --------------------------------------------------------------------------


def _floor_with_a_second_approved_build(api: ApiClient) -> Dict[str, Any]:
    """The serviceable fixture of :func:`_delivery_floor` plus a second fixture
    carrying its own APPROVED ZONE_C build, so the wrong-fixture build is in
    every other respect a legitimate rostering target."""
    scenario = _delivery_floor(api)
    other_event = make_event(api, **SECOND_EVENT)
    other_build = make_build(api, other_event["id"], **SECOND_EVENT_BUILD)
    scenario["other_event"] = other_event
    scenario["other_build"] = approve_build(api, other_build["id"])
    return scenario


def test_a_build_on_another_fixture_cannot_staff_this_bookings_hospitality(
    api: ApiClient,
) -> None:
    """The join is refused even though the build itself is perfectly rosterable.

    The wrong-fixture build is APPROVED and the booking is ALLOCATED, so neither
    the build-state test nor the booking-state test can be responsible for the
    refusal; the shift also sits well inside that build's own window. Only the
    fixture the build hangs off is wrong, and the host's live-assignment counter
    is untouched.

    PRD §3.7: "The build named by `hospitality_build_id` must belong to the same
    fixture as the booking named by `booking_id`, and the shift must lie inside
    that build's service window; either failing is
    `ERR_ASSIGNMENT_SCOPE_MISMATCH` (HTTP 422)."

    PRD §3.7: "A new host opens with `active_assignment_count` at 0; that counter
    is always the number of that host's assignments whose `assignment_state` is
    `ASSIGNED`."

    Design: Corner/validations/host_assignment_must_stay_inside_one_event_and_one_build_window
    """
    scenario = _floor_with_a_second_approved_build(api)
    assert scenario["booking"]["fulfillment_status"] == "ALLOCATED"
    assert scenario["other_build"]["build_state"] == "APPROVED"

    response = api.create_host_assignment(
        host_assignment_payload(
            scenario["host"]["id"],
            scenario["booking"]["id"],
            scenario["other_build"]["id"],
            shift_start="2027-03-01T10:00:00.000Z",
            shift_end="2027-03-01T18:00:00.000Z",
        ),
        OPERATIONS_MANAGER,
    )

    validate_error(response, ERR_ASSIGNMENT_SCOPE_MISMATCH, 422)
    assert read_host(api, scenario["host"]["id"])["active_assignment_count"] == 0


def test_a_shift_one_minute_past_the_service_window_is_refused_but_the_edges_are_inclusive(
    api: ApiClient,
) -> None:
    """Containment is inclusive at both ends of the build's service window.

    A shift ending one minute after the build stops serving is refused; the shift
    that starts exactly when the window opens and ends exactly when it closes is
    accepted, opens as an active roster and is the only one the host's counter
    ever sees.

    PRD §3.7: "The build named by `hospitality_build_id` must belong to the same
    fixture as the booking named by `booking_id`, and the shift must lie inside
    that build's service window; either failing is
    `ERR_ASSIGNMENT_SCOPE_MISMATCH` (HTTP 422)."

    PRD §3.7: "A new assignment opens `ASSIGNED` with `released_at` unset, and it
    immediately triggers a recompute of the host's `active_assignment_count` and
    of the host list on the booking's itinerary."

    Design: Corner/validations/host_assignment_must_stay_inside_one_event_and_one_build_window
    """
    scenario = _delivery_floor(api)
    host_id = scenario["host"]["id"]
    booking_id = scenario["booking"]["id"]
    build_id = scenario["build"]["id"]

    overrunning = api.create_host_assignment(
        host_assignment_payload(host_id, booking_id, build_id,
                                shift_start="2027-02-01T10:00:00.000Z",
                                shift_end="2027-02-01T20:01:00.000Z"),
        OPERATIONS_MANAGER,
    )
    validate_error(overrunning, ERR_ASSIGNMENT_SCOPE_MISMATCH, 422)

    exact = get_success_data(
        api.create_host_assignment(
            host_assignment_payload(host_id, booking_id, build_id,
                                    shift_start="2027-02-01T09:00:00.000Z",
                                    shift_end="2027-02-01T20:00:00.000Z"),
            OPERATIONS_MANAGER,
        ),
        201,
    )
    assert exact["assignment_state"] == "ASSIGNED"
    assert exact["released_at"] is None
    assert read_host(api, host_id)["active_assignment_count"] == 1


# --------------------------------------------------------------------------
# The rebooking window closes one second after the deadline instant
# --------------------------------------------------------------------------


def _two_frozen_bookings(api: ApiClient) -> Dict[str, Any]:
    """Two 5-unit bookings frozen into REBOOK_PENDING by one postponement.

    The postponement is taken at the default clock, so the deadline the two
    rebooking attempts probe is 2026-08-01 plus twenty-one days.
    """
    floor = unexposed_bronze_floor(api)
    first = make_booking(api, floor["client"]["id"], floor["package"]["id"], units=5)
    second = make_booking(api, floor["client"]["id"], floor["package"]["id"], units=5)
    postponed = get_success_data(
        api.postpone_event(floor["event"]["id"], {}, RIGHTS_MANAGER)
    )
    floor.update({"first": first, "second": second, "postponed": postponed})
    return floor


def test_rebooking_exactly_on_the_deadline_instant_is_still_inside_the_window(
    api: ApiClient,
) -> None:
    """The deadline is three weeks from the postponement, and it is inclusive.

    The postponement is taken at 2026-08-01T00:00:00Z, so the window closes at
    2026-08-22T00:00:00.000Z — derived from the postponement instant, not from
    the fixture's own date. With the clock parked exactly on that instant the
    frozen booking is rescued and returns to the reserved state with its rebooking
    counter advanced.

    PRD §3.8: "`postponement_count` increases by one, `status` becomes
    `POSTPONED`, and `rebook_deadline_at` is set to twenty-one days after the
    logical clock — the rebooking window is three weeks wide and is re-opened
    from scratch on every fresh postponement."

    PRD §3.8: "The logical clock must be at or before the fixture's
    `rebook_deadline_at`, inclusive — landing exactly on the deadline instant is
    still inside the window, and passing it is `ERR_REBOOK_WINDOW_CLOSED` (HTTP
    422)."

    PRD §3.8: "A successful rebooking replaces the booking's
    `package_product_id` with the target, increases `rebook_count` by one, and
    moves the booking `REBOOK_PENDING → RESERVED`."

    Design: Corner/validations/rebooking_is_allowed_on_the_deadline_instant_and_refused_one_second_later
    """
    scenario = _two_frozen_bookings(api)
    postponed = scenario["postponed"]
    assert postponed["status"] == "POSTPONED"
    assert postponed["postponement_count"] == 1
    assert postponed["rebook_deadline_at"] == "2026-08-22T00:00:00.000Z"

    set_clock(api, "2026-08-22T00:00:00Z")
    response = api.rebook_booking(
        scenario["first"]["id"],
        rebook_payload(scenario["package"]["id"]),
        CLIENT_SERVICE_AGENT,
    )

    rebooked = get_success_data(response)
    assert rebooked["fulfillment_status"] == "RESERVED"
    assert rebooked["rebook_count"] == 1


def test_rebooking_one_second_past_the_deadline_leaves_the_booking_frozen(
    api: ApiClient,
) -> None:
    """One second later the identical call on the sibling booking is refused.

    Both bookings were frozen by the same postponement cascade, so the two
    attempts differ only in where the logical clock stands. Past the deadline the
    booking is left exactly as the cascade left it, with no rebooking recorded.

    PRD §3.8: "The logical clock must be at or before the fixture's
    `rebook_deadline_at`, inclusive — landing exactly on the deadline instant is
    still inside the window, and passing it is `ERR_REBOOK_WINDOW_CLOSED` (HTTP
    422)."

    PRD §3.8: "Every booking on a package of this fixture whose
    `fulfillment_status` is `RESERVED`, `ALLOCATED` or `CREDENTIALED` moves to
    `REBOOK_PENDING`, processed in ascending `created_at` order."

    Design: Corner/validations/rebooking_is_allowed_on_the_deadline_instant_and_refused_one_second_later
    """
    scenario = _two_frozen_bookings(api)
    sibling_id = scenario["second"]["id"]
    assert read_booking(api, sibling_id)["fulfillment_status"] == "REBOOK_PENDING"

    set_clock(api, "2026-08-22T00:00:00Z")
    get_success_data(
        api.rebook_booking(scenario["first"]["id"],
                           rebook_payload(scenario["package"]["id"]),
                           CLIENT_SERVICE_AGENT)
    )

    set_clock(api, "2026-08-22T00:00:01Z")
    response = api.rebook_booking(sibling_id,
                                  rebook_payload(scenario["package"]["id"]),
                                  CLIENT_SERVICE_AGENT)

    validate_error(response, ERR_REBOOK_WINDOW_CLOSED, 422)
    frozen = read_booking(api, sibling_id)
    assert frozen["fulfillment_status"] == "REBOOK_PENDING"
    assert frozen["rebook_count"] == 0


# --------------------------------------------------------------------------
# An installment is settled to the cent or not at all
# --------------------------------------------------------------------------


def _booking_with_a_three_line_schedule(api: ApiClient) -> Dict[str, Any]:
    """A 5-unit CORPORATE booking netting 558720 over three scheduled lines."""
    floor = unexposed_bronze_floor(api)
    booking = make_booking(api, floor["client"]["id"], floor["package"]["id"], units=5)
    lines = installments_of(api, booking["id"])
    floor.update({"booking": booking, "lines": lines})
    return floor


@pytest.mark.parametrize("offered_cents", [167615, 167617])
def test_a_payment_one_cent_off_the_scheduled_amount_is_refused(
    api: ApiClient, offered_cents: int,
) -> None:
    """Both sides of "exactly" are probed one cent from the scheduled figure.

    The first line of the schedule is 167616, so 167615 is a partial payment and
    167617 is an overpayment. Both are refused on the same installment, and the
    line is left untouched in its scheduled state with nothing collected against
    it.

    PRD §3.6: "Payment must be exact: `amount_cents_paid` has to equal the
    installment's `amount_cents`, and both partial payments and overpayments are
    rejected with `ERR_INSTALLMENT_AMOUNT_MISMATCH` (HTTP 422) — the
    well-formed-but-wrong counterpart to a malformed body."

    PRD §5: "| `ERR_INSTALLMENT_AMOUNT_MISMATCH` | 422 |"

    Design: Corner/validations/installment_payment_must_match_the_scheduled_amount_to_the_cent
    """
    scenario = _booking_with_a_three_line_schedule(api)
    first_line = scenario["lines"][0]
    assert first_line["amount_cents"] == 167616
    assert first_line["installment_state"] == "SCHEDULED"

    response = api.pay_installment(first_line["id"], pay_payload(offered_cents),
                                   FINANCE_CONTROLLER)

    validate_error(response, ERR_INSTALLMENT_AMOUNT_MISMATCH, 422)
    unchanged = get_success_data(
        api.get_payment_installment(first_line["id"], FINANCE_CONTROLLER)
    )
    assert unchanged["installment_state"] == "SCHEDULED"
    assert unchanged["paid_amount_cents"] == 0
    assert read_booking(api, scenario["booking"]["id"])["paid_cents"] == 0


def test_the_exact_amount_is_collected_once_and_the_replay_is_a_state_conflict(
    api: ApiClient,
) -> None:
    """The identical successful call changes error class on the second attempt.

    Paying 167616 settles the line and stamps it at the logical clock. Replaying
    that very request is refused as a state conflict rather than an amount
    mismatch, because the line is no longer payable — so the money moved exactly
    once, leaving 391104 of the 558720 net price outstanding on the client.

    PRD §3.6: "On success the installment moves `SCHEDULED → PAID` or `OVERDUE →
    PAID`, its `paid_amount_cents` is set to its `amount_cents`, `paid_at` is
    stamped with the logical clock, and `days_overdue` is reset to 0."

    PRD §3.6: "The installment's `installment_state` must be `SCHEDULED` or
    `OVERDUE`, and where its `installment_kind` is `SCHEDULE` its parent booking
    must not be `CANCELLED`; a `PAID` or `VOIDED` installment, or a `SCHEDULE`
    line on a cancelled booking, gives `ERR_INSTALLMENT_NOT_PAYABLE`."

    PRD §3.6: "From `UNPAID`, a payment that still leaves at least one `SCHEDULE`
    installment of the booking in `SCHEDULED` or `OVERDUE` moves `payment_status`
    to `DEPOSIT_PAID`."

    Design: Corner/validations/installment_payment_must_match_the_scheduled_amount_to_the_cent
    """
    scenario = _booking_with_a_three_line_schedule(api)
    first_line = scenario["lines"][0]

    paid = get_success_data(
        api.pay_installment(first_line["id"], pay_payload(167616), FINANCE_CONTROLLER)
    )
    assert paid["installment_state"] == "PAID"
    assert paid["paid_amount_cents"] == 167616
    assert paid["paid_at"] == "2026-08-01T00:00:00.000Z"

    replay = api.pay_installment(first_line["id"], pay_payload(167616),
                                 FINANCE_CONTROLLER)
    validate_error(replay, ERR_INSTALLMENT_NOT_PAYABLE, 409)

    booking = read_booking(api, scenario["booking"]["id"])
    assert booking["paid_cents"] == 167616
    assert booking["payment_status"] == "DEPOSIT_PAID"
    assert read_client(api, scenario["client"]["id"])["outstanding_cents"] == 391104


# --------------------------------------------------------------------------
# The margin floor, crossed by changing the package
# --------------------------------------------------------------------------


def test_publication_is_refused_while_the_computed_margin_sits_below_the_floor(
    api: ApiClient,
) -> None:
    """A 0.1667 margin against a 0.5000 floor stops the package going on sale.

    The publish call carries the package's current version and comes from a
    director who is not the pricer, so neither the version pin nor the
    separation of hands can be responsible for the refusal. The package is left
    exactly where the pricing pass left it, which is why a further component line
    is still accepted afterwards.

    PRD §3.4: "The computed `margin_pct` must be greater than or equal to
    `min_margin_pct`, with a shortfall rejected as `ERR_MARGIN_BELOW_FLOOR`."

    PRD §3.4: "Lines may only be added while the package is `DRAFT` or `PRICED`;
    adding to a `PUBLISHED` or `CLOSED` package is `ERR_INVALID_PACKAGE_STATE`."

    PRD §5: "| `ERR_MARGIN_BELOW_FLOOR` | 422 |"

    Design: Corner/validations/publish_is_refused_below_the_margin_floor_and_allowed_once_a_component_lifts_it
    """
    scenario = _thin_margin_package(api)
    priced = scenario["priced"]
    assert_package_pricing(priced, base_cost=100000, subtotal=120000,
                           list_price=120000, margin_pct=0.1667, status="PRICED")

    response = api.publish_package_product(
        priced["id"], publish_payload(priced["version"]), COMMERCIAL_DIRECTOR
    )

    validate_error(response, ERR_MARGIN_BELOW_FLOOR, 422)

    lifting_line = add_component(
        api, priced["id"], component_type="EXPERIENCE",
        descriptor="Pitchside pre-match access", quantity=1,
        unit_cost_cents=100000, markup_pct=2.0000, sequence_no=2,
    )
    assert lifting_line["line_cost_cents"] == 100000
    assert lifting_line["line_price_cents"] == 300000


def test_a_high_markup_line_lifts_the_margin_and_the_identical_publish_lands(
    api: ApiClient,
) -> None:
    """The same publish call succeeds once the package itself has changed.

    Adding a high-markup experience line and re-pricing takes the margin from
    0.1667 to 0.5238, which clears the 0.5000 floor, and the publication that was
    refused a moment earlier now stamps the director's approval on the package
    and advances its version again.

    PRD §3.4: "The computed `margin_pct` must be greater than or equal to
    `min_margin_pct`, with a shortfall rejected as `ERR_MARGIN_BELOW_FLOOR`."

    PRD §3.4: "When all of that holds, `package_status` becomes `PUBLISHED`,
    `published_by_user_id` is stamped with the acting user, `published_at` is
    stamped with the logical clock, and the package's `version` increases by one
    again."

    Design: Corner/validations/publish_is_refused_below_the_margin_floor_and_allowed_once_a_component_lifts_it
    """
    scenario = _thin_margin_package(api)
    package_id = scenario["priced"]["id"]
    version_below_floor = scenario["priced"]["version"]
    validate_error(
        api.publish_package_product(package_id,
                                    publish_payload(version_below_floor),
                                    COMMERCIAL_DIRECTOR),
        ERR_MARGIN_BELOW_FLOOR, 422,
    )

    add_component(api, package_id, component_type="EXPERIENCE",
                  descriptor="Pitchside pre-match access", quantity=1,
                  unit_cost_cents=100000, markup_pct=2.0000, sequence_no=2)
    repriced = price_package(api, package_id)
    assert_package_pricing(repriced, base_cost=200000, subtotal=420000,
                           list_price=420000, margin_pct=0.5238, status="PRICED")
    assert repriced["version"] > version_below_floor

    published = get_success_data(
        api.publish_package_product(package_id,
                                    publish_payload(repriced["version"]),
                                    COMMERCIAL_DIRECTOR)
    )
    assert published["package_status"] == "PUBLISHED"
    assert published["published_by_user_id"] == USER_COMMERCIAL_DIRECTOR
    assert published["published_at"] == "2026-08-01T00:00:00.000Z"
    assert published["version"] == repriced["version"] + 1


# --------------------------------------------------------------------------
# Allocation needs the right channel AND a deal that has released something
# --------------------------------------------------------------------------


def _two_deals_one_channel_each(api: ApiClient) -> Dict[str, Any]:
    """One fixture, two deals: a fully released TICKET deal serving CORPORATE
    and a merely committed HOSPITALITY_SPACE deal serving INDIVIDUAL.

    Each of the two arms of the allocation join therefore has its own block to
    fail against, with the other arm satisfied.
    """
    scenario = _committed_deal_on_a_fresh_fixture(api, 40)
    event_id = scenario["event"]["id"]
    released_deal = scenario["deal"]
    corporate_block = make_block(api, released_deal["id"], channel="CORPORATE",
                                 target_units=40)
    release_deal(api, released_deal["id"], 40)

    unreleased_deal = make_committed_deal(
        api, event_id, rights_holder_name="Meridian Hospitality BV",
        inventory_type="HOSPITALITY_SPACE", contracted_units=40,
        guaranteed_minimum_units=0, unit_cost_cents=6000,
    )
    individual_block = make_block(api, unreleased_deal["id"], channel="INDIVIDUAL",
                                  target_units=40)

    package = make_published_bronze_package(api, event_id)
    client = make_client(api)
    return {
        "event": scenario["event"],
        "released_deal": released_deal,
        "unreleased_deal": unreleased_deal,
        "corporate_block": read_block(api, corporate_block["id"]),
        "individual_block": read_block(api, individual_block["id"]),
        "package": package,
        "client": client,
        "individual_booking": make_booking(api, client["id"], package["id"],
                                          channel="INDIVIDUAL", units=5),
        "corporate_booking": make_booking(api, client["id"], package["id"],
                                          channel="CORPORATE", units=5),
    }


def test_each_arm_of_the_allocation_join_refuses_on_its_own(
    api: ApiClient,
) -> None:
    """One error identity, two independent reasons, probed one at a time.

    Against the CORPORATE block the individual sale fails on the channel arm
    alone — the deal behind that block is fully released and holds forty free
    units. Against the channel-matching INDIVIDUAL block it fails on the
    deal-status arm alone, because a merely committed deal has released nothing,
    and that answers ahead of the units test even though that block holds no
    units either.

    PRD §3.5: "The block's `channel` must equal the booking's `channel`, and the
    block's rights deal must have `deal_status` of `PARTIALLY_RELEASED` or
    `FULLY_RELEASED`; either failing gives `ERR_CHANNEL_OR_DEAL_MISMATCH`."

    PRD §5: "| `ERR_CHANNEL_OR_DEAL_MISMATCH` | 422 |"

    Design: Corner/validations/allocate_requires_both_a_matching_channel_and_a_released_deal
    """
    scenario = _two_deals_one_channel_each(api)
    corporate_block = scenario["corporate_block"]
    individual_block = scenario["individual_block"]
    booking_id = scenario["individual_booking"]["id"]
    assert corporate_block["allocated_units"] == 40
    assert individual_block["allocated_units"] == 0

    wrong_channel = api.allocate_booking(
        booking_id,
        allocate_payload(corporate_block["id"], corporate_block["version"]),
        CLIENT_SERVICE_AGENT,
    )
    validate_error(wrong_channel, ERR_CHANNEL_OR_DEAL_MISMATCH, 422)

    unreleased_deal = api.allocate_booking(
        booking_id,
        allocate_payload(individual_block["id"], individual_block["version"]),
        CLIENT_SERVICE_AGENT,
    )
    validate_error(unreleased_deal, ERR_CHANNEL_OR_DEAL_MISMATCH, 422)

    still_reserved = read_booking(api, booking_id)
    assert still_reserved["fulfillment_status"] == "RESERVED"
    assert still_reserved["allocation_block_id"] is None


def test_the_matching_channel_on_a_released_deal_commits_two_units_per_package(
    api: ApiClient,
) -> None:
    """The version the rejections did not consume is still current.

    The corporate sale allocates against the very block and the very version the
    two refusals were aimed at, which shows neither refusal touched the block, and
    it consumes ten ticket units for its five package units.

    PRD §3.5: "On success the booking moves `RESERVED → ALLOCATED`, its
    `allocation_block_id` is set, the block's `committed_units` increases by the
    booking's `units` multiplied by `tickets_per_package`, the block's `version`
    increases by one, and the fixture's `fulfillment_risk_score` and
    `risk_posture` are recomputed."

    Design: Corner/validations/allocate_requires_both_a_matching_channel_and_a_released_deal
    """
    scenario = _two_deals_one_channel_each(api)
    corporate_block = scenario["corporate_block"]
    individual_booking_id = scenario["individual_booking"]["id"]

    validate_error(
        api.allocate_booking(
            individual_booking_id,
            allocate_payload(corporate_block["id"], corporate_block["version"]),
            CLIENT_SERVICE_AGENT,
        ),
        ERR_CHANNEL_OR_DEAL_MISMATCH, 422,
    )

    allocated = get_success_data(
        api.allocate_booking(
            scenario["corporate_booking"]["id"],
            allocate_payload(corporate_block["id"], corporate_block["version"]),
            CLIENT_SERVICE_AGENT,
        )
    )
    assert allocated["fulfillment_status"] == "ALLOCATED"
    assert allocated["allocation_block_id"] == corporate_block["id"]
    assert read_block(api, corporate_block["id"])["committed_units"] == 10


# --------------------------------------------------------------------------
# Availability is what is allocated less what is already committed
# --------------------------------------------------------------------------


def _full_corporate_block_and_three_bookings(api: ApiClient) -> Dict[str, Any]:
    """A 40-unit CORPORATE block with nothing sold, and 10, 10 and 1-unit sales.

    Two ticket units go per package unit, so the first two bookings consume the
    block exactly and the third needs two units that are no longer there.
    """
    scenario = _committed_deal_on_a_fresh_fixture(api, 40)
    block = make_block(api, scenario["deal"]["id"], channel="CORPORATE",
                       target_units=40)
    release_deal(api, scenario["deal"]["id"], 40)
    package = make_published_bronze_package(api, scenario["event"]["id"])
    client = make_client(api)
    scenario.update({
        "block": read_block(api, block["id"]),
        "package": package,
        "client": client,
        "bookings": [
            make_booking(api, client["id"], package["id"], units=units)
            for units in (10, 10, 1)
        ],
    })
    return scenario


def test_the_second_sale_lands_on_exactly_the_units_the_first_one_left(
    api: ApiClient,
) -> None:
    """The availability comparison is inclusive at its boundary.

    The first sale commits twenty of the block's forty ticket units; the second
    needs precisely the twenty that remain and must be accepted. The block was
    exhausted against its target from the start and stays that way throughout,
    because that dimension tracks allocation and not sales, while each accepted
    commitment advances the block's version once.

    PRD §3.5: "Finally the block must actually have the units free: its
    `allocated_units` less its `committed_units` must be at least the booking's
    `units` multiplied by the package's `tickets_per_package`, and a shortfall is
    `ERR_ALLOCATION_UNITS_UNAVAILABLE`."

    PRD §3.3: "Afterwards the block's `block_state` is set once more purely from
    allocation against target — `OPEN` when `allocated_units` is below
    `target_units`, `EXHAUSTED` when it equals it — and never from
    `committed_units`."

    Design: Corner/validations/allocation_availability_is_tested_net_of_committed_units
    """
    scenario = _full_corporate_block_and_three_bookings(api)
    block_id = scenario["block"]["id"]
    first, second, _third = scenario["bookings"]

    opening = read_block(api, block_id)
    assert_block_position(opening, allocated=40, committed=0,
                          released_back=0, state="EXHAUSTED")

    allocate_booking(api, first["id"], block_id)
    after_first = read_block(api, block_id)
    assert_block_position(after_first, allocated=40, committed=20,
                          released_back=0, state="EXHAUSTED")
    assert after_first["version"] > opening["version"]

    accepted = get_success_data(
        api.allocate_booking(
            second["id"],
            allocate_payload(block_id, after_first["version"]),
            CLIENT_SERVICE_AGENT,
        )
    )
    assert accepted["fulfillment_status"] == "ALLOCATED"

    after_second = read_block(api, block_id)
    assert_block_position(after_second, allocated=40, committed=40,
                          released_back=0, state="EXHAUSTED")
    assert after_second["version"] > after_first["version"]


def test_a_single_unit_sale_is_refused_once_the_block_is_exactly_full(
    api: ApiClient,
) -> None:
    """One package unit still needs two ticket units, and there are none.

    The refused sale asks for the smallest quantity the package can consume, so
    an implementation comparing the raw package units against the free units
    would accept it. Nothing moves: the block keeps its version and its forty
    committed units, and the booking is left holding no inventory.

    PRD §3.5: "Finally the block must actually have the units free: its
    `allocated_units` less its `committed_units` must be at least the booking's
    `units` multiplied by the package's `tickets_per_package`, and a shortfall is
    `ERR_ALLOCATION_UNITS_UNAVAILABLE`."

    PRD §5: "| `ERR_ALLOCATION_UNITS_UNAVAILABLE` | 422 |"

    Design: Corner/validations/allocation_availability_is_tested_net_of_committed_units
    """
    scenario = _full_corporate_block_and_three_bookings(api)
    block_id = scenario["block"]["id"]
    first, second, third = scenario["bookings"]
    allocate_booking(api, first["id"], block_id)
    allocate_booking(api, second["id"], block_id)

    full = read_block(api, block_id)
    assert full["committed_units"] == 40

    response = api.allocate_booking(
        third["id"], allocate_payload(block_id, full["version"]), CLIENT_SERVICE_AGENT
    )

    validate_error(response, ERR_ALLOCATION_UNITS_UNAVAILABLE, 422)
    unchanged = read_block(api, block_id)
    assert unchanged["version"] == full["version"]
    assert unchanged["committed_units"] == 40
    untouched = read_booking(api, third["id"])
    assert untouched["fulfillment_status"] == "RESERVED"
    assert untouched["allocation_block_id"] is None


# --------------------------------------------------------------------------
# Booking privilege is a consequence of the sweep, not a stored flag
# --------------------------------------------------------------------------


def _client_swept_on_hold(api: ApiClient) -> Dict[str, Any]:
    """A client whose single overdue line has driven it to ON_HOLD.

    The booking is taken at the default clock so its first line falls due three
    days later, and the sweep is then run one day past that date.
    """
    floor = unexposed_bronze_floor(api)
    assert floor["client"]["client_status"] == "ACTIVE"
    booking = make_booking(api, floor["client"]["id"], floor["package"]["id"], units=5)
    lines = installments_of(api, booking["id"])
    assert lines[0]["due_at"] == "2026-08-04T00:00:00.000Z"

    set_clock(api, "2026-08-05T00:00:00Z")
    report = daily_run(api)
    floor.update({"booking": booking, "lines": lines, "report": report})
    return floor


def test_a_client_the_sweep_put_on_hold_cannot_take_a_new_booking(
    api: ApiClient,
) -> None:
    """One overdue line is enough to suspend the client, and only one.

    The sweep ages the single line past its due date and re-derives the client's
    standing from the resulting count of one, which lands on suspension rather
    than the blocked band. The booking payload that was legal a moment earlier is
    then refused on the client's standing alone.

    PRD §3.6: "The first line falls due three days after the logical clock."

    PRD §3.6: "A client with an `overdue_installment_count` of at least 1 and at
    most 2 lands on `ON_HOLD` — whether it arrives there from `ACTIVE` or back up
    from `BLOCKED`."

    PRD §3.5: "Only then does credit control speak: the client's `client_status`
    must be `ACTIVE`, with an `ON_HOLD` or `BLOCKED` client refused as
    `ERR_CLIENT_NOT_ACTIVE`, and the client's `outstanding_cents` plus this
    booking's freshly computed `net_price_cents` must be at most
    `credit_limit_cents`."

    PRD §5: "| `ERR_CLIENT_NOT_ACTIVE` | 422 |"

    Design: Corner/validations/an_on_hold_client_cannot_book_until_the_sweep_restores_it
    """
    scenario = _client_swept_on_hold(api)
    assert_daily_run_report(scenario["report"], run_at="2026-08-05T00:00:00.000Z",
                            lapsed=0, overdue=1, shortfall=0, client_changes=1)

    suspended = read_client(api, scenario["client"]["id"])
    assert suspended["client_status"] == "ON_HOLD"
    assert suspended["overdue_installment_count"] == 1

    aged = get_success_data(
        api.get_payment_installment(scenario["lines"][0]["id"], FINANCE_CONTROLLER)
    )
    assert aged["installment_state"] == "OVERDUE"
    assert aged["days_overdue"] == 1

    response = api.create_booking(
        booking_payload(scenario["client"]["id"], scenario["package"]["id"], units=5),
        CLIENT_SERVICE_AGENT,
    )
    validate_error(response, ERR_CLIENT_NOT_ACTIVE, 422)


def test_paying_the_overdue_line_and_a_second_sweep_restore_the_clients_privilege(
    api: ApiClient,
) -> None:
    """The recovery edge runs the other way with no client mutation at all.

    Settling the overdue line takes the count back to zero, and the next sweep is
    what actually restores the standing — the payment alone does not move
    `client_status`. The identical booking payload is then accepted.

    PRD §3.6: "A client with an `overdue_installment_count` of exactly 0 returns
    to `ACTIVE`, whether from `ON_HOLD` or from `BLOCKED`."

    PRD §3.6: "No credit-standing state is terminal, and only the rollover moves
    `client_status`."

    PRD §3.5: "A booking that survives all of that opens with
    `fulfillment_status` at `RESERVED` on its delivery dimension and
    `payment_status` at `UNPAID` on its money dimension, with
    `allocation_block_id`, `settlement_variant`, `credential_serial_prefix` and
    `itinerary` all null, and `credentials_issued_count` and `rebook_count` at 0."

    Design: Corner/validations/an_on_hold_client_cannot_book_until_the_sweep_restores_it
    """
    scenario = _client_swept_on_hold(api)
    client_id = scenario["client"]["id"]
    payload = booking_payload(client_id, scenario["package"]["id"], units=5)
    validate_error(api.create_booking(payload, CLIENT_SERVICE_AGENT),
                   ERR_CLIENT_NOT_ACTIVE, 422)

    settled = get_success_data(
        api.pay_installment(scenario["lines"][0]["id"], pay_payload(167616),
                            FINANCE_CONTROLLER)
    )
    assert settled["installment_state"] == "PAID"

    second_run = daily_run(api)
    assert_daily_run_report(second_run, overdue=0, client_changes=1)

    restored = read_client(api, client_id)
    assert restored["client_status"] == "ACTIVE"
    assert restored["overdue_installment_count"] == 0

    accepted = get_success_data(api.create_booking(payload, CLIENT_SERVICE_AGENT), 201)
    assert accepted["fulfillment_status"] == "RESERVED"
    assert accepted["payment_status"] == "UNPAID"


# --------------------------------------------------------------------------
# A critical fixture sells only against an explicit acknowledgement
# --------------------------------------------------------------------------


def _fixture_that_will_turn_critical(api: ApiClient) -> Dict[str, Any]:
    """A 60-unit deal guaranteeing 20 units, with two 30-unit promises pending.

    Both promises fall due before 2026-09-16, so a sweep taken at that instant
    lapses the pair and pushes the fixture's risk over the critical threshold.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"], contracted_units=60,
                               guaranteed_minimum_units=20, unit_cost_cents=8000)
    make_tranche(api, deal["id"], promised_units=30,
                 promised_release_at="2026-09-01T00:00:00.000Z")
    make_tranche(api, deal["id"], promised_units=30,
                 promised_release_at="2026-09-15T00:00:00.000Z")
    package = make_published_bronze_package(api, event["id"])
    client = make_client(api)
    return {"event": event, "deal": deal, "package": package, "client": client}


def test_an_elevated_posture_sells_without_any_acknowledgement(
    api: ApiClient,
) -> None:
    """At a score of 40 the sale needs no acknowledgement in the body at all.

    Ten package units commit twenty ticket units against nothing released, which
    is the whole of the gap component and nothing else, so the fixture sits in the
    middle band. The booking payload carries no acknowledgement field and is
    accepted.

    PRD §3.9: "`risk_posture` is a band over that score, and both boundaries are
    inclusive: `CRITICAL` when `fulfillment_risk_score` is 70 or more, `ELEVATED`
    when it is 40 or more, and `NORMAL` otherwise."

    PRD §3.5: "Where the fixture's `risk_posture` currently reads `CRITICAL`, the
    agent must knowingly accept the fulfillment risk by sending
    `risk_override_ack` as true; without it the sale is refused with
    `ERR_EVENT_RISK_CRITICAL` (HTTP 422)."

    Design: Corner/validations/critical_risk_gates_new_bookings_unless_the_agent_acknowledges_it
    """
    scenario = _fixture_that_will_turn_critical(api)

    accepted = get_success_data(
        api.create_booking(
            booking_payload(scenario["client"]["id"], scenario["package"]["id"],
                            units=10),
            CLIENT_SERVICE_AGENT,
        ),
        201,
    )
    assert accepted["fulfillment_status"] == "RESERVED"
    assert_risk_band(read_event(api, scenario["event"]["id"]), score=40,
                     posture="ELEVATED")


def _critical_fixture_and_a_fresh_client(api: ApiClient) -> Dict[str, Any]:
    """The same fixture after the sweep has lapsed both promises.

    The buyer is a newly registered client, so nothing about the sale can be
    refused on credit standing and only the risk gate is left to answer.
    """
    scenario = _fixture_that_will_turn_critical(api)
    get_success_data(
        api.create_booking(
            booking_payload(scenario["client"]["id"], scenario["package"]["id"],
                            units=10),
            CLIENT_SERVICE_AGENT,
        ),
        201,
    )
    set_clock(api, "2026-09-16T00:00:00Z")
    scenario["report"] = daily_run(api)
    scenario["buyer"] = make_client(api, name="Vantage Partners",
                                    client_type="TRAVEL_PARTNER")
    return scenario


@pytest.mark.parametrize("acknowledgement", [None, False])
def test_a_critical_fixture_refuses_a_sale_that_does_not_acknowledge_the_risk(
    api: ApiClient, acknowledgement: Optional[bool],
) -> None:
    """Omitting the acknowledgement and sending it as false are the same refusal.

    Lapsing both promises adds the whole lapse component to the standing gap
    component, so the score lands exactly on the inclusive critical boundary. From
    there the sale is refused whether the acknowledgement is missing from the body
    or present and false.

    PRD §3.5: "Where the fixture's `risk_posture` currently reads `CRITICAL`, the
    agent must knowingly accept the fulfillment risk by sending
    `risk_override_ack` as true; without it the sale is refused with
    `ERR_EVENT_RISK_CRITICAL` (HTTP 422)."

    PRD §3.9: "`risk_posture` is a band over that score, and both boundaries are
    inclusive: `CRITICAL` when `fulfillment_risk_score` is 70 or more, `ELEVATED`
    when it is 40 or more, and `NORMAL` otherwise."

    PRD §5: "| `ERR_EVENT_RISK_CRITICAL` | 422 |"

    Design: Corner/validations/critical_risk_gates_new_bookings_unless_the_agent_acknowledges_it
    """
    scenario = _critical_fixture_and_a_fresh_client(api)
    assert_daily_run_report(scenario["report"], lapsed=2, shortfall=1)
    assert_risk_band(read_event(api, scenario["event"]["id"]), score=70,
                     posture="CRITICAL")

    payload = booking_payload(scenario["buyer"]["id"], scenario["package"]["id"],
                              units=10)
    if acknowledgement is not None:
        payload["risk_override_ack"] = acknowledgement

    response = api.create_booking(payload, CLIENT_SERVICE_AGENT)

    validate_error(response, ERR_EVENT_RISK_CRITICAL, 422)


def test_a_true_acknowledgement_is_what_lets_the_critical_sale_through(
    api: ApiClient,
) -> None:
    """The identical sale lands once the agent knowingly accepts the risk.

    Nothing about the fixture, the package or the buyer changes between the
    refusal and the acceptance; only the acknowledgement flips to true, and the
    booking records that it was taken knowingly.

    PRD §3.5: "Where the fixture's `risk_posture` currently reads `CRITICAL`, the
    agent must knowingly accept the fulfillment risk by sending
    `risk_override_ack` as true; without it the sale is refused with
    `ERR_EVENT_RISK_CRITICAL` (HTTP 422)."

    Design: Corner/validations/critical_risk_gates_new_bookings_unless_the_agent_acknowledges_it
    """
    scenario = _critical_fixture_and_a_fresh_client(api)
    payload = booking_payload(scenario["buyer"]["id"], scenario["package"]["id"],
                              units=10)
    validate_error(api.create_booking(payload, CLIENT_SERVICE_AGENT),
                   ERR_EVENT_RISK_CRITICAL, 422)

    acknowledged = get_success_data(
        api.create_booking(dict(payload, risk_override_ack=True),
                           CLIENT_SERVICE_AGENT),
        201,
    )
    assert acknowledged["risk_override_ack"] is True
    assert acknowledged["fulfillment_status"] == "RESERVED"


# --------------------------------------------------------------------------
# The credit limit admits the booking that lands exactly on it
# --------------------------------------------------------------------------


def test_a_sale_that_lands_exactly_on_the_credit_limit_is_admitted(
    api: ApiClient,
) -> None:
    """Exposure of 558720 against a limit of 558720 is inside the rule.

    The client's limit is set to the exact net price of the sale, so the
    comparison is decided by its far side alone, and the accepted booking takes
    the client's exposure to precisely its ceiling.

    PRD §3.5: "The comparison is strict on the far side: landing exactly on the
    limit is permitted, and only strictly exceeding it is refused, with
    `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

    PRD §3.5: "A new client opens with `client_status` at `ACTIVE`,
    `outstanding_cents` at 0 and `overdue_installment_count` at 0."

    Design: Corner/validations/credit_limit_admits_a_booking_that_lands_exactly_on_the_limit
    """
    floor = unexposed_bronze_floor(api, client_overrides={"credit_limit_cents": 558720})
    assert floor["client"]["outstanding_cents"] == 0

    accepted = get_success_data(
        api.create_booking(
            booking_payload(floor["client"]["id"], floor["package"]["id"], units=5),
            CLIENT_SERVICE_AGENT,
        ),
        201,
    )
    assert accepted["net_price_cents"] == 558720
    assert read_client(api, floor["client"]["id"])["outstanding_cents"] == 558720


def test_the_smallest_follow_up_sale_over_the_limit_is_refused_on_the_aggregate(
    api: ApiClient,
) -> None:
    """One more package unit is 116400 the client does not have.

    The refused sale is far below the limit on its own, so the rule can only be
    testing it against the exposure already carried. The refusal uses the status
    no other rule in the catalogue uses, exposure is unmoved, and the client ends
    with exactly the one booking it could afford.

    PRD §3.5: "The comparison is strict on the far side: landing exactly on the
    limit is permitted, and only strictly exceeding it is refused, with
    `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

    PRD §5: "| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |"

    Design: Corner/validations/credit_limit_admits_a_booking_that_lands_exactly_on_the_limit
    """
    floor = unexposed_bronze_floor(api, client_overrides={"credit_limit_cents": 558720})
    client_id = floor["client"]["id"]
    first = get_success_data(
        api.create_booking(booking_payload(client_id, floor["package"]["id"], units=5),
                           CLIENT_SERVICE_AGENT),
        201,
    )

    response = api.create_booking(
        booking_payload(client_id, floor["package"]["id"], units=1),
        CLIENT_SERVICE_AGENT,
    )

    validate_error(response, ERR_CREDIT_LIMIT_EXCEEDED, 402)
    assert read_client(api, client_id)["outstanding_cents"] == 558720
    rows = assert_total_count(
        api.list_bookings(FINANCE_CONTROLLER,
                          {"client_id": client_id, "limit": 10, "offset": 0}), 1
    )
    assert rows[0]["id"] == first["id"]


# --------------------------------------------------------------------------
# Identity answers before existence, and the body answers before it too
# --------------------------------------------------------------------------

POSTPONE_A_MISSING_FIXTURE = f"/events/{NON_EXISTENT_UUID}/postpone"


@pytest.mark.parametrize("incomplete_headers", [
    {"Content-Type": "application/json"},
    headers_without_user_id(ROLE_RIGHTS_MANAGER),
    headers_without_role(USER_RIGHTS_MANAGER),
])
def test_an_unidentified_caller_is_refused_before_the_fixture_is_looked_for(
    api: ApiClient, incomplete_headers: Dict[str, str],
) -> None:
    """A request with an incomplete identity never reaches the missing fixture.

    The path names an identifier no record carries, so the existence rule is
    genuinely broken as well — yet an implementation that resolved the path first
    would answer 404 to all three of these probes instead of the authentication
    refusal.

    PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the
    seven declared role names, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    PRD §2.7: "Checks are evaluated in the fixed sequence below and the first
    failing check produces the response."

    Design: Corner/validations/authentication_and_authorization_answer_before_existence_and_body_checks
    """
    response = api.raw_post(POSTPONE_A_MISSING_FIXTURE, {}, incomplete_headers)

    validate_error(response, ERR_UNAUTHENTICATED, 401)


def test_a_role_outside_the_endpoints_list_is_refused_before_the_fixture_is_looked_for(
    api: ApiClient,
) -> None:
    """A recognised but unauthorised role answers 403, not 404.

    Postponing a fixture belongs to the rights manager alone, so a client service
    agent is refused on authorisation even though the fixture it names does not
    exist either.

    PRD §2.1: "When both headers are well formed but the declared role is not
    authorised for the endpoint being called, the rejection is `ERR_UNAUTHORIZED`
    (HTTP 403). Authorisation per endpoint is tabulated in §4."

    PRD §4: "| POST | `/events/{id}/postpone` | Postpones a fixture, freezing its
    sold bookings into rebook-pending and opening a rebooking window; from a
    postponed fixture, confirms a replacement date instead. | RightsManager |"

    Design: Corner/validations/authentication_and_authorization_answer_before_existence_and_body_checks
    """
    response = api.raw_post(POSTPONE_A_MISSING_FIXTURE, {}, CLIENT_SERVICE_AGENT)

    validate_error(response, ERR_UNAUTHORIZED, 403)


def test_a_malformed_body_is_refused_before_the_fixture_is_looked_for(
    api: ApiClient,
) -> None:
    """Body validation still precedes existence for the authorised caller.

    The rights manager is entitled to call this endpoint, so the only two rules
    left broken are the unparseable replacement date and the fixture that does not
    exist. The shape rule is the one that answers.

    PRD §2.7: "Checks are evaluated in the fixed sequence below and the first
    failing check produces the response."

    PRD §2.7: "**Request shape.** Body parses, every required field is present,
    every value matches its declared type, every enumerated value is a declared
    member, every integer bound holds, `sequence_no` is unique within its parent
    package, a build's `service_window_end` is strictly after its
    `service_window_start`, a shift's `shift_end` is strictly after its
    `shift_start`, `hospitality_zone_codes` is a non-empty array of unique
    strings, and any supplied `limit` lies between 1 and 100 inclusive —
    `ERR_INVALID_REQUEST`."

    Design: Corner/validations/authentication_and_authorization_answer_before_existence_and_body_checks
    """
    response = api.raw_post(POSTPONE_A_MISSING_FIXTURE,
                            {"new_event_date": "not-a-timestamp"}, RIGHTS_MANAGER)

    validate_error(response, ERR_INVALID_REQUEST, 400)


def test_only_the_well_formed_authorised_call_reaches_the_existence_rule(
    api: ApiClient,
) -> None:
    """With identity, authority and body all in order the 404 finally surfaces.

    This is the same path and the same nonexistent identifier as the three
    refusals above; the difference is that nothing earlier in the sequence is
    broken any more, so the missing fixture is reported with a human-readable
    message.

    PRD §2.7: "Checks are evaluated in the fixed sequence below and the first
    failing check produces the response."

    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    PRD §5: "| `ERR_EVENT_NOT_FOUND` | 404 |"

    Design: Corner/validations/authentication_and_authorization_answer_before_existence_and_body_checks
    """
    response = api.raw_post(POSTPONE_A_MISSING_FIXTURE, {}, RIGHTS_MANAGER)

    body = validate_error(response, ERR_EVENT_NOT_FOUND, 404)
    assert body["message"]
