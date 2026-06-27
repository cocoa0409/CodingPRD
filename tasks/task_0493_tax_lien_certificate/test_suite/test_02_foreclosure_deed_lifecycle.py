"""Foreclosure lifecycle: deed application filing (minimum_bid snapshot), the
ACTIVE<->FORECLOSURE_PENDING revision loop, the award branch (DEEDED + surplus),
and the surplus waterfall invariant.
"""
import pytest

from test_helpers import (
    validate_success,
    TEST_USERS,
    make_investor_headers,
    assert_deed_application,
    assert_surplus_distribution,
    assert_surplus_conserves_gross,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f

TREASURER = TEST_USERS["treasurer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_minimum_bid_frozen_at_filing_three_input_position(api):
    """PRD §3.10: "At filing, the application freezes a `minimum_bid_cents` — the
    floor price the property must fetch at the deed sale — as a snapshot of the
    holder's full position plus the deed cost."
    PRD §3.10: "The `minimum_bid_cents` is that position plus the
    `deed_cost_cents`. This value is computed once at filing and frozen on the
    application; it is not recomputed at award."

    Design: Difficulty/combinatorial_formula/minimum_bid_three_input_nonlinear_position
    """
    ctx = fx.setup_foreclosure_pending_certificate(
        county_overrides={
            "name": "TX County", "state_code": "TX", "penalty_rate_bps": 500,
            "premium_bidding_enabled": False, "day_count_basis": 365,
        },
        parcel_overrides={"apn": "T-1", "assessed_value_cents": 9_000_000,
                          "base_tax_due_cents": 100_000},
        investor_escrow=400_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
        sub_tax={"tax_year": 2026, "principal_cents": 50_000,
                 "posted_clock": "2026-06-01T00:00:00Z"},
        deed_filing_clock="2027-04-01T00:00:00Z",
        deed_cost_cents=30_000,
    )
    cert, deed = ctx["certificate"], ctx["deed_application"]
    assert_deed_application(deed)
    assert deed["minimum_bid_cents"] == 204682
    assert cert["status"] == "FORECLOSURE_PENDING"


def test_deed_application_cancel_returns_certificate_to_active(api):
    """PRD §3.10: "**Cancelling** it moves the deed application from `FILED` to
    `CANCELLED` and returns the certificate from `FORECLOSURE_PENDING` back to
    `ACTIVE`, reopening the possibility of redemption — this is the revision loop."

    Design: Difficulty/non_linear_state_machine/certificate_foreclosure_revision_loop
    """
    ctx = fx.setup_foreclosure_pending_certificate(
        county_overrides={"name": "Loop County", "state_code": "AZ",
                          "penalty_rate_bps": 0},
        parcel_overrides={"apn": "L-1", "base_tax_due_cents": 100_000},
        investor_escrow=400_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
        sub_tax=None,
        deed_filing_clock="2027-04-01T00:00:00Z",
        deed_cost_cents=30_000,
    )
    county, cert, deed = ctx["county"], ctx["certificate"], ctx["deed_application"]

    cancelled = validate_success(
        api.cancel_deed(county["id"], deed["id"], TREASURER)
    )
    assert cancelled["status"] == "CANCELLED"

    cert_after = validate_success(
        api.get_certificate(county["id"], cert["id"], AUDITOR)
    )
    assert cert_after["status"] == "ACTIVE"


def test_deed_award_branch_drives_certificate_deeded(api):
    """PRD §3.10: "**Awarding** the deed moves the application from `FILED` to
    `AWARDED` and the certificate from `FORECLOSURE_PENDING` to `DEEDED`."
    PRD §3.10: "On award the system creates a surplus distribution, credits the
    holder's escrow with the lien-satisfied amount, moves every `POSTED`
    subsequent tax to `REDEEMED`, sets the parcel's `status` to `DEEDED` and clears
    its `active_certificate_id` to null, and increments both the deed application's
    `version` and the certificate's `version` — a transitive cascade from deed
    application to certificate to parcel and from deed application to surplus
    distribution."

    Design: Difficulty/non_linear_state_machine/deed_application_branch_award_vs_cancel
    """
    ctx = fx.setup_foreclosure_pending_certificate(
        county_overrides={"name": "Branch County", "state_code": "TX",
                          "penalty_rate_bps": 500},
        parcel_overrides={"apn": "BR-1", "assessed_value_cents": 9_000_000,
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

    awarded = validate_success(
        api.award_deed(county["id"], deed["id"], f.award_deed_payload(250_000), TREASURER)
    )
    assert awarded["status"] == "AWARDED"

    cert_after = validate_success(
        api.get_certificate(county["id"], cert["id"], AUDITOR)
    )
    assert cert_after["status"] == "DEEDED"

    parcel_after = validate_success(
        api.get_parcel(county["id"], parcel["id"], AUDITOR)
    )
    assert parcel_after["status"] == "DEEDED"


def test_deed_award_cascade_creates_surplus_and_deeds_parcel(api):
    """PRD §3.11: "The proceeds are allocated as a waterfall: the certificate
    holder's bucket is filled first, so `lien_satisfied_cents` is the smaller of
    the gross proceeds and the frozen `minimum_bid_cents`, and the former owner's
    `surplus_cents` is whatever remains above the floor — the greater of 0 and the
    gross proceeds minus the `minimum_bid_cents`."
    PRD §3.10: "sets the parcel's `status` to `DEEDED` and clears its
    `active_certificate_id` to null"

    Design: Difficulty/transitive_cascade/deed_award_surplus_certificate_parcel
    """
    ctx = fx.setup_foreclosure_pending_certificate(
        county_overrides={"name": "Surplus County", "state_code": "TX",
                          "penalty_rate_bps": 500},
        parcel_overrides={"apn": "SP-1", "assessed_value_cents": 9_000_000,
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

    awarded = validate_success(
        api.award_deed(county["id"], deed["id"], f.award_deed_payload(250_000), TREASURER)
    )
    assert awarded["status"] == "AWARDED"

    cert_after = validate_success(api.get_certificate(county["id"], cert["id"], AUDITOR))
    assert cert_after["status"] == "DEEDED"
    parcel_after = validate_success(api.get_parcel(county["id"], parcel["id"], AUDITOR))
    assert parcel_after["status"] == "DEEDED"

    surplus_list, _meta = api_validate_surplus_by_cert(api, county["id"], cert["id"])
    assert len(surplus_list) == 1
    surplus = surplus_list[0]
    assert_surplus_distribution(surplus)
    assert surplus["surplus_cents"] == 45318
    assert surplus["lien_satisfied_cents"] == 204682


def test_surplus_waterfall_conserves_gross_proceeds(api):
    """PRD §3.11: "Because award is only permitted when the price meets or exceeds
    the floor, the lien-satisfied amount plus the surplus always equal the gross
    proceeds, with the holder made whole before any overage is set aside."
    PRD §3.11: "Its `gross_proceeds_cents` equals the deed application's
    `sale_price_cents`."

    Design: Difficulty/compensating_invariant/surplus_waterfall_conserves_gross_proceeds
    """
    ctx = fx.setup_foreclosure_pending_certificate(
        county_overrides={"name": "Inv County", "state_code": "TX",
                          "penalty_rate_bps": 500},
        parcel_overrides={"apn": "INV-1", "assessed_value_cents": 9_000_000,
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
        api.award_deed(county["id"], deed["id"], f.award_deed_payload(250_000), TREASURER)
    )
    surplus_list, _meta = api_validate_surplus_by_cert(api, county["id"], cert["id"])
    surplus = surplus_list[0]
    assert surplus["gross_proceeds_cents"] == 250000
    assert surplus["lien_satisfied_cents"] == 204682
    assert surplus["surplus_cents"] == 45318
    assert_surplus_conserves_gross(surplus)


def test_claim_surplus_sets_claimed_true(api):
    """PRD §3.11: "A `CountyTreasurer` records the former owner's claim, which
    flips `claimed` to true."

    Design: Corner/endpoints/claim_surplus_sets_claimed
    """
    ctx = fx.setup_foreclosure_pending_certificate(
        county_overrides={"name": "CL County", "state_code": "TX",
                          "penalty_rate_bps": 500},
        parcel_overrides={"apn": "CL-1", "assessed_value_cents": 9_000_000,
                          "base_tax_due_cents": 100_000},
        investor_escrow=400_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
        sub_tax={"tax_year": 2026, "principal_cents": 50_000,
                 "posted_clock": "2026-06-01T00:00:00Z"},
        deed_filing_clock="2027-04-01T00:00:00Z",
        deed_cost_cents=30_000,
    )
    county, deed = ctx["county"], ctx["deed_application"]

    validate_success(
        api.award_deed(county["id"], deed["id"], f.award_deed_payload(250_000), TREASURER)
    )
    surplus_list, _meta = validate_list(
        api.list_surplus_by_deed(county["id"], deed["id"], TREASURER)
    )
    surplus_id = surplus_list[0]["id"]

    claimed = validate_success(
        api.claim_surplus(county["id"], deed["id"], surplus_id, TREASURER)
    )
    assert claimed["claimed"] is True


# --- small local helpers (no envelope-strictness beyond the framework) ------

def api_validate_surplus_by_cert(api, county_id, cert_id):
    return validate_list(api.list_surplus_by_certificate(county_id, cert_id, AUDITOR))


def validate_list(response):
    from test_helpers import validate_paginated
    return validate_paginated(response)
