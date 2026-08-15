"""Entity assertions and domain invariant checkers (construction materials PRD)."""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# PRD §2.4: created_at / updated_at are ISO 8601 UTC timestamps with three
# fractional digits, stamped from the logical clock.
_ISO8601_MILLIS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def assert_iso8601_millis(value: str) -> None:
    """Assert an ISO 8601 UTC timestamp with exactly three fractional digits."""
    assert isinstance(value, str) and _ISO8601_MILLIS_RE.match(value), (
        f"Expected ISO 8601 UTC timestamp with three fractional digits, got {value!r}"
    )


def _assert_common(data: dict) -> None:
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert_iso8601_millis(data.get("created_at", ""))
    assert_iso8601_millis(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_project(data: dict) -> None:
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "COMPLETED")
    assert data["compliance_posture"] in (
        "IN_PROGRESS", "NONCONFORMANCE_OUTSTANDING", "READY_FOR_LETTER", "LETTER_ISSUED"
    )
    assert isinstance(data["open_ncr_count"], int) and data["open_ncr_count"] >= 0
    assert data["letter_status"] in ("NONE", "ISSUED", "VOIDED")
    assert isinstance(data["permit_number"], str) and data["permit_number"]
    for nullable in ("current_approved_ssi_id", "letter_issued_at",
                     "letter_issued_by", "letter_void_reason"):
        assert nullable in data, f"project must carry {nullable} (null until set)"


def assert_ssi_revision(data: dict) -> None:
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED")
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert isinstance(data["specified_fc_psi"], int)
    assert data["acceptance_method_concrete"] in ("MOVING_AVERAGE", "INDIVIDUAL_SET")
    assert is_valid_uuid(data.get("project_id", ""))


def assert_scope_item(data: dict) -> None:
    _assert_common(data)
    assert data["test_method"] in (
        "CONCRETE_STRENGTH", "SOIL_COMPACTION", "WELD_VISUAL", "BOLT_TENSION"
    )
    assert data["status"] in ("OPEN", "SATISFIED")
    assert isinstance(data["completed_count"], int) and data["completed_count"] >= 0
    assert isinstance(data["required_count"], int) and data["required_count"] >= 1
    assert data["required_cert_level"] in (1, 2, 3)


def assert_technician(data: dict) -> None:
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["certifications"], list)
    for cert in data["certifications"]:
        assert cert["method"] in (
            "CONCRETE_STRENGTH", "SOIL_COMPACTION", "WELD_VISUAL", "BOLT_TENSION"
        )
        assert cert["level"] in (1, 2, 3)


def assert_assignment(data: dict) -> None:
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "DISPATCHED", "COMPLETED", "CANCELLED")
    for fk in ("project_id", "scope_item_id", "technician_id", "ssi_revision_id"):
        assert is_valid_uuid(data.get(fk, "")), f"{fk} must reference a persisted entity"
    assert "covered_by_dir_id" in data, "assignment must carry covered_by_dir_id (null until covered)"


def assert_field_test(data: dict) -> None:
    _assert_common(data)
    assert data["status"] in ("RECORDED", "VOIDED")
    assert data["result"] in ("CONFORMING", "NONCONFORMING")
    assert data["test_method"] in ("SOIL_COMPACTION", "WELD_VISUAL", "BOLT_TENSION")
    assert isinstance(data["result_details"], dict)


def assert_lab_sample(data: dict) -> None:
    _assert_common(data)
    assert data["status"] in ("CAST", "BREAK_SCHEDULED", "REPORTED", "DISCARDED")
    assert data["required_break_age_days"] in (7, 28, 56)
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert is_valid_uuid(data.get("lab_id", ""))
    assert "break_due_at" in data, "lab sample must carry the computed break_due_at"


def assert_lab(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["daily_break_capacity"], int) and data["daily_break_capacity"] >= 1


def assert_ncr(data: dict) -> None:
    _assert_common(data)
    assert data["status"] in ("OPEN", "CORRECTION_SUBMITTED", "ESCALATED", "VERIFIED")
    assert data["severity"] in ("MINOR", "MAJOR", "STRUCTURAL")
    assert data["source_type"] in ("FIELD_TEST", "LAB_SAMPLE")
    assert isinstance(data["ncr_number"], str) and data["ncr_number"].startswith("NCR-")
    assert isinstance(data["rejection_count"], int) and data["rejection_count"] >= 0


def assert_daily_report(data: dict) -> None:
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "ACKNOWLEDGED")
    assert isinstance(data["assignment_ids"], list)
    assert "acknowledged_by" in data, "daily report must carry acknowledged_by (null until acknowledged)"


def assert_discrepancy(data: dict) -> None:
    _assert_common(data)
    assert data["status"] in ("RAISED", "RESPONSE_SUBMITTED", "RESOLVED")
    assert data["routed_to"] in ("CONTRACTOR", "ENGINEER")
    assert isinstance(data["round_count"], int) and data["round_count"] >= 1


def assert_project_invariants(data: dict) -> None:
    """Domain invariants that must hold for any project read (PRD §3.9)."""
    assert_project(data)
    if data["letter_status"] == "ISSUED":
        assert data["compliance_posture"] == "LETTER_ISSUED", (
            "an issued letter forces posture LETTER_ISSUED (gate 1)"
        )
    if data["open_ncr_count"] > 0 and data["letter_status"] != "ISSUED":
        assert data["compliance_posture"] == "NONCONFORMANCE_OUTSTANDING", (
            "any open NCR forces posture NONCONFORMANCE_OUTSTANDING (gate 2)"
        )
