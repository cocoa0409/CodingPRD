"""
Composite setup helpers.

Every test runs against an empty database, so each scenario is built from
scratch through the API's own endpoints. The helpers are layered: the tier-one
primitives wrap a single call each, and the higher tiers compose them into the
recurring shapes a deal passes through — a registered desk, a screened lead, an
underwritten lead, a signed contract, a marketed contract, an accepted offer and
an executed agreement.

Setup calls use the lenient success validator so that a broken precondition
reports where the setup failed rather than surfacing as an opaque assertion in
the body of a test.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    PLATFORM_ADMIN,
    TITLE_AGENT_1,
    TITLE_AGENT_2,
    make_cash_buyer_headers,
    make_compliance_officer_headers,
    make_seller_headers,
    make_wholesaler_headers,
)

Record = Dict[str, Any]


# ---------------------------------------------------------------------------
# Tier one: one call each
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, to_iso8601: str) -> Record:
    """Drive the logical clock; only a platform administrator may do so."""
    return get_success_data(api.set_clock(to_iso8601, PLATFORM_ADMIN))


def register_wholesaler(api: ApiClient, **kwargs: Any) -> Record:
    """POST /wholesalers as PlatformAdmin."""
    return get_success_data(
        api.create_wholesaler(f.wholesaler_payload(**kwargs), PLATFORM_ADMIN)
    )


def draft_campaign(api: ApiClient, wholesaler_id: str, **kwargs: Any) -> Record:
    """POST /marketing-campaigns as the owning wholesaler."""
    return get_success_data(
        api.create_marketing_campaign(
            f.marketing_campaign_payload(wholesaler_id, **kwargs),
            make_wholesaler_headers(wholesaler_id),
        )
    )


def publish_campaign(api: ApiClient, campaign_id: str, wholesaler_id: str) -> Record:
    """POST /marketing-campaigns/{id}/publish as the owning wholesaler."""
    return get_success_data(
        api.publish_marketing_campaign(
            campaign_id, make_wholesaler_headers(wholesaler_id)
        )
    )


def archive_campaign(api: ApiClient, campaign_id: str, wholesaler_id: str) -> Record:
    """POST /marketing-campaigns/{id}/archive as the owning wholesaler."""
    return get_success_data(
        api.archive_marketing_campaign(
            campaign_id, make_wholesaler_headers(wholesaler_id)
        )
    )


def record_lead(api: ApiClient, wholesaler_id: str, **kwargs: Any) -> Record:
    """POST /seller-leads as the owning wholesaler."""
    return get_success_data(
        api.create_seller_lead(
            f.seller_lead_payload(wholesaler_id, **kwargs),
            make_wholesaler_headers(wholesaler_id),
        )
    )


def screen_lead(
    api: ApiClient,
    seller_lead_id: str,
    wholesaler_id: str,
    screening_variant: str = "STATUTORY",
) -> Record:
    """POST /seller-leads/{id}/protection-screen as the owning wholesaler."""
    return get_success_data(
        api.protection_screen(
            seller_lead_id,
            f.protection_screen_payload(screening_variant),
            make_wholesaler_headers(wholesaler_id),
        )
    )


def underwrite(
    api: ApiClient,
    seller_lead_id: str,
    wholesaler_id: str,
    expected_seller_lead_version: int,
    **kwargs: Any,
) -> Record:
    """POST /deal-analyses as the owning wholesaler."""
    return get_success_data(
        api.create_deal_analysis(
            f.deal_analysis_payload(
                seller_lead_id, expected_seller_lead_version, **kwargs
            ),
            make_wholesaler_headers(wholesaler_id),
        )
    )


def finalize(
    api: ApiClient,
    deal_analysis_id: str,
    wholesaler_id: str,
    valuation_variant: str = "AGGRESSIVE",
) -> Record:
    """POST /deal-analyses/{id}/finalize as the owning wholesaler."""
    return get_success_data(
        api.finalize_deal_analysis(
            deal_analysis_id,
            f.finalize_payload(valuation_variant),
            make_wholesaler_headers(wholesaler_id),
        )
    )


def open_contract(
    api: ApiClient,
    seller_lead_id: str,
    deal_analysis_id: str,
    wholesaler_id: str,
    **kwargs: Any,
) -> Record:
    """POST /purchase-contracts as the owning wholesaler."""
    return get_success_data(
        api.create_purchase_contract(
            f.purchase_contract_payload(seller_lead_id, deal_analysis_id, **kwargs),
            make_wholesaler_headers(wholesaler_id),
        )
    )


def acknowledge_disclosures(
    api: ApiClient, purchase_contract_id: str, seller_lead_id: str, **kwargs: Any
) -> Record:
    """POST /disclosure-acknowledgements as the acting seller."""
    return get_success_data(
        api.create_disclosure_acknowledgement(
            f.disclosure_acknowledgement_payload(purchase_contract_id, **kwargs),
            make_seller_headers(seller_lead_id),
        )
    )


def sign(api: ApiClient, purchase_contract_id: str, seller_lead_id: str) -> Record:
    """POST /purchase-contracts/{id}/sign as the acting seller."""
    return get_success_data(
        api.sign_purchase_contract(
            purchase_contract_id, make_seller_headers(seller_lead_id)
        )
    )


def elect(
    api: ApiClient,
    purchase_contract_id: str,
    wholesaler_id: str,
    structure_election: str,
) -> Record:
    """POST /purchase-contracts/{id}/elect-structure as the owning wholesaler."""
    return get_success_data(
        api.elect_structure(
            purchase_contract_id,
            f.elect_structure_payload(structure_election),
            make_wholesaler_headers(wholesaler_id),
        )
    )


def add_buyer(api: ApiClient, wholesaler_id: str, **kwargs: Any) -> Record:
    """POST /cash-buyers as the owning wholesaler."""
    return get_success_data(
        api.create_cash_buyer(
            f.cash_buyer_payload(wholesaler_id, **kwargs),
            make_wholesaler_headers(wholesaler_id),
        )
    )


def upload_proof_of_funds(api: ApiClient, cash_buyer_id: str, **kwargs: Any) -> Record:
    """POST /proof-of-funds as the acting buyer."""
    return get_success_data(
        api.create_proof_of_funds(
            f.proof_of_funds_payload(cash_buyer_id, **kwargs),
            make_cash_buyer_headers(cash_buyer_id),
        )
    )


def verify_proof_of_funds(
    api: ApiClient, proof_of_funds_id: str, wholesaler_id: str, **kwargs: Any
) -> Record:
    """POST /proof-of-funds/{id}/verify as the owning wholesaler."""
    return get_success_data(
        api.verify_proof_of_funds(
            proof_of_funds_id,
            f.verify_proof_of_funds_payload(**kwargs),
            make_wholesaler_headers(wholesaler_id),
        )
    )


def submit_offer(
    api: ApiClient,
    purchase_contract_id: str,
    cash_buyer_id: str,
    buyer_price_cents: int,
    expected_purchase_contract_version: int,
    **kwargs: Any,
) -> Record:
    """POST /assignment-offers as the acting buyer."""
    return get_success_data(
        api.create_assignment_offer(
            f.assignment_offer_payload(
                purchase_contract_id,
                cash_buyer_id,
                buyer_price_cents,
                expected_purchase_contract_version,
                **kwargs,
            ),
            make_cash_buyer_headers(cash_buyer_id),
        )
    )


def counter_offer(
    api: ApiClient, offer_id: str, wholesaler_id: str, countered_price_cents: int
) -> Record:
    """POST /assignment-offers/{id}/counter as the owning wholesaler."""
    return get_success_data(
        api.counter_assignment_offer(
            offer_id,
            f.counter_payload(countered_price_cents),
            make_wholesaler_headers(wholesaler_id),
        )
    )


def revise_offer(
    api: ApiClient,
    offer_id: str,
    cash_buyer_id: str,
    buyer_price_cents: int,
    buyer_deposit_cents: int,
) -> Record:
    """POST /assignment-offers/{id}/revise as the acting buyer."""
    return get_success_data(
        api.revise_assignment_offer(
            offer_id,
            f.revise_payload(buyer_price_cents, buyer_deposit_cents),
            make_cash_buyer_headers(cash_buyer_id),
        )
    )


def accept_offer(api: ApiClient, offer_id: str, wholesaler_id: str) -> Record:
    """POST /assignment-offers/{id}/accept as the owning wholesaler."""
    return get_success_data(
        api.accept_assignment_offer(offer_id, make_wholesaler_headers(wholesaler_id))
    )


def execute_agreement(
    api: ApiClient, offer_id: str, wholesaler_id: str, structure: str = "ASSIGNMENT"
) -> Record:
    """POST /assignment-agreements as the owning wholesaler."""
    return get_success_data(
        api.create_assignment_agreement(
            f.assignment_agreement_payload(offer_id, structure),
            make_wholesaler_headers(wholesaler_id),
        )
    )


def settle_agreement(
    api: ApiClient,
    agreement_id: str,
    headers: Optional[Dict[str, str]] = None,
    settlement_reference: str = "STL-2026-000117",
) -> Record:
    """POST /assignment-agreements/{id}/settle as a title agent."""
    return get_success_data(
        api.settle_assignment_agreement(
            agreement_id,
            f.settle_payload(settlement_reference),
            headers or TITLE_AGENT_1,
        )
    )


def open_title_order(
    api: ApiClient, purchase_contract_id: str, wholesaler_id: str, **kwargs: Any
) -> Record:
    """POST /title-orders as the owning wholesaler."""
    return get_success_data(
        api.create_title_order(
            f.title_order_payload(purchase_contract_id, **kwargs),
            make_wholesaler_headers(wholesaler_id),
        )
    )


def clear_title_order(
    api: ApiClient, title_order_id: str, headers: Optional[Dict[str, str]] = None
) -> Record:
    """POST /title-orders/{id}/clear-to-fund as the first title agent."""
    return get_success_data(
        api.clear_to_fund(title_order_id, headers or TITLE_AGENT_1)
    )


def fund_title_order(
    api: ApiClient, title_order_id: str, headers: Optional[Dict[str, str]] = None
) -> Record:
    """POST /title-orders/{id}/fund-and-close as the second title agent."""
    return get_success_data(
        api.fund_and_close(title_order_id, headers or TITLE_AGENT_2)
    )


def forfeit_deposit(
    api: ApiClient,
    deposit_id: str,
    headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Record:
    """POST /earnest-money-deposits/{id}/forfeit as a title agent."""
    return get_success_data(
        api.forfeit_earnest_money_deposit(
            deposit_id, f.forfeit_payload(**kwargs), headers or TITLE_AGENT_1
        )
    )


def open_review(
    api: ApiClient,
    wholesaler_id: str,
    headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Record:
    """POST /compliance-reviews as a compliance officer."""
    return get_success_data(
        api.create_compliance_review(
            f.compliance_review_payload(wholesaler_id, **kwargs),
            headers or make_compliance_officer_headers(),
        )
    )


def adjudicate_review(
    api: ApiClient,
    review_id: str,
    decision: str,
    finding: str,
    headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Record:
    """POST /compliance-reviews/{id}/adjudicate as a second compliance officer."""
    return get_success_data(
        api.adjudicate_compliance_review(
            review_id,
            f.adjudicate_review_payload(decision, finding, **kwargs),
            headers or make_compliance_officer_headers("co-2"),
        )
    )


def open_dispute(
    api: ApiClient, purchase_contract_id: str, seller_lead_id: str, **kwargs: Any
) -> Record:
    """POST /dispute-cases as the acting seller."""
    return get_success_data(
        api.create_dispute_case(
            f.dispute_case_payload(purchase_contract_id, **kwargs),
            make_seller_headers(seller_lead_id),
        )
    )


def file_evidence(
    api: ApiClient, dispute_case_id: str, evidence_ref: str, headers: Dict[str, str]
) -> Record:
    """POST /dispute-cases/{id}/submit-evidence as either party."""
    return get_success_data(
        api.submit_dispute_evidence(
            dispute_case_id, f.submit_evidence_payload(evidence_ref), headers
        )
    )


def adjudicate_dispute(
    api: ApiClient,
    dispute_case_id: str,
    award: str,
    headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Record:
    """POST /dispute-cases/{id}/adjudicate as a compliance officer."""
    return get_success_data(
        api.adjudicate_dispute_case(
            dispute_case_id,
            f.adjudicate_dispute_payload(award, **kwargs),
            headers or make_compliance_officer_headers(),
        )
    )


# ---------------------------------------------------------------------------
# Read-back helpers
# ---------------------------------------------------------------------------


def read_wholesaler(api: ApiClient, wholesaler_id: str) -> Record:
    return get_success_data(
        api.get_wholesaler(wholesaler_id, make_wholesaler_headers(wholesaler_id))
    )


def read_lead(api: ApiClient, seller_lead_id: str, wholesaler_id: str) -> Record:
    return get_success_data(
        api.get_seller_lead(seller_lead_id, make_wholesaler_headers(wholesaler_id))
    )


def read_analysis(api: ApiClient, deal_analysis_id: str, wholesaler_id: str) -> Record:
    return get_success_data(
        api.get_deal_analysis(deal_analysis_id, make_wholesaler_headers(wholesaler_id))
    )


def read_contract(api: ApiClient, contract_id: str, wholesaler_id: str) -> Record:
    return get_success_data(
        api.get_purchase_contract(contract_id, make_wholesaler_headers(wholesaler_id))
    )


def read_buyer(api: ApiClient, cash_buyer_id: str, wholesaler_id: str) -> Record:
    return get_success_data(
        api.get_cash_buyer(cash_buyer_id, make_wholesaler_headers(wholesaler_id))
    )


def read_offer(api: ApiClient, offer_id: str, wholesaler_id: str) -> Record:
    return get_success_data(
        api.get_assignment_offer(offer_id, make_wholesaler_headers(wholesaler_id))
    )


def read_agreement(api: ApiClient, agreement_id: str, wholesaler_id: str) -> Record:
    return get_success_data(
        api.get_assignment_agreement(
            agreement_id, make_wholesaler_headers(wholesaler_id)
        )
    )


def read_title_order(api: ApiClient, title_order_id: str, wholesaler_id: str) -> Record:
    return get_success_data(
        api.get_title_order(title_order_id, make_wholesaler_headers(wholesaler_id))
    )


def read_review(api: ApiClient, review_id: str, wholesaler_id: str) -> Record:
    return get_success_data(
        api.get_compliance_review(review_id, make_wholesaler_headers(wholesaler_id))
    )


def read_dispute(api: ApiClient, dispute_case_id: str, wholesaler_id: str) -> Record:
    return get_success_data(
        api.get_dispute_case(dispute_case_id, make_wholesaler_headers(wholesaler_id))
    )


def read_campaign(api: ApiClient, campaign_id: str, wholesaler_id: str) -> Record:
    return get_success_data(
        api.get_marketing_campaign(campaign_id, make_wholesaler_headers(wholesaler_id))
    )


def find_deposit(api: ApiClient, purchase_contract_id: str, wholesaler_id: str) -> Record:
    """
    The deposit created by the signing cascade is never returned by the signing
    call itself; it is found by listing deposits filtered on
    purchase_contract_id.
    """
    body = get_success_data(
        api.list_earnest_money_deposits(
            make_wholesaler_headers(wholesaler_id),
            {"purchase_contract_id": purchase_contract_id},
        )
    )
    assert isinstance(body, list) and body, (
        f"expected exactly one earnest money deposit for contract "
        f"{purchase_contract_id}, list returned {body!r}"
    )
    return body[0]


def contract_version(api: ApiClient, contract_id: str, wholesaler_id: str) -> int:
    """The contract's current version, for the offer-create concurrency field."""
    return read_contract(api, contract_id, wholesaler_id)["version"]


# ---------------------------------------------------------------------------
# Scenario container
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    """Mutable carrier for the records a layered setup has built so far."""

    api: ApiClient
    wholesaler: Optional[Record] = None
    campaign: Optional[Record] = None
    lead: Optional[Record] = None
    analysis: Optional[Record] = None
    contract: Optional[Record] = None
    acknowledgement: Optional[Record] = None
    deposit: Optional[Record] = None
    buyer: Optional[Record] = None
    proof_of_funds: Optional[Record] = None
    offer: Optional[Record] = None
    agreement: Optional[Record] = None
    title_order: Optional[Record] = None
    extras: Dict[str, Any] = field(default_factory=dict)

    # -- identifiers ----------------------------------------------------

    @property
    def w_id(self) -> str:
        return self.wholesaler["id"]

    @property
    def lead_id(self) -> str:
        return self.lead["id"]

    @property
    def analysis_id(self) -> str:
        return self.analysis["id"]

    @property
    def pc_id(self) -> str:
        return self.contract["id"]

    @property
    def buyer_id(self) -> str:
        return self.buyer["id"]

    @property
    def offer_id(self) -> str:
        return self.offer["id"]

    @property
    def agreement_id(self) -> str:
        return self.agreement["id"]

    @property
    def deposit_id(self) -> str:
        return self.deposit["id"]

    @property
    def title_order_id(self) -> str:
        return self.title_order["id"]

    # -- principals -----------------------------------------------------

    @property
    def w_headers(self) -> Dict[str, str]:
        return make_wholesaler_headers(self.w_id)

    @property
    def seller_headers(self) -> Dict[str, str]:
        return make_seller_headers(self.lead_id)

    @property
    def buyer_headers(self) -> Dict[str, str]:
        return make_cash_buyer_headers(self.buyer_id)

    # -- refreshers -----------------------------------------------------

    def refresh_wholesaler(self) -> Record:
        self.wholesaler = read_wholesaler(self.api, self.w_id)
        return self.wholesaler

    def refresh_lead(self) -> Record:
        self.lead = read_lead(self.api, self.lead_id, self.w_id)
        return self.lead

    def refresh_analysis(self) -> Record:
        self.analysis = read_analysis(self.api, self.analysis_id, self.w_id)
        return self.analysis

    def refresh_contract(self) -> Record:
        self.contract = read_contract(self.api, self.pc_id, self.w_id)
        return self.contract

    def refresh_buyer(self) -> Record:
        self.buyer = read_buyer(self.api, self.buyer_id, self.w_id)
        return self.buyer

    def refresh_offer(self) -> Record:
        self.offer = read_offer(self.api, self.offer_id, self.w_id)
        return self.offer

    def refresh_agreement(self) -> Record:
        self.agreement = read_agreement(self.api, self.agreement_id, self.w_id)
        return self.agreement

    def refresh_title_order(self) -> Record:
        self.title_order = read_title_order(self.api, self.title_order_id, self.w_id)
        return self.title_order

    def refresh_deposit(self) -> Record:
        self.deposit = find_deposit(self.api, self.pc_id, self.w_id)
        return self.deposit

    def refresh_campaign(self) -> Record:
        self.campaign = read_campaign(self.api, self.campaign["id"], self.w_id)
        return self.campaign

    @property
    def pc_version(self) -> int:
        """Re-read the contract and hand back its current version."""
        return self.refresh_contract()["version"]


# ---------------------------------------------------------------------------
# Tier two: a registered desk
# ---------------------------------------------------------------------------


def build_desk(
    api: ApiClient,
    clock: Optional[str] = None,
    **wholesaler_kwargs: Any,
) -> Scenario:
    """Set the clock where asked and register one wholesaling entity."""
    if clock is not None:
        set_clock(api, clock)
    scenario = Scenario(api=api)
    scenario.wholesaler = register_wholesaler(api, **wholesaler_kwargs)
    return scenario


def build_published_campaign(
    api: ApiClient,
    clock: Optional[str] = None,
    channel: str = "DIRECT_MAIL",
    headline: str = "We buy houses fast",
    dnc_scrubbed: Optional[bool] = None,
    **wholesaler_kwargs: Any,
) -> Scenario:
    """A desk with one campaign carrying both disclosures and published."""
    scenario = build_desk(api, clock=clock, **wholesaler_kwargs)
    scenario.campaign = draft_campaign(
        api,
        scenario.w_id,
        channel=channel,
        headline=headline,
        discloses_intent_to_assign=True,
        discloses_unlicensed_status=True,
        dnc_scrubbed=dnc_scrubbed,
    )
    scenario.campaign = publish_campaign(api, scenario.campaign["id"], scenario.w_id)
    return scenario


# ---------------------------------------------------------------------------
# Tier three: a screened, then underwritten lead
# ---------------------------------------------------------------------------


def build_screened_lead(
    api: ApiClient,
    clock: Optional[str] = None,
    screening_variant: str = "STATUTORY",
    lead_kwargs: Optional[Dict[str, Any]] = None,
    **wholesaler_kwargs: Any,
) -> Scenario:
    """A desk with one lead recorded and screened onto a protection tier."""
    scenario = build_desk(api, clock=clock, **wholesaler_kwargs)
    scenario.lead = record_lead(api, scenario.w_id, **(lead_kwargs or {}))
    scenario.lead = screen_lead(
        api, scenario.lead_id, scenario.w_id, screening_variant
    )
    return scenario


def build_underwritten_lead(
    api: ApiClient,
    clock: Optional[str] = None,
    screening_variant: str = "STATUTORY",
    valuation_variant: str = "AGGRESSIVE",
    lead_kwargs: Optional[Dict[str, Any]] = None,
    analysis_kwargs: Optional[Dict[str, Any]] = None,
    **wholesaler_kwargs: Any,
) -> Scenario:
    """A screened lead with one finalized analysis fixing the price ceiling."""
    scenario = build_screened_lead(
        api,
        clock=clock,
        screening_variant=screening_variant,
        lead_kwargs=lead_kwargs,
        **wholesaler_kwargs,
    )
    scenario.analysis = underwrite(
        api,
        scenario.lead_id,
        scenario.w_id,
        scenario.lead["version"],
        **(analysis_kwargs or {}),
    )
    scenario.analysis = finalize(
        api, scenario.analysis_id, scenario.w_id, valuation_variant
    )
    return scenario


# ---------------------------------------------------------------------------
# Tier four: a contract, drafted then signed
# ---------------------------------------------------------------------------


def build_draft_contract(
    api: ApiClient,
    clock: Optional[str] = None,
    screening_variant: str = "STATUTORY",
    valuation_variant: str = "AGGRESSIVE",
    lead_kwargs: Optional[Dict[str, Any]] = None,
    analysis_kwargs: Optional[Dict[str, Any]] = None,
    contract_kwargs: Optional[Dict[str, Any]] = None,
    **wholesaler_kwargs: Any,
) -> Scenario:
    """An underwritten lead put under contract; the contract is still DRAFT."""
    scenario = build_underwritten_lead(
        api,
        clock=clock,
        screening_variant=screening_variant,
        valuation_variant=valuation_variant,
        lead_kwargs=lead_kwargs,
        analysis_kwargs=analysis_kwargs,
        **wholesaler_kwargs,
    )
    kwargs = dict(contract_kwargs or {})
    kwargs.setdefault("option_start_at", clock or "2026-08-01T00:00:00Z")
    scenario.contract = open_contract(
        api, scenario.lead_id, scenario.analysis_id, scenario.w_id, **kwargs
    )
    return scenario


def build_signed_contract(
    api: ApiClient,
    clock: Optional[str] = None,
    acknowledgement_kwargs: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Scenario:
    """
    A drafted contract acknowledged by the seller and signed, which opens the
    inspection period and funds escrow.
    """
    scenario = build_draft_contract(api, clock=clock, **kwargs)
    scenario.acknowledgement = acknowledge_disclosures(
        api, scenario.pc_id, scenario.lead_id, **(acknowledgement_kwargs or {})
    )
    scenario.contract = sign(api, scenario.pc_id, scenario.lead_id)
    scenario.deposit = find_deposit(api, scenario.pc_id, scenario.w_id)
    return scenario


# ---------------------------------------------------------------------------
# Tier five: a marketed contract, an accepted offer, an executed agreement
# ---------------------------------------------------------------------------


def add_verified_buyer(
    scenario: Scenario,
    stated_funds_cents: int = 25500000,
    verified_funds_cents: Optional[int] = None,
    expires_at: str = "2026-12-01T00:00:00Z",
    document_ref: str = "pof-ridgeline-001",
    legal_name: str = f.CASH_BUYER_LEGAL_NAME,
    contact_email: str = f.CASH_BUYER_CONTACT_EMAIL,
) -> Record:
    """Add a cash buyer whose proof of funds is uploaded and then verified."""
    api = scenario.api
    scenario.buyer = add_buyer(
        api, scenario.w_id, legal_name=legal_name, contact_email=contact_email
    )
    scenario.proof_of_funds = upload_proof_of_funds(
        api,
        scenario.buyer_id,
        stated_funds_cents=stated_funds_cents,
        document_ref=document_ref,
        expires_at=expires_at,
    )
    scenario.proof_of_funds = verify_proof_of_funds(
        api,
        scenario.proof_of_funds["id"],
        scenario.w_id,
        verification_decision="VERIFIED",
        verified_funds_cents=(
            stated_funds_cents if verified_funds_cents is None else verified_funds_cents
        ),
    )
    scenario.buyer = read_buyer(api, scenario.buyer_id, scenario.w_id)
    return scenario.buyer


def build_marketed_contract(
    api: ApiClient,
    clock: Optional[str] = None,
    buyer_price_cents: int = 20000000,
    buyer_deposit_cents: int = 1000000,
    structure_election: Optional[str] = "ASSIGNMENT_ELECTED",
    buyer_kwargs: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Scenario:
    """
    A signed contract with an exit structure elected, a verified buyer on the
    list and one live offer, so the contract's assignment_status is MARKETED.
    """
    scenario = build_signed_contract(api, clock=clock, **kwargs)
    if structure_election is not None:
        scenario.contract = elect(api, scenario.pc_id, scenario.w_id, structure_election)
    add_verified_buyer(scenario, **(buyer_kwargs or {}))
    scenario.offer = submit_offer(
        api,
        scenario.pc_id,
        scenario.buyer_id,
        buyer_price_cents,
        scenario.refresh_contract()["version"],
        buyer_deposit_cents=buyer_deposit_cents,
    )
    scenario.refresh_contract()
    return scenario


def build_accepted_offer(api: ApiClient, **kwargs: Any) -> Scenario:
    """A marketed contract whose single offer has been accepted."""
    scenario = build_marketed_contract(api, **kwargs)
    scenario.offer = accept_offer(api, scenario.offer_id, scenario.w_id)
    scenario.refresh_contract()
    return scenario


def build_executed_agreement(
    api: ApiClient, structure: str = "ASSIGNMENT", **kwargs: Any
) -> Scenario:
    """An accepted offer papered into an agreement in PENDING_SETTLEMENT."""
    scenario = build_accepted_offer(api, **kwargs)
    scenario.agreement = execute_agreement(
        api, scenario.offer_id, scenario.w_id, structure
    )
    scenario.refresh_contract()
    scenario.refresh_offer()
    return scenario


# ---------------------------------------------------------------------------
# Convenience collections
# ---------------------------------------------------------------------------


def list_all_offers(api: ApiClient, contract_id: str, wholesaler_id: str) -> List[Record]:
    """Every offer on one contract, for buyer-capital reconciliation checks."""
    return get_success_data(
        api.list_assignment_offers(
            make_wholesaler_headers(wholesaler_id),
            {"purchase_contract_id": contract_id, "limit": 100},
        )
    )
