"""Composite setup helpers for multi-step test prerequisites.

These encapsulate the recurring setup chains shared across many design
instances: laying down reference data, creating sellers/profiles, building and
settling transactions, accruing nexus, and walking returns through their
lifecycle. Each fixture uses get_success_data() (lenient) so a broken
precondition surfaces as a clear "Setup step failed" message.

Identity threading: Seller is entity-backed, so every ownership-gated Seller
call passes make_seller_headers(seller["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CA_JURISDICTION,
    NY_JURISDICTION,
    TX_JURISDICTION,
)
from .factories import (
    create_exemption_certificate_payload,
    create_line_item_payload,
    create_marketplace_facilitator_payload,
    create_nexus_profile_payload,
    create_product_category_payload,
    create_seller_payload,
    create_tax_jurisdiction_payload,
    create_tax_return_payload,
    create_transaction_payload,
    create_use_tax_accrual_payload,
)
from .test_users import (
    TEST_USERS,
    make_approver_headers,
    make_preparer_headers,
    make_seller_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── Clock control ────────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Set the server's logical UTC clock (PlatformAdmin-only)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 1: reference data ────────────────────────────────────────────────

def create_jurisdiction(**overrides):
    """Create one TaxJurisdiction (defaults to CA). Returns the entity."""
    res = api_client.create_tax_jurisdiction(create_tax_jurisdiction_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_ca_jurisdiction():
    return create_jurisdiction(**CA_JURISDICTION)


def create_tx_jurisdiction():
    return create_jurisdiction(**TX_JURISDICTION)


def create_ny_jurisdiction():
    return create_jurisdiction(**NY_JURISDICTION)


def create_category(jurisdiction_id, category_code="TANGIBLE", taxability="FULL"):
    res = api_client.create_product_category(
        create_product_category_payload(jurisdiction_id, category_code, taxability), ADMIN)
    return get_success_data(res)


def create_seller(legal_name="Test Seller", origin_state_code="CA"):
    res = api_client.create_seller(
        create_seller_payload(legal_name=legal_name, origin_state_code=origin_state_code), ADMIN)
    return get_success_data(res)


def create_facilitator(name="MP", collecting_state_codes=None):
    res = api_client.create_marketplace_facilitator(
        create_marketplace_facilitator_payload(name=name,
                                               collecting_state_codes=collecting_state_codes or ["CA"]),
        ADMIN)
    return get_success_data(res)


def create_nexus_profile(seller_id, jurisdiction_id):
    """Open a NexusProfile owned by the given seller (ownership-threaded)."""
    res = api_client.create_nexus_profile(
        create_nexus_profile_payload(seller_id, jurisdiction_id),
        make_seller_headers(seller_id))
    return get_success_data(res)


# ─── Tier 2: jurisdiction + category + seller bundle ───────────────────────

def setup_ca_seller(category_taxability="FULL", with_category=True):
    """CA jurisdiction (+ TANGIBLE category) and an ACTIVE seller with CA origin.

    Returns (jurisdiction, seller). When with_category is False no
    ProductCategory is created (for tests that never settle)."""
    jur = create_ca_jurisdiction()
    if with_category:
        create_category(jur["id"], "TANGIBLE", category_taxability)
    seller = create_seller(origin_state_code="CA")
    return jur, seller


def setup_ca_seller_with_profile(category_taxability="FULL", with_category=True):
    """CA jurisdiction (+ category), an ACTIVE seller, and an open CA NexusProfile.

    Returns (jurisdiction, seller, profile)."""
    jur, seller = setup_ca_seller(category_taxability, with_category)
    profile = create_nexus_profile(seller["id"], jur["id"])
    return jur, seller, profile


# ─── Tier 3: transactions + line items ─────────────────────────────────────

def create_pending_transaction(seller_id, jurisdiction_id, customer_ref="b1",
                               facilitator_id=None, customer_exempt_requested=None):
    """Create a PENDING transaction owned by the seller. Returns the entity."""
    payload = create_transaction_payload(seller_id, jurisdiction_id, customer_ref=customer_ref)
    if facilitator_id is not None:
        payload["facilitator_id"] = facilitator_id
    if customer_exempt_requested is not None:
        payload["customer_exempt_requested"] = customer_exempt_requested
    res = api_client.create_transaction(payload, make_seller_headers(seller_id))
    return get_success_data(res)


def add_line_item(seller_id, transaction_id, category_code="TANGIBLE",
                  quantity=1, unit_price=10.00):
    res = api_client.create_line_item(
        create_line_item_payload(transaction_id, category_code, quantity, unit_price),
        make_seller_headers(seller_id))
    return get_success_data(res)


def create_transaction_with_lines(seller_id, jurisdiction_id, lines, customer_ref="b1",
                                  facilitator_id=None, customer_exempt_requested=None):
    """Create a PENDING transaction and attach each line in `lines`.

    Each entry in `lines` is a dict: {category_code, quantity, unit_price}.
    Returns the transaction entity (PENDING, lines attached)."""
    txn = create_pending_transaction(
        seller_id, jurisdiction_id, customer_ref=customer_ref,
        facilitator_id=facilitator_id, customer_exempt_requested=customer_exempt_requested)
    for line in lines:
        add_line_item(seller_id, txn["id"],
                      category_code=line.get("category_code", "TANGIBLE"),
                      quantity=line.get("quantity", 1),
                      unit_price=line["unit_price"])
    return txn


def settle_transaction(seller_id, transaction_id):
    """Settle a PENDING transaction (ownership-threaded). Returns the settled txn."""
    res = api_client.settle_transaction(transaction_id, make_seller_headers(seller_id))
    return get_success_data(res)


def create_and_settle_transaction(seller_id, jurisdiction_id, lines, customer_ref="b1",
                                  facilitator_id=None, customer_exempt_requested=None):
    """Create a PENDING transaction with lines, then settle it. Returns settled txn."""
    txn = create_transaction_with_lines(
        seller_id, jurisdiction_id, lines, customer_ref=customer_ref,
        facilitator_id=facilitator_id, customer_exempt_requested=customer_exempt_requested)
    return settle_transaction(seller_id, txn["id"])


# ─── Tier 4: nexus accrual / threshold targeting ───────────────────────────

def settle_one_full_line(seller_id, jurisdiction_id, unit_price, customer_ref="b1"):
    """Settle a transaction carrying a single FULL TANGIBLE line at unit_price.

    Convenient for driving a NexusProfile accumulator to an exact value."""
    return create_and_settle_transaction(
        seller_id, jurisdiction_id,
        [{"category_code": "TANGIBLE", "quantity": 1, "unit_price": unit_price}],
        customer_ref=customer_ref)


def setup_registered_seller_ca(big_unit_price=100000.00,
                               threshold_clock="2026-01-15T00:00:00Z",
                               working_clock="2026-02-15T00:00:00Z"):
    """CA jurisdiction + category + seller + open profile, then settle a large
    SELLER transaction to cross the sales threshold and register for nexus.

    The threshold-crossing transaction is settled at `threshold_clock`, an
    instant that is deliberately BEFORE the return periods these tests file
    (which start 2026-02-01). Per PRD §3.9 the acceptance sweep gathers every
    SETTLED/SELLER transaction whose `created_at` falls in the return period,
    so the threshold-crosser must be created outside that period or a faithful
    sweep would (correctly) fold its large `tax_collected` into `tax_due`.
    Nexus accumulators are persistent and period-independent, so settling the
    crosser earlier still registers the profile. The clock is then advanced to
    `working_clock` (inside the period) for whatever the caller does next.

    Returns (jurisdiction, seller, profile) with profile.nexus_status REGISTERED."""
    jur, seller, profile = setup_ca_seller_with_profile()
    set_clock(threshold_clock)
    settle_one_full_line(seller["id"], jur["id"], big_unit_price, customer_ref="big")
    reg = api_client.register_nexus_profile(profile["id"], make_seller_headers(seller["id"]))
    profile = get_success_data(reg)
    set_clock(working_clock)
    return jur, seller, profile


# ─── Tier 5: exemption certificates ────────────────────────────────────────

def create_certificate(seller_id, jurisdiction_id, customer_ref="b1",
                       exempt_category_code="TANGIBLE",
                       valid_from="2026-01-01T00:00:00Z",
                       valid_to="2027-01-01T00:00:00Z"):
    res = api_client.create_exemption_certificate(
        create_exemption_certificate_payload(
            seller_id, jurisdiction_id, customer_ref, exempt_category_code,
            valid_from, valid_to),
        make_seller_headers(seller_id))
    return get_success_data(res)


def revoke_certificate(seller_id, certificate_id):
    res = api_client.revoke_exemption_certificate(certificate_id, make_seller_headers(seller_id))
    return get_success_data(res)


# ─── Tier 6: use-tax accrual ───────────────────────────────────────────────

def create_use_tax_accrual(seller_id, jurisdiction_id, purchase_amount=1200.00):
    res = api_client.create_use_tax_accrual(
        create_use_tax_accrual_payload(seller_id, jurisdiction_id, purchase_amount),
        make_seller_headers(seller_id))
    return get_success_data(res)


# ─── Tier 7: tax-return lifecycle ──────────────────────────────────────────

def create_draft_return(seller_id, jurisdiction_id,
                        period_start="2026-02-01T00:00:00Z",
                        period_end="2026-03-01T00:00:00Z",
                        preparer_id="preparer-1"):
    """Create a DRAFT TaxReturn prepared by the given TaxPreparer."""
    res = api_client.create_tax_return(
        create_tax_return_payload(seller_id, jurisdiction_id, period_start, period_end),
        make_preparer_headers(preparer_id))
    return get_success_data(res)


def accept_return(return_id, approver_id="approver-1"):
    res = api_client.accept_tax_return(return_id, make_approver_headers(approver_id))
    return get_success_data(res)


def file_return(return_id, approver_id="approver-1"):
    res = api_client.file_tax_return(return_id, make_approver_headers(approver_id))
    return get_success_data(res)


def setup_filed_return_ca(small_unit_price=10.00, period_start="2026-02-01T00:00:00Z",
                          period_end="2026-03-01T00:00:00Z", clock="2026-02-15T00:00:00Z"):
    """Full chain to a FILED CA return for one seller.

    Sets the clock, registers the seller (via a large settle), settles one
    additional small SELLER transaction in the period, drafts/accepts/files a
    return covering the period.

    Returns a dict with jurisdiction, seller, profile, small_txn, tax_return,
    and filed_version (the return's version after filing, for the OCC field)."""
    set_clock(clock)
    jur, seller, profile = setup_registered_seller_ca()
    small = settle_one_full_line(seller["id"], jur["id"], small_unit_price, customer_ref="small")
    ret = create_draft_return(seller["id"], jur["id"], period_start, period_end)
    ret = accept_return(ret["id"])
    ret = file_return(ret["id"])
    return {
        "jurisdiction": jur,
        "seller": seller,
        "profile": profile,
        "small_txn": small,
        "tax_return": ret,
        "filed_version": ret["version"],
    }
