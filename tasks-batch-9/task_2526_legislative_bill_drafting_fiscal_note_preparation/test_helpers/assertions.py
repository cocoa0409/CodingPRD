"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgencyStatus,
    AmendmentStage,
    AmendmentStatus,
    BillFiscalStatus,
    BillLegislativeStatus,
    Chamber,
    Confidentiality,
    ConflictResolutionStatus,
    ConflictSeverity,
    ConflictType,
    CommitteeReferralStatus,
    CorrectionType,
    DraftingRequestStatus,
    EnrolledBillStatus,
    FiscalNoteRequestStatus,
    FiscalPosture,
    Methodology,
    Scenario,
    SessionStatus,
    SignatureRole,
    TechnicalCorrectionStatus,
)

_ENUM_VALUES = {
    "SessionStatus": [e.value for e in SessionStatus],
    "FiscalPosture": [e.value for e in FiscalPosture],
    "Chamber": [e.value for e in Chamber],
    "AgencyStatus": [e.value for e in AgencyStatus],
    "DraftingRequestStatus": [e.value for e in DraftingRequestStatus],
    "Confidentiality": [e.value for e in Confidentiality],
    "ConflictType": [e.value for e in ConflictType],
    "ConflictSeverity": [e.value for e in ConflictSeverity],
    "ConflictResolutionStatus": [e.value for e in ConflictResolutionStatus],
    "BillLegislativeStatus": [e.value for e in BillLegislativeStatus],
    "BillFiscalStatus": [e.value for e in BillFiscalStatus],
    "CommitteeReferralStatus": [e.value for e in CommitteeReferralStatus],
    "FiscalNoteRequestStatus": [e.value for e in FiscalNoteRequestStatus],
    "Methodology": [e.value for e in Methodology],
    "Scenario": [e.value for e in Scenario],
    "AmendmentStage": [e.value for e in AmendmentStage],
    "AmendmentStatus": [e.value for e in AmendmentStatus],
    "EnrolledBillStatus": [e.value for e in EnrolledBillStatus],
    "SignatureRole": [e.value for e in SignatureRole],
    "CorrectionType": [e.value for e in CorrectionType],
    "TechnicalCorrectionStatus": [e.value for e in TechnicalCorrectionStatus],
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def assert_common_properties(data: Dict[str, Any], label: str = "entity") -> None:
    """id, created_at, updated_at and version are carried by every entity except
    the append-only cost estimate lines."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1, got {data['version']}"


def assert_append_only_properties(data: Dict[str, Any], label: str = "entity") -> None:
    """Append-only rows carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, f"{label} must not carry updated_at"
    assert "version" not in data, f"{label} must not carry version"


def assert_enum(data: Dict[str, Any], field: str, enum_name: str) -> None:
    assert data[field] in _ENUM_VALUES[enum_name], (
        f"{field} must be one of {_ENUM_VALUES[enum_name]}, got {data[field]!r}"
    )


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into the instant it names.

    The PRD pins a three-fractional-digit rendering for `created_at` and
    `updated_at` only; every other timestamp is specified as an *instant* — it is
    "stamped with the logical clock", copied from a client-supplied instant, or
    derived by adding whole hours/minutes/days to one. Sub-second rendering is
    therefore not part of any declared rule, so domain timestamps are compared as
    instants rather than byte-for-byte.
    """
    assert isinstance(value, str) and value, f"expected an ISO 8601 timestamp, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant(actual: Any, expected: str, label: Optional[str] = None) -> None:
    """Assert that a returned timestamp names the same instant as `expected`."""
    prefix = f"{label}: " if label else ""
    assert isinstance(actual, str) and actual, (
        f"{prefix}expected the ISO 8601 instant {expected}, got {actual!r}"
    )
    assert is_iso8601_timestamp(actual), (
        f"{prefix}{actual!r} is not a well-formed ISO 8601 UTC timestamp"
    )
    assert parse_instant(actual) == parse_instant(expected), (
        f"{prefix}expected the instant {expected}, got {actual}"
    )


def assert_cents(value: Any, label: str) -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Entity assertions
# ---------------------------------------------------------------------------
def assert_session(data: Dict[str, Any]) -> None:
    assert_common_properties(data, "Session")
    assert isinstance(data["name"], str) and data["name"]
    for field in (
        "introduction_deadline_utc",
        "committee_report_deadline_utc",
        "sine_die_utc",
    ):
        assert is_iso8601_timestamp(data[field]), f"Session.{field} must be ISO 8601 UTC"
    assert_enum(data, "status", "SessionStatus")
    assert_enum(data, "fiscal_posture", "FiscalPosture")
    assert isinstance(data["required_fiscal_years"], list) and data["required_fiscal_years"]
    assert data["required_fiscal_years"] == sorted(set(data["required_fiscal_years"])), (
        "Session.required_fiscal_years must be strictly ascending"
    )
    assert_cents(data["constrained_threshold_cents"], "Session.constrained_threshold_cents")
    assert_cents(data["fiscal_cap_cents"], "Session.fiscal_cap_cents")
    assert_cents(data["certified_fiscal_total_cents"], "Session.certified_fiscal_total_cents")
    assert data["fiscal_note_default_days"] >= 1
    assert data["next_house_bill_number"] >= 1
    assert data["next_senate_bill_number"] >= 1
    assert data["bills_introduced_count"] >= 0
    assert data["bills_enrolled_count"] >= 0


def assert_member(data: Dict[str, Any]) -> None:
    assert_common_properties(data, "Member")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert_enum(data, "chamber", "Chamber")
    assert isinstance(data["party"], str)
    assert data["priority_slots_total"] >= 0
    assert data["priority_slots_used"] >= 0
    assert data["clarification_pending_count"] >= 0
    assert isinstance(data["intake_hold"], bool)


def assert_drafter(data: Dict[str, Any]) -> None:
    assert_common_properties(data, "Drafter")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["is_senior"], bool)
    assert data["max_concurrent_engagements"] >= 1
    assert data["active_engagement_count"] >= 0


def assert_agency(data: Dict[str, Any]) -> None:
    assert_common_properties(data, "Agency")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["agency_code"], str) and data["agency_code"]
    assert_enum(data, "status", "AgencyStatus")
    assert data["max_open_requests"] >= 1
    assert data["open_request_count"] >= 0
    assert data["late_submission_count"] >= 0
    assert data["revision_count"] >= 0
    assert 0 <= data["responsiveness_score"] <= 100, (
        f"Agency.responsiveness_score must sit in 0..100, got {data['responsiveness_score']}"
    )


def assert_committee(data: Dict[str, Any]) -> None:
    assert_common_properties(data, "Committee")
    assert is_valid_uuid(data["session_id"])
    assert_enum(data, "chamber", "Chamber")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["is_fiscal_committee"], bool)
    assert data["max_concurrent_referrals"] >= 1
    assert data["active_referral_count"] >= 0


def assert_drafting_request(data: Dict[str, Any]) -> None:
    assert_common_properties(data, "DraftingRequest")
    assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["subject"], str) and data["subject"]
    assert isinstance(data["summary"], str) and data["summary"]
    assert_enum(data, "confidentiality", "Confidentiality")
    assert_enum(data, "status", "DraftingRequestStatus")
    assert isinstance(data["priority_flag"], bool)
    assert data["requested_sections_count"] >= 1
    assert_cents(data["appropriation_requested_cents"], "DraftingRequest.appropriation_requested_cents")
    assert data["appropriation_requested_cents"] >= 0
    assert data["revision_round"] >= 0
    assert data["blocking_conflict_count"] >= 0
    assert data["open_blocking_conflict_count"] >= 0
    assert data["advisory_conflict_count"] >= 0
    assert data["open_blocking_conflict_count"] <= data["blocking_conflict_count"], (
        "open blocking conflicts can never exceed the total blocking conflict count"
    )


def assert_statutory_conflict(data: Dict[str, Any]) -> None:
    assert_common_properties(data, "StatutoryConflict")
    assert is_valid_uuid(data["drafting_request_id"])
    assert isinstance(data["code_citation"], str) and data["code_citation"]
    assert_enum(data, "conflict_type", "ConflictType")
    assert_enum(data, "severity", "ConflictSeverity")
    assert_enum(data, "resolution_status", "ConflictResolutionStatus")


def assert_bill(data: Dict[str, Any]) -> None:
    assert_common_properties(data, "Bill")
    assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["drafting_request_id"])
    assert is_valid_uuid(data["sponsor_member_id"])
    assert_enum(data, "chamber", "Chamber")
    assert_enum(data, "legislative_status", "BillLegislativeStatus")
    assert_enum(data, "fiscal_status", "BillFiscalStatus")
    assert isinstance(data["bill_number"], str) and data["bill_number"]
    assert data["bill_number"].startswith(("HB ", "SB ")), (
        f"bill_number must carry the chamber prefix, got {data['bill_number']!r}"
    )
    assert is_iso8601_timestamp(data["introduced_utc"])
    assert_cents(data["appropriation_requested_cents"], "Bill.appropriation_requested_cents")
    assert_cents(data["adopted_fiscal_delta_cents"], "Bill.adopted_fiscal_delta_cents")
    assert isinstance(data["priority_bill"], bool)
    assert data["adopted_amendment_count"] >= 0
    assert data["referral_count"] >= 0


def assert_committee_referral(data: Dict[str, Any]) -> None:
    assert_common_properties(data, "CommitteeReferral")
    assert is_valid_uuid(data["bill_id"])
    assert is_valid_uuid(data["committee_id"])
    assert data["referral_order"] >= 1
    for field in ("hearing_window_start_utc", "hearing_window_end_utc", "report_deadline_utc"):
        assert is_iso8601_timestamp(data[field]), f"CommitteeReferral.{field} must be ISO 8601 UTC"
    assert data["hearing_window_end_utc"] > data["hearing_window_start_utc"], (
        "the hearing window must end after it starts"
    )
    assert_enum(data, "status", "CommitteeReferralStatus")


def assert_fiscal_note_request(data: Dict[str, Any]) -> None:
    assert_common_properties(data, "FiscalNoteRequest")
    assert is_valid_uuid(data["bill_id"])
    assert is_valid_uuid(data["agency_id"])
    assert_enum(data, "methodology", "Methodology")
    assert_enum(data, "status", "FiscalNoteRequestStatus")
    assert is_iso8601_timestamp(data["routed_utc"])
    assert is_iso8601_timestamp(data["due_utc"])
    assert data["revision_round"] >= 0
    assert isinstance(data["late_submission"], bool)
    for field in (
        "direct_cost_cents",
        "contingency_cents",
        "certified_total_cents",
        "projected_revenue_total_cents",
        "high_scenario_total_cents",
        "low_scenario_total_cents",
    ):
        if data.get(field) is not None:
            assert_cents(data[field], f"FiscalNoteRequest.{field}")


def assert_cost_estimate(data: Dict[str, Any]) -> None:
    assert_append_only_properties(data, "CostEstimate")
    assert is_valid_uuid(data["fiscal_note_request_id"])
    assert data["fiscal_year"] >= 2000
    assert_enum(data, "scenario", "Scenario")
    assert data["revision_round"] >= 0
    for field in ("personnel_cost_cents", "operating_cost_cents", "one_time_cost_cents"):
        assert_cents(data[field], f"CostEstimate.{field}")
        assert data[field] >= 0
    assert_cents(data["revenue_impact_cents"], "CostEstimate.revenue_impact_cents")
    assert float(data["fte_count"]) >= 0
    assert isinstance(data["included_in_certification"], bool)


def assert_amendment(data: Dict[str, Any]) -> None:
    assert_common_properties(data, "Amendment")
    assert is_valid_uuid(data["bill_id"])
    assert is_valid_uuid(data["requested_by_member_id"])
    assert_enum(data, "stage", "AmendmentStage")
    assert_enum(data, "status", "AmendmentStatus")
    assert isinstance(data["summary"], str) and data["summary"]
    assert_cents(data["fiscal_impact_delta_cents"], "Amendment.fiscal_impact_delta_cents")
    for field in ("drafting_start_utc", "drafting_due_utc", "requested_utc", "turnaround_deadline_utc"):
        assert is_iso8601_timestamp(data[field]), f"Amendment.{field} must be ISO 8601 UTC"
    assert data["drafting_due_utc"] > data["drafting_start_utc"]
    assert data["rescind_count"] >= 0
    if data["stage"] == "FLOOR":
        assert data["committee_referral_id"] is None, (
            "a FLOOR amendment must not carry a committee_referral_id"
        )


def assert_enrolled_bill(data: Dict[str, Any]) -> None:
    assert_common_properties(data, "EnrolledBill")
    assert is_valid_uuid(data["bill_id"])
    assert data["adopted_amendment_count"] >= 0
    assert_cents(data["net_fiscal_delta_cents"], "EnrolledBill.net_fiscal_delta_cents")
    assert isinstance(data["enrollment_sequence"], list)
    assert len(data["enrollment_sequence"]) == data["adopted_amendment_count"], (
        "enrollment_sequence must list exactly the frozen adopted amendments"
    )
    assert data["origin_signature_role"] in ("SPEAKER", "SENATE_PRESIDENT")
    assert_enum(data, "expected_next_signature", "SignatureRole")
    assert_enum(data, "status", "EnrolledBillStatus")
    assert data["corrections_applied_count"] >= 0
    assert data["open_corrections_count"] >= 0


def assert_technical_correction(data: Dict[str, Any]) -> None:
    assert_common_properties(data, "TechnicalCorrection")
    assert is_valid_uuid(data["enrolled_bill_id"])
    assert is_valid_uuid(data["proposed_by_drafter_id"])
    assert_enum(data, "correction_type", "CorrectionType")
    assert_enum(data, "status", "TechnicalCorrectionStatus")
    assert isinstance(data["is_substantive"], bool)
    assert isinstance(data["description"], str) and data["description"]


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_session_ledger_invariants(session: Dict[str, Any]) -> None:
    """The certified ledger drives the posture, and the posture flips inclusively."""
    expected_posture = (
        "CONSTRAINED"
        if session["certified_fiscal_total_cents"] >= session["constrained_threshold_cents"]
        else "NORMAL"
    )
    assert session["fiscal_posture"] == expected_posture, (
        f"fiscal_posture must be {expected_posture} at ledger "
        f"{session['certified_fiscal_total_cents']} against threshold "
        f"{session['constrained_threshold_cents']}, got {session['fiscal_posture']}"
    )
    assert session["certified_fiscal_total_cents"] <= session["fiscal_cap_cents"], (
        "the certified ledger must never exceed the session fiscal cap"
    )


def assert_note_total_invariants(note: Dict[str, Any]) -> None:
    """certified_total_cents is direct cost plus contingency, in whole cents."""
    if note["direct_cost_cents"] is None:
        return
    assert float(note["contingency_pct"]) in (0.05, 0.08, 0.12), (
        f"contingency_pct must be one of the three declared tiers, got {note['contingency_pct']}"
    )
    assert note["certified_total_cents"] == note["direct_cost_cents"] + note["contingency_cents"], (
        "certified_total_cents must equal direct_cost_cents + contingency_cents"
    )


def assert_agency_responsiveness_invariants(agency: Dict[str, Any]) -> None:
    """responsiveness_score is the clamped penalty formula over the two counters."""
    expected = max(
        0,
        min(100, 100 - 12 * agency["late_submission_count"] - 5 * agency["revision_count"]),
    )
    assert agency["responsiveness_score"] == expected, (
        f"responsiveness_score must be {expected} for "
        f"{agency['late_submission_count']} late submissions and "
        f"{agency['revision_count']} revisions, got {agency['responsiveness_score']}"
    )


def assert_member_hold_invariants(member: Dict[str, Any]) -> None:
    """intake_hold latches at two pending clarifications."""
    expected = member["clarification_pending_count"] >= 2
    assert member["intake_hold"] is expected, (
        f"intake_hold must be {expected} at clarification_pending_count "
        f"{member['clarification_pending_count']}, got {member['intake_hold']}"
    )
