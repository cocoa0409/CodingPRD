"""Request payload builders.

Each builder returns a complete, valid payload for one endpoint and accepts
keyword overrides so a test can vary exactly the field under examination and
nothing else.  Defaults are chosen to be uncontroversial (inside every window,
under every cap) so that a failing assertion always points at the overridden
field.
"""

from __future__ import annotations

import itertools
from typing import Any

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


# ----------------------------------------------------------------------
# Association / roster
# ----------------------------------------------------------------------
def association_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "legal_name": f"Test Condominium Association {_seq()}",
    }
    payload.update(overrides)
    return payload


def owner_payload(**overrides: Any) -> dict[str, Any]:
    index = _seq()
    payload: dict[str, Any] = {
        "full_name": f"Owner {index}",
        "email": f"owner{index}@example.test",
        "board_role": "NONE",
        "is_seated": False,
    }
    payload.update(overrides)
    return payload


def director_payload(**overrides: Any) -> dict[str, Any]:
    """A seated board member; board_role defaults to DIRECTOR."""
    payload = owner_payload(board_role="DIRECTOR", is_seated=True)
    payload.update(overrides)
    return payload


def unit_payload(current_owner_id: str, **overrides: Any) -> dict[str, Any]:
    index = _seq()
    payload: dict[str, Any] = {
        "current_owner_id": current_owner_id,
        "unit_label": f"U{index}",
        "interest_bp": 2500,
        "heated_sqft": 1000,
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Ledger
# ----------------------------------------------------------------------
def charge_payload(**overrides: Any) -> dict[str, Any]:
    """A manual charge; ``bucket`` is derived from ``entry_type`` by the server."""
    payload: dict[str, Any] = {
        "entry_type": "COLLECTION_COST",
        "amount_cents": 8_000,
        "due_on": "2026-04-01T00:00:00Z",
        "effective_period": "2026-04",
        "memo": "Collection cost",
    }
    payload.update(overrides)
    return payload


def payment_payload(amount_cents: int, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "amount_cents": amount_cents,
        "effective_period": "2026-10",
        "application_mode": "STATUTORY",
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Budgets and billing
# ----------------------------------------------------------------------
def budget_payload(
    expected_association_version: int, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "fiscal_year": 2026,
        "operating_total_cents": 12_000_000,
        "reserve_contribution_cents": 1_200_000,
        "expected_association_version": expected_association_version,
    }
    payload.update(overrides)
    return payload


def billing_run_payload(source_budget_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source_budget_id": source_budget_id,
        "period": "2026-10",
        "due_on": "2026-10-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Special assessments and votes
# ----------------------------------------------------------------------
def special_assessment_payload(
    expected_association_version: int, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "purpose": f"Special assessment {_seq()}",
        "total_amount_cents": 1_000_000,
        "installment_count": 2,
        "expected_association_version": expected_association_version,
    }
    payload.update(overrides)
    return payload


def board_vote_payload(
    association_id: str,
    subject_type: str,
    subject_id: str,
    voter_owner_id: str,
    meeting_id: str,
    **overrides: Any,
) -> dict[str, Any]:
    """A board vote carries meeting_id."""
    payload: dict[str, Any] = {
        "association_id": association_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "choice": "YES",
        "voter_owner_id": voter_owner_id,
        "meeting_id": meeting_id,
    }
    payload.update(overrides)
    return payload


def owner_ballot_payload(
    association_id: str,
    subject_type: str,
    subject_id: str,
    voter_owner_id: str,
    unit_id: str,
    **overrides: Any,
) -> dict[str, Any]:
    """A weighted owner ballot carries unit_id."""
    payload: dict[str, Any] = {
        "association_id": association_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "choice": "YES",
        "voter_owner_id": voter_owner_id,
        "unit_id": unit_id,
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Board meetings
# ----------------------------------------------------------------------
def board_meeting_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "scheduled_start": "2026-09-10T18:00:00Z",
        "scheduled_end": "2026-09-10T21:00:00Z",
        "agenda_kinds": ["REGULAR"],
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Common elements and vendor contracts
# ----------------------------------------------------------------------
def common_element_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": f"Common Element {_seq()}",
        "element_class": "ROOF",
        "replacement_cost_cents": 9_000_000,
        "useful_life_years": 30,
        "effective_age_years": 10,
    }
    payload.update(overrides)
    return payload


def vendor_contract_payload(covered_element_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "covered_element_id": covered_element_id,
        "vendor_name": f"Vendor {_seq()} LLC",
        "contract_cap_cents": 20_000_000,
        "insurance_cert_expires_at": "2027-06-01T00:00:00Z",
        "effective_from": "2026-09-01T00:00:00Z",
        "effective_to": "2027-06-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def work_order_payload(
    contract_id: str,
    element_id: str,
    expected_contract_version: int,
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract_id": contract_id,
        "element_id": element_id,
        "scope": f"Scheduled maintenance {_seq()}",
        "window_start": "2026-10-05T08:00:00Z",
        "window_end": "2026-10-07T18:00:00Z",
        "estimated_cost_cents": 1_000_000,
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Insurance claims
# ----------------------------------------------------------------------
def insurance_claim_payload(
    association_id: str, unit_id: str, element_id: str, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "association_id": association_id,
        "loss_type": "WATER",
        "loss_at": "2026-06-15T00:00:00Z",
        "gross_damage_cents": 4_800_000,
        "within_unit_boundary_cents": 400_000,
        "unit_id": unit_id,
        "element_id": element_id,
        "affected_unit_ids": [unit_id],
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Violation cases
# ----------------------------------------------------------------------
def violation_case_payload(
    association_id: str, unit_id: str, reported_by_owner_id: str, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "association_id": association_id,
        "unit_id": unit_id,
        "rule_code": "PARKING",
        "reported_by_owner_id": reported_by_owner_id,
    }
    payload.update(overrides)
    return payload


def schedule_hearing_payload(
    hearing_meeting_id: str, hearing_slot_start: str, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "hearing_meeting_id": hearing_meeting_id,
        "hearing_slot_start": hearing_slot_start,
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Resale certificates
# ----------------------------------------------------------------------
def resale_certificate_payload(
    requesting_agent_id: str, expected_unit_version: int, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "closing_date": "2026-09-15T00:00:00Z",
        "payoff_basis": "LEDGER_BALANCE",
        "requesting_agent_id": requesting_agent_id,
        "expected_unit_version": expected_unit_version,
    }
    payload.update(overrides)
    return payload


def installment_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "due_on": "2026-10-01T00:00:00Z",
        "effective_period": "2026-10",
    }
    payload.update(overrides)
    return payload


def refund_payload(unit_id: str, amount_cents: int, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "unit_id": unit_id,
        "amount_cents": amount_cents,
        "effective_period": "2026-11",
    }
    payload.update(overrides)
    return payload
