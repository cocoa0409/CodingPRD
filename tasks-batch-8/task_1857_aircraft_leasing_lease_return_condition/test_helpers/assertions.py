"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity_label: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be a positive integer, got {data.get('version')!r}"
    )


def assert_aircraft(data: dict):
    _assert_common(data, "Aircraft")
    assert isinstance(data["msn"], str) and data["msn"]
    assert isinstance(data["model"], str) and data["model"]
    assert isinstance(data["manufacture_date"], str) and data["manufacture_date"]
    assert data["status"] in ["AVAILABLE", "ON_LEASE", "IN_TRANSITION", "REPOSSESSED"]
    assert isinstance(data["total_flight_hours"], (int, float))
    assert isinstance(data["total_flight_cycles"], int)


def assert_lessee(data: dict):
    _assert_common(data, "Lessee")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["credit_tier"] in ["A", "B", "C"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_inspector(data: dict):
    _assert_common(data, "Inspector")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]


def assert_lease(data: dict):
    _assert_common(data, "Lease")
    assert is_valid_uuid(data.get("aircraft_id", "")), "Lease.aircraft_id must be a UUID"
    assert is_valid_uuid(data.get("lessee_id", "")), "Lease.lessee_id must be a UUID"
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["monthly_rent_cents"], int) and data["monthly_rent_cents"] > 0
    assert isinstance(data["reserve_rate_per_fh_cents"], int) and data["reserve_rate_per_fh_cents"] >= 0
    assert isinstance(data["reserve_rate_per_fc_cents"], int) and data["reserve_rate_per_fc_cents"] >= 0
    assert isinstance(data["monthly_hour_cap"], int) and data["monthly_hour_cap"] > 0
    assert data["accrual_basis"] in ["ACTUAL", "MINIMUM_GUARANTEE"]
    assert data["status"] in [
        "DRAFT", "ACTIVE", "RETURN_INITIATED", "RETURNED", "CLOSED", "DEFAULTED", "TERMINATED",
    ]
    for field in ("reserve_accrued_cents", "reserve_reimbursed_cents", "reserve_forfeited_cents", "reserve_balance_cents"):
        assert isinstance(data[field], int), f"Lease.{field} must be integer cents"


def assert_lease_reserve_invariants(lease: dict):
    """The reserve-ledger invariant must hold after every operation."""
    expected = (
        lease["reserve_accrued_cents"]
        - lease["reserve_reimbursed_cents"]
        - lease["reserve_forfeited_cents"]
    )
    assert lease["reserve_balance_cents"] == expected, (
        f"reserve_balance_cents {lease['reserve_balance_cents']} != "
        f"accrued {lease['reserve_accrued_cents']} - reimbursed {lease['reserve_reimbursed_cents']} "
        f"- forfeited {lease['reserve_forfeited_cents']} (= {expected})"
    )


def assert_utilization_report(data: dict):
    _assert_common(data, "UtilizationReport")
    assert is_valid_uuid(data.get("lease_id", "")), "UtilizationReport.lease_id must be a UUID"
    assert isinstance(data["period_month"], str) and len(data["period_month"]) == 7
    assert isinstance(data["flight_hours"], (int, float)) and data["flight_hours"] >= 0
    assert isinstance(data["flight_cycles"], int) and data["flight_cycles"] >= 0
    assert data["status"] in ["SUBMITTED", "ACCEPTED", "DISPUTED", "VOIDED"]
    assert isinstance(data["posted_accrual_cents"], int)


def assert_reserve_claim(data: dict):
    _assert_common(data, "ReserveClaim")
    assert is_valid_uuid(data.get("lease_id", "")), "ReserveClaim.lease_id must be a UUID"
    assert isinstance(data["maintenance_event_ref"], str)
    assert isinstance(data["claimed_amount_cents"], int) and data["claimed_amount_cents"] > 0
    assert data["status"] in ["SUBMITTED", "APPROVED", "REJECTED", "PAID"]


def assert_aircraft_document(data: dict):
    _assert_common(data, "AircraftDocument")
    assert is_valid_uuid(data.get("aircraft_id", "")), "AircraftDocument.aircraft_id must be a UUID"
    assert data["doc_type"] in ["BIRTH_RECORD", "AIRWORTHINESS_CERT", "ENGINE_LOG", "LLP_STATUS", "OTHER"]
    assert isinstance(data["doc_reference"], str)
    assert data["status"] in ["SUBMITTED", "VERIFIED", "REJECTED"]


def assert_return_case(data: dict):
    _assert_common(data, "ReturnCase")
    assert is_valid_uuid(data.get("lease_id", "")), "ReturnCase.lease_id must be a UUID"
    assert data["status"] in [
        "OPEN", "RECORDS_VERIFIED", "INSPECTION", "NEGOTIATION", "AGREED", "SETTLED", "CANCELLED",
    ]
    assert isinstance(data["round_count"], int) and data["round_count"] >= 0
    assert isinstance(data["reinspection_count"], int) and data["reinspection_count"] >= 0
    assert isinstance(data["provisional_estimate_cents"], int)


def assert_checklist_item(data: dict):
    _assert_common(data, "ChecklistItem")
    assert is_valid_uuid(data.get("return_case_id", "")), "ChecklistItem.return_case_id must be a UUID"
    assert data["item_code"] in ["AIRFRAME", "ENGINE", "INTERIOR", "PAINT"]
    assert data["severity"] in ["CRITICAL", "MAJOR", "MINOR"]
    assert data["status"] in ["PENDING", "COMPLIANT", "NON_COMPLIANT", "RECTIFIED", "WAIVED", "COMPENSATED"]


def assert_inspection_booking(data: dict):
    # Scheduling record: id + created_at only; updated_at and version absent.
    assert is_valid_uuid(data.get("id", "")), "InspectionBooking.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "InspectionBooking.created_at must be ISO 8601"
    assert "updated_at" not in data, "InspectionBooking must not carry updated_at"
    assert "version" not in data, "InspectionBooking must not carry version"
    assert is_valid_uuid(data.get("return_case_id", "")), "InspectionBooking.return_case_id must be a UUID"
    assert is_valid_uuid(data.get("inspector_id", "")), "InspectionBooking.inspector_id must be a UUID"
    assert isinstance(data["booking_date"], str)


def assert_novation_request(data: dict):
    _assert_common(data, "NovationRequest")
    assert is_valid_uuid(data.get("lease_id", "")), "NovationRequest.lease_id must be a UUID"
    assert data["request_type"] in ["NOVATION", "SUBLEASE"]
    assert is_valid_uuid(data.get("proposed_lessee_id", "")), "NovationRequest.proposed_lessee_id must be a UUID"
    assert data["status"] in ["SUBMITTED", "CREDIT_APPROVED", "APPROVED", "REJECTED"]


def assert_default_case(data: dict):
    _assert_common(data, "DefaultCase")
    assert is_valid_uuid(data.get("lease_id", "")), "DefaultCase.lease_id must be a UUID"
    assert isinstance(data["reason"], str)
    assert isinstance(data["cure_period_days"], int) and data["cure_period_days"] >= 0
    assert is_iso8601_timestamp(data.get("declared_at", "")), "DefaultCase.declared_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("cure_deadline", "")), "DefaultCase.cure_deadline must be ISO 8601"
    assert isinstance(data["declared_by"], str) and data["declared_by"]
    assert data["status"] in ["DECLARED", "CURED", "REPOSSESSION_AUTHORIZED", "REPOSSESSED"]


def assert_transition_slot(data: dict):
    _assert_common(data, "TransitionSlot")
    assert is_valid_uuid(data.get("aircraft_id", "")), "TransitionSlot.aircraft_id must be a UUID"
    assert isinstance(data["window_start"], str)
    assert isinstance(data["window_end"], str)
    assert data["status"] in ["TENTATIVE", "CONFIRMED", "COMPLETED", "RELEASED"]
