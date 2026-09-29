"""Payload factories — one per resource family, client-supplied fields only."""

from .constants import TEST_DEFAULTS


def create_program_payload(**overrides) -> dict:
    """A grant program round. The ten policy parameters are omitted by default
    so the server applies its programme defaults."""
    payload = {
        "name": TEST_DEFAULTS["PROGRAM_NAME"],
        "fiscal_year": TEST_DEFAULTS["FISCAL_YEAR"],
        "total_appropriation_cents": TEST_DEFAULTS["TOTAL_APPROPRIATION_CENTS"],
        "challenge_window_start": TEST_DEFAULTS["CHALLENGE_WINDOW_START"],
        "challenge_window_end": TEST_DEFAULTS["CHALLENGE_WINDOW_END"],
        "application_window_start": TEST_DEFAULTS["APPLICATION_WINDOW_START"],
        "application_window_end": TEST_DEFAULTS["APPLICATION_WINDOW_END"],
    }
    payload.update(overrides)
    return payload


def create_location_payload(program_id, address_id, **overrides) -> dict:
    """One national-map location record. Defaults to the canonical UNSERVED
    reading of 10 down, 1 up, 50 milliseconds on DSL."""
    payload = {
        "program_id": program_id,
        "address_id": address_id,
        "reported_down_mbps": 10,
        "reported_up_mbps": 1,
        "reported_latency_ms": 50,
        "reported_technology": "DSL",
        "reporting_provider_user_id": "prov-2",
    }
    payload.update(overrides)
    return payload


def create_challenge_payload(program_id, location_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "location_id": location_id,
        "challenger_type": "COMMUNITY",
        "asserted_classification": "UNSERVED",
        "rationale": "Community filing contesting the mapped classification.",
    }
    payload.update(overrides)
    return payload


def create_evidence_payload(
    evidence_type, collected_at, expected_challenge_version, **overrides
) -> dict:
    payload = {
        "evidence_type": evidence_type,
        "collected_at": collected_at,
        "description": f"{evidence_type} artefact gathered for the record.",
        "expected_challenge_version": expected_challenge_version,
    }
    payload.update(overrides)
    return payload


def create_subgrantee_payload(program_id, **overrides) -> dict:
    """A prospective subgrantee. The declared figures default to the canonical
    applicant that qualifies at a capability index of 90.00."""
    payload = {
        "program_id": program_id,
        "legal_name": TEST_DEFAULTS["SUBGRANTEE_LEGAL_NAME"],
        "ein": TEST_DEFAULTS["SUBGRANTEE_EIN"],
        "net_assets_cents": 900000,
        "requested_amount_cents": 3000000,
        "key_personnel_count": 4,
        "has_prior_federal_award": True,
    }
    payload.update(overrides)
    return payload


def create_application_payload(program_id, subgrantee_id, **overrides) -> dict:
    """A draft application offering symmetrical gigabit at 50 milliseconds,
    a 25.0 percent match and a thirty-dollar low-cost plan."""
    payload = {
        "program_id": program_id,
        "subgrantee_id": subgrantee_id,
        "match_offer_pct": 25.0,
        "committed_down_mbps": 1000,
        "committed_up_mbps": 1000,
        "committed_latency_ms": 50,
        "low_cost_plan_price_cents": 3000,
        "participates_in_state_affordability_program": True,
        "has_dbe_plan": True,
        "has_union_agreement": False,
        "local_hire_pct": 40,
        "proposed_construction_start": TEST_DEFAULTS["CONSTRUCTION_START"],
        "proposed_construction_end": TEST_DEFAULTS["CONSTRUCTION_END"],
    }
    payload.update(overrides)
    return payload


def create_location_claim_payload(application_id, location_id, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "location_id": location_id,
        "claimed_cost_cents": TEST_DEFAULTS["CANONICAL_CLAIM_COST_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_score_sheet_payload(
    application_id, expected_application_version, **overrides
) -> dict:
    payload = {
        "application_id": application_id,
        "expected_application_version": expected_application_version,
    }
    payload.update(overrides)
    return payload


def create_award_payload(application_id, **overrides) -> dict:
    payload = {"application_id": application_id}
    payload.update(overrides)
    return payload


def create_environmental_review_payload(**overrides) -> dict:
    payload = {
        "tribal_consultation_required": False,
        "shpo_consultation_required": False,
    }
    payload.update(overrides)
    return payload


def create_environmental_determination_payload(pathway, **overrides) -> dict:
    payload = {"pathway": pathway}
    payload.update(overrides)
    return payload


def create_milestone_payload(sequence_no, planned_location_ids, **overrides) -> dict:
    payload = {
        "sequence_no": sequence_no,
        "description": f"Build milestone {sequence_no}.",
        "evidence_basis": "BUILD_PROGRESS",
        "planned_location_ids": planned_location_ids,
        "is_final": False,
    }
    payload.update(overrides)
    return payload


def submit_milestone_evidence_payload(built_location_ids, **overrides) -> dict:
    payload = {"built_location_ids": built_location_ids}
    payload.update(overrides)
    return payload


def verify_milestone_payload(outcome="APPROVED", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def create_compliance_audit_payload(
    audit_type, window_start, window_end, **overrides
) -> dict:
    payload = {
        "audit_type": audit_type,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def record_audit_result_payload(result, tested_location_ids, **overrides) -> dict:
    payload = {"result": result, "tested_location_ids": tested_location_ids}
    payload.update(overrides)
    return payload


def resolve_clawback_payload(resolution, **overrides) -> dict:
    payload = {"resolution": resolution}
    payload.update(overrides)
    return payload


def submit_remediation_payload(
    audited_net_assets_cents, withdrawn_personnel_count, **overrides
) -> dict:
    payload = {
        "audited_net_assets_cents": audited_net_assets_cents,
        "withdrawn_personnel_count": withdrawn_personnel_count,
    }
    payload.update(overrides)
    return payload
