"""Entity assertions and domain invariant checkers.

Each assert_* validates the system-managed fields (PRD §2.4) and that the
status/enum fields carry values from the sets the PRD enumerates.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AssessmentStatus,
    Certification,
    CompensationType,
    ContributionType,
    CorrectiveActionStatus,
    CorrectiveActionType,
    CorrectionProgram,
    CorrectionProgramFilingStatus,
    EarningsVariant,
    EngagementPosture,
    EngagementStatus,
    ExtensionStatus,
    FilingStatus,
    FindingCategory,
    Severity,
    FindingSource,
    FindingStatus,
    FundingArrangement,
    MatchStatus,
    ParticipantStatus,
    PlanType,
    PriorYearScheduleType,
    RequiredScheduleType,
    ScheduleEntryStatus,
    ScheduleType,
    ServiceCode,
    TestResultStatus,
    TestResultValue,
    TestType,
    TestingMethod,
    TimelinessStatus,
    TrustStatementStatus,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), \
        f"version must be an integer, got {data.get('version')!r}"


def assert_engagement(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in EngagementStatus}
    assert data["posture"] in {p.value for p in EngagementPosture}
    assert data["plan_type"] in {p.value for p in PlanType}
    assert data["funding_arrangement"] in {f.value for f in FundingArrangement}
    assert data["prior_year_schedule_type"] in {p.value for p in PriorYearScheduleType}
    for field in ("participant_count_beginning", "audit_required",
                  "required_schedule_type", "remittance_standard_days"):
        assert field in data, f"missing computed field {field}"


def assert_participant(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in ParticipantStatus}
    assert isinstance(data["is_eligible"], bool)
    assert isinstance(data["is_hce"], bool)
    assert isinstance(data["compensation_cy_cents"], int)
    assert isinstance(data["deferral_amount_cy_cents"], int)
    assert isinstance(data["opening_balance_cents"], int)
    assert isinstance(data["account_balance_cents"], int)


def assert_contribution(data: dict):
    _assert_common(data)
    assert data["type"] in {t.value for t in ContributionType}
    assert data["match_status"] in {m.value for m in MatchStatus}
    assert data["timeliness_status"] in {t.value for t in TimelinessStatus}
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_trust_statement(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in TrustStatementStatus}
    assert data["certification"] in {c.value for c in Certification}
    assert isinstance(data["reported_deposit_total_cents"], int)
    assert isinstance(data["matched_contribution_cents"], int)
    assert isinstance(data["adjustment_cents"], int)
    assert isinstance(data["unreconciled_deposit_cents"], int)


def assert_reconciliation_identity(statement: dict):
    """PRD §3.4: unreconciled == reported - matched - adjustment (signed, exact)."""
    expected = (statement["reported_deposit_total_cents"]
                - statement["matched_contribution_cents"]
                - statement["adjustment_cents"])
    assert statement["unreconciled_deposit_cents"] == expected, (
        f"reconciliation identity broken: {statement['unreconciled_deposit_cents']} "
        f"!= {statement['reported_deposit_total_cents']} - "
        f"{statement['matched_contribution_cents']} - {statement['adjustment_cents']}"
    )


def assert_test_result(data: dict):
    _assert_common(data)
    assert data["test_type"] in {t.value for t in TestType}
    assert data["testing_method"] in {m.value for m in TestingMethod}
    assert data["result"] in {r.value for r in TestResultValue}
    assert data["status"] in {s.value for s in TestResultStatus}
    assert isinstance(data["is_current_official"], bool)


def assert_late_contribution_assessment(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in AssessmentStatus}
    assert data["severity_hint"] in {s.value for s in Severity}
    assert isinstance(data["amount_cents"], int)


def assert_audit_finding(data: dict):
    _assert_common(data)
    assert data["source"] in {s.value for s in FindingSource}
    assert data["category"] in {c.value for c in FindingCategory}
    assert data["severity"] in {s.value for s in Severity}
    assert data["status"] in {s.value for s in FindingStatus}


def assert_corrective_action(data: dict):
    _assert_common(data)
    assert data["action_type"] in {t.value for t in CorrectiveActionType}
    assert data["earnings_variant"] in {v.value for v in EarningsVariant}
    assert data["status"] in {s.value for s in CorrectiveActionStatus}
    assert isinstance(data["principal_cents"], int) and data["principal_cents"] > 0
    assert isinstance(data["earnings_cents"], int)
    assert isinstance(data["excise_tax_cents"], int)
    assert data["total_amount_cents"] == data["principal_cents"] + data["earnings_cents"], (
        f"total_amount_cents {data['total_amount_cents']} != principal "
        f"{data['principal_cents']} + earnings {data['earnings_cents']}"
    )


def assert_filing(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in FilingStatus}
    assert isinstance(data["is_amendment"], bool)
    assert isinstance(data["is_late"], bool)
    assert isinstance(data["penalty_cents"], int)
    assert isinstance(data["has_active_extension"], bool)


def assert_schedule_entry(data: dict):
    _assert_common(data)
    assert data["schedule_type"] in {t.value for t in ScheduleType}
    assert data["status"] in {s.value for s in ScheduleEntryStatus}
    assert isinstance(data["amount_cents"], int)


def assert_service_provider_fee(data: dict):
    _assert_common(data)
    assert data["service_code"] in {c.value for c in ServiceCode}
    assert data["compensation_type"] in {c.value for c in CompensationType}
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["reportable_on_schedule_c"], bool)


def assert_filing_extension(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in ExtensionStatus}


def assert_correction_program_filing(data: dict):
    _assert_common(data)
    assert data["program"] in {p.value for p in CorrectionProgram}
    assert data["status"] in {s.value for s in CorrectionProgramFilingStatus}
    assert isinstance(data["linked_finding_ids"], list)
    assert isinstance(data["government_fee_cents"], int)
