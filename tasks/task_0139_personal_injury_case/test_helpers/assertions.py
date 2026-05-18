"""Entity assertions and domain invariant checkers.

These check response shape and domain invariants required by the PRD
contract.

PRD §2.4: every persisted resource carries id + created_at +
updated_at + version EXCEPT ContingencyFeeAgreement and
SettlementDisbursement which are lean (id + created_at + own immutable
fields only).
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields predicates — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'an integer version that starts at 1 and increments
    by one each time the row is mutated'."""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4 — common_fields entities."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)


def assert_lean_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4 — lean entities (ContingencyFeeAgreement,
    SettlementDisbursement)."""
    _assert_id_and_created_at(data)


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_client(data: Dict[str, Any]) -> None:
    """PRD §3.1: 'full_name, date_of_birth, contact_email, and
    state_of_residence'."""
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["contact_email"], str) and "@" in data["contact_email"]
    assert isinstance(data["state_of_residence"], str)
    assert len(data["state_of_residence"]) == 2
    assert data["state_of_residence"].isupper()
    # is_minor_at_incident may be null until first case is opened.
    assert "is_minor_at_incident" in data


CASE_STATUSES_VALID = {
    "INTAKE", "RECORDS_PENDING", "READY_FOR_DEMAND",
    "DEMAND_SENT", "NEGOTIATING", "LITIGATION",
    "SETTLED", "TRIAL_AWARDED", "DISMISSED", "CLOSED",
}

INCIDENT_TYPES_VALID = {
    "AUTO", "SLIP_FALL", "MEDICAL_MALPRACTICE",
    "PRODUCT_LIABILITY", "PREMISES", "DOG_BITE",
}


def assert_case(data: Dict[str, Any]) -> None:
    """PRD §3.1: case fields."""
    assert_common_fields(data)
    assert isinstance(data["client_id"], str) and data["client_id"]
    assert isinstance(data["incident_date"], str)
    assert data["incident_type"] in INCIDENT_TYPES_VALID
    assert isinstance(data["jurisdiction_state"], str)
    assert len(data["jurisdiction_state"]) == 2
    assert data["status"] in CASE_STATUSES_VALID
    assert isinstance(data["sol_deadline"], str)
    # PRD §2.5: 'stored as whole calendar dates in the form YYYY-MM-DD'.
    assert len(data["sol_deadline"]) == 10
    assert isinstance(data["sol_tolled_days"], int)
    assert data["sol_tolled_days"] >= 0
    assert isinstance(data["gross_settlement_cents"], int)
    assert isinstance(data["case_costs_cents"], int)
    assert data["case_costs_cents"] >= 0
    assert isinstance(data["filed_in_court"], bool)
    # disbursement_approved_by may be null
    assert "disbursement_approved_by" in data


MED_REQ_STATUSES_VALID = {"DRAFT", "SENT", "RECEIVED", "REJECTED", "CANCELED"}


def assert_medical_record_request(data: Dict[str, Any]) -> None:
    """PRD §3.3."""
    assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["provider_name"], str) and data["provider_name"]
    assert isinstance(data["date_of_service_start"], str)
    assert isinstance(data["date_of_service_end"], str)
    assert data["status"] in MED_REQ_STATUSES_VALID
    # sent_at / received_at may be null
    assert "sent_at" in data
    assert "received_at" in data
    assert isinstance(data["billed_amount_cents"], int)
    assert data["billed_amount_cents"] >= 0


DAMAGES_METHODS_VALID = {"MULTIPLIER", "PER_DIEM"}


def assert_damages(data: Dict[str, Any]) -> None:
    """PRD §3.4."""
    assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["medical_bills_cents"], int)
    assert data["medical_bills_cents"] >= 0
    assert isinstance(data["lost_wages_cents"], int)
    assert isinstance(data["property_damage_cents"], int)
    assert data["pain_suffering_method"] in DAMAGES_METHODS_VALID
    assert isinstance(data["pain_suffering_cents"], int)
    assert isinstance(data["total_damages_cents"], int)


LIEN_TYPES_VALID = {
    "MEDICARE", "MEDICAID", "ERISA", "HOSPITAL_STATUTORY",
    "PROVIDER_NEGOTIATED", "CHILD_SUPPORT", "ATTORNEY_PRIOR_COUNSEL",
}
LIEN_STATUSES_VALID = {
    "ASSERTED", "NEGOTIATING", "REDUCED", "RESOLVED", "DISPUTED",
}


def assert_lien(data: Dict[str, Any]) -> None:
    """PRD §3.8."""
    assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["lienholder_name"], str) and data["lienholder_name"]
    assert data["lien_type"] in LIEN_TYPES_VALID
    assert isinstance(data["face_amount_cents"], int)
    assert data["face_amount_cents"] > 0
    assert "negotiated_amount_cents" in data
    assert data["status"] in LIEN_STATUSES_VALID
    assert "final_paid_amount_cents" in data
    assert "priority_rank" in data


DEMAND_STATUSES_VALID = {
    "DRAFT", "SENT", "RESPONDED", "SUPERSEDED", "WITHDRAWN",
}


def assert_demand_letter(data: Dict[str, Any]) -> None:
    """PRD §3.5."""
    assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["demanded_amount_cents"], int)
    assert isinstance(data["snapshot_total_damages_cents"], int)
    assert isinstance(data["snapshot_damages_version"], int)
    assert data["status"] in DEMAND_STATUSES_VALID
    assert "sent_at" in data
    assert "response_due_at" in data


OFFER_PARTIES_VALID = {"DEFENDANT", "PLAINTIFF"}
OFFER_STATUSES_VALID = {
    "PENDING", "ACCEPTED", "REJECTED", "COUNTERED", "EXPIRED", "WITHDRAWN",
}


def assert_settlement_offer(data: Dict[str, Any]) -> None:
    """PRD §3.6."""
    assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert "predecessor_offer_id" in data
    assert data["offer_party"] in OFFER_PARTIES_VALID
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] > 0
    assert data["status"] in OFFER_STATUSES_VALID
    assert isinstance(data["expires_at"], str)
    assert isinstance(data["round_number"], int)
    assert data["round_number"] >= 1


def assert_contingency_fee_agreement(data: Dict[str, Any]) -> None:
    """PRD §2.4 — lean entity (id + created_at only)."""
    assert_lean_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["pre_suit_rate_bps"], int)
    assert isinstance(data["post_suit_rate_bps"], int)
    assert isinstance(data["trial_rate_bps"], int)
    assert isinstance(data["signed_at"], str)
    assert "updated_at" not in data, (
        "ContingencyFeeAgreement must NOT carry updated_at per PRD §2.4"
    )
    assert "version" not in data, (
        "ContingencyFeeAgreement must NOT carry version per PRD §2.4"
    )


COURT_EVENT_TYPES_VALID = {
    "COMPLAINT_FILED", "ANSWER_DUE", "DISCOVERY_DEADLINE",
    "MEDIATION", "MOTION_HEARING", "TRIAL", "JUDGMENT",
}
COURT_EVENT_STATUSES_VALID = {
    "SCHEDULED", "COMPLETED", "CONTINUED", "CANCELED",
}


def assert_court_event(data: Dict[str, Any]) -> None:
    """PRD §3.7."""
    assert_common_fields(data)
    assert isinstance(data["case_id"], str)
    assert data["event_type"] in COURT_EVENT_TYPES_VALID
    assert isinstance(data["scheduled_at"], str)
    assert isinstance(data["duration_minutes"], int)
    assert 15 <= data["duration_minutes"] <= 480, (
        "PRD §3.7: duration_minutes between 15 and 480 inclusive"
    )
    assert data["status"] in COURT_EVENT_STATUSES_VALID
    assert "courtroom" in data


DISBURSEMENT_STRATEGIES_VALID = {
    "CHRONOLOGICAL_PRIORITY", "FORWARD_LOOKING_PRORATA",
}


def assert_settlement_disbursement(data: Dict[str, Any]) -> None:
    """PRD §3.10 — lean entity (id + created_at only)."""
    assert_lean_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["attorney_fee_cents"], int)
    assert isinstance(data["case_costs_cents"], int)
    assert isinstance(data["total_lien_payment_cents"], int)
    assert isinstance(data["client_net_cents"], int)
    assert data["strategy"] in DISBURSEMENT_STRATEGIES_VALID
    assert isinstance(data["approved_by"], str) and data["approved_by"]
    assert "updated_at" not in data, (
        "SettlementDisbursement must NOT carry updated_at per PRD §2.4"
    )
    assert "version" not in data, (
        "SettlementDisbursement must NOT carry version per PRD §2.4"
    )


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_disbursement_conservation(data: Dict[str, Any]) -> None:
    """PRD §3.10 / validation priority 80: 'The post-condition
    gross_amount_cents minus attorney_fee_cents minus case_costs_cents
    minus total_lien_payment_cents must equal client_net_cents with no
    cents drift'.
    """
    g = data["gross_amount_cents"]
    f = data["attorney_fee_cents"]
    c = data["case_costs_cents"]
    l = data["total_lien_payment_cents"]
    n = data["client_net_cents"]
    assert g - f - c - l == n, (
        f"Disbursement conservation violated: "
        f"{g} - {f} - {c} - {l} = {g - f - c - l} != client_net {n}"
    )
    assert n >= 0, (
        "PRD §3.10: 'Negative client_net rejected' — client_net_cents "
        f"must be >= 0, got {n}"
    )


def assert_version_incremented_by(old: Dict[str, Any], new: Dict[str, Any],
                                  by: int = 1) -> None:
    """PRD §2.4: version increments by one on each mutation."""
    assert new["version"] == old["version"] + by, (
        f"Expected version {old['version']} + {by} = "
        f"{old['version'] + by}, got {new['version']}"
    )


def assert_sol_deadline_format(deadline: str) -> None:
    """PRD §3.2: 'stored as a YYYY-MM-DD date string'."""
    assert isinstance(deadline, str)
    assert len(deadline) == 10
    assert deadline[4] == "-" and deadline[7] == "-"


__all__ = [
    "assert_common_fields",
    "assert_lean_fields",
    "assert_client",
    "assert_case",
    "assert_medical_record_request",
    "assert_damages",
    "assert_lien",
    "assert_demand_letter",
    "assert_settlement_offer",
    "assert_contingency_fee_agreement",
    "assert_court_event",
    "assert_settlement_disbursement",
    "assert_disbursement_conservation",
    "assert_version_incremented_by",
    "assert_sol_deadline_format",
]
