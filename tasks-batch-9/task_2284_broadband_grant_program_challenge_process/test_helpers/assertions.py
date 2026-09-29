"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ApplicationState,
    AuditState,
    AwardState,
    CapabilityState,
    ChallengeState,
    ClaimState,
    ClassificationSource,
    ClassificationStatus,
    ComplianceState,
    EhpState,
    EligibilityState,
    EvidenceState,
    LedgerEntryType,
    MilestoneState,
    ProgramState,
    ScoreState,
    ScoringPosture,
    ServiceState,
    SubmitterSide,
)


def _assert_versioned_common_fields(data: dict, label: str):
    """Every grant resource family carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1"


def _assert_append_only_common_fields(data: dict, label: str):
    """Append-only records carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be an ISO 8601 UTC timestamp"
    assert (
        "updated_at" not in data
    ), f"{label} is append-only and must not expose updated_at"
    assert "version" not in data, f"{label} is append-only and must not expose version"


def assert_grant_program(data: dict):
    _assert_versioned_common_fields(data, "GrantProgram")
    assert data["program_state"] in [s.value for s in ProgramState]
    assert data["scoring_posture"] in [s.value for s in ScoringPosture]
    assert isinstance(data["total_appropriation_cents"], int)
    assert data["total_appropriation_cents"] > 0
    assert_program_balance_invariant(data)


def assert_program_balance_invariant(data: dict):
    """total_appropriation_cents equals the sum of the three balances."""
    total = data["total_appropriation_cents"]
    uncommitted = data["uncommitted_balance_cents"]
    obligated = data["obligated_balance_cents"]
    disbursed = data["disbursed_balance_cents"]
    assert total == uncommitted + obligated + disbursed, (
        f"Appropriation ledger invariant broken: {total} != {uncommitted} + "
        f"{obligated} + {disbursed}"
    )


def assert_eligible_location(data: dict):
    _assert_versioned_common_fields(data, "EligibleLocation")
    assert data["classification_status"] in [s.value for s in ClassificationStatus]
    assert data["classification_source"] in [s.value for s in ClassificationSource]
    assert data["eligibility_state"] in [s.value for s in EligibilityState]
    assert data["service_state"] in [s.value for s in ServiceState]
    assert isinstance(data["challenge_count"], int) and data["challenge_count"] >= 0


def assert_challenge(data: dict):
    _assert_versioned_common_fields(data, "Challenge")
    assert data["challenge_state"] in [s.value for s in ChallengeState]
    assert isinstance(data["rebuttal_round"], int)
    assert isinstance(data["resubmission_count"], int)
    assert_two_decimal_places(
        data["evidence_sufficiency_score"], "evidence_sufficiency_score"
    )
    assert_two_decimal_places(data["rebuttal_strength_score"], "rebuttal_strength_score")


def assert_challenge_evidence(data: dict):
    _assert_append_only_common_fields(data, "ChallengeEvidence")
    assert data["evidence_state"] in [s.value for s in EvidenceState]
    assert data["submitter_side"] in [s.value for s in SubmitterSide]
    assert_two_decimal_places(data["weighted_value"], "weighted_value")


def assert_subgrantee(data: dict):
    _assert_versioned_common_fields(data, "Subgrantee")
    assert data["capability_state"] in [s.value for s in CapabilityState]
    assert isinstance(data["remediation_count"], int)
    assert isinstance(data["withdrawn_personnel_count"], int)


def assert_application(data: dict):
    _assert_versioned_common_fields(data, "Application")
    assert data["application_state"] in [s.value for s in ApplicationState]
    assert isinstance(data["claim_count"], int)
    assert isinstance(data["confirmed_location_count"], int)
    assert data["confirmed_location_count"] <= data["claim_count"], (
        "confirmed_location_count counts the narrower claim set and can never "
        "exceed claim_count"
    )


def assert_location_claim(data: dict):
    _assert_versioned_common_fields(data, "LocationClaim")
    assert data["claim_state"] in [s.value for s in ClaimState]
    assert isinstance(data["claimed_cost_cents"], int)
    assert data["claimed_cost_cents"] > 0


def assert_score_sheet(data: dict):
    _assert_versioned_common_fields(data, "ScoreSheet")
    assert data["score_state"] in [s.value for s in ScoreState]
    for field in (
        "cost_points",
        "speed_points",
        "affordability_points",
        "workforce_points",
        "total_score",
    ):
        assert_two_decimal_places(data[field], field)
    assert data["cost_points"] <= 30.00
    assert data["speed_points"] <= 30.00
    assert data["affordability_points"] <= 20.00
    assert data["workforce_points"] <= 20.00
    assert data["total_score"] <= 100.00, "total_score is capped at 100.00"


def assert_award(data: dict):
    _assert_versioned_common_fields(data, "Award")
    assert data["award_state"] in [s.value for s in AwardState]
    assert data["compliance_state"] in [s.value for s in ComplianceState]
    assert isinstance(data["obligation_amount_cents"], int)
    assert isinstance(data["holdback_cap_cents"], int)
    assert isinstance(data["disbursed_to_date_cents"], int)


def assert_environmental_review(data: dict):
    _assert_versioned_common_fields(data, "EnvironmentalReview")
    assert data["ehp_state"] in [s.value for s in EhpState]


def assert_milestone(data: dict):
    _assert_versioned_common_fields(data, "Milestone")
    assert data["milestone_state"] in [s.value for s in MilestoneState]
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert isinstance(data["resubmission_count"], int)


def assert_compliance_audit(data: dict):
    _assert_versioned_common_fields(data, "ComplianceAudit")
    assert data["audit_state"] in [s.value for s in AuditState]
    assert isinstance(data["appeal_count"], int)


def assert_ledger_entry(data: dict):
    _assert_append_only_common_fields(data, "LedgerEntry")
    assert data["entry_type"] in [t.value for t in LedgerEntryType]
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] > 0, (
        "amount_cents is strictly positive; the sign is implied by entry_type"
    )


# ------------------------------------------------------------------ numerics


def assert_two_decimal_places(value, label="value"):
    """Score components, evidence weights and capability components are decimal
    numbers carried to exactly 2 decimal places."""
    assert value is not None, f"{label} must not be null"
    rounded = round(float(value) + 1e-12, 2)
    assert abs(float(value) - rounded) < 1e-9, (
        f"{label} must carry at most 2 decimal places, got {value}"
    )


def assert_four_decimal_places(value, label="noncompliant_share"):
    """An audit's noncompliant_share is rounded to 4 decimal places."""
    assert value is not None, f"{label} must not be null"
    rounded = round(float(value) + 1e-14, 4)
    assert abs(float(value) - rounded) < 1e-9, (
        f"{label} must carry at most 4 decimal places, got {value}"
    )


def assert_integer_cents(value, label="amount"):
    """Money is held in integer cents throughout; there are no fractional cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )


def assert_ledger_reconciliation(program: dict, entries: list):
    """Re-derive the three balances from the complete set of ledger entries."""

    def _sum(entry_type):
        return sum(e["amount_cents"] for e in entries if e["entry_type"] == entry_type)

    obligation = _sum("OBLIGATION")
    disbursement = _sum("DISBURSEMENT")
    deobligation = _sum("DEOBLIGATION")
    recovery = _sum("CLAWBACK_RECOVERY")

    expected_uncommitted = (
        program["total_appropriation_cents"] - obligation + deobligation + recovery
    )
    expected_obligated = obligation - deobligation - disbursement
    expected_disbursed = disbursement - recovery

    assert program["uncommitted_balance_cents"] == expected_uncommitted
    assert program["obligated_balance_cents"] == expected_obligated
    assert program["disbursed_balance_cents"] == expected_disbursed
    assert_program_balance_invariant(program)


def assert_error_envelope_meta(response):
    """An error envelope's meta object carries only the request id and timestamp."""
    body = response.json()
    assert body["response_type"] == "error"
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", ""))
