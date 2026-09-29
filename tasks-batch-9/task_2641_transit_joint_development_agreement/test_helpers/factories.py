"""Request payload factories.

Every factory returns a plain dict of JSON-native values: monetary fields are
integer cents, percentages and fractions are numbers, never strings. Each
factory accepts `**overrides` so a test can vary exactly one field, and an
override whose value is `None` for an optional field removes it from the
payload so server-side defaults can be observed.
"""

from typing import Dict, List, Optional

SITE_DEFAULTS = {
    "site_code": "TJD-A-001",
    "name": "Sequoia Junction Park-and-Ride",
    "address_line": "1420 Sequoia Junction Road",
    "parcel_area_sqft": 54000,
    "acquisition_funding_source": "FEDERAL_GRANT",
    "federal_interest_pct": 2.5,
}

ASSESSMENT_DEFAULTS = {
    "environmental_score": 80,
    "utility_score": 75,
    "access_score": 70,
    "entitlement_score": 60,
    "encumbrance_count": 1,
}

DEVELOPER_DEFAULTS = {
    "legal_name": "Alder Transit Partners LLC",
    "contact_email": "dev-a@example.com",
}

SOLICITATION_DEFAULTS = {
    "solicitation_type": "RFP",
    "response_deadline": "2026-09-15T00:00:00Z",
    "benchmark_value_cents": 48_500_000,
    "affordable_housing_min_pct": 15,
}

PROPOSAL_DEFAULTS = {
    "proposed_structure": "GROUND_LEASE",
    "proposed_annual_rent_cents": 2_400_000,
    "affordable_units": 50,
    "total_units": 200,
    "transit_ridership_uplift": 600,
    "design_compliance_score": 88,
}

VALUATION_DEFAULTS = {
    "method": "INCOME_APPROACH",
    "appraised_value_cents": 48_500_000,
    "transit_supportive_use_pct": 60,
    "affordable_units_pct": 25,
    "transfer_basis": "TRANSIT_SUPPORTIVE_BELOW_MARKET",
    "effective_date": "2026-08-20",
}

AGREEMENT_DEFAULTS = {
    "structure": "GROUND_LEASE",
    "term_years": 20,
    "base_rent_cents": 2_000_000,
    "revenue_share_pct": 0.05,
    "projected_gross_revenue_cents": 12_000_000,
    "affordable_units_committed": 50,
    "total_units": 200,
    "site_area_share_pct": 60,
}

SHARED_FACILITY_DEFAULTS = {
    "facility_type": "BUS_BAY",
    "total_bay_capacity": 6,
    "maintenance_responsibility": "SHARED",
    "cost_share_pct_developer": 0.35,
}

FACILITY_REPLACEMENT_DEFAULTS = {
    "facility_type": "BUS_BAY",
    "original_capacity": 10,
    "replacement_capacity": 10,
    "interim_capacity": 8,
    "milestone_date": "2027-06-30",
}


def _merge(defaults: Dict, overrides: Dict) -> Dict:
    payload = dict(defaults)
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


def create_site_payload(**overrides) -> Dict:
    return _merge(SITE_DEFAULTS, overrides)


def create_local_only_site_payload(**overrides) -> Dict:
    """A locally funded parcel: `federal_interest_pct` must be exactly 0."""
    base = dict(SITE_DEFAULTS)
    base["acquisition_funding_source"] = "LOCAL_ONLY"
    base["federal_interest_pct"] = 0
    return _merge(base, overrides)


def create_assessment_payload(**overrides) -> Dict:
    return _merge(ASSESSMENT_DEFAULTS, overrides)


def create_developer_payload(**overrides) -> Dict:
    return _merge(DEVELOPER_DEFAULTS, overrides)


def create_solicitation_payload(**overrides) -> Dict:
    return _merge(SOLICITATION_DEFAULTS, overrides)


def create_proposal_payload(developer_id: str, **overrides) -> Dict:
    base = dict(PROPOSAL_DEFAULTS)
    base["developer_id"] = developer_id
    return _merge(base, overrides)


def create_fee_proposal_payload(developer_id: str, **overrides) -> Dict:
    """A fee disposition proposal carries a purchase price, not a rent."""
    base = dict(PROPOSAL_DEFAULTS)
    base["developer_id"] = developer_id
    base["proposed_structure"] = "FEE_DISPOSITION"
    base.pop("proposed_annual_rent_cents", None)
    base["proposed_purchase_price_cents"] = 48_000_000
    return _merge(base, overrides)


def create_valuation_payload(expected_site_version: int, **overrides) -> Dict:
    base = dict(VALUATION_DEFAULTS)
    base["expected_site_version"] = expected_site_version
    return _merge(base, overrides)


def create_agreement_payload(site_id: str, developer_id: str, proposal_id: str,
                             valuation_id: str, **overrides) -> Dict:
    base = {
        "site_id": site_id,
        "developer_id": developer_id,
        "proposal_id": proposal_id,
        "valuation_id": valuation_id,
    }
    base.update(AGREEMENT_DEFAULTS)
    return _merge(base, overrides)


def create_fee_agreement_payload(site_id: str, developer_id: str, proposal_id: str,
                                 valuation_id: str, **overrides) -> Dict:
    base = create_agreement_payload(site_id, developer_id, proposal_id, valuation_id)
    base["structure"] = "FEE_DISPOSITION"
    base.pop("base_rent_cents", None)
    base["purchase_price_cents"] = 42_000_000
    return _merge(base, overrides)


def award_payload(proposal_id: str, negotiation_start_date: str = "2026-08-15",
                  negotiation_end_date: str = "2027-01-15",
                  deviation_justification: Optional[str] = None) -> Dict:
    payload = {
        "proposal_id": proposal_id,
        "negotiation_start_date": negotiation_start_date,
        "negotiation_end_date": negotiation_end_date,
    }
    if deviation_justification is not None:
        payload["deviation_justification"] = deviation_justification
    return payload


def create_negotiation_period_payload(proposal_id: str,
                                      start_date: str = "2026-08-15",
                                      end_date: str = "2027-01-15",
                                      **overrides) -> Dict:
    base = {
        "proposal_id": proposal_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    return _merge(base, overrides)


def extend_negotiation_period_payload(new_end_date: str) -> Dict:
    return {"new_end_date": new_end_date}


def terminate_negotiation_period_payload(termination_reason: str) -> Dict:
    return {"termination_reason": termination_reason}


def reopen_inventory_payload(reason: str) -> Dict:
    return {"reason": reason}


def request_revision_payload(revision_notes: str) -> Dict:
    return {"revision_notes": revision_notes}


def board_approve_payload(resolution_number: str) -> Dict:
    return {"resolution_number": resolution_number}


def execute_agreement_payload(execution_date: str = "2026-08-25") -> Dict:
    return {"execution_date": execution_date}


def create_disposition_request_payload(narrative: str) -> Dict:
    return {"narrative": narrative}


def determination_payload(determination: str,
                         condition_notes: Optional[str] = None) -> Dict:
    payload = {"determination": determination}
    if condition_notes is not None:
        payload["condition_notes"] = condition_notes
    return payload


def withdraw_disposition_payload(withdraw_reason: str) -> Dict:
    return {"withdraw_reason": withdraw_reason}


def create_facility_replacement_payload(**overrides) -> Dict:
    return _merge(FACILITY_REPLACEMENT_DEFAULTS, overrides)


def replacement_status_payload(status: str, **overrides) -> Dict:
    base = {"status": status}
    return _merge(base, overrides)


def create_shared_facility_payload(**overrides) -> Dict:
    return _merge(SHARED_FACILITY_DEFAULTS, overrides)


def create_staging_window_payload(jda_id: str, shared_facility_id: str,
                                  expected_facility_version: int,
                                  start_at: str = "2026-08-16T08:00:00Z",
                                  end_at: str = "2026-08-18T08:00:00Z",
                                  bays_occupied: int = 3,
                                  purpose: str = "Crane pad",
                                  **overrides) -> Dict:
    base = {
        "jda_id": jda_id,
        "shared_facility_id": shared_facility_id,
        "start_at": start_at,
        "end_at": end_at,
        "bays_occupied": bays_occupied,
        "purpose": purpose,
        "expected_facility_version": expected_facility_version,
    }
    return _merge(base, overrides)


def staging_decision_payload(decision: str,
                            rejection_reason: Optional[str] = None) -> Dict:
    payload = {"decision": decision}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return payload


def maintenance_line_item(description: str, cost_cents: int) -> Dict:
    return {"description": description, "cost_cents": cost_cents}


def create_maintenance_charge_payload(jda_id: str, line_items: List[Dict],
                                      period_start: str = "2026-08-01",
                                      period_end: str = "2026-08-31",
                                      **overrides) -> Dict:
    base = {
        "jda_id": jda_id,
        "period_start": period_start,
        "period_end": period_end,
        "line_items": line_items,
    }
    payload = dict(base)
    for key, value in overrides.items():
        payload[key] = value
    return payload


def clock_payload(to_iso8601: str) -> Dict:
    return {"to_iso8601": to_iso8601}
