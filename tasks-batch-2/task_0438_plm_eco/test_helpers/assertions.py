"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id (UUID), created_at/updated_at (ISO 8601), integer version >= 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must be >= 1, got {data['version']}"


def assert_supplier(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["supplier_code"], str) and len(data["supplier_code"]) > 0
    assert data["status"] in ("ACTIVE", "DISABLED"), data["status"]


def assert_part(data: dict):
    _assert_common(data)
    assert isinstance(data["part_number"], str) and len(data["part_number"]) > 0
    assert data["part_type"] in ("MAKE", "BUY", "PHANTOM"), data["part_type"]
    assert isinstance(data["base_cost_cents"], int) and data["base_cost_cents"] >= 0
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_part_revision(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("part_id", "")), "part_id must be a UUID"
    assert isinstance(data["rev_label"], str) and len(data["rev_label"]) > 0
    assert data["lifecycle_state"] in (
        "WORKING",
        "IN_REVIEW",
        "RELEASED",
        "OBSOLETE",
    ), data["lifecycle_state"]
    assert isinstance(data["planned_cost_cents"], int)
    assert isinstance(data["effective_cost_cents"], int)


def assert_bom_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("parent_revision_id", "")), "parent_revision_id must be a UUID"
    assert is_valid_uuid(data.get("child_part_id", "")), "child_part_id must be a UUID"
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1


def assert_change_request(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str)
    assert is_valid_uuid(data.get("affected_part_id", "")), "affected_part_id must be a UUID"
    assert data["reason_code"] in (
        "DESIGN_DEFECT",
        "COST_REDUCTION",
        "SUPPLIER_CHANGE",
        "OBSOLESCENCE",
    ), data["reason_code"]
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED"), data["status"]


def assert_change_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("change_request_id", "")), "change_request_id must be a UUID"
    assert isinstance(data["required_approvals"], int) and data["required_approvals"] >= 1
    assert isinstance(data["approval_count"], int) and data["approval_count"] >= 0
    assert data["status"] in (
        "DRAFT",
        "IN_APPROVAL",
        "APPROVED",
        "EFFECTIVE",
        "REJECTED",
        "CANCELLED",
    ), data["status"]


def assert_approval_task(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("change_order_id", "")), "change_order_id must be a UUID"
    assert isinstance(data["assignee_user_id"], str) and len(data["assignee_user_id"]) > 0
    assert data["decision"] in ("PENDING", "APPROVED", "REJECTED"), data["decision"]


def assert_affected_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("change_order_id", "")), "change_order_id must be a UUID"
    assert is_valid_uuid(data.get("part_revision_id", "")), "part_revision_id must be a UUID"
    assert isinstance(data["pinned"], bool)


def assert_document(data: dict):
    _assert_common(data)
    assert isinstance(data["doc_number"], str) and len(data["doc_number"]) > 0
    assert data["doc_type"] in ("CAD", "DRAWING", "SPEC"), data["doc_type"]
    assert data["lifecycle_state"] in (
        "WORKING",
        "IN_REVIEW",
        "RELEASED",
        "OBSOLETE",
    ), data["lifecycle_state"]


def assert_deviation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("part_id", "")), "part_id must be a UUID"
    assert data["defect_code"] in (
        "DIMENSIONAL",
        "COSMETIC",
        "MATERIAL",
        "FUNCTIONAL",
    ), data["defect_code"]
    assert isinstance(data["max_units"], int) and data["max_units"] >= 1
    assert isinstance(data["covered_unit_count"], int) and data["covered_unit_count"] >= 0
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "GRANTED",
        "DENIED",
        "EXPIRED",
    ), data["status"]


def assert_pcn(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("supplier_id", "")), "supplier_id must be a UUID"
    assert is_valid_uuid(data.get("affected_part_id", "")), "affected_part_id must be a UUID"
    assert isinstance(data["pcn_reference"], str)
    assert data["status"] in (
        "RECEIVED",
        "UNDER_ASSESSMENT",
        "ACCEPTED",
        "REJECTED",
    ), data["status"]


def assert_serialized_unit(data: dict):
    _assert_common(data)
    assert isinstance(data["serial_number"], str) and len(data["serial_number"]) > 0
    assert is_valid_uuid(data.get("part_revision_id", "")), "part_revision_id must be a UUID"
    assert data["build_status"] in ("PLANNED", "BUILT", "SHIPPED"), data["build_status"]
    assert data["conformance_status"] in (
        "CONFORMING",
        "NONCONFORMING",
        "WAIVED",
    ), data["conformance_status"]
