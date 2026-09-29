"""Entity assertions and domain invariant checkers for the DMC Ground Operations API."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    CancellationTier,
    CredentialStatus,
    ElementType,
    LineKind,
    ManifestEntryStatus,
    PermitStatus,
    PermitType,
    ProgramElementStatus,
    ProgramExecutionStatus,
    ProgramSettlementStatus,
    SegmentType,
    SettlementPaymentStatus,
    StaffAssignmentStatus,
    StaffMemberStatus,
    StaffRoleType,
    SupplierContractStatus,
    SupplierStatus,
    SupplierType,
    TransportSegmentStatus,
    ReconciliationLineStatus,
    VenueStatus,
    AssignmentTargetType,
)


def _values(enum_cls):
    return [member.value for member in enum_cls]


def assert_common_fields(data: dict):
    """Every persisted resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1 or above, got {data['version']}"


def assert_program(data: dict):
    assert_common_fields(data)
    assert isinstance(data["client_name"], str) and 1 <= len(data["client_name"]) <= 120
    assert isinstance(data["group_name"], str) and 1 <= len(data["group_name"]) <= 120
    assert data["guaranteed_count"] >= 1
    assert data["execution_status"] in _values(ProgramExecutionStatus)
    assert data["settlement_status"] in _values(ProgramSettlementStatus)
    assert 0.05 <= data["markup_pct"] <= 0.35
    for field in (
        "element_count",
        "open_element_count",
        "actual_attendance_total",
        "estimated_client_total_cents",
        "final_subtotal_cents",
        "disclosed_markup_cents",
        "management_fee_cents",
        "final_client_total_cents",
        "supplier_gross_payable_cents",
        "supplier_settled_cents",
        "supplier_open_payable_cents",
        "credit_note_cents",
        "seated_guest_count",
        "staffing_gap_count",
        "unseated_guest_count",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer count"
        assert data[field] >= 0, f"{field} must not be negative, got {data[field]}"


def assert_venue(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["capacity_seated"] >= 0
    assert data["capacity_reception"] >= 0
    assert data["turnover_buffer_minutes"] >= 0
    assert isinstance(data["requires_special_venue_permit"], bool)
    assert data["status"] in _values(VenueStatus)


def assert_supplier(data: dict):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["supplier_type"] in _values(SupplierType)
    assert data["insurance_liability_limit_cents"] >= 0
    assert isinstance(data["coi_verified"], bool)
    assert data["status"] in _values(SupplierStatus)


def assert_supplier_contract(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert is_valid_uuid(data["supplier_id"])
    assert data["contract_value_cents"] >= 1
    assert data["required_liability_limit_cents"] >= 0
    assert 0 <= data["deposit_pct"] <= 1
    assert data["cancellation_tier"] in _values(CancellationTier)
    assert data["status"] in _values(SupplierContractStatus)
    assert 0 <= data["round_count"] <= 3
    assert data["deposit_due_cents"] >= 0
    assert data["deposit_paid_cents"] >= 0


def assert_program_element(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert is_valid_uuid(data["supplier_id"])
    assert data["element_type"] in _values(ElementType)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["starts_at"] < data["ends_at"], "ends_at must be strictly after starts_at"
    assert data["planned_headcount"] >= 0
    assert data["guaranteed_headcount"] >= 0
    assert data["per_person_cost_cents"] >= 0
    assert isinstance(data["is_weather_dependent"], bool)
    assert data["status"] in _values(ProgramElementStatus)
    assert data["cancellation_penalty_cents"] >= 0


def assert_permit(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["element_id"])
    assert data["permit_type"] in _values(PermitType)
    assert isinstance(data["authority_name"], str) and len(data["authority_name"]) > 0
    assert data["lead_time_days_required"] >= 0
    assert data["status"] in _values(PermitStatus)
    assert data["resubmission_count"] >= 0


def assert_transport_segment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert data["segment_type"] in _values(SegmentType)
    assert isinstance(data["vehicle_code"], str) and len(data["vehicle_code"]) > 0
    assert data["depart_at"] < data["arrive_at"], "arrive_at must be strictly after depart_at"
    assert data["seat_capacity"] >= 1
    assert isinstance(data["wheelchair_accessible"], bool)
    assert data["status"] in _values(TransportSegmentStatus)
    assert 0 <= data["booked_seat_count"] <= data["seat_capacity"]


def assert_manifest_entry(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["segment_id"])
    assert isinstance(data["guest_ref"], str) and len(data["guest_ref"]) > 0
    assert isinstance(data["guest_name"], str) and len(data["guest_name"]) > 0
    assert data["seat_count"] >= 1
    assert isinstance(data["mobility_assist"], bool)
    assert data["status"] in _values(ManifestEntryStatus)
    assert data["move_count"] >= 0


def assert_staff_member(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["role_type"] in _values(StaffRoleType)
    assert data["pay_rate_cents_per_hour"] >= 0
    assert data["min_rest_minutes"] >= 0
    assert data["max_daily_minutes"] >= 0
    assert data["status"] in _values(StaffMemberStatus)
    assert data["credential_status"] in _values(CredentialStatus)
    assert data["confirmed_minutes_total"] >= 0


def assert_staff_assignment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["staff_id"])
    assert is_valid_uuid(data["program_id"])
    assert data["target_type"] in _values(AssignmentTargetType)
    assert data["role_type"] in _values(StaffRoleType)
    assert data["starts_at"] < data["ends_at"], "ends_at must be strictly after starts_at"
    assert data["status"] in _values(StaffAssignmentStatus)
    assert data["planned_labor_cost_cents"] >= 0
    assert data["actual_labor_cost_cents"] >= 0
    if data["target_type"] == "ELEMENT":
        assert data["element_id"] is not None
        assert data["segment_id"] is None
    else:
        assert data["segment_id"] is not None
        assert data["element_id"] is None


def assert_reconciliation_line(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert is_valid_uuid(data["element_id"])
    assert is_valid_uuid(data["supplier_id"])
    assert data["line_kind"] in _values(LineKind)
    assert data["status"] in _values(ReconciliationLineStatus)
    assert data["guaranteed_headcount"] >= 0
    assert data["actual_headcount"] >= 0
    assert data["billed_headcount"] >= 0
    assert data["supplier_cost_cents"] >= 0
    assert data["markup_cents"] >= 0
    assert data["variance_pct"] >= 0
    assert (
        data["client_charge_cents"] == data["supplier_cost_cents"] + data["markup_cents"]
    ), "client_charge_cents must be supplier_cost_cents plus markup_cents"


def assert_settlement_payment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert is_valid_uuid(data["supplier_id"])
    assert is_valid_uuid(data["contract_id"])
    assert data["status"] in _values(SettlementPaymentStatus)
    assert data["gross_cents"] >= 0
    assert data["deposit_applied_cents"] >= 0
    assert data["net_payable_cents"] >= 0, "net_payable_cents is floored at zero"
    assert data["overpayment_credit_cents"] >= 0


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_supplier_payable_conserved(program: dict):
    """The gross owed must always equal what is settled plus what is still open."""
    assert (
        program["supplier_gross_payable_cents"]
        == program["supplier_settled_cents"] + program["supplier_open_payable_cents"]
    ), (
        "supplier_gross_payable_cents must equal supplier_settled_cents plus "
        f"supplier_open_payable_cents; got {program['supplier_gross_payable_cents']} "
        f"vs {program['supplier_settled_cents']} + {program['supplier_open_payable_cents']}"
    )


def assert_deposit_waterfall_conserved(payment: dict, contract: dict):
    """deposit_applied_cents plus overpayment_credit_cents equals the paid deposit."""
    assert (
        payment["deposit_applied_cents"] + payment["overpayment_credit_cents"]
        == contract["deposit_paid_cents"]
    ), (
        "deposit_applied_cents plus overpayment_credit_cents must equal the contract's "
        f"deposit_paid_cents; got {payment['deposit_applied_cents']} + "
        f"{payment['overpayment_credit_cents']} vs {contract['deposit_paid_cents']}"
    )


def assert_client_total_decomposition(program: dict):
    """final_client_total_cents is subtotal + disclosed markup + management fee."""
    assert (
        program["final_client_total_cents"]
        == program["final_subtotal_cents"]
        + program["disclosed_markup_cents"]
        + program["management_fee_cents"]
    ), (
        "final_client_total_cents must equal final_subtotal_cents + "
        "disclosed_markup_cents + management_fee_cents; got "
        f"{program['final_client_total_cents']}"
    )
