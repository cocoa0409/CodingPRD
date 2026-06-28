"""Composite setup helpers for the Equity Crowdfunding (Reg CF) Portal.

Every fixture builds its preconditions from scratch via PRD-declared endpoints, using
get_success_data() (lenient) so setup failures surface as clear "Setup failed" errors.

Identity threading: entity_backed roles (Issuer, Investor) thread the real entity id into
make_issuer_headers / make_investor_headers for ownership-gated calls.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_issuer_payload,
    create_investor_payload,
    create_accreditation_request_payload,
    create_offering_payload,
    create_investment_payload,
    create_investor_update_payload,
)
from .test_users import (
    make_issuer_headers,
    make_investor_headers,
    make_compliance_officer_headers,
    make_anonymous_headers,
    COMPLIANCE_OFFICER_USER_ID,
)

CO = make_compliance_officer_headers()
ANON = make_anonymous_headers()


# --- Tier 0: logical clock ---

def set_clock(to_iso8601: str):
    """Advance the server logical clock (PRD §2.9). ComplianceOfficer-only."""
    return get_success_data(api_client.set_clock(to_iso8601, headers=CO))


# --- Tier 1: state progression (single entities) ---

def create_issuer(**overrides) -> dict:
    """Create an issuer in ONBOARDING. Returns the issuer dict."""
    return get_success_data(api_client.create_issuer(create_issuer_payload(**overrides), headers=ANON))


def create_verified_issuer(**overrides) -> dict:
    """Create an issuer and verify it (ONBOARDING -> VERIFIED). Returns the verified issuer dict."""
    issuer = create_issuer(**overrides)
    get_success_data(api_client.verify_issuer(issuer["id"], headers=CO))
    # Re-read to reflect VERIFIED status / bumped version.
    return get_success_data(api_client.get_issuer(issuer["id"], headers=CO))


def create_investor(**overrides) -> dict:
    """Register an investor (UNACCREDITED). Returns the investor dict."""
    return get_success_data(api_client.create_investor(create_investor_payload(**overrides), headers=ANON))


def create_accredited_investor(**overrides) -> dict:
    """Register an investor and approve an accreditation request -> ACCREDITED.
    Returns the investor dict (re-read so accreditation_status==ACCREDITED)."""
    investor = create_investor(**overrides)
    inv_headers = make_investor_headers(investor["id"])
    req = get_success_data(api_client.create_accreditation_request(
        create_accreditation_request_payload(investor["id"]), headers=inv_headers))
    get_success_data(api_client.approve_accreditation_request(req["id"], headers=CO))
    return get_success_data(api_client.get_investor(investor["id"], headers=CO))


# --- Tier 2: offering lifecycle helpers ---

def create_draft_offering(issuer_id, **overrides) -> dict:
    """Create a DRAFT offering for a (presumably verified) issuer. Returns the offering dict."""
    issuer_headers = make_issuer_headers(issuer_id)
    return get_success_data(api_client.create_offering(
        create_offering_payload(issuer_id, **overrides), headers=issuer_headers))


def create_qualified_offering(issuer_id, **overrides) -> dict:
    """Create a DRAFT offering, submit + qualify its Form C (form_c_status==QUALIFIED, still DRAFT).
    Returns the offering dict (re-read)."""
    offering = create_draft_offering(issuer_id, **overrides)
    issuer_headers = make_issuer_headers(issuer_id)
    get_success_data(api_client.submit_form_c(offering["id"], headers=issuer_headers))
    get_success_data(api_client.qualify_form_c(offering["id"], headers=CO))
    return get_success_data(api_client.get_offering(offering["id"], headers=issuer_headers))


def create_live_offering(issuer_id, **overrides) -> dict:
    """Create a DRAFT offering, qualify Form C, and take it LIVE. Returns the LIVE offering dict
    (re-read so version/live_at reflect go-live)."""
    offering = create_qualified_offering(issuer_id, **overrides)
    issuer_headers = make_issuer_headers(issuer_id)
    get_success_data(api_client.go_live(offering["id"], headers=issuer_headers))
    return get_success_data(api_client.get_offering(offering["id"], headers=issuer_headers))


# --- Tier 3: full scenario shortcuts ---

def setup_verified_issuer_and_accredited_investor(clock="2026-06-01T00:00:00Z",
                                                   issuer_overrides=None,
                                                   investor_overrides=None):
    """Set clock, create a verified issuer and an accredited investor.
    Returns (issuer, investor)."""
    if clock is not None:
        set_clock(clock)
    issuer = create_verified_issuer(**(issuer_overrides or {}))
    investor = create_accredited_investor(**(investor_overrides or {}))
    return issuer, investor


def setup_live_offering_with_accredited_investor(clock="2026-06-01T00:00:00Z",
                                                 offering_overrides=None,
                                                 issuer_overrides=None,
                                                 investor_overrides=None):
    """Verified issuer + accredited investor + LIVE offering (no commitment yet).
    Returns (issuer, investor, offering). The offering is re-read so .version is current."""
    issuer, investor = setup_verified_issuer_and_accredited_investor(
        clock=clock, issuer_overrides=issuer_overrides, investor_overrides=investor_overrides)
    offering = create_live_offering(issuer["id"], **(offering_overrides or {}))
    return issuer, investor, offering


def commit(offering, investor_id, amount_cents):
    """Place a single investment against an offering at its current version (re-read first to
    capture the live version). Returns (investment, refreshed_offering)."""
    issuer_id = offering["issuer_id"]
    fresh = get_success_data(api_client.get_offering(offering["id"], headers=make_issuer_headers(issuer_id)))
    inv_headers = make_investor_headers(investor_id)
    investment = get_success_data(api_client.create_investment(
        create_investment_payload(offering["id"], investor_id, fresh["version"], amount_cents=amount_cents),
        headers=inv_headers))
    refreshed = get_success_data(api_client.get_offering(offering["id"], headers=make_issuer_headers(issuer_id)))
    return investment, refreshed


def setup_committed_offering(amount_cents=200_000, clock="2026-06-01T00:00:00Z",
                             offering_overrides=None, investor_overrides=None):
    """LIVE offering with one accredited commitment in COMMITTED.
    Returns (issuer, investor, offering, investment)."""
    issuer, investor, offering = setup_live_offering_with_accredited_investor(
        clock=clock, offering_overrides=offering_overrides, investor_overrides=investor_overrides)
    investment, offering = commit(offering, investor["id"], amount_cents)
    return issuer, investor, offering, investment


def setup_funded_offering(amount_cents=200_000, clock="2026-06-01T00:00:00Z",
                          offering_overrides=None, investor_overrides=None):
    """LIVE offering with one accredited commitment, then final-closed -> FUNDED.
    Returns (issuer, investor, offering, investment). offering is re-read (FUNDED)."""
    issuer, investor, offering, investment = setup_committed_offering(
        amount_cents=amount_cents, clock=clock,
        offering_overrides=offering_overrides, investor_overrides=investor_overrides)
    issuer_headers = make_issuer_headers(issuer["id"])
    get_success_data(api_client.close_offering(offering["id"], headers=issuer_headers))
    offering = get_success_data(api_client.get_offering(offering["id"], headers=issuer_headers))
    investment = get_success_data(api_client.get_investment(investment["id"], headers=issuer_headers))
    return issuer, investor, offering, investment


def get_escrow_data(offering_id, issuer_id):
    """Return the single escrow account dict for an offering (the endpoint returns an array of 0-1)."""
    issuer_headers = make_issuer_headers(issuer_id)
    arr = get_success_data(api_client.get_escrow(offering_id, headers=issuer_headers))
    assert isinstance(arr, list) and len(arr) >= 1, "expected an escrow account to exist"
    return arr[0]


def get_cap_table_list(offering_id, issuer_id, params=None):
    """Return the cap-table positions list for an offering."""
    issuer_headers = make_issuer_headers(issuer_id)
    return get_success_data(api_client.get_cap_table(offering_id, headers=issuer_headers, params=params))


# --- Tier 4: investor-update helpers ---

def create_draft_update(offering_id, issuer_id, **overrides) -> dict:
    """Draft an investor update on an offering. Returns the DRAFT update dict."""
    issuer_headers = make_issuer_headers(issuer_id)
    return get_success_data(api_client.create_investor_update(
        create_investor_update_payload(offering_id, **overrides), headers=issuer_headers))


def publish_update(update_id, issuer_id) -> dict:
    """Publish an investor update. Returns the response data."""
    issuer_headers = make_issuer_headers(issuer_id)
    return get_success_data(api_client.publish_investor_update(update_id, headers=issuer_headers))
