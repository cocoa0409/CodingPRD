"""Sale-close award cascade, escrow hold/release accounting, struck-off and
withdrawal compensation, and immediate visibility of issued certificates.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_paginated,
    TEST_USERS,
    make_investor_headers,
    assert_certificate,
)
from test_helpers import fixtures as fx

TREASURER = TEST_USERS["treasurer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_sale_close_cascade_lists_listing_bid_certificate_parcel(api):
    """PRD §3.5: "The winning bid moves to `WON` and every other bid on that
    listing moves to `LOST`."
    PRD §3.5: "Winning a listing makes it `SOLD`: its `winning_bid_id` and
    `certificate_id` are filled in, and a **certificate** is issued — this is a
    transitive cascade from listing to bid to certificate to parcel."
    PRD §2.8: "when a certificate is issued, the parcel becomes `LIENED` and its
    `active_certificate_id` points at that certificate"

    Design: Difficulty/transitive_cascade/sale_close_award_listing_bid_certificate_parcel
    """
    ctx = fx.setup_open_sale_with_listing(
        county_overrides={"name": "Cascade County"},
        parcel_overrides={"apn": "CS-1", "base_tax_due_cents": 100_000},
    )
    county, parcel, sale, listing = (
        ctx["county"], ctx["parcel"], ctx["sale"], ctx["listing"]
    )
    investor = fx.create_funded_investor(200_000, legal_name="HolderCS", tax_id="TIN-CS1")
    bid = fx.place_rate_bid(county["id"], sale["id"], listing["id"], investor["id"],
                            1200, listing["version"])

    validate_success(api.close_sale(county["id"], sale["id"], TREASURER))

    listing_after = validate_success(
        api.get_listing(county["id"], sale["id"], listing["id"], AUDITOR)
    )
    assert listing_after["status"] == "SOLD"

    bid_after = validate_success(
        api.get_bid(county["id"], sale["id"], listing["id"], bid["id"], AUDITOR)
    )
    assert bid_after["status"] == "WON"

    parcel_after = validate_success(api.get_parcel(county["id"], parcel["id"], AUDITOR))
    assert parcel_after["status"] == "LIENED"
    assert parcel_after["active_certificate_id"] == listing_after["certificate_id"]


def test_losing_bid_releases_hold_winner_commits(api):
    """PRD §3.5: "The winner's hold converts to a permanent commitment (face
    amount plus premium debited for good, with no further escrow change), while
    each losing bidder's hold is released and credited back to their
    `escrow_balance_cents`."
    PRD §3.5: "In a rate-bid-down sale the winner is the bid with the lowest
    `rate_bps`, and ties at an equal rate are broken in favor of the
    earliest-created bid"

    Design: Difficulty/compensating_invariant/bid_hold_release_conserves_investor_escrow
    """
    ctx = fx.setup_open_sale_with_listing(
        county_overrides={"name": "Esc County"},
        parcel_overrides={"apn": "ESC-1", "base_tax_due_cents": 100_000},
    )
    county, sale, listing = ctx["county"], ctx["sale"], ctx["listing"]
    i1 = fx.create_funded_investor(200_000, legal_name="I1", tax_id="TIN-ESC1")
    i2 = fx.create_funded_investor(150_000, legal_name="I2", tax_id="TIN-ESC2")

    fx.place_rate_bid(county["id"], sale["id"], listing["id"], i1["id"],
                      1100, listing["version"])
    listing_v1 = validate_success(
        api.get_listing(county["id"], sale["id"], listing["id"], AUDITOR)
    )["version"]
    bid2 = fx.place_rate_bid(county["id"], sale["id"], listing["id"], i2["id"],
                             1200, listing_v1)

    validate_success(api.close_sale(county["id"], sale["id"], TREASURER))

    bid2_after = validate_success(
        api.get_bid(county["id"], sale["id"], listing["id"], bid2["id"], AUDITOR)
    )
    assert bid2_after["status"] == "LOST"

    i1_after = validate_success(api.get_investor(i1["id"], AUDITOR))
    i2_after = validate_success(api.get_investor(i2["id"], AUDITOR))
    # winner committed face 100000 -> 100000 remaining; loser's hold released -> 150000
    assert i1_after["escrow_balance_cents"] == 100000
    assert i2_after["escrow_balance_cents"] == 150000
    assert i2_after["deposit_total_cents"] == 150000


def test_winner_committed_escrow_excludes_loser_hold(api):
    """PRD §3.5: "The candidate set is exactly the listing's `PLACED` bids; bids
    already `LOST` or `REFUNDED` are excluded."
    PRD §3.2: "it subtracts the permanently committed cost of every winning bid
    (face amount plus any premium), adds back every hold that was released when a
    bid lost or was refunded"

    Design: Corner/calculations/redemption_excludes_lost_bids_input_set
    """
    ctx = fx.setup_open_sale_with_listing(
        county_overrides={"name": "IS County"},
        parcel_overrides={"apn": "IS-1", "base_tax_due_cents": 100_000},
    )
    county, sale, listing = ctx["county"], ctx["sale"], ctx["listing"]
    i1 = fx.create_funded_investor(200_000, legal_name="I1", tax_id="TIN-IS1")
    i2 = fx.create_funded_investor(150_000, legal_name="I2", tax_id="TIN-IS2")

    bid1 = fx.place_rate_bid(county["id"], sale["id"], listing["id"], i1["id"],
                             1100, listing["version"])
    listing_v1 = validate_success(
        api.get_listing(county["id"], sale["id"], listing["id"], AUDITOR)
    )["version"]
    bid2 = fx.place_rate_bid(county["id"], sale["id"], listing["id"], i2["id"],
                             1200, listing_v1)

    validate_success(api.close_sale(county["id"], sale["id"], TREASURER))

    bid1_after = validate_success(
        api.get_bid(county["id"], sale["id"], listing["id"], bid1["id"], AUDITOR)
    )
    bid2_after = validate_success(
        api.get_bid(county["id"], sale["id"], listing["id"], bid2["id"], AUDITOR)
    )
    assert bid1_after["status"] == "WON"
    assert bid2_after["status"] == "LOST"

    i1_after = validate_success(api.get_investor(i1["id"], AUDITOR))
    i2_after = validate_success(api.get_investor(i2["id"], AUDITOR))
    assert i1_after["escrow_balance_cents"] == 100000
    assert i2_after["escrow_balance_cents"] == 150000


def test_sale_close_zero_bids_strikes_off_listing(api):
    """PRD §3.5: "A listing that is still `LISTED` but has zero `PLACED` bids is
    **struck off** to `STRUCK_OFF` and produces no certificate; its parcel reverts
    from `ON_SALE` to `DELINQUENT` unless some other path has already liened it."

    Design: Corner/state_machines/sale_close_zero_bids_struck_off
    """
    ctx = fx.setup_open_sale_with_listing(
        county_overrides={"name": "StruckOff County"},
        parcel_overrides={"apn": "SO-1", "base_tax_due_cents": 100_000},
    )
    county, parcel, sale, listing = (
        ctx["county"], ctx["parcel"], ctx["sale"], ctx["listing"]
    )

    validate_success(api.close_sale(county["id"], sale["id"], TREASURER))

    listing_after = validate_success(
        api.get_listing(county["id"], sale["id"], listing["id"], AUDITOR)
    )
    assert listing_after["status"] == "STRUCK_OFF"
    assert listing_after["certificate_id"] is None

    parcel_after = validate_success(api.get_parcel(county["id"], parcel["id"], AUDITOR))
    assert parcel_after["status"] == "DELINQUENT"


def test_withdraw_listing_refunds_bid_and_reverts_parcel(api):
    """PRD §3.3: "On withdrawal, every `PLACED` bid on that listing moves to
    `REFUNDED` and its escrow hold is released back to the bidder, and the parcel
    reverts from `ON_SALE` to `DELINQUENT` provided no other still-`LISTED` listing
    references it."

    Design: Corner/state_machines/withdraw_listing_refunds_bids_reverts_parcel
    """
    ctx = fx.setup_open_sale_with_listing(
        county_overrides={"name": "Withdraw County"},
        parcel_overrides={"apn": "WD-1", "base_tax_due_cents": 100_000},
    )
    county, parcel, sale, listing = (
        ctx["county"], ctx["parcel"], ctx["sale"], ctx["listing"]
    )
    investor = fx.create_funded_investor(200_000, legal_name="I1", tax_id="TIN-WD1")
    bid = fx.place_rate_bid(county["id"], sale["id"], listing["id"], investor["id"],
                            1200, listing["version"])

    validate_success(api.withdraw_listing(county["id"], sale["id"], listing["id"], TREASURER))

    listing_after = validate_success(
        api.get_listing(county["id"], sale["id"], listing["id"], AUDITOR)
    )
    assert listing_after["status"] == "WITHDRAWN"

    bid_after = validate_success(
        api.get_bid(county["id"], sale["id"], listing["id"], bid["id"], AUDITOR)
    )
    assert bid_after["status"] == "REFUNDED"

    inv_after = validate_success(api.get_investor(investor["id"], AUDITOR))
    assert inv_after["escrow_balance_cents"] == 200000

    parcel_after = validate_success(api.get_parcel(county["id"], parcel["id"], AUDITOR))
    assert parcel_after["status"] == "DELINQUENT"


def test_settle_closed_sale_advances_to_settled(api):
    """PRD §3.5: "After the close, settling the sale advances it from `CLOSED` to
    `SETTLED`; settlement requires the sale to be `CLOSED` (otherwise
    `ERR_INVALID_STATE`), finalizes the event, and leaves the certificates already
    issued at close untouched."

    Design: Corner/endpoints/settle_sale_after_close
    """
    ctx = fx.setup_active_certificate(
        county_overrides={"name": "Settle County"},
        parcel_overrides={"apn": "ST-1", "base_tax_due_cents": 100_000},
        investor_escrow=200_000, winning_rate_bps=1200,
    )
    county, sale = ctx["county"], ctx["sale"]

    settled = validate_success(api.settle_sale(county["id"], sale["id"], TREASURER))
    assert settled["status"] == "SETTLED"


def test_certificate_immediately_visible_after_close(api):
    """PRD §3.6: "Certificates can be read directly and listed in a county,
    filtered by `parcel_id`, `listing_id`, `holder_investor_id`, `county_id`, or
    `status`."
    PRD §3.5: "Winning a listing makes it `SOLD`: its `winning_bid_id` and
    `certificate_id` are filled in, and a **certificate** is issued"

    Design: Corner/consistency_model/immediate_visibility_of_certificate_after_close
    """
    ctx = fx.setup_open_sale_with_listing(
        county_overrides={"name": "IM County"},
        parcel_overrides={"apn": "IM-1", "base_tax_due_cents": 100_000},
    )
    county, parcel, sale, listing = (
        ctx["county"], ctx["parcel"], ctx["sale"], ctx["listing"]
    )
    investor = fx.create_funded_investor(200_000, legal_name="I1", tax_id="TIN-IM1")
    fx.place_rate_bid(county["id"], sale["id"], listing["id"], investor["id"],
                      1200, listing["version"])
    validate_success(api.close_sale(county["id"], sale["id"], TREASURER))

    data, meta = validate_paginated(
        api.list_certificates(county["id"], AUDITOR, {"parcel_id": parcel["id"]})
    )
    assert meta["total_count"] == 1
    cert = data[0]
    assert_certificate(cert)
    assert cert["status"] == "ACTIVE"
