"""Payload factories — input fields only, exact PRD field names.

Every factory emits a payload that matches the schema PRD declares for the
corresponding endpoint. Tests pass overrides via kwargs for the specific
field they care about; defaults are PRD-permissible everywhere else.
"""
from typing import Any, Dict, List, Optional


# --- RightsHolder ---

def create_rights_holder_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.1: legal_name, holder_type, contact_email, jurisdiction (ISO 3166-1 alpha-2)."""
    p = {
        "legal_name": "Test Rights Holder",
        "holder_type": "INDIVIDUAL",
        "contact_email": "rh@example.com",
        "jurisdiction": "US",
    }
    p.update(overrides)
    return p


# --- Work ---

def create_work_payload(*, primary_owner_id: str,
                        co_owners: Optional[List[Dict[str, Any]]] = None,
                        primary_share_bps: int = 10000,
                        ownership_proof_doc_id: str = "doc-test-1",
                        title: str = "Test Work",
                        work_type: str = "LITERARY",
                        creation_date: str = "2024-01-01T00:00:00.000Z",
                        **overrides) -> Dict[str, Any]:
    """PRD §3.1: title, work_type, creation_date, primary_owner_id, co_owners,
    primary_share_bps, ownership_proof_doc_id."""
    p = {
        "title": title,
        "work_type": work_type,
        "creation_date": creation_date,
        "primary_owner_id": primary_owner_id,
        "co_owners": co_owners if co_owners is not None else [],
        "primary_share_bps": primary_share_bps,
        "ownership_proof_doc_id": ownership_proof_doc_id,
    }
    p.update(overrides)
    return p


def patch_work_payload(**fields) -> Dict[str, Any]:
    """PRD §3.1 patch: title?, co_owners?, primary_share_bps?, ownership_proof_doc_id?, version."""
    return dict(fields)


# --- License ---

def create_license_payload(*, work_id: str, licensor_id: str, licensee_id: str,
                           territory: Optional[List[str]] = None,
                           term_start: str = "2099-01-01T00:00:00.000Z",
                           term_end: str = "2099-12-31T00:00:00.000Z",
                           media_types: Optional[List[str]] = None,
                           exclusivity: str = "NON_EXCLUSIVE",
                           sublicense_allowed: bool = False,
                           revision_rights: str = "NONE",
                           fixed_fee_cents: int = 100_000,
                           revenue_share_bps: int = 1500,
                           minimum_guarantee_cents: int = 0,
                           advance_cents: int = 0,
                           settlement_period: str = "MONTHLY",
                           **overrides) -> Dict[str, Any]:
    """PRD §3.3: License creation payload — full input set."""
    p = {
        "work_id": work_id,
        "licensor_id": licensor_id,
        "licensee_id": licensee_id,
        "territory": territory if territory is not None else ["US"],
        "term_start": term_start,
        "term_end": term_end,
        "media_types": media_types if media_types is not None else ["DIGITAL"],
        "exclusivity": exclusivity,
        "sublicense_allowed": sublicense_allowed,
        "revision_rights": revision_rights,
        "fixed_fee_cents": fixed_fee_cents,
        "revenue_share_bps": revenue_share_bps,
        "minimum_guarantee_cents": minimum_guarantee_cents,
        "advance_cents": advance_cents,
        "settlement_period": settlement_period,
    }
    p.update(overrides)
    return p


def round_payload(*, action: str,
                  clause_diff: Optional[Dict[str, Any]] = None,
                  version: Optional[int] = None) -> Dict[str, Any]:
    """PRD §3.3: NegotiationRound submission — action, clause_diff?, version?."""
    p: Dict[str, Any] = {"action": action}
    if clause_diff is not None:
        p["clause_diff"] = clause_diff
    if version is not None:
        p["version"] = version
    return p


# --- Contract ---

def create_contract_payload(*, license_id: str, signing_order: List[str],
                            effective_date_target: str,
                            parent_contract_id: Optional[str] = None,
                            **overrides) -> Dict[str, Any]:
    """PRD §3.5: license_id, signing_order, effective_date_target, parent_contract_id?."""
    p: Dict[str, Any] = {
        "license_id": license_id,
        "signing_order": signing_order,
        "effective_date_target": effective_date_target,
    }
    if parent_contract_id is not None:
        p["parent_contract_id"] = parent_contract_id
    p.update(overrides)
    return p


def signature_payload(*, signer_id: str,
                      signature_payload: str = "sig-blob-base64",
                      version: Optional[int] = None) -> Dict[str, Any]:
    """PRD §3.5: Signature submission — signer_id, signature_payload, version?."""
    p: Dict[str, Any] = {
        "signer_id": signer_id,
        "signature_payload": signature_payload,
    }
    if version is not None:
        p["version"] = version
    return p


# --- RoyaltyStatement ---

def royalty_statement_payload(*, period_start_at: str, period_end_at: str,
                              gross_revenue_cents: int = 0,
                              variant: str = "FINAL",
                              reversal_of_id: Optional[str] = None,
                              refund_cents: Optional[int] = None,
                              **overrides) -> Dict[str, Any]:
    """PRD §3.7: period_start_at, period_end_at, gross_revenue_cents, variant,
    reversal_of_id?, refund_cents?."""
    p: Dict[str, Any] = {
        "period_start_at": period_start_at,
        "period_end_at": period_end_at,
        "gross_revenue_cents": gross_revenue_cents,
        "variant": variant,
    }
    if reversal_of_id is not None:
        p["reversal_of_id"] = reversal_of_id
    if refund_cents is not None:
        p["refund_cents"] = refund_cents
    p.update(overrides)
    return p


# --- InfringementCase ---

def create_infringement_payload(*, work_id: str, alleged_infringer_id: str,
                                 evidence_doc_ids: Optional[List[str]] = None,
                                 **overrides) -> Dict[str, Any]:
    """PRD §3.8: work_id, alleged_infringer_id, evidence_doc_ids."""
    p = {
        "work_id": work_id,
        "alleged_infringer_id": alleged_infringer_id,
        "evidence_doc_ids": evidence_doc_ids if evidence_doc_ids is not None else ["ev-1"],
    }
    p.update(overrides)
    return p


def respond_payload(*, response_text: str, version: Optional[int] = None) -> Dict[str, Any]:
    p: Dict[str, Any] = {"response_text": response_text}
    if version is not None:
        p["version"] = version
    return p


def resolve_payload(*, compensation_cents: int, version: Optional[int] = None) -> Dict[str, Any]:
    p: Dict[str, Any] = {"compensation_cents": compensation_cents}
    if version is not None:
        p["version"] = version
    return p


# --- ExternalEvent ---

def emit_event_payload(*, source: str, event_type: str, ref_entity: str,
                        ref_id: str, payload: Dict[str, Any],
                        external_event_id: str) -> Dict[str, Any]:
    """PRD §2.11 / §3.2 / §3.7: external event injection payload."""
    return {
        "source": source,
        "event_type": event_type,
        "ref_entity": ref_entity,
        "ref_id": ref_id,
        "payload": payload,
        "external_event_id": external_event_id,
    }
