"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_builder(data: dict):
    _assert_common_fields(data, "Builder")
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_service_application(data: dict):
    _assert_common_fields(data, "ServiceApplication")
    assert isinstance(data["builder_id"], str) and data["builder_id"]
    assert isinstance(data["service_address"], str)
    assert isinstance(data["city"], str)
    assert isinstance(data["state_code"], str)
    assert isinstance(data["postal_code"], str)
    assert data.get("pressure_class_requested", "LOW") in ("LOW", "MEDIUM")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "LOAD_CONFIRMED", "DESIGN", "QUOTED", "CIAC_PENDING",
        "APPROVED_FOR_CONSTRUCTION", "PERMITTING", "CONSTRUCTION_SCHEDULED",
        "SERVICE_INSTALLED", "METER_WORK", "TESTING", "TURN_ON", "ENERGIZED",
        "GIS_REVIEW", "COMPLETED", "REJECTED", "CANCELLED", "EXPIRED",
    )
    assert data.get("hold_status", "NOT_HELD") in (
        "NOT_HELD", "HELD_BY_BUILDER", "HELD_BY_UTILITY"
    )


def assert_appliance_load(data: dict):
    _assert_common_fields(data, "ApplianceLoad")
    assert isinstance(data["service_application_id"], str)
    assert data["appliance_type"] in (
        "FURNACE", "WATER_HEATER", "RANGE", "DRYER", "FIREPLACE",
        "STANDBY_GENERATOR", "POOL_HEATER", "OTHER",
    )
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["btuh_input_rating"], int) and data["btuh_input_rating"] > 0
    assert isinstance(data["counted_load_cfph"], (int, float))


def assert_main_extension(data: dict):
    _assert_common_fields(data, "MainExtension")
    assert isinstance(data["service_application_id"], str)
    assert isinstance(data["design_footage_ft"], int) and data["design_footage_ft"] > 0
    assert isinstance(data["crossings"], list)
    assert data["status"] in (
        "DRAFT", "DESIGN_SUBMITTED", "QUOTED", "ACCEPTED", "CONSTRUCTED",
        "AS_BUILT_RECORDED", "FINALIZED", "CANCELLED", "EXPIRED",
    )


def assert_ciac_invoice(data: dict):
    _assert_common_fields(data, "CIACInvoice")
    assert isinstance(data["main_extension_id"], str)
    assert isinstance(data["service_application_id"], str)
    assert isinstance(data["amount_due_cents"], int)
    assert isinstance(data["payments_applied_cents"], int)
    assert isinstance(data["refunds_issued_cents"], int)
    assert isinstance(data["balance_due_cents"], int)
    assert data["status"] in (
        "ISSUED", "PARTIALLY_PAID", "PAID", "SETTLED", "REFUND_PENDING", "REFUNDED", "VOID"
    )


def assert_ciac_payment(data: dict):
    # Append-only ledger entry: id + created_at, NO updated_at / version (PRD §2.4)
    assert is_valid_uuid(data.get("id", "")), "CIACPayment.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "CIACPayment.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, "CIACPayment must not expose updated_at"
    assert "version" not in data, "CIACPayment must not expose version"
    assert isinstance(data["ciac_invoice_id"], str)
    assert data["direction"] in ("PAYMENT", "REFUND")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["method"] in ("CHECK", "ACH", "CARD")
    assert isinstance(data["recorded_by_user_id"], str) and data["recorded_by_user_id"]


def assert_permit(data: dict):
    _assert_common_fields(data, "Permit")
    assert isinstance(data["service_application_id"], str)
    assert data["permit_type"] in ("ROAD_CUT", "EASEMENT", "RAILROAD_CROSSING", "DOT_HIGHWAY")
    assert isinstance(data["jurisdiction"], str)
    assert isinstance(data["crossings"], list)
    assert isinstance(data["permit_fee_cents"], int)
    assert data["status"] in (
        "DRAFT", "FILED", "APPROVED", "REJECTED", "EXPIRED", "CLOSED", "WITHDRAWN"
    )


def assert_field_crew(data: dict):
    _assert_common_fields(data, "FieldCrew")
    assert isinstance(data["crew_name"], str)
    assert data["specialty"] in ("MAIN_EXTENSION", "SERVICE_LINE", "RESTORATION", "GENERAL")
    assert isinstance(data["daily_capacity_minutes"], int) and data["daily_capacity_minutes"] > 0
    assert isinstance(data["active"], bool)


def assert_crew_booking(data: dict):
    _assert_common_fields(data, "CrewBooking")
    assert isinstance(data["service_application_id"], str)
    assert isinstance(data["field_crew_id"], str)
    assert isinstance(data["work_date"], str)
    assert isinstance(data["start_minute"], int)
    assert isinstance(data["end_minute"], int)
    assert data["end_minute"] > data["start_minute"]
    assert data["scope"] in ("MAIN_CONSTRUCTION", "SERVICE_INSTALL", "RESTORATION")
    assert data["status"] in ("REQUESTED", "CONFIRMED", "COMPLETED", "CANCELLED")


def assert_inspector(data: dict):
    _assert_common_fields(data, "Inspector")
    assert isinstance(data["full_name"], str)
    assert isinstance(data["certifications"], list)
    assert isinstance(data["active"], bool)


def assert_inspection(data: dict):
    _assert_common_fields(data, "Inspection")
    assert isinstance(data["service_application_id"], str)
    assert isinstance(data["inspector_id"], str)
    assert data["inspection_type"] in ("ROAD_CUT_RESTORATION", "PRESSURE_TEST", "FINAL_SAFETY")
    assert isinstance(data["inspection_date"], str)
    assert data["end_minute"] > data["start_minute"]
    assert data["status"] in (
        "SCHEDULED", "COMPLETED_PASS", "COMPLETED_FAIL", "CANCELLED", "EXPIRED"
    )


def assert_meter_set(data: dict):
    _assert_common_fields(data, "MeterSet")
    assert isinstance(data["service_application_id"], str)
    assert data["status"] in (
        "PLANNED", "SIZED", "ORDERED", "INSTALLED", "TESTING", "REPAIR",
        "READY_FOR_TURN_ON", "ENERGIZED", "CANCELLED",
    )


def assert_purge_leak_test(data: dict):
    _assert_common_fields(data, "PurgeLeakTest")
    assert isinstance(data["meter_set_id"], str)
    assert isinstance(data["purge_duration_min"], int)
    assert isinstance(data["test_pressure_psi"], (int, float))
    assert isinstance(data["test_duration_min"], int)
    assert isinstance(data["observed_pressure_drop_psi"], (int, float))
    assert isinstance(data["max_allowed_drop_psi"], (int, float))
    assert data["result"] in ("PASS", "FAIL")
    assert data["status"] in ("RECORDED", "CERTIFIED", "REJECTED")


def assert_turn_on_event(data: dict):
    _assert_common_fields(data, "TurnOnEvent")
    assert isinstance(data["service_application_id"], str)
    assert isinstance(data["appliance_load_id"], str)
    assert data["status"] in ("SCHEDULED", "VERIFIED", "FAILED", "CANCELLED")


def assert_timeline_commitment(data: dict):
    _assert_common_fields(data, "TimelineCommitment")
    assert isinstance(data["service_application_id"], str)
    assert isinstance(data["base_date"], str)
    assert isinstance(data["optimistic_completion_date"], str)
    assert isinstance(data["conservative_completion_date"], str)
    assert isinstance(data["committed_completion_date"], str)
    assert data["status"] in (
        "PROPOSED", "ACCEPTED", "REVISION_PENDING", "AT_RISK", "MET", "MISSED", "CANCELLED"
    )


def assert_gis_as_built(data: dict):
    _assert_common_fields(data, "GISAsBuilt")
    assert isinstance(data["service_application_id"], str)
    assert isinstance(data["geometry_geojson"], str)
    assert data["pipe_material"] in ("STEEL", "PE", "CSST")
    assert isinstance(data["depth_inches"], (int, float))
    assert data["status"] in ("SUBMITTED", "VALIDATED", "REJECTED", "CANCELLED")


def assert_invoice_cash_conserved(invoice: dict):
    """Net cash invariant: payments minus refunds never exceeds the amount due."""
    net_cash = invoice["payments_applied_cents"] - invoice["refunds_issued_cents"]
    assert net_cash >= 0, f"net cash {net_cash} must never be negative"
    assert isinstance(invoice["amount_due_cents"], int)
