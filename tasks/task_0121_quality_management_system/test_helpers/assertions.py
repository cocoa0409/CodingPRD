"""Entity assertions and domain invariant checkers.

Each assert_{entity}(data) verifies field presence, types, and enum-domain for
fields the PRD guarantees on the response. Append-only entities (8D steps) are
asserted to carry only id + created_at (no version).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_NCR_STATUSES = {"DRAFT", "OPEN", "DISPOSITIONED", "CAPA_IN_PROGRESS", "CLOSED", "VOID"}
_CAPA_STATUSES = {
    "OPEN", "ROOT_CAUSE", "VERIFICATION", "EFFECTIVENESS_CHECK",
    "CLOSED_EFFECTIVE", "CLOSED_INEFFECTIVE",
}
_SCAR_STATUSES = {
    "OPEN", "ACK", "RESPONDED", "ACCEPTED_RESPONSE", "REJECTED_RESPONSE",
    "RESOLVED", "CANCELLED",
}
_LOT_STATUSES = {"PENDING", "IN_INSPECTION", "ACCEPTED", "REJECTED"}
_AUDIT_STATUSES = {"PLANNED", "IN_PROGRESS", "CLOSED"}
_FINDING_STATUSES = {"OPEN", "NCR_RAISED", "CLOSED", "VOID"}
_DEVIATION_STATUSES = {"REQUESTED", "APPROVED", "REJECTED", "EXPIRED", "REVOKED"}
_APPROVAL_STATUSES = {"APPROVED", "PROBATION", "DISQUALIFIED"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_versioned(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_personnel(data: dict):
    _assert_versioned(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["role"] in {"QUALITY_ENGINEER", "QUALITY_MANAGER", "INSPECTOR", "AUDITOR"}
    assert data["status"] in {"ACTIVE", "DEACTIVATED"}


def assert_supplier(data: dict):
    _assert_versioned(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["quality_rating"], (int, float))
    assert 0.0 <= float(data["quality_rating"]) <= 100.0, "quality_rating in [0,100]"
    assert data["approval_status"] in _APPROVAL_STATUSES
    for counter in ("open_scar_count", "lots_inspected", "lots_rejected", "ncrs_attributed"):
        assert isinstance(data[counter], int) and data[counter] >= 0, f"{counter} must be int >= 0"
    assert_supplier_invariants(data)


def assert_supplier_invariants(data: dict):
    """Cross-field invariants that must always hold for a Supplier."""
    assert data["lots_rejected"] <= data["lots_inspected"], "lots_rejected <= lots_inspected"
    qr = float(data["quality_rating"])
    if qr >= 70.0:
        assert data["approval_status"] == "APPROVED"
    elif qr >= 50.0:
        assert data["approval_status"] == "PROBATION"
    else:
        assert data["approval_status"] == "DISQUALIFIED"


def assert_ncr(data: dict):
    _assert_versioned(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["source"] in {"SUPPLIER", "INTERNAL", "AUDIT"}
    assert data["severity"] in {"CRITICAL", "MAJOR", "MINOR"}
    assert isinstance(data["defect_qty"], int) and data["defect_qty"] >= 1
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert data["status"] in _NCR_STATUSES
    assert data["disposition"] is None or data["disposition"] in {
        "REWORK", "SCRAP", "USE_AS_IS", "RETURN_TO_SUPPLIER"
    }
    assert isinstance(data["budget_reserved_cents"], int) and data["budget_reserved_cents"] >= 0


def assert_capa(data: dict):
    _assert_versioned(data)
    assert data["ncr_id"]
    assert data["status"] in _CAPA_STATUSES
    assert data["current_step"] in {"D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"}
    assert isinstance(data["rework_loops"], int) and data["rework_loops"] >= 0


def assert_eightdstep(data: dict):
    """8D step is append-only: id + created_at only (NO updated_at, NO version)."""
    _assert_common(data)
    assert "version" not in data, "8D step must NOT carry a version field"
    assert "updated_at" not in data, "8D step must NOT carry an updated_at field"
    assert data["capa_id"]
    assert data["discipline"] in {"D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"}


def assert_scar(data: dict):
    _assert_versioned(data)
    assert data["ncr_id"]
    assert data["supplier_id"]
    assert data["status"] in _SCAR_STATUSES
    assert isinstance(data["rejection_count"], int) and data["rejection_count"] >= 0


def assert_inspection_plan(data: dict):
    _assert_versioned(data)
    assert data["control_plan_id"]
    assert data["severity_mode"] in {"NORMAL", "TIGHTENED"}
    assert data["inspection_level"] in {"GI", "GII", "GIII"}
    assert isinstance(data["consecutive_rejects"], int) and data["consecutive_rejects"] >= 0
    assert isinstance(data["needs_review"], bool)


def assert_inspection_lot(data: dict):
    _assert_versioned(data)
    assert data["inspection_plan_id"]
    assert data["supplier_id"]
    assert data["status"] in _LOT_STATUSES


def assert_audit(data: dict):
    _assert_versioned(data)
    assert data["lead_auditor_id"]
    assert data["status"] in _AUDIT_STATUSES
    assert isinstance(data["open_finding_count"], int) and data["open_finding_count"] >= 0


def assert_audit_finding(data: dict):
    _assert_versioned(data)
    assert data["audit_id"]
    assert data["grade"] in {"MAJOR", "MINOR", "OBSERVATION"}
    assert data["status"] in _FINDING_STATUSES


def assert_deviation(data: dict):
    _assert_versioned(data)
    assert data["ncr_id"]
    assert data["supplier_id"]
    assert data["status"] in _DEVIATION_STATUSES
    assert isinstance(data["max_qty"], int) and data["max_qty"] >= 1


def assert_control_plan(data: dict):
    _assert_versioned(data)
    assert data["status"] in {"ACTIVE", "RETIRED"}
    assert isinstance(data["current_revision_no"], int) and data["current_revision_no"] >= 0


def assert_control_plan_revision(data: dict):
    _assert_versioned(data)
    assert data["control_plan_id"]
    assert isinstance(data["revision_no"], int) and data["revision_no"] >= 1
    assert data["status"] in {"DRAFT", "APPROVED", "SUPERSEDED"}
