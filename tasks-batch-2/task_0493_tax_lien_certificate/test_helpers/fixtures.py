"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build every precondition from scratch using
only PRD-declared endpoints. They use get_success_data() (lenient) internally so
that any setup failure surfaces as a clear "Setup failed" error.

Identity threading: the Investor role is entity-backed, so ownership-gated calls
use make_investor_headers(investor["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_investor_headers
from . import factories as f


TREASURER = TEST_USERS["treasurer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# --- Primitive setup steps --------------------------------------------------

def set_clock(instant):
    """Advance/rewind the logical clock; treasurer-only capability."""
    return get_success_data(api_client.set_clock(instant, TREASURER))


def create_county(**county_overrides):
    """Create a county; returns the county dict."""
    payload = f.create_county_payload(**county_overrides)
    return get_success_data(api_client.create_county(payload, TREASURER))


def create_parcel(county_id, **parcel_overrides):
    payload = f.create_parcel_payload(**parcel_overrides)
    return get_success_data(api_client.create_parcel(county_id, payload, TREASURER))


def create_funded_investor(amount_cents, legal_name="Investor", tax_id=None):
    """Register an investor and fund their escrow. Returns the investor dict
    (after the deposit, so escrow_balance_cents reflects the deposit)."""
    if tax_id is None:
        tax_id = f"TIN-{legal_name}-{amount_cents}"
    inv = get_success_data(
        api_client.create_investor(
            f.create_investor_payload(legal_name=legal_name, tax_id=tax_id), TREASURER
        )
    )
    headers = make_investor_headers(inv["id"])
    funded = get_success_data(
        api_client.create_deposit(
            inv["id"], f.create_deposit_payload(amount_cents), headers
        )
    )
    return funded


def create_sale(county_id, scheduled_at="2026-03-01T00:00:00Z", sale_name="Sale"):
    payload = f.create_sale_payload(sale_name=sale_name, scheduled_at=scheduled_at)
    return get_success_data(api_client.create_sale(county_id, payload, TREASURER))


def create_listing(county_id, sale_id, parcel_id):
    return get_success_data(
        api_client.create_listing(
            county_id, sale_id, f.create_listing_payload(parcel_id), TREASURER
        )
    )


# --- Tier 2/3: build an OPEN sale with a single listing ready for bids ------

def setup_open_sale_with_listing(county_overrides=None, parcel_overrides=None,
                                 scheduled_at="2026-03-01T00:00:00Z",
                                 issue_clock="2026-03-01T00:00:00Z"):
    """County + parcel + DRAFT sale + LISTED listing + OPEN sale.

    Returns dict with county, parcel, sale, listing (freshly re-read so its
    version reflects the listing creation). Clock is set to issue_clock first.
    """
    county_overrides = county_overrides or {}
    parcel_overrides = parcel_overrides or {}
    set_clock(issue_clock)
    county = create_county(**county_overrides)
    parcel = create_parcel(county["id"], **parcel_overrides)
    sale = create_sale(county["id"], scheduled_at=scheduled_at)
    listing = create_listing(county["id"], sale["id"], parcel["id"])
    get_success_data(api_client.open_sale(county["id"], sale["id"], TREASURER))
    # Re-read the listing so the caller has its current version for bids.
    listing = get_success_data(
        api_client.get_listing(county["id"], sale["id"], listing["id"], AUDITOR)
    )
    return {
        "county": county,
        "parcel": parcel,
        "sale": sale,
        "listing": listing,
    }


def place_rate_bid(county_id, sale_id, listing_id, investor_id, rate_bps,
                   expected_listing_version):
    headers = make_investor_headers(investor_id)
    payload = f.create_bid_payload(
        investor_id, expected_listing_version, rate_bps=rate_bps
    )
    return get_success_data(
        api_client.create_bid(county_id, sale_id, listing_id, payload, headers)
    )


def place_premium_bid(county_id, sale_id, listing_id, investor_id, premium_cents,
                      expected_listing_version):
    headers = make_investor_headers(investor_id)
    payload = f.create_bid_payload(
        investor_id, expected_listing_version, premium_cents=premium_cents
    )
    return get_success_data(
        api_client.create_bid(county_id, sale_id, listing_id, payload, headers)
    )


def get_certificate_for_parcel(county_id, parcel_id):
    """Read back the certificate issued for a parcel after a sale close."""
    data, _meta = _list(
        api_client.list_certificates(county_id, AUDITOR, {"parcel_id": parcel_id})
    )
    assert data, f"No certificate found for parcel {parcel_id} (setup failed)"
    return data[0]


def _list(response):
    """Return (data_list, meta) from a list response without strict envelope
    checks — used only in setup."""
    body = response.json()
    return body["data"], body["meta"]


# --- Tier 3: issue a certificate via the award cascade ----------------------

def setup_active_certificate(county_overrides=None, parcel_overrides=None,
                             investor_escrow=300_000, winning_rate_bps=1200,
                             issue_clock="2026-03-01T00:00:00Z"):
    """Full path to an ACTIVE certificate held by a single winning investor.

    Returns dict with county, parcel, investor, sale, listing, certificate.
    The certificate is issued at issue_clock with rate winning_rate_bps.
    """
    ctx = setup_open_sale_with_listing(
        county_overrides=county_overrides,
        parcel_overrides=parcel_overrides,
        issue_clock=issue_clock,
    )
    county, parcel, sale, listing = (
        ctx["county"], ctx["parcel"], ctx["sale"], ctx["listing"]
    )
    investor = create_funded_investor(investor_escrow, legal_name="Holder",
                                      tax_id=f"TIN-HOLD-{parcel['id'][:8]}")
    place_rate_bid(county["id"], sale["id"], listing["id"], investor["id"],
                   winning_rate_bps, listing["version"])
    get_success_data(api_client.close_sale(county["id"], sale["id"], TREASURER))
    cert = get_certificate_for_parcel(county["id"], parcel["id"])
    return {
        "county": county,
        "parcel": parcel,
        "investor": investor,
        "sale": sale,
        "listing": listing,
        "certificate": cert,
    }


def add_sub_tax(county_id, certificate_id, investor_id, tax_year, principal_cents):
    """Re-read the certificate for its current version, then post a sub-tax.
    Returns the created SubsequentTax dict."""
    headers = make_investor_headers(investor_id)
    cert = get_success_data(
        api_client.get_certificate(county_id, certificate_id, headers)
    )
    payload = f.create_sub_tax_payload(
        investor_id, tax_year, principal_cents, cert["version"]
    )
    return get_success_data(
        api_client.create_sub_tax(county_id, certificate_id, payload, headers)
    )


def get_certificate_version(county_id, certificate_id, investor_id):
    headers = make_investor_headers(investor_id)
    cert = get_success_data(
        api_client.get_certificate(county_id, certificate_id, headers)
    )
    return cert["version"]


# --- Tier 5: drive a certificate into FORECLOSURE_PENDING -------------------

def setup_foreclosure_pending_certificate(
    county_overrides=None, parcel_overrides=None,
    investor_escrow=400_000, winning_rate_bps=1200,
    issue_clock="2026-03-01T00:00:00Z",
    sub_tax=None,
    deed_filing_clock="2027-04-01T00:00:00Z",
    deed_cost_cents=30_000,
):
    """ACTIVE certificate -> (optional sub-tax) -> deed application FILED,
    certificate FORECLOSURE_PENDING.

    sub_tax (optional): dict like {"tax_year": 2026, "principal_cents": 50000,
    "posted_clock": "2026-06-01T00:00:00Z"}.

    Returns dict with county, parcel, investor, certificate, deed_application.
    """
    ctx = setup_active_certificate(
        county_overrides=county_overrides,
        parcel_overrides=parcel_overrides,
        investor_escrow=investor_escrow,
        winning_rate_bps=winning_rate_bps,
        issue_clock=issue_clock,
    )
    county, parcel, investor, cert = (
        ctx["county"], ctx["parcel"], ctx["investor"], ctx["certificate"]
    )
    if sub_tax is not None:
        set_clock(sub_tax["posted_clock"])
        add_sub_tax(county["id"], cert["id"], investor["id"],
                    sub_tax["tax_year"], sub_tax["principal_cents"])
    set_clock(deed_filing_clock)
    headers = make_investor_headers(investor["id"])
    deed = get_success_data(
        api_client.create_deed_application(
            county["id"], cert["id"],
            f.create_deed_application_payload(investor["id"], deed_cost_cents),
            headers,
        )
    )
    cert = get_success_data(
        api_client.get_certificate(county["id"], cert["id"], headers)
    )
    return {
        "county": county,
        "parcel": parcel,
        "investor": investor,
        "certificate": cert,
        "deed_application": deed,
    }
