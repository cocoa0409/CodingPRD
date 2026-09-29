"""Cascades whose later hops are caused by earlier hops, not by the request.

A postponement reaches a host's counter and a client's exposure through four
hops without naming either of them, and creating an allocation block reaches a
sold booking through the waterfall's two passes without naming it.
"""

from typing import Any, Dict

from test_helpers import (
    OPERATIONS_MANAGER,
    RIGHTS_MANAGER,
    ApiClient,
    allocate_booking,
    assert_block_position,
    assert_risk_band,
    credentialed_booking_with_host,
    daily_run,
    get_success_data,
    installments_of,
    make_block,
    make_booking,
    make_client,
    make_committed_deal,
    make_event,
    make_published_gold_package,
    read_block,
    read_booking,
    read_client,
    read_event,
    read_host,
    release_deal,
    reset_clock,
    set_clock,
)


def _credentialed_booking_with_an_overdue_client(api: ApiClient) -> Dict[str, Any]:
    """A credentialed, hosted booking whose first installment has gone overdue.

    The clock is pushed one day past the first installment's due date of
    2026-08-04 and the rollover is run, so the client carries one OVERDUE line
    and its credit standing has dropped to ON_HOLD.
    """
    scenario = credentialed_booking_with_host(api)
    set_clock(api, "2026-08-05T00:00:00Z")
    scenario["sweep"] = daily_run(api)
    scenario["client_before"] = read_client(api, scenario["client"]["id"])
    scenario["host_before"] = read_host(api, scenario["host"]["id"])
    return scenario


def _sold_out_partner_block(api: ApiClient) -> Dict[str, Any]:
    """A rank-5 TRAVEL_PARTNER block filled to 30 with a 15-unit sale on it.

    Only 40 of the 60 contracted units are released, so the deal stays
    PARTIALLY_RELEASED with 10 units unallocated after the partner block takes
    its full target of 30.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_committed_deal(api, event["id"])
    partner_block = make_block(api, deal["id"], channel="TRAVEL_PARTNER",
                              target_units=30, priority_rank=5)
    release_deal(api, deal["id"], 40)
    package = make_published_gold_package(api, event["id"])
    client = make_client(api, name="Aventine Travel Group", client_type="TRAVEL_PARTNER")
    booking = make_booking(api, client["id"], package["id"],
                           channel="TRAVEL_PARTNER", units=15)
    allocated = allocate_booking(api, booking["id"], partner_block["id"])
    return {
        "event": event,
        "deal": deal,
        "partner_block": read_block(api, partner_block["id"]),
        "package": package,
        "client": client,
        "booking": allocated,
    }


# --------------------------------------------------------------------------
# Postponement, four hops deep
# --------------------------------------------------------------------------


def test_postponement_freezes_the_booking_and_hands_its_units_back(
    api: ApiClient,
) -> None:
    """The fixture moves, the sale freezes, and the block gives up its sales.

    The postponement stamps the original kick-off, opens a fresh three-week
    rebooking window from the logical clock of 2026-08-05, and drives the
    credentialed booking to REBOOK_PENDING with its credentials torn up and its
    block reference cleared. The block hands back all 20 committed ticket units
    but its own state is deliberately left at EXHAUSTED, because state tracks
    allocation against target and the allocation of 40 has not moved.

    PRD §3.8: "The block's `block_state` is deliberately not touched — it tracks
    allocation against target, not sales."

    Design: Difficulty/transitive_cascade/postpone_event_depth4_cascade_to_host_counter_and_client_overdue
    """
    scenario = _credentialed_booking_with_an_overdue_client(api)
    assert scenario["booking"]["net_price_cents"] == 1580574
    assert scenario["booking"]["credentials_issued_count"] == 30
    assert scenario["host_before"]["active_assignment_count"] == 1
    assert scenario["sweep"]["overdue_installment_count"] == 1
    assert scenario["client_before"]["overdue_installment_count"] == 1
    assert scenario["client_before"]["client_status"] == "ON_HOLD"

    postponed = get_success_data(
        api.postpone_event(scenario["event"]["id"], {}, RIGHTS_MANAGER)
    )

    assert postponed["status"] == "POSTPONED"
    assert postponed["postponement_count"] == 1
    assert postponed["rebook_deadline_at"] == "2026-08-26T00:00:00.000Z"
    assert postponed["original_event_date"] == "2027-02-01T15:00:00.000Z"
    assert postponed["event_date"] == "2027-02-01T15:00:00.000Z"
    assert_risk_band(postponed, score=10, posture="NORMAL")

    booking = read_booking(api, scenario["booking"]["id"])
    assert booking["fulfillment_status"] == "REBOOK_PENDING"
    assert booking["allocation_block_id"] is None
    assert booking["credentials_issued_count"] == 0

    assert_block_position(read_block(api, scenario["block"]["id"]),
                          allocated=40, committed=0, released_back=20,
                          state="EXHAUSTED")


def test_postponement_unages_the_installments_and_voids_the_host_roster(
    api: ApiClient,
) -> None:
    """Hops three and three-b reach records the call never named.

    Because the booking entered REBOOK_PENDING, all three of its live schedule
    lines are re-dated to the new rebooking deadline and pulled back to
    SCHEDULED — including the one the rollover had aged into OVERDUE, whose
    days_overdue returns to 0. Because the booking left CREDENTIALED, its host
    roster is voided with a release stamp at the logical clock, and the host's
    own counter falls to 0 as a consequence of that.

    PRD §3.8: "Because each booking entered `REBOOK_PENDING`, every one of its
    installments whose `installment_state` is `SCHEDULED` or `OVERDUE` has its
    `due_at` rewritten to the fixture's new `rebook_deadline_at` and its
    `installment_state` set to `SCHEDULED` — an overdue line is un-aged, because
    the client is no longer late for a fixture that is no longer happening."

    Design: Difficulty/transitive_cascade/postpone_event_depth4_cascade_to_host_counter_and_client_overdue
    """
    scenario = _credentialed_booking_with_an_overdue_client(api)

    get_success_data(api.postpone_event(scenario["event"]["id"], {}, RIGHTS_MANAGER))

    lines = installments_of(api, scenario["booking"]["id"])
    assert len(lines) == 3
    for line in lines:
        assert line["installment_kind"] == "SCHEDULE"
        assert line["installment_state"] == "SCHEDULED"
        assert line["days_overdue"] == 0
        assert line["due_at"] == "2026-08-26T00:00:00.000Z"

    assignment = get_success_data(
        api.get_host_assignment(scenario["assignment"]["id"], OPERATIONS_MANAGER)
    )
    assert assignment["assignment_state"] == "VOIDED"
    assert assignment["released_at"] == "2026-08-05T00:00:00.000Z"

    host = read_host(api, scenario["host"]["id"])
    assert host["active_assignment_count"] == 0


def test_postponement_recomputes_client_exposure_without_moving_credit_standing(
    api: ApiClient,
) -> None:
    """The overdue counter falls to 0 while the credit standing stays ON_HOLD.

    The client's overdue count drops only because hop three pulled its aged line
    back to SCHEDULED, and its exposure is the whole unpaid net price of the
    frozen booking, since REBOOK_PENDING is still a live fulfillment state. The
    credit standing does not follow the counter down, because only the rollover
    moves it.

    PRD §3.6: "No credit-standing state is terminal, and only the rollover moves
    `client_status`."

    Design: Difficulty/transitive_cascade/postpone_event_depth4_cascade_to_host_counter_and_client_overdue
    """
    scenario = _credentialed_booking_with_an_overdue_client(api)
    assert scenario["client_before"]["overdue_installment_count"] == 1
    assert scenario["client_before"]["client_status"] == "ON_HOLD"

    get_success_data(api.postpone_event(scenario["event"]["id"], {}, RIGHTS_MANAGER))

    client = read_client(api, scenario["client"]["id"])
    assert client["overdue_installment_count"] == 0
    assert client["outstanding_cents"] == 1580574
    assert client["client_status"] == "ON_HOLD"


# --------------------------------------------------------------------------
# Block preemption, three hops deep
# --------------------------------------------------------------------------


def test_a_higher_priority_block_takes_units_from_an_exhausted_incumbent(
    api: ApiClient,
) -> None:
    """Creating a rank-1 block lowers a rank-5 block's allocation.

    Forty units are distributable. The new CORPORATE block sorts first and takes
    its full target of 20, which leaves only 20 for the incumbent partner block
    that previously held 30. The incumbent therefore returns from EXHAUSTED to
    OPEN, and the deal's unallocated units fall to 0 because 20 + 20 is the whole
    release.

    PRD §3.3: "The one input that lowers an incumbent's allocation is the
    creation of a **new** block whose `priority_rank` sorts ahead of it: the
    newcomer takes units the incumbent already held, so the incumbent's
    `allocated_units` falls, and a block sitting at `EXHAUSTED` returns
    `EXHAUSTED → OPEN` as it gives units back to the higher-priority channel."

    Design: Difficulty/transitive_cascade/block_preemption_depth3_cascade_reverts_a_sold_allocation
    """
    scenario = _sold_out_partner_block(api)
    incumbent_id = scenario["partner_block"]["id"]
    assert scenario["partner_block"]["allocated_units"] == 30
    assert scenario["partner_block"]["block_state"] == "EXHAUSTED"
    assert scenario["booking"]["fulfillment_status"] == "ALLOCATED"
    assert scenario["booking"]["net_price_cents"] == 2285315
    deal_before = get_success_data(
        api.get_rights_deal(scenario["deal"]["id"], RIGHTS_MANAGER)
    )
    assert deal_before["unallocated_units"] == 10

    newcomer = make_block(api, scenario["deal"]["id"], channel="CORPORATE",
                         target_units=20, priority_rank=1)

    assert newcomer["priority_rank"] == 1
    assert_block_position(newcomer, allocated=20, committed=0, released_back=0,
                          state="EXHAUSTED")

    incumbent = read_block(api, incumbent_id)
    assert incumbent["allocated_units"] == 20
    assert incumbent["block_state"] == "OPEN"

    deal_after = get_success_data(
        api.get_rights_deal(scenario["deal"]["id"], RIGHTS_MANAGER)
    )
    assert deal_after["unallocated_units"] == 0
    assert deal_after["released_units"] == 40
    assert deal_after["deal_status"] == "PARTIALLY_RELEASED"


def test_the_revert_pass_drags_an_over_committed_sale_back_to_reserved(
    api: ApiClient,
) -> None:
    """The third hop is caused by the second alone and names nobody.

    Once the incumbent holds 20 allocated against 30 already sold, it is
    over-committed, and the revert pass unwinds the newest sale on it: the
    15-unit booking returns to RESERVED with its block reference cleared, the
    block's committed units fall to 0 and its released-back units rise to the 30
    ticket units the sale consumed. The block's state is recomputed from
    allocation against target, so it reads OPEN rather than anything derived from
    the now-zero committed figure.

    PRD §3.3: "This revert pass is the only mechanism in the entire system by
    which an `ALLOCATED` booking returns to `RESERVED`."

    Design: Difficulty/transitive_cascade/block_preemption_depth3_cascade_reverts_a_sold_allocation
    """
    scenario = _sold_out_partner_block(api)

    make_block(api, scenario["deal"]["id"], channel="CORPORATE",
               target_units=20, priority_rank=1)

    booking = read_booking(api, scenario["booking"]["id"])
    assert booking["fulfillment_status"] == "RESERVED"
    assert booking["allocation_block_id"] is None

    assert_block_position(read_block(api, scenario["partner_block"]["id"]),
                          allocated=20, committed=0, released_back=30, state="OPEN")


def test_the_preemption_unwind_touches_only_the_delivery_dimension(
    api: ApiClient,
) -> None:
    """The reverted booking keeps its price, its payments and its schedule.

    Nothing on the money side moved: the net price, the paid amount, the payment
    status and the rebooking counter are all as they were, and the three schedule
    lines are still scheduled. The fixture's risk is unchanged too, because the
    reverted booking's 30 ticket units still count as committed and 30 is below
    the 40 released.

    PRD §3.3: "for each such booking it takes the consumed quantity to be the
    booking's `units` multiplied by that booking's package's
    `tickets_per_package`, moves the booking `ALLOCATED → RESERVED`, clears its
    `allocation_block_id` to null, subtracts the consumed quantity from the
    block's `committed_units`, adds the same quantity to the block's
    `released_back_units`, and reduces the outstanding over-commitment by it."

    Design: Difficulty/transitive_cascade/block_preemption_depth3_cascade_reverts_a_sold_allocation
    """
    scenario = _sold_out_partner_block(api)

    make_block(api, scenario["deal"]["id"], channel="CORPORATE",
               target_units=20, priority_rank=1)

    booking = read_booking(api, scenario["booking"]["id"])
    assert booking["net_price_cents"] == 2285315
    assert booking["paid_cents"] == 0
    assert booking["payment_status"] == "UNPAID"
    assert booking["rebook_count"] == 0

    lines = installments_of(api, scenario["booking"]["id"])
    assert len(lines) == 3
    assert all(line["installment_kind"] == "SCHEDULE" for line in lines)
    assert all(line["installment_state"] == "SCHEDULED" for line in lines)

    assert_risk_band(read_event(api, scenario["event"]["id"]), score=0, posture="NORMAL")
