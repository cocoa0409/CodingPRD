"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """Every persisted resource carries id/created_at/updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_landlord(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert isinstance(data.get("tax_id"), str) and data["tax_id"]
    assert data.get("status") in ("ACTIVE", "SUSPENDED", "TERMINATED")


def assert_property(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("landlord_id", ""))
    assert isinstance(data.get("address"), str) and data["address"]
    assert isinstance(data.get("zip_code"), str) and data["zip_code"]


def assert_unit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("property_id", ""))
    assert isinstance(data.get("unit_label"), str) and data["unit_label"]
    assert isinstance(data.get("bedroom_count"), int) and data["bedroom_count"] >= 0
    assert data.get("status") in (
        "LISTED", "UNDER_CONTRACT", "SUSPENDED_ABATEMENT", "DELISTED",
    )


def assert_voucher_family(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("family_code"), str) and data["family_code"]
    assert isinstance(data.get("voucher_bedroom_size"), int)
    assert isinstance(data.get("annual_income_cents"), int)
    assert data.get("status") in ("SEARCHING", "LEASED", "PORTED_OUT", "EXITED")


def assert_payment_standard(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("zip_code"), str) and data["zip_code"]
    assert isinstance(data.get("bedroom_count"), int)
    assert isinstance(data.get("amount_cents"), int)
    assert isinstance(data.get("effective_from"), str) and data["effective_from"]
    assert "effective_to" in data, "effective_to key must be present (null when open-ended)"


def assert_hap_contract(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("unit_id", ""))
    assert is_valid_uuid(data.get("family_id", ""))
    assert isinstance(data.get("contract_rent_cents"), int)
    assert isinstance(data.get("approved_rent_cents"), int)
    assert isinstance(data.get("hap_portion_cents"), int)
    assert isinstance(data.get("tenant_portion_cents"), int)
    assert isinstance(data.get("lease_start_date"), str) and data["lease_start_date"]
    assert data.get("status") in (
        "DRAFT", "PENDING_INSPECTION", "APPROVED", "ACTIVE", "ABATED", "TERMINATED",
    )
    assert "next_recert_due_date" in data, "next_recert_due_date key must be present"


def assert_inspection(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("contract_id", ""))
    assert data.get("inspection_type") in ("INITIAL", "ANNUAL", "REINSPECTION", "COMPLAINT")
    assert isinstance(data.get("scheduled_date"), str) and data["scheduled_date"]
    assert data.get("status") in (
        "SCHEDULED", "PASSED", "FAILED", "REPAIR_VERIFICATION", "CLOSED",
    )


def assert_repair_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("inspection_id", ""))
    assert isinstance(data.get("description"), str) and data["description"]
    assert isinstance(data.get("is_life_threatening"), bool)
    assert data.get("status") in ("OPEN", "REPAIRED", "VERIFIED", "FAILED_VERIFICATION")


def assert_rent_comparable(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("zip_code"), str) and data["zip_code"]
    assert isinstance(data.get("bedroom_count"), int)
    assert isinstance(data.get("rent_cents"), int)
    assert isinstance(data.get("survey_date"), str) and data["survey_date"]


def assert_rent_increase_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("contract_id", ""))
    assert isinstance(data.get("requested_rent_cents"), int)
    assert isinstance(data.get("effective_date"), str) and data["effective_date"]
    assert data.get("status") in ("PENDING", "APPROVED", "DENIED", "WITHDRAWN")


def assert_recertification(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("contract_id", ""))
    assert isinstance(data.get("due_date"), str) and data["due_date"]
    assert isinstance(data.get("new_family_income_cents"), int)
    assert data.get("status") in ("OPEN", "COMPLETED", "OVERDUE")


def assert_hap_payment(data: dict):
    """HAPPayment is the PRD §2.4 exception: only id and created_at are carried.

    Both updated_at and version are absent on HAPPayment rows.
    """
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert "version" not in data, "HAPPayment rows must not carry a version field (PRD §2.4)"
    assert "updated_at" not in data, "HAPPayment rows must not carry updated_at (PRD §2.4)"
    assert is_valid_uuid(data.get("contract_id", ""))
    assert isinstance(data.get("period_month"), str) and data["period_month"]
    assert isinstance(data.get("hap_amount_cents"), int)
    assert data.get("disbursement_status") in ("SCHEDULED", "PAID", "ABATED_HELD", "VOID")


def assert_portability_action(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("family_id", ""))
    assert isinstance(data.get("destination_zip"), str) and data["destination_zip"]
    assert data.get("action_type") in ("PORT_IN", "PORT_OUT")
    assert data.get("status") in ("INITIATED", "BILLING_ACCEPTED", "ABSORBED", "TERMINATED")


def assert_contract_portion_invariants(data: dict):
    """Domain invariants that must hold on any HAPContract read (PRD §3.2)."""
    assert data["tenant_portion_cents"] >= 0
    assert data["hap_portion_cents"] >= 0
    assert data["tenant_portion_cents"] + data["hap_portion_cents"] == data["approved_rent_cents"], (
        "tenant + HAP portions must sum to the approved rent"
    )
    assert data["tenant_portion_cents"] <= data["approved_rent_cents"]
