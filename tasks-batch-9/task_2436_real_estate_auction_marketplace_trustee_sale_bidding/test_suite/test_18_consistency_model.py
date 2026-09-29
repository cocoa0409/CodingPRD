"""Side effects are never deferred: the reads issued straight after an outbidding bid already
show the demotion, both released and newly held money, both recomputed ledgers and the lot's
new high bid, with no second call, retry or refresh."""

from test_helpers import (
    CLOCK_EVENT_OPEN,
    LOT_WINDOW_END,
    TEST_USERS,
    api_client,
    assert_timestamp_equals,
    funded_bidder,
    open_event,
    place_bid,
    read_bid,
    read_bidder,
    read_lot,
    scheduled_lot,
    set_clock,
    validate_paginated,
)

OPS = TEST_USERS["auction_ops_headers"]

CLOCK_SECOND_BID = "2026-09-15T17:20:00Z"


def test_one_outbidding_call_leaves_every_derived_row_already_settled():
    """The outbidding bid's own response, the displaced bid, the lot, both bidder ledgers and
    both deposit holds are all read once, immediately afterwards, and each already carries its
    final value.

    PRD: "Acceptance rewrites the lot's competitive state in one atomic step. The bid that was
    standing — the one bid on the lot whose `bid_status` is `ACTIVE` — becomes `OUTBID`, and
    that displaced bidder's deposit hold on the lot is `RELEASED` with a `released_reason` of
    `OUTBID`, returning their money to their available balance immediately rather than at the
    end of the session."
    PRD: "The new bid is written with a `bid_status` of `ACTIVE` and a `placed_at` stamped from
    the logical clock."
    PRD: "Its `is_above_reserve` flag is fixed at acceptance as whether the `amount_cents` is
    greater than or equal to the lot's `reserve_price_cents`, and it is never revisited
    afterwards, even if the reserve is somehow different later."
    PRD: "A deposit hold of exactly `required_deposit_cents` is created for the incoming bidder
    with a `status` of `HELD`, unless that bidder already holds a live hold on this lot, in
    which case the existing hold is left in place and reused."
    PRD: "Both bidders' deposit ledgers are then recomputed, the lot's `current_high_bid_cents`
    is set to the accepted `amount_cents`, and the lot's `version` advances by 1."
    PRD: "Holds whose `status` is `RELEASED` contribute to none of the three terms, which is
    what allows a released hold to return money to the available balance without any explicit
    credit."
    PRD: "Otherwise `bid_close_at` is left exactly where it was and the bid records
    `triggered_extension` as false."

    Design: Corner/consistency_model/one_bid_makes_every_derived_row_visible_in_the_same_request
    """
    scenario = scheduled_lot(
        org_name="Immediate Bank",
        seller_type="BANK",
        contact_email="i@immediate.example",
        settlement_account_ref="ACH-IMMD",
        street_address="1 Immediate Rd",
        city="Oakland",
        estimated_value_cents=26000000,
        event_title="Immediate Event",
        opening_bid_cents=20000000,
        reserve_price_cents=20000000,
    )
    first = funded_bidder(
        1000000,
        legal_name="Immediate First LLC",
        email="first@immediate.example",
        mailing_address="2 Immediate Rd, Oakland CA",
        document_reference="KYC-IMMD-1",
        funding_reference="WIRE-IMMD-1",
    )
    second = funded_bidder(
        1000000,
        legal_name="Immediate Second LLC",
        email="second@immediate.example",
        mailing_address="3 Immediate Rd, Oakland CA",
        document_reference="KYC-IMMD-2",
        funding_reference="WIRE-IMMD-2",
    )

    set_clock(CLOCK_EVENT_OPEN)
    open_event(scenario.event_id)
    assert read_lot(scenario.lot_id)["required_deposit_cents"] == 1000000
    standing = place_bid(scenario.lot_id, first["id"], 20000000)

    set_clock(CLOCK_SECOND_BID)
    raising = place_bid(scenario.lot_id, second["id"], 20500000)
    assert raising["bid_status"] == "ACTIVE"
    assert raising["is_above_reserve"] is True
    assert raising["triggered_extension"] is False
    assert_timestamp_equals(raising["placed_at"], CLOCK_SECOND_BID)

    assert read_bid(standing["id"], OPS)["bid_status"] == "OUTBID"

    lot = read_lot(scenario.lot_id, OPS)
    assert lot["current_high_bid_cents"] == 20500000
    assert lot["lot_status"] == "OPEN"
    assert lot["extension_count"] == 0
    assert_timestamp_equals(lot["bid_close_at"], LOT_WINDOW_END)

    displaced = read_bidder(first["id"], OPS)
    assert displaced["deposit_available_cents"] == 1000000
    assert displaced["deposit_funded_cents"] == 1000000
    assert read_bidder(second["id"], OPS)["deposit_available_cents"] == 0

    released, released_meta = validate_paginated(
        api_client.list_deposit_holds(
            OPS, params={"auction_lot_id": scenario.lot_id, "status": "RELEASED"}
        )
    )
    assert released_meta["total_count"] == 1
    assert released[0]["released_reason"] == "OUTBID"
    assert released[0]["bidder_id"] == first["id"]

    held, held_meta = validate_paginated(
        api_client.list_deposit_holds(
            OPS, params={"auction_lot_id": scenario.lot_id, "status": "HELD"}
        )
    )
    assert held_meta["total_count"] == 1
    assert held[0]["amount_cents"] == 1000000
    assert held[0]["bidder_id"] == second["id"]

    bids, bids_meta = validate_paginated(
        api_client.list_bids(OPS, params={"auction_lot_id": scenario.lot_id})
    )
    assert bids_meta["total_count"] == 2
    assert {row["id"]: row["bid_status"] for row in bids} == {
        standing["id"]: "OUTBID",
        raising["id"]: "ACTIVE",
    }
