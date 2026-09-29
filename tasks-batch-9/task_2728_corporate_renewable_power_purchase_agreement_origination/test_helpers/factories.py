"""Payload factories.

Every builder emits only the fields the PRD declares as input for that
endpoint, with the required ones always present and the optional ones omitted
unless a caller overrides them — so that a test which wants to exercise a
declared default can simply leave the field out.  Money is emitted as a JSON
number, never as a string.
"""

from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


def clock_payload(current_utc: str) -> Dict[str, Any]:
    return {"current_utc": current_utc}


# ---------------------------------------------------------------------------
# Pricing nodes
# ---------------------------------------------------------------------------


def pricing_node_payload(name: str = "KRAMER JUNCTION 1N",
                         iso: str = "CAISO",
                         settlement_point_type: str = "NODE",
                         **overrides) -> Dict[str, Any]:
    payload = {"name": name, "iso": iso,
               "settlement_point_type": settlement_point_type}
    payload.update(overrides)
    return payload


def hub_payload(name: str = "SP15 EZ GEN HUB", iso: str = "CAISO",
                **overrides) -> Dict[str, Any]:
    return pricing_node_payload(name=name, iso=iso,
                                settlement_point_type="HUB", **overrides)


# ---------------------------------------------------------------------------
# Offtakers
#
# The anchor buyer used throughout: an A-rated retailer with full disclosure,
# a science-based target, RE100 membership and a 2030 near-term year.  Its
# credit score is 0.55 x 84 + 0.30 x 75 + 0.15 x 100 = 83.70, tier PRIME, and
# its unsecured limit is min(25,000,000.00, 60,000,000.00 x 0.05).
# ---------------------------------------------------------------------------


def offtaker_payload(legal_name: str = "Northwind Retail Inc",
                     credit_rating: str = "A",
                     rating_agency: str = "SP",
                     reported_ebitda_usd: float = 60000000.00,
                     net_debt_to_ebitda: float = 2.5,
                     disclosure_framework: str = "CDP_AND_TCFD",
                     **overrides) -> Dict[str, Any]:
    """The six required buyer inputs, with optionals left to their defaults."""
    payload: Dict[str, Any] = {
        "legal_name": legal_name,
        "credit_rating": credit_rating,
        "rating_agency": rating_agency,
        "reported_ebitda_usd": reported_ebitda_usd,
        "net_debt_to_ebitda": net_debt_to_ebitda,
        "disclosure_framework": disclosure_framework,
    }
    payload.update(overrides)
    return payload


def anchor_offtaker_payload(**overrides) -> Dict[str, Any]:
    """The fully sustainable anchor buyer: score 83.70, sustainability 100.00."""
    payload = offtaker_payload(
        has_science_based_target=True,
        re100_member=True,
        scope2_target_year=2030,
        registry_account_id="WREGIS-ACC-00417",
    )
    payload.update(overrides)
    return payload


def submit_qualification_payload() -> Dict[str, Any]:
    """Submitting for review takes no body of its own."""
    return {}


def qualification_decision_payload(decision: str,
                                   conditions: Optional[list] = None,
                                   **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if conditions is not None:
        payload["conditions"] = conditions
    payload.update(overrides)
    return payload


def rating_change_payload(credit_rating: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"credit_rating": credit_rating}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


def project_payload(node_id: str,
                    name: str = "Kramer Junction Solar I",
                    technology: str = "SOLAR",
                    capacity_mw: float = 100.000,
                    cod_target_date: str = "2029-06-30T00:00:00Z",
                    p50_annual_mwh: float = 245280.00,
                    **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "technology": technology,
        "capacity_mw": capacity_mw,
        "node_id": node_id,
        "cod_target_date": cod_target_date,
        "p50_annual_mwh": p50_annual_mwh,
    }
    payload.update(overrides)
    return payload


def advance_milestone_payload(milestone: Optional[str] = None,
                             evidence_ref: Optional[str] = None,
                             **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if milestone is not None:
        payload["milestone"] = milestone
    if evidence_ref is not None:
        payload["evidence_ref"] = evidence_ref
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Deals
#
# The baseline agreement: 25.000 MW off a solar project at a 22.00 base with
# no escalation and shared basis, so the escalated base is 22.0000, the price
# tier is LOW and the contract price is 22.75.
# ---------------------------------------------------------------------------


def deal_payload(project_id: str, anchor_offtaker_id: str,
                 settlement_point_id: str,
                 product_type: str = "PHYSICAL_DELIVERY",
                 contracted_mw: float = 25.000,
                 term_years: int = 10,
                 first_delivery_year: int = 2026,
                 commercial_operation_deadline: str = "2029-12-31T00:00:00Z",
                 settlement_frequency: str = "HOURLY",
                 base_fixed_price_usd_per_mwh: float = 22.00,
                 escalation_pct_per_year: float = 0.0,
                 shape_product: str = "AS_GENERATED",
                 basis_responsibility: str = "SHARED",
                 **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "project_id": project_id,
        "anchor_offtaker_id": anchor_offtaker_id,
        "settlement_point_id": settlement_point_id,
        "product_type": product_type,
        "contracted_mw": contracted_mw,
        "term_years": term_years,
        "first_delivery_year": first_delivery_year,
        "commercial_operation_deadline": commercial_operation_deadline,
        "settlement_frequency": settlement_frequency,
        "base_fixed_price_usd_per_mwh": base_fixed_price_usd_per_mwh,
        "escalation_pct_per_year": escalation_pct_per_year,
        "shape_product": shape_product,
        "basis_responsibility": basis_responsibility,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Term sheet rounds
# ---------------------------------------------------------------------------


def round_payload(response_deadline: str = "2026-08-15T00:00:00Z",
                  proposed_fixed_price_usd_per_mwh: float = 22.00,
                  proposed_escalation_pct_per_year: float = 0.0,
                  proposed_shape_product: str = "AS_GENERATED",
                  proposed_basis_responsibility: str = "SHARED",
                  proposed_by: str = "DEVELOPER",
                  **overrides) -> Dict[str, Any]:
    """`proposed_by` "must be `DEVELOPER` on this path"."""
    payload: Dict[str, Any] = {
        "proposed_by": proposed_by,
        "proposed_fixed_price_usd_per_mwh": proposed_fixed_price_usd_per_mwh,
        "proposed_escalation_pct_per_year": proposed_escalation_pct_per_year,
        "proposed_shape_product": proposed_shape_product,
        "proposed_basis_responsibility": proposed_basis_responsibility,
        "response_deadline": response_deadline,
    }
    payload.update(overrides)
    return payload


def round_response_payload(response: str, **overrides) -> Dict[str, Any]:
    """`ACCEPT` takes no terms; `COUNTER` optionally supplies counter terms."""
    payload: Dict[str, Any] = {"response": response}
    payload.update(overrides)
    return payload


def counter_terms(counter_fixed_price_usd_per_mwh: float,
                  counter_escalation_pct_per_year: float = 0.0,
                  counter_shape_product: str = "AS_GENERATED",
                  counter_basis_responsibility: str = "SHARED"
                  ) -> Dict[str, Any]:
    """The four counter terms a `COUNTER` carries onto its successor round."""
    return {
        "counter_fixed_price_usd_per_mwh": counter_fixed_price_usd_per_mwh,
        "counter_escalation_pct_per_year": counter_escalation_pct_per_year,
        "counter_shape_product": counter_shape_product,
        "counter_basis_responsibility": counter_basis_responsibility,
    }


# ---------------------------------------------------------------------------
# Allocations
# ---------------------------------------------------------------------------


def allocation_payload(offtaker_id: str, allocated_mw: float,
                       expected_deal_version: int,
                       **overrides) -> Dict[str, Any]:
    """`deal_id` is taken from the path rather than the payload."""
    payload: Dict[str, Any] = {
        "offtaker_id": offtaker_id,
        "allocated_mw": allocated_mw,
        "expected_deal_version": expected_deal_version,
    }
    payload.update(overrides)
    return payload


def allocation_decision_payload(decision: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Credit
# ---------------------------------------------------------------------------


def credit_decision_payload(decision: str,
                            decision_note: str = "Underwriting complete.",
                            **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision,
                               "decision_note": decision_note}
    payload.update(overrides)
    return payload


def letter_of_credit_payload(face_amount_usd: float,
                            issuer_name: str = "First Pacific Bank",
                            issuer_rating: str = "A",
                            purpose: str = "PERFORMANCE_SECURITY",
                            effective_date: str = "2026-08-01T00:00:00Z",
                            expiry_date: str = "2029-08-01T00:00:00Z",
                            **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "instrument_type": "LETTER_OF_CREDIT",
        "purpose": purpose,
        "face_amount_usd": face_amount_usd,
        "issuer_name": issuer_name,
        "issuer_rating": issuer_rating,
        "effective_date": effective_date,
        "expiry_date": expiry_date,
    }
    payload.update(overrides)
    return payload


def parent_guarantee_payload(face_amount_usd: float,
                            guarantor_offtaker_id: str,
                            issuer_name: str = "Guarantor Parent Co",
                            purpose: str = "PERFORMANCE_SECURITY",
                            effective_date: str = "2026-08-01T00:00:00Z",
                            expiry_date: str = "2029-08-01T00:00:00Z",
                            **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "instrument_type": "PARENT_GUARANTEE",
        "purpose": purpose,
        "face_amount_usd": face_amount_usd,
        "issuer_name": issuer_name,
        "guarantor_offtaker_id": guarantor_offtaker_id,
        "effective_date": effective_date,
        "expiry_date": expiry_date,
    }
    payload.update(overrides)
    return payload


def cash_collateral_payload(face_amount_usd: float,
                           purpose: str = "PERFORMANCE_SECURITY",
                           effective_date: str = "2026-08-01T00:00:00Z",
                           expiry_date: str = "2029-08-01T00:00:00Z",
                           issuer_name: str = "Escrow Agent LLC",
                           **overrides) -> Dict[str, Any]:
    """Cash collateral "consults neither" the issuer nor the guarantor limb."""
    payload: Dict[str, Any] = {
        "instrument_type": "CASH_COLLATERAL",
        "purpose": purpose,
        "face_amount_usd": face_amount_usd,
        "issuer_name": issuer_name,
        "effective_date": effective_date,
        "expiry_date": expiry_date,
    }
    payload.update(overrides)
    return payload


def post_credit_support_payload(expected_deal_version: int,
                                **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_deal_version": expected_deal_version}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Conditions precedent and termination
# ---------------------------------------------------------------------------


def cp_resolution_payload(resolution: str,
                          evidence_ref: Optional[str] = None,
                          waiver_justification: Optional[str] = None,
                          **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"resolution": resolution}
    if evidence_ref is not None:
        payload["evidence_ref"] = evidence_ref
    if waiver_justification is not None:
        payload["waiver_justification"] = waiver_justification
    payload.update(overrides)
    return payload


def termination_payload(termination_reason: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"termination_reason": termination_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------


def settlement_period_payload(period_start: str, period_end: str,
                              **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"period_start": period_start,
                               "period_end": period_end}
    payload.update(overrides)
    return payload


def meter_interval_payload(hour_start: str, metered_mwh: float,
                           node_price_usd_per_mwh: float,
                           hub_price_usd_per_mwh: float,
                           expected_settlement_period_version: int,
                           **overrides) -> Dict[str, Any]:
    """`curtailment_flag` is omitted so its declared default `NONE` applies."""
    payload: Dict[str, Any] = {
        "hour_start": hour_start,
        "metered_mwh": metered_mwh,
        "node_price_usd_per_mwh": node_price_usd_per_mwh,
        "hub_price_usd_per_mwh": hub_price_usd_per_mwh,
        "expected_settlement_period_version": expected_settlement_period_version,
    }
    payload.update(overrides)
    return payload


def period_advance_payload(action: str, dispute_reason: Optional[str] = None,
                           **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if dispute_reason is not None:
        payload["dispute_reason"] = dispute_reason
    payload.update(overrides)
    return payload


def mint_attributes_payload(quantity_mwh: int, registry: str = "WREGIS",
                            **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"quantity_mwh": quantity_mwh,
                               "registry": registry}
    payload.update(overrides)
    return payload


def transfer_payload(transferred_to_offtaker_id: str,
                     registry_serial_range: str = "WREGIS-0001-0030",
                     **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "transferred_to_offtaker_id": transferred_to_offtaker_id,
        "registry_serial_range": registry_serial_range,
    }
    payload.update(overrides)
    return payload


def retire_payload(claim_year: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"claim_year": claim_year}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Risk events
# ---------------------------------------------------------------------------


def risk_event_payload(event_type: str, window_start: str, window_end: str,
                       claimed_by: str = "DEVELOPER",
                       description: str = "Claim filed for review.",
                       **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "event_type": event_type,
        "claimed_by": claimed_by,
        "window_start": window_start,
        "window_end": window_end,
        "description": description,
    }
    payload.update(overrides)
    return payload


def risk_review_payload(decision: str,
                        allocation_outcome: Optional[str] = None,
                        price_adjustment_usd_per_mwh: Optional[float] = None,
                        **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if allocation_outcome is not None:
        payload["allocation_outcome"] = allocation_outcome
    if price_adjustment_usd_per_mwh is not None:
        payload["price_adjustment_usd_per_mwh"] = price_adjustment_usd_per_mwh
    payload.update(overrides)
    return payload
