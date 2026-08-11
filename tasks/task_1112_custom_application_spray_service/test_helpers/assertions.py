"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_mutable_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def _assert_append_only_common(data: dict, entity: str):
    """Evidence records carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} is append-only: updated_at must be absent"
    assert "version" not in data, f"{entity} is append-only: version must be absent"


def assert_customer(data: dict):
    _assert_mutable_common(data, "Customer")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["billing_email"], str)
    assert isinstance(data["rate_per_acre_cents"], int)
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["outstanding_cents"], int)
    assert data["outstanding_cents"] >= 0


def assert_field(data: dict):
    _assert_mutable_common(data, "Field")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["label"], str)
    assert isinstance(data["crop"], str)
    assert data["acres"] > 0
    assert isinstance(data["buffer_clearance_ft"], int)
    assert data.get("rei_until") is None or is_iso8601_timestamp(data["rei_until"])


def assert_product(data: dict):
    _assert_mutable_common(data, "Product")
    assert isinstance(data["name"], str)
    assert isinstance(data["epa_registration_no"], str)
    assert data["category"] in ["HERBICIDE", "INSECTICIDE", "FUNGICIDE"]
    assert isinstance(data["rei_hours"], int)
    assert isinstance(data["required_buffer_ft"], int)
    assert isinstance(data["unit_cost_cents"], int)


def assert_compatibility_rule(data: dict):
    _assert_append_only_common(data, "CompatibilityRule")
    assert is_valid_uuid(data.get("product_a_id", ""))
    assert is_valid_uuid(data.get("product_b_id", ""))
    assert data["verdict"] in ["COMPATIBLE", "CONDITIONAL", "INCOMPATIBLE"]


def assert_prescription(data: dict):
    _assert_mutable_common(data, "Prescription")
    assert is_valid_uuid(data.get("field_id", ""))
    assert isinstance(data["season_year"], int)
    assert is_iso8601_timestamp(data.get("valid_from", ""))
    assert is_iso8601_timestamp(data.get("valid_to", ""))
    assert data["carrier_gpa"] > 0
    assert isinstance(data["lines"], list) and len(data["lines"]) > 0
    for line in data["lines"]:
        assert is_valid_uuid(line.get("product_id", ""))
        assert line["rate_per_acre"] > 0
    assert data["status"] in ["DRAFT", "APPROVED", "SUPERSEDED"]
    assert isinstance(data.get("created_by_user_id"), str)


def assert_applicator(data: dict):
    _assert_mutable_common(data, "Applicator")
    assert isinstance(data["display_name"], str)
    assert isinstance(data["license_no"], str)
    assert is_iso8601_timestamp(data.get("license_expires_on", ""))
    assert isinstance(data["license_categories"], list)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "REVOKED"]
    assert isinstance(data["penalty_points_lifetime"], int)
    assert isinstance(data["rolling_score_365"], int)


def assert_equipment(data: dict):
    _assert_mutable_common(data, "Equipment")
    assert isinstance(data["unit_label"], str)
    assert isinstance(data["tank_capacity_gal"], int)
    assert data["status"] in ["AVAILABLE", "CALIBRATION_DUE"]
    assert data.get("calibration_valid_until") is None or \
        is_iso8601_timestamp(data["calibration_valid_until"])


def assert_calibration_record(data: dict):
    _assert_append_only_common(data, "CalibrationRecord")
    assert is_valid_uuid(data.get("equipment_id", ""))
    assert isinstance(data.get("applicator_id"), str)
    assert is_iso8601_timestamp(data.get("performed_at", ""))
    assert data["target_gpa"] > 0
    assert data["measured_gpa"] > 0
    assert isinstance(data["error_pct"], (int, float))
    assert data["verdict"] in ["PASS", "FAIL"]


def assert_weather_observation(data: dict):
    _assert_append_only_common(data, "WeatherObservation")
    assert is_iso8601_timestamp(data.get("observed_at", ""))
    assert isinstance(data["wind_mph"], (int, float))
    assert isinstance(data["temp_f"], (int, float))
    assert isinstance(data["inversion_present"], bool)
    assert isinstance(data.get("recorded_by_user_id"), str)


def assert_work_order(data: dict):
    _assert_mutable_common(data, "WorkOrder")
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("field_id", ""))
    assert is_valid_uuid(data.get("prescription_id", ""))
    assert data["acres_to_treat"] > 0
    assert data["status"] in ["DRAFT", "SCHEDULED", "IN_PROGRESS", "WEATHER_HOLD",
                              "COMPLETED", "CLOSED", "CANCELLED"]
    assert isinstance(data["uses_adjuvant"], bool)
    assert isinstance(data["rinsate_generated_gal"], (int, float))
    assert isinstance(data["rinsate_balance_gal"], (int, float))


def assert_application_record(data: dict):
    _assert_mutable_common(data, "ApplicationRecord")
    assert is_valid_uuid(data.get("work_order_id", ""))
    assert isinstance(data.get("applicator_id"), str)
    assert isinstance(data["lines"], list) and len(data["lines"]) > 0
    for line in data["lines"]:
        assert is_valid_uuid(line.get("product_id", ""))
        assert line["actual_rate_per_acre"] > 0
    assert data["status"] in ["SUBMITTED", "CERTIFIED", "RETURNED"]


def assert_rinsate_record(data: dict):
    _assert_append_only_common(data, "RinsateRecord")
    assert is_valid_uuid(data.get("work_order_id", ""))
    assert data["kind"] in ["FIELD_DISPOSAL", "CONTAINMENT_DISPOSAL"]
    assert data["volume_gal"] > 0
    assert is_iso8601_timestamp(data.get("recorded_at", ""))


def assert_drift_complaint(data: dict):
    _assert_mutable_common(data, "DriftComplaint")
    assert is_valid_uuid(data.get("complainant_customer_id", ""))
    assert is_valid_uuid(data.get("work_order_id", ""))
    assert isinstance(data.get("applicator_id"), str)
    assert isinstance(data["description"], str)
    assert data["severity"] in ["MINOR", "MAJOR"]
    assert data["status"] in ["FILED", "INVESTIGATING", "SUBSTANTIATED", "DISMISSED"]


def assert_invoice(data: dict):
    _assert_mutable_common(data, "Invoice")
    assert is_valid_uuid(data.get("work_order_id", ""))
    assert isinstance(data["provisional_amount_cents"], int)
    assert data.get("final_amount_cents") is None or isinstance(data["final_amount_cents"], int)
    assert data["status"] in ["DRAFT", "ISSUED", "PAID", "VOIDED"]
