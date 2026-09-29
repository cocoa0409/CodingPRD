"""Cyclic and multi-axis lifecycles: amendment rounds, dual-axis orders, dispute cycles."""

from test_helpers import (
    ANALYST_ONE,
    ApiClient,
    ApiErrorId,
    BALLROOM_B,
    EVENT_SERVICES,
    MEETING_ROOM_301,
    SPARKLECLEAN_EXCLUSIVE,
    amendment_round_trip,
    approve_service_order,
    assert_fields,
    assert_money_cents,
    assert_settlement_money,
    dispute_settlement,
    issue_settlement,
    make_analyst_headers,
    order_service,
    read_booking,
    read_license,
    read_service_order,
    read_settlement,
    reconcile_service_order,
    register_vendor,
    setup_event_lifecycle,
    validate_error,
    validate_success,
)

BALLROOM_JUNE_BOOKING = {
    "event_name": "Sunbelt Home & Garden Expo",
    "move_in_start_date": "2027-06-08",
    "show_start_date": "2027-06-10",
    "show_end_date": "2027-06-12",
    "move_out_end_date": "2027-06-13",
}


def _executed_ballroom_license(api: ApiClient):
    """A TENTATIVE Ballroom B booking whose license has been issued and countersigned."""
    return setup_event_lifecycle(
        api,
        "license_executed",
        space=dict(BALLROOM_B),
        deposit_cents=1400000,
        booking=dict(BALLROOM_JUNE_BOOKING),
    )


def _two_accepted_amendments(api: ApiClient):
    world = _executed_ballroom_license(api)
    license_id = world["license"]["id"]
    client_id = world["client"]["id"]
    amendment_round_trip(api, license_id, client_id, "shift move-in one day earlier")
    amendment_round_trip(api, license_id, client_id, "add the north concourse to the licensed space")
    return world


def test_license_re_enters_amendment_pending_and_returns_to_executed_twice(api: ApiClient):
    """Two negotiation rounds leave the license EXECUTED again with amendment_round 2.

    PRD: "A `SalesManager` opens a round on an `EXECUTED` license, driving
    `EXECUTED → AMENDMENT_PENDING`, and the request carries two fields: the
    stale-write guard `expected_license_version`, and `amendment_note`, whose text
    is stored on the license as `pending_amendment_note`."
    PRD: "The `Licensee` closes the round by accepting it, driving
    `AMENDMENT_PENDING → EXECUTED`, again subject to the ownership check on
    `X-User-ID`; acceptance increments `amendment_round` by 1 and clears
    `pending_amendment_note` back to null."

    Design: Difficulty/non_linear_state_machine/license_amendment_round_trips_executed_to_amendment_pending_and_back_twice
    """
    world = _two_accepted_amendments(api)

    license_row = read_license(api, world["license"]["id"])
    assert_fields(license_row, status="EXECUTED", amendment_round=2)
    assert license_row.get("pending_amendment_note") is None


def test_amendment_cycle_leaves_escrow_and_booking_state_untouched(api: ApiClient):
    """The escrowed deposit stays at 1350000 and the booking stays TENTATIVE across both rounds.

    PRD: "issuing a license moves the deposit out of the client's credit balance
    and into escrow, voiding or terminating a license moves it back, and finalizing
    a settlement moves it out of escrow and onto the settlement as
    `deposit_applied_cents`."
    PRD: "`deposit_required_cents` is `contracted_rental_cents` multiplied by one
    quarter, rounded half up to whole cents."

    Design: Difficulty/non_linear_state_machine/license_amendment_round_trips_executed_to_amendment_pending_and_back_twice
    """
    world = _two_accepted_amendments(api)

    license_row = read_license(api, world["license"]["id"])
    assert_money_cents(license_row["deposit_held_cents"], 1350000, "deposit_held_cents")

    assert_fields(read_booking(api, world["booking"]["id"]), status="TENTATIVE")


def _reconciled_cleaning_order(api: ApiClient):
    """A cleaning order approved at 2000 sqft and reconciled at 2600 sqft."""
    world = setup_event_lifecycle(
        api,
        "in_house",
        space=dict(MEETING_ROOM_301),
        deposit_cents=200000,
    )
    vendor = register_vendor(api, **dict(SPARKLECLEAN_EXCLUSIVE))
    order = order_service(api, world["booking"]["id"], vendor["id"], "CLEANING", 2000)
    approve_service_order(api, order["id"])
    reconcile_service_order(api, order["id"], 2600)
    world["vendor"] = vendor
    world["service_order"] = order
    return world


def test_cancel_is_refused_once_the_billing_axis_reached_reconciled(api: ApiClient):
    """A reconciled order cannot be cancelled even though its approval axis allows it.

    PRD: "**Cancelling** drives `PENDING_APPROVAL → CANCELLED`, where it likewise
    drives billing `UNBILLED → VOID`, or `APPROVED → CANCELLED`, where it drives
    billing `ESTIMATED → VOID` and resets `estimated_charge_cents` to 0 — but a
    cancel from `APPROVED` is refused when the row's `billing_status` has already
    reached `RECONCILED`, since money has by then been metered and the two
    dimensions must not contradict each other."
    PRD: "That refusal is `ERR_SERVICE_ORDER_STATE_INVALID`."

    Design: Difficulty/non_linear_state_machine/service_order_billing_dimension_blocks_approval_dimension_cancellation
    """
    world = _reconciled_cleaning_order(api)

    response = api.cancel_service_order(world["service_order"]["id"], headers=EVENT_SERVICES)
    validate_error(response, ApiErrorId.SERVICE_ORDER_STATE_INVALID, expected_status=409)

    assert_fields(
        read_service_order(api, world["service_order"]["id"]),
        approval_status="APPROVED",
        billing_status="RECONCILED",
    )


def test_both_status_axes_carry_their_own_priced_figure(api: ApiClient):
    """The order keeps 16200 from approval and gains 21060 from reconciliation.

    PRD: "Approval simultaneously drives the billing dimension `UNBILLED →
    ESTIMATED` on the same row and writes `estimated_charge_cents` from the pricing
    calculation over `ordered_quantity`."
    PRD: "**Reconciling** an order drives `ESTIMATED → RECONCILED`: the
    `EventServicesManager` submits the metered `actual_quantity`, which is stored on
    the row, and `actual_charge_cents` is written by re-running the pricing
    calculation over that actual quantity with the same tiers, timing factor,
    vendor multiplier, cap and floor."

    Design: Difficulty/non_linear_state_machine/service_order_billing_dimension_blocks_approval_dimension_cancellation
    """
    world = _reconciled_cleaning_order(api)

    order = read_service_order(api, world["service_order"]["id"])
    assert_money_cents(order["estimated_charge_cents"], 16200, "estimated_charge_cents")
    assert_money_cents(order["actual_charge_cents"], 21060, "actual_charge_cents")
    assert_fields(order, actual_quantity=2600, billing_status="RECONCILED")


def _settlement_disputed_with_revisions_exhausted(api: ApiClient):
    """A settlement round-tripped ISSUED/DISPUTED twice and sitting DISPUTED again."""
    world = setup_event_lifecycle(
        api,
        "settlement_issued",
        space=dict(BALLROOM_B),
        deposit_cents=1400000,
        booking=dict(BALLROOM_JUNE_BOOKING),
    )
    settlement_id = world["settlement"]["id"]
    client_id = world["client"]["id"]

    dispute_settlement(api, settlement_id, client_id, "rigging labour was billed to the wrong hall")
    issue_settlement(api, settlement_id)
    dispute_settlement(api, settlement_id, client_id, "the utilities meter reading is still disputed")
    issue_settlement(api, settlement_id)
    dispute_settlement(api, settlement_id, client_id, "the parties remain apart on the dark-day credit")
    return world


def test_third_re_issue_is_refused_once_two_revisions_have_run(api: ApiClient):
    """The re-issue edge closes once revision_round has reached two.

    PRD: "A re-issue out of `DISPUTED` additionally requires `revision_round` to be
    strictly less than two, else `ERR_SETTLEMENT_REVISION_LIMIT_REACHED`, and it
    increments `revision_round` by 1 and clears `dispute_reason` back to null."
    PRD: "The cycle from `ISSUED` to `DISPUTED` and back to `ISSUED` is therefore
    bounded at two revisions, after which the only way forward is arbitration."

    Design: Difficulty/non_linear_state_machine/settlement_dispute_cycle_exhausts_revisions_then_escalates_to_arbitration
    """
    world = _settlement_disputed_with_revisions_exhausted(api)

    response = api.issue_settlement(
        world["settlement"]["id"], headers=make_analyst_headers(ANALYST_ONE)
    )
    validate_error(response, ApiErrorId.SETTLEMENT_REVISION_LIMIT_REACHED, expected_status=409)

    assert_fields(read_settlement(api, world["settlement"]["id"]), status="DISPUTED", revision_round=2)


def test_escalation_opens_only_after_the_dispute_cycle_is_exhausted(api: ApiClient):
    """Escalating the exhausted settlement moves it to ARBITRATION with its totals intact.

    PRD: "**Escalating** drives `DISPUTED → ARBITRATION` and is available only once
    `revision_round` has reached two or more; escalating too early is refused with
    `ERR_SETTLEMENT_REVISION_LIMIT_REACHED`."
    PRD: "Escalation retains `dispute_reason` as the arbitration statement rather
    than clearing it."

    Design: Difficulty/non_linear_state_machine/settlement_dispute_cycle_exhausts_revisions_then_escalates_to_arbitration
    """
    world = _settlement_disputed_with_revisions_exhausted(api)

    response = api.escalate_settlement(
        world["settlement"]["id"], headers=make_analyst_headers(ANALYST_ONE)
    )
    validate_success(response, expected_status=200)

    settlement = read_settlement(api, world["settlement"]["id"])
    assert_fields(settlement, status="ARBITRATION", revision_round=2)
    assert_settlement_money(
        settlement, line_subtotal_cents=5400000, facility_service_fee_cents=378000
    )
