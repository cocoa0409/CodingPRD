"""Payload factories — one per resource, input fields only.

Defaults describe the canonical management-liability file used throughout the
suite: a listed biotech insured whose latest disclosure package carries a
restatement and a single material weakness, and one securities class action
filed inside the three-year full-weight recency band.
"""

# ─── Canonical literals ──────────────────────────────────────────────────────

CANONICAL_INSURED_NAME = "Vantiq Bio Inc"
SECOND_INSURED_NAME = "Harrow Freight Group"
SMALL_INSURED_NAME = "Marrow Pantry Co"


def create_insured_payload(**overrides) -> dict:
    payload = {
        "legal_name": CANONICAL_INSURED_NAME,
        "sector_code": "BIOTECH",
        "exchange_listing": "LISTED",
        "market_cap_usd": 1_800_000_000,
        "fiscal_year_end": "12-31",
        "entity_capacity_cap_usd": 25_000_000,
    }
    payload.update(overrides)
    return payload


def update_insured_payload(expected_insured_version: int, **overrides) -> dict:
    payload = {"expected_insured_version": expected_insured_version}
    payload.update(overrides)
    return payload


def create_disclosure_package_payload(insured_id: str = None, **overrides) -> dict:
    payload = {
        "fiscal_year": 2025,
        "filed_date": "2026-03-01T00:00:00Z",
        "restatement_flag": True,
        "material_weakness_count": 1,
        "going_concern_flag": False,
        "negative_operating_cash_flow_flag": False,
        "debt_to_equity": 1.1,
        "independent_director_ratio": 0.40,
        "dual_class_shares_flag": False,
        "staggered_board_flag": False,
        "combined_ceo_chair_flag": True,
        "auditor_change_flag": False,
    }
    if insured_id is not None:
        payload["insured_id"] = insured_id
    payload.update(overrides)
    return payload


def clean_disclosure_package_payload(insured_id: str = None, **overrides) -> dict:
    """A package on which every underwriting fact scores zero."""
    payload = create_disclosure_package_payload(
        insured_id,
        fiscal_year=2026,
        filed_date="2026-07-15T00:00:00Z",
        restatement_flag=False,
        material_weakness_count=0,
        going_concern_flag=False,
        negative_operating_cash_flow_flag=False,
        debt_to_equity=0.4,
        independent_director_ratio=0.80,
        dual_class_shares_flag=False,
        staggered_board_flag=False,
        combined_ceo_chair_flag=False,
        auditor_change_flag=False,
    )
    payload.update(overrides)
    return payload


def create_litigation_event_payload(insured_id: str = None, **overrides) -> dict:
    payload = {
        "case_type": "SECURITIES_CLASS_ACTION",
        "filed_date": "2024-06-15T00:00:00Z",
        "resolved_date": "2025-01-15T00:00:00Z",
        "indemnity_paid_usd": 4_000_000,
        "outcome": "SETTLED",
    }
    if insured_id is not None:
        payload["insured_id"] = insured_id
    payload.update(overrides)
    # A matter that is still pending carries no resolution date at all, which is
    # what makes it count as open litigation.
    if payload.get("resolved_date", "") is None:
        del payload["resolved_date"]
    return payload


def create_submission_payload(insured_id: str, **overrides) -> dict:
    payload = {
        "insured_id": insured_id,
        "requested_limit_usd": 10_000_000,
        "requested_retention_usd": 250_000,
        "requested_side_c_sublimit_usd": 5_000_000,
        "requested_program_target_limit_usd": 20_000_000,
        "requested_period_start": "2026-09-01T00:00:00Z",
        "requested_period_end": "2027-09-01T00:00:00Z",
        "retroactive_date": "2024-01-01T00:00:00Z",
        "erp_days": 90,
    }
    payload.update(overrides)
    return payload


def score_submission_payload(variant: str = "INDICATIVE") -> dict:
    return {"variant": variant}


def create_quote_payload(expected_submission_version: int, **overrides) -> dict:
    payload = {
        "offered_limit_usd": 10_000_000,
        "offered_retention_usd": 250_000,
        "offered_side_c_sublimit_usd": 5_000_000,
        "quote_valid_until": "2026-08-31T00:00:00Z",
        "expected_submission_version": expected_submission_version,
    }
    payload.update(overrides)
    return payload


def create_exclusion_term_payload(**overrides) -> dict:
    payload = {
        "exclusion_type": "INSURED_VS_INSURED",
        "wording_variant": "BROAD",
        "premium_impact_pct": 0.05,
    }
    payload.update(overrides)
    return payload


def counter_exclusion_term_payload(**overrides) -> dict:
    payload = {
        "wording_variant": "FINAL_ADJUDICATION",
        "premium_impact_pct": -0.05,
    }
    payload.update(overrides)
    return payload


def resolve_exclusion_term_payload(resolution: str = "AGREE") -> dict:
    return {"resolution": resolution}


def create_layer_payload(policy_id: str = None, **overrides) -> dict:
    payload = {
        "carrier_name": "Meridian Primary",
        "attachment_point_usd": 0,
        "limit_usd": 10_000_000,
        "participation_pct": 1.0,
        "form_type": "FOLLOWING_FORM",
    }
    if policy_id is not None:
        payload["policy_id"] = policy_id
    payload.update(overrides)
    return payload


def premium_payment_payload(amount_usd: float) -> dict:
    return {"amount_usd": amount_usd}


def cancel_policy_payload(effective_date: str, cancelled_reason: str = "INSURED_REQUEST") -> dict:
    return {"effective_date": effective_date, "cancelled_reason": cancelled_reason}


def create_runoff_endorsement_payload(tail_years: int) -> dict:
    return {"tail_years": tail_years}


def create_circumstance_report_payload(**overrides) -> dict:
    payload = {
        "description": "SEC informal inquiry into revenue recognition",
        "discovered_date": "2026-08-20T00:00:00Z",
        "potential_claimants": "Shareholders of record",
        "estimated_exposure_usd": 3_000_000,
    }
    payload.update(overrides)
    return payload


def create_claim_payload(policy_id: str = None, **overrides) -> dict:
    payload = {
        "claim_type": "SECURITIES_CLASS_ACTION",
        "claimant_name": "Meridian Pension Fund",
        "claimant_capacity": "THIRD_PARTY",
        "wrongful_act_date": "2026-06-10T00:00:00Z",
        "alleged_damages_usd": 9_000_000,
    }
    if policy_id is not None:
        payload["policy_id"] = policy_id
    payload.update(overrides)
    return payload


def mature_circumstance_report_payload(**overrides) -> dict:
    payload = {
        "claim_type": "SECURITIES_CLASS_ACTION",
        "claimant_name": "Meridian Pension Fund",
        "claimant_capacity": "THIRD_PARTY",
        "wrongful_act_date": "2026-06-10T00:00:00Z",
        "alleged_damages_usd": 9_000_000,
    }
    payload.update(overrides)
    return payload


def coverage_decision_payload(decision: str = "ACCEPT_WITH_ROR", **overrides) -> dict:
    payload = {"decision": decision}
    if decision == "ACCEPT_WITH_ROR":
        payload["allocation_method"] = "RELATIVE_EXPOSURE"
    payload.update(overrides)
    return payload


def create_defense_invoice_payload(claim_id: str = None, **overrides) -> dict:
    payload = {
        "law_firm_name": "Harlow & Reeve LLP",
        "invoice_reference": "HR-2026-0001",
        "billed_amount_usd": 400_000,
        "covered_matter_amount_usd": 150_000,
        "uncovered_matter_amount_usd": 50_000,
        "mixed_matter_amount_usd": 200_000,
        "insured_person_defendant_count": 3,
        "entity_defendant_count": 1,
    }
    if claim_id is not None:
        payload["claim_id"] = claim_id
    payload.update(overrides)
    return payload


def allocate_invoice_payload(expected_claim_version: int) -> dict:
    return {"expected_claim_version": expected_claim_version}


def create_settlement_proposal_payload(recommended_amount_usd: float,
                                       expected_claim_version: int) -> dict:
    return {
        "recommended_amount_usd": recommended_amount_usd,
        "expected_claim_version": expected_claim_version,
    }


def respond_settlement_proposal_payload(response: str, **overrides) -> dict:
    payload = {"response": response}
    if response == "REFUSE":
        payload["refusal_reason"] = "Board considers the demand unsupported by the record"
    payload.update(overrides)
    return payload


def resolve_claim_payload(final_resolution_amount_usd: float, **overrides) -> dict:
    payload = {"final_resolution_amount_usd": final_resolution_amount_usd}
    payload.update(overrides)
    return payload


__all__ = [
    "CANONICAL_INSURED_NAME", "SECOND_INSURED_NAME", "SMALL_INSURED_NAME",
    "create_insured_payload", "update_insured_payload",
    "create_disclosure_package_payload", "clean_disclosure_package_payload",
    "create_litigation_event_payload", "create_submission_payload",
    "score_submission_payload", "create_quote_payload",
    "create_exclusion_term_payload", "counter_exclusion_term_payload",
    "resolve_exclusion_term_payload", "create_layer_payload",
    "premium_payment_payload", "cancel_policy_payload",
    "create_runoff_endorsement_payload", "create_circumstance_report_payload",
    "create_claim_payload", "mature_circumstance_report_payload",
    "coverage_decision_payload", "create_defense_invoice_payload",
    "allocate_invoice_payload", "create_settlement_proposal_payload",
    "respond_settlement_proposal_payload", "resolve_claim_payload",
]
