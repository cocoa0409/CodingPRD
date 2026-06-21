"""Payload factories — one per entity, input fields only (PRD §3).

Field names are PRD-exact. Only fields the client supplies appear here;
server-managed fields (id, status, computed totals, version, timestamps)
are never included.
"""
from .constants import TEST_DEFAULTS


def create_funeral_home_payload(**overrides) -> dict:
    """POST /funeral-homes (PRD §3.1). trust_admin_retention_cents and
    chapel_buffer_minutes are optional."""
    payload = {
        "name": "Rose Hill",
        "sales_tax_pct": TEST_DEFAULTS["SALES_TAX_PCT"],
        "state_trust_pct": TEST_DEFAULTS["STATE_TRUST_PCT"],
    }
    payload.update(overrides)
    return payload


def create_gpl_item_payload(funeral_home_id, **overrides) -> dict:
    """POST /gpl-items (PRD §3.1). taxable/non_declinable/preneed_trustable
    are optional with defaults false/false/true respectively."""
    payload = {
        "funeral_home_id": funeral_home_id,
        "code": "SVC-BASIC",
        "name": "Basic services of funeral director",
        "category": "SERVICE",
        "unit_price_cents": 200000,
    }
    payload.update(overrides)
    return payload


def create_case_payload(funeral_home_id, **overrides) -> dict:
    """POST /cases (PRD §3.2). AT_NEED requires date_of_death; PRENEED omits it."""
    payload = {
        "funeral_home_id": funeral_home_id,
        "decedent_name": "Jane Doe",
        "case_mode": "AT_NEED",
        "date_of_death": "2026-06-01T00:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def add_statement_line_payload(gpl_item_id, **overrides) -> dict:
    """POST /cases/{caseId}/statement-lines (PRD §3.3). quantity optional, default 1."""
    payload = {"gpl_item_id": gpl_item_id}
    payload.update(overrides)
    return payload


def create_contract_payload(funding_type="AT_NEED_DIRECT", **overrides) -> dict:
    """POST /cases/{caseId}/contract (PRD §3.4)."""
    payload = {"funding_type": funding_type}
    payload.update(overrides)
    return payload


def mark_funded_payload(expected_contract_version, **overrides) -> dict:
    """POST /contracts/{contractId}/mark-funded (PRD §2.7, §3.6)."""
    payload = {"expected_contract_version": expected_contract_version}
    payload.update(overrides)
    return payload


def trust_deposit_payload(kind="PRINCIPAL", amount_cents=100000, **overrides) -> dict:
    """POST /contracts/{contractId}/trust-deposits (PRD §3.5)."""
    payload = {"kind": kind, "amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def insurance_assignment_payload(assigned_value_cents=100000, **overrides) -> dict:
    """POST /contracts/{contractId}/insurance-assignments (PRD §3.5)."""
    payload = {
        "policy_number": "P-1",
        "carrier": "Acme Life",
        "assigned_value_cents": assigned_value_cents,
    }
    payload.update(overrides)
    return payload


def create_plot_payload(funeral_home_id, **overrides) -> dict:
    """POST /plots (PRD §3.1)."""
    payload = {
        "funeral_home_id": funeral_home_id,
        "section": "A",
        "plot_code": "A-1",
        "current_price_cents": 80000,
    }
    payload.update(overrides)
    return payload


def reserve_plot_payload(case_id, expected_plot_version, **overrides) -> dict:
    """POST /plots/{plotId}/reserve (PRD §2.7, §3.8)."""
    payload = {"case_id": case_id, "expected_plot_version": expected_plot_version}
    payload.update(overrides)
    return payload


def create_venue_payload(funeral_home_id, **overrides) -> dict:
    """POST /venues (PRD §3.1)."""
    payload = {
        "funeral_home_id": funeral_home_id,
        "name": "Main Chapel",
        "capacity": 120,
    }
    payload.update(overrides)
    return payload


def create_event_payload(resource_kind, resource_id, starts_at, **overrides) -> dict:
    """POST /cases/{caseId}/events (PRD §3.9). ends_at required for CHAPEL."""
    payload = {
        "resource_kind": resource_kind,
        "resource_id": resource_id,
        "starts_at": starts_at,
    }
    payload.update(overrides)
    return payload


def apply_permit_payload(permit_type="DEATH_CERTIFICATE", **overrides) -> dict:
    """POST /cases/{caseId}/permits (PRD §3.7)."""
    payload = {"permit_type": permit_type}
    payload.update(overrides)
    return payload


def issue_permit_payload(reference_number="REF-1", **overrides) -> dict:
    """POST /permits/{permitId}/issue (PRD §3.7)."""
    payload = {"reference_number": reference_number}
    payload.update(overrides)
    return payload
