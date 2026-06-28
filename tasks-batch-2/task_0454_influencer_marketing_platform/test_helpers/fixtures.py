"""Composite setup helpers.

These encapsulate the multi-step API sequences needed to drive the platform into
the states that tests assert against (signed contracts, fulfilled contracts,
settled payouts, generated 1099s, etc.). Every helper builds its preconditions
from scratch against an empty database using only PRD-declared endpoints, and
uses get_success_data() so a setup failure surfaces clearly.

Identity threading: Brand and Creator are entity-backed roles. After a fixture
creates a Brand/Creator, any ownership-gated call uses make_brand_headers(brand_id)
or make_creator_headers(creator_id) with the real entity id — never a shared
constant — so ownership checks pass.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_brand_headers, make_creator_headers,
    make_compliance_headers, make_admin_headers,
)
from .factories import (
    create_brand_payload, create_creator_payload, create_campaign_payload,
    create_deliverable_payload, create_offer_payload,
    create_content_submission_payload, create_attribution_asset_payload,
    create_audience_snapshot_payload, create_brand_safety_flag_payload,
)

ADMIN = make_admin_headers()
COMPLIANCE = make_compliance_headers()


# ----------------------------------------------------------------------------
# Clock
# ----------------------------------------------------------------------------
def set_clock(iso: str):
    """Set the logical clock; returns the response data."""
    return get_success_data(api_client.set_clock(iso, ADMIN))


# ----------------------------------------------------------------------------
# Tier 1: Primitive creation helpers
# ----------------------------------------------------------------------------
def create_brand(budget_cents=1_000_000, legal_name="Test Brand", contact_email="ops@test.com"):
    """Create a brand. Returns the brand dict."""
    return get_success_data(api_client.create_brand(
        create_brand_payload(legal_name=legal_name, contact_email=contact_email,
                             budget_cents=budget_cents),
        ADMIN,
    ))


_handle_counter = [0]


def _unique_handle(base="@c"):
    _handle_counter[0] += 1
    return f"{base}{_handle_counter[0]}"


def create_creator(handle=None, primary_platform="INSTAGRAM", tax_id_on_file=True, **overrides):
    """Create a creator. Returns the creator dict."""
    if handle is None:
        handle = _unique_handle()
    payload = create_creator_payload(handle=handle, primary_platform=primary_platform,
                                     tax_id_on_file=tax_id_on_file, **overrides)
    return get_success_data(api_client.create_creator(payload, ADMIN))


def add_audience_snapshot(creator_id, **overrides):
    """Record an audience snapshot for a creator. Returns the snapshot dict."""
    return get_success_data(api_client.create_audience_snapshot(
        creator_id, create_audience_snapshot_payload(**overrides), ADMIN,
    ))


def create_clean_creator(handle=None, primary_platform="INSTAGRAM", tax_id_on_file=True):
    """Creator + one low-fraud snapshot so discovery_status is DISCOVERABLE
    and brand_safety_status is CLEAR. Returns the creator dict (re-fetched)."""
    creator = create_creator(handle=handle, primary_platform=primary_platform,
                             tax_id_on_file=tax_id_on_file)
    add_audience_snapshot(creator["id"])
    return get_success_data(api_client.get_creator(creator["id"], ADMIN))


def open_brand_safety_flag(creator_id, severity="HIGH", reason_code="FRAUD_SIGNAL", note="blocked"):
    """Open a brand-safety flag on a creator. Returns the flag dict."""
    return get_success_data(api_client.create_brand_safety_flag(
        creator_id, create_brand_safety_flag_payload(severity=severity,
                                                     reason_code=reason_code, note=note),
        COMPLIANCE,
    ))


# ----------------------------------------------------------------------------
# Tier 1/2: Campaign progression
# ----------------------------------------------------------------------------
def create_draft_campaign(brand_id, with_deliverable=True, requires_ftc_disclosure=False,
                          campaign_budget_cents=200_000, starts_at="2026-02-01T00:00:00Z",
                          ends_at="2026-03-01T00:00:00Z", base_rate_cents=60_000,
                          content_type="FEED_POST", title="Test Campaign"):
    """Create a DRAFT campaign, optionally with one deliverable.
    Returns (campaign, deliverable_or_None). campaign is the fresh response (version 1)."""
    bh = make_brand_headers(brand_id)
    campaign = get_success_data(api_client.create_campaign(
        create_campaign_payload(brand_id, title=title,
                                campaign_budget_cents=campaign_budget_cents,
                                requires_ftc_disclosure=requires_ftc_disclosure,
                                starts_at=starts_at, ends_at=ends_at),
        bh,
    ))
    deliverable = None
    if with_deliverable:
        deliverable = get_success_data(api_client.create_deliverable(
            campaign["id"],
            create_deliverable_payload(content_type=content_type, quantity=1,
                                       base_rate_cents=base_rate_cents),
            bh,
        ))
    return campaign, deliverable


def open_campaign(campaign):
    """Open a DRAFT campaign (campaign dict must carry current version).
    Returns the opened campaign dict."""
    bh = make_brand_headers(campaign["brand_id"])
    return get_success_data(api_client.open_campaign(
        campaign["id"], {"expected_campaign_version": campaign["version"]}, bh,
    ))


def create_open_campaign(brand_id, **overrides):
    """DRAFT campaign with one deliverable, then opened.
    Returns (campaign_after_open, deliverable)."""
    campaign, deliverable = create_draft_campaign(brand_id, with_deliverable=True, **overrides)
    opened = open_campaign(campaign)
    return opened, deliverable


# ----------------------------------------------------------------------------
# Tier 2/3: Negotiation + signing
# ----------------------------------------------------------------------------
def open_offer(brand_id, campaign_id, creator_id, current_amount_cents=60_000, exclusivity_days=0):
    """Brand opens an offer on an OPEN campaign. Returns the offer dict (status OFFERED)."""
    bh = make_brand_headers(brand_id)
    return get_success_data(api_client.create_offer(
        create_offer_payload(campaign_id, creator_id,
                             current_amount_cents=current_amount_cents,
                             exclusivity_days=exclusivity_days),
        bh,
    ))


def accept_offer_by_creator(offer, creator_id):
    """Creator accepts a brand-opened offer (opposite side). Returns the accepted offer."""
    ch = make_creator_headers(creator_id)
    return get_success_data(api_client.accept_offer(
        offer["id"], {"expected_offer_version": offer["version"]}, ch,
    ))


def sign_contract(brand_id, offer_after_accept):
    """Brand signs an ACCEPTED offer. Returns the contract dict (status ACTIVE)."""
    bh = make_brand_headers(brand_id)
    return get_success_data(api_client.create_contract(
        {"offer_id": offer_after_accept["id"],
         "expected_offer_version": offer_after_accept["version"]},
        bh,
    ))


def setup_active_contract(brand_budget_cents=1_000_000, offer_amount_cents=60_000,
                          requires_ftc_disclosure=False, exclusivity_days=0,
                          creator_tax_id_on_file=True, base_rate_cents=None,
                          campaign_budget_cents=200_000, content_type="FEED_POST"):
    """Full chain to an ACTIVE contract on a single-deliverable campaign.

    brand -> clean creator -> open campaign (1 deliverable) -> offer -> accept -> sign.
    Returns a dict with brand, creator, campaign, deliverable, offer, contract.
    """
    if base_rate_cents is None:
        base_rate_cents = offer_amount_cents
    brand = create_brand(budget_cents=brand_budget_cents)
    creator = create_clean_creator(tax_id_on_file=creator_tax_id_on_file)
    campaign, deliverable = create_open_campaign(
        brand["id"], requires_ftc_disclosure=requires_ftc_disclosure,
        campaign_budget_cents=campaign_budget_cents, base_rate_cents=base_rate_cents,
        content_type=content_type,
    )
    offer = open_offer(brand["id"], campaign["id"], creator["id"],
                       current_amount_cents=offer_amount_cents, exclusivity_days=exclusivity_days)
    accepted = accept_offer_by_creator(offer, creator["id"])
    contract = sign_contract(brand["id"], accepted)
    return {
        "brand": brand, "creator": creator, "campaign": campaign,
        "deliverable": deliverable, "offer": accepted, "contract": contract,
    }


# ----------------------------------------------------------------------------
# Tier 3: Content submission + approval -> FULFILLED
# ----------------------------------------------------------------------------
def submit_content(creator_id, deliverable_id, contract_id, caption="Loving this #ad",
                   media_url="https://example.com/content"):
    """Creator submits content. Returns the submission dict (status SUBMITTED)."""
    ch = make_creator_headers(creator_id)
    return get_success_data(api_client.create_content_submission(
        create_content_submission_payload(deliverable_id, contract_id,
                                          media_url=media_url, caption=caption),
        ch,
    ))


def start_review(submission_id):
    return get_success_data(api_client.start_review(submission_id, COMPLIANCE))


def approve_content(submission_id):
    return get_success_data(api_client.approve_content(submission_id, COMPLIANCE))


def setup_fulfilled_contract(offer_amount_cents=80_000, creator_tax_id_on_file=True,
                             requires_ftc_disclosure=False, brand_budget_cents=1_000_000,
                             campaign_budget_cents=200_000, caption="ok",
                             content_type="FEED_POST"):
    """ACTIVE contract whose single deliverable is approved -> contract FULFILLED.

    Returns a dict: brand, creator, campaign, deliverable, offer, contract (FULFILLED),
    submission (APPROVED), plus contract_version (the current Contract.version after fulfill).
    """
    ctx = setup_active_contract(
        brand_budget_cents=brand_budget_cents, offer_amount_cents=offer_amount_cents,
        requires_ftc_disclosure=requires_ftc_disclosure,
        creator_tax_id_on_file=creator_tax_id_on_file,
        campaign_budget_cents=campaign_budget_cents, content_type=content_type,
    )
    submission = submit_content(ctx["creator"]["id"], ctx["deliverable"]["id"],
                                ctx["contract"]["id"], caption=caption)
    start_review(submission["id"])
    approved = approve_content(submission["id"])
    contract = get_success_data(api_client.get_contract(ctx["contract"]["id"], COMPLIANCE))
    ctx["submission"] = approved
    ctx["contract"] = contract
    ctx["contract_version"] = contract["version"]
    return ctx


# ----------------------------------------------------------------------------
# Tier 4/5: Payout lifecycle
# ----------------------------------------------------------------------------
def create_payout(contract_id, expected_contract_version):
    """ComplianceOfficer creates a payout against a FULFILLED contract. Returns payout dict."""
    return get_success_data(api_client.create_payout(
        {"contract_id": contract_id, "expected_contract_version": expected_contract_version},
        COMPLIANCE,
    ))


def setup_pending_payout(offer_amount_cents=80_000, creator_tax_id_on_file=True, **overrides):
    """FULFILLED contract with a freshly created PENDING payout.
    Returns the fulfilled-contract ctx augmented with 'payout'."""
    ctx = setup_fulfilled_contract(offer_amount_cents=offer_amount_cents,
                                   creator_tax_id_on_file=creator_tax_id_on_file, **overrides)
    payout = create_payout(ctx["contract"]["id"], ctx["contract_version"])
    ctx["payout"] = payout
    return ctx


def setup_released_payout(offer_amount_cents=80_000, **overrides):
    """FULFILLED contract with a payout driven to RELEASED (W-9 creator).
    Returns ctx augmented with 'payout' (RELEASED)."""
    ctx = setup_pending_payout(offer_amount_cents=offer_amount_cents,
                               creator_tax_id_on_file=True, **overrides)
    released = get_success_data(api_client.release_payout(ctx["payout"]["id"], COMPLIANCE))
    ctx["payout"] = released
    return ctx


def setup_settled_payout(offer_amount_cents=80_000, **overrides):
    """FULFILLED contract with a payout driven to SETTLED (cascades fire).
    Returns ctx augmented with 'payout' (SETTLED)."""
    ctx = setup_released_payout(offer_amount_cents=offer_amount_cents, **overrides)
    settled = get_success_data(api_client.settle_payout(ctx["payout"]["id"], COMPLIANCE))
    ctx["payout"] = settled
    return ctx


# ----------------------------------------------------------------------------
# Helpers for performance / conversions
# ----------------------------------------------------------------------------
def create_attribution_asset(brand_id, contract_id, asset_type="TRACKING_LINK",
                             code_or_slug="test-slug"):
    bh = make_brand_headers(brand_id)
    return get_success_data(api_client.create_attribution_asset(
        create_attribution_asset_payload(contract_id, asset_type=asset_type,
                                         code_or_slug=code_or_slug),
        bh,
    ))


def ingest_conversion(asset_id, event_type, count, revenue_cents=None):
    payload = {"event_type": event_type, "count": count}
    if revenue_cents is not None:
        payload["revenue_cents"] = revenue_cents
    return get_success_data(api_client.create_conversion(asset_id, payload, ADMIN))
