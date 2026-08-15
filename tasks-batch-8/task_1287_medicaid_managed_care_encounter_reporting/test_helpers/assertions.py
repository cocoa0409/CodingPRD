"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"{label}.version must be a positive int"


def assert_program(data: dict):
    _assert_common_fields(data, "Program")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["posture"] in ("OPEN", "RESTRICTED")
    assert isinstance(data["penalties_outstanding_cents"], int)
    assert data["penalties_outstanding_cents"] >= 0
    assert isinstance(data["penalty_threshold_cents"], int)


def assert_member(data: dict):
    _assert_common_fields(data, "Member")
    assert data["aid_category"] in ("TANF", "SSI", "DUAL", "EXPANSION", "CHIP")
    assert data["status"] in ("ACTIVE", "DISENROLLED")


def assert_provider(data: dict):
    _assert_common_fields(data, "Provider")
    assert data["contract_status"] in ("ACTIVE", "SUSPENDED")
    assert data["quality_tier"] in ("GREEN", "YELLOW", "RED")


def assert_submitter(data: dict):
    _assert_common_fields(data, "Submitter")
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_cycle(data: dict):
    _assert_common_fields(data, "SubmissionCycle")
    assert data["status"] in ("OPEN", "CLOSED")
    assert data["extension_status"] in ("NONE", "PENDING", "APPROVED", "DENIED")
    assert isinstance(data["intake_encounter_count"], int)
    assert isinstance(data["net_accepted_encounter_count"], int)
    assert isinstance(data["net_accepted_paid_cents"], int)


def assert_rate_schedule(data: dict):
    _assert_common_fields(data, "CapitationRateSchedule")
    assert data["aid_category"] in ("TANF", "SSI", "DUAL", "EXPANSION", "CHIP")
    assert isinstance(data["pmpm_cents"], int) and data["pmpm_cents"] > 0


def assert_encounter(data: dict):
    _assert_common_fields(data, "Encounter")
    assert data["status"] in (
        "RECEIVED", "VALIDATED", "REJECTED", "STAGED", "SUBMITTED",
        "ACKNOWLEDGED", "DENIED", "VOIDED", "SUPERSEDED",
    )
    assert isinstance(data["correction_sequence"], int)
    assert isinstance(data["validation_run_seq"], int)
    assert isinstance(data["paid_amount_cents"], int)


def assert_encounter_line(data: dict):
    """Append-only child row: id + created_at present; updated_at/version absent."""
    assert is_valid_uuid(data.get("id", "")), "EncounterLine.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "EncounterLine.created_at must be ISO 8601"
    assert "updated_at" not in data, "EncounterLine must not carry updated_at"
    assert "version" not in data, "EncounterLine must not carry version"
    assert isinstance(data["line_number"], int) and data["line_number"] >= 1
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert data["paid_amount_cents"] <= data["billed_amount_cents"]


def assert_validation_finding(data: dict):
    """Append-only child row: id + created_at present; updated_at/version absent."""
    assert is_valid_uuid(data.get("id", "")), "ValidationFinding.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "ValidationFinding.created_at must be ISO 8601"
    assert "updated_at" not in data, "ValidationFinding must not carry updated_at"
    assert "version" not in data, "ValidationFinding must not carry version"
    assert data["tier"] in ("SYNTAX", "REFERENTIAL", "BUSINESS")
    assert data["severity"] in ("FATAL", "WARN")
    assert data["origin"] in ("MCO_EDIT", "STATE_ACK")


def assert_batch(data: dict):
    _assert_common_fields(data, "SubmissionBatch")
    assert data["status"] in (
        "DRAFT", "SEALED", "TRANSMITTED", "ACKNOWLEDGED",
        "PARTIAL", "REJECTED_BATCH", "RECONCILED", "DISCARDED",
    )
    assert isinstance(data["encounter_count"], int)
    assert isinstance(data["total_paid_cents"], int)
    assert isinstance(data.get("late", False), bool)


def assert_audit(data: dict):
    _assert_common_fields(data, "Audit")
    assert data["status"] in ("DRAFT", "DETERMINED")
    assert isinstance(data["sample_size"], int) and data["sample_size"] >= 1
    assert isinstance(data["defect_count"], int) and 0 <= data["defect_count"] <= data["sample_size"]


def assert_penalty(data: dict):
    _assert_common_fields(data, "PenaltyAssessment")
    assert data["reason"] in ("COMPLETENESS", "ACCURACY", "COMBINED", "LATE_SUBMISSION")
    assert data["status"] in ("ASSESSED", "APPEALED", "UPHELD", "WAIVED", "REDUCED", "PAID")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0


def assert_statement(data: dict):
    _assert_common_fields(data, "CapitationStatement")
    assert data["status"] in ("PROVISIONAL_ISSUED", "RECONCILED")
    assert isinstance(data["member_months"], int)
    assert isinstance(data["provisional_paid_cents"], int)
    assert isinstance(data.get("withhold_applied", False), bool)


def assert_risk_snapshot(data: dict):
    _assert_common_fields(data, "RiskScoreSnapshot")
    assert data["status"] in ("COMPUTED", "APPLIED")
    assert isinstance(data["raw_score"], (int, float))
    assert isinstance(data["normalized_score"], (int, float))


def assert_scorecard(data: dict):
    _assert_common_fields(data, "ProviderScorecard")
    assert data["status"] in ("OPEN", "ACKNOWLEDGED")
    assert data["tier"] in ("GREEN", "YELLOW", "RED")
    assert isinstance(data["run_count"], int)
    assert isinstance(data["fatal_finding_count"], int)


def assert_program_invariants(data: dict):
    """Domain invariants that must hold after any operation on a Program."""
    assert data["penalties_outstanding_cents"] >= 0
    if data["penalties_outstanding_cents"] >= data["penalty_threshold_cents"]:
        assert data["posture"] == "RESTRICTED", (
            f"posture must be RESTRICTED when outstanding {data['penalties_outstanding_cents']} "
            f">= threshold {data['penalty_threshold_cents']}"
        )
    else:
        assert data["posture"] == "OPEN", (
            f"posture must be OPEN when outstanding {data['penalties_outstanding_cents']} "
            f"< threshold {data['penalty_threshold_cents']}"
        )
