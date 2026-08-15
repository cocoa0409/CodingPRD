"""Composite setup helpers for the yacht brokerage deal pipeline.

Every helper builds its preconditions from scratch against an empty database
using only PRD-declared endpoints, and uses get_success_data() so setup
failures surface as clear "Setup failed" errors rather than assertion noise.

Header threading: ListingAgent / SellingAgent calls are ownership-gated, so
each fixture derives headers from the actual BrokerAgent ids it created.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .factories import (
    create_agent_payload,
    create_brokerage_payload,
    create_client_payload,
    create_closing_statement_payload,
    create_documentation_record_payload,
    create_escrow_entry_payload,
    create_lien_payload,
    create_listing_payload,
    create_offer_payload,
    create_state_vessel_payload,
    create_title_transfer_payload,
    create_vessel_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_listing_agent_headers,
    make_selling_agent_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLOSING = TEST_USERS["closing_officer_headers"]
ESCROW = TEST_USERS["escrow_officer_headers"]


def required_deposit_cents(offer_price_cents: int, deposit_pct_basis: int) -> int:
    """PRD 3.6: offer price * deposit basis points / 10000, rounded half-up."""
    return (offer_price_cents * deposit_pct_basis + 5000) // 10000


# --- Tier 0: primitive creation helpers ------------------------------------

def set_clock(to_iso8601: str = DEFAULT_CLOCK):
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


def create_brokerage(**overrides):
    return get_success_data(api_client.create_brokerage(
        create_brokerage_payload(**overrides), ADMIN))


def create_agent(brokerage_id: str, **overrides):
    return get_success_data(api_client.create_agent(
        create_agent_payload(brokerage_id, **overrides), ADMIN))


def create_client(**overrides):
    return get_success_data(api_client.create_client(
        create_client_payload(**overrides), ADMIN))


def create_vessel(**overrides):
    return get_success_data(api_client.create_vessel(
        create_vessel_payload(**overrides), ADMIN))


def create_state_vessel(**overrides):
    return get_success_data(api_client.create_vessel(
        create_state_vessel_payload(**overrides), ADMIN))


# --- Tier 1/2: desk + active listing ----------------------------------------

def setup_brokerage_desk(co_broke: bool = False, brokerage_overrides=None,
                         seller_overrides=None, buyer_overrides=None):
    """Brokerage + listing agent + selling agent + seller + buyer clients.

    With co_broke=True the selling agent belongs to a SECOND brokerage,
    producing a co-brokered deal (PRD 3.7 commission split).
    """
    set_clock(DEFAULT_CLOCK)
    brokerage = create_brokerage(**(brokerage_overrides or {}))
    listing_agent = create_agent(brokerage["id"], full_name="Lena Lister")
    if co_broke:
        selling_brokerage = create_brokerage(
            legal_name="Selling House", home_state_code="CA",
            escrow_account_ref="TRUST-002", license_no="CA-BRK-2")
        selling_agent = create_agent(selling_brokerage["id"], full_name="Sam Seller")
    else:
        selling_brokerage = brokerage
        selling_agent = create_agent(brokerage["id"], full_name="Sam Seller")
    seller = create_client(**(seller_overrides or {}))
    buyer = create_client(kind="BUYER", full_name="Bob Buyer",
                          **(buyer_overrides or {}))
    return {
        "brokerage": brokerage,
        "selling_brokerage": selling_brokerage,
        "listing_agent": listing_agent,
        "selling_agent": selling_agent,
        "seller": seller,
        "buyer": buyer,
    }


def listing_headers(deal) -> dict:
    return make_listing_agent_headers(deal["listing_agent"]["id"])


def selling_headers(deal) -> dict:
    return make_selling_agent_headers(deal["selling_agent"]["id"])


def setup_active_listing(list_price_cents: int = 120000000,
                         vessel_overrides=None, listing_overrides=None,
                         lien_payloads=None, state_vessel: bool = False,
                         **desk_kwargs):
    """Desk + vessel + listing activated to ACTIVE. Returns the deal dict."""
    deal = setup_brokerage_desk(**desk_kwargs)
    if state_vessel:
        vessel = create_state_vessel(**(vessel_overrides or {}))
    else:
        vessel = create_vessel(**(vessel_overrides or {}))
    deal["vessel"] = vessel
    liens = []
    for lp in (lien_payloads or []):
        liens.append(get_success_data(api_client.create_lien(
            vessel["id"], create_lien_payload(**lp), listing_headers(deal))))
    deal["liens"] = liens
    listing = get_success_data(api_client.create_listing(
        create_listing_payload(
            deal["brokerage"]["id"], deal["listing_agent"]["id"],
            deal["seller"]["id"], vessel["id"],
            list_price_cents=list_price_cents, **(listing_overrides or {})),
        listing_headers(deal)))
    listing = get_success_data(api_client.activate_listing(
        listing["id"], listing_headers(deal)))
    deal["listing"] = listing
    return deal


# --- Tier 3: offer lifecycle -------------------------------------------------

def submit_offer(deal, **overrides) -> dict:
    offer = get_success_data(api_client.create_offer(
        create_offer_payload(
            deal["listing"]["id"], deal["buyer"]["id"],
            deal["selling_agent"]["id"], **overrides),
        selling_headers(deal)))
    deal["offer"] = offer
    return offer


def accept_current_offer(deal, offer) -> dict:
    """Accept a PENDING offer using its current version (OCC)."""
    accepted = get_success_data(api_client.accept_offer(
        offer["id"], {"expected_offer_version": offer["version"]},
        listing_headers(deal)))
    deal["offer"] = accepted
    return accepted


def setup_accepted_offer(offer_price_cents: int = 110000000,
                         offer_overrides=None, **listing_kwargs):
    """Active listing + one PENDING offer + accept. Returns deal dict with
    deal['offer'] ACCEPTED. Contingencies are auto-created by acceptance."""
    deal = setup_active_listing(**listing_kwargs)
    offer = submit_offer(deal, offer_price_cents=offer_price_cents,
                         **(offer_overrides or {}))
    accept_current_offer(deal, offer)
    return deal


def list_offer_contingencies(deal, offer=None) -> list:
    offer = offer or deal["offer"]
    return get_success_data(api_client.list_contingencies(
        offer["id"], selling_headers(deal)))


def waive_all_contingencies(deal, offer=None) -> list:
    """Waive every OPEN contingency on the accepted offer (buyer side)."""
    offer = offer or deal["offer"]
    updated = []
    for c in list_offer_contingencies(deal, offer):
        if c["status"] == "OPEN":
            updated.append(get_success_data(api_client.waive_contingency(
                c["id"], selling_headers(deal))))
        else:
            updated.append(c)
    deal["contingencies"] = updated
    return updated


# --- Tier 4/5: closing statement pipeline ------------------------------------

def setup_draft_statement(deal, offer=None) -> dict:
    offer = offer or deal["offer"]
    statement = get_success_data(api_client.create_closing_statement(
        create_closing_statement_payload(offer["id"]), CLOSING))
    deal["statement"] = statement
    return statement


def build_statement(deal, statement, offer=None) -> dict:
    """Build a DRAFT statement, pinning the offer's current version (OCC)."""
    offer = offer or deal["offer"]
    fresh = get_success_data(api_client.get_offer(offer["id"], CLOSING))
    built = get_success_data(api_client.build_closing_statement(
        statement["id"], {"expected_offer_version": fresh["version"]}, CLOSING))
    deal["statement"] = built
    return built


def approve_statement(deal, statement) -> dict:
    """ListingAgent approval carrying the statement's current version (OCC)."""
    approved = get_success_data(api_client.approve_closing_statement(
        statement["id"], {"expected_statement_version": statement["version"]},
        listing_headers(deal)))
    deal["statement"] = approved
    return approved


def setup_balanced_statement(**kwargs):
    """Accepted offer, all contingencies waived, statement built to BALANCED."""
    deal = setup_accepted_offer(**kwargs)
    waive_all_contingencies(deal)
    statement = setup_draft_statement(deal)
    build_statement(deal, statement)
    return deal


def setup_approved_statement(**kwargs):
    """Statement through BALANCED and on to APPROVED."""
    deal = setup_balanced_statement(**kwargs)
    approve_statement(deal, deal["statement"])
    return deal


def record_cleared_deposit(deal, amount_cents=None, value_date="2026-08-02T00:00:00Z"):
    """Record a DEPOSIT entry and clear it once the clock reaches value_date."""
    offer = deal["offer"]
    if amount_cents is None:
        amount_cents = required_deposit_cents(
            offer["offer_price_cents"], offer["deposit_pct_basis"])
    entry = get_success_data(api_client.create_escrow_entry(
        offer["id"],
        create_escrow_entry_payload(amount_cents=amount_cents, value_date=value_date),
        ESCROW))
    set_clock(value_date)
    entry = get_success_data(api_client.clear_escrow_entry(entry["id"], ESCROW))
    return entry


def setup_disbursable(lien_payloads=None, offer_price_cents: int = 400000000,
                      warranty_of_title: str = "FULL", **kwargs):
    """Full chain to an APPROVED statement with every disbursement gate open:
    contingencies waived, deposit CLEARED before build then released to
    DISBURSED after approval, COD documentation record filed, title transfer
    EXECUTED. Returns the deal dict with keys statement/entry/transfer."""
    deal = setup_accepted_offer(
        offer_price_cents=offer_price_cents, lien_payloads=lien_payloads, **kwargs)
    entry = record_cleared_deposit(deal)
    deal["entry"] = entry
    waive_all_contingencies(deal)
    statement = setup_draft_statement(deal)
    build_statement(deal, statement)
    approve_statement(deal, deal["statement"])
    get_success_data(api_client.release_escrow_entry(entry["id"], CLOSING))
    get_success_data(api_client.create_documentation_record(
        deal["vessel"]["id"],
        create_documentation_record_payload(
            instrument_no=deal["vessel"].get("uscg_official_no") or "1234567"),
        CLOSING))
    transfer = get_success_data(api_client.create_title_transfer(
        deal["statement"]["id"],
        create_title_transfer_payload(
            deal["vessel"]["id"], deal["seller"]["id"], deal["buyer"]["id"],
            warranty_of_title=warranty_of_title),
        CLOSING))
    transfer = get_success_data(api_client.execute_title_transfer(
        transfer["id"], CLOSING))
    deal["transfer"] = transfer
    return deal
