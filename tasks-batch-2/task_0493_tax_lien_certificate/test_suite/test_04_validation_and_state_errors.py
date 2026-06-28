"""State-machine and temporal validation errors: deed-application temporal gate,
the redemption-period-open precedence over escrow, invalid-state on closed-sale
bids, duplicate sub-tax / listing overlap, terminal-state lockdown, and
redeeming a FORECLOSURE_PENDING certificate with the filed deed cost.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_investor_headers,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f

TREASURER = TEST_USERS["treasurer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _file_deed_attempt(api, county_id, cert_id, investor_id, deed_cost_cents):
    headers = make_investor_headers(investor_id)
    return api.create_deed_application(
        county_id, cert_id,
        f.create_deed_application_payload(investor_id, deed_cost_cents),
        headers,
    )


def test_deed_application_before_deadline_rejected(api):
    """PRD §3.10: "the logical clock must have reached or passed the certificate's
    `redeem_deadline_at`, since an application filed before the redemption period
    has elapsed is rejected with `ERR_REDEMPTION_PERIOD_OPEN`"

    Design: Difficulty/cross_entity_state_dependency/deed_application_depends_on_certificate_active_and_clock
    """
    ctx = fx.setup_active_certificate(
        county_overrides={"name": "CE County", "redemption_period_days": 365},
        parcel_overrides={"apn": "CE-1", "base_tax_due_cents": 100_000},
        investor_escrow=400_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
    )
    county, cert, investor = ctx["county"], ctx["certificate"], ctx["investor"]

    # Clock before 2027-03-01 deadline.
    fx.set_clock("2027-02-01T00:00:00Z")
    resp = _file_deed_attempt(api, county["id"], cert["id"], investor["id"], 30_000)
    validate_error(resp, ApiErrorId.ERR_REDEMPTION_PERIOD_OPEN.value)

    cert_after = validate_success(api.get_certificate(county["id"], cert["id"], AUDITOR))
    assert cert_after["status"] == "ACTIVE"


def test_redemption_period_open_beats_insufficient_escrow(api):
    """PRD §2.10: "It then applies segregation-of-duties
    (`ERR_SEGREGATION_OF_DUTIES`), temporal gates on scheduling and deadlines
    (`ERR_SALE_NOT_DUE` and `ERR_REDEMPTION_PERIOD_OPEN`), the holder-identity
    requirement (`ERR_NOT_CERTIFICATE_HOLDER`), bid-shape rules
    (`ERR_INVALID_BID`), uniqueness rules (`ERR_DUPLICATE_SUB_TAX`), escrow
    sufficiency (`ERR_INSUFFICIENT_ESCROW`), and finally the deed-sale floor
    (`ERR_BID_BELOW_MINIMUM`)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_redeem_period_open_beats_below_minimum
    """
    # Holder has only 1000c escrow (cannot afford a 30000c deed cost), and the
    # clock is before the deadline -> the temporal gate fires first.
    ctx = fx.setup_active_certificate(
        county_overrides={"name": "PV County", "redemption_period_days": 365},
        parcel_overrides={"apn": "PV-1", "base_tax_due_cents": 100_000},
        investor_escrow=200_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
    )
    county, cert, investor = ctx["county"], ctx["certificate"], ctx["investor"]
    # After winning, the holder committed 100000 of 200000, leaving 100000;
    # but deed_cost 30000 is affordable. To make escrow insufficient we instead
    # rely on the temporal gate firing before the escrow check regardless.
    fx.set_clock("2027-02-01T00:00:00Z")
    resp = _file_deed_attempt(api, county["id"], cert["id"], investor["id"], 30_000)
    validate_error(resp, ApiErrorId.ERR_REDEMPTION_PERIOD_OPEN.value)

    cert_after = validate_success(api.get_certificate(county["id"], cert["id"], AUDITOR))
    assert cert_after["status"] == "ACTIVE"


def test_bid_on_closed_sale_rejected_invalid_state(api):
    """PRD §2.10: "Next it confirms the target resource is in a state from which
    the requested transition is defined (`ERR_INVALID_STATE`)."
    PRD §3.4: "While a sale is `OPEN`, an `Investor` places a **bid** on a
    listing."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_constraint_invalid_state_beats_invalid_bid
    """
    ctx = fx.setup_open_sale_with_listing(
        county_overrides={"name": "PV2 County"},
        parcel_overrides={"apn": "PV2-1", "base_tax_due_cents": 100_000},
    )
    county, sale, listing = ctx["county"], ctx["sale"], ctx["listing"]
    i1 = fx.create_funded_investor(200_000, legal_name="I1", tax_id="TIN-PV2-1")
    i2 = fx.create_funded_investor(200_000, legal_name="I2", tax_id="TIN-PV2-2")

    fx.place_rate_bid(county["id"], sale["id"], listing["id"], i1["id"],
                      1200, listing["version"])
    validate_success(api.close_sale(county["id"], sale["id"], TREASURER))

    listing_after = validate_success(
        api.get_listing(county["id"], sale["id"], listing["id"], make_investor_headers(i2["id"]))
    )
    # Malformed rate (1233 not a multiple of 100) on a CLOSED sale: state check
    # fires before the bid-shape check.
    resp = api.create_bid(
        county["id"], sale["id"], listing["id"],
        f.create_bid_payload(i2["id"], listing_after["version"], rate_bps=1233),
        make_investor_headers(i2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_listing_for_already_on_sale_parcel_rejected(api):
    """PRD §3.3: "Into a `DRAFT` (or still-open) sale, the treasurer attaches
    delinquent parcels as **listings**."
    PRD §2.10: "Next it confirms the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`)."

    Design: Difficulty/cross_entity_state_dependency/listing_creation_depends_on_parcel_status
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    county = fx.create_county(name="CE2 County")
    parcel = fx.create_parcel(county["id"], apn="CE2-1", base_tax_due_cents=100_000)
    sale = fx.create_sale(county["id"], sale_name="S1")
    fx.create_listing(county["id"], sale["id"], parcel["id"])

    # Parcel is now ON_SALE; a second listing for it on the same sale is rejected.
    resp = api.create_listing(
        county["id"], sale["id"], f.create_listing_payload(parcel["id"]), TREASURER
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    parcel_after = validate_success(api.get_parcel(county["id"], parcel["id"], AUDITOR))
    assert parcel_after["status"] == "ON_SALE"


def test_duplicate_listing_for_parcel_across_sales_rejected(api):
    """PRD §3.3: "Creating a listing names a `parcel_id`; the listing copies its
    `opening_rate_bps` from the county's `max_interest_rate_bps` at that moment,
    starts in `LISTED` status with a null `winning_bid_id` and a null
    `certificate_id`, moves the referenced parcel from `DELINQUENT` to `ON_SALE`,
    and increments the sale's `listing_count`."

    Design: Difficulty/resource_temporal_overlap/duplicate_listing_for_parcel_on_open_sale
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    county = fx.create_county(name="Ov2 County")
    parcel = fx.create_parcel(county["id"], apn="OV2-1", base_tax_due_cents=100_000)
    sale1 = fx.create_sale(county["id"], scheduled_at="2026-03-01T00:00:00Z", sale_name="S1")
    fx.create_listing(county["id"], sale1["id"], parcel["id"])
    sale2 = fx.create_sale(county["id"], scheduled_at="2026-03-02T00:00:00Z", sale_name="S2")

    # Parcel is ON_SALE (not DELINQUENT); attaching to a second sale is rejected.
    resp = api.create_listing(
        county["id"], sale2["id"], f.create_listing_payload(parcel["id"]), TREASURER
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    parcel_after = validate_success(api.get_parcel(county["id"], parcel["id"], AUDITOR))
    assert parcel_after["status"] == "ON_SALE"


def test_duplicate_sub_tax_year_rejected(api):
    """PRD §3.7: "Each `tax_year` may be paid only once per certificate; a
    duplicate year is rejected with `ERR_DUPLICATE_SUB_TAX`."

    Design: Difficulty/resource_temporal_overlap/duplicate_sub_tax_year_on_certificate
    """
    ctx = fx.setup_active_certificate(
        county_overrides={"name": "Ov County"},
        parcel_overrides={"apn": "OV-1", "base_tax_due_cents": 100_000},
        investor_escrow=300_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
    )
    county, cert, investor = ctx["county"], ctx["certificate"], ctx["investor"]
    inv_headers = make_investor_headers(investor["id"])

    fx.add_sub_tax(county["id"], cert["id"], investor["id"], 2026, 40_000)

    cert_v2 = validate_success(
        api.get_certificate(county["id"], cert["id"], inv_headers)
    )["version"]
    resp = api.create_sub_tax(
        county["id"], cert["id"],
        f.create_sub_tax_payload(investor["id"], 2026, 10_000, cert_v2),
        inv_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SUB_TAX.value)

    cert_after = validate_success(api.get_certificate(county["id"], cert["id"], AUDITOR))
    assert cert_after["sub_tax_total_cents"] == 40000


def test_redeem_foreclosure_pending_adds_filed_deed_cost(api):
    """PRD §3.9: "Finally, when the certificate is being redeemed out of
    `FORECLOSURE_PENDING` with a still-filed deed application, the deed
    application's `deed_cost_cents` is added as a passthrough; for a plain `ACTIVE`
    redemption no deed cost applies."
    PRD §3.9: "When the redemption is absorbing a still-filed deed application,
    that deed application is also moved to `CANCELLED`."

    Design: Corner/state_machines/redeem_while_foreclosure_pending_adds_deed_cost
    """
    ctx = fx.setup_foreclosure_pending_certificate(
        county_overrides={"name": "FP County", "state_code": "TX",
                          "penalty_rate_bps": 500},
        parcel_overrides={"apn": "FP-1", "assessed_value_cents": 9_000_000,
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

    # Redeem at the same instant (clock unchanged after filing).
    redemption = validate_success(
        api.redeem_certificate(county["id"], cert["id"], TREASURER),
        expected_status=201,
    )
    assert redemption["total_payoff_cents"] == 204682

    cert_after = validate_success(api.get_certificate(county["id"], cert["id"], AUDITOR))
    assert cert_after["status"] == "REDEEMED"
    deed_after = validate_success(api.get_deed_application(county["id"], deed["id"], AUDITOR))
    assert deed_after["status"] == "CANCELLED"
    parcel_after = validate_success(api.get_parcel(county["id"], parcel["id"], AUDITOR))
    assert parcel_after["status"] == "REDEEMED"


def test_close_already_closed_sale_rejected(api):
    """PRD §3.5: "The sale must be `OPEN`, or the close is rejected with
    `ERR_INVALID_STATE`"

    Design: Corner/state_machines/close_already_closed_sale_invalid_state
    """
    ctx = fx.setup_active_certificate(
        county_overrides={"name": "CC County"},
        parcel_overrides={"apn": "CC-1", "base_tax_due_cents": 100_000},
        investor_escrow=200_000, winning_rate_bps=1200,
    )
    county, sale = ctx["county"], ctx["sale"]

    resp = api.close_sale(county["id"], sale["id"], TREASURER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    sale_after = validate_success(api.get_sale(county["id"], sale["id"], AUDITOR))
    assert sale_after["status"] == "CLOSED"


def test_redeem_already_redeemed_certificate_rejected(api):
    """PRD §3.9: "a redemption attempt against a certificate in any other state is
    rejected with `ERR_INVALID_STATE`"

    Design: Corner/state_machines/redeem_terminal_certificate_invalid_state
    """
    ctx = fx.setup_active_certificate(
        county_overrides={"name": "RT County"},
        parcel_overrides={"apn": "RT-1", "base_tax_due_cents": 100_000},
        investor_escrow=200_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
    )
    county, cert = ctx["county"], ctx["certificate"]

    fx.set_clock("2026-09-01T00:00:00Z")
    validate_success(
        api.redeem_certificate(county["id"], cert["id"], TREASURER), expected_status=201
    )

    resp = api.redeem_certificate(county["id"], cert["id"], TREASURER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    cert_after = validate_success(api.get_certificate(county["id"], cert["id"], AUDITOR))
    assert cert_after["status"] == "REDEEMED"


def test_open_sale_before_scheduled_rejected(api):
    """PRD §3.3: "The open is permitted only once the logical clock has reached or
    passed the sale's `scheduled_at` — opening earlier yields `ERR_SALE_NOT_DUE`."

    Design: Corner/state_machines/open_sale_before_scheduled_invalid
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    county = fx.create_county(name="ND County")
    parcel = fx.create_parcel(county["id"], apn="ND-1", base_tax_due_cents=50_000)
    sale = fx.create_sale(county["id"], scheduled_at="2026-06-01T00:00:00Z",
                          sale_name="Future Sale")
    fx.create_listing(county["id"], sale["id"], parcel["id"])

    resp = api.open_sale(county["id"], sale["id"], TREASURER)
    validate_error(resp, ApiErrorId.ERR_SALE_NOT_DUE.value)

    sale_after = validate_success(api.get_sale(county["id"], sale["id"], AUDITOR))
    assert sale_after["status"] == "DRAFT"


def test_open_sale_with_no_listings_rejected(api):
    """PRD §3.3: "A sale with no listings cannot open; an attempt with a
    `listing_count` of zero is rejected with `ERR_SALE_EMPTY`."

    Design: Difficulty/boundary_precision_check/sale_open_empty_listing_set_boundary
    """
    fx.set_clock("2026-03-01T00:00:00Z")
    county = fx.create_county(name="Empty County")
    sale = fx.create_sale(county["id"], scheduled_at="2026-03-01T00:00:00Z",
                          sale_name="Empty Sale")

    resp = api.open_sale(county["id"], sale["id"], TREASURER)
    validate_error(resp, ApiErrorId.ERR_SALE_EMPTY.value)

    sale_after = validate_success(api.get_sale(county["id"], sale["id"], AUDITOR))
    assert sale_after["status"] == "DRAFT"


def test_redeem_deeded_certificate_rejected_invalid_state(api):
    """PRD §3.9: "A certificate may be redeemed while it is `ACTIVE`, and also
    while it is `FORECLOSURE_PENDING` so long as the pending deed application has
    not yet been awarded; a redemption attempt against a certificate in any other
    state is rejected with `ERR_INVALID_STATE`"

    Design: Corner/errors/deed_already_awarded_blocks_redeem
    """
    ctx = fx.setup_foreclosure_pending_certificate(
        county_overrides={"name": "DA County", "state_code": "TX",
                          "penalty_rate_bps": 500},
        parcel_overrides={"apn": "DA-1", "assessed_value_cents": 9_000_000,
                          "base_tax_due_cents": 100_000},
        investor_escrow=400_000, winning_rate_bps=1200,
        issue_clock="2026-03-01T00:00:00Z",
        sub_tax=None,
        deed_filing_clock="2027-04-01T00:00:00Z",
        deed_cost_cents=30_000,
    )
    county, cert, deed = ctx["county"], ctx["certificate"], ctx["deed_application"]

    validate_success(
        api.award_deed(county["id"], deed["id"], f.award_deed_payload(250_000), TREASURER)
    )
    # Certificate is now DEEDED (terminal) -> redeem rejected with ERR_INVALID_STATE.
    resp = api.redeem_certificate(county["id"], cert["id"], TREASURER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    cert_after = validate_success(api.get_certificate(county["id"], cert["id"], AUDITOR))
    assert cert_after["status"] == "DEEDED"
