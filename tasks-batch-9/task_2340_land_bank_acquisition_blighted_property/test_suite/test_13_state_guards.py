"""
Transitions the API must refuse, and the rows they must leave untouched.

Every test here drives a target record into the state the guard protects against,
fires the transition anyway, and then re-reads the target row, the parcel and the
funding ledger to prove that a refused transition writes nothing at all.
"""

from typing import Any, Dict

from test_helpers import (
    ApiClient,
    ApiErrorId,
    CLERK_1,
    DISP_1,
    INTAKE_1,
    INTAKE_2,
    INV_1,
    assert_ledger_position,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

# A 10,000 sqft mow: ten started thousand-square-foot blocks at 1,850 cents give
# an 18,500-cent subtotal, plus 1,203 cents of county overhead rounded half up.
MOW_ESTIMATE_10K_SQFT_CENTS = 19703

# A grade D, 10,000 sqft demolition: a 950,000-cent base, 620,000 cents of
# per-area charge, an 18 percent asbestos surcharge of 282,600 cents on those two,
# and 120,419 cents of county overhead on the 1,852,600-cent subtotal.
DEMOLITION_ESTIMATE_10K_SQFT_GRADE_D_CENTS = 1973019


def _negotiated_packet(
    api: ApiClient,
    property_id: str,
    funding_source_id: str,
    *,
    offer_price_cents: int,
    title_search_fee_cents: int = 0,
) -> Dict[str, Any]:
    """
    Open a negotiated-purchase packet. A negotiated purchase carries neither a
    foreclosure case number nor a donor name.
    """
    payload = factories.without(
        factories.acquisition_packet_payload(
            property_id,
            funding_source_id,
            channel="NEGOTIATED_PURCHASE",
            offer_price_cents=offer_price_cents,
            title_search_fee_cents=title_search_fee_cents,
        ),
        "donor_name",
    )
    return validate_success(api.create_acquisition_packet(payload, INTAKE_1), 201)


def test_board_approval_on_a_constrained_source_is_refused(api: ApiClient) -> None:
    """
    A funding source that has fallen below its reserve floor may not take a new acquisition commitment even when the balance would cover it.

    A `CONSTRAINED` source still funds demolition, securing and mowing work — blight does not wait for a budget to recover — but it may not take a new acquisition commitment, and an attempt to board-approve a packet against it is refused with `ERR_FUNDING_CONSTRAINED`.
    Design: Corner/state_machines/board_approval_on_constrained_source_rejected
    """
    source = fixtures.create_funding_source(
        api,
        name="Constrained Acquisition Line",
        source_type="GENERAL_FUND",
        authorized_cents=100000,
        restriction="ANY",
    )
    # 5 percent of the authorization, rounded half up.
    assert source["reserve_floor_cents"] == 5000
    first_parcel = fixtures.create_property(api, address="1020 Juniper St")
    first_packet = _negotiated_packet(
        api, first_parcel["id"], source["id"], offer_price_cents=96000
    )
    fixtures.board_approve_packet(api, first_packet["id"])
    assert_ledger_position(
        fixtures.read_funding_source(api, source["id"]),
        committed_cents=96000,
        available_cents=4000,
        status="CONSTRAINED",
    )
    # A packet opened after the source was constrained is still in due diligence,
    # and the 4,000 cents left would cover its 1,000-cent ask.
    second_parcel = fixtures.create_property(api, address="1021 Juniper St")
    second_packet = _negotiated_packet(
        api, second_parcel["id"], source["id"], offer_price_cents=1000
    )
    assert second_packet["status"] == "DUE_DILIGENCE"

    response = api.board_approve_packet(
        second_packet["id"], {"resolution_no": "R-2026-321"}, CLERK_1
    )

    validate_error(response, ApiErrorId.FUNDING_CONSTRAINED.value, 422)
    unchanged = fixtures.read_packet(api, second_packet["id"])
    assert unchanged["status"] == "DUE_DILIGENCE"
    assert unchanged["committed_cents"] == 0
    assert unchanged["resolution_no"] is None
    assert_ledger_position(
        fixtures.read_funding_source(api, source["id"]),
        authorized_cents=100000,
        committed_cents=96000,
        disbursed_cents=0,
        available_cents=4000,
        status="CONSTRAINED",
    )


def test_completing_a_cancelled_order_is_refused(api: ApiClient) -> None:
    """
    A cancelled maintenance order can no longer be completed.

    An `InventoryManager` completes an order still in `SCHEDULED` — anything else is `ERR_ORDER_NOT_SCHEDULED` — by supplying the invoiced `actual_cost_cents`, which may be zero but not negative.
    Design: Corner/state_machines/order_completion_after_cancel_is_rejected
    """
    source = fixtures.create_funding_source(
        api,
        name="Cancel Then Complete Line",
        source_type="GRANT",
        authorized_cents=1000000,
        restriction="ANY",
    )
    bundle = fixtures.acquired_parcel(
        api,
        funding_source=source,
        property_overrides={
            "address": "1050 Maple St",
            "lot_area_sqft": 10000,
            "assessed_value_cents": 300000,
            "structure_present": True,
            "structure_condition_grade": "C",
            "vacancy_months": 4,
        },
    )
    contractor = fixtures.create_contractor(
        api, name="Mow Masters Inc", max_concurrent_crews=2, specialties=["MOW"]
    )
    order = fixtures.schedule_order(
        api,
        bundle["property"]["id"],
        funding_source_id=source["id"],
        contractor_id=contractor["id"],
        work_type="MOW",
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-06T00:00:00Z",
    )
    assert order["estimated_cost_cents"] == MOW_ESTIMATE_10K_SQFT_CENTS
    cancelled = fixtures.cancel_order(
        api, order["id"], "Crew reassigned to storm response"
    )
    assert cancelled["status"] == "CANCELLED"

    response = api.complete_maintenance_order(
        order["id"], {"actual_cost_cents": 18000}, INV_1
    )

    validate_error(response, ApiErrorId.ORDER_NOT_SCHEDULED.value, 409)
    unchanged = fixtures.read_order(api, order["id"])
    assert unchanged["status"] == "CANCELLED"
    assert unchanged["actual_cost_cents"] is None
    assert unchanged["completed_at"] is None
    # The cancellation released the estimate and nothing was ever disbursed: the
    # donation channel paid no purchase price and no title search fee.
    assert_ledger_position(
        fixtures.read_funding_source(api, source["id"]),
        authorized_cents=1000000,
        committed_cents=0,
        disbursed_cents=0,
        available_cents=1000000,
    )


def test_closing_a_declined_packet_is_refused(api: ApiClient) -> None:
    """
    A declined acquisition packet can never be closed into inventory.

    Closing is refused with `ERR_PACKET_INVALID_STATE` from any other packet state.
    Design: Corner/state_machines/declined_packet_cannot_be_closed
    """
    source = fixtures.create_funding_source(
        api,
        name="Terminal Lockdown Line",
        source_type="GENERAL_FUND",
        authorized_cents=500000,
        restriction="ANY",
    )
    parcel = fixtures.create_property(
        api,
        address="1060 Nettle St",
        lot_area_sqft=6000,
        assessed_value_cents=300000,
        structure_present=True,
        structure_condition_grade="C",
        vacancy_months=4,
    )
    packet = _negotiated_packet(
        api,
        parcel["id"],
        source["id"],
        offer_price_cents=40000,
        title_search_fee_cents=5000,
    )
    declined = fixtures.decline_packet(
        api, packet["id"], "Environmental risk found in due diligence"
    )
    assert declined["status"] == "DECLINED"

    # A second intake officer closes, so the four-eyes rule is satisfied and the
    # packet's own state is the only obstacle left.
    response = api.close_packet(
        packet["id"], {"deed_reference": "BK-4560-PG-01"}, INTAKE_2
    )

    validate_error(response, ApiErrorId.PACKET_INVALID_STATE.value, 409)
    unchanged = fixtures.read_packet(api, packet["id"])
    assert unchanged["status"] == "DECLINED"
    assert unchanged["closed_by_user_id"] is None
    assert unchanged.get("deed_reference") is None
    parcel_after = fixtures.read_property(api, parcel["id"])
    assert parcel_after["custody_status"] == "PROSPECT"
    assert parcel_after["acquired_at"] is None
    assert_ledger_position(
        fixtures.read_funding_source(api, source["id"]),
        committed_cents=0,
        disbursed_cents=0,
        available_cents=500000,
    )


def test_second_adjudication_of_the_same_title_action_is_refused(
    api: ApiClient,
) -> None:
    """
    An adjudicated title action cannot be adjudicated a second time.

    Adjudicating an action that already reached `CLEARED` or `DEFECT_REMAINS` is refused with `ERR_TITLE_ACTION_ALREADY_ADJUDICATED`.
    Design: Corner/state_machines/second_adjudication_of_same_title_action_rejected
    """
    parcel = fixtures.create_property(
        api,
        address="1070 Olive St",
        lot_area_sqft=6000,
        assessed_value_cents=300000,
        structure_present=True,
        structure_condition_grade="C",
        vacancy_months=4,
    )
    action = fixtures.open_title_action(api, parcel["id"])
    adjudicated = fixtures.adjudicate_title_action(api, action["id"], "CLEARED")
    assert adjudicated["status"] == "CLEARED"
    adjudicated_at = adjudicated["adjudicated_at"]
    parcel_before = fixtures.read_property(api, parcel["id"])

    response = api.adjudicate_title_action(
        action["id"], {"outcome": "CLEARED"}, INTAKE_1
    )

    validate_error(response, ApiErrorId.TITLE_ACTION_ALREADY_ADJUDICATED.value, 409)
    actions, _meta = validate_paginated(
        api.list_title_actions(parcel["id"], INTAKE_1)
    )
    unchanged = [row for row in actions if row["id"] == action["id"]][0]
    assert unchanged["status"] == "CLEARED"
    assert unchanged["adjudicated_at"] == adjudicated_at
    assert unchanged["defect_count"] == 0
    parcel_after = fixtures.read_property(api, parcel["id"])
    assert parcel_after["title_status"] == "CLEAR"
    # A refused replay mutates nothing, so the parcel's version cannot move.
    assert parcel_after["version"] == parcel_before["version"]


def test_listing_is_blocked_while_a_demolition_order_is_scheduled(
    api: ApiClient,
) -> None:
    """
    A parcel carrying a scheduled demolition order may not be listed, and cancelling that order unblocks the same listing call.

    A parcel with a demolition order still in `SCHEDULED` may not be listed at all and is refused with `ERR_PROPERTY_NOT_IN_INVENTORY` — the authority does not market a parcel it is about to knock down.
    Design: Corner/state_machines/listing_blocked_while_demolition_order_scheduled
    """
    source = fixtures.create_funding_source(
        api,
        name="Demolition Guard Line",
        source_type="GRANT",
        authorized_cents=5000000,
        restriction="ANY",
    )
    parcel = fixtures.create_property(
        api,
        address="1090 Quince St",
        lot_area_sqft=10000,
        assessed_value_cents=300000,
        structure_present=True,
        structure_condition_grade="D",
        vacancy_months=4,
    )
    packet = fixtures.open_packet(
        api, parcel["id"], source["id"], title_search_fee_cents=12000
    )
    fixtures.board_approve_packet(api, packet["id"])
    fixtures.close_packet(api, packet["id"])
    action = fixtures.open_title_action(api, parcel["id"], "TAX_DEED_CONFIRMATION")
    fixtures.adjudicate_title_action(api, action["id"], "CLEARED")
    contractor = fixtures.create_contractor(
        api,
        name="Wrecking Ball Co",
        max_concurrent_crews=2,
        specialties=["DEMOLITION"],
    )
    order = fixtures.schedule_order(
        api,
        parcel["id"],
        funding_source_id=source["id"],
        contractor_id=contractor["id"],
        work_type="DEMOLITION",
        window_start="2026-08-10T00:00:00Z",
        window_end="2026-08-20T00:00:00Z",
    )
    assert order["estimated_cost_cents"] == (
        DEMOLITION_ESTIMATE_10K_SQFT_GRADE_D_CENTS
    )

    blocked = api.list_property_for_disposition(parcel["id"], DISP_1)

    validate_error(blocked, ApiErrorId.PROPERTY_NOT_IN_INVENTORY.value, 409)
    unchanged = fixtures.read_property(api, parcel["id"])
    assert unchanged["custody_status"] == "ACQUIRED"
    # The parcel's own title was never the obstacle.
    assert unchanged["title_status"] == "CLEAR"
    assert unchanged["listed_at"] is None

    fixtures.cancel_order(api, order["id"], "Demolition deferred pending historic review")
    allowed = validate_success(
        api.list_property_for_disposition(parcel["id"], DISP_1)
    )

    assert allowed["custody_status"] == "LISTED"
    # The cancel released the estimate; only the 12,000-cent title search fee of
    # the closed packet was ever disbursed.
    assert_ledger_position(
        fixtures.read_funding_source(api, source["id"]),
        authorized_cents=5000000,
        committed_cents=0,
        disbursed_cents=12000,
        available_cents=4988000,
    )
