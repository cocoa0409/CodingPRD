"""Entity assertions and domain invariant checkers for the Ambulance EMS Billing API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_agency(data: dict):
    assert is_valid_uuid(data.get("id", "")), "agency id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["npi"], str)
    assert isinstance(data["state_code"], str)
    assert isinstance(data["base_state_is_no_surprises"], bool)
    assert isinstance(data["charity_fpl_threshold_pct"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["version"], int)


def assert_agency_staff(data: dict):
    assert is_valid_uuid(data.get("id", "")), "staff id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["agency_id"]), "agency_id must be valid UUID"
    assert data["role"] in ("Dispatcher", "Coder", "Biller", "ComplianceOfficer")
    assert isinstance(data["pcs_signature_authority"], bool)
    assert data["status"] in ("ACTIVE", "DEACTIVATED")


def assert_payer_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "payer plan id must be valid UUID"
    assert data["payer_type"] in ("MEDICARE", "MEDICAID", "AUTO", "COMMERCIAL", "SELF_PAY")
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["allows_balance_billing"], bool)


def assert_patient(data: dict):
    assert is_valid_uuid(data.get("id", "")), "patient id must be valid UUID"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["household_size"], int)
    assert isinstance(data["coverages"], list)


def assert_vehicle(data: dict):
    assert is_valid_uuid(data.get("id", "")), "vehicle id must be valid UUID"
    assert isinstance(data["unit_call_sign"], str)
    assert isinstance(data["turnaround_minutes"], int)
    assert data["status"] in ("IN_SERVICE", "OUT_OF_SERVICE")


def assert_crew_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "crew member id must be valid UUID"
    assert data["certification"] in ("EMT", "AEMT", "PARAMEDIC")
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_unit_assignment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "unit assignment id must be valid UUID"
    assert is_valid_uuid(data["transport_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert is_valid_uuid(data["crew_member_id"])
    assert isinstance(data["window_start_iso"], str)
    assert isinstance(data["window_end_iso"], str)


def assert_transport(data: dict):
    assert is_valid_uuid(data.get("id", "")), "transport id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["agency_id"])
    assert is_valid_uuid(data["patient_id"])
    assert isinstance(data["run_number"], str)
    assert isinstance(data["loaded_miles"], (int, float))
    assert data["documentation_status"] in (
        "IMPORTED", "CODED", "NECESSITY_REVIEW", "DOCUMENTATION_COMPLETE", "RETURNED",
    )
    assert data["billing_status"] in (
        "UNBILLED", "BILLING_IN_PROGRESS", "BILLED", "PATIENT_BALANCE", "CLOSED", "VOID",
    )
    assert isinstance(data["total_billed_cents"], int)
    assert isinstance(data["total_allowed_cents"], int)
    assert isinstance(data["total_paid_cents"], int)
    assert isinstance(data["total_writeoff_cents"], int)
    assert isinstance(data["patient_responsibility_cents"], int)
    assert isinstance(data["balance_cents"], int)


def assert_charge(data: dict):
    assert is_valid_uuid(data.get("id", "")), "charge id must be valid UUID"
    assert data["charge_type"] in ("BASE_RATE", "MILEAGE")
    assert isinstance(data["hcpcs_code"], str)
    assert isinstance(data["billed_amount_cents"], int)


def assert_claim(data: dict):
    assert is_valid_uuid(data.get("id", "")), "claim id must be valid UUID"
    assert is_valid_uuid(data["transport_id"])
    assert is_valid_uuid(data["payer_plan_id"])
    assert isinstance(data["sequence_rank"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "PAID", "DENIED", "APPEALED", "CLOSED")
    assert isinstance(data["billed_amount_cents"], int)
    assert isinstance(data["allowed_amount_cents"], int)
    assert isinstance(data["paid_amount_cents"], int)


def assert_remittance_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "remittance id must be valid UUID"
    assert is_valid_uuid(data["claim_id"])
    assert data["outcome"] in ("PAID", "PARTIAL", "DENIED")


def assert_payment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "payment id must be valid UUID"
    assert is_valid_uuid(data["transport_id"])
    assert data["source"] in ("PAYER", "PATIENT")
    assert isinstance(data["amount_cents"], int)


def assert_adjustment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "adjustment id must be valid UUID"
    assert is_valid_uuid(data["transport_id"])
    assert data["adjustment_type"] in ("CHARITY", "UNCOLLECTIBLE", "BALANCE_BILLING_CAP", "GOODWILL")
    assert isinstance(data["amount_cents"], int)


def assert_transport_ledger_non_negative(data: dict):
    """Derived ledger totals floor at zero (PRD §2.6, §3.9)."""
    assert data["total_billed_cents"] >= 0
    assert data["total_paid_cents"] >= 0
    assert data["total_writeoff_cents"] >= 0
    assert data["patient_responsibility_cents"] >= 0
    assert data["balance_cents"] >= 0
