"""Entity assertions and domain invariant checkers for the Roofing Storm
Restoration API. Each assert_{entity}() validates the shape and field types
of a returned resource; invariant checkers validate the Job ledger conservation
rules from the PRD (§2.6).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

JOB_STATUSES = ["LEAD", "INSPECTED", "ESTIMATED", "CONTRACTED",
                "IN_PRODUCTION", "COMPLETED", "LOST"]
INSPECTION_STATUSES = ["SCHEDULED", "PASSED", "FAILED"]
ESTIMATE_STATUSES = ["DRAFT", "FINALIZED", "SUPERSEDED"]
MATERIAL_ORDER_STATUSES = ["ORDERED", "DELIVERED", "CANCELLED"]
CREW_ASSIGNMENT_STATUSES = ["BOOKED", "CHECKED_IN", "COMPLETED", "CANCELLED"]
PERMIT_STATUSES = ["APPLIED", "ISSUED", "CLOSED", "EXPIRED"]
DRAW_STATUSES = ["REQUESTED", "DISBURSED", "REJECTED"]
CHANGE_ORDER_STATUSES = ["PROPOSED", "APPROVED", "APPLIED", "VOIDED"]
WARRANTY_STATUSES = ["PENDING", "ACTIVE", "CANCELLED", "EXPIRED"]


def _assert_common_mutable(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an int >= 1, got {data.get('version')!r}"


def assert_estimator(data: dict):
    """Estimator is immutable reference data: id + created_at only (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["license_no"], str) and data["license_no"]
    assert "version" not in data, "Estimator must not carry a version field (PRD §2.4)"
    assert "updated_at" not in data, "Estimator must not carry an updated_at field (PRD §2.4)"


def assert_crew(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["active"], bool)


def assert_job(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["customer_name"], str) and data["customer_name"]
    assert isinstance(data["property_address"], str) and data["property_address"]
    assert data["peril"] in ["HAIL", "WIND", "HURRICANE", "OTHER"]
    assert data["status"] in JOB_STATUSES, f"unexpected job status {data['status']!r}"
    assert isinstance(data["contract_value_cents"], int)
    assert isinstance(data["disbursed_gross_cents"], int)
    assert isinstance(data["disbursed_net_cents"], int)
    assert isinstance(data["retainage_held_cents"], int)
    assert isinstance(data["remaining_billable_cents"], int)


def assert_inspection(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["job_id"])
    assert data["kind"] in ["DAMAGE_ASSESSMENT", "PERMIT_FINAL"]
    assert data["status"] in INSPECTION_STATUSES


def assert_estimate(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["job_id"])
    assert data["source_kind"] in ["AERIAL", "FIELD"]
    assert data["status"] in ESTIMATE_STATUSES
    assert isinstance(data["line_subtotal_cents"], int)
    assert isinstance(data["final_total_cents"], int)


def assert_line_item(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["estimate_id"])
    assert data["trade"] in ["SHINGLE", "UNDERLAYMENT", "RIDGE_VENT",
                             "FLASHING", "DECKING", "GUTTER"]
    assert isinstance(data["line_cost_cents"], int)


def assert_material_order(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["job_id"])
    assert data["status"] in MATERIAL_ORDER_STATUSES
    assert isinstance(data["bundles"], int)
    assert isinstance(data["total_weight_lbs"], int)
    assert isinstance(data["freight_cents"], int)


def assert_crew_assignment(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["job_id"])
    assert is_valid_uuid(data["crew_id"])
    assert data["status"] in CREW_ASSIGNMENT_STATUSES


def assert_permit(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["job_id"])
    assert data["status"] in PERMIT_STATUSES


def assert_draw(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["job_id"])
    assert data["status"] in DRAW_STATUSES
    assert isinstance(data["gross_eligible_cents"], int)
    assert isinstance(data["retainage_cents"], int)
    assert isinstance(data["net_disbursed_cents"], int)
    assert isinstance(data["is_final"], bool)


def assert_change_order(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["job_id"])
    assert data["status"] in CHANGE_ORDER_STATUSES
    assert isinstance(data["delta_cents"], int)


def assert_warranty(data: dict):
    _assert_common_mutable(data)
    assert is_valid_uuid(data["job_id"])
    assert data["status"] in WARRANTY_STATUSES
    assert isinstance(data["premium_cents"], int)
    assert isinstance(data["term_months"], int)


def assert_job_ledger_conserved(data: dict):
    """PRD §2.6: remaining_billable_cents = contract_value_cents - disbursed_gross_cents,
    never negative; disbursed_gross + remaining conserves exactly to contract_value."""
    assert data["remaining_billable_cents"] >= 0, "remaining_billable_cents must never be negative"
    assert (data["disbursed_gross_cents"] + data["remaining_billable_cents"]
            == data["contract_value_cents"]), (
        "disbursed_gross_cents + remaining_billable_cents must equal contract_value_cents "
        f"(got {data['disbursed_gross_cents']} + {data['remaining_billable_cents']} "
        f"!= {data['contract_value_cents']})")
