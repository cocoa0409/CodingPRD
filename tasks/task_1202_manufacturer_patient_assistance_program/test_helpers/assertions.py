"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data, with_version=True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, "version starts at 1"


def assert_program(data: dict):
    _assert_common(data)
    assert data["posture"] in ["OPEN", "RESTRICTED", "EXHAUSTED"]
    for field in ("total_allocated_cents", "total_committed_cents", "total_disbursed_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be a non-negative integer"
    for field in ("max_units_per_enrollment", "max_units_per_shipment", "max_annual_benefit_cents",
                  "enrollment_duration_days", "screening_validity_days", "appeal_window_days",
                  "renewal_window_days", "lot_expiry_buffer_days"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["name"], str) and isinstance(data["product_name"], str)
    assert isinstance(data["unit_cost_per_unit"], str)
    assert isinstance(data["allow_patient_direct_shipment"], bool)


def assert_budget_period(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "CLOSED"]
    assert isinstance(data["program_id"], str)
    assert isinstance(data["allocated_cents"], int) and data["allocated_cents"] >= 0
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["disbursed_cents"], int)


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2


def assert_prescriber(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["npi_number"], str) and len(data["npi_number"]) > 0
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2


def assert_screening(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "VERIFIED", "REJECTED", "STALE"]
    assert data["income_basis"] in ["YTD_ANNUALIZED", "PRIOR_YEAR"]
    assert data["insurance_status"] in ["UNINSURED", "UNDERINSURED", "INSURED_COMMERCIAL", "MEDICARE", "MEDICAID"]
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert isinstance(data["annualized_income_cents"], int)
    assert isinstance(data["fpl_limit_cents"], int)
    assert isinstance(data["fpl_percent"], str)
    assert data.get("eligibility_determination") in [None, "ELIGIBLE", "INELIGIBLE"]


def assert_document(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "ACCEPTED", "REJECTED"]
    assert data["doc_type"] in ["PROOF_OF_INCOME", "IDENTITY", "INSURANCE_VERIFICATION", "OTHER"]
    assert isinstance(data["screening_id"], str)
    assert isinstance(data["file_reference"], str)


def assert_application(data: dict):
    _assert_common(data)
    assert data["status"] in ["SUBMITTED", "UNDER_REVIEW", "MORE_INFO_REQUESTED", "APPROVED", "DENIED", "SUPERSEDED"]
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["screening_id"], str)


def assert_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "TERMINATED", "EXPIRED", "CLOSED_RENEWED"]
    assert isinstance(data["benefit_cap_cents"], int)
    assert isinstance(data["cap_units"], int)
    assert isinstance(data["disbursed_cents"], int)
    assert isinstance(data["remaining_units"], int)
    assert isinstance(data["start_date"], str) and isinstance(data["end_date"], str)


def assert_circumstance(data: dict):
    _assert_common(data)
    assert data["status"] in ["REPORTED", "APPLIED", "DISMISSED"]
    assert data["circumstance_type"] in ["INCOME_CHANGE", "INSURANCE_CHANGE", "HOUSEHOLD_CHANGE"]
    assert isinstance(data["enrollment_id"], str)


def assert_appeal(data: dict):
    _assert_common(data)
    assert data["status"] in ["FILED", "UPHELD", "OVERTURNED"]
    assert isinstance(data["application_id"], str)
    assert isinstance(data["grounds"], str) and len(data["grounds"]) > 0


def assert_copay_card(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "TERMINATED"]
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["coverage_start"], str) and isinstance(data["coverage_end"], str)


def assert_lot(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "QUARANTINED", "EXPIRED", "UNDER_INVESTIGATION"]
    assert isinstance(data["lot_number"], str)
    for field in ("quantity_received", "quantity_on_hand", "quantity_reserved",
                  "quantity_shipped", "quantity_dispensed", "quantity_quarantined"):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be a non-negative integer"


def assert_lot_units_conserved(data: dict):
    """PRD §3.7: on-hand is always what remains after subtracting reserved,
    shipped, dispensed, and quarantined units from what was received."""
    assert (
        data["quantity_on_hand"]
        + data["quantity_reserved"]
        + data["quantity_shipped"]
        + data["quantity_dispensed"]
        + data["quantity_quarantined"]
        == data["quantity_received"]
    ), f"lot {data.get('id')} unit buckets do not conserve received quantity"


def assert_shipment(data: dict):
    _assert_common(data)
    assert data["status"] in ["RESERVED", "DISPATCHED", "DELIVERED", "CANCELLED", "RETURNED"]
    assert data["destination"] in ["PROVIDER", "PATIENT"]
    assert isinstance(data["enrollment_id"], str)
    assert isinstance(data["quantity_units"], int) and data["quantity_units"] >= 1
    assert isinstance(data["value_cents"], int)
    assert isinstance(data["dispensed_value_cents"], int)


def assert_shipment_line(data: dict):
    _assert_common(data)
    assert isinstance(data["shipment_id"], str)
    assert isinstance(data["lot_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["value_cents"], int)
    assert isinstance(data["dispensed_quantity"], int)


def assert_dispense_event(data: dict):
    # PRD §2.4: DispenseEvent is the immutable audit record — only id and
    # created_at of the common fields; updated_at and version are absent.
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "DispenseEvent must not carry updated_at"
    assert "version" not in data, "DispenseEvent must not carry version"
    assert isinstance(data["shipment_id"], str)
    assert isinstance(data["lot_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["value_cents"], int)
    assert isinstance(data["dispenser_id"], str)


def assert_reconciliation_run(data: dict):
    _assert_common(data)
    assert data["status"] in ["CLEAN", "VARIANCE_FLAGGED"]
    assert isinstance(data["program_id"], str)
    assert isinstance(data["budget_period_id"], str)
    assert isinstance(data["lines"], list)
    for line in data["lines"]:
        assert isinstance(line["lot_id"], str)
        for field in ("book_on_hand", "actual_on_hand", "variance_units", "variance_value_cents"):
            assert isinstance(line[field], int), f"line.{field} must be an integer"


def assert_program_budget_conserved(utilization: dict):
    """PRD §2.11: allocated equals committed plus disbursed plus unallocated
    available funds at all times."""
    allocated = utilization["allocated_cents"]
    committed = utilization["committed_cents"]
    disbursed = utilization["disbursed_cents"]
    assert committed >= 0 and disbursed >= 0
    assert committed + disbursed <= allocated, (
        f"committed ({committed}) + disbursed ({disbursed}) exceeds allocated ({allocated})"
    )
