"""Every derived figure is final in the response of the request that caused it.

The probes here look for lag in the two places it could hide: the mutation's own
response body, and the very first read of each aggregate the mutation touched
indirectly, taken with no intervening call at all. Repeating those reads must
return the same figures, so nothing is allowed to converge on a second look.
"""

from typing import Any, Dict

from test_helpers import (
    CLIENT_SERVICE_AGENT,
    COMMERCIAL_MANAGER,
    FINANCE_CONTROLLER,
    RIGHTS_MANAGER,
    ApiClient,
    assert_block_position,
    assert_booking_price_buildup,
    assert_deal_position,
    assert_risk_band,
    booking_payload,
    commit_deal,
    confirm_tranche,
    deal_version,
    get_success_data,
    installments_of,
    make_block,
    make_client,
    make_deal,
    make_event,
    make_published_bronze_package,
    make_tranche,
    reset_clock,
)

CLOCK_START = "2026-08-01T00:00:00.000Z"


# --------------------------------------------------------------------------
# Scenario builder
# --------------------------------------------------------------------------


def _sellable_fixture_awaiting_its_release(api: ApiClient) -> Dict[str, Any]:
    """A committed 40-unit deal with one live block and one PENDING tranche.

    The block is created before the release, so confirming the tranche makes the
    waterfall fill it in the same request. A published BRONZE package priced at
    120000 and a corporate client with a large credit limit stand ready, so a
    single sale exercises the money breakdown, the client's exposure and the
    installment schedule at once.
    """
    reset_clock(api)
    event = make_event(api)
    deal = make_deal(api, event["id"], contracted_units=40,
                     guaranteed_minimum_units=20, unit_cost_cents=8000)
    commit_deal(api, deal["id"])
    block = make_block(api, deal["id"], channel="CORPORATE", target_units=40,
                       priority_rank=1)
    tranche = make_tranche(api, deal["id"], promised_units=40)
    package = make_published_bronze_package(api, event["id"])
    client = make_client(api)
    return {
        "event": event,
        "deal": deal,
        "block": block,
        "tranche": tranche,
        "package": package,
        "client": client,
    }


def _release_the_whole_contract(api: ApiClient, scenario: Dict[str, Any]) -> Dict[str, Any]:
    """Confirm the 40-unit tranche in full, pinning the deal's current version."""
    return confirm_tranche(api, scenario["tranche"]["id"], scenario["deal"]["id"], 40)


def _sell_five_units(api: ApiClient, scenario: Dict[str, Any]) -> Dict[str, Any]:
    """A 5-unit CORPORATE sale on the published package, returned as created."""
    payload = booking_payload(scenario["client"]["id"], scenario["package"]["id"],
                              units=5)
    return get_success_data(api.create_booking(payload, CLIENT_SERVICE_AGENT), 201)


# ==========================================================================
# The mutation's own response
# ==========================================================================


def test_the_confirmations_own_response_already_carries_its_finished_fields(
    api: ApiClient,
) -> None:
    """No field of the confirmed tranche is left null for a later pass.

    The response to the confirmation itself already reports the tranche as
    CONFIRMED, already carries the 40 confirmed units, and already bears the
    stamp taken from the logical clock — the write is complete when the caller
    sees it.

    PRD §3.2: "Either way `confirmed_units` is written, `confirmed_at` is stamped
    with the logical clock, the parent deal's `version` increases by one, and the
    deal's `released_units`, `shortfall_units`, `unallocated_units`,
    `minimum_liability_cents` and `deal_status` are all recomputed."

    Design: Corner/consistency_model/every_derived_field_is_final_in_the_response_that_caused_it
    """
    scenario = _sellable_fixture_awaiting_its_release(api)
    assert scenario["tranche"]["tranche_state"] == "PENDING"
    assert scenario["tranche"]["confirmed_at"] is None

    confirmed = _release_the_whole_contract(api, scenario)

    assert confirmed["tranche_state"] == "CONFIRMED"
    assert confirmed["confirmed_units"] == 40
    assert confirmed["confirmed_at"] == CLOCK_START


def test_the_first_read_of_the_parent_deal_after_the_release_is_already_final(
    api: ApiClient,
) -> None:
    """One read, no intervening call, and every recomputed figure is right.

    The confirmation's cascade re-derives the deal's whole position, and the very
    first read of it reports the finished answer: the contract is met, so the deal
    is FULLY_RELEASED with 40 released units, nothing is left unallocated because
    the block absorbed the lot, and the liability is 40 units at 8000 cents.

    PRD §2.9: "Derived fields are never stale."

    PRD §2.9: "`released_units`, `shortfall_units`, `unallocated_units` and
    `minimum_liability_cents` on a rights deal, `allocated_units`,
    `committed_units` and `released_back_units` on an allocation block,
    `base_cost_cents`, `component_price_subtotal_cents`, `list_price_cents` and
    `margin_pct` on a package, `line_cost_cents` and `line_price_cents` on a
    component, `outstanding_cents` and `overdue_installment_count` on a client,
    the whole price breakdown and `paid_cents` on a booking, `days_overdue` on an
    installment, `total_cost_cents` on a build, `active_assignment_count` on a
    host, and `fulfillment_risk_score` with its derived `risk_posture` on a
    fixture are all recomputed at the moment their inputs change, within the same
    request."

    Design: Corner/consistency_model/every_derived_field_is_final_in_the_response_that_caused_it
    """
    scenario = _sellable_fixture_awaiting_its_release(api)
    _release_the_whole_contract(api, scenario)

    deal = get_success_data(
        api.get_rights_deal(scenario["deal"]["id"], RIGHTS_MANAGER), 200
    )

    assert_deal_position(deal, released=40, shortfall=0, liability=320000,
                         status="FULLY_RELEASED", unallocated=0)


def test_the_sibling_block_and_the_grandparent_fixture_are_current_on_first_read(
    api: ApiClient,
) -> None:
    """The waterfall and the risk recomputation land inside the same request.

    Neither the block nor the fixture was named in the confirmation, yet the first
    read of each already reflects it: the block holds all 40 distributed units and
    is EXHAUSTED because that equals its target, and the fixture's derived risk is
    0 with a NORMAL posture — the release gap closed at once rather than decaying
    to zero over subsequent reads.

    PRD §3.9: "`risk_posture` is a band over that score, and both boundaries are
    inclusive: `CRITICAL` when `fulfillment_risk_score` is 70 or more, `ELEVATED`
    when it is 40 or more, and `NORMAL` otherwise."

    Design: Corner/consistency_model/every_derived_field_is_final_in_the_response_that_caused_it
    """
    scenario = _sellable_fixture_awaiting_its_release(api)
    _release_the_whole_contract(api, scenario)

    block = get_success_data(
        api.get_allocation_block(scenario["block"]["id"], COMMERCIAL_MANAGER), 200
    )
    event = get_success_data(
        api.get_event(scenario["event"]["id"], FINANCE_CONTROLLER), 200
    )

    assert_block_position(block, allocated=40, committed=0, released_back=0,
                          state="EXHAUSTED")
    assert_risk_band(event, score=0, posture="NORMAL")


def test_the_sales_own_response_carries_the_finished_money_breakdown(
    api: ApiClient,
) -> None:
    """The 201 body holds the whole build-up, not placeholders to be filled in.

    Five units of a 120000-cent package gross 600000; five units earn the 0.0400
    volume band, so 24000 comes off to leave 576000; the corporate channel takes
    3 percent of that subtotal as 17280; and the deal is fully released, so the
    fixture is not exposed and the surcharge is 0 — leaving a net of 558720. Both
    status dimensions open in their declared states in the same body.

    PRD §3.5: "`net_price_cents` is the discounted subtotal, less the partner
    commission, plus the guarantee surcharge."

    PRD §3.5: "A booking that survives all of that opens with `fulfillment_status`
    at `RESERVED` on its delivery dimension and `payment_status` at `UNPAID` on its
    money dimension, with `allocation_block_id`, `settlement_variant`,
    `credential_serial_prefix` and `itinerary` all null, and
    `credentials_issued_count` and `rebook_count` at 0."

    Design: Corner/consistency_model/every_derived_field_is_final_in_the_response_that_caused_it
    """
    scenario = _sellable_fixture_awaiting_its_release(api)
    _release_the_whole_contract(api, scenario)

    booking = _sell_five_units(api, scenario)

    assert_booking_price_buildup(booking, gross=600000, volume_discount_pct=0.0400,
                                 discounted_subtotal=576000, commission=17280,
                                 surcharge=0, net=558720)
    assert booking["payment_status"] == "UNPAID"
    assert booking["fulfillment_status"] == "RESERVED"


def test_the_clients_exposure_is_already_moved_when_the_sale_is_first_read_back(
    api: ApiClient,
) -> None:
    """The buyer's own record is current on the first read after the sale.

    The sale is the client's only booking and it is RESERVED with nothing paid, so
    the whole 558720 sits against the credit limit immediately, and the client is
    still ACTIVE.

    PRD §3.6: "Both figures are recomputed on booking creation, on cancellation,
    on rebooking, on installment payment, on fixture postponement, on fixture
    cancellation, and during the operations rollover."

    Design: Corner/consistency_model/every_derived_field_is_final_in_the_response_that_caused_it
    """
    scenario = _sellable_fixture_awaiting_its_release(api)
    _release_the_whole_contract(api, scenario)
    _sell_five_units(api, scenario)

    client = get_success_data(
        api.get_client(scenario["client"]["id"], FINANCE_CONTROLLER), 200
    )

    assert client["outstanding_cents"] == 558720
    assert client["client_status"] == "ACTIVE"


def test_the_schedule_already_exists_the_first_time_it_is_listed(
    api: ApiClient,
) -> None:
    """The installment lines are written by the sale, not by a later sweep.

    The fixture is 184 days away, so the schedule has three lines, and the first
    of them is thirty percent of 558720 — 167616 — already SCHEDULED when the
    collection is first listed for this booking.

    PRD §3.6: "The first line's `amount_cents` is thirty percent of the payable
    amount rounded half-up; the second line's is forty percent of the payable
    amount rounded half-up; and the third line's is the payable amount less the
    first two lines, computed by subtraction so that residual cents land on the
    last line and the three lines sum exactly to the payable amount with no
    drift."

    Design: Corner/consistency_model/every_derived_field_is_final_in_the_response_that_caused_it
    """
    scenario = _sellable_fixture_awaiting_its_release(api)
    _release_the_whole_contract(api, scenario)
    booking = _sell_five_units(api, scenario)

    lines = installments_of(api, booking["id"])

    assert [line["amount_cents"] for line in lines] == [167616, 223488, 167616]
    assert lines[0]["amount_cents"] == 167616
    assert lines[0]["installment_state"] == "SCHEDULED"


def test_reading_everything_a_second_time_returns_the_same_figures(
    api: ApiClient,
) -> None:
    """The first read was the settled answer, not a snapshot that converged.

    Re-reading the client and the deal after the sale gives byte-identical
    figures, so no read is what makes the numbers right and none of them drifts
    once the causing request has returned.

    PRD §2.9: "Derived fields are never stale."

    Design: Corner/consistency_model/every_derived_field_is_final_in_the_response_that_caused_it
    """
    scenario = _sellable_fixture_awaiting_its_release(api)
    _release_the_whole_contract(api, scenario)
    _sell_five_units(api, scenario)
    client_id = scenario["client"]["id"]
    deal_id = scenario["deal"]["id"]

    first_client = get_success_data(api.get_client(client_id, FINANCE_CONTROLLER), 200)
    first_deal = get_success_data(api.get_rights_deal(deal_id, RIGHTS_MANAGER), 200)
    second_client = get_success_data(api.get_client(client_id, FINANCE_CONTROLLER), 200)
    second_deal = get_success_data(api.get_rights_deal(deal_id, RIGHTS_MANAGER), 200)

    assert second_client["outstanding_cents"] == first_client["outstanding_cents"] == 558720
    assert second_deal["released_units"] == first_deal["released_units"] == 40
    assert second_deal["unallocated_units"] == first_deal["unallocated_units"] == 0
    assert second_deal["version"] == first_deal["version"]
    assert deal_version(api, deal_id) == first_deal["version"]
