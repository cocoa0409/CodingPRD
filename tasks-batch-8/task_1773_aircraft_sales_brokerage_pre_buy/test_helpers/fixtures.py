"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. Setup calls use the lenient get_success_data()
validator so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    CANONICAL_COMPS,
    DEFAULT_FACILITY,
    DEFAULT_SLOT_END,
    DEFAULT_SLOT_START,
    DEAL_BUDGET_USD,
    DEAL_CREDIT_USD,
    DEAL_DEPOSIT_USD,
    DEAL_OFFER_USD,
    SMALL_BUDGET_USD,
    SMALL_DEPOSIT_USD,
    SMALL_OFFER_USD,
)
from .factories import (
    counter_discrepancy_payload,
    counter_loi_payload,
    create_buyer_payload,
    create_comparable_sale_payload,
    create_discrepancy_item_payload,
    create_inspection_booking_payload,
    create_inspection_facility_payload,
    create_listing_payload,
    create_loi_payload,
    delivery_conditions_payload,
    disclosure_ack_payload,
    fund_escrow_payload,
    qualify_buyer_payload,
    terminate_transaction_payload,
    valuation_payload,
)
from .test_users import TEST_USERS

BROKER = TEST_USERS["broker_principal_headers"]
LISTING_AGENT = TEST_USERS["listing_agent_headers"]
BUYER_AGENT = TEST_USERS["buyer_agent_headers"]
ESCROW = TEST_USERS["escrow_officer_headers"]
SCHEDULER = TEST_USERS["facility_scheduler_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_facility(name=DEFAULT_FACILITY["name"],
                    airport_code=DEFAULT_FACILITY["airport_code"],
                    turnaround_buffer_minutes=DEFAULT_FACILITY["turnaround_buffer_minutes"]):
    """Register an inspection facility. Returns the facility."""
    payload = create_inspection_facility_payload(
        name=name, airport_code=airport_code,
        turnaround_buffer_minutes=turnaround_buffer_minutes)
    return get_success_data(api_client.create_inspection_facility(payload, BROKER))


def create_comparable_sale(**overrides):
    """Record one comparable sale. Returns the comparable."""
    return get_success_data(
        api_client.create_comparable_sale(create_comparable_sale_payload(**overrides),
                                          LISTING_AGENT))


def setup_canonical_comps():
    """Post the three canonical VERIFIED Gulfstream G550 comparables."""
    return [create_comparable_sale(**comp) for comp in CANONICAL_COMPS]


def create_draft_listing(**overrides):
    """Create a listing (born DRAFT, valuation_status NONE)."""
    return get_success_data(
        api_client.create_listing(create_listing_payload(**overrides), LISTING_AGENT))


def run_valuation(listing_id, variant="FINAL"):
    """Run a valuation of the given variant; returns the updated listing."""
    return get_success_data(
        api_client.run_valuation(listing_id, valuation_payload(variant), LISTING_AGENT))


def setup_active_listing(with_comps=True, **listing_overrides):
    """Comps + listing + FINAL valuation + activate. Returns ACTIVE listing."""
    if with_comps:
        setup_canonical_comps()
    listing = create_draft_listing(**listing_overrides)
    run_valuation(listing["id"], "FINAL")
    return get_success_data(api_client.activate_listing(listing["id"], LISTING_AGENT))


def setup_qualified_buyer(budget=SMALL_BUDGET_USD, **buyer_overrides):
    """Register a buyer and qualify them with the given budget ceiling."""
    buyer = get_success_data(
        api_client.create_buyer(create_buyer_payload(**buyer_overrides), BUYER_AGENT))
    return get_success_data(
        api_client.qualify_buyer(buyer["id"],
                                 qualify_buyer_payload(qualified_budget_usd=budget),
                                 BUYER_AGENT))


def submit_loi(listing_id, buyer_id, offer=SMALL_OFFER_USD, deposit=SMALL_DEPOSIT_USD,
               dual_agency=None):
    """Submit a letter of intent. Returns the LOI (SUBMITTED)."""
    overrides = {"offer_price_usd": offer, "deposit_amount_usd": deposit}
    if dual_agency is not None:
        overrides["dual_agency"] = dual_agency
    return get_success_data(
        api_client.create_loi(create_loi_payload(listing_id, buyer_id, **overrides),
                              BUYER_AGENT))


def acknowledge_disclosure(loi_id, party):
    """Record one party's dual-agency acknowledgment. Returns the LOI."""
    return get_success_data(
        api_client.ack_disclosure(loi_id, disclosure_ack_payload(party), BROKER))


def accept_loi(loi_id):
    """Accept an LOI (ListingAgent). Returns the ACCEPTED LOI."""
    return get_success_data(api_client.accept_loi(loi_id, LISTING_AGENT))


def get_transaction_for_listing(listing_id, status=None):
    """Fetch the single transaction for a listing via the filtered list."""
    params = {"listing_id": listing_id}
    if status is not None:
        params["status"] = status
    rows, _meta = validate_paginated(api_client.list_transactions(LISTING_AGENT, params))
    assert len(rows) == 1, f"expected exactly 1 transaction for listing, got {len(rows)}"
    return rows[0]


def get_escrow_for_transaction(transaction_id):
    """Fetch the single escrow deposit for a transaction via the filtered list."""
    rows, _meta = validate_paginated(
        api_client.list_escrow_deposits(ESCROW, {"transaction_id": transaction_id}))
    assert len(rows) == 1, f"expected exactly 1 escrow deposit, got {len(rows)}"
    return rows[0]


def fund_escrow(escrow_id, funding_reference="WIRE-1"):
    """Record the deposit wire. Returns the FUNDED escrow deposit."""
    return get_success_data(
        api_client.fund_escrow_deposit(escrow_id, fund_escrow_payload(funding_reference),
                                       ESCROW))


def book_inspection(transaction_id, facility_id, start_at=DEFAULT_SLOT_START,
                    end_at=DEFAULT_SLOT_END):
    """Book an inspection slot. Returns the REQUESTED booking."""
    payload = create_inspection_booking_payload(
        transaction_id, facility_id, start_at=start_at, end_at=end_at)
    return get_success_data(api_client.create_inspection_booking(payload, SCHEDULER))


def raise_discrepancy(transaction_id, booking_id, description="Corrosion at MLG trunnion",
                      severity="NON_AIRWORTHINESS", estimated_cost_usd=185000.00):
    """Raise a finding on a transaction. Returns the RAISED item."""
    payload = create_discrepancy_item_payload(
        booking_id, description=description, severity=severity,
        estimated_cost_usd=estimated_cost_usd)
    return get_success_data(
        api_client.raise_discrepancy_item(transaction_id, payload, SCHEDULER))


def counter_discrepancy(item_id, proposed_credit_usd=None, repair_offer_note=None):
    """Seller counters a finding. Returns the COUNTERED item."""
    overrides = {}
    if proposed_credit_usd is not None:
        overrides["proposed_credit_usd"] = proposed_credit_usd
    if repair_offer_note is not None:
        overrides["repair_offer_note"] = repair_offer_note
    return get_success_data(
        api_client.counter_discrepancy_item(item_id, counter_discrepancy_payload(**overrides),
                                            LISTING_AGENT))


def complete_delivery_conditions(transaction_id, tax_planning_notes=None):
    """Set logbook_complete and registration_docs_complete true (OCC-threaded)."""
    tx = get_success_data(api_client.get_transaction(transaction_id, BROKER))
    fields = {"logbook_complete": True, "registration_docs_complete": True}
    if tax_planning_notes is not None:
        fields["tax_planning_notes"] = tax_planning_notes
    return get_success_data(
        api_client.patch_delivery_conditions(
            transaction_id,
            delivery_conditions_payload(tx["version"], **fields),
            BROKER))


# ---------------------------------------------------------------------------
# Tier 2/3: deal pipeline composites
# ---------------------------------------------------------------------------

def setup_accepted_deal(offer=SMALL_OFFER_USD, deposit=SMALL_DEPOSIT_USD,
                        budget=SMALL_BUDGET_USD, dual_agency=False,
                        listing_overrides=None):
    """ACTIVE listing + QUALIFIED buyer + LOI accepted.

    Returns dict with keys: listing, buyer, loi, transaction, escrow.
    For dual_agency deals both disclosure acknowledgments are recorded first.
    """
    listing = setup_active_listing(**(listing_overrides or {}))
    buyer = setup_qualified_buyer(budget=budget)
    loi = submit_loi(listing["id"], buyer["id"], offer=offer, deposit=deposit,
                     dual_agency=dual_agency)
    if dual_agency:
        acknowledge_disclosure(loi["id"], "BUYER")
        acknowledge_disclosure(loi["id"], "SELLER")
    loi = accept_loi(loi["id"])
    transaction = get_transaction_for_listing(listing["id"])
    escrow = get_escrow_for_transaction(transaction["id"])
    return {"listing": listing, "buyer": buyer, "loi": loi,
            "transaction": transaction, "escrow": escrow}


def setup_funded_deal(funding_reference="WIRE-1", **deal_kwargs):
    """Accepted deal with the escrow deposit funded (transaction ESCROW_FUNDED)."""
    deal = setup_accepted_deal(**deal_kwargs)
    deal["escrow"] = fund_escrow(deal["escrow"]["id"], funding_reference)
    deal["transaction"] = get_success_data(
        api_client.get_transaction(deal["transaction"]["id"], BROKER))
    return deal


def setup_deal_with_booking(facility_kwargs=None, start_at=DEFAULT_SLOT_START,
                            end_at=DEFAULT_SLOT_END, **deal_kwargs):
    """Funded deal plus one REQUESTED booking at a freshly registered facility."""
    deal = setup_funded_deal(**deal_kwargs)
    facility = create_facility(**(facility_kwargs or {}))
    booking = book_inspection(deal["transaction"]["id"], facility["id"],
                              start_at=start_at, end_at=end_at)
    deal["facility"] = facility
    deal["booking"] = booking
    return deal


def setup_inspection_scheduled_deal(**kwargs):
    """Deal with one CONFIRMED booking (transaction INSPECTION_SCHEDULED)."""
    deal = setup_deal_with_booking(**kwargs)
    deal["booking"] = get_success_data(
        api_client.confirm_booking(deal["booking"]["id"], SCHEDULER))
    deal["transaction"] = get_success_data(
        api_client.get_transaction(deal["transaction"]["id"], BROKER))
    return deal


def setup_inspection_complete_deal(**kwargs):
    """Deal with one COMPLETED booking (transaction INSPECTION_COMPLETE)."""
    deal = setup_inspection_scheduled_deal(**kwargs)
    deal["booking"] = get_success_data(
        api_client.complete_booking(deal["booking"]["id"], SCHEDULER))
    deal["transaction"] = get_success_data(
        api_client.get_transaction(deal["transaction"]["id"], BROKER))
    return deal


def setup_discrepancy_negotiation_deal(severity="NON_AIRWORTHINESS",
                                       estimated_cost_usd=185000.00, **kwargs):
    """INSPECTION_COMPLETE deal plus one RAISED finding (transaction moves to
    DISCREPANCY_NEGOTIATION)."""
    deal = setup_inspection_complete_deal(**kwargs)
    deal["discrepancy"] = raise_discrepancy(
        deal["transaction"]["id"], deal["booking"]["id"],
        severity=severity, estimated_cost_usd=estimated_cost_usd)
    deal["transaction"] = get_success_data(
        api_client.get_transaction(deal["transaction"]["id"], BROKER))
    return deal


def setup_delivery_pending_deal(credit=None, **deal_kwargs):
    """Deal walked to DELIVERY_PENDING.

    credit=None takes the zero-findings path (buyer accepts as-is);
    credit=<amount> resolves one NON_AIRWORTHINESS finding via the
    counter/agree-credit path so credits_total_usd equals the credit.
    """
    if credit is None:
        deal = setup_inspection_complete_deal(**deal_kwargs)
        deal["transaction"] = get_success_data(
            api_client.accept_as_is(deal["transaction"]["id"], BUYER_AGENT))
        deal["discrepancy"] = None
    else:
        deal = setup_discrepancy_negotiation_deal(**deal_kwargs)
        item = counter_discrepancy(deal["discrepancy"]["id"], proposed_credit_usd=credit)
        deal["discrepancy"] = get_success_data(
            api_client.agree_credit(item["id"], BUYER_AGENT))
        deal["transaction"] = get_success_data(
            api_client.get_transaction(deal["transaction"]["id"], BROKER))
    return deal


def setup_closable_deal(tax_planning_notes=None, **deal_kwargs):
    """DELIVERY_PENDING deal with both delivery conditions complete."""
    deal = setup_delivery_pending_deal(**deal_kwargs)
    deal["transaction"] = complete_delivery_conditions(
        deal["transaction"]["id"], tax_planning_notes=tax_planning_notes)
    return deal


def setup_closed_deal(**deal_kwargs):
    """Full lifecycle through CLOSED. Returns the deal dict (post-close reads)."""
    deal = setup_closable_deal(**deal_kwargs)
    deal["transaction"] = get_success_data(
        api_client.close_transaction(deal["transaction"]["id"], BROKER))
    deal["escrow"] = get_success_data(
        api_client.get_escrow_deposit(deal["escrow"]["id"], ESCROW))
    deal["listing"] = get_success_data(
        api_client.get_listing(deal["listing"]["id"], LISTING_AGENT))
    return deal


# ---------------------------------------------------------------------------
# Tier 4: canonical economics shortcut
# ---------------------------------------------------------------------------

def setup_closable_canonical_deal(dual_agency=False, tax_planning_notes=None):
    """DELIVERY_PENDING deal at the canonical economics: offer 6200000.50,
    deposit 500000.00, one CREDIT resolution of 100000.25, conditions complete.
    Base 6100000.25 straddles the five-million commission tier boundary."""
    return setup_closable_deal(
        offer=DEAL_OFFER_USD, deposit=DEAL_DEPOSIT_USD, budget=DEAL_BUDGET_USD,
        dual_agency=dual_agency, credit=DEAL_CREDIT_USD,
        tax_planning_notes=tax_planning_notes)


def counter_loi(loi_id, new_price_usd, expected_loi_version, as_role=LISTING_AGENT):
    """Counter the in-force LOI price. Returns the updated LOI."""
    return get_success_data(
        api_client.counter_loi(loi_id,
                               counter_loi_payload(new_price_usd, expected_loi_version),
                               as_role))


def terminate_deal(transaction_id, reason="buyer walked during inspection window",
                   as_role=BROKER):
    """Terminate an open transaction. Returns the TERMINATED transaction."""
    return get_success_data(
        api_client.terminate_transaction(transaction_id,
                                         terminate_transaction_payload(reason),
                                         as_role))
