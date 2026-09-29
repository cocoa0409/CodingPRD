"""
Request payload factories.

Each factory returns a fresh, complete, valid payload for one create or action
endpoint, with keyword overrides for the fields a test cares about. Passing
None for an optional field omits it entirely so that server-side defaults are
exercised; to send an explicit null, place it in the payload after the call.

Every monetary value produced here is a Python int, because a field named with
a _cents suffix is a whole number of cents and nothing else.
"""

from typing import Any, Dict, List, Optional

Payload = Dict[str, Any]


def _drop_none(payload: Payload) -> Payload:
    """Remove keys whose value is None so defaults apply server-side."""
    return {k: v for k, v in payload.items() if v is not None}


# ---------------------------------------------------------------------------
# Canonical literals reused across payloads
# ---------------------------------------------------------------------------

DEFAULT_DISCLOSURE_TEMPLATE_VERSION = "DISC-2026.1"
DEFAULT_STATE_CODE = "TX"

WHOLESALER_LEGAL_NAME = "Keystone Property Partners LLC"
SECOND_WHOLESALER_LEGAL_NAME = "Cascade Doorstep Homes LLC"

LEAD_OWNER_NAME = "Dana Ruiz"
LEAD_PROPERTY_ADDRESS = "118 Cedar St, Austin TX"
SECOND_LEAD_OWNER_NAME = "Omar Beck"
SECOND_LEAD_PROPERTY_ADDRESS = "220 Birch Ln, Austin TX"
THIRD_LEAD_OWNER_NAME = "Priya Nandan"
THIRD_LEAD_PROPERTY_ADDRESS = "77 Willow Ct, Austin TX"

CASH_BUYER_LEGAL_NAME = "Ridgeline Capital LLC"
CASH_BUYER_CONTACT_EMAIL = "bids@ridgeline.example"
SECOND_CASH_BUYER_LEGAL_NAME = "Brazos Yield Partners LLC"
SECOND_CASH_BUYER_CONTACT_EMAIL = "desk@brazosyield.example"


# ---------------------------------------------------------------------------
# Wholesaler
# ---------------------------------------------------------------------------


def wholesaler_payload(
    legal_name: str = WHOLESALER_LEGAL_NAME,
    state_code: str = DEFAULT_STATE_CODE,
    disclosure_template_version: str = DEFAULT_DISCLOSURE_TEMPLATE_VERSION,
    licensure_status: Optional[str] = None,
    funding_window_capacity: Optional[int] = None,
) -> Payload:
    """POST /wholesalers — licensure and capacity are optional at registration."""
    return _drop_none(
        {
            "legal_name": legal_name,
            "state_code": state_code,
            "disclosure_template_version": disclosure_template_version,
            "licensure_status": licensure_status,
            "funding_window_capacity": funding_window_capacity,
        }
    )


# ---------------------------------------------------------------------------
# Marketing campaign
# ---------------------------------------------------------------------------


def marketing_campaign_payload(
    wholesaler_id: str,
    channel: str = "DIRECT_MAIL",
    headline: str = "We buy houses fast",
    target_state_code: str = DEFAULT_STATE_CODE,
    discloses_intent_to_assign: Optional[bool] = None,
    discloses_unlicensed_status: Optional[bool] = None,
    dnc_scrubbed: Optional[bool] = None,
) -> Payload:
    """POST /marketing-campaigns — the three disclosure booleans default false."""
    return _drop_none(
        {
            "wholesaler_id": wholesaler_id,
            "channel": channel,
            "headline": headline,
            "target_state_code": target_state_code,
            "discloses_intent_to_assign": discloses_intent_to_assign,
            "discloses_unlicensed_status": discloses_unlicensed_status,
            "dnc_scrubbed": dnc_scrubbed,
        }
    )


# ---------------------------------------------------------------------------
# Seller lead
# ---------------------------------------------------------------------------


def seller_lead_payload(
    wholesaler_id: str,
    owner_name: str = LEAD_OWNER_NAME,
    property_address: str = LEAD_PROPERTY_ADDRESS,
    state_code: str = DEFAULT_STATE_CODE,
    estimated_market_value_cents: int = 30000000,
    recorded_senior_lien_cents: int = 10000000,
    marketing_campaign_id: Optional[str] = None,
    junior_lien_cents: Optional[int] = None,
    delinquent_property_tax_cents: Optional[int] = None,
    distress_flags: Optional[List[str]] = None,
) -> Payload:
    """POST /seller-leads — four inputs are optional."""
    return _drop_none(
        {
            "wholesaler_id": wholesaler_id,
            "owner_name": owner_name,
            "property_address": property_address,
            "state_code": state_code,
            "estimated_market_value_cents": estimated_market_value_cents,
            "recorded_senior_lien_cents": recorded_senior_lien_cents,
            "marketing_campaign_id": marketing_campaign_id,
            "junior_lien_cents": junior_lien_cents,
            "delinquent_property_tax_cents": delinquent_property_tax_cents,
            "distress_flags": distress_flags,
        }
    )


def protection_screen_payload(screening_variant: str = "STATUTORY") -> Payload:
    """POST /seller-leads/{seller_lead_id}/protection-screen"""
    return {"screening_variant": screening_variant}


# ---------------------------------------------------------------------------
# Deal analysis
# ---------------------------------------------------------------------------


def comparable(
    sale_price_cents: int,
    distance_miles: float,
    closed_days_ago: int,
    gla_sqft: int,
    adjustment_cents: int = 0,
) -> Payload:
    """One element of the comparables array."""
    return {
        "sale_price_cents": sale_price_cents,
        "distance_miles": distance_miles,
        "closed_days_ago": closed_days_ago,
        "gla_sqft": gla_sqft,
        "adjustment_cents": adjustment_cents,
    }


def repair_item(code: str, low_cents: int, high_cents: int) -> Payload:
    """One element of the repair_scope_items array."""
    return {"code": code, "low_cents": low_cents, "high_cents": high_cents}


# Three comparables that all qualify against a 1800 sqft subject: each is well
# inside 0.50 miles, 10 days old and exactly on the subject's size.
BASELINE_COMPARABLES: List[Payload] = [
    comparable(30000000, 0.10, 10, 1800, 0),
    comparable(30000000, 0.20, 10, 1800, 0),
    comparable(30000000, 0.30, 10, 1800, 0),
]

BASELINE_REPAIR_ITEMS: List[Payload] = [repair_item("ROOF", 1000000, 1200000)]


def deal_analysis_payload(
    seller_lead_id: str,
    expected_seller_lead_version: int,
    subject_gla_sqft: int = 1800,
    comparables: Optional[List[Payload]] = None,
    repair_scope_items: Optional[List[Payload]] = None,
) -> Payload:
    """POST /deal-analyses — expected_seller_lead_version is non-optional."""
    return {
        "seller_lead_id": seller_lead_id,
        "subject_gla_sqft": subject_gla_sqft,
        "comparables": (
            [dict(c) for c in BASELINE_COMPARABLES]
            if comparables is None
            else [dict(c) for c in comparables]
        ),
        "repair_scope_items": (
            [dict(r) for r in BASELINE_REPAIR_ITEMS]
            if repair_scope_items is None
            else [dict(r) for r in repair_scope_items]
        ),
        "expected_seller_lead_version": expected_seller_lead_version,
    }


def finalize_payload(valuation_variant: str = "AGGRESSIVE") -> Payload:
    """POST /deal-analyses/{deal_analysis_id}/finalize"""
    return {"valuation_variant": valuation_variant}


# ---------------------------------------------------------------------------
# Purchase contract
# ---------------------------------------------------------------------------


def purchase_contract_payload(
    seller_lead_id: str,
    deal_analysis_id: str,
    purchase_price_cents: int = 18000000,
    earnest_money_cents: int = 500000,
    inspection_period_days: int = 7,
    option_start_at: str = "2026-08-01T00:00:00Z",
    closing_window_start_at: str = "2026-09-15T00:00:00Z",
    closing_window_end_at: str = "2026-09-30T00:00:00Z",
    assignment_rights_granted: Optional[bool] = None,
) -> Payload:
    """POST /purchase-contracts — assignment_rights_granted defaults to true."""
    return _drop_none(
        {
            "seller_lead_id": seller_lead_id,
            "deal_analysis_id": deal_analysis_id,
            "purchase_price_cents": purchase_price_cents,
            "earnest_money_cents": earnest_money_cents,
            "inspection_period_days": inspection_period_days,
            "option_start_at": option_start_at,
            "closing_window_start_at": closing_window_start_at,
            "closing_window_end_at": closing_window_end_at,
            "assignment_rights_granted": assignment_rights_granted,
        }
    )


def elect_structure_payload(structure_election: str) -> Payload:
    """POST /purchase-contracts/{purchase_contract_id}/elect-structure"""
    return {"structure_election": structure_election}


def cancel_payload(reason: str = "Title defect discovered during the option period") -> Payload:
    """POST /purchase-contracts/{purchase_contract_id}/cancel"""
    return {"reason": reason}


# ---------------------------------------------------------------------------
# Disclosure acknowledgement
# ---------------------------------------------------------------------------


def disclosure_acknowledgement_payload(
    purchase_contract_id: str,
    disclosure_template_version: str = DEFAULT_DISCLOSURE_TEMPLATE_VERSION,
    acknowledged_intent_to_assign: bool = True,
    acknowledged_unlicensed_status: bool = True,
    signature_ref: str = "esig-dana-001",
) -> Payload:
    """POST /disclosure-acknowledgements"""
    return {
        "purchase_contract_id": purchase_contract_id,
        "disclosure_template_version": disclosure_template_version,
        "acknowledged_intent_to_assign": acknowledged_intent_to_assign,
        "acknowledged_unlicensed_status": acknowledged_unlicensed_status,
        "signature_ref": signature_ref,
    }


# ---------------------------------------------------------------------------
# Earnest money deposit
# ---------------------------------------------------------------------------


def forfeit_payload(
    forfeiture_reason: str = "Buyer failed to close after the option period expired",
) -> Payload:
    """POST /earnest-money-deposits/{earnest_money_deposit_id}/forfeit"""
    return {"forfeiture_reason": forfeiture_reason}


# ---------------------------------------------------------------------------
# Cash buyer and proof of funds
# ---------------------------------------------------------------------------


def cash_buyer_payload(
    wholesaler_id: str,
    legal_name: str = CASH_BUYER_LEGAL_NAME,
    contact_email: str = CASH_BUYER_CONTACT_EMAIL,
) -> Payload:
    """POST /cash-buyers"""
    return {
        "wholesaler_id": wholesaler_id,
        "legal_name": legal_name,
        "contact_email": contact_email,
    }


def proof_of_funds_payload(
    cash_buyer_id: str,
    stated_funds_cents: int = 25500000,
    document_ref: str = "pof-ridgeline-001",
    expires_at: str = "2026-12-01T00:00:00Z",
) -> Payload:
    """POST /proof-of-funds"""
    return {
        "cash_buyer_id": cash_buyer_id,
        "stated_funds_cents": stated_funds_cents,
        "document_ref": document_ref,
        "expires_at": expires_at,
    }


def verify_proof_of_funds_payload(
    verification_decision: str = "VERIFIED",
    verified_funds_cents: Optional[int] = None,
    verification_note: Optional[str] = None,
) -> Payload:
    """POST /proof-of-funds/{proof_of_funds_id}/verify"""
    return _drop_none(
        {
            "verification_decision": verification_decision,
            "verified_funds_cents": verified_funds_cents,
            "verification_note": verification_note,
        }
    )


# ---------------------------------------------------------------------------
# Assignment offer
# ---------------------------------------------------------------------------


def assignment_offer_payload(
    purchase_contract_id: str,
    cash_buyer_id: str,
    buyer_price_cents: int,
    expected_purchase_contract_version: int,
    buyer_deposit_cents: int = 1000000,
    supersedes_offer_id: Optional[str] = None,
) -> Payload:
    """POST /assignment-offers — expected_purchase_contract_version is required."""
    return _drop_none(
        {
            "purchase_contract_id": purchase_contract_id,
            "cash_buyer_id": cash_buyer_id,
            "buyer_price_cents": buyer_price_cents,
            "buyer_deposit_cents": buyer_deposit_cents,
            "expected_purchase_contract_version": expected_purchase_contract_version,
            "supersedes_offer_id": supersedes_offer_id,
        }
    )


def counter_payload(countered_price_cents: int) -> Payload:
    """POST /assignment-offers/{assignment_offer_id}/counter"""
    return {"countered_price_cents": countered_price_cents}


def revise_payload(buyer_price_cents: int, buyer_deposit_cents: int) -> Payload:
    """POST /assignment-offers/{assignment_offer_id}/revise"""
    return {
        "buyer_price_cents": buyer_price_cents,
        "buyer_deposit_cents": buyer_deposit_cents,
    }


# ---------------------------------------------------------------------------
# Assignment agreement
# ---------------------------------------------------------------------------


def assignment_agreement_payload(
    assignment_offer_id: str, structure: str = "ASSIGNMENT"
) -> Payload:
    """POST /assignment-agreements"""
    return {"assignment_offer_id": assignment_offer_id, "structure": structure}


def settle_payload(settlement_reference: str = "STL-2026-000117") -> Payload:
    """POST /assignment-agreements/{assignment_agreement_id}/settle"""
    return {"settlement_reference": settlement_reference}


# ---------------------------------------------------------------------------
# Title order
# ---------------------------------------------------------------------------


def title_order_payload(
    purchase_contract_id: str,
    funding_window_start_at: str = "2026-09-15T00:00:00Z",
    funding_window_end_at: str = "2026-09-16T00:00:00Z",
    title_company_name: str = "Lone Star Title Co",
    escrow_officer_ref: str = "eo-marisol-vega",
) -> Payload:
    """POST /title-orders — structure is copied from the contract, never sent."""
    return {
        "purchase_contract_id": purchase_contract_id,
        "title_company_name": title_company_name,
        "escrow_officer_ref": escrow_officer_ref,
        "funding_window_start_at": funding_window_start_at,
        "funding_window_end_at": funding_window_end_at,
    }


# ---------------------------------------------------------------------------
# Compliance review
# ---------------------------------------------------------------------------


def compliance_review_payload(
    wholesaler_id: str,
    review_type: str = "MARKETING_COMPLIANCE",
    allegation_note: str = "Bandit signs omit the intent-to-assign disclosure.",
    subject_seller_lead_id: Optional[str] = None,
) -> Payload:
    """POST /compliance-reviews — opened_by_user_id comes from the header."""
    return _drop_none(
        {
            "wholesaler_id": wholesaler_id,
            "review_type": review_type,
            "allegation_note": allegation_note,
            "subject_seller_lead_id": subject_seller_lead_id,
        }
    )


def adjudicate_review_payload(
    decision: str,
    finding: str,
    rationale: str = "Signage was corrected before the audit window closed.",
) -> Payload:
    """POST /compliance-reviews/{compliance_review_id}/adjudicate"""
    return {"decision": decision, "finding": finding, "rationale": rationale}


# ---------------------------------------------------------------------------
# Dispute case
# ---------------------------------------------------------------------------


def dispute_case_payload(
    purchase_contract_id: str,
    dispute_basis: str = "EARNEST_MONEY_FORFEITURE",
    claimed_amount_cents: int = 500000,
) -> Payload:
    """POST /dispute-cases"""
    return {
        "purchase_contract_id": purchase_contract_id,
        "dispute_basis": dispute_basis,
        "claimed_amount_cents": claimed_amount_cents,
    }


def submit_evidence_payload(evidence_ref: str) -> Payload:
    """POST /dispute-cases/{dispute_case_id}/submit-evidence"""
    return {"evidence_ref": evidence_ref}


def adjudicate_dispute_payload(
    award: str,
    rationale: str = "Both parties bear partial fault for the failed close",
) -> Payload:
    """POST /dispute-cases/{dispute_case_id}/adjudicate"""
    return {"award": award, "rationale": rationale}
