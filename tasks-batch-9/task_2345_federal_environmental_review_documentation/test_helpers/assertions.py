"""Per-entity shape assertions and domain invariant checkers."""
from typing import List, Optional

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgencyStatus,
    AlternativeKind,
    CommentDisposition,
    CommentStatus,
    CommitmentStatus,
    ConsultationStatus,
    DecisionStatus,
    DocumentType,
    EcScreenStatus,
    InclusionStatus,
    IssueStatus,
    MonitoringStatus,
    ObjectionStatus,
    PublicationStatus,
    PurposeNeedStatus,
    RecordEntryCode,
    ResourceAnalysisStatus,
    ReviewStage,
    ScopingPeriodStatus,
    ScreeningStatus,
)

#: Tolerance for the two-decimal quantities the PRD carries (PRD 2.8).
SCORE_TOLERANCE = 0.005


def approx_score(expected: float):
    """Comparison helper for a value carried to exactly two decimal places."""
    return pytest.approx(expected, abs=SCORE_TOLERANCE)


def assert_scores_differ(actual: float, other: float, label: str = "value") -> None:
    """Assert that ``actual`` is not the value a mis-ordered calculation yields."""
    assert abs(actual - other) > SCORE_TOLERANCE, (
        f"{label} is {actual}, which equals the value produced by the wrong "
        f"evaluation order ({other})"
    )


# --------------------------------------------------------------------------
# Common property assertions (PRD 2.4)
# --------------------------------------------------------------------------

def assert_common_fields(entity: dict, name: str = "entity") -> None:
    """Every resource carries a UUID ``id``, a ``created_at``, and — for every
    resource except an administrative record entry — ``updated_at`` and
    ``version``."""
    assert is_valid_uuid(entity.get("id")), f"{name}.id must be a UUID: {entity.get('id')}"
    assert is_iso8601_timestamp(entity.get("created_at")), (
        f"{name}.created_at must be an ISO 8601 UTC instant: {entity.get('created_at')}"
    )
    assert is_iso8601_timestamp(entity.get("updated_at")), (
        f"{name}.updated_at must be an ISO 8601 UTC instant: {entity.get('updated_at')}"
    )
    assert isinstance(entity.get("version"), int) and entity["version"] >= 1, (
        f"{name}.version must be an integer starting at 1: {entity.get('version')}"
    )


def assert_versionless_common_fields(entity: dict, name: str = "record entry") -> None:
    """An administrative record entry carries only ``id`` and ``created_at``."""
    assert is_valid_uuid(entity.get("id")), f"{name}.id must be a UUID: {entity.get('id')}"
    assert is_iso8601_timestamp(entity.get("created_at")), (
        f"{name}.created_at must be an ISO 8601 UTC instant: {entity.get('created_at')}"
    )
    assert "updated_at" not in entity, f"{name} must not carry updated_at"
    assert "version" not in entity, f"{name} must not carry version"


def _normalize_instant(value: str) -> str:
    """Reduce an ISO 8601 UTC instant to a comparable canonical form so that a
    payload carrying three fractional digits compares equal to the same instant
    written without them."""
    assert isinstance(value, str), f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "." in text:
        head, fraction = text.split(".", 1)
        fraction = (fraction + "000")[:3]
    else:
        head, fraction = text, "000"
    return f"{head}.{fraction}Z"


def assert_instant_equals(actual: str, expected: str, label: str = "instant") -> None:
    """Assert that two ISO 8601 UTC instants name the same moment."""
    assert _normalize_instant(actual) == _normalize_instant(expected), (
        f"{label} should be {expected}, got {actual}"
    )


def _assert_in_enum(value, enum_cls, field: str, name: str) -> None:
    allowed = [member.value for member in enum_cls]
    assert value in allowed, f"{name}.{field} must be one of {allowed}, got {value!r}"


# --------------------------------------------------------------------------
# Entity assertions
# --------------------------------------------------------------------------

def assert_review_office(office: dict) -> None:
    assert_common_fields(office, "office")
    assert isinstance(office.get("office_code"), str)
    assert isinstance(office.get("name"), str)
    assert isinstance(office.get("binding_obligation_cents"), int), (
        "office.binding_obligation_cents must be whole cents"
    )
    assert office["binding_obligation_cents"] >= 0


def assert_agency(agency: dict) -> None:
    assert_common_fields(agency, "agency")
    _assert_in_enum(agency.get("status"), AgencyStatus, "status", "agency")
    assert isinstance(agency.get("active_consultation_count"), int)
    assert agency["active_consultation_count"] >= 0


def assert_proposed_action(action: dict) -> None:
    assert_common_fields(action, "action")
    _assert_in_enum(action.get("review_stage"), ReviewStage, "review_stage", "action")
    for counter in (
        "significant_issue_count",
        "unaddressed_issue_count",
        "alternatives_screened_in_count",
        "finalized_analysis_count",
        "record_entry_count",
    ):
        assert isinstance(action.get(counter), int), f"action.{counter} must be an integer"
        assert action[counter] >= 0, f"action.{counter} must not be negative"
    assert isinstance(action.get("extraordinary_circumstance_flag"), bool)


def assert_ec_screen(screen: dict) -> None:
    assert_common_fields(screen, "screen")
    _assert_in_enum(screen.get("status"), EcScreenStatus, "status", "screen")
    assert isinstance(screen.get("findings"), list) and screen["findings"], (
        "screen.findings must be a non-empty array"
    )
    assert isinstance(screen.get("triggered_codes"), list)
    assert isinstance(screen.get("max_severity"), int)
    assert 0 <= screen["max_severity"] <= 5
    assert isinstance(screen.get("screen_round"), int) and screen["screen_round"] >= 1


def assert_purpose_need_statement(statement: dict) -> None:
    assert_common_fields(statement, "statement")
    _assert_in_enum(statement.get("status"), PurposeNeedStatus, "status", "statement")
    assert isinstance(statement.get("version_no"), int) and statement["version_no"] >= 1
    assert isinstance(statement.get("goal_codes"), list) and statement["goal_codes"]


def assert_scoping_period(period: dict) -> None:
    assert_common_fields(period, "period")
    _assert_in_enum(period.get("status"), ScopingPeriodStatus, "status", "period")
    assert isinstance(period.get("duration_days"), int)
    assert period["duration_days"] >= 0


def assert_issue(issue: dict) -> None:
    assert_common_fields(issue, "issue")
    _assert_in_enum(issue.get("status"), IssueStatus, "status", "issue")


def assert_alternative(alternative: dict) -> None:
    assert_common_fields(alternative, "alternative")
    _assert_in_enum(alternative.get("screening_status"), ScreeningStatus,
                    "screening_status", "alternative")
    _assert_in_enum(alternative.get("alternative_kind"), AlternativeKind,
                    "alternative_kind", "alternative")
    assert 0.0 <= float(alternative["feasibility_score"]) <= 100.0, (
        "alternative.feasibility_score must lie between 0 and 100"
    )


def assert_cumulative_action(entry: dict) -> None:
    assert_common_fields(entry, "cumulative entry")
    _assert_in_enum(entry.get("inclusion_status"), InclusionStatus,
                    "inclusion_status", "cumulative entry")


def assert_resource_analysis(analysis: dict) -> None:
    assert_common_fields(analysis, "analysis")
    _assert_in_enum(analysis.get("status"), ResourceAnalysisStatus, "status", "analysis")


def assert_draft_analysis_scores_unset(analysis: dict) -> None:
    """A draft analysis has the three recorded-variant fields null and the three
    score fields at 0.00 until finalisation computes them (PRD 3.7)."""
    assert analysis["status"] == ResourceAnalysisStatus.DRAFT.value
    for field in ("significance_score", "significance_determination", "variant_applied"):
        assert analysis[field] is None, (
            f"analysis.{field} must be null while the analysis is DRAFT, got "
            f"{analysis[field]!r}"
        )
    for field in ("cumulative_effect_score", "unmitigated_score", "mitigated_score"):
        assert float(analysis[field]) == approx_score(0.00), (
            f"analysis.{field} must be 0.00 until finalisation, got {analysis[field]!r}"
        )


def assert_consultation(consultation: dict) -> None:
    assert_common_fields(consultation, "consultation")
    _assert_in_enum(consultation.get("status"), ConsultationStatus, "status", "consultation")
    assert isinstance(consultation.get("is_required"), bool)
    assert isinstance(consultation.get("late"), bool)


def assert_document(document: dict) -> None:
    assert_common_fields(document, "document")
    _assert_in_enum(document.get("publication_status"), PublicationStatus,
                    "publication_status", "document")
    _assert_in_enum(document.get("comment_status"), CommentStatus,
                    "comment_status", "document")
    _assert_in_enum(document.get("document_type"), DocumentType,
                    "document_type", "document")
    assert document["unresolved_substantive_count"] == (
        document["substantive_comment_count"] - document["responded_substantive_count"]
    ), (
        "unresolved_substantive_count must equal substantive_comment_count minus "
        "responded_substantive_count"
    )


def assert_comment(comment: dict) -> None:
    assert_common_fields(comment, "comment")
    _assert_in_enum(comment.get("disposition"), CommentDisposition, "disposition", "comment")


def assert_decision(decision: dict) -> None:
    assert_common_fields(decision, "decision")
    _assert_in_enum(decision.get("status"), DecisionStatus, "status", "decision")
    for field in ("committed_obligation_cents", "base_obligation_cents",
                  "contingency_fee_cents", "binding_obligation_cents"):
        assert isinstance(decision.get(field), int), (
            f"decision.{field} must be carried in whole cents"
        )
    assert decision["binding_obligation_cents"] == (
        decision["base_obligation_cents"] + decision["contingency_fee_cents"]
    ), "binding_obligation_cents must equal base_obligation_cents plus contingency_fee_cents"
    assert decision["committed_obligation_cents"] <= decision["binding_obligation_cents"], (
        "committed_obligation_cents must always be at or below binding_obligation_cents"
    )


def assert_mitigation(commitment: dict) -> None:
    assert_common_fields(commitment, "commitment")
    _assert_in_enum(commitment.get("status"), CommitmentStatus, "status", "commitment")
    _assert_in_enum(commitment.get("monitoring_status"), MonitoringStatus,
                    "monitoring_status", "commitment")
    assert isinstance(commitment.get("lifecycle_obligation_cents"), int)
    assert commitment["lifecycle_obligation_cents"] >= commitment["cost_estimate_cents"], (
        "lifecycle_obligation_cents is cost_estimate_cents plus the rounded "
        "monitoring stream, so it can never be smaller than the estimate"
    )


def assert_objection(objection: dict) -> None:
    assert_common_fields(objection, "objection")
    _assert_in_enum(objection.get("status"), ObjectionStatus, "status", "objection")


def assert_record_entry(entry: dict) -> None:
    assert_versionless_common_fields(entry)
    _assert_in_enum(entry.get("entry_code"), RecordEntryCode, "entry_code", "record entry")
    assert isinstance(entry.get("sequence_no"), int) and entry["sequence_no"] >= 1
    assert is_iso8601_timestamp(entry.get("occurred_at")), (
        f"record entry occurred_at must be an ISO 8601 instant: {entry.get('occurred_at')}"
    )
    assert isinstance(entry.get("summary"), str) and entry["summary"].strip()
    assert isinstance(entry.get("related_entity_type"), str)
    assert isinstance(entry.get("related_entity_ref"), str)


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------

def assert_sequence_contiguous(entries: List[dict]) -> None:
    """``sequence_no`` is 1-based, gap-free and unique within an action, and the
    listing is returned in ``sequence_no`` ascending order (PRD 2.4, 2.3)."""
    numbers = [entry["sequence_no"] for entry in entries]
    assert numbers == sorted(numbers), (
        f"record entries must be listed in sequence_no ascending order, got {numbers}"
    )
    assert numbers == list(range(1, len(entries) + 1)), (
        f"sequence_no must be 1-based and gap-free, got {numbers}"
    )


def assert_entry_codes(entries: List[dict], expected_codes: List[str]) -> None:
    actual = [entry["entry_code"] for entry in entries]
    assert actual == expected_codes, (
        f"expected record entry codes {expected_codes}, got {actual}"
    )


def assert_strictly_increasing_sequence(entries: List[dict]) -> None:
    numbers = [entry["sequence_no"] for entry in entries]
    assert all(later > earlier for earlier, later in zip(numbers, numbers[1:])), (
        f"sequence_no must increase strictly across cascade entries, got {numbers}"
    )


def assert_occurred_at_non_decreasing(entries: List[dict]) -> None:
    instants = [entry["occurred_at"] for entry in entries]
    assert all(later >= earlier for earlier, later in zip(instants, instants[1:])), (
        f"occurred_at must be non-decreasing across the sequence, got {instants}"
    )


def find_entry(entries: List[dict], entry_code: str) -> Optional[dict]:
    for entry in entries:
        if entry["entry_code"] == entry_code:
            return entry
    return None


def entries_with_code(entries: List[dict], entry_code: str) -> List[dict]:
    return [entry for entry in entries if entry["entry_code"] == entry_code]


def assert_office_ledger_equals(office: dict, expected_cents: int) -> None:
    """The office's ``binding_obligation_cents`` is the sum over its SIGNED
    decisions (PRD 2.12)."""
    assert office["binding_obligation_cents"] == expected_cents, (
        f"office binding_obligation_cents should be {expected_cents}, got "
        f"{office['binding_obligation_cents']}"
    )
