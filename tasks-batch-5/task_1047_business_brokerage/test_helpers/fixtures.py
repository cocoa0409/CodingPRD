"""Composite setup helpers for the Business Brokerage API.

Every helper builds its preconditions from scratch (the server database is empty
before each test) using only PRD-declared endpoints, and threads entity-backed
identities through ``make_*_headers(entity_id)`` so ownership checks pass.

Setup calls use ``get_success_data`` (lenient) so a broken precondition surfaces
as a clear "Setup failed" rather than a confusing assertion later.
"""
from prd_bench_local_runner.testing import get_success_data

from .test_users import (
    TEST_USERS,
    make_broker_headers,
    make_seller_headers,
    make_buyer_headers,
)
from . import factories as F


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------
def onboard_broker(api, **overrides) -> dict:
    return get_success_data(
        api.create_broker(F.create_broker_payload(**overrides), TEST_USERS["platform_admin_headers"])
    )


def onboard_seller(api, **overrides) -> dict:
    return get_success_data(
        api.create_seller(F.create_seller_payload(**overrides), TEST_USERS["platform_admin_headers"])
    )


def onboard_buyer(api, proof_of_funds_cents=30_000_000, net_worth_cents=150_000_000, **overrides) -> dict:
    payload = F.create_buyer_payload(
        proof_of_funds_cents=proof_of_funds_cents, net_worth_cents=net_worth_cents, **overrides
    )
    return get_success_data(api.create_buyer(payload, TEST_USERS["platform_admin_headers"]))


def create_listing(api, broker_id, seller_id, **overrides) -> dict:
    payload = F.create_listing_payload(seller_id, **overrides)
    return get_success_data(api.create_listing(payload, make_broker_headers(broker_id)))


def create_and_publish_cim(api, broker_id, listing_id, valuation_method="SDE_MULTIPLE") -> dict:
    cim = get_success_data(
        api.create_cim(listing_id, F.create_cim_payload(valuation_method), make_broker_headers(broker_id))
    )
    return get_success_data(api.publish_cim(cim["id"], make_broker_headers(broker_id)))


def activate_listing(api, broker_id, listing_id) -> dict:
    return get_success_data(api.activate_listing(listing_id, make_broker_headers(broker_id)))


def sign_nda(api, buyer_id, listing_id) -> dict:
    return get_success_data(api.sign_nda(listing_id, make_buyer_headers(buyer_id)))


def upload_document(api, broker_id, listing_id, **overrides) -> dict:
    return get_success_data(
        api.upload_document(listing_id, F.create_document_payload(**overrides), make_broker_headers(broker_id))
    )


def open_deal(api, broker_id, listing_id, buyer_id) -> dict:
    return get_success_data(
        api.create_deal(F.create_deal_payload(listing_id, buyer_id), make_broker_headers(broker_id))
    )


def qualify_deal(api, broker_id, deal_id) -> dict:
    return get_success_data(api.qualify_deal(deal_id, make_broker_headers(broker_id)))


def submit_loi(api, buyer_id, deal_id, expected_deal_version, **overrides) -> dict:
    payload = F.create_loi_payload(expected_deal_version, **overrides)
    return get_success_data(api.submit_loi(deal_id, payload, make_buyer_headers(buyer_id)))


def accept_loi(api, seller_id, loi_id) -> dict:
    return get_success_data(api.accept_loi(loi_id, make_seller_headers(seller_id)))


# ---------------------------------------------------------------------------
# Tier 1/2: listings and qualified deals
# ---------------------------------------------------------------------------
def setup_active_listing(api, **listing_overrides) -> dict:
    """Broker + Seller + a DRAFT->ACTIVE listing with one PUBLISHED SDE_MULTIPLE CIM.

    Returns dict: broker, seller, listing, cim.
    """
    broker = onboard_broker(api)
    seller = onboard_seller(api)
    listing = create_listing(api, broker["id"], seller["id"], **listing_overrides)
    cim = create_and_publish_cim(api, broker["id"], listing["id"], "SDE_MULTIPLE")
    listing = activate_listing(api, broker["id"], listing["id"])
    return {"broker": broker, "seller": seller, "listing": listing, "cim": cim}


def setup_qualified_deal(
    api,
    buyer_proof_of_funds_cents=30_000_000,
    buyer_net_worth_cents=150_000_000,
    sign_buyer_nda=True,
    **listing_overrides,
) -> dict:
    """Active listing + onboarded buyer (NDA signed) + a QUALIFIED deal.

    Returns dict: broker, seller, buyer, listing, cim, deal, deal_version
    (deal_version is the deal.version observed right after qualify — the value a
    buyer would carry as expected_deal_version on their first LOI submit).
    """
    s = setup_active_listing(api, **listing_overrides)
    buyer = onboard_buyer(
        api, proof_of_funds_cents=buyer_proof_of_funds_cents, net_worth_cents=buyer_net_worth_cents
    )
    if sign_buyer_nda:
        sign_nda(api, buyer["id"], s["listing"]["id"])
    deal = open_deal(api, s["broker"]["id"], s["listing"]["id"], buyer["id"])
    deal = qualify_deal(api, s["broker"]["id"], deal["id"])
    s.update({"buyer": buyer, "deal": deal, "deal_version": deal["version"]})
    return s


def setup_prospect_deal(
    api,
    buyer_proof_of_funds_cents=30_000_000,
    buyer_net_worth_cents=150_000_000,
    sign_buyer_nda=True,
    **listing_overrides,
) -> dict:
    """Active listing + onboarded buyer (NDA signed) + a deal left at PROSPECT (not qualified).

    Returns dict: broker, seller, buyer, listing, cim, deal, deal_version.
    """
    s = setup_active_listing(api, **listing_overrides)
    buyer = onboard_buyer(
        api, proof_of_funds_cents=buyer_proof_of_funds_cents, net_worth_cents=buyer_net_worth_cents
    )
    if sign_buyer_nda:
        sign_nda(api, buyer["id"], s["listing"]["id"])
    deal = open_deal(api, s["broker"]["id"], s["listing"]["id"], buyer["id"])
    s.update({"buyer": buyer, "deal": deal, "deal_version": deal["version"]})
    return s


def setup_submitted_loi(
    api,
    offer_price_cents=115_000_000,
    earnest_deposit_cents=5_000_000,
    earnout_amount_cents=0,
    earnout_periods=1,
    buyer_proof_of_funds_cents=30_000_000,
    buyer_net_worth_cents=150_000_000,
    **listing_overrides,
) -> dict:
    """Qualified deal + one SUBMITTED LOI. Returns the qualified-deal dict plus `loi`."""
    s = setup_qualified_deal(
        api,
        buyer_proof_of_funds_cents=buyer_proof_of_funds_cents,
        buyer_net_worth_cents=buyer_net_worth_cents,
        **listing_overrides,
    )
    loi = submit_loi(
        api,
        s["buyer"]["id"],
        s["deal"]["id"],
        s["deal_version"],
        offer_price_cents=offer_price_cents,
        earnest_deposit_cents=earnest_deposit_cents,
        earnout_amount_cents=earnout_amount_cents,
        earnout_periods=earnout_periods,
    )
    s["loi"] = loi
    return s


def setup_deal_under_loi(api, **kwargs) -> dict:
    """Qualified deal + SUBMITTED LOI + seller accept -> deal UNDER_LOI, LOI ACCEPTED."""
    s = setup_submitted_loi(api, **kwargs)
    loi = accept_loi(api, s["seller"]["id"], s["loi"]["id"])
    s["loi"] = loi
    s["deal"] = get_success_data(
        api.get_deal(s["deal"]["id"], make_broker_headers(s["broker"]["id"]))
    )
    return s


# ---------------------------------------------------------------------------
# Tier 3: financing and escrow lifecycle
# ---------------------------------------------------------------------------
def setup_deal_in_financing(api, loan_requested_amount_cents=99_000_000, upload_doc=True, **kwargs) -> dict:
    """Deal advanced to FINANCING with a SUBMITTED loan application.

    Returns the under-LOI dict plus `loan`. Setup: accept -> upload document ->
    open-diligence -> enter-financing -> submit loan application.
    """
    s = setup_deal_under_loi(api, **kwargs)
    broker_id = s["broker"]["id"]
    if upload_doc:
        upload_document(api, broker_id, s["listing"]["id"])
    get_success_data(api.open_diligence(s["deal"]["id"], make_broker_headers(broker_id)))
    get_success_data(api.enter_financing(s["deal"]["id"], make_broker_headers(broker_id)))
    loan = get_success_data(
        api.submit_loan_application(
            s["deal"]["id"], F.create_loan_payload(loan_requested_amount_cents),
            make_buyer_headers(s["buyer"]["id"]),
        )
    )
    s["loan"] = loan
    return s


def approve_loan(api, loan_id) -> dict:
    return get_success_data(
        api.decide_loan(loan_id, {"outcome": "APPROVED"}, TEST_USERS["lender_headers"])
    )


def setup_deal_in_escrow(
    api,
    closing_price_cents=110_000_000,
    required_deposit_cents=5_000_000,
    **kwargs,
) -> dict:
    """Deal advanced to IN_ESCROW with an OPENED escrow account (loan APPROVED).

    Returns the financing dict plus `escrow`.
    """
    s = setup_deal_in_financing(api, **kwargs)
    approve_loan(api, s["loan"]["id"])
    escrow = get_success_data(
        api.open_escrow(
            s["deal"]["id"],
            F.create_escrow_payload(closing_price_cents, required_deposit_cents),
            TEST_USERS["escrow_agent_headers"],
        )
    )
    s["escrow"] = escrow
    return s


def setup_deal_escrow_funded(api, deposit_amount_cents=5_000_000, **kwargs) -> dict:
    """Deal IN_ESCROW with a FUNDED escrow account (buyer deposit made)."""
    s = setup_deal_in_escrow(api, **kwargs)
    escrow = get_success_data(
        api.deposit_escrow(
            s["escrow"]["id"], {"amount_cents": deposit_amount_cents},
            make_buyer_headers(s["buyer"]["id"]),
        )
    )
    s["escrow"] = escrow
    return s


def setup_closed_deal(api, **kwargs) -> dict:
    """Full pipeline through escrow close -> deal CLOSED, listing SOLD.

    Returns the funded-escrow dict plus refreshed `deal`, `escrow`, `broker`.
    """
    s = setup_deal_escrow_funded(api, **kwargs)
    escrow = get_success_data(api.close_escrow(s["escrow"]["id"], TEST_USERS["escrow_agent_headers"]))
    s["escrow"] = escrow
    s["deal"] = get_success_data(
        api.get_deal(s["deal"]["id"], make_broker_headers(s["broker"]["id"]))
    )
    s["broker"] = get_success_data(
        api.get_broker(s["broker"]["id"], TEST_USERS["platform_admin_headers"])
    )
    return s


# ---------------------------------------------------------------------------
# Multi-buyer rival scenario (for the acceptance-cascade instance)
# ---------------------------------------------------------------------------
def setup_two_rival_qualified_deals(api, **listing_overrides) -> dict:
    """One ACTIVE listing with two QUALIFIED deals (Buyer-A, Buyer-B), each with a
    SUBMITTED LOI. Returns broker, seller, listing, buyer_a, buyer_b, deal_a, deal_b,
    loi_a, loi_b.
    """
    base = setup_active_listing(api, **listing_overrides)
    broker_id = base["broker"]["id"]
    listing_id = base["listing"]["id"]

    buyer_a = onboard_buyer(api, full_name="Buyer A", email="a@x.com")
    buyer_b = onboard_buyer(api, full_name="Buyer B", email="b@x.com")
    sign_nda(api, buyer_a["id"], listing_id)
    sign_nda(api, buyer_b["id"], listing_id)

    deal_a = qualify_deal(api, broker_id, open_deal(api, broker_id, listing_id, buyer_a["id"])["id"])
    deal_b = qualify_deal(api, broker_id, open_deal(api, broker_id, listing_id, buyer_b["id"])["id"])

    loi_a = submit_loi(
        api, buyer_a["id"], deal_a["id"], deal_a["version"],
        offer_price_cents=115_000_000, earnest_deposit_cents=5_000_000,
    )
    loi_b = submit_loi(
        api, buyer_b["id"], deal_b["id"], deal_b["version"],
        offer_price_cents=112_000_000, earnest_deposit_cents=4_000_000,
    )
    return {
        "broker": base["broker"], "seller": base["seller"], "listing": base["listing"],
        "buyer_a": buyer_a, "buyer_b": buyer_b,
        "deal_a": deal_a, "deal_b": deal_b, "loi_a": loi_a, "loi_b": loi_b,
    }


# ---------------------------------------------------------------------------
# Convenience re-reads
# ---------------------------------------------------------------------------
def get_deal(api, s, deal_id=None) -> dict:
    return get_success_data(
        api.get_deal(deal_id or s["deal"]["id"], make_broker_headers(s["broker"]["id"]))
    )


def get_buyer(api, buyer_id) -> dict:
    return get_success_data(api.get_buyer(buyer_id, TEST_USERS["platform_admin_headers"]))


def get_broker(api, broker_id) -> dict:
    return get_success_data(api.get_broker(broker_id, TEST_USERS["platform_admin_headers"]))


def get_listing(api, broker_id, listing_id) -> dict:
    return get_success_data(api.get_listing(listing_id, make_broker_headers(broker_id)))
