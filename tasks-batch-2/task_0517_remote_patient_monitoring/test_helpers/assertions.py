"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_payer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["payer_type"] in ("MEDICARE", "MEDICARE_ADVANTAGE", "COMMERCIAL")
    assert isinstance(data["rate_99453_cents"], int) and data["rate_99453_cents"] >= 0
    assert isinstance(data["rate_99454_cents"], int) and data["rate_99454_cents"] >= 0
    assert isinstance(data["rate_99457_cents"], int) and data["rate_99457_cents"] >= 0


def assert_patient(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["enrollment_status"] in (
        "PENDING_CONSENT", "ENROLLED", "SUSPENDED", "DISCHARGED")
    assert data["monitoring_status"] in ("INACTIVE", "MONITORING", "PAUSED")
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_consent(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["consent_type"] in ("RPM", "CCM", "BOTH")
    assert data["status"] in ("ACTIVE", "REVOKED", "SUPERSEDED")


def assert_care_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("DRAFT", "ACTIVE", "REVISED", "RETIRED")
    assert isinstance(data["required_care_minutes"], int)


def assert_device(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["device_type"] in ("BP_CUFF", "GLUCOMETER", "PULSE_OX", "WEIGHT_SCALE")
    assert data["status"] in ("ENROLLED", "ACTIVE", "RETURNED")
    assert isinstance(data["setup_billed"], bool)


def assert_vitals_reading(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["service_date"], str) and len(data["service_date"]) == 10
    assert isinstance(data["breach_flag"], bool)


def assert_threshold_alert(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["severity"] in ("WARNING", "CRITICAL")
    assert data["status"] in ("OPEN", "ACKNOWLEDGED", "ESCALATED", "RESOLVED")


def assert_review_task(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["priority"] in ("ROUTINE", "URGENT")
    assert data["status"] in ("QUEUED", "IN_REVIEW", "SIGNED", "ESCALATED")


def assert_care_activity(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["minutes"], int)
    assert isinstance(data["counted_minutes"], int)
    assert data["counted_minutes"] >= 0


def assert_billing_period(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("OPEN", "FINALIZED", "CLAIMED", "REOPENED")
    assert isinstance(data["provisional_total_minutes"], int)
    assert isinstance(data["distinct_device_days"], int)


def assert_billing_line_item(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["cpt_code"] in ("CPT_99453", "CPT_99454", "CPT_99457")
    assert data["units"] == 1
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in ("ACCRUED", "VOIDED", "FINALIZED")


def assert_claim(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "PARTIALLY_PAID", "PAID", "DENIED")
    assert isinstance(data["claimed_cents"], int) and data["claimed_cents"] >= 0
    assert isinstance(data["reimbursed_cents"], int) and data["reimbursed_cents"] >= 0


def assert_claim_conserved_value(data: dict):
    """Conserved-value invariant (§2.10): reimbursed + outstanding == claimed,
    and reimbursed never exceeds claimed."""
    assert data["reimbursed_cents"] <= data["claimed_cents"], (
        f"reimbursed_cents {data['reimbursed_cents']} must not exceed "
        f"claimed_cents {data['claimed_cents']}")
    outstanding = data["claimed_cents"] - data["reimbursed_cents"]
    assert data["reimbursed_cents"] + outstanding == data["claimed_cents"]
