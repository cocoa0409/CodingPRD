"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_instant_equals(actual, expected):
    """Compare two ISO-8601 timestamps as instants.

    PRD pins timestamp VALUES (e.g. due_at is "an exact instant at second
    precision", section 3.4) but does not pin the serialization of the
    fractional-second component for domain timestamps, so comparisons must be
    made on the instant, not the string.
    """
    def _parse(ts):
        return datetime.fromisoformat(
            str(ts).strip().replace("Z", "+00:00")).astimezone(timezone.utc)
    assert _parse(actual) == _parse(expected), (
        f"{actual!r} != {expected!r} as instants")


def _assert_common(data: dict, what: str):
    assert is_valid_uuid(data.get("id", "")), f"{what}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{what}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{what}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{what}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_hospital(data: dict):
    _assert_common(data, "ClientHospital")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert data["status"] in ["ONBOARDING", "ACTIVE", "SUSPENDED"]
    assert data["credentialing_mode"] in ["BY_PROXY", "INDEPENDENT"]
    assert data["pricing_mode"] in ["MARGINAL", "FLAT_TIER"]
    for field in ("tat_stat_minutes", "tat_urgent_minutes", "tat_routine_minutes",
                  "penalty_per_breach_minute_cents", "breach_penalty_cap_cents"):
        assert isinstance(data[field], int), f"ClientHospital.{field} must be an integer"


def assert_radiologist(data: dict):
    _assert_common(data, "Radiologist")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["subspecialties"], list)
    assert isinstance(data["license_states"], list)
    assert data["status"] in ["ACTIVE", "ON_LEAVE", "INACTIVE"]
    assert isinstance(data["reserved_rvu"], (int, float))
    assert isinstance(data["completed_rvu_24h"], (int, float))
    assert isinstance(data["stat_active_count"], int)
    assert isinstance(data["pending_critical_count"], int)


def assert_shift(data: dict):
    _assert_common(data, "CoverageShift")
    assert is_valid_uuid(data.get("radiologist_id", "")), "shift.radiologist_id must be a UUID"
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))
    assert isinstance(data["modalities"], list)
    assert data["status"] in ["SCHEDULED", "ACTIVE", "COMPLETED", "CANCELLED"]


def assert_routing_policy(data: dict):
    _assert_common(data, "RoutingPolicy")
    assert data["modality"] in ["CT", "MR", "XR", "US", "NM", "MG"]
    assert data["body_part_group"] in ["NEURO", "BODY", "MSK", "CHEST", "VASCULAR", "OTHER"]
    assert data["priority"] in ["STAT", "URGENT", "ROUTINE"]
    assert data["required_subspecialty"] in ["NEURORAD", "MSK", "BODY", "CHEST", "PEDS", "GENERAL"]
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_study(data: dict):
    _assert_common(data, "Study")
    assert data["modality"] in ["CT", "MR", "XR", "US", "NM", "MG"]
    assert data["body_part_group"] in ["NEURO", "BODY", "MSK", "CHEST", "VASCULAR", "OTHER"]
    assert data["priority"] in ["STAT", "URGENT", "ROUTINE"]
    assert data["status"] in [
        "RECEIVED", "QUEUED", "ASSIGNED", "IN_PROGRESS",
        "PRELIMINARY_SIGNED", "FINAL_SIGNED", "AMENDMENT_PENDING", "CANCELLED",
    ]
    assert is_iso8601_timestamp(data.get("received_at", ""))
    assert is_iso8601_timestamp(data.get("due_at", ""))
    assert isinstance(data["excluded_radiologist_ids"], list)
    assert isinstance(data["addendum_count"], int)
    assert isinstance(data["tat_breached"], bool)
    assert isinstance(data["breach_minutes"], int)


def assert_assignment(data: dict):
    _assert_common(data, "Assignment")
    assert data["phase"] in ["PRELIMINARY", "FINAL"]
    assert data["status"] in ["ACTIVE", "COMPLETED", "RELEASED"]
    assert isinstance(data["reserved_rvu"], (int, float))
    assert isinstance(data["auto_selected"], bool)


def assert_report(data: dict):
    _assert_common(data, "Report")
    assert data["report_type"] in ["PRELIMINARY", "FINAL", "ADDENDUM"]
    assert data["status"] in ["DRAFT", "SIGNED", "SUPERSEDED"]
    assert isinstance(data["credited_rvu"], (int, float))


def assert_discrepancy_case(data: dict):
    _assert_common(data, "DiscrepancyCase")
    assert data["origin"] in ["AUTO", "MANUAL"]
    assert data["status"] in ["OPEN", "PEER_REVIEW", "ESCALATED_QI", "RECONCILED", "NO_ACTION_CLOSED"]
    assert isinstance(data["grade"], int)


def assert_critical_notice(data: dict):
    _assert_common(data, "CriticalResultNotice")
    assert data["status"] in ["PENDING", "NOTIFIED", "ESCALATED", "READBACK_CONFIRMED"]
    assert isinstance(data["escalation_count"], int)


def assert_credential_grant(data: dict):
    _assert_common(data, "CredentialGrant")
    assert data["grant_type"] in ["BY_PROXY", "INDEPENDENT"]
    assert data["status"] in ["PENDING", "GRANTED", "SUSPENDED", "REVOKED", "EXPIRED"]


def assert_billing_period(data: dict):
    _assert_common(data, "BillingPeriod")
    assert data["status"] in ["OPEN", "CLOSED", "INVOICED"]


def assert_invoice(data: dict):
    _assert_common(data, "Invoice")
    assert data["status"] in ["CURRENT", "VOID"]
    assert data["pricing_mode_snapshot"] in ["MARGINAL", "FLAT_TIER"]
    assert isinstance(data["billable_study_count"], int)
    assert isinstance(data["line_items"], list)
    for field in ("critical_addon_cents", "gross_cents", "penalty_credits_cents", "total_cents"):
        assert isinstance(data[field], int), f"Invoice.{field} must be integer cents"


def assert_radiologist_utilization_invariants(data: dict):
    """Domain invariants on the radiologist capacity ledger."""
    assert data["reserved_rvu"] >= 0, "reserved_rvu must be non-negative"
    assert data["completed_rvu_24h"] >= 0, "completed_rvu_24h must be non-negative"
    assert data["reserved_rvu"] + data["completed_rvu_24h"] <= data["fatigue_cap_rvu"] + 1e-9, (
        "utilization may reach but never exceed the fatigue cap"
    )
    assert data["stat_active_count"] >= 0
    assert data["pending_critical_count"] >= 0
