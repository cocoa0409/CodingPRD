"""Payload factories for every writeable endpoint.

Each factory returns a valid minimal-but-complete request body, with keyword
overrides for the field a test wants to vary. Money is always integer cents
(never a string, never a float) and dates are always YYYY-MM-DD strings.
"""

import itertools
from typing import Any, Dict

Json = Dict[str, Any]

_ein_counter = itertools.count(10)


def next_ein() -> str:
    """A registry-unique EIN in the two-digit / hyphen / seven-digit shape."""
    n = next(_ein_counter)
    return f"{n % 100:02d}-{(n * 7919) % 10000000:07d}"


# ----------------------------------------------------------------------
# Organizations and programs
# ----------------------------------------------------------------------
def organization_payload(**overrides: Any) -> Json:
    payload: Json = {
        "legal_name": "Riverside Youth Alliance",
        "ein": next_ein(),
        "state_code": "CA",
        "mission_code": "YM-YOUTH_MENTORING",
        "annual_expense_cents": 100000002,
        "unrestricted_net_assets_cents": 59916670,
    }
    payload.update(overrides)
    return payload


def financial_restatement_payload(**overrides: Any) -> Json:
    payload: Json = {
        "annual_expense_cents": 120000000,
        "unrestricted_net_assets_cents": 60000000,
        "restatement_reason": "Audit adjustment following FY close",
    }
    payload.update(overrides)
    return payload


def program_payload(org_id: str, **overrides: Any) -> Json:
    payload: Json = {
        "org_id": org_id,
        "name": "After-School Mentoring",
        "service_category": "YOUTH_MENTORING",
        "county_code": "CA-ALAMEDA",
        "annual_expense_cents": 12000000,
        "clients_served": 400,
    }
    payload.update(overrides)
    return payload


def continuity_decision_payload(deal_id: str, **overrides: Any) -> Json:
    payload: Json = {
        "restructuring_id": deal_id,
        "disposition": "TRANSFER",
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Restructurings and alignment assessments
# ----------------------------------------------------------------------
def restructuring_payload(initiator_org_id: str, target_org_id: str, **overrides: Any) -> Json:
    payload: Json = {
        "initiator_org_id": initiator_org_id,
        "target_org_id": target_org_id,
    }
    payload.update(overrides)
    return payload


def alignment_assessment_payload(deal_id: str, variant: str = "SCREENING", **overrides: Any) -> Json:
    payload: Json = {
        "restructuring_id": deal_id,
        "variant": variant,
    }
    payload.update(overrides)
    return payload


def select_structure_payload(**overrides: Any) -> Json:
    payload: Json = {
        "structure_type": "MERGER",
        "unrestricted_transfer_value_cents": 200000000,
    }
    payload.update(overrides)
    return payload


def consummate_payload(**overrides: Any) -> Json:
    payload: Json = {"closing_memo_ref": "CLOSE-MEMO-0001"}
    payload.update(overrides)
    return payload


def abandon_payload(**overrides: Any) -> Json:
    payload: Json = {"abandonment_reason": "Boards could not agree on governance"}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Letters of intent
# ----------------------------------------------------------------------
def letter_of_intent_payload(deal_id: str, expected_version: int, **overrides: Any) -> Json:
    payload: Json = {
        "restructuring_id": deal_id,
        "expected_restructuring_version": expected_version,
        "proposed_structure_type": "MERGER",
        "combined_board_seats": 15,
        "board_seat_split_initiator": 8,
        "exclusivity_days": 60,
        "exclusivity_start_date": "2026-08-01",
    }
    payload.update(overrides)
    return payload


def counter_payload(**overrides: Any) -> Json:
    payload: Json = {"counter_note": "Target requests a larger seat share"}
    payload.update(overrides)
    return payload


def revise_payload(board_seat_split_initiator: int = 7, **overrides: Any) -> Json:
    payload: Json = {"board_seat_split_initiator": board_seat_split_initiator}
    payload.update(overrides)
    return payload


def execute_payload(**overrides: Any) -> Json:
    payload: Json = {"executed_note": "Countersigned by the target board chair"}
    payload.update(overrides)
    return payload


def withdraw_payload(**overrides: Any) -> Json:
    payload: Json = {"withdrawal_reason": "Initiator is pausing the process"}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Diligence requests
# ----------------------------------------------------------------------
def diligence_request_payload(deal_id: str, **overrides: Any) -> Json:
    payload: Json = {
        "restructuring_id": deal_id,
        "workstream": "FINANCE",
        "severity": "HIGH",
        "summary": "Unreconciled pledge receivable",
        "exposure_cents": 29916670,
    }
    payload.update(overrides)
    return payload


def diligence_respond_payload(**overrides: Any) -> Json:
    payload: Json = {"response_ref": "RESP-0001"}
    payload.update(overrides)
    return payload


def diligence_clear_payload(**overrides: Any) -> Json:
    payload: Json = {"clearance_note": "Reconciliation evidence reviewed and accepted"}
    payload.update(overrides)
    return payload


def diligence_escalate_payload(**overrides: Any) -> Json:
    payload: Json = {"escalation_reason": "Exposure exceeds the board risk tolerance"}
    payload.update(overrides)
    return payload


def diligence_waive_payload(**overrides: Any) -> Json:
    payload: Json = {"waiver_justification": "Board accepted the unresolved risk in writing"}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Restricted funds
# ----------------------------------------------------------------------
def restricted_fund_payload(org_id: str, **overrides: Any) -> Json:
    payload: Json = {
        "org_id": org_id,
        "fund_name": "Nakamura Family Program Fund",
        "fund_type": "TEMP_RESTRICTED",
        "principal_cents": 50000000,
        "accumulated_appreciation_cents": 12000000,
        "historic_dollar_value_cents": 0,
        "restriction_purpose_code": "AF-AFTERSCHOOL",
        "restriction_conflict": False,
        "donor_of_record_reachable": True,
    }
    payload.update(overrides)
    return payload


def seek_consent_payload(**overrides: Any) -> Json:
    payload: Json = {"consent_method": "WRITTEN"}
    payload.update(overrides)
    return payload


def record_consent_payload(decision: str = "GRANTED", **overrides: Any) -> Json:
    payload: Json = {"decision": decision}
    payload.update(overrides)
    return payload


def file_petition_payload(**overrides: Any) -> Json:
    payload: Json = {
        "petition_basis": "IMPRACTICABLE",
        "court_docket_no": "SUP-CIV-2026-0001",
    }
    payload.update(overrides)
    return payload


def court_decision_payload(decision: str = "GRANTED", **overrides: Any) -> Json:
    payload: Json = {
        "decision": decision,
        "modified_purpose_code": "YS-YOUTHSERVICES",
    }
    payload.update(overrides)
    return payload


def transfer_payload(deal_id: str, transfer_basis: str = "DONOR_CONSENT", **overrides: Any) -> Json:
    payload: Json = {
        "restructuring_id": deal_id,
        "transfer_basis": transfer_basis,
    }
    payload.update(overrides)
    return payload


def unwind_payload(**overrides: Any) -> Json:
    payload: Json = {"unwind_reason": "Transfer rescinded pending donor clarification"}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Board approvals
# ----------------------------------------------------------------------
def board_approval_payload(
    deal_id: str, expected_version: int, approving_party: str = "INITIATOR", **overrides: Any
) -> Json:
    payload: Json = {
        "restructuring_id": deal_id,
        "expected_restructuring_version": expected_version,
        "approving_party": approving_party,
        "seats_total": 15,
        "recusals": 1,
        "votes_for": 10,
        "votes_against": 4,
        "abstentions": 0,
        "conflict_disclosures_count": 1,
        "recording_secretary_ref": "SEC-A-1",
    }
    payload.update(overrides)
    return payload


def certify_payload(**overrides: Any) -> Json:
    payload: Json = {
        "fiduciary_memo_ref": "MEMO-A-1",
        "certifying_secretary_ref": "SEC-A-2",
    }
    payload.update(overrides)
    return payload


def rescind_payload(**overrides: Any) -> Json:
    payload: Json = {"rescission_reason": "Minutes contained a material error"}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Attorney-general filings
# ----------------------------------------------------------------------
def ag_filing_payload(deal_id: str, **overrides: Any) -> Json:
    payload: Json = {
        "restructuring_id": deal_id,
        "state_code": "CA",
        "filing_type": "NOTICE",
        "legal_costs_cents": 0,
    }
    payload.update(overrides)
    return payload


def ag_decision_payload(decision: str = "APPROVED", **overrides: Any) -> Json:
    payload: Json = {"decision": decision}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Integration tasks
# ----------------------------------------------------------------------
def integration_task_payload(deal_id: str, **overrides: Any) -> Json:
    payload: Json = {
        "restructuring_id": deal_id,
        "workstream": "SYSTEMS",
        "title": "Consolidate donor CRM",
        "crew_code": "CREW-A1",
        "planned_start_date": "2026-09-01",
        "planned_end_date": "2026-09-10",
    }
    payload.update(overrides)
    return payload


def start_task_payload(**overrides: Any) -> Json:
    payload: Json = {"started_note": "Crew mobilised"}
    payload.update(overrides)
    return payload


def complete_task_payload(**overrides: Any) -> Json:
    payload: Json = {"completion_note": "Cutover verified"}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# Operator endpoints
# ----------------------------------------------------------------------
def clock_payload(current_utc: str, **overrides: Any) -> Json:
    payload: Json = {"current_utc": current_utc}
    payload.update(overrides)
    return payload
