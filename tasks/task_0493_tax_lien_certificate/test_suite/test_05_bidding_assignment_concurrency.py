"""Bid-shape validation, escrow sufficiency, certificate assignment, the
optimistic-concurrency (stale-version) checks, computed sub-tax totals, and the
deed-below-minimum floor.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_investor_headers,
    assert_assignment,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f

TREASURER = TEST_USERS["treasurer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_bid_rate_not_multiple_of_increment_rejected(api):
    """PRD §3.4: "the submitted `rate_bps` must be at most the listing's
    `opening_rate_bps` and must be a positive multiple of the county's
    `bid_down_increment_bps`; a `rate_bps` that exceeds the opening rate or is not
    such a multiple is rejected with `ERR_INVALID_BID`"

    Design: Corner/validations/bid_rate_not_multiple_of_increment
    """
    ctx = fx.setup_open_sale_with_listing(
        county_overrides={"name": "BR County", "bid_down_increment_bps": 100},
        parcel_overrides={"apn": "BR-1", "base_tax_due_cents": 100_000},
    )
    county, sale, listing = ctx["county"], ctx["sale"], ctx["listing"]
    investor = fx.create_funded_investor(200_000, legal_name="I1", tax_id="TIN-BR1")

    resp = api.create_bid(
        county["id"], sale["id"], listing["id"],
        f.create_bid_payload(investor["id"], listing["version"], rate_bps=1250),
        make_investor_headers(investor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_BID.value)


def test_bid_rate_above_opening_rejected(api):
    """PRD §3.4: "the submitted `rate_bps` must be at most the listing's
    `opening_rate_bps` and must be a positive multiple of the county's
    `bid_down_increment_bps`; a `rate_bps` that exceeds the opening rate or is not
    such a multiple is rejected with `ERR_INVALID_BID`"

    Design: Corner/validations/bid_rate_above_opening_invalid
    """
    ctx = fx.setup_open_sale_with_listing(
        county_overrides={"name": "BA County", "max_interest_rate_bps": 1600},
        parcel_overrides={"apn": "BA-1", "base_tax_due_cents": 100_000},
    )
    county, sale, listing = ctx["county"], ctx["sale"], ctx["listing"]
    investor = fx.create_funded_investor(200_000, legal_name="I1", tax_id="TIN-BA1")

    resp = api.create_bid(
        county["id"], sale["id"], listing["id"],
        f.create_bid_payload(investor["id"], listing["version"], rate_bps=1700),
        make_investor_headers(investor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_BID.value)


def test_bid_insufficient_escrow_rejected(api):
    """PRD §3.4: "If the hold would push the bidder's `escrow_balance_cents` below
    zero, the bid is rejected with `ERR_INSUFFICIENT_ESCROW`."

    Design: Corner/validations/insufficient_escrow_on_bid
    """
    ctx = fx.setup_open_sale_with_listing(
        county_overrides={"name": "IE County"},
        parcel_overrides={"apn": "IE-1", "base_tax_due_cents": 100_000},
    )
    county, sale, listing = ctx["county"], ctx["sale"], ctx["listing"]
    investor = fx.create_funded_investor(50_000, legal_name="I1", tax_id="TIN-IE1")

    resp = api.create_bid(
        county["id"], sale["id"], listing["id"],
        f.create_bid_payload(investor["id"], listing["version"], rate_bps=1200),
        make_investor_headers(investor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ESCROW.value)


def test_deed_award_below_minimum_rejected(api):
    """PRD §3.10: "The award names the `sale_price_cents` — the hammer price
    realized at the deed sale — which must be at least the frozen
    `minimum_bid_cents`; a price below the floor is rejected with
    `ERR_BID_BELOW_MINIMUM`."

    Design: Corner/validations/deed_award_below_minimum_rejected
    """
    ctx = fx.setup_foreclosure_pending_certificate(
        county_overrides={"name": "BM County", "state_code": "TX",
                          "penalty_rate_bps": 500},
        parcel_overrides={"apn": "BM-1", "assessed_value_cents": 9_000_000,
                          "base_tax_due_cents": 100_000},
        investor_escrow=400_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
        sub_tax={"tax_year": 2026, "principal_cents": 50_000,
                 "posted_clock": "2026-06-01T00:00:00Z"},
        deed_filing_clock="2027-04-01T00:00:00Z",
        deed_cost_cents=30_000,
    )
    county, cert, deed = ctx["county"], ctx["certificate"], ctx["deed_application"]

    resp = api.award_deed(county["id"], deed["id"], f.award_deed_payload(100_000), TREASURER)
    validate_error(resp, ApiErrorId.ERR_BID_BELOW_MINIMUM.value)

    cert_after = validate_success(api.get_certificate(county["id"], cert["id"], AUDITOR))
    assert cert_after["status"] == "FORECLOSURE_PENDING"


def test_assignment_transfers_holder_and_assigns_seq(api):
    """PRD §3.8: "A recorded assignment receives the next `seq` (a 1-based position
    in the certificate's transfer chain), enters the terminal `RECORDED` status,
    repoints the certificate's `holder_investor_id` to the assignee, increments the
    certificate's `assignment_seq`, and increments the certificate's `version` by
    one."

    Design: Corner/state_machines/assignment_transfers_holder_and_seq
    """
    ctx = fx.setup_active_certificate(
        county_overrides={"name": "AS County"},
        parcel_overrides={"apn": "AS-1", "base_tax_due_cents": 100_000},
        investor_escrow=200_000, winning_rate_bps=1200,
    )
    county, cert, i1 = ctx["county"], ctx["certificate"], ctx["investor"]
    i2 = fx.create_funded_investor(100_000, legal_name="I2", tax_id="TIN-AS2")

    cert_v = validate_success(
        api.get_certificate(county["id"], cert["id"], make_investor_headers(i1["id"]))
    )["version"]
    assignment = validate_success(
        api.create_assignment(
            county["id"], cert["id"],
            f.create_assignment_payload(i1["id"], i2["id"], 50_000, cert_v),
            make_investor_headers(i1["id"]),
        ),
        expected_status=201,
    )
    assert_assignment(assignment)
    assert assignment["seq"] == 1
    assert assignment["status"] == "RECORDED"

    cert_after = validate_success(api.get_certificate(county["id"], cert["id"], AUDITOR))
    assert cert_after["holder_investor_id"] == i2["id"]
    assert cert_after["assignment_seq"] == 1


def test_assignment_to_equals_from_rejected(api):
    """PRD §3.8: "the assignee must differ from the assignor — an assignment whose
    `to_investor_id` equals its `from_investor_id` is rejected with
    `ERR_DUPLICATE_SUB_TAX`."

    Design: Corner/validations/assignment_to_equals_from_rejected
    """
    ctx = fx.setup_active_certificate(
        county_overrides={"name": "AE County"},
        parcel_overrides={"apn": "AE-1", "base_tax_due_cents": 100_000},
        investor_escrow=200_000, winning_rate_bps=1200,
    )
    county, cert, i1 = ctx["county"], ctx["certificate"], ctx["investor"]

    cert_v = validate_success(
        api.get_certificate(county["id"], cert["id"], make_investor_headers(i1["id"]))
    )["version"]
    resp = api.create_assignment(
        county["id"], cert["id"],
        f.create_assignment_payload(i1["id"], i1["id"], 0, cert_v),
        make_investor_headers(i1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SUB_TAX.value)

    cert_after = validate_success(api.get_certificate(county["id"], cert["id"], AUDITOR))
    assert cert_after["holder_investor_id"] == i1["id"]


def test_stale_listing_version_bid_rejected(api):
    """PRD §2.7: "If a withdrawal (or any other mutation) has advanced the
    listing's `version` since the client last read it, the placement is rejected
    with `ERR_STALE_VERSION` at HTTP status 412, forcing the investor to re-read
    the listing's current status before committing escrow."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_listing_version_on_bid
    """
    ctx = fx.setup_open_sale_with_listing(
        county_overrides={"name": "OCC County"},
        parcel_overrides={"apn": "OCC-1", "base_tax_due_cents": 100_000},
    )
    county, sale, listing = ctx["county"], ctx["sale"], ctx["listing"]
    investor = fx.create_funded_investor(300_000, legal_name="I1", tax_id="TIN-OCC1")
    stale_version = listing["version"]

    # First bid succeeds and bumps the listing version.
    fx.place_rate_bid(county["id"], sale["id"], listing["id"], investor["id"],
                      1200, stale_version)

    # Second bid carries the now-stale version -> ERR_STALE_VERSION.
    resp = api.create_bid(
        county["id"], sale["id"], listing["id"],
        f.create_bid_payload(investor["id"], stale_version, rate_bps=1100),
        make_investor_headers(investor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_stale_certificate_version_assignment_rejected(api):
    """PRD §2.7: "When recording an assignment on a certificate, the request body
    must likewise carry `expected_certificate_version` equal to the certificate's
    current `version`; if a prior assignment (or other mutation) has already
    advanced the `version`, the record is rejected with `ERR_STALE_VERSION` (HTTP
    412), keeping the transfer chain single-threaded and ordered so that a second
    assignment cannot be recorded against a view in which `from_investor_id` was
    still the holder."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_certificate_version_on_assignment
    """
    ctx = fx.setup_active_certificate(
        county_overrides={"name": "OCC2 County"},
        parcel_overrides={"apn": "OCC2-1", "base_tax_due_cents": 100_000},
        investor_escrow=200_000, winning_rate_bps=1200,
    )
    county, cert, i1 = ctx["county"], ctx["certificate"], ctx["investor"]
    i2 = _register_only("I2", "TIN-OCC2-2")
    i3 = _register_only("I3", "TIN-OCC2-3")

    cert_v0 = validate_success(
        api.get_certificate(county["id"], cert["id"], make_investor_headers(i1["id"]))
    )["version"]

    # First assignment I1 -> I2 succeeds and bumps the certificate version.
    validate_success(
        api.create_assignment(
            county["id"], cert["id"],
            f.create_assignment_payload(i1["id"], i2["id"], 0, cert_v0),
            make_investor_headers(i1["id"]),
        ),
        expected_status=201,
    )

    # Second assignment reuses the stale pre-transfer version -> ERR_STALE_VERSION.
    resp = api.create_assignment(
        county["id"], cert["id"],
        f.create_assignment_payload(i2["id"], i3["id"], 0, cert_v0),
        make_investor_headers(i2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_certificate_sub_tax_total_recomputed(api):
    """PRD §3.6: "A certificate tracks `sub_tax_total_cents` — the running sum of
    principal across its posted subsequent taxes"
    PRD §3.7: "A successful payment is `POSTED`, stamps `posted_at` with the
    current logical-clock instant (the point from which that sub-tax's interest
    accrues at the county's `sub_tax_interest_rate_bps`), debits the holder's
    escrow by the principal, recomputes the certificate's `sub_tax_total_cents`,
    and increments the certificate's `version` by one."

    Design: Corner/entities/certificate_sub_tax_total_computed
    """
    ctx = fx.setup_active_certificate(
        county_overrides={"name": "CF County"},
        parcel_overrides={"apn": "CF-1", "base_tax_due_cents": 100_000},
        investor_escrow=300_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
    )
    county, cert, investor = ctx["county"], ctx["certificate"], ctx["investor"]

    fx.add_sub_tax(county["id"], cert["id"], investor["id"], 2026, 40_000)

    cert_after = validate_success(api.get_certificate(county["id"], cert["id"], AUDITOR))
    assert cert_after["sub_tax_total_cents"] == 40000


def _register_only(legal_name, tax_id):
    """Register an investor with no deposit (escrow stays 0). Returns the dict."""
    from test_helpers import get_success_data
    from test_helpers import api_client
    return get_success_data(
        api_client.create_investor(
            f.create_investor_payload(legal_name=legal_name, tax_id=tax_id), TREASURER
        )
    )
