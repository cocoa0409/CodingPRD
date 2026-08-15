"""Entity assertions and domain invariant checkers.

Each assert_* helper validates the four common system-managed properties
(PRD section 2.4) plus the resource's documented fields.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(ts: str) -> datetime:
    """Parse an ISO 8601 instant tolerantly (Z or numeric offset)."""
    assert isinstance(ts, str) and ts, f"Expected non-empty timestamp, got {ts!r}"
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]


def assert_project(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"
    assert data["status"] in [
        "DRAFT", "SCOPED", "FIELD_AUTHORIZED", "FIELDWORK", "LAB_ANALYSIS",
        "REPORT_REVIEW", "ISSUED", "CONSTRUCTION_SUPPORT", "CLOSED",
    ]
    assert data["posture"] in ["OPEN", "FROZEN", "CLAIM_REVIEW"]
    assert isinstance(data["additional_committed_cents"], int)
    assert isinstance(data["claims_exposure_cents"], int)
    assert isinstance(data["testing_invoice_cents"], int)
    assert isinstance(data["total_fee_cents"], int)


def assert_boring_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "LOCKED",
                              "SUPERSEDED"]
    assert isinstance(data["revision_no"], int) and data["revision_no"] >= 1
    assert isinstance(data["planned_boring_count"], int)
    assert isinstance(data["mobilization_charged"], bool)


def assert_subcontractor(data: dict):
    _assert_common(data)
    assert data["standing"] in ["GOOD_STANDING", "SUSPENDED"]
    assert isinstance(data["license_no"], str) and data["license_no"]
    assert isinstance(data["committed_rig_hours"], (int, float))


def assert_rig_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "MOBILIZED", "DEMOBILIZED", "CANCELLED"]
    assert is_valid_uuid(data.get("boring_id", ""))
    assert is_valid_uuid(data.get("subcontractor_id", ""))
    parse_instant(data["window_start"])
    parse_instant(data["window_end"])


def assert_utility_clearance(data: dict):
    _assert_common(data)
    assert data["status"] in ["FILED", "CLEARED", "CONFLICT_MARKED", "EXPIRED"]
    assert isinstance(data["ticket_number"], str) and data["ticket_number"]
    assert isinstance(data["valid_days"], int) and data["valid_days"] >= 1
    parse_instant(data["issued_on"])
    parse_instant(data["expires_on"])


def assert_boring(data: dict):
    _assert_common(data)
    assert data["status"] in ["PLANNED", "SCHEDULED", "CLEARED", "DRILLED",
                              "LOGGED", "CLOSED", "REFUSED", "ABANDONED"]
    assert isinstance(data["boring_no"], str) and data["boring_no"]
    assert isinstance(data["planned_depth_ft"], (int, float))


def assert_sample(data: dict):
    _assert_common(data)
    assert data["custody_status"] in ["COLLECTED", "IN_TRANSIT", "LAB_RECEIVED",
                                      "CONSUMED", "ARCHIVED", "LOST"]
    assert data["sampler_type"] in ["SPT", "SHELBY", "BULK", "ROCK_CORE"]
    assert 0 <= data["recovery_pct"] <= 100
    assert data["uscs_class"] in [
        None, "GW", "GP", "GM", "GC", "SW", "SP", "SM", "SC", "ML", "CL",
        "OL", "MH", "CH", "OH", "PT",
    ]


def assert_lab_test_order(data: dict):
    _assert_common(data)
    assert data["status"] in ["REQUESTED", "AUTHORIZED", "IN_TEST",
                              "RESULT_SUBMITTED", "ACCEPTED", "REJECTED"]
    assert data["test_type"] in [
        "MOISTURE_CONTENT", "ATTERBERG", "SIEVE_ANALYSIS",
        "UNCONFINED_COMPRESSION", "DIRECT_SHEAR", "CONSOLIDATION", "PROCTOR",
    ]
    assert data["priority"] in ["STANDARD", "RUSH"]
    assert isinstance(data["fee_cents"], int)
    assert isinstance(data["rerun_count"], int) and data["rerun_count"] >= 0


def assert_lab_test_result(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("lab_test_order_id", ""))
    assert isinstance(data["submitted_by_user_id"], str)


def assert_foundation_analysis(data: dict):
    _assert_common(data)
    assert data["status"] in ["PRELIMINARY", "VERIFIED", "SUPERSEDED"]
    assert data["data_status"] in ["CURRENT", "STALE"]
    assert data["method"] in ["ALLOWABLE_STRESS", "LRFD"]


def assert_report(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "TECH_REVIEW", "PE_REVIEW", "ISSUED",
                              "SUPERSEDED"]
    assert isinstance(data["revision_no"], int) and data["revision_no"] >= 1
    assert isinstance(data["prepared_by_user_id"], str)


def assert_observation_visit(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "PERFORMED", "FINDINGS_FILED",
                              "CLOSED"]
    parse_instant(data["visit_date"])


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ["SUBMITTED", "UNDER_REVIEW", "SUBSTANTIATED",
                              "REBUTTED", "SETTLED"]
    assert isinstance(data["claimed_amount_cents"], int)
    assert isinstance(data["appeal_count"], int) and data["appeal_count"] >= 0


def assert_exploration_authorization(data: dict):
    _assert_common(data)
    assert data["status"] in ["PROPOSED", "APPROVED", "REVOKED", "EXHAUSTED"]
    assert isinstance(data["authorized_amount_cents"], int)
    assert isinstance(data["extra_boring_count"], int)
    assert isinstance(data["consumed_boring_count"], int)
