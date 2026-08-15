"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_primary_common(data: dict, entity_name: str):
    """Primary resources carry id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity_name}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity_name}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity_name}.version must be int"


def _assert_subrecord_common(data: dict, entity_name: str):
    """Sub-records carry only id and created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity_name}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity_name} must not carry updated_at"
    assert "version" not in data, f"{entity_name} must not carry version"


def assert_customer_account(data: dict):
    _assert_primary_common(data, "CustomerAccount")
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert isinstance(data["contact_email"], str)
    assert isinstance(data["contact_phone"], str)
    assert isinstance(data["billing_address"], str)
    assert isinstance(data["tax_exempt"], bool)
    assert data["credit_status"] in ("ACTIVE", "SUSPENDED", "COLLECTIONS")
    assert isinstance(data["total_completed_trips"], int)
    assert isinstance(data["lifetime_revenue_cents"], int)


def assert_vehicle(data: dict):
    _assert_primary_common(data, "Vehicle")
    assert isinstance(data["unit_number"], str) and len(data["unit_number"]) > 0
    assert isinstance(data["make_model"], str)
    assert isinstance(data["year"], int)
    assert isinstance(data["seating_capacity"], int) and data["seating_capacity"] > 0
    assert isinstance(data["ada_accessible"], bool)
    assert data["vehicle_class"] in ("STANDARD", "PREMIUM", "EXECUTIVE")
    assert data["status"] in ("AVAILABLE", "ASSIGNED", "IN_TRIP",
                              "IN_MAINTENANCE", "OUT_OF_SERVICE")
    assert isinstance(data["odometer_miles"], int) and data["odometer_miles"] >= 0
    assert isinstance(data["maintenance_due_miles"], int)


def assert_driver(data: dict):
    _assert_primary_common(data, "Driver")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["cdl_number"], str)
    assert data["cdl_class"] in ("CLASS_A", "CLASS_B", "CLASS_C")
    assert isinstance(data["endorsements"], list)
    assert data["status"] in ("AVAILABLE", "ON_TRIP", "ON_DUTY_NOT_DRIVING",
                              "OFF_DUTY", "SUSPENDED")
    assert data["hos_cycle_type"] in ("CYCLE_70_8", "CYCLE_60_7")
    assert isinstance(data["safety_score"], (int, float))
    assert 0.0 <= data["safety_score"] <= 100.0


def assert_quote(data: dict):
    _assert_primary_common(data, "CharterQuote")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["passenger_count"], int)
    assert isinstance(data["estimated_miles"], int)
    assert isinstance(data["estimated_hours"], (int, float))
    assert isinstance(data["ada_required"], bool)
    assert data["vehicle_class_requested"] in ("STANDARD", "PREMIUM", "EXECUTIVE")
    assert data["status"] in ("DRAFT", "QUOTED", "ACCEPTED", "EXPIRED", "CANCELLED")


def assert_priced_quote(data: dict):
    """A quote in QUOTED status carries the computed pricing fields (PRD §3.3)."""
    assert_quote(data)
    for field in ("mileage_rate_cents", "hourly_rate_cents", "subtotal_cents",
                  "tax_cents", "total_cents", "deposit_cents"):
        assert isinstance(data[field], int), f"{field} must be int cents"
    assert data["pricing_variant"] in ("MILEAGE_PRIMARY", "HOURLY_PRIMARY")
    assert isinstance(data["requires_overnight"], bool)
    assert isinstance(data["requires_relief_driver"], bool)
    assert data["total_cents"] == data["subtotal_cents"] + data["tax_cents"], \
        "total_cents must equal subtotal_cents + tax_cents (PRD §3.3)"


def assert_order(data: dict):
    _assert_primary_common(data, "CharterOrder")
    assert isinstance(data["quote_id"], str)
    assert isinstance(data["customer_id"], str)
    assert data["status"] in ("PENDING_DEPOSIT", "CONFIRMED", "ASSIGNED",
                              "IN_PROGRESS", "COMPLETED", "CANCELLED", "DISPUTED")
    assert isinstance(data["deposit_cents"], int)
    assert isinstance(data["deposit_paid_cents"], int)
    assert isinstance(data["itinerary_changes"], list)


def assert_completed_order(data: dict):
    """A COMPLETED order carries the full settlement figures (PRD §3.5)."""
    assert_order(data)
    assert data["status"] == "COMPLETED"
    for field in ("extra_hours_charge_cents", "fuel_surcharge_cents",
                  "final_subtotal_cents", "final_tax_cents",
                  "final_invoice_cents", "balance_due_cents"):
        assert isinstance(data[field], int), f"{field} must be int cents"
    assert data["final_invoice_cents"] == \
        data["final_subtotal_cents"] + data["final_tax_cents"], \
        "final_invoice_cents must equal final_subtotal_cents + final_tax_cents"
    assert data["balance_due_cents"] == \
        data["final_invoice_cents"] - data["deposit_paid_cents"], \
        "balance_due_cents must equal final_invoice_cents - deposit_paid_cents"


def assert_trip_log(data: dict):
    _assert_subrecord_common(data, "TripLog")
    assert isinstance(data["order_id"], str)
    assert isinstance(data["driver_id"], str)
    assert data["log_type"] in ("DRIVING", "ON_DUTY_NOT_DRIVING", "OFF_DUTY",
                                "SLEEPER_BERTH")


def assert_incident_report(data: dict):
    _assert_subrecord_common(data, "IncidentReport")
    assert isinstance(data["order_id"], str)
    assert isinstance(data["driver_id"], str)
    assert isinstance(data["vehicle_id"], str)
    assert data["incident_type"] in ("ACCIDENT", "BREAKDOWN", "TRAFFIC_VIOLATION",
                                     "CUSTOMER_COMPLAINT", "HOS_VIOLATION",
                                     "CARGO_DAMAGE", "OTHER")
    assert data["severity"] in ("MINOR", "MODERATE", "MAJOR", "CRITICAL")
    assert isinstance(data["dot_recordable"], bool)
    assert data["resolution_status"] in ("OPEN", "UNDER_INVESTIGATION",
                                         "RESOLVED", "CLOSED")


def assert_maintenance_record(data: dict):
    _assert_subrecord_common(data, "MaintenanceRecord")
    assert isinstance(data["vehicle_id"], str)
    assert data["maintenance_type"] in ("PREVENTIVE", "DOT_INSPECTION", "REPAIR",
                                        "RECALL", "TIRE_REPLACE", "BRAKE_SERVICE")
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "OVERDUE")


def assert_breakdown_event(data: dict):
    _assert_primary_common(data, "BreakdownEvent")
    assert isinstance(data["order_id"], str)
    assert isinstance(data["vehicle_id"], str)
    assert isinstance(data["driver_id"], str)
    assert data["status"] in ("REPORTED", "DISPATCHED", "REPLACEMENT_EN_ROUTE",
                              "REPLACED", "RESOLVED_IN_PLACE", "CANCELLED")


def assert_insurance_certificate(data: dict):
    _assert_primary_common(data, "InsuranceCertificate")
    assert isinstance(data["order_id"], str)
    assert isinstance(data["venue_name"], str)
    assert data["certificate_type"] in ("GENERAL_LIABILITY", "AUTO_LIABILITY",
                                        "UMBRELLA", "WORKERS_COMP")
    assert isinstance(data["coverage_amount_cents"], int)
    assert data["status"] in ("REQUESTED", "ISSUED", "EXPIRED", "REVOKED")


def assert_safety_audit_request(data: dict):
    _assert_primary_common(data, "SafetyAuditRequest")
    assert isinstance(data["customer_id"], str)
    assert data["audit_type"] in ("DOT_COMPLIANCE", "SAFETY_RATING",
                                  "INSURANCE_VERIFICATION", "FULL_OPERATIONAL")
    assert data["status"] in ("REQUESTED", "IN_REVIEW", "APPROVED", "REJECTED",
                              "COMPLETED")
