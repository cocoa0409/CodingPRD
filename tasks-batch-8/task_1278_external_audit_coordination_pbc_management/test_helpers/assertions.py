"""Entity assertions and domain invariant checkers.

Field-level checks assert only what PRD prose names: the common fields of
PRD §2.4 plus each entity's PRD-stated fields and status vocabularies.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

ENGAGEMENT_STATUSES = [
    "PLANNING", "FIELDWORK", "FIELDWORK_COMPLETE", "REPORT_ISSUED", "CANCELLED",
]
ENGAGEMENT_POSTURES = ["OPEN", "CLOSING", "LOCKED"]
PBC_STATUSES = [
    "OPEN", "IN_PROGRESS", "SUBMITTED", "ACCEPTED", "REJECTED", "FROZEN",
]
EVIDENCE_STATUSES = [
    "PENDING_REVIEW", "ACCEPTED", "REJECTED", "SUPERSEDED", "INVALIDATED",
]
QUERY_STATUSES = ["OPEN", "AWAITING_CLIENT", "RESPONDED", "CLOSED", "ESCALATED"]
QUERY_SEVERITIES = ["LOW", "MEDIUM", "HIGH"]
SAMPLING_STATUSES = ["DRAFT", "DISPATCHED", "IN_PROGRESS", "COMPLETE", "CANCELLED"]
VISIT_STATUSES = ["SCHEDULED", "COMPLETED", "CANCELLED"]
ADJUSTMENT_DISPOSITIONS = ["PROPOSED", "ACCEPTED", "REJECTED", "PASSED"]
ADJUSTMENT_DIRECTIONS = ["DEBIT", "CREDIT"]
REP_LETTER_STATUSES = ["DRAFT", "PENDING_SIGNATURE", "SIGNED"]
FEE_CHANGE_STATUSES = ["PROPOSED", "APPROVED", "REJECTED", "WITHDRAWN"]
FEE_PROPOSER_ROLES = ["CONTROLLER_OFFICE", "AUDITOR"]


def _assert_common_fields(data: dict, entity: str):
    """PRD §2.4: id (UUID), created_at/updated_at (ISO 8601), version (int)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def assert_engagement(data: dict):
    _assert_common_fields(data, "AuditEngagement")
    assert isinstance(data["client_name"], str) and data["client_name"]
    assert isinstance(data["fiscal_year_end"], str) and data["fiscal_year_end"]
    assert isinstance(data["filing_deadline"], str) and data["filing_deadline"]
    assert isinstance(data["base_fee_cents"], int)
    assert isinstance(data["materiality_cents"], int)
    assert isinstance(data["total_fee_cents"], int)
    assert isinstance(data["open_pbc_count"], int)
    assert isinstance(data["open_query_count"], int)
    assert isinstance(data["passed_adjustment_total_cents"], int)
    assert data["status"] in ENGAGEMENT_STATUSES
    assert data["posture"] in ENGAGEMENT_POSTURES


def assert_location(data: dict):
    _assert_common_fields(data, "Location")
    assert isinstance(data["engagement_id"], str) and data["engagement_id"]
    assert isinstance(data["location_code"], str) and data["location_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["materiality_cents"], int)


def assert_pbc_request(data: dict):
    _assert_common_fields(data, "PBCRequest")
    assert isinstance(data["engagement_id"], str) and data["engagement_id"]
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["owner_user_id"], str) and data["owner_user_id"]
    assert isinstance(data["due_date"], str) and data["due_date"]
    assert "current_evidence_id" in data, \
        "current_evidence_id must be present (null until first acceptance)"
    assert isinstance(data["rejection_count"], int)
    assert data["status"] in PBC_STATUSES


def assert_evidence_upload(data: dict):
    _assert_common_fields(data, "EvidenceUpload")
    assert isinstance(data["pbc_request_id"], str) and data["pbc_request_id"]
    assert isinstance(data["engagement_id"], str) and data["engagement_id"]
    assert isinstance(data["uploader_user_id"], str) and data["uploader_user_id"]
    assert isinstance(data["version_seq"], int) and data["version_seq"] >= 1
    assert isinstance(data["file_name"], str) and data["file_name"]
    assert isinstance(data["file_size_bytes"], int)
    assert isinstance(data["sha256"], str) and len(data["sha256"]) == 64
    assert is_iso8601_timestamp(data.get("uploaded_at", "")), \
        "EvidenceUpload.uploaded_at must be ISO 8601"
    assert data["status"] in EVIDENCE_STATUSES


def assert_query(data: dict):
    _assert_common_fields(data, "AuditorQuery")
    assert isinstance(data["engagement_id"], str) and data["engagement_id"]
    assert isinstance(data["auditor_user_id"], str) and data["auditor_user_id"]
    assert isinstance(data["subject"], str) and data["subject"]
    assert data["severity"] in QUERY_SEVERITIES
    assert is_iso8601_timestamp(data.get("raised_at", "")), \
        "AuditorQuery.raised_at must be ISO 8601"
    assert "responded_at" in data, "responded_at present (null until responded)"
    assert "turnaround_hours" in data, \
        "turnaround_hours present (null until responded)"
    assert data["status"] in QUERY_STATUSES


def assert_sampling_request(data: dict):
    _assert_common_fields(data, "SamplingRequest")
    assert isinstance(data["engagement_id"], str) and data["engagement_id"]
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["location_ids"], list)
    assert isinstance(data["window_start"], str) and data["window_start"]
    assert isinstance(data["window_end"], str) and data["window_end"]
    assert isinstance(data["sample_size"], int)
    assert data["status"] in SAMPLING_STATUSES


def assert_fieldwork_visit(data: dict):
    _assert_common_fields(data, "FieldworkVisit")
    assert isinstance(data["engagement_id"], str) and data["engagement_id"]
    assert isinstance(data["auditor_user_id"], str) and data["auditor_user_id"]
    assert isinstance(data["location_id"], str) and data["location_id"]
    assert isinstance(data["visit_start"], str) and data["visit_start"]
    assert isinstance(data["visit_end"], str) and data["visit_end"]
    assert data["status"] in VISIT_STATUSES


def assert_adjustment(data: dict):
    _assert_common_fields(data, "AuditAdjustment")
    assert isinstance(data["engagement_id"], str) and data["engagement_id"]
    assert isinstance(data["proposed_by_user_id"], str) \
        and data["proposed_by_user_id"]
    assert isinstance(data["description"], str) and data["description"]
    assert isinstance(data["amount_cents"], int)
    assert data["direction"] in ADJUSTMENT_DIRECTIONS
    assert data["disposition"] in ADJUSTMENT_DISPOSITIONS
    assert "disposition_rationale" in data, \
        "disposition_rationale present (null until REJECTED/PASSED)"
    assert "disposition_by_user_id" in data, \
        "disposition_by_user_id present (null until dispositioned)"


def assert_representation_letter(data: dict):
    _assert_common_fields(data, "RepresentationLetter")
    assert isinstance(data["engagement_id"], str) and data["engagement_id"]
    assert data["status"] in REP_LETTER_STATUSES


def assert_fee_change_request(data: dict):
    _assert_common_fields(data, "FeeChangeRequest")
    assert isinstance(data["engagement_id"], str) and data["engagement_id"]
    assert data["proposed_by_role"] in FEE_PROPOSER_ROLES
    assert isinstance(data["scope_description"], str) \
        and data["scope_description"]
    assert isinstance(data["delta_cents"], int)
    assert data["status"] in FEE_CHANGE_STATUSES


def assert_engagement_counters(engagement: dict):
    """PRD §2.6/§3.1 invariants: derived counters are never negative."""
    assert engagement["open_pbc_count"] >= 0, "open_pbc_count must be >= 0"
    assert engagement["open_query_count"] >= 0, "open_query_count must be >= 0"
    assert engagement["passed_adjustment_total_cents"] >= 0, \
        "passed_adjustment_total_cents must be >= 0"
    assert engagement["total_fee_cents"] > 0, "total_fee_cents must be > 0"
