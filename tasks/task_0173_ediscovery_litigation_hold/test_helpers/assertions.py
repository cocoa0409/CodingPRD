"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

LIFECYCLE_STATES = {"OPEN", "IN_DISCOVERY", "CLOSING", "CLOSED"}
HOLD_STATES = {"NO_HOLD", "HOLD_ACTIVE", "HOLD_RELEASED"}
ACK_STATES = {"NONE", "PENDING", "ACKNOWLEDGED"}
LEGAL_HOLD_STATES = {"DRAFT", "ISSUED", "ACKNOWLEDGED", "RELEASED"}
ACK_RECORD_STATES = {"PENDING", "ACKNOWLEDGED"}
SCOPE_STATES = {"DEFINED", "COLLECTING", "COLLECTED", "PROCESSED", "RELEASED"}
DOC_STATES = {"COLLECTED", "DUPLICATE", "UNIQUE", "PURGEABLE"}
PRIVILEGE_TAGS = {"UNREVIEWED", "NOT_PRIVILEGED", "PRIVILEGED", "REDACTED"}
RESPONSIVENESS_TAGS = {"UNREVIEWED", "RESPONSIVE", "NON_RESPONSIVE"}
JOB_STATES = {"QUEUED", "RUNNING", "COMPLETED", "FAILED"}
BATCH_STATES = {"DRAFT", "IN_REVIEW", "QC_REVIEW", "COMPLETED"}
DECISIONS = {
    "UNDECIDED",
    "RESPONSIVE_NOT_PRIV",
    "RESPONSIVE_PRIV",
    "RESPONSIVE_REDACTED",
    "NON_RESPONSIVE",
}
PRODUCTION_SET_STATES = {"DRAFT", "VALIDATING", "BLOCKED", "STAGED", "PRODUCED"}
PRODUCTION_ITEM_STATES = {"STAGED", "PRODUCED", "CLAWED_BACK"}
CLAWBACK_STATES = {"REQUESTED", "SEQUESTERED", "DISPUTED"}


def _assert_common_fields(data: dict):
    """Full common-field set: id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 and increments"


def assert_matter(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["caption"], str) and len(data["caption"]) > 0
    assert isinstance(data["bates_prefix"], str)
    assert data["lifecycle_status"] in LIFECYCLE_STATES
    assert data["hold_status"] in HOLD_STATES
    assert isinstance(data["custodian_count"], int)
    assert isinstance(data["acknowledged_count"], int)
    assert isinstance(data["responsive_doc_count"], int)
    assert isinstance(data["next_bates_seq"], int)
    assert isinstance(data["produced_document_count"], int)
    assert isinstance(data["clawed_back_document_count"], int)
    assert isinstance(data["spoliation_risk_score"], int)


def assert_custodian(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["matter_id"])
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)
    assert data["ack_state"] in ACK_STATES
    assert isinstance(data["retention_released"], bool)


def assert_legal_hold(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["matter_id"])
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["status"] in LEGAL_HOLD_STATES
    assert isinstance(data["pending_ack_count"], int)


def assert_hold_acknowledgement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["hold_id"])
    assert is_valid_uuid(data["custodian_id"])
    assert data["status"] in ACK_RECORD_STATES
    assert isinstance(data["on_time"], bool)


def assert_collection_scope(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["matter_id"])
    assert is_valid_uuid(data["custodian_id"])
    assert isinstance(data["source_label"], str) and len(data["source_label"]) > 0
    assert data["status"] in SCOPE_STATES
    assert isinstance(data["expected_doc_count"], int)
    assert isinstance(data["collected_actual_count"], int)


def assert_document(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["scope_id"])
    assert is_valid_uuid(data["matter_id"])
    assert isinstance(data["content_hash"], str) and len(data["content_hash"]) > 0
    assert isinstance(data["page_count"], int) and data["page_count"] >= 1
    assert data["status"] in DOC_STATES
    assert data["privilege_tag"] in PRIVILEGE_TAGS
    assert data["responsiveness_tag"] in RESPONSIVENESS_TAGS


def assert_processing_job(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["matter_id"])
    assert is_valid_uuid(data["scope_id"])
    assert data["status"] in JOB_STATES
    assert isinstance(data["total_input_count"], int)
    assert isinstance(data["unique_count"], int)
    assert isinstance(data["duplicate_count"], int)


def assert_review_batch(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["matter_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in BATCH_STATES
    assert isinstance(data["document_count"], int)
    assert isinstance(data["reviewed_count"], int)


def assert_document_review(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["batch_id"])
    assert is_valid_uuid(data["document_id"])
    assert data["decision"] in DECISIONS


def assert_production_set(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["matter_id"])
    assert is_valid_uuid(data["source_batch_id"])
    assert data["status"] in PRODUCTION_SET_STATES
    assert isinstance(data["item_count"], int)


def assert_production_item(data: dict):
    """ProductionItem has common_fields:false — id + created_at only,
    NO updated_at and NO version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ProductionItem must not carry updated_at"
    assert "version" not in data, "ProductionItem must not carry version"
    assert is_valid_uuid(data["set_id"])
    assert is_valid_uuid(data["document_id"])
    assert data["status"] in PRODUCTION_ITEM_STATES


def assert_clawback(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["matter_id"])
    assert is_valid_uuid(data["production_item_id"])
    assert isinstance(data["reason"], str) and len(data["reason"]) > 0
    assert data["status"] in CLAWBACK_STATES


def assert_produced_clawed_conserved(matter: dict, total_ever_produced: int):
    """PRD §3.8 conservation invariant: produced + clawed-back is conserved at
    the number ever produced."""
    assert (
        matter["produced_document_count"] + matter["clawed_back_document_count"]
        == total_ever_produced
    ), (
        f"produced({matter['produced_document_count']}) + "
        f"clawed_back({matter['clawed_back_document_count']}) "
        f"should equal total-ever-produced {total_ever_produced}"
    )
