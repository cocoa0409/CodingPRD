"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, status_values, context: str):
    assert is_valid_uuid(data.get("id", "")), f"{context}: id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{context}: created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{context}: updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{context}: version must be a positive integer, got {data.get('version')}"
    )
    assert data.get("status") in status_values, (
        f"{context}: status must be one of {status_values}, got {data.get('status')}"
    )


def assert_contact(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Contact.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Contact.created_at must be ISO 8601"
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("email"), str) and data["email"]


def assert_process(data: dict):
    _assert_common(data, {"DRAFT", "ACTIVE", "SUSPENDED", "RETIRED"}, "Process")
    assert data.get("criticality_tier") in {"TIER_1", "TIER_2", "TIER_3"}
    assert isinstance(data.get("name"), str) and data["name"]


def assert_bia(data: dict):
    _assert_common(data, {"DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED"}, "Bia")
    assert data.get("score_variant") in {"PROVISIONAL", "FINAL"}
    assert isinstance(data.get("criticality_score"), (int, float))


def assert_plan(data: dict):
    _assert_common(data, {"DRAFT", "IN_REVIEW", "APPROVED", "RETIRED"}, "Plan")
    assert data.get("strategy_type") in {"ACTIVE_ACTIVE", "WARM_SITE", "COLD_SITE", "MANUAL_WORKAROUND"}


def assert_plan_section(data: dict):
    assert is_valid_uuid(data.get("id", "")), "PlanSection.id must be a valid UUID"
    assert data.get("section_type") in {
        "SCOPE", "RECOVERY_STRATEGY", "DEPENDENCY_MAP", "COMMS_PLAN",
        "SITE_STRATEGY", "WORKFORCE_STRATEGY", "VALIDATION_STRATEGY", "ATTESTATION_MAP",
    }
    assert isinstance(data.get("order_index"), int)
    assert isinstance(data.get("required_flag"), bool)


def assert_dependency(data: dict):
    # Dependency carries only id + created_at; updated_at/version must be absent (PRD §2.5).
    assert is_valid_uuid(data.get("id", "")), "Dependency.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Dependency.created_at must be ISO 8601"
    assert "updated_at" not in data, "Dependency must not carry updated_at"
    assert "version" not in data, "Dependency must not carry version"
    assert data.get("dependency_type") in {"DATA", "STAFF", "FACILITY", "VENDOR", "SYSTEM"}
    assert data.get("criticality") in {"HIGH", "MEDIUM", "LOW"}


def assert_third_party(data: dict):
    _assert_common(data, {"ONBOARDING", "ACTIVE", "SUSPENDED", "EXITED"}, "ThirdParty")
    assert data.get("criticality_rating") in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}


def assert_assessment(data: dict):
    _assert_common(data, {"DRAFT", "FINALIZED"}, "Assessment")
    assert data.get("score_variant") in {"PROVISIONAL", "FINAL"}
    assert isinstance(data.get("continuity_score"), int)
    assert isinstance(data.get("meets_required_rto"), bool)


def assert_alternate_site(data: dict):
    _assert_common(data, {"ACTIVE", "RETIRED"}, "AlternateSite")
    assert data.get("site_type") in {"HOT", "WARM", "COLD", "WORK_AREA_RECOVERY"}
    assert isinstance(data.get("capacity_seats"), int)


def assert_site_reservation(data: dict):
    _assert_common(data, {"CONFIRMED", "RELEASED"}, "SiteReservation")
    assert data.get("purpose") in {"EXERCISE", "INCIDENT"}
    assert isinstance(data.get("seats_reserved"), int)


def assert_exercise(data: dict):
    _assert_common(data, {"SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED"}, "Exercise")
    assert data.get("exercise_type") in {"TABLETOP", "FAILOVER"}
    assert isinstance(data.get("requires_capability_check"), bool)


def assert_finding(data: dict):
    _assert_common(data, {"OPEN", "REMEDIATING", "VERIFIED", "REJECTED"}, "Finding")
    assert data.get("severity") in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}


def assert_recovery_capability(data: dict):
    _assert_common(data, {"UNPROVEN", "VALIDATED", "GAP_IDENTIFIED", "REMEDIATED"}, "RecoveryCapability")
    assert data.get("capability_type") in {"SITE", "WORKFORCE", "DATA_RESTORE", "VENDOR_FAILOVER"}
    assert data.get("validation_freshness") in {"CURRENT", "STALE", "NEVER"}


def assert_validation_run(data: dict):
    _assert_common(data, {"RECORDED", "SUPERSEDED"}, "ValidationRun")
    assert data.get("method") in {"FAILOVER", "SIMULATION", "COMPONENT_TEST"}
    assert data.get("result") in {"VALIDATED", "GAP_IDENTIFIED"}


def assert_gap(data: dict):
    _assert_common(data, {"OPEN", "IN_PROGRESS", "CLOSED", "ACCEPTED_RISK"}, "Gap")
    assert data.get("gap_type") in {"CAPABILITY", "FINDING"}
    assert data.get("severity") in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    assert isinstance(data.get("overdue"), bool)


def assert_comm_node(data: dict):
    assert is_valid_uuid(data.get("id", "")), "CommNode.id must be a valid UUID"
    assert data.get("channel") in {"PHONE", "EMAIL", "SMS"}
    assert isinstance(data.get("active_flag"), bool)


def assert_activation(data: dict):
    _assert_common(data, {"ACTIVE", "ALL_NOTIFIED", "ACKNOWLEDGED", "DEACTIVATED"}, "Activation")
    assert data.get("declared_severity") in {"SEV1", "SEV2", "SEV3"}
    assert isinstance(data.get("expected_notifications"), int)
    assert isinstance(data.get("notified_count"), int)
    assert isinstance(data.get("acked_count"), int)


def assert_attestation(data: dict):
    _assert_common(data, {"DRAFT", "SIGNED", "REVOKED"}, "Attestation")
    assert data.get("attestation_type") in {"REGULATORY", "CUSTOMER"}
    assert isinstance(data.get("readiness_score"), int)


def assert_notification(data: dict):
    # Notification carries only id + created_at; updated_at/version must be absent (PRD §2.5).
    assert is_valid_uuid(data.get("id", "")), "Notification.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Notification.created_at must be ISO 8601"
    assert "updated_at" not in data, "Notification must not carry updated_at"
    assert "version" not in data, "Notification must not carry version"
    assert data.get("status") in {"SENT", "ACKED"}
    assert data.get("channel") in {"PHONE", "EMAIL", "SMS"}
