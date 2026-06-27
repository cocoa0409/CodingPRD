"""Second assertions for each difficulty-design instance.

Each test here pairs with a primary test elsewhere in the suite, exercising a
distinct, additionally PRD-grounded facet of the same difficulty instance so
every instance carries at least two tests.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    make_investor_headers,
    assert_surplus_conserves_gross,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f

TREASURER = TEST_USERS["treasurer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# --- dual_variant_calc -------------------------------------------------------

def test_redemption_credits_holder_and_redeems_sub_taxes(api):
    """PRD §3.9: "Redemption then settles the lien: it credits the holder's escrow
    with the payoff (the filed-deed-cost passthrough is reimbursement to the
    applicant and is handled outside the holder's lien credit), moves every
    `POSTED` subsequent tax on the certificate to `REDEEMED`"

    Design: Difficulty/dual_variant_calc/redemption_payoff_vs_premium_refund_on_certificate
    """
    ctx = fx.setup_active_certificate(
        county_overrides={"name": "CA County", "state_code": "CA",
                          "penalty_rate_bps": 500, "premium_bidding_enabled": False,
                          "premium_earns_interest": False, "day_count_basis": 365},
        parcel_overrides={"apn": "A-1", "base_tax_due_cents": 100_000},
        investor_escrow=200_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
    )
    county, cert, investor = ctx["county"], ctx["certificate"], ctx["investor"]

    fx.set_clock("2026-06-01T00:00:00Z")
    sub_tax = fx.add_sub_tax(county["id"], cert["id"], investor["id"], 2026, 50_000)

    # After winning (face 100000 committed) and sub-tax (50000 debited),
    # escrow = 200000 - 100000 - 50000 = 50000.
    inv_mid = validate_success(api.get_investor(investor["id"], AUDITOR))
    assert inv_mid["escrow_balance_cents"] == 50000

    fx.set_clock("2026-09-01T00:00:00Z")
    validate_success(
        api.redeem_certificate(county["id"], cert["id"], TREASURER), expected_status=201
    )

    # Holder credited the full 163065 payoff: 50000 + 163065 = 213065.
    inv_after = validate_success(api.get_investor(investor["id"], AUDITOR))
    assert inv_after["escrow_balance_cents"] == 213065

    sub_after, _meta = validate_paginated(
        api.list_sub_taxes(county["id"], cert["id"], AUDITOR)
    )
    assert sub_after[0]["status"] == "REDEEMED"


def test_premium_county_payoff_quote_mirrors_redemption(api):
    """PRD §3.9: "A non-mutating payoff quote is also available at the current
    logical-clock instant, returning `face_payoff_cents`, `face_interest_cents`,
    `penalty_cents`, `sub_tax_payoff_cents`, `sub_tax_interest_cents`,
    `premium_refund_cents`, `total_payoff_cents`, and the `as_of` instant it was
    computed at."

    Design: Difficulty/dual_variant_calc/premium_refund_with_interest_on_premium_county
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    county = fx.create_county(name="FL2 County", state_code="FL",
                              max_interest_rate_bps=1600, penalty_rate_bps=0,
                              premium_bidding_enabled=True, premium_earns_interest=True,
                              day_count_basis=365)
    parcel = fx.create_parcel(county["id"], apn="B2-1", base_tax_due_cents=100_000)
    investor = fx.create_funded_investor(200_000, legal_name="HolderB2", tax_id="TIN-B2")
    sale = fx.create_sale(county["id"], sale_name="Premium Sale")
    listing = fx.create_listing(county["id"], sale["id"], parcel["id"])
    validate_success(api.open_sale(county["id"], sale["id"], TREASURER))
    listing = validate_success(api.get_listing(county["id"], sale["id"], listing["id"], AUDITOR))
    fx.place_premium_bid(county["id"], sale["id"], listing["id"], investor["id"],
                         25_000, listing["version"])
    validate_success(api.close_sale(county["id"], sale["id"], TREASURER))
    cert = fx.get_certificate_for_parcel(county["id"], parcel["id"])

    fx.set_clock("2026-09-01T00:00:00Z")
    quote = validate_success(
        api.get_payoff_quote(county["id"], cert["id"], make_investor_headers(investor["id"]))
    )
    assert quote["premium_refund_cents"] == 27016
    assert quote["total_payoff_cents"] == 135082


# --- combinatorial_formula ---------------------------------------------------

def test_subtax_round_per_subtax_quote_matches(api):
    """PRD §2.6: "This per-component-then-sum ordering is mandatory wherever
    interest appears, both in a live redemption and in the snapshot taken at
    deed-application time."

    Design: Difficulty/combinatorial_formula/subtax_interest_round_per_subtax_then_sum
    """
    ctx = fx.setup_active_certificate(
        county_overrides={"name": "GA2 County", "state_code": "GA",
                          "penalty_rate_bps": 0, "day_count_basis": 365},
        parcel_overrides={"apn": "G2-1", "base_tax_due_cents": 100_000},
        investor_escrow=300_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
    )
    county, cert, investor = ctx["county"], ctx["certificate"], ctx["investor"]

    fx.set_clock("2026-08-31T00:00:00Z")
    fx.add_sub_tax(county["id"], cert["id"], investor["id"], 2025, 33_333)
    fx.add_sub_tax(county["id"], cert["id"], investor["id"], 2026, 33_333)

    fx.set_clock("2026-09-30T00:00:00Z")
    quote = validate_success(
        api.get_payoff_quote(county["id"], cert["id"], make_investor_headers(investor["id"]))
    )
    assert quote["sub_tax_payoff_cents"] == 66666
    assert quote["sub_tax_interest_cents"] == 876
    assert quote["total_payoff_cents"] == 174545


def test_minimum_bid_frozen_not_recomputed_at_award(api):
    """PRD §3.10: "This value is computed once at filing and frozen on the
    application; it is not recomputed at award."
    PRD §3.11: "`lien_satisfied_cents` is the smaller of the gross proceeds and the
    frozen `minimum_bid_cents`, and the former owner's `surplus_cents` is whatever
    remains above the floor"

    Design: Difficulty/combinatorial_formula/minimum_bid_three_input_nonlinear_position
    """
    ctx = fx.setup_foreclosure_pending_certificate(
        county_overrides={"name": "TX2 County", "state_code": "TX",
                          "penalty_rate_bps": 500, "day_count_basis": 365},
        parcel_overrides={"apn": "T2-1", "assessed_value_cents": 9_000_000,
                          "base_tax_due_cents": 100_000},
        investor_escrow=400_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
        sub_tax={"tax_year": 2026, "principal_cents": 50_000,
                 "posted_clock": "2026-06-01T00:00:00Z"},
        deed_filing_clock="2027-04-01T00:00:00Z",
        deed_cost_cents=30_000,
    )
    county, cert, deed = ctx["county"], ctx["certificate"], ctx["deed_application"]
    assert deed["minimum_bid_cents"] == 204682

    # Advance the clock well past filing, then award at exactly the frozen floor:
    # if the floor were recomputed it would be higher and the award would reject.
    fx.set_clock("2027-12-01T00:00:00Z")
    validate_success(
        api.award_deed(county["id"], deed["id"], f.award_deed_payload(204682), TREASURER)
    )
    surplus, _meta = validate_paginated(
        api.list_surplus_by_certificate(county["id"], cert["id"], AUDITOR)
    )
    assert surplus[0]["lien_satisfied_cents"] == 204682
    assert surplus[0]["surplus_cents"] == 0


# --- non_linear_state_machine ------------------------------------------------

def test_revision_loop_reopens_redemption_after_cancel(api):
    """PRD §3.10: "**Cancelling** it moves the deed application from `FILED` to
    `CANCELLED` and returns the certificate from `FORECLOSURE_PENDING` back to
    `ACTIVE`, reopening the possibility of redemption — this is the revision loop."

    Design: Difficulty/non_linear_state_machine/certificate_foreclosure_revision_loop
    """
    ctx = fx.setup_foreclosure_pending_certificate(
        county_overrides={"name": "Loop2 County", "state_code": "AZ",
                          "penalty_rate_bps": 0},
        parcel_overrides={"apn": "L2-1", "base_tax_due_cents": 100_000},
        investor_escrow=400_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
        sub_tax=None,
        deed_filing_clock="2027-04-01T00:00:00Z",
        deed_cost_cents=30_000,
    )
    county, cert, deed = ctx["county"], ctx["certificate"], ctx["deed_application"]

    validate_success(api.cancel_deed(county["id"], deed["id"], TREASURER))

    # Certificate is ACTIVE again -> redemption is once more possible.
    redemption = validate_success(
        api.redeem_certificate(county["id"], cert["id"], TREASURER), expected_status=201
    )
    cert_after = validate_success(api.get_certificate(county["id"], cert["id"], AUDITOR))
    assert cert_after["status"] == "REDEEMED"
    assert redemption["total_payoff_cents"] > 0


def test_deed_branch_cancel_drives_certificate_active(api):
    """PRD §3.10: "**Cancelling** it moves the deed application from `FILED` to
    `CANCELLED` and returns the certificate from `FORECLOSURE_PENDING` back to
    `ACTIVE`"

    Design: Difficulty/non_linear_state_machine/deed_application_branch_award_vs_cancel
    """
    ctx = fx.setup_foreclosure_pending_certificate(
        county_overrides={"name": "Branch2 County", "state_code": "TX",
                          "penalty_rate_bps": 500},
        parcel_overrides={"apn": "BR2-1", "assessed_value_cents": 9_000_000,
                          "base_tax_due_cents": 100_000},
        investor_escrow=400_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
        sub_tax={"tax_year": 2026, "principal_cents": 50_000,
                 "posted_clock": "2026-06-01T00:00:00Z"},
        deed_filing_clock="2027-04-01T00:00:00Z",
        deed_cost_cents=30_000,
    )
    county, cert, deed = ctx["county"], ctx["certificate"], ctx["deed_application"]

    cancelled = validate_success(api.cancel_deed(county["id"], deed["id"], TREASURER))
    assert cancelled["status"] == "CANCELLED"
    cert_after = validate_success(api.get_certificate(county["id"], cert["id"], AUDITOR))
    assert cert_after["status"] == "ACTIVE"


# --- transitive_cascade ------------------------------------------------------

def test_close_cascade_links_winning_bid_to_listing(api):
    """PRD §3.5: "Winning a listing makes it `SOLD`: its `winning_bid_id` and
    `certificate_id` are filled in, and a **certificate** is issued"

    Design: Difficulty/transitive_cascade/sale_close_award_listing_bid_certificate_parcel
    """
    ctx = fx.setup_open_sale_with_listing(
        county_overrides={"name": "Cascade2 County"},
        parcel_overrides={"apn": "CS2-1", "base_tax_due_cents": 100_000},
    )
    county, parcel, sale, listing = (
        ctx["county"], ctx["parcel"], ctx["sale"], ctx["listing"]
    )
    investor = fx.create_funded_investor(200_000, legal_name="HolderCS2", tax_id="TIN-CS2")
    bid = fx.place_rate_bid(county["id"], sale["id"], listing["id"], investor["id"],
                            1200, listing["version"])

    validate_success(api.close_sale(county["id"], sale["id"], TREASURER))

    listing_after = validate_success(
        api.get_listing(county["id"], sale["id"], listing["id"], AUDITOR)
    )
    assert listing_after["winning_bid_id"] == bid["id"]
    cert = fx.get_certificate_for_parcel(county["id"], parcel["id"])
    assert listing_after["certificate_id"] == cert["id"]


def test_deed_award_redeems_sub_taxes_and_credits_holder(api):
    """PRD §3.10: "On award the system creates a surplus distribution, credits the
    holder's escrow with the lien-satisfied amount, moves every `POSTED` subsequent
    tax to `REDEEMED`, sets the parcel's `status` to `DEEDED` and clears its
    `active_certificate_id` to null"

    Design: Difficulty/transitive_cascade/deed_award_surplus_certificate_parcel
    """
    ctx = fx.setup_foreclosure_pending_certificate(
        county_overrides={"name": "Surplus2 County", "state_code": "TX",
                          "penalty_rate_bps": 500},
        parcel_overrides={"apn": "SP2-1", "assessed_value_cents": 9_000_000,
                          "base_tax_due_cents": 100_000},
        investor_escrow=400_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
        sub_tax={"tax_year": 2026, "principal_cents": 50_000,
                 "posted_clock": "2026-06-01T00:00:00Z"},
        deed_filing_clock="2027-04-01T00:00:00Z",
        deed_cost_cents=30_000,
    )
    county, parcel, cert, deed = (
        ctx["county"], ctx["parcel"], ctx["certificate"], ctx["deed_application"]
    )

    validate_success(
        api.award_deed(county["id"], deed["id"], f.award_deed_payload(250_000), TREASURER)
    )
    sub_after, _meta = validate_paginated(
        api.list_sub_taxes(county["id"], cert["id"], AUDITOR)
    )
    assert sub_after[0]["status"] == "REDEEMED"
    parcel_after = validate_success(api.get_parcel(county["id"], parcel["id"], AUDITOR))
    assert parcel_after["active_certificate_id"] is None


# --- priority_pair_validation_conflict --------------------------------------

def test_after_deadline_insufficient_escrow_blocks_deed(api):
    """PRD §3.10: "Filing creates a deed application in `FILED` status, debits the
    holder's escrow by `deed_cost_cents`"
    PRD §2.10: "escrow sufficiency (`ERR_INSUFFICIENT_ESCROW`)"

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_redeem_period_open_beats_below_minimum
    """
    ctx = fx.setup_active_certificate(
        county_overrides={"name": "PVB County", "redemption_period_days": 365},
        parcel_overrides={"apn": "PVB-1", "base_tax_due_cents": 100_000},
        investor_escrow=200_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
    )
    county, cert, investor = ctx["county"], ctx["certificate"], ctx["investor"]

    # After the deadline the temporal gate passes; with only 100000 escrow left
    # a 150000 deed cost is unaffordable, so the fiscal check fires.
    fx.set_clock("2027-04-01T00:00:00Z")
    resp = api.create_deed_application(
        county["id"], cert["id"],
        f.create_deed_application_payload(investor["id"], 150_000),
        make_investor_headers(investor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ESCROW.value)


def test_wellformed_bid_on_closed_sale_still_invalid_state(api):
    """PRD §3.4: "While a sale is `OPEN`, an `Investor` places a **bid** on a
    listing"
    PRD §2.10: "a stale-version failure, for instance, is reported before a
    state-machine failure"

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_constraint_invalid_state_beats_invalid_bid
    """
    ctx = fx.setup_open_sale_with_listing(
        county_overrides={"name": "PV3 County"},
        parcel_overrides={"apn": "PV3-1", "base_tax_due_cents": 100_000},
    )
    county, sale, listing = ctx["county"], ctx["sale"], ctx["listing"]
    i1 = fx.create_funded_investor(200_000, legal_name="I1", tax_id="TIN-PV3-1")
    i2 = fx.create_funded_investor(200_000, legal_name="I2", tax_id="TIN-PV3-2")

    fx.place_rate_bid(county["id"], sale["id"], listing["id"], i1["id"],
                      1200, listing["version"])
    validate_success(api.close_sale(county["id"], sale["id"], TREASURER))

    listing_after = validate_success(
        api.get_listing(county["id"], sale["id"], listing["id"], make_investor_headers(i2["id"]))
    )
    # Perfectly valid rate (1100, a multiple of 100, below opening) but the sale
    # is CLOSED -> the state check rejects regardless of bid shape.
    resp = api.create_bid(
        county["id"], sale["id"], listing["id"],
        f.create_bid_payload(i2["id"], listing_after["version"], rate_bps=1100),
        make_investor_headers(i2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --- boundary_precision_check (sale_open_empty has the second test here) ------

def test_sale_with_one_listing_opens_successfully(api):
    """PRD §3.3: "A sale with no listings cannot open; an attempt with a
    `listing_count` of zero is rejected with `ERR_SALE_EMPTY`."

    Design: Difficulty/boundary_precision_check/sale_open_empty_listing_set_boundary
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    county = fx.create_county(name="NonEmpty County")
    parcel = fx.create_parcel(county["id"], apn="NE-1", base_tax_due_cents=100_000)
    sale = fx.create_sale(county["id"], scheduled_at="2026-03-01T00:00:00Z",
                          sale_name="Has Listing")
    fx.create_listing(county["id"], sale["id"], parcel["id"])

    opened = validate_success(api.open_sale(county["id"], sale["id"], TREASURER))
    assert opened["status"] == "OPEN"


# --- cross_entity_state_dependency ------------------------------------------

def test_deed_application_succeeds_after_deadline(api):
    """PRD §3.10: "the logical clock must have reached or passed the certificate's
    `redeem_deadline_at`, since an application filed before the redemption period
    has elapsed is rejected with `ERR_REDEMPTION_PERIOD_OPEN`"
    PRD §3.10: "Filing creates a deed application in `FILED` status, debits the
    holder's escrow by `deed_cost_cents`, moves the certificate from `ACTIVE` to
    `FORECLOSURE_PENDING`"

    Design: Difficulty/cross_entity_state_dependency/deed_application_depends_on_certificate_active_and_clock
    """
    ctx = fx.setup_active_certificate(
        county_overrides={"name": "CE3 County", "redemption_period_days": 365},
        parcel_overrides={"apn": "CE3-1", "base_tax_due_cents": 100_000},
        investor_escrow=400_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
    )
    county, cert, investor = ctx["county"], ctx["certificate"], ctx["investor"]

    fx.set_clock("2027-04-01T00:00:00Z")
    deed = validate_success(
        api.create_deed_application(
            county["id"], cert["id"],
            f.create_deed_application_payload(investor["id"], 30_000),
            make_investor_headers(investor["id"]),
        ),
        expected_status=201,
    )
    assert deed["status"] == "FILED"
    cert_after = validate_success(api.get_certificate(county["id"], cert["id"], AUDITOR))
    assert cert_after["status"] == "FORECLOSURE_PENDING"


def test_delinquent_parcel_can_be_listed(api):
    """PRD §3.3: "Creating a listing names a `parcel_id`; the listing copies its
    `opening_rate_bps` from the county's `max_interest_rate_bps` at that moment,
    starts in `LISTED` status with a null `winning_bid_id` and a null
    `certificate_id`, moves the referenced parcel from `DELINQUENT` to `ON_SALE`,
    and increments the sale's `listing_count`."

    Design: Difficulty/cross_entity_state_dependency/listing_creation_depends_on_parcel_status
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    county = fx.create_county(name="CE4 County")
    parcel = fx.create_parcel(county["id"], apn="CE4-1", base_tax_due_cents=100_000)
    sale = fx.create_sale(county["id"], sale_name="S")

    listing = validate_success(
        api.create_listing(county["id"], sale["id"], f.create_listing_payload(parcel["id"]), TREASURER),
        expected_status=201,
    )
    assert listing["status"] == "LISTED"
    parcel_after = validate_success(api.get_parcel(county["id"], parcel["id"], AUDITOR))
    assert parcel_after["status"] == "ON_SALE"


# --- resource_temporal_overlap ----------------------------------------------

def test_distinct_tax_year_sub_tax_accepted(api):
    """PRD §3.7: "Each `tax_year` may be paid only once per certificate; a
    duplicate year is rejected with `ERR_DUPLICATE_SUB_TAX`."

    Design: Difficulty/resource_temporal_overlap/duplicate_sub_tax_year_on_certificate
    """
    ctx = fx.setup_active_certificate(
        county_overrides={"name": "Ov3 County"},
        parcel_overrides={"apn": "OV3-1", "base_tax_due_cents": 100_000},
        investor_escrow=300_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
    )
    county, cert, investor = ctx["county"], ctx["certificate"], ctx["investor"]

    fx.add_sub_tax(county["id"], cert["id"], investor["id"], 2025, 40_000)
    # A different tax_year does not collide and is accepted.
    fx.add_sub_tax(county["id"], cert["id"], investor["id"], 2026, 10_000)

    cert_after = validate_success(api.get_certificate(county["id"], cert["id"], AUDITOR))
    assert cert_after["sub_tax_total_cents"] == 50000


def test_parcel_relistable_after_withdrawal(api):
    """PRD §3.3: "On withdrawal, every `PLACED` bid on that listing moves to
    `REFUNDED` and its escrow hold is released back to the bidder, and the parcel
    reverts from `ON_SALE` to `DELINQUENT` provided no other still-`LISTED` listing
    references it."

    Design: Difficulty/resource_temporal_overlap/duplicate_listing_for_parcel_on_open_sale
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    county = fx.create_county(name="Ov4 County")
    parcel = fx.create_parcel(county["id"], apn="OV4-1", base_tax_due_cents=100_000)
    sale1 = fx.create_sale(county["id"], scheduled_at="2026-03-01T00:00:00Z", sale_name="S1")
    listing1 = fx.create_listing(county["id"], sale1["id"], parcel["id"])
    sale2 = fx.create_sale(county["id"], scheduled_at="2026-03-02T00:00:00Z", sale_name="S2")

    # Withdraw the first listing -> parcel reverts to DELINQUENT.
    validate_success(api.withdraw_listing(county["id"], sale1["id"], listing1["id"], TREASURER))

    # Now the parcel can be attached to the second sale.
    listing2 = validate_success(
        api.create_listing(county["id"], sale2["id"], f.create_listing_payload(parcel["id"]), TREASURER),
        expected_status=201,
    )
    assert listing2["status"] == "LISTED"


# --- compensating_invariant --------------------------------------------------

def test_surplus_at_exact_floor_yields_zero_surplus(api):
    """PRD §3.11: "`lien_satisfied_cents` is the smaller of the gross proceeds and
    the frozen `minimum_bid_cents`, and the former owner's `surplus_cents` is
    whatever remains above the floor — the greater of 0 and the gross proceeds
    minus the `minimum_bid_cents`."

    Design: Difficulty/compensating_invariant/surplus_waterfall_conserves_gross_proceeds
    """
    ctx = fx.setup_foreclosure_pending_certificate(
        county_overrides={"name": "Inv2 County", "state_code": "TX",
                          "penalty_rate_bps": 500},
        parcel_overrides={"apn": "INV2-1", "assessed_value_cents": 9_000_000,
                          "base_tax_due_cents": 100_000},
        investor_escrow=400_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
        sub_tax={"tax_year": 2026, "principal_cents": 50_000,
                 "posted_clock": "2026-06-01T00:00:00Z"},
        deed_filing_clock="2027-04-01T00:00:00Z",
        deed_cost_cents=30_000,
    )
    county, cert, deed = ctx["county"], ctx["certificate"], ctx["deed_application"]

    validate_success(
        api.award_deed(county["id"], deed["id"], f.award_deed_payload(204682), TREASURER)
    )
    surplus, _meta = validate_paginated(
        api.list_surplus_by_certificate(county["id"], cert["id"], AUDITOR)
    )
    s = surplus[0]
    assert s["surplus_cents"] == 0
    assert s["lien_satisfied_cents"] == 204682
    assert_surplus_conserves_gross(s)


def test_winner_escrow_committed_face_deposit_unchanged(api):
    """PRD §3.2: "it subtracts the permanently committed cost of every winning bid
    (face amount plus any premium)"
    PRD §3.2: "The `deposit_total_cents` is simply the cumulative sum of deposits
    and never decreases."

    Design: Difficulty/compensating_invariant/bid_hold_release_conserves_investor_escrow
    """
    ctx = fx.setup_open_sale_with_listing(
        county_overrides={"name": "Esc2 County"},
        parcel_overrides={"apn": "ESC2-1", "base_tax_due_cents": 100_000},
    )
    county, sale, listing = ctx["county"], ctx["sale"], ctx["listing"]
    i1 = fx.create_funded_investor(200_000, legal_name="I1", tax_id="TIN-ESC2-1")
    i2 = fx.create_funded_investor(150_000, legal_name="I2", tax_id="TIN-ESC2-2")

    fx.place_rate_bid(county["id"], sale["id"], listing["id"], i1["id"], 1100, listing["version"])
    listing_v1 = validate_success(
        api.get_listing(county["id"], sale["id"], listing["id"], AUDITOR)
    )["version"]
    fx.place_rate_bid(county["id"], sale["id"], listing["id"], i2["id"], 1200, listing_v1)
    validate_success(api.close_sale(county["id"], sale["id"], TREASURER))

    i1_after = validate_success(api.get_investor(i1["id"], AUDITOR))
    # winner committed face 100000 -> escrow 100000, deposit_total unchanged.
    assert i1_after["escrow_balance_cents"] == 100000
    assert i1_after["deposit_total_cents"] == 200000
