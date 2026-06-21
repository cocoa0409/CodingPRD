"""Payload factories — one per entity, input fields only.

Per the PRD, only `source: input` fields are part of POST/PUT payloads.
"""


def create_community_payload(
    name: str = "Test HOA",
    fiscal_year_start_month: int = 1,
    regular_assessment_cents: int = 30000,
    **overrides,
) -> dict:
    """POST /hoa/communities input fields (PRD §3.1).

    Optional fields (omitted unless overridden so server defaults apply):
      late_fee_grace_days, late_fee_flat_cents, late_fee_pct_bps,
      lien_threshold_cents, election_quorum_pct, reserve_inflation_bps.
    """
    defaults: dict = {
        "name": name,
        "fiscal_year_start_month": fiscal_year_start_month,
        "regular_assessment_cents": regular_assessment_cents,
    }
    defaults.update(overrides)
    return defaults


def create_owner_payload(
    community_id: str,
    email: str = "owner@example.com",
    full_name: str = "Test Owner",
    **overrides,
) -> dict:
    """POST /hoa/owners input fields (PRD §3.1)."""
    defaults = {
        "community_id": community_id,
        "email": email,
        "full_name": full_name,
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(
    community_id: str,
    owner_id: str,
    unit_label: str = "U-1",
    **overrides,
) -> dict:
    """POST /hoa/properties input fields (PRD §3.1)."""
    defaults = {
        "community_id": community_id,
        "owner_id": owner_id,
        "unit_label": unit_label,
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(
    property_id: str,
    kind: str = "REGULAR",
    principal_cents: int = 30000,
    due_date: str = "2027-01-01T00:00:00Z",
    **overrides,
) -> dict:
    """POST /hoa/assessments input fields (PRD §3.2)."""
    defaults = {
        "property_id": property_id,
        "kind": kind,
        "principal_cents": principal_cents,
        "due_date": due_date,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(
    assessment_id: str,
    amount_cents: int,
    expected_assessment_version: int,
    **overrides,
) -> dict:
    """POST /hoa/payments input fields (PRD §2.8, §3.2)."""
    defaults = {
        "assessment_id": assessment_id,
        "amount_cents": amount_cents,
        "expected_assessment_version": expected_assessment_version,
    }
    defaults.update(overrides)
    return defaults


def create_violation_payload(
    property_id: str,
    category: str = "NOISE",
    **overrides,
) -> dict:
    """POST /hoa/violations input fields (PRD §3.5)."""
    defaults = {
        "property_id": property_id,
        "category": category,
    }
    defaults.update(overrides)
    return defaults


def create_acc_request_payload(
    property_id: str,
    scope: str = "APPEARANCE",
    description: str = "Paint exterior trim",
    **overrides,
) -> dict:
    """POST /hoa/acc-requests input fields (PRD §3.6)."""
    defaults = {
        "property_id": property_id,
        "scope": scope,
        "description": description,
    }
    defaults.update(overrides)
    return defaults


def create_election_payload(
    community_id: str,
    cycle_label: str = "FY2026",
    opens_at: str = "2026-02-01T00:00:00Z",
    closes_at: str = "2026-02-16T00:00:00Z",
    **overrides,
) -> dict:
    """POST /hoa/elections input fields (PRD §3.7)."""
    defaults = {
        "community_id": community_id,
        "cycle_label": cycle_label,
        "opens_at": opens_at,
        "closes_at": closes_at,
    }
    defaults.update(overrides)
    return defaults


def create_vote_payload(
    election_id: str,
    owner_id: str,
    candidate_name: str = "Alice",
    **overrides,
) -> dict:
    """POST /hoa/votes input fields (PRD §3.7)."""
    defaults = {
        "election_id": election_id,
        "owner_id": owner_id,
        "candidate_name": candidate_name,
    }
    defaults.update(overrides)
    return defaults


def create_reserve_component_payload(
    community_id: str,
    label: str = "Roof - Building A",
    useful_life_years: int = 20,
    remaining_life_years: int = 5,
    replacement_cost_cents: int = 500000,
    **overrides,
) -> dict:
    """POST /hoa/reserve-components input fields (PRD §3.8)."""
    defaults = {
        "community_id": community_id,
        "label": label,
        "useful_life_years": useful_life_years,
        "remaining_life_years": remaining_life_years,
        "replacement_cost_cents": replacement_cost_cents,
    }
    defaults.update(overrides)
    return defaults


def create_reserve_study_payload(
    community_id: str,
    fiscal_year: int = 2026,
    method: str = "COMPONENT",
    accumulated_funds_cents: int = 1_000_000,
    **overrides,
) -> dict:
    """POST /hoa/reserve-studies input fields (PRD §3.8)."""
    defaults = {
        "community_id": community_id,
        "fiscal_year": fiscal_year,
        "method": method,
        "accumulated_funds_cents": accumulated_funds_cents,
    }
    defaults.update(overrides)
    return defaults
