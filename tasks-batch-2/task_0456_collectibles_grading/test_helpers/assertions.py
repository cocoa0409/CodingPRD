"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    # PRD §2.4 says version begins at the resource's first persisted value and
    # increments on every mutation; it does not pin the initial integer, so we
    # only require a non-negative integer rather than forcing a 0-vs-1 choice.
    assert isinstance(data.get("version"), int) and data["version"] >= 0, "version must be a non-negative int"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["store_credit_cents"], int)
    assert data["store_credit_cents"] >= 0, "store_credit_cents must be >= 0"


def assert_service_level(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["turnaround_business_days"] >= 1
    assert data["base_fee_cents"] >= 0
    assert data["max_declared_value_cents"] >= 1
    assert data["insurance_rate_bps"] >= 0
    assert isinstance(data["active"], bool)


def assert_grading_standard(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["max_grade"] > 0
    assert 0 < data["authentic_min_grade"] <= data["max_grade"]
    total = (data["centering_weight_bps"] + data["corners_weight_bps"]
             + data["edges_weight_bps"] + data["surface_weight_bps"])
    assert total == 10000, f"weights must sum to 10000, got {total}"


def assert_submission(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "RECEIVING", "IN_GRADING",
        "READY_TO_SHIP", "SHIPPED", "CLOSED",
    ]
    assert data["item_count"] >= 0
    assert data["total_estimated_fee_cents"] >= 0
    assert data["total_final_fee_cents"] >= 0


def assert_submission_item(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "REGISTERED", "INTAKE_LOGGED", "GRADING", "AUTHENTICATED",
        "ENCAPSULATED", "CRACK_PENDING", "REJECTED_RETURNED", "SHIPPED",
    ]
    assert data["declared_value_cents"] >= 1
    assert data["regrade_count"] >= 0


def assert_grade_assessment(data: dict):
    _assert_common(data)
    assert isinstance(data["superseded"], bool)


def assert_slab(data: dict):
    _assert_common(data)
    assert isinstance(data["cert_number"], str) and len(data["cert_number"]) > 0
    assert isinstance(data["active"], bool)


def assert_population_report(data: dict):
    _assert_common(data)
    assert data["pop_count"] >= 0, "pop_count never drops below zero"


def assert_insurance_policy(data: dict):
    _assert_common(data)
    assert data["claim_status"] in ["NONE", "FILED", "PAID"]
    assert data["covered_value_cents"] >= 0
    assert data["payout_cents"] >= 0


def assert_shipment(data: dict):
    _assert_common(data)
    assert data["status"] in ["LABEL_CREATED", "IN_TRANSIT", "DELIVERED", "LOST"]


def assert_label(data: dict):
    """Label is immutable once printed: it carries only id + created_at, never
    updated_at / version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["printed_pop_count"] >= 0
