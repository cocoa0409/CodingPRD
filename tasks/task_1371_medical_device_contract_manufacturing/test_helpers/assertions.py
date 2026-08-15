"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value) -> datetime:
    """Parse an ISO 8601 timestamp at second precision (PRD section 2.12:
    datetime comparisons are made at second precision)."""
    assert isinstance(value, str), f"expected ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.replace(microsecond=0)


def assert_instant_equal(actual, expected_iso: str, what: str = "instant"):
    """Assert two instants are equal at second precision, tolerating optional
    fractional-digit formatting differences in the serialized form."""
    expected = _parse_instant(expected_iso)
    actual_parsed = _parse_instant(actual)
    assert actual_parsed == expected, (
        f"{what}: expected {expected_iso}, got {actual}"
    )


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_dmr(data: dict):
    _assert_common(data)
    assert isinstance(data["device_code"], str) and data["device_code"]
    assert isinstance(data["revision_code"], str) and data["revision_code"]
    assert isinstance(data["revision_seq"], int) and data["revision_seq"] >= 1
    assert isinstance(data["sterile"], bool)
    assert isinstance(data["shelf_life_claim_months"], int) and data["shelf_life_claim_months"] > 0
    assert data["status"] in ["DRAFT", "APPROVED", "SUPERSEDED", "OBSOLETE"]
    assert isinstance(data["complaint_rate_per_100k"], (int, float))
    assert isinstance(data["field_action_review_required"], bool)


def assert_line(data: dict):
    _assert_common(data)
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert isinstance(data["changeover_buffer_hours"], int)


def assert_supplier(data: dict):
    _assert_common(data)
    assert isinstance(data["supplier_code"], str) and data["supplier_code"]
    assert data["status"] in ["PENDING_QUALIFICATION", "QUALIFIED", "SUSPENDED", "DISQUALIFIED"]
    assert isinstance(data["quality_score"], (int, float))
    assert isinstance(data["quality_score_finalized"], (int, float))
    assert isinstance(data["applied_penalty_points"], (int, float))
    assert isinstance(data["applied_finalized_penalty_points"], (int, float))
    assert data["risk_tier"] in ["LOW", "MEDIUM", "HIGH"]
    assert isinstance(data["is_audit_overdue"], bool)


def assert_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["agreement_code"], str) and data["agreement_code"]
    assert data["status"] in ["DRAFT", "ACTIVE", "SUPERSEDED", "EXPIRED", "TERMINATED"]
    assert isinstance(data["audit_rights_granted"], bool)


def assert_part(data: dict):
    _assert_common(data)
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert data["status"] in ["QUALIFIED", "ON_HOLD", "DISQUALIFIED"]
    for bucket in (
        "quantity_received",
        "quantity_remaining",
        "quantity_committed",
        "quantity_in_released_lots",
        "quantity_in_scrapped_lots",
    ):
        assert isinstance(data[bucket], int) and data[bucket] >= 0, f"{bucket} must be a non-negative integer"


def assert_scn(data: dict):
    _assert_common(data)
    assert data["impact_class"] in ["MINOR", "MAJOR"]
    assert data["status"] in ["SUBMITTED", "UNDER_REVIEW", "ACCEPTED", "REJECTED"]


def assert_audit(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_protocol(data: dict):
    _assert_common(data)
    assert isinstance(data["protocol_code"], str) and data["protocol_code"]
    assert data["status"] in [
        "DRAFT", "IQ_EXECUTION", "IQ_REVIEW", "OQ_EXECUTION", "OQ_REVIEW",
        "PQ_EXECUTION", "PQ_REVIEW", "VALIDATED", "REVALIDATION_REQUIRED",
    ]
    assert data["revalidation_reason"] in [
        "NONE", "TIME_EXPIRY", "SUPPLIER_CHANGE", "CAPA_PROCESS_CHANGE", "STUDY_FAILURE",
    ]
    assert isinstance(data["generation"], int) and data["generation"] >= 1


def assert_study(data: dict):
    _assert_common(data)
    assert data["study_type"] in ["REAL_TIME", "ACCELERATED"]
    assert data["status"] in ["IN_PROGRESS", "PASSED", "FAILED", "INVALIDATED"]


def assert_lot(data: dict):
    _assert_common(data)
    assert isinstance(data["lot_number"], str) and data["lot_number"]
    assert data["disposition_status"] in ["IN_PRODUCTION", "COMPLETED", "RELEASED", "SCRAPPED", "RECALLED"]
    assert data["hold_status"] in ["CLEAR", "ON_HOLD"]
    assert data["hold_reason"] in [
        "NONE", "MANUAL", "NCR_OPEN", "SUPPLIER_QUALITY", "REVALIDATION",
        "STERILITY_FAILURE", "FIELD_ACTION",
    ]
    assert data["sterility_result"] in ["PENDING", "PASSED", "FAILED"]
    assert data["expiry_basis"] in ["PROVISIONAL", "FINAL"]
    assert isinstance(data["quantity"], int) and data["quantity"] > 0


def assert_component(data: dict):
    _assert_common(data)
    assert isinstance(data["quantity_used"], int) and data["quantity_used"] > 0
    assert isinstance(data["supplier_lot_number"], str) and data["supplier_lot_number"]


def assert_label(data: dict):
    _assert_common(data)
    assert isinstance(data["udi_di"], str) and len(data["udi_di"]) == 14
    assert isinstance(data["udi_pi"], str) and data["udi_pi"].startswith("LOT-")
    assert data["status"] in ["DRAFT", "APPROVED", "PRINTED", "VOID"]
    assert data["void_reason"] in ["NONE", "LOT_SCRAPPED", "LOT_RECALLED", "MANUAL"]


def assert_ncr(data: dict):
    _assert_common(data)
    assert isinstance(data["ncr_code"], str) and data["ncr_code"]
    assert data["severity"] in ["MINOR", "MAJOR", "CRITICAL"]
    assert data["fault"] in ["UNDETERMINED", "INTERNAL", "SUPPLIER"]
    assert data["disposition"] in ["NONE", "USE_AS_IS", "REWORK", "SCRAP", "RETURN_TO_SUPPLIER"]
    assert data["status"] in ["OPEN", "CONTAINED", "DISPOSITIONED", "CLOSED"]
    assert isinstance(data["penalty_points_applied"], (int, float))


def assert_complaint(data: dict):
    _assert_common(data)
    assert isinstance(data["complaint_code"], str) and data["complaint_code"]
    assert data["severity"] in ["COSMETIC", "MINOR", "SERIOUS_INJURY", "DEATH"]
    assert data["status"] in ["RECEIVED", "UNDER_INVESTIGATION", "INVESTIGATED", "CLOSED"]
    assert isinstance(data["confirmed"], bool)


def assert_capa(data: dict):
    _assert_common(data)
    assert isinstance(data["capa_code"], str) and data["capa_code"]
    assert data["source_type"] in ["COMPLAINT", "NCR", "AUDIT", "MANUAL"]
    assert data["status"] in [
        "INITIATED", "INVESTIGATING", "ACTION_PLANNED", "IMPLEMENTING",
        "EFFECTIVENESS_CHECK", "CLOSED", "INEFFECTIVE",
    ]
    assert isinstance(data["effectiveness_cycles"], int)


def assert_field_action(data: dict):
    _assert_common(data)
    assert isinstance(data["action_code"], str) and data["action_code"]
    assert data["action_type"] in ["CORRECTION", "REMOVAL"]
    assert data["status"] in ["DRAFT", "ISSUED", "CLOSED"]
    assert isinstance(data["recalled_lot_count"], int)


def assert_part_mass_balance(part: dict):
    """Component units are conserved: received == remaining + committed +
    in_released_lots + in_scrapped_lots (PRD section 3.5 bucket choreography)."""
    total = (
        part["quantity_remaining"]
        + part["quantity_committed"]
        + part["quantity_in_released_lots"]
        + part["quantity_in_scrapped_lots"]
    )
    assert total == part["quantity_received"], (
        f"part mass balance violated: {total} != received {part['quantity_received']}"
    )


def assert_supplier_score_invariant(supplier: dict):
    """quality_score + applied_penalty_points == 100, and the same for the
    finalized variant, each floored at zero (PRD section 2.9)."""
    assert supplier["quality_score"] == max(0, 100 - supplier["applied_penalty_points"]), (
        f"quality_score {supplier['quality_score']} inconsistent with "
        f"applied_penalty_points {supplier['applied_penalty_points']}"
    )
    assert supplier["quality_score_finalized"] == max(
        0, 100 - supplier["applied_finalized_penalty_points"]
    ), (
        f"quality_score_finalized {supplier['quality_score_finalized']} inconsistent with "
        f"applied_finalized_penalty_points {supplier['applied_finalized_penalty_points']}"
    )
